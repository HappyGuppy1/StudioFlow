"""TikTok araması: Apify `clockworks/tiktok-scraper` aktörü (senkron çalıştırma).

TikTok'un resmî Research API'si yalnızca akademik araştırmacılara açık (ticari kullanım
yasak). Apify ücretsiz planı **her ay 5 $** kredi verir, kredi kartı istemez; bu aktör
~1,70 $ / 1.000 video → ayda ~2.900 video. Kredi bitince HTTP 402 döner ve hesap elenir.

Sonuç biçimi `viral_youtube.video` ile aynıdır.
"""
import requests

from studioflow.saglayicilar.arama_ortak import AramaHatasi, yanit_hatasi
from studioflow.saglayicilar.viral_youtube import video

AKTOR = "clockworks~tiktok-scraper"
URL = f"https://api.apify.com/v2/acts/{AKTOR}/run-sync-get-dataset-items"
BIRIM_FIYAT = 1.70 / 1000        # $ / video (aktör sayfası, Eylül 2026)
ZAMAN_ASIMI = 290                # Apify senkron çalıştırmayı 300 sn'de keser


def maliyet(adet):
    """Tahmini Apify maliyeti ($)."""
    return round(adet * BIRIM_FIYAT, 3)


class TiktokApify:
    ad = "apify_tiktok"

    def ara(self, sorgular, adet, anahtar):
        """Sorgu başına en fazla `adet` video. Hata `AramaHatasi` (402 = kredi bitti)."""
        if not (anahtar or "").strip():
            raise AramaHatasi("Apify token'ı kayıtlı değil.", "YETKİ")
        sorgular = [s for s in sorgular if (s or "").strip()]
        if not sorgular:
            return []
        adet = max(1, min(int(adet), 50))
        girdi = {"searchQueries": sorgular, "resultsPerPage": adet, "searchSection": "/video",
                 "shouldDownloadVideos": False, "shouldDownloadCovers": False,
                 "shouldDownloadSubtitles": False, "shouldDownloadAvatars": False}
        try:
            yanit = requests.post(URL, json=girdi, timeout=ZAMAN_ASIMI + 20,
                                  params={"timeout": ZAMAN_ASIMI, "maxItems": adet * len(sorgular)},
                                  headers={"Authorization": f"Bearer {anahtar.strip()}"})
        except requests.RequestException as exc:
            raise AramaHatasi(f"Apify'a bağlanılamadı: {exc}") from exc
        if yanit.status_code == 408:
            raise AramaHatasi("Apify 300 sn'de bitiremedi; daha az sorgu/sonuç dene.")
        if not yanit.ok:
            raise yanit_hatasi("Apify", yanit, anahtar.strip())
        videolar = []
        for k in yanit.json() or []:
            if not isinstance(k, dict) or not k.get("webVideoUrl"):
                continue
            yazar, meta = k.get("authorMeta") or {}, k.get("videoMeta") or {}
            videolar.append(video(
                "TikTok", str(k.get("id") or k["webVideoUrl"]), k["webVideoUrl"], k.get("text"),
                yazar.get("name"), k.get("playCount"), k.get("diggCount"), k.get("commentCount"),
                k.get("shareCount"), meta.get("duration"), (k.get("createTimeISO") or "")[:10],
                yazar.get("fans"), [h.get("name") for h in k.get("hashtags") or [] if h.get("name")]))
        return videolar

    def kredi(self, anahtar):
        """Hesap planı ve bu ayki kullanım (ücretsiz, kredi harcamaz)."""
        try:
            yanit = requests.get("https://api.apify.com/v2/users/me/limits", timeout=20,
                                 headers={"Authorization": f"Bearer {(anahtar or '').strip()}"})
        except requests.RequestException as exc:
            raise AramaHatasi(f"Apify'a bağlanılamadı: {exc}") from exc
        if not yanit.ok:
            raise yanit_hatasi("Apify", yanit, (anahtar or "").strip())
        veri = (yanit.json() or {}).get("data") or {}
        sinir = (veri.get("limits") or {}).get("maxMonthlyUsageUsd")
        kullanim = (veri.get("current") or {}).get("monthlyUsageUsd")
        return sinir, kullanim


VARSAYILAN = TiktokApify()
