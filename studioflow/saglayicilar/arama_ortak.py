"""Arama servislerinin ortak parçaları: sonuç biçimi, hata türü, HTTP ayarları.

Her arama sonucu tek biçimli bir sözlüktür (`sonuc`): servisler arasında taşınır,
araştırma hattı hangi servisin bulduğunu bilmeden kullanır.
"""
from urllib.parse import urlsplit

# Wikimedia, kimliği belirsiz istemcileri kısıtlıyor; tanımlayıcı bir User-Agent ister.
KULLANICI_AJANI = "StudioFlow/1.0 (hikaye arastirmasi; yerel masaustu uygulamasi)"

ZAMAN_ASIMI = (15, 60)


class AramaHatasi(RuntimeError):
    """Arama başarısız. `tur`: KOTA, YETKİ ya da HATA (hesap değiştirmenin işe yarayıp yaramadığı)."""

    def __init__(self, mesaj, tur="HATA"):
        super().__init__(mesaj)
        self.tur = tur


def http_turu(kod):
    """HTTP durum kodunu hata türüne çevir (Tavily 432/433 = plan/kredi sınırı)."""
    if kod in (401, 403):
        return "YETKİ"
    if kod in (402, 429, 432, 433):
        return "KOTA"
    return "HATA"


def yanit_hatasi(etiket, response, anahtar=""):
    """Başarısız HTTP yanıtından okunur bir `AramaHatasi` üret (anahtar gizlenir)."""
    metin = (response.text or "")[:300]
    if anahtar:
        metin = metin.replace(anahtar, "[gizli]")
    return AramaHatasi(f"{etiket} HTTP {response.status_code}: {metin}",
                       http_turu(response.status_code))


def alan_adi(url):
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def sonuc(baslik, url, metin="", ozet="", saglayici="", tarih=""):
    """Tek bir arama sonucu. `metin` sayfanın tam metni (varsa), `ozet` kısa parça."""
    return {"baslik": (baslik or "").strip() or alan_adi(url), "url": (url or "").strip(),
            "metin": (metin or "").strip(), "ozet": (ozet or "").strip(),
            "saglayici": saglayici, "tarih": (tarih or "").strip()}
