"""Wikipedia: anahtarsız, ücretsiz ansiklopedi araması ve makale metni (her dil sürümü).

Tarihî olaylarda araştırmanın omurgasıdır: kesin tarih, kişi ve yer bilgisi önce
buradan kurulur. MediaWiki Action API kullanılır (`list=search` + `prop=extracts`).
"""
import requests

from studioflow.saglayicilar.arama_ortak import (KULLANICI_AJANI, ZAMAN_ASIMI, AramaHatasi,
                                                 sonuc, yanit_hatasi)
from studioflow.saglayicilar.taban import AramaSaglayici


def _api(dil):
    return f"https://{dil}.wikipedia.org/w/api.php"


class WikipediaArama(AramaSaglayici):
    ad = "wikipedia"
    hizmet = ""

    def __init__(self, oturum=None):
        self.oturum = oturum or requests.Session()
        self.oturum.headers.update({"User-Agent": KULLANICI_AJANI})

    def _sorgu(self, dil, **parametreler):
        parametreler.update(format="json", utf8=1, formatversion=2)
        try:
            yanit = self.oturum.get(_api(dil), params=parametreler, timeout=ZAMAN_ASIMI)
        except requests.RequestException as exc:
            raise AramaHatasi(f"Wikipedia'ya bağlanılamadı: {exc}") from exc
        if not yanit.ok:
            raise yanit_hatasi("Wikipedia", yanit)
        return yanit.json()

    def basliklar(self, sorgu, adet=3, dil="tr"):
        """Sorguya en uygun makale başlıkları."""
        veri = self._sorgu(dil, action="query", list="search", srsearch=sorgu,
                           srlimit=max(1, min(int(adet), 10)))
        return [kayit["title"] for kayit in (veri.get("query") or {}).get("search") or []]

    def makale(self, baslik, dil="tr"):
        """Makalenin düz metni; yönlendirmeler izlenir. Yoksa `None`."""
        veri = self._sorgu(dil, action="query", prop="extracts|info", explaintext=1,
                           redirects=1, inprop="url", titles=baslik)
        for sayfa in (veri.get("query") or {}).get("pages") or []:
            if sayfa.get("missing") or not sayfa.get("extract"):
                continue
            return sonuc(sayfa.get("title"), sayfa.get("fullurl")
                         or f"https://{dil}.wikipedia.org/wiki/{sayfa.get('title')}",
                         metin=sayfa["extract"], saglayici=f"Wikipedia ({dil})")
        return None

    def ara(self, sorgu, adet=2, anahtar="", dil="tr"):
        sonuclar = []
        for baslik in self.basliklar(sorgu, adet, dil):
            makale = self.makale(baslik, dil)
            if makale:
                sonuclar.append(makale)
        return sonuclar


VARSAYILAN = WikipediaArama()
