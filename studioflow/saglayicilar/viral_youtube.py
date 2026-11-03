"""YouTube Shorts araması: izlenmeye göre sıralı kısa videolar ve istatistikleri.

İki yol, aynı sonuç biçimi (`video` sözlüğü):

1. **YouTube Data API v3** (anahtar varsa): `search.list` (100 birim; `videoDuration=short`,
   `order=viewCount`, `publishedAfter`) + `videos.list` (50 video = 1 birim; izlenme, beğeni,
   yorum, süre, tarih). Günlük ücretsiz kota 10.000 birim.
2. **yt-dlp** (anahtarsız): YouTube arama sayfası "izlenmeye göre sırala" filtresiyle okunur.
   Ölçüm (26.09.2026): "izlenme + kısa (<4 dk)" filtresi tarih filtresiyle birlikte neredeyse
   boş dönüyor; bu yüzden tarihli aramada "izlenme + tarih" istenir ve süre kodda süzülür.
   Düz listede izlenme ve süre gelir, yayın tarihi gelmez.

API'de "bu bir Short" alanı yoktur. Süre ≤ 180 sn ön süzgeçtir; kesin tespit
`/shorts/{id}` adresine HEAD isteğidir (200 = Short, 303 = normal video).
"""
import base64
import re
import shutil
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from studioflow.saglayicilar.arama_ortak import AramaHatasi, yanit_hatasi

try:
    import yt_dlp
except ImportError:              # paket kurulu değil: anahtarsız yol kullanılamaz
    yt_dlp = None

API = "https://www.googleapis.com/youtube/v3"
SHORT_SURE = 180                 # Shorts 15 Ekim 2024'ten beri en fazla 3 dakika

# Zaman aralığı → (gün, YouTube arama sayfası tarih kodu). None = tüm zamanlar.
ZAMANLAR = {"hafta": (7, 3), "ay": (30, 4), "yil": (365, 5), "tum": (None, None)}


def video(platform, kimlik, url, baslik, kanal="", izlenme=0, begeni=None, yorum=None,
          paylasim=None, sure=None, tarih="", abone=None, etiketler=()):
    """Platformdan bağımsız tek video kaydı."""
    return {"platform": platform, "id": kimlik, "url": url, "baslik": (baslik or "").strip(),
            "kanal": (kanal or "").strip(), "izlenme": int(izlenme or 0),
            "begeni": begeni, "yorum": yorum, "paylasim": paylasim, "sure": sure,
            "tarih": tarih or "", "abone": abone, "etiketler": list(etiketler or [])}


def js_ayarlari():
    """yt-dlp güncel YouTube için bir JavaScript çalışma ortamı ister; Node varsa onu kullan."""
    return {"js_runtimes": {"node": {}}} if shutil.which("node") else {}


def iso_sure(metin):
    """ISO 8601 süresini (PT1M5S) saniyeye çevir."""
    eslesme = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", metin or "")
    if not eslesme:
        return None
    g, s, d, sn = (int(x or 0) for x in eslesme.groups())
    return ((g * 24 + s) * 60 + d) * 60 + sn


def short_mu(kimlik, oturum=None):
    """`/shorts/{id}` HEAD isteği: 200 → Short, 303 → normal video; belirsizse None."""
    try:
        yanit = (oturum or requests).head(f"https://www.youtube.com/shorts/{kimlik}",
                                          allow_redirects=False, timeout=15)
    except requests.RequestException:
        return None
    return True if yanit.status_code == 200 else False if yanit.status_code in (301, 302, 303) else None


def shortlari_suz(videolar, is_parcacigi=8):
    """Süresi ≤ 180 sn olanları `/shorts/` kontrolüyle kesinleştir (paralel HEAD istekleri)."""
    adaylar = [v for v in videolar if v["sure"] is None or v["sure"] <= SHORT_SURE]
    with requests.Session() as oturum, ThreadPoolExecutor(is_parcacigi) as havuz:
        sonuclar = list(havuz.map(lambda v: short_mu(v["id"], oturum), adaylar))
    # Kontrol belirsiz kaldıysa (ağ hatası) süre ön süzgeci yeterli sayılır.
    return [v for v, short in zip(adaylar, sonuclar) if short is not False]


class YoutubeApi:
    """Resmî API ile arama. Hata `AramaHatasi` (403 kota/yetki → hesap değiştirilir)."""

    ad = "youtube_api"

    def _get(self, yol, anahtar, **parametreler):
        try:
            yanit = requests.get(f"{API}/{yol}", params={**parametreler, "key": anahtar}, timeout=30)
        except requests.RequestException as exc:
            raise AramaHatasi(f"YouTube API'ye bağlanılamadı: {exc}") from exc
        if not yanit.ok:
            hata = yanit_hatasi("YouTube API", yanit, anahtar)
            if "quotaExceeded" in yanit.text or "dailyLimitExceeded" in yanit.text:
                hata.tur = "KOTA"
            raise hata
        return yanit.json()

    def ara(self, sorgu, adet, anahtar, zaman="ay", dil=""):
        gun = ZAMANLAR.get(zaman, ZAMANLAR["ay"])[0]
        parametreler = {"part": "snippet", "q": sorgu, "type": "video", "videoDuration": "short",
                        "order": "viewCount", "maxResults": max(1, min(int(adet), 50))}
        if gun:
            parametreler["publishedAfter"] = ((datetime.now(timezone.utc) - timedelta(days=gun))
                                              .strftime("%Y-%m-%dT%H:%M:%SZ"))
        if dil:
            parametreler["relevanceLanguage"] = dil
        kimlikler = [k["id"]["videoId"] for k in self._get("search", anahtar, **parametreler)
                     .get("items") or [] if (k.get("id") or {}).get("videoId")]
        return self.ayrinti(kimlikler, anahtar)

    def ayrinti(self, kimlikler, anahtar):
        videolar = []
        for bas in range(0, len(kimlikler), 50):
            veri = self._get("videos", anahtar, part="snippet,statistics,contentDetails",
                             id=",".join(kimlikler[bas:bas + 50]))
            for k in veri.get("items") or []:
                s, ist = k.get("snippet") or {}, k.get("statistics") or {}
                videolar.append(video(
                    "YouTube", k["id"], f"https://www.youtube.com/shorts/{k['id']}", s.get("title"),
                    s.get("channelTitle"), ist.get("viewCount"),
                    int(ist["likeCount"]) if ist.get("likeCount") else None,
                    int(ist["commentCount"]) if ist.get("commentCount") else None,
                    sure=iso_sure((k.get("contentDetails") or {}).get("duration")),
                    tarih=(s.get("publishedAt") or "")[:10], etiketler=s.get("tags") or ()))
        return videolar

    def dogrula(self, anahtar):
        """Anahtarı 1 birimlik bir istekle dene."""
        return bool(self._get("videos", anahtar, part="id", id="jNQXAC9IVRw").get("items"))


def _arama_filtresi(tarih_kodu):
    """YouTube arama sayfası `sp` parametresi: izlenmeye göre sırala (+ tarih ya da kısa süre)."""
    ic = bytes([0x08, tarih_kodu]) if tarih_kodu else bytes([0x18, 0x01])   # tarih | <4 dk
    return urllib.parse.quote(base64.b64encode(bytes([0x08, 0x03, 0x12, len(ic)]) + ic).decode())


class YoutubeYtdlp:
    """Anahtarsız arama (yt-dlp). Tarih bilgisi gelmez; süre ve izlenme gelir."""

    ad = "yt_dlp"

    def ara(self, sorgu, adet, anahtar="", zaman="ay", dil=""):
        if yt_dlp is None:
            raise AramaHatasi("yt-dlp kurulu değil (requirements.txt ile kur).")
        tarih_kodu = ZAMANLAR.get(zaman, ZAMANLAR["ay"])[1]
        url = (f"https://www.youtube.com/results?search_query={urllib.parse.quote(sorgu)}"
               f"&sp={_arama_filtresi(tarih_kodu)}")
        # Tarihli aramada süre filtresi yok: kısa olmayanlar sonradan atılır, fazladan istenir.
        istenen = int(adet) * (3 if tarih_kodu else 1)
        ayar = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True,
                "playlistend": max(1, min(istenen, 120)), **js_ayarlari()}
        try:
            with yt_dlp.YoutubeDL(ayar) as ydl:
                sonuc = ydl.extract_info(url, download=False) or {}
        except Exception as exc:
            raise AramaHatasi(f"yt-dlp YouTube araması başarısız: {str(exc)[:200]}") from exc
        videolar = [video("YouTube", e["id"], f"https://www.youtube.com/shorts/{e['id']}",
                          e.get("title"), e.get("channel") or e.get("uploader"), e.get("view_count"),
                          sure=int(e["duration"]) if e.get("duration") else None)
                    for e in sonuc.get("entries") or [] if e and e.get("id")]
        return [v for v in videolar if v["sure"] is None or v["sure"] <= SHORT_SURE]


API_VARSAYILAN = YoutubeApi()
YTDLP_VARSAYILAN = YoutubeYtdlp()
