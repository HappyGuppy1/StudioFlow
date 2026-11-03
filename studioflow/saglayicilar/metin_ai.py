"""Metin yapay zekâsı havuzu: seçili servis + anahtarı kayıtlı yedekler.

Kota, yetki, model ya da bağlantı hatası alan servis bırakılmaz: sıradaki servis
(Cloudflare → Gemini → EVREN → ChatGPT → Claude) kendiliğinden denenir ve işlem kaldığı
yerden sürer.
"""
import time

from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek.hatalar import dakikalik_bekleme, hata_etiketle
from studioflow.saglayicilar import kota_listesi
from studioflow.saglayicilar.metin_anthropic import AnthropicMetin
from studioflow.saglayicilar.metin_cloudflare import CloudflareMetin
from studioflow.saglayicilar.metin_evren import EvrenMetin
from studioflow.saglayicilar.metin_gemini import GeminiMetin
from studioflow.saglayicilar.metin_openai import OpenAIMetin
from studioflow.saglayicilar.metin_ortak import (AI_SAGLAYICILAR, AI_YEDEK_SIRA, EN_IYI_MODELLER,
                                                 ai_anahtari, baglanti_hatasi, kisa)


class MetinAIHavuzu:
    """Servisleri sırayla deneyen havuz; sağlayıcılar ve hesap deposu değiştirilebilir."""

    def __init__(self, saglayicilar=None, hesaplar=None):
        self.saglayicilar = saglayicilar or {"cloudflare": CloudflareMetin(),
                                             "gemini": GeminiMetin(), "evren": EvrenMetin(),
                                             "openai": OpenAIMetin(),
                                             "anthropic": AnthropicMetin()}
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN

    def _kayitli_anahtar(self, servis):
        """Servisin aktif hesabındaki anahtar; kayıt yoksa boş metin.

        Prompt üretimi anahtarları çağırandan alsa da yedek servislerin anahtarları API
        hesapları dosyasından (`self.hesaplar`) okunur. Servisin kaç alan istediğini
        `ai_anahtari` bilir: Cloudflare iki alanlıdır (Account ID + token).
        """
        try:
            return ai_anahtari(servis, self.hesaplar.aktif_degerler(servis))
        except Exception:
            return ""

    def adaylar(self, provider, anahtar, model):
        """Denenecek servisler: seçili servis **önce**, sonra anahtarı kayıtlı yedekler.

        Her aday `{"provider", "label", "key", "model"}` sözlüğüdür. Seçili serviste
        kullanıcının seçtiği model korunur; yedek serviste kendi model listesinin ilki
        kullanılır (model adları servisler arasında taşınamaz). Anahtarı kayıtlı olmayan
        servis listeye girmez: anahtarsız metin üretimi mümkün değildir.
        """
        adaylar = []
        for servis in (provider, *[s for s in AI_YEDEK_SIRA if s != provider]):
            if servis not in AI_SAGLAYICILAR:
                continue
            servis_anahtari = ((anahtar or "").strip() if servis == provider
                               else self._kayitli_anahtar(servis))
            if not servis_anahtari:
                continue
            adaylar.append({"provider": servis,
                            "label": AI_SAGLAYICILAR[servis]["label"],
                            "key": servis_anahtari,
                            "model": ((model or "").strip() if servis == provider else "")})
        return adaylar

    def _istek(self, aday, sistem, kullanici, json_modu):
        """Tek bir aday servise istek gönder ve metni döndür (modeli `ai_metin` belirler)."""
        saglayici = self.saglayicilar.get(aday["provider"]) or self.saglayicilar["anthropic"]
        return saglayici.metin(aday["key"], aday["model"], sistem, kullanici, json_modu)

    def _yazan_model(self, aday):
        """Yanıtı yazan model: Gemini 503'te `GEMINI_YOGUN_YEDEK`'e geçmiş olabilir."""
        saglayici = self.saglayicilar.get(aday["provider"])
        return getattr(saglayici, "son_model", "") or aday["model"]

    def metin(self, provider, anahtar, model, sistem, kullanici, json_modu=True, *,
                 bildir=None, kullanilan=None, yedek=True):
        """Metin isteği gönder; seçili servis yazamazsa **anahtarı kayıtlı yedeklere geç**.

        Kota, yetki, model ya da bağlantı hatası alan servis bırakılmaz: sıradaki servis
        (Cloudflare → Gemini → EVREN → ChatGPT → Claude) kendiliğinden denenir ve işlem kaldığı
        yerden sürer. `bildir(mesaj)` verilirse geçişler bu çağrıya bildirilir; `kullanilan` sözlüğü
        yanıtı yazan servisi taşır (`provider`, `label`, `model`). `yedek=False` yalnızca
        seçili servisi dener (bağlantı kontrolü gibi "tek servisi ölç" işleri için).

        Hiçbir servis yanıt veremezse son hatanın kendisi yükseltilir.
        """
        if provider not in AI_SAGLAYICILAR:
            raise ValueError("Geçersiz prompt yapay zekâsı seçimi.")
        adaylar = self.adaylar(provider, anahtar, model)
        if not yedek:
            adaylar = [aday for aday in adaylar if aday["provider"] == provider]
        if not adaylar:
            etiket = AI_SAGLAYICILAR[provider]["label"]
            raise ValueError(f"{etiket} anahtarı kayıtlı değil. API hesapları sekmesinden gir ve kaydet.")
        son_hata = None
        for sira, aday in enumerate(adaylar):
            # Yedek servisin modeli kendi listesinin ilkidir; seçili serviste kullanıcının
            # seçtiği model korunur (model adları servisler arasında taşınamaz).
            aday["model"] = ((aday["model"] or "").strip()
                             or AI_SAGLAYICILAR[aday["provider"]]["models"][0])
            try:
                metin = self._istek(aday, sistem, kullanici, json_modu)
            except Exception as exc:
                son_hata = baglanti_hatasi(exc)
                if sira + 1 >= len(adaylar):
                    break
                if bildir:
                    bildir(f"{aday['label']} yazamadı ({kisa(son_hata)}); "
                           f"{adaylar[sira + 1]['label']} otomatik denenecek.")
                continue
            yazan = self._yazan_model(aday)
            if yazan != aday["model"] and bildir:
                bildir(f"{aday['label']} · {aday['model']} kullanılamadı; yanıtı {yazan} yazdı.")
            if kullanilan is not None:
                kullanilan.update(provider=aday["provider"], label=aday["label"], model=yazan)
            if sira and bildir:
                bildir(f"Yedek servis devrede: {aday['label']} · model: {aday['model']}.")
            return metin
        raise son_hata

    def yokla(self, provider, anahtar, model):
        """Küçük bir istekle anahtarı ve modeli doğrula (yalnızca seçili servis)."""
        cevap = self.metin(provider, anahtar, model,
                         "You are a connection tester. Reply with the single word OK.",
                         "Connection test.", json_modu=False, yedek=False)
        etiket = AI_SAGLAYICILAR.get(provider, {}).get("label", provider)
        return f"{etiket} bağlantısı çalışıyor · model: {model or 'varsayılan'} · yanıt: {cevap.strip()[:60] or 'boş'}"


VARSAYILAN = MetinAIHavuzu()


def _model_bulunamadi(hata):
    """Hata modelin kendisiyle mi ilgili? ("model aşırı yüklü" geçici sayılır, bu değil.)"""
    dusuk = str(hata).lower()
    return "model" in dusuk and any(k in dusuk for k in (
        "404", "not_found", "not found", "does not exist", "no such model", "kabul etmedi"))


# Proje akışı da (bkz. `yeniden_deneme._hesaplari_dene`) aynı ayrımı kullanır.
_bekleme_suresi = dakikalik_bekleme


# Bütün hesaplar geçici hata verdiğinde (ör. modelin genel "yüksek talep" 503'ü) kaç
# kez ve ne kadar beklenip yeniden denenir.
GECIS_BEKLEMELERI = (10, 30, 60)


class HesapliMetin:
    """Tek servis, tek model; kota ya da yetki hatasında **aynı servisin sıradaki hesabı**.

    `MetinAIHavuzu`'nun tersine ne model ne servis yedeği vardır: yanıtı her zaman
    seçilen model yazar. Hesaplar aktif olandan başlayarak denenir:

    - günlük kota / yetki hatası: hesap bu nesne yaşadığı sürece (bir araştırma boyunca) elenir;
    - dakikalık hız sınırı: hesap yalnızca istenen süre kadar **bekletilir**, sıradaki geçer;
    - geçici hata (503, kopan bağlantı): hesap elenmez; bir geçişte iki geçici hata
      görülürse servis sallanıyordur, `GECIS_BEKLEMELERI` kadar beklenip yeniden denenir.

    Yanıt veren hesap uygulamanın da aktif hesabı olur (★ API hesapları sekmesinde).
    `bekle(saniye)` beklemeyi yapar (varsayılan `time.sleep`); araştırma bunu durdurma
    düğmesine bağlar.
    """

    def __init__(self, provider, model="", saglayicilar=None, hesaplar=None, bekle=None):
        if provider not in AI_SAGLAYICILAR:
            raise ValueError("Geçersiz yapay zekâ servisi.")
        self.provider = provider
        self.label = AI_SAGLAYICILAR[provider]["label"]
        self.model = ((model or "").strip() or EN_IYI_MODELLER.get(provider)
                      or AI_SAGLAYICILAR[provider]["models"][0])
        self.saglayici = (saglayicilar or VARSAYILAN.saglayicilar)[provider]
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.bekle = bekle or time.sleep
        self.elenen = set()
        self.bekleyen = {}            # hesap adı → tekrar denenebileceği an (monotonic)
        self.kullanilan = ""          # son yanıtı yazan hesabın adı

    def _kota_bekliyor(self, ad):
        """Hesap kalıcı kota listesinde mi (yalnızca Cloudflare; bkz. `kota_listesi`)."""
        return kota_listesi.VARSAYILAN.bekliyor(
            self.provider, {"ad": ad,
                            "degerler": self.hesaplar.hesap_degerleri(self.provider, ad)})

    def _sirali_hesaplar(self):
        adlar = self.hesaplar.hesap_adlari(self.provider)
        aktif = self.hesaplar.aktif_hesap(self.provider)
        return ([aktif] if aktif in adlar else []) + [ad for ad in adlar if ad != aktif]

    def _gecis(self, sistem, kullanici, json_modu, haber):
        """Hesapları bir kez dolaş: `(cevap, None)` ya da `(None, son hata)`."""
        son_hata, gecici = None, 0
        for ad in self._sirali_hesaplar():
            if ad in self.elenen or self.bekleyen.get(ad, 0) > time.monotonic():
                continue
            if self._kota_bekliyor(ad) is not None:
                # Görsel üretiminde günlük kotası biten Cloudflare hesabı prompt'ta da
                # aynı 10.000 nöronu kullanır: yenilenene kadar denenmez.
                self.elenen.add(ad)
                continue
            anahtar = ai_anahtari(self.provider, self.hesaplar.hesap_degerleri(self.provider, ad))
            if not anahtar:
                self.elenen.add(ad)
                continue
            try:
                cevap = self.saglayici.metin_tek_model(anahtar, self.model, sistem, kullanici,
                                                       json_modu)
            except Exception as exc:
                son_hata = baglanti_hatasi(exc)
                etiket = hata_etiketle(son_hata)
                if etiket == "HATA" and _model_bulunamadi(son_hata):
                    # Model adı yanlış ya da kapalı: hesap değiştirmek çözmez.
                    raise son_hata
                sure = _bekleme_suresi(son_hata) if etiket == "KOTA" else None
                if sure is not None:
                    self.bekleyen[ad] = time.monotonic() + sure
                    haber(f"{self.label} · '{ad}' dakikalık sınırda ({sure:.0f} sn); "
                          "sıradaki hesap deneniyor.")
                    continue
                if etiket in ("KOTA", "YETKİ"):
                    self.elenen.add(ad)
                    kota_listesi.VARSAYILAN.kaydet(
                        self.provider, {"ad": ad, "degerler":
                                        self.hesaplar.hesap_degerleri(self.provider, ad)},
                        str(son_hata))
                    haber(f"{self.label} · '{ad}' hesabı elendi ({kisa(son_hata)}); "
                          "sıradaki hesap deneniyor.")
                    continue
                gecici += 1
                haber(f"{self.label} · '{ad}' geçici hata ({kisa(son_hata)}).")
                if gecici >= 2:
                    break
                continue
            if ad != self.hesaplar.aktif_hesap(self.provider):
                try:
                    self.hesaplar.hesap_sec(self.provider, ad)
                except Exception:
                    pass
            self.kullanilan = ad
            yazan = getattr(self.saglayici, "son_model", "") or self.model
            if yazan != self.model:
                haber(f"{self.label} · {self.model} yoğun (503); yanıtı {yazan} yazdı.")
            return cevap, None
        return None, son_hata

    def metin(self, sistem, kullanici, json_modu=True, bildir=None):
        """Yanıt metni; bütün hesaplar tükenirse (ya da beklemeler biterse) son hata yükseltilir."""
        def haber(mesaj):
            if bildir:
                bildir(mesaj)

        son_hata = None
        for sira in range(len(GECIS_BEKLEMELERI) + 1):
            cevap, hata = self._gecis(sistem, kullanici, json_modu, haber)
            if hata is None and cevap is not None:
                return cevap
            son_hata = hata or son_hata
            kalan = [ad for ad in self._sirali_hesaplar() if ad not in self.elenen]
            if not kalan or sira >= len(GECIS_BEKLEMELERI):
                break
            simdi = time.monotonic()
            en_yakin = min(max(self.bekleyen.get(ad, 0) - simdi, 0) for ad in kalan)
            sure = GECIS_BEKLEMELERI[sira] if hata is not None and en_yakin == 0 else en_yakin
            haber(f"{self.label} · kullanılabilir hesap yok; {sure:.0f} sn beklenip "
                  "yeniden denenecek.")
            self.bekle(sure)
        if son_hata is None:
            raise ValueError(f"{self.label} için kullanılabilir hesap kalmadı. "
                             "API hesapları sekmesinden anahtar ekle.")
        raise son_hata
