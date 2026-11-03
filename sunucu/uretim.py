"""Üretim işleri: StudioFlow'un üretim işlevlerini editörden arka planda çalıştırır.

Her iş StudioFlow'un **kendi** işlevini çağırır (kod kopyalanmaz); kota, hesap sırası,
deneme sayaçları ve `proje.txt` kaydı StudioFlow'daki gibi işler:

    devam           kaldığı yerden devam (StudioFlow'un "Kaldığı yerden devam et"i)
    prompt          prompt üretimine başla (seslendirmeden sonraki kapı)
    onay            görselleri onayla ve videoları seçilen servisle üret
    sahne_prompt    sahnenin görsel prompt'unu kaydet, yalnızca o karesini yeniden üret
    kare            sahnenin karesini kaldır ve yenile (onay yeniden sorulur)
    klip            sahnenin klibini sil ve yalnızca onu yeniden üret
    deneme          deneme sayaçlarını sıfırla (eşzamanlı, iş değildir)

Aynı anda tek iş çalışır. Proje başka bir süreçte (StudioFlow uygulamasında) çalışıyorsa
editör başlatmayı reddeder: iki akış aynı `proje.txt`'e yazarsa kayıt bozulur. Durdurma,
StudioFlow'un durdurma bayrağıyla yapılır: geçerli adım bitince akış kaydedip durur.
"""
import copy
import inspect
import itertools
import re
import threading
import time

from sunucu import ayar  # noqa: F401  (studioflow paketini bağlar)
from sunucu import veri
from studioflow.proje import (akis, ayar_normalize, calisma_kilidi, coklu_uretim, depo, dosya,
                              yeniden_deneme, yonetim)
from studioflow.proje import karakterler as kadro
from studioflow.proje.akis_servis import VIDEO_SERVIS_ADI
from studioflow.saglayicilar import metin_ortak

ESKI_CALISMA_DK = 15     # bu kadar dakikadır güncellenmeyen "çalışıyor" kaydı bayattır
SERVISLER = {k: v for k, v in VIDEO_SERVIS_ADI.items()}


class UretimHatasi(RuntimeError):
    """İş başlatılamadı; mesaj kullanıcıya gösterilir."""


def _temiz(metin):
    """Durum mesajındaki Markdown işaretlerini at (editör düz metin gösterir)."""
    return re.sub(r"\*\*|`", "", str(metin or "")).strip()


class Is:
    def __init__(self, ad, tur, baslik):
        self.ad, self.tur, self.baslik = ad, tur, baslik
        self.durum = "calisiyor"         # calisiyor · bitti · hata · durduruldu
        self.mesaj = "Başlatılıyor…"
        self.gecmis = []                 # son mesajlar (en yenisi sonda)
        self.baslangic = time.time()
        self.bitis = None
        self.durdurma_istendi = False
        self.sonuc = None                # işin ürettiği veri (ör. üretilen müzik dosyası)
        self.no = next(_SAYAC)

    def ozet(self):
        return {"ad": self.ad, "tur": self.tur, "baslik": self.baslik, "durum": self.durum,
                "mesaj": self.mesaj, "gecmis": self.gecmis[-12:], "sonuc": self.sonuc,
                "no": self.no, "sure": round((self.bitis or time.time()) - self.baslangic)}


_IS = None
_KILIT = threading.Lock()
_SAYAC = itertools.count(1)


def is_durumu():
    return _IS.ozet() if _IS else None


def baska_yerde_calisiyor(ad):
    """Proje başka bir süreçte (StudioFlow uygulaması) çalışıyor mu?

    Akış çalışırken `proje.txt`'in başlığına `Durum : çalışıyor` yazar ve dosyayı sık sık
    günceller. (StudioFlow dosyayı okurken bu durumu geri yüklemez, her okumada "bekliyor"
    kurar; bu yüzden başlık satırı doğrudan okunur.) Uzun süredir güncellenmeyen kayıt,
    yarıda kapanmış bir uygulamadan kalmıştır (bayat).
    """
    klasor = depo.guvenli_klasor(ad)
    if klasor is None or veri.diskteki_durum(klasor) != "calisiyor":
        return False
    if calisma_kilidi.calisan() == klasor.name:      # bu süreçte çalışıyor (editörün işi)
        return False
    try:
        yas = time.time() - (klasor / "proje.txt").stat().st_mtime
    except OSError:
        return False
    return yas < ESKI_CALISMA_DK * 60


def _baslat(ad, tur, baslik, uretec_fabrikasi, klasor_sart=True, sonuc_al=None):
    global _IS
    if klasor_sart and depo.guvenli_klasor(ad) is None:
        raise veri.ProjeYok(ad)
    with _KILIT:
        if _IS and _IS.durum == "calisiyor":
            raise UretimHatasi(f"'{_IS.ad}' projesinde bir iş sürüyor ({_IS.baslik}). "
                               "Bitmesini bekle ya da Durdur'a bas.")
        if klasor_sart and baska_yerde_calisiyor(ad):
            raise UretimHatasi("Bu proje şu anda StudioFlow uygulamasında çalışıyor. Orada "
                               "durdur ya da bitmesini bekle; iki akış aynı kayda yazarsa bozulur.")
        if calisma_kilidi.calisan():
            raise UretimHatasi(f"'{calisma_kilidi.calisan()}' projesi çalışıyor.")
        _IS = Is(ad, tur, baslik)
        is_ = _IS
    ozet = is_.ozet()      # iş çok hızlı bitse de çağıran "başladı" yanıtını alır
    threading.Thread(target=_calis, args=(is_, uretec_fabrikasi, sonuc_al), daemon=True,
                     name=f"uretim-{tur}-{ad}").start()
    return ozet


def paket_mesaji(paket):
    """StudioFlow paketinin durum metni: ilk öğe (iç içe paketlerde ilk paketin ilk öğesi)."""
    while isinstance(paket, (tuple, list)) and paket:
        paket = paket[0]
    return _temiz(paket) if isinstance(paket, str) else ""


def _calis(is_, uretec_fabrikasi, sonuc_al=None):
    try:
        cikti = uretec_fabrikasi()
        # Üreteç (akış, dublaj…) ya da tek paket döndüren işlev (müzik kaydet, göm…)
        paketler = cikti if inspect.isgenerator(cikti) else [cikti]
        for paket in paketler:
            if sonuc_al is not None:
                sonuc = sonuc_al(paket)
                if sonuc:
                    is_.sonuc = sonuc
            mesaj = paket_mesaji(paket)
            if mesaj and mesaj != is_.mesaj:
                is_.mesaj = mesaj
                is_.gecmis.append(f"{time.strftime('%H:%M:%S')} · {mesaj.splitlines()[0][:300]}")
        is_.durum = "durduruldu" if is_.durdurma_istendi else "bitti"
    except Exception as hata:   # StudioFlow işlevi beklenmedik hata verse de sunucu düşmesin
        is_.durum, is_.mesaj = "hata", f"Beklenmeyen hata: {hata}"
        is_.gecmis.append(is_.mesaj)
    finally:
        is_.bitis = time.time()


def baslat_ozel(ad, tur, baslik, uretec_fabrikasi):
    """Klasörü henüz olmayan proje için iş (yeni proje: klasörü akış kurar)."""
    return _baslat(ad, tur, baslik, uretec_fabrikasi, klasor_sart=False)


def islem(ad, tur, baslik, uretec_fabrikasi, sonuc_al=None):
    """Projeye bağlı katman işi (dublaj, müzik, altyazı, efekt, video katmanları)."""
    return _baslat(ad, tur, baslik, uretec_fabrikasi, sonuc_al=sonuc_al)


def durdur():
    """Çalışan işi geçerli adım bitince durdur (StudioFlow'un durdurma bayrağı)."""
    if _IS and _IS.durum == "calisiyor":
        _IS.durdurma_istendi = True
        _IS.mesaj = calisma_kilidi.durdur()
    return is_durumu()


# ── Ayarlar ve işler ─────────────────────────────────────────────────────────────
def edge_sesini_tamamla(ayarlar):
    """Edge sesi boş ya da dile uymuyorsa dilin ilk güvenli sesi (StudioFlow arayüzü de
    Edge sesini dilin ilk sesiyle açar). Boş kalırsa Edge seslendirmesi "Önce listeden bir
    Edge sesi seç" hatasıyla durur."""
    from studioflow.saglayicilar import ses_edge
    ses = ayarlar.setdefault("ses", {})
    sesler = ses_edge.VARSAYILAN.guvenli_sesler(ses.get("dil") or "en") or []
    if sesler and ses.get("edge_ses") not in sesler:
        ses["edge_ses"] = sesler[0]
    return ayarlar


def _edge_sesini_kaydet(ad):
    """Akış var olan projede ses ayarlarını `proje.txt`'ten okur: boş Edge sesi kayda da
    yazılır (yalnızca bellekte düzeltmek seslendirmeyi kurtarmaz)."""
    from studioflow.proje.dosya import proje_oku, proje_yaz
    klasor = depo.guvenli_klasor(ad)
    durum = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if durum is None:
        return
    eski = (durum.get("ayarlar") or {}).get("ses", {}).get("edge_ses")
    edge_sesini_tamamla(durum["ayarlar"])
    if durum["ayarlar"]["ses"].get("edge_ses") != eski:
        proje_yaz(durum)


def calisma_ayarlari(ad):
    """Projenin kayıtlı ayarları, StudioFlow arayüzünün akışa verdiği biçimde.

    Arayüz ayarları alanlardan toplar: normalleştirilmiş sözlük, karakter kadrosunun
    görselleri tam yolla. Editör aynı biçimi `proje.txt`'ten kurar.
    """
    kayit = yonetim.proje_ayarlari(ad)
    if kayit is None:
        raise veri.ProjeYok(ad)
    _edge_sesini_kaydet(ad)
    ayarlar = edge_sesini_tamamla(ayar_normalize.ayarlari_normalize(copy.deepcopy(kayit["ayarlar"])))
    ayarlar["video"]["karakterler"] = kadro.mutlak_kadro(
        ayarlar["video"].get("karakterler") or [], depo.proje_klasoru(ad))
    return kayit["metin"], ayarlar


def uretim_modu(deger=None):
    """Tekli / çoklu üretim (StudioFlow'un paylaşılan seçimi, bu süreçte)."""
    if deger is not None:
        coklu_uretim.VARSAYILAN.ayarla(deger)
    return coklu_uretim.VARSAYILAN.deger


# Kullanıcının düzeltemeyeceği, servisten kaynaklanan geçici hatalar.
GECICI_HATA = re.compile(r"internal server error|\b5\d\d\b|timed? ?out|yanıt vermedi|"
                         r"bağlanılamadı|connection|temporarily|service unavailable", re.I)
# Prompt düzeltmesi isteyen hatalar: bunlarda sayaç kendiliğinden açılmaz.
KALICI_HATA = re.compile(r"flagged|içerik filtresi|yazı var|yazısız|denetim|kalite", re.I)


def _gecici_denemeleri_ac(ad):
    """Hakkı dolan adımlardan son hatası **geçici** olanların sayacını aç.

    Deneme hakkı dolunca akış durur ve "Kaldığı yerden devam" sayacı açmaz (bkz.
    `yeniden_deneme.denemeleri_sifirla`). Bu, gerçek bir sorunu olan adımda doğru; ama
    Cloudflare'in geçici 500 hatasında kullanıcı devama bastığında hiçbir şey olmuyordu,
    önce **Deneme hakkını yenile** bulunması gerekiyordu (Betta, 23.10.2026).
    """
    if (_IS and _IS.durum == "calisiyor") or baska_yerde_calisiyor(ad):
        return
    klasor = depo.guvenli_klasor(ad)
    kayit = dosya.proje_oku(klasor) if klasor is not None else None
    if not kayit:
        return
    acilan = []
    for adim in kayit["adimlar"]:
        sayac = adim.get("deneme") or {}
        dolu = [islem for islem, sayi in sayac.items()
                if int(sayi or 0) >= yeniden_deneme.YENIDEN_SINIR]
        hata = adim.get("hata") or ""
        if not dolu or not GECICI_HATA.search(hata) or KALICI_HATA.search(hata):
            continue
        for islem in dolu:
            sayac[islem] = 0
        adim["deneme"] = sayac
        if hata.startswith("[DENEME DOLDU]") and " · " in hata:
            adim["hata"] = hata.split(" · ", 1)[1]
        if adim.get("durum") == "HATA":
            adim["durum"] = "YARIM" if adim.get("gorsel") else "BEKLİYOR"
        acilan.append(str(adim["index"]))
    if acilan:
        dosya.not_ekle(kayit, "Kaldığı yerden devam · geçici servis hatasıyla hakkı dolan "
                       "adımların sayacı kendiliğinden açıldı: " + ", ".join(acilan) + ".")
        dosya.proje_yaz(kayit)


def devam(ad):
    _gecici_denemeleri_ac(ad)
    metin, ayarlar = calisma_ayarlari(ad)
    return _baslat(ad, "devam", "Kaldığı yerden devam",
                   lambda: akis.proje_calistir(ad, metin, ayarlar))


def prompt_baslat(ad, ai=None, model=None):
    _metin, ayarlar = calisma_ayarlari(ad)
    ai = ai or ayarlar["video"].get("ai") or metin_ortak.AI_VARSAYILAN
    model = model or ayarlar["video"].get("model") or ""
    return _baslat(ad, "prompt", "Prompt üretimi",
                   lambda: yonetim.prompt_uretimi_baslat(ad, ai, model))


def onay(ad, servis):
    if servis not in SERVISLER:
        raise UretimHatasi(f"Bilinmeyen video servisi: {servis}")
    return _baslat(ad, "onay", f"Görsel onayı · {SERVISLER[servis]}",
                   lambda: yonetim.gorsel_onayi_ver(ad, servis))


def sahne_prompt(ad, index, gorsel_prompt, negatif_prompt):
    gorsel_prompt = (gorsel_prompt or "").strip()
    if not gorsel_prompt:
        raise UretimHatasi("Görsel prompt'u boş olamaz.")
    return _baslat(ad, "sahne_prompt", f"Sahne {index} · prompt kaydet ve yeniden üret",
                   lambda: yonetim.sahne_prompt_uygula(ad, str(index), gorsel_prompt,
                                                       (negatif_prompt or "").strip()))


def kare_yenile(ad, index):
    return _baslat(ad, "kare", f"Sahne {index} · kareyi yenile",
                   lambda: yonetim.gorsel_sil_yenile(ad, int(index)))


def klip_yenile(ad, index):
    return _baslat(ad, "klip", f"Sahne {index} · klibi yeniden üret",
                   lambda: yonetim.sahne_sil_yenile(ad, int(index)))


def deneme_sifirla(ad):
    if depo.guvenli_klasor(ad) is None:
        raise veri.ProjeYok(ad)
    if (_IS and _IS.durum == "calisiyor") or baska_yerde_calisiyor(ad):
        raise UretimHatasi("Proje çalışırken deneme hakkı yenilenmez; önce durdur.")
    paket = yeniden_deneme.denemeleri_sifirla(ad)
    return _temiz(paket[0] if isinstance(paket, (tuple, list)) else paket)


def sil(ad):
    """Projeyi kalıcı olarak sil (StudioFlow'un `yonetim.sil`'i); çalışırken silinmez."""
    klasor = depo.guvenli_klasor(ad)
    if klasor is None or not klasor.is_dir():
        raise veri.ProjeYok(ad)
    is_ = is_durumu()
    if (is_ and is_["durum"] == "calisiyor" and is_["ad"] == klasor.name) \
            or baska_yerde_calisiyor(klasor.name):
        raise UretimHatasi("Proje çalışırken silinmez; önce durdur.")
    mesaj = yonetim.sil(klasor.name)
    if klasor.exists():
        raise UretimHatasi(mesaj)
    return {"mesaj": mesaj}
