"""Exa: anlamsal (anlama dayalı) web araması; sayfa metniyle birlikte döner.

Ücretsiz kredi biterse HTTP 402 (`NO_MORE_CREDITS`) döner; `AramaHavuzu` o hesabı
eler ve sıradaki Exa hesabına geçer.
"""
import requests

from studioflow.saglayicilar.arama_ortak import ZAMAN_ASIMI, AramaHatasi, sonuc, yanit_hatasi
from studioflow.saglayicilar.taban import AramaSaglayici

EXA_URL = "https://api.exa.ai/search"

# Sayfa başına istenen en fazla karakter: araştırma hattı zaten ilgili paragrafları seçer.
EXA_KARAKTER = 20000


class ExaArama(AramaSaglayici):
    ad = "exa"
    hizmet = "exa"

    def ara(self, sorgu, adet=5, anahtar="", dil="tr"):
        if not (anahtar or "").strip():
            raise AramaHatasi("Exa anahtarı kayıtlı değil.", "YETKİ")
        govde = {"query": sorgu, "type": "auto", "numResults": max(1, min(int(adet), 25)),
                 "contents": {"text": {"maxCharacters": EXA_KARAKTER}}}
        try:
            yanit = requests.post(EXA_URL, json=govde, timeout=ZAMAN_ASIMI,
                                  headers={"x-api-key": anahtar.strip()})
        except requests.RequestException as exc:
            raise AramaHatasi(f"Exa'ya bağlanılamadı: {exc}") from exc
        if not yanit.ok:
            raise yanit_hatasi("Exa", yanit, anahtar.strip())
        return [sonuc(k.get("title"), k.get("url"), metin=k.get("text") or "",
                      saglayici="Exa", tarih=(k.get("publishedDate") or "")[:10])
                for k in yanit.json().get("results") or [] if k.get("url")]


VARSAYILAN = ExaArama()
