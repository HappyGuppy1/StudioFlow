"""Tavily: yapay zekâ ajanları için web araması; sayfanın temizlenmiş metnini de döndürür.

Ücretsiz plan ayda 1.000 kredi verir (gelişmiş arama 2 kredi). Kota bitince HTTP 432
döner; `AramaHavuzu` o hesabı eler ve sıradaki Tavily hesabına geçer.
"""
import requests

from studioflow.saglayicilar.arama_ortak import ZAMAN_ASIMI, AramaHatasi, sonuc, yanit_hatasi
from studioflow.saglayicilar.taban import AramaSaglayici

TAVILY_URL = "https://api.tavily.com/search"


class TavilyArama(AramaSaglayici):
    ad = "tavily"
    hizmet = "tavily"

    def ara(self, sorgu, adet=5, anahtar="", dil="tr"):
        if not (anahtar or "").strip():
            raise AramaHatasi("Tavily anahtarı kayıtlı değil.", "YETKİ")
        govde = {"query": sorgu, "search_depth": "advanced", "max_results": max(1, min(int(adet), 20)),
                 "include_raw_content": "text", "include_answer": False}
        try:
            yanit = requests.post(TAVILY_URL, json=govde, timeout=ZAMAN_ASIMI,
                                  headers={"Authorization": f"Bearer {anahtar.strip()}"})
        except requests.RequestException as exc:
            raise AramaHatasi(f"Tavily'ye bağlanılamadı: {exc}") from exc
        if not yanit.ok:
            raise yanit_hatasi("Tavily", yanit, anahtar.strip())
        return [sonuc(k.get("title"), k.get("url"), metin=k.get("raw_content") or "",
                      ozet=k.get("content") or "", saglayici="Tavily",
                      tarih=k.get("published_date") or "")
                for k in yanit.json().get("results") or [] if k.get("url")]


VARSAYILAN = TavilyArama()
