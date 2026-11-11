"""Hesap yedekleme: kota bitince aynı servisin sıradaki hesabına geçiş, sağlık kontrolü.

Havuz, bu çalışmada tükenen hesapları (`elenen`) ve sağlık kontrolü önbelleğini
(`saglik`) taşır; hesapları API hesapları deposundan okur.

İki eleme katmanı vardır:
* `elenen` yalnızca **bu çalışma** içindir; her çalışma başında ve her yeniden denemede
  boşaltılır (geçici sorun yaşayan hesap sonra yeniden denensin).
* `kota` (bkz. `kota_listesi`) diske yazılır: **kesin günlük kotası** biten Hugging Face
  ve Cloudflare hesapları, kota yenilenene kadar hiçbir çalışmada kullanılmaz.
`hesap_elendi` ikisine birden bakar; hesapları dolaşan her yer bu yüzden ikisine uyar.
"""
import threading
import time
from contextlib import contextmanager

import requests

from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek.cloudflare_http import CF_API, cf_verify_urls
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir, metin as _metin
from studioflow.saglayicilar import kota_listesi


def aktif_anahtar(hizmet, alan):
    return api_hesaplari.VARSAYILAN.aktif_deger(hizmet, alan)


def aktif_kimlik(hizmet):
    """Servisin aktif hesabındaki **bütün** alanlar.

    Tek alanlı servisler için `aktif_anahtar` yeterliydi; Cloudflare iki alan
    istediği için metin yapay zekâsı kimliği hep buradan okunur.
    """
    return api_hesaplari.VARSAYILAN.aktif_degerler(hizmet)


KAYITSIZ = "kayıt yok"


# Kota/yetki dışı (geçici) hatada hesap kaç denemede elenir: ilk hata hesabı yakmaz,
# aynı hesap üst üste bu kadar kez yanıt veremezse sıradan çıkarılır.
GECICI_HATA_SINIRI = 2


SAGLIK_SANIYE = 60                 # başarılı sağlık kontrolü bu süre önbellekte kalır


HIZMET_ADI = {"huggingface": "Hugging Face", "gemini": "Gemini", "openai": "ChatGPT",
                  "anthropic": "Claude", "cloudflare": "Cloudflare Workers AI", "evren": "EVREN",
                  "agnes": "Agnes AI", "tavily": "Tavily", "exa": "Exa", "jina": "Jina Reader",
                  "youtube": "YouTube Data API", "apify": "Apify"}


# Seslendirme sağlayıcısı hangi hizmetin hesaplarıyla dönecek? Edge anahtarsız çalışır.
SES_HIZMET = {"gemini": "gemini", "chatterbox": "huggingface"}


def hesap_adi(kayit):
    return KAYITSIZ if kayit["ad"] == KAYITSIZ else f"'{kayit['ad']}'"


def _durum(ok, kod, etiket, ek=""):
    """HTTP sonucunu sağlık durumuna çevir."""
    if ok:
        return "tamam", f"{etiket} çalışıyor{' ' + ek if ek else ''}"
    if kod in (401, 403):
        return "bozuk", f"{etiket} reddedildi (HTTP {kod})"
    if kod == 429:
        # Ücretsiz sorguda 429 çoğunlukla dakikalık hız sınırıdır: hesap elenmez,
        # gerçek işlem hatayı verirse orada ayırt edilir (bkz. `dakikalik_bekleme`).
        return "bilinmiyor", f"{etiket} hız/kota sınırında (HTTP 429)"
    if kod == 402:
        return "bozuk", f"{etiket} için bakiye/kota yok (HTTP 402)"
    return "bilinmiyor", f"{etiket} doğrulanamadı (HTTP {kod})"


class HesapHavuzu:
    """Hizmet başına hesap sırası, sağlık kontrolü ve eleme."""

    def __init__(self, hesaplar=None, kota=None):
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.kota = kota or kota_listesi.VARSAYILAN
        self.elenen = set()
        # Hesap başına **geçici** hata sayacı: kota/yetki dışı hatalar burada birikir.
        self.hatalar = {}        # {(hizmet, hesap adı)} bu çalışmada tükenenler
        self.saglik = {}           # {(hizmet, ad, değer): (zaman, (durum, mesaj))}
        # Çoklu üretimde her iş parçacığı **yalnızca kendi hesaplarıyla** çalışır
        # (bkz. `hesaplari_sabitle`); diğer iş parçacıklarının sırası etkilenmez.
        self._yerel = threading.local()

    def _sabit(self, hizmet):
        """Bu iş parçacığına sabitlenmiş hesap adları (yoksa `None`)."""
        return (getattr(self._yerel, "sabit", None) or {}).get(hizmet)

    @contextmanager
    def hesaplari_sabitle(self, hizmet, adlar):
        """Bu iş parçacığında hizmetin hesap sırasını **yalnızca** `adlar` yap.

        Çoklu üretimde her grup kendi asıl hesabıyla, kotası biterse kendi yedeğiyle
        çalışır; başka grubun hesabına geçmez. Sabitken çalışan hesap uygulamanın aktif
        hesabı yapılmaz: paralel gruplar ★ işaretini birbirinden kapmasın.
        """
        onceki = dict(getattr(self._yerel, "sabit", None) or {})
        self._yerel.sabit = {**onceki, hizmet: [ad for ad in adlar if ad]}
        try:
            yield
        finally:
            self._yerel.sabit = onceki

    def _hesap_kilit(self, hizmet, kayit):
        return (hizmet, kayit["ad"], repr(sorted(kayit["degerler"].items())))

    def hesap_listesi(self, hizmet):
        """Hizmetin hesaplarını **aktif olandan başlayarak** sırala.

        Her kayıt: `{"ad": hesap adı, "degerler": {alan: değer}}`. Hiç hesap yoksa tek
        bir "kayıt yok" kaydı döner; anahtarsız çalışabilen hizmetler (anonim Hugging
        Face) böylece anonim olarak denenir. İş parçacığına hesap sabitlenmişse
        (`hesaplari_sabitle`) yalnızca o hesaplar, verilen sırayla döner.
        """
        sabit = self._sabit(hizmet)
        if sabit is not None:
            return [{"ad": ad, "degerler": self.hesaplar.hesap_degerleri(hizmet, ad)}
                    for ad in sabit]
        try:
            adlar = self.hesaplar.hesap_adlari(hizmet)
            aktif = self.hesaplar.aktif_hesap(hizmet)
        except Exception:
            adlar, aktif = [], ""
        sirali = ([aktif] if aktif in adlar else []) + [ad for ad in adlar if ad != aktif]
        kayitlar = [{"ad": ad, "degerler": self.hesaplar.hesap_degerleri(hizmet, ad)}
                    for ad in sirali]
        return kayitlar or [{"ad": KAYITSIZ, "degerler": {}}]

    def hesap_kimligi(self, veri, hizmet=None, kayit=None):
        """İşlem için gereken bütün anahtarları topla.

        Denenen hesap varsa o hizmetin alanları o hesaptan, geri kalanı kendi aktif
        hesabından okunur.
        """
        degerler = dict(kayit["degerler"]) if kayit else {}

        def al(servis, alan):
            if hizmet == servis:
                return _metin(degerler.get(alan))
            return aktif_anahtar(servis, alan)

        return {"gemini_key": al("gemini", "gemini_key"),
                "hf_token": al("huggingface", "hf_token"),
                "cf_account_id": al("cloudflare", "cf_account_id"),
                "cf_token": al("cloudflare", "cf_token"),
                "openai_key": al("openai", "openai_key"),
                "anthropic_key": al("anthropic", "anthropic_key"),
                "evren_key": al("evren", "evren_key")}

    def _saglik_istegi(self, hizmet, kayit):
        """Hesabı küçük ve ücretsiz bir istekle doğrula.

        Üretim yapılmaz, kota harcanmaz. Sonuç kesin değilse (\"bilinmiyor\") akış
        durdurulmaz; gerçek işlem zaten hatayı kendisi verir ve hesap orada elenir.
        """
        deger = kayit["degerler"]
        if hizmet == "huggingface":
            token = _metin(deger.get("hf_token"))
            if not token:
                return "bilinmiyor", "token kayıtlı değil (anonim kotayla denenir)"
            yanit = requests.get("https://huggingface.co/api/whoami-v2",
                                 headers={"Authorization": f"Bearer {token}"}, timeout=20)
            return _durum(yanit.ok, yanit.status_code, "Hugging Face token'ı")
        if hizmet == "cloudflare":
            token = _metin(deger.get("cf_token"))
            if not token or not _metin(deger.get("cf_account_id")):
                return "bozuk", "Account ID ya da token eksik"
            # Kullanıcı (`cfut_`) ve hesaba ait (`cfat_`) token'lar farklı adreste
            # doğrulanır (bkz. `cf_verify_urls`); biri 401 verirse öbürü denenir.
            for adres in cf_verify_urls(deger.get("cf_account_id")):
                yanit = requests.get(adres, headers={"Authorization": f"Bearer {token}"},
                                     timeout=20)
                if yanit.status_code != 401:
                    break
            return _durum(yanit.ok, yanit.status_code, "Cloudflare token'ı")
        if hizmet == "gemini":
            anahtar = _metin(deger.get("gemini_key"))
            if not anahtar:
                return "bozuk", "Gemini anahtarı kayıtlı değil"
            yanit = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                 headers={"x-goog-api-key": anahtar}, timeout=20)
            return _durum(yanit.ok, yanit.status_code, "Gemini anahtarı")
        if hizmet == "openai":
            anahtar = _metin(deger.get("openai_key"))
            if not anahtar:
                return "bozuk", "OpenAI anahtarı kayıtlı değil"
            yanit = requests.get("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {anahtar}"}, timeout=20)
            return _durum(yanit.ok, yanit.status_code, "OpenAI anahtarı")
        if hizmet == "anthropic":
            anahtar = _metin(deger.get("anthropic_key"))
            if not anahtar:
                return "bozuk", "Anthropic anahtarı kayıtlı değil"
            yanit = requests.get("https://api.anthropic.com/v1/models",
                                 headers={"x-api-key": anahtar, "anthropic-version": "2023-06-01"},
                                 timeout=20)
            return _durum(yanit.ok, yanit.status_code, "Anthropic anahtarı")
        if hizmet == "evren":
            anahtar = _metin(deger.get("evren_key"))
            if not anahtar:
                return "bozuk", "EVREN anahtarı kayıtlı değil"
            # Şart onayı durumu: onaylanmamış hesap her üretim isteğinde 403 alır.
            yanit = requests.get("https://evren-llmapi.ssyz.org.tr/v1/terms/status",
                                 headers={"Authorization": f"Bearer {anahtar}"}, timeout=20)
            if yanit.ok and not (yanit.json() or {}).get("accepted"):
                return "bozuk", ("EVREN kullanım şartları onaylanmamış; evren.ssyz.org.tr "
                                 "panelinden onayla")
            return _durum(yanit.ok, yanit.status_code, "EVREN anahtarı")
        return "bilinmiyor", "bu hizmet için kontrol yok"

    def saglik_kontrol(self, hizmet, kayit):
        """Hesabı doğrula. Sonuç kısa süre önbellekte tutulur: `("tamam"|"bozuk"|"bilinmiyor", mesaj)`."""
        # Anahtarlar yalnızca ASCII'dir. 14.10.2026: 'apple' HF token'ında iki Türkçe "ı"
        # vardı; istek başlığa yazılamadığı için kontrol "bilinmiyor" döndü, hesap elenmedi
        # ve her video "'ascii' codec can't encode" ile düşüp adımın hakkını yaktı.
        for alan, deger in (kayit.get("degerler") or {}).items():
            yanlis = sorted({c for c in str(deger or "") if ord(c) > 127})
            if yanlis:
                return ("bozuk", f"{alan} içinde geçersiz karakter ({' '.join(yanlis)}); "
                                 "anahtarı API hesapları sekmesine yeniden yapıştır")
        kilit = self._hesap_kilit(hizmet, kayit)
        simdi = time.time()
        onbellek = self.saglik.get(kilit)
        if onbellek and simdi - onbellek[0] < SAGLIK_SANIYE:
            return onbellek[1]
        try:
            sonuc = self._saglik_istegi(hizmet, kayit)
        except Exception as hata:
            sonuc = "bilinmiyor", _ilk_satir(hata, 120)
        if sonuc[0] == "tamam":
            self.saglik[kilit] = (simdi, sonuc)
        return sonuc

    def hesap_ele(self, hizmet, kayit, mesaj):
        """Hesabı bu çalışma boyunca elenmiş say ve önbelleğini düşür.

        Mesaj kesin günlük kotaysa hesap kalıcı kota listesine de girer.
        """
        self.elenen.add((hizmet, kayit["ad"]))
        self.saglik.pop(self._hesap_kilit(hizmet, kayit), None)
        if kayit["ad"] != KAYITSIZ:
            self.kota.kaydet(hizmet, kayit, mesaj)
        return mesaj

    def kota_uyarisi(self, hizmet, kayit, mesaj):
        """Hesap elenmeden kota uyarısı verdi (ör. dakikalık hız sınırı): listeye yaz.

        Kural (21.10.2026): kota uyarısı veren her hesap listede görünür; açılış zamanı
        uyarının kendi bekleme süresidir, süre dolunca kendiliğinden düşer.
        """
        if kayit.get("ad") not in (None, KAYITSIZ):
            self.kota.kaydet(hizmet, kayit, mesaj)

    def hesap_hatasi(self, hizmet, kayit):
        """Hesabın **geçici** hata sayacını artır ve yeni değeri döndür.

        Kota ve yetki dışındaki hatalar (503, boş yanıt, kopan bağlantı) hesabın
        kendisiyle ilgili değildir: servis o an sallanıyordur. Tek hatada hesabı
        elemek, çalışan hesapları birer birer yakıp "hepsinin kotası bitti" gibi
        görünmesine yol açıyordu. Bu yüzden geçici hata **sayılır**; hesap ancak
        üst üste `GECICI_HATA_SINIRI` kez yanıt veremezse elenir.
        """
        kilit = (hizmet, kayit["ad"])
        self.hatalar[kilit] = self.hatalar.get(kilit, 0) + 1
        return self.hatalar[kilit]

    def hesap_basarisi(self, hizmet, kayit):
        """Hesap yanıt verdi: geçici hata sayacını sıfırla."""
        self.hatalar.pop((hizmet, kayit["ad"]), None)

    def hesap_elendi(self, hizmet, kayit):
        """Bu çalışmada elendi mi, ya da kotası yenilenmeyi mi bekliyor?"""
        return (hizmet, kayit["ad"]) in self.elenen or self.kota_bekliyor(hizmet, kayit) is not None

    def kota_bekliyor(self, hizmet, kayit):
        """Hesap kalıcı kota listesindeyse açılış anı (UTC), değilse None."""
        if kayit.get("ad") in (None, KAYITSIZ):
            return None
        return self.kota.bekliyor(hizmet, kayit)

    def hesap_aktif_yap(self, hizmet, kayit):
        """Çalışan hesabı uygulamanın da aktif hesabı yap (★ API hesapları sekmesinde görünür).

        Zaten aktifse `False` döner, böylece günlüğe gereksiz satır düşmez.
        """
        if (kayit["ad"] == KAYITSIZ or self._sabit(hizmet) is not None
                or kayit["ad"] == self.hesaplar.aktif_hesap(hizmet)):
            return False
        try:
            self.hesaplar.hesap_sec(hizmet, kayit["ad"])
            return True
        except Exception:
            return False


# Uygulamanın paylaşılan havuzu; eski adlar aynı nesnelere bağlıdır.
VARSAYILAN = HesapHavuzu()
ELENEN = VARSAYILAN.elenen
_SAGLIK = VARSAYILAN.saglik
_hesap_kilit = VARSAYILAN._hesap_kilit
hesap_listesi = VARSAYILAN.hesap_listesi
hesap_kimligi = VARSAYILAN.hesap_kimligi
_saglik_istegi = VARSAYILAN._saglik_istegi
saglik_kontrol = VARSAYILAN.saglik_kontrol
hesap_ele = VARSAYILAN.hesap_ele
hesap_hatasi = VARSAYILAN.hesap_hatasi
hesap_basarisi = VARSAYILAN.hesap_basarisi
hesap_elendi = VARSAYILAN.hesap_elendi
kota_bekliyor = VARSAYILAN.kota_bekliyor
hesap_aktif_yap = VARSAYILAN.hesap_aktif_yap
hesaplari_sabitle = VARSAYILAN.hesaplari_sabitle
