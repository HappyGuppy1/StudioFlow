"""Video konusu bul: bir isteği alt konulara çevirir, her alt konuda viral Shorts / TikTok arar.

Akış:

1. **Anlama** (yapay zekâ) — serbest metin ("osmanlıyla ilgili ilginç olaylar") alt
   konulara ve platform başına arama sorgularına çevrilir.
2. **YouTube Shorts** — anahtar varsa resmî API (`viral_youtube.YoutubeApi`; kotası biten
   anahtarın yerine sıradaki hesap), yoksa ya da bütün anahtarlar biterse anahtarsız yt-dlp.
   Sonuçlar `/shorts/` kontrolüyle kesinleştirilir.
3. **TikTok** — Apify token'ı varsa (`viral_tiktok`); her alt konu ayrı çalıştırılır ki
   hangi videonun hangi konudan geldiği bilinsin. Token yoksa atlanır.
4. **Özet** — alt konu × platform: video sayısı, viral sayısı (izlenme ≥ eşik), medyan
   izlenme, en çok izlenen video. Videolar izlenmeye göre sıralanır; tarih biliniyorsa
   günlük izlenme de hesaplanır.
5. **Kayıt** — `outputs/viral/<tarih>_<istek>.json` + `.csv` + `.txt` (indirilebilir liste).
"""
import csv
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek.yollar import OUTPUTS
from studioflow.hikaye import istemler, rapor
from studioflow.hikaye.yanit import YapayZekaIsi
from studioflow.saglayicilar import viral_tiktok, viral_youtube
from studioflow.saglayicilar.arama_ortak import AramaHatasi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import kisa

KLASOR = OUTPUTS / "viral"
VARSAYILAN_ESIK = 100_000
ZAMAN_ETIKETLERI = {"hafta": "Son 7 gün", "ay": "Son 30 gün", "yil": "Son 1 yıl", "tum": "Tüm zamanlar"}


def gunluk_izlenme(v, bugun=None):
    """İzlenme / yayından bu yana geçen gün (tarih bilinmiyorsa None)."""
    if not v.get("tarih"):
        return None
    try:
        gun = ((bugun or date.today()) - date.fromisoformat(v["tarih"][:10])).days
    except ValueError:
        return None
    return round(v["izlenme"] / max(gun, 1))


def ozet_satirlari(videolar, esik):
    """Alt konu × platform özeti; en çok viral video olan konu önce."""
    gruplar = {}
    for v in videolar:
        gruplar.setdefault((v["alt_konu"], v["platform"]), []).append(v)
    satirlar = []
    for (konu, platform), liste in gruplar.items():
        izlenmeler = [v["izlenme"] for v in liste]
        enust = max(liste, key=lambda v: v["izlenme"])
        satirlar.append({"alt_konu": konu, "platform": platform, "video": len(liste),
                         "viral": sum(1 for i in izlenmeler if i >= esik),
                         "medyan": int(statistics.median(izlenmeler)),
                         "en_cok": enust["izlenme"], "en_cok_baslik": enust["baslik"],
                         "en_cok_url": enust["url"]})
    return sorted(satirlar, key=lambda s: (-s["viral"], -s["medyan"]))


def liste_metni(videolar, anlasilan=""):
    """Videoların listesini düz metin (.txt) olarak biçimlendir (indirilebilir liste)."""
    satirlar = ["Viral video listesi"]
    if anlasilan:
        satirlar.append(f"Anlaşılan istek: {anlasilan}")
    satirlar.append(f"Toplam: {len(videolar or [])} video")
    satirlar.append("")
    for sira, v in enumerate(videolar or [], 1):
        izlenme = int(v.get("izlenme") or 0)
        satirlar += [f"{sira}. {v.get('baslik') or '(başlıksız)'}",
                     f"   Platform : {v.get('platform') or '-'}",
                     f"   Alt konu : {v.get('alt_konu') or '-'}",
                     f"   Kanal    : {v.get('kanal') or '-'}",
                     f"   İzlenme  : {izlenme:,}",
                     f"   Bağlantı : {v.get('url') or '-'}", ""]
    return "\n".join(satirlar).rstrip() + "\n"


class KonuBulucu(YapayZekaIsi):
    """Tek bir arama. `adimlar()` durum satırları üretir; bitince `sonuc` dolar."""

    def __init__(self, istek, platformlar=("youtube", "tiktok"), zaman="ay", adet=20,
                 alt_konu=5, esik=VARSAYILAN_ESIK, provider="gemini", model="", *, ai=None,
                 iptal=None, hesaplar=None, youtube_api=None, youtube_ytdlp=None, tiktok=None,
                 short_suz=None, klasor=None):
        self.istek = str(istek or "").strip()
        self.platformlar = set(platformlar or ())
        self.zaman = zaman if zaman in ZAMAN_ETIKETLERI else "ay"
        self.adet = max(5, min(int(adet), 50))
        self.alt_konu = max(1, min(int(alt_konu), 8))
        self.esik = max(0, int(esik or 0))
        self.iptal = iptal
        self.ai = ai or HesapliMetin(provider, model, bekle=self._bekle)
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.youtube_api = youtube_api or viral_youtube.API_VARSAYILAN
        self.youtube_ytdlp = youtube_ytdlp or viral_youtube.YTDLP_VARSAYILAN
        self.tiktok = tiktok or viral_tiktok.VARSAYILAN
        self.short_suz = short_suz or viral_youtube.shortlari_suz
        self.klasor = klasor or KLASOR
        self.plan = {}
        self.videolar = []
        self.elenen = set()        # {(hizmet, hesap)} kotası/yetkisi biten anahtarlar
        self.kaynak_sayac = {}     # "YouTube API" / "yt-dlp" / "Apify" → sorgu sayısı
        self.sonuc = None
        self._notlar = []
        self._gorulen = set()

    # ------------------------------------------------------------ hesaplar

    def _anahtarlar(self, hizmet, alan):
        try:
            adlar = self.hesaplar.hesap_adlari(hizmet)
            aktif = self.hesaplar.aktif_hesap(hizmet)
        except Exception:
            return []
        sirali = ([aktif] if aktif in adlar else []) + [a for a in adlar if a != aktif]
        return [(ad, (self.hesaplar.hesap_degerleri(hizmet, ad).get(alan) or "").strip())
                for ad in sirali
                if (hizmet, ad) not in self.elenen
                and (self.hesaplar.hesap_degerleri(hizmet, ad).get(alan) or "").strip()]

    def _say(self, kaynak):
        self.kaynak_sayac[kaynak] = self.kaynak_sayac.get(kaynak, 0) + 1

    # ------------------------------------------------------------ aramalar

    def _youtube(self, sorgu):
        for ad, anahtar in self._anahtarlar("youtube", "youtube_key"):
            try:
                sonuc = self.youtube_api.ara(sorgu, self.adet, anahtar, self.zaman)
                self._say("YouTube API")
                return sonuc
            except AramaHatasi as exc:
                if exc.tur in ("KOTA", "YETKİ"):
                    self.elenen.add(("youtube", ad))
                    self._notlar.append(f"YouTube API · '{ad}' kullanılamıyor ({kisa(exc)}); "
                                        "sıradaki hesap / anahtarsız arama deneniyor.")
                    continue
                self._notlar.append(f"YouTube API hata verdi ({kisa(exc)}); anahtarsız aramaya geçiliyor.")
                break
        try:
            sonuc = self.youtube_ytdlp.ara(sorgu, self.adet, "", self.zaman)
            self._say("yt-dlp")
            return sonuc
        except AramaHatasi as exc:
            self._notlar.append(f"YouTube araması yapılamadı ({kisa(exc)}).")
            return []

    def _tiktok(self, sorgular):
        for ad, anahtar in self._anahtarlar("apify", "apify_token"):
            try:
                sonuc = self.tiktok.ara(sorgular, self.adet, anahtar)
                self._say("Apify")
                return sonuc
            except AramaHatasi as exc:
                if exc.tur in ("KOTA", "YETKİ"):
                    self.elenen.add(("apify", ad))
                    self._notlar.append(f"Apify · '{ad}' kullanılamıyor ({kisa(exc)}); sıradaki hesap.")
                    continue
                self._notlar.append(f"TikTok araması yapılamadı ({kisa(exc)}).")
                return []
        return []

    def _ekle(self, videolar, alt_konu):
        yeni = 0
        for v in videolar:
            anahtar = (v["platform"], v["id"])
            if anahtar in self._gorulen:
                continue
            self._gorulen.add(anahtar)
            self.videolar.append({**v, "alt_konu": alt_konu})
            yeni += 1
        return yeni

    # ------------------------------------------------------------ adımlar

    def _anla(self):
        veri = self._json(istemler.KONU_BUL.format(adet=self.alt_konu),
                          f"User request: {self.istek}") or {}
        konular = []
        for oge in veri.get("alt_konular") or []:
            if not isinstance(oge, dict):
                continue
            ad = str(oge.get("ad") or "").strip()
            yt = [str(s).strip() for s in oge.get("youtube") or [] if str(s).strip()][:2]
            tt = [str(s).strip() for s in oge.get("tiktok") or [] if str(s).strip()][:1]
            if ad and (yt or tt):
                konular.append({"ad": ad, "youtube": yt, "tiktok": tt})
        if not konular:
            # Yapay zekâ anlayamadıysa istek olduğu gibi aranır.
            konular = [{"ad": self.istek[:40], "youtube": [self.istek], "tiktok": [self.istek]}]
        self.plan = {"anlasilan": str(veri.get("anlasilan") or self.istek).strip(),
                     "alt_konular": konular[:self.alt_konu]}

    def _kaydet(self, zaman):
        self.klasor.mkdir(parents=True, exist_ok=True)
        ad = rapor.dosya_adi(self.istek, zaman)
        jsn, csv_yol = self.klasor / f"{ad}.json", self.klasor / f"{ad}.csv"
        txt_yol = self.klasor / f"{ad}.txt"
        txt_yol.write_text(liste_metni(self.videolar, self.plan.get("anlasilan", "")),
                           encoding="utf-8")
        jsn.write_text(json.dumps({"istek": self.istek, "plan": self.plan, "zaman": self.zaman,
                                   "esik": self.esik, "ozet": self.ozet,
                                   "videolar": self.videolar}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        alanlar = ["platform", "alt_konu", "baslik", "kanal", "izlenme", "begeni", "yorum",
                   "paylasim", "sure", "tarih", "gunluk", "url"]
        with csv_yol.open("w", encoding="utf-8-sig", newline="") as dosya:
            yazar = csv.DictWriter(dosya, fieldnames=alanlar, extrasaction="ignore")
            yazar.writeheader()
            yazar.writerows(self.videolar)
        return jsn, csv_yol, txt_yol

    def adimlar(self):
        if not self.istek:
            raise ValueError("Ne aramak istediğini yaz.")
        if not self.platformlar:
            raise ValueError("En az bir platform seç.")
        zaman_damgasi = datetime.now()
        yield f"İstek anlaşılıyor · {self.ai.label} · {self.ai.model}…"
        self._anla()
        yield from self._notlari_bosalt()
        konular = self.plan["alt_konular"]
        yield f"Anlaşılan: {self.plan['anlasilan']}"
        yield "Alt konular: " + " · ".join(k["ad"] for k in konular)

        if "youtube" in self.platformlar:
            for sira, konu in enumerate(konular, 1):
                for sorgu in konu["youtube"]:
                    self._dur_mu()
                    bulunan = self._youtube(sorgu)
                    yield from self._notlari_bosalt()
                    yield (f"YouTube {sira}/{len(konular)} · {konu['ad']} · '{sorgu}' · "
                           f"{self._ekle(bulunan, konu['ad'])} yeni aday")
            adaylar = [v for v in self.videolar if v["platform"] == "YouTube"]
            if adaylar:
                self._dur_mu()
                yield f"Shorts kontrolü · {len(adaylar)} YouTube videosu /shorts/ ile doğrulanıyor…"
                shortlar = {v["id"] for v in self.short_suz(adaylar)}
                self.videolar = [v for v in self.videolar
                                 if v["platform"] != "YouTube" or v["id"] in shortlar]
                yield f"Shorts kontrolü · {len(shortlar)}/{len(adaylar)} video gerçekten Short"

        if "tiktok" in self.platformlar:
            if not self._anahtarlar("apify", "apify_token"):
                yield "TikTok atlandı · Apify token'ı yok (API hesapları › Apify)."
            else:
                toplam = sum(len(k["tiktok"]) for k in konular) * self.adet
                yield (f"TikTok · {len(konular)} alt konu · en fazla {toplam} video · tahmini "
                       f"Apify maliyeti ~{viral_tiktok.maliyet(toplam)} $ (aylık ücretsiz 5 $)…")
                self._dur_mu()
                with ThreadPoolExecutor(3) as havuz:
                    sonuclar = list(havuz.map(lambda k: self._tiktok(k["tiktok"]), konular))
                yield from self._notlari_bosalt()
                for konu, bulunan in zip(konular, sonuclar):
                    yield f"TikTok · {konu['ad']} · {self._ekle(bulunan, konu['ad'])} video"

        if not self.videolar:
            raise RuntimeError("Hiç video bulunamadı. İsteği genişlet ya da zaman aralığını büyüt.")
        for v in self.videolar:
            v["gunluk"] = gunluk_izlenme(v)
        self.videolar.sort(key=lambda v: -v["izlenme"])
        self.ozet = ozet_satirlari(self.videolar, self.esik)
        jsn, csv_yol, txt_yol = self._kaydet(zaman_damgasi)
        kaynak = ", ".join(f"{k} {n}" for k, n in self.kaynak_sayac.items()) or "—"
        viral = sum(1 for v in self.videolar if v["izlenme"] >= self.esik)
        self.sonuc = {"anlasilan": self.plan["anlasilan"], "ozet": self.ozet,
                      "videolar": self.videolar, "json": jsn, "csv": csv_yol, "txt": txt_yol}
        yield (f"Tamamlandı · {len(self.videolar)} video · {viral} viral (≥ {self.esik:,}) · "
               f"kaynaklar: {kaynak}")
