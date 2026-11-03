"""DDGS: anahtarsız meta arama (DuckDuckGo, Bing, Google… sonuçlarını birleştirir).

Anahtar ve kota yoktur ama IP başına hız sınırı vardır (`RatelimitException`); bu
yüzden ana arama değil, anahtarlı servisler bitince devreye giren son katmandır.
Sonuçlar yalnızca kısa özet taşır; sayfa metnini `sayfa_okuma` getirir.

Paket kurulu değilse servis "kullanılamıyor" hatası verir, uygulama çalışmaya devam eder.
"""
from studioflow.saglayicilar.arama_ortak import AramaHatasi, sonuc
from studioflow.saglayicilar.taban import AramaSaglayici

try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException, RatelimitException
except ImportError:          # paket kurulu değil: katman atlanır
    DDGS = None
    DDGSException = RatelimitException = Exception

# Arama dili → DDGS bölgesi.
BOLGELER = {"tr": "tr-tr", "en": "us-en", "de": "de-de", "fr": "fr-fr", "es": "es-es",
            "it": "it-it", "ru": "ru-ru", "ar": "xa-ar"}


class DdgsArama(AramaSaglayici):
    ad = "ddgs"
    hizmet = ""

    def ara(self, sorgu, adet=5, anahtar="", dil="tr"):
        if DDGS is None:
            raise AramaHatasi("ddgs paketi kurulu değil (requirements.txt ile kur).")
        try:
            kayitlar = DDGS(timeout=20).text(sorgu, region=BOLGELER.get(dil, "wt-wt"),
                                             max_results=max(1, min(int(adet), 20)))
        except RatelimitException as exc:
            raise AramaHatasi(f"DDGS hız sınırına takıldı: {exc}", "KOTA") from exc
        except DDGSException as exc:
            raise AramaHatasi(f"DDGS araması başarısız: {exc}") from exc
        return [sonuc(k.get("title"), k.get("href"), ozet=k.get("body") or "", saglayici="DDGS")
                for k in kayitlar or [] if k.get("href")]


VARSAYILAN = DdgsArama()
