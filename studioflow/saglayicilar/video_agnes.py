"""Agnes AI (Sapiens AI, Singapur) ile metinden / fotoğraftan video üretimi.

API OpenAI Videos uyumlu ve **eşzamansızdır**: `POST /v1/videos` bir iş açar, dönen
`video_id` ile `GET /agnesapi?video_id=…&model_name=…` sorgulanır; iş bitince yanıtta
indirilebilir MP4 adresi gelir. Bütün değerler resmi belgeden alınmıştır
(https://wiki.agnes-ai.com/llms.txt · Eylül 2026):

* `agnes-video-2.5-flash` — yalnızca `720P`, 4–12 sn, `seconds` **metin** olarak gider;
  fiyatı şu an **$0** (belge: "sınırlı süreli ücretsiz promosyon").
* `agnes-video-v2.0` — genişlik/yükseklik + kare sayısı (`8n + 1`, ≤ 441) ile çalışır;
  fiyatı şu an **$0**.
* Ücretsiz anahtar: video modellerinde **dakikada 1 istek**; ayrıca belgede sayısı
  verilmeyen bir günlük süre kotası vardır. Sonuç sorgusu da istek sayıldığı için
  sorgular seyrek tutulur ve `429` alınınca beklenip yeniden denenir.

Belge, başlangıç karesini "herkese açık URL" olarak ister; ağ geçidi base64 görselleri
de kabul ettiği için (hata kodları belgesi) fotoğraf küçültülüp **data URI** olarak
gönderilir. Reddedilirse hata metni bunu açıkça söyler.

**Varsayılan model 2.5 Flash, keyframe modunda yalnızca ilk kare** (04.10.2026). V2.0
belgeden kalktı (kapanış duyurusu: 25 Eylül) ve kareye sadık değildi: Turkic-Mythology'de
tek gözlü dev yarım saniyede iki gözlü bir adama döndü, sahne başka bir vadiye geçti. Aynı
kare ve ayrıntılı prompt'la 2.5 Flash keyframe (`first_frame`) kareyi, karakteri ve stili
baştan sona korudu (1248×704 · 24 fps, ~5 dk). `last_frame` kullanıcı kararıyla
gönderilmez: klibi başladığı kareye geri döndürüyordu. Flash negatif prompt almaz;
koruma prompt'un sonuna eklenir (`KORUMA`). Flash kendi ürettiği bir ses izi de ekler,
kayıtta silinir.
"""
import base64
import io
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests
from PIL import Image, ImageOps

from studioflow.cekirdek import depolama as _depolama
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir, sinirla

API_TABAN = "https://apihub.agnes-ai.com/v1"
SONUC_URL = "https://apihub.agnes-ai.com/agnesapi"
PLATFORM_URL = "https://platform.agnes-ai.com"
BELGE_URL = "https://wiki.agnes-ai.com/en/docs/agnes-video-25-flash"

MODEL_FLASH = "agnes-video-2.5-flash"
MODEL_V20 = "agnes-video-v2.0"
# Arayüzde yalnızca 2.5 Flash seçilebilir: V2.0 belgeden kalktı ve kareye sadık değildi
# (bkz. modül başı). Flash'ın ücretsiz kuyruğu dolu dönerse iş açma artan aralıklarla
# yeniden denenir (`KUYRUK_BEKLEMELERI`); başka modele **geçilmez**. V2.0'ın istek
# gövdesi eski kayıtlar için kodda durur.
MODELLER = (
    ("Agnes Video 2.5 Flash · 720P · ilk kareden · ücretsiz", MODEL_FLASH),
)
DESTEKLENEN = (MODEL_FLASH, MODEL_V20)
MODEL_VARSAYILAN = MODEL_FLASH
# Fotoğraftan videoda prompt'un sonuna eklenen koruma: Flash negatif prompt almıyor.
# LTX-2.3'te ölçüldü: "yüze yaklaş" türü kısa prompt'lar ekli değilken kareden koparıp yeni
# bir yüz üretti; bu ekle giden denemelerde kare, karakter ve stil korundu.
KORUMA = (" The camera stays steady or moves only slightly. Keep exactly the same scene, the "
          "same characters with the same faces and the same art style as the first frame; no "
          "new characters, no cuts.")
# Agnes, V2.0'ı bu tarihte kapatacağını duyurdu (belge, 23 Eylül 2026). Sonrasında
# istekler hata verir; uygulama başka modele geçmez, yalnızca sebebi açıkça yazar.
V20_KAPANIS = "25 Eylül 2026 18:59 (Türkiye saati)"

SURE_ALT, SURE_UST, SURE_VARSAYILAN = 4, 12, 5
# V2.0 süreyi kare sayısından alır (`8n + 1`, ≤ 441 kare = 18,3 sn): proje adımlarının
# ondalıklı süreleri (ör. 3,4 sn) de istenebilir.
V20_SURE_ALT, V20_SURE_UST = 0.5, 18.0
ORANLAR = ("9:16", "16:9", "1:1", "4:3", "3:4")
ORAN_VARSAYILAN = "9:16"
# V2.0 genişlik/yükseklik ister; **1080p** katmanındaki karşılıklar (model yakın standart
# ölçüye kendisi eşler: 9:16 → 1088×1920). 24 Eylül 2026 A/B denemesi (aynı kare ve
# prompt, napolyon3 · adım 4): 720p + varsayılan adımda video ~1,6. saniyede sert bir
# kesmeyle kareyi terk edip başka bir sahneye geçti; 1080p + 40 adım + sahne negatifiyle
# ilk kare görselle birebir kaldı, kesme olmadı ve görüntü keskinleşti. Bedeli: bekleme
# süresi ~2 kat (132 → 268 sn); video süresi aynıdır.
V20_OLCU = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080),
            "4:3": (1440, 1080), "3:4": (1080, 1440)}
V20_FPS = 24
V20_KARE_UST = 441
V20_ADIM = 40

# Ücretsiz anahtar dakikada 1 video isteği alır; sonuç sorgusu da sayıldığı için
# seyrek sorgulanır. 429'da bekleme katlanarak uzar (üst sınır 60 sn).
SORGU_ARALIGI = 6
BEKLEME_UST = 60
# Agnes'in video kuyruğu doluysa (HTTP 503 `video_queue_full`) iş hiç açılmaz; bu
# sunucu tarafı yoğunluktur, anahtar sorunu değildir. İş açma, artan aralıklarla
# en çok `KUYRUK_SURE` boyunca yeniden denenir.
KUYRUK_BEKLEMELERI = (20, 40, 60, 90, 120)
KUYRUK_SURE = 10 * 60
# Geçici sayılan (beklenip yeniden denenen) HTTP kodları ve Agnes hata kodları.
GECICI_KODLAR = (429, 502, 503, 504)
GECICI_TURLER = ("video_queue_full",)
ZAMAN_ASIMI = 15 * 60
GORSEL_UST = 1280

PROMPT = ("The white cat gently turns its head and blinks. A soft sea breeze moves its fur. "
          "Small ocean waves move in the background. Slow cinematic camera push in, natural "
          "motion, preserve the cat's appearance.")


class AgnesHatasi(RuntimeError):
    """Agnes API hatası: HTTP kodu (`kod`) ve Agnes'in hata kodu (`tur`, ör. `video_queue_full`)."""

    def __init__(self, kod, tur, mesaj):
        super().__init__(f"HTTP {kod}: " + (f"[{tur}] " if tur else "") + mesaj)
        self.kod, self.tur = kod, tur

    @property
    def gecici(self):
        """Beklenip yeniden denenebilir mi (sınır, kuyruk dolu, sunucu geçici hatası)?"""
        return self.kod in GECICI_KODLAR or self.tur in GECICI_TURLER


def v20_kare_sayisi(saniye):
    """V2.0 kare sayısı: `saniye × 24`'ü **karşılayan** en küçük `8n + 1` (9–441 arası).

    Yukarı yuvarlanır: klip istenen süreden kısa kalmasın (birleştirme fazlasını keser,
    eksiğini tamamlayamaz).
    """
    kare = max(1, math.ceil(float(saniye) * V20_FPS - 1e-9))
    return max(9, min(V20_KARE_UST, 8 * math.ceil((kare - 1) / 8) + 1))


def oran_bul(genislik, yukseklik):
    """Görsel ölçüsüne en yakın desteklenen en-boy oranı (ör. 768×1344 → `9:16`)."""
    try:
        hedef = float(genislik) / float(yukseklik)
    except (TypeError, ValueError, ZeroDivisionError):
        return ORAN_VARSAYILAN
    return min(ORANLAR, key=lambda oran: abs(int(oran.split(":")[0]) / int(oran.split(":")[1])
                                            - hedef))


def hata_metni(exc, anahtar=""):
    """Hata metnini kullanıcı diline çevir; anahtarı asla göstermez."""
    mesaj = str(exc)
    if anahtar:
        mesaj = mesaj.replace(anahtar, "[gizli]")
    mesaj = re.sub(r"Bearer\s+\S+", "Bearer [gizli]", mesaj)
    kucuk = mesaj.lower()
    if ("retire" in kucuk or "deprecat" in kucuk or "not found" in kucuk or "404" in kucuk
            or ("model" in kucuk and ("not exist" in kucuk or "not support" in kucuk
                                      or "unavailable" in kucuk or "invalid" in kucuk))):
        return ("Agnes video modeli yanıt vermedi; model kullanımdan kalkmış olabilir. Başka "
                "modele geçilmedi, video üretilmedi. Ayrıntı: " + mesaj[:300])
    if "queue is full" in kucuk or "video_queue_full" in kucuk:
        return ("Agnes AI'ın video kuyruğu dolu: sunucu şu an yoğun, istek kuyruğa alınamadı. "
                "Anahtarın çalışıyor; bu Agnes tarafındaki geçici bir yoğunluk. Uygulama "
                f"{KUYRUK_SURE // 60} dakika boyunca yeniden denedi. Biraz sonra tekrar dene. "
                "Ayrıntı: " + mesaj[:300])
    if "token not provided" in kucuk or "401" in kucuk or "403" in kucuk or "unauthorized" in kucuk:
        return ("Agnes AI anahtarı geçersiz ya da girilmemiş. **API hesapları** sekmesinde "
                f"Agnes AI anahtarını kaydet ({PLATFORM_URL} → API key). Ayrıntı: " + mesaj[:400])
    if "429" in kucuk or "too many" in kucuk or "quota" in kucuk:
        return ("Agnes AI sınırı doldu: ücretsiz anahtar dakikada 1 video isteği ve günlük bir "
                "süre kotası alır. Biraz bekleyip yeniden dene. Ayrıntı: " + mesaj[:400])
    if "image" in kucuk and ("url" in kucuk or "base64" in kucuk or "invalid" in kucuk):
        return ("Agnes AI fotoğrafı kabul etmedi (belge herkese açık bir görsel adresi istiyor; "
                "fotoğraf dosya içeriği olarak gönderildi). Fotoğrafsız, yalnızca metinle "
                "deneyebilirsin. Ayrıntı: " + mesaj[:400])
    return mesaj[:800]


def _data_uri(image_path):
    """Fotoğrafı döndür, EXIF'i at, en çok 1280 px'e küçült ve JPEG data URI'ye çevir."""
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((GORSEL_UST, GORSEL_UST))
        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def _video_adresi(veri):
    """Sonuç yanıtındaki MP4 adresi: 2.5'te `url`, V2.0'da `metadata.url`."""
    for aday in (veri.get("url"), (veri.get("metadata") or {}).get("url"),
                 veri.get("video_url")):
        if isinstance(aday, str) and aday.startswith("http"):
            return aday
    return None


class AgnesVideo:
    """Agnes AI video API'si: iş aç → seyrek sorgula → MP4'ü indir ve kaydet."""

    ad = "agnes"

    def __init__(self, depolama=None, oturum=None):
        self.depolama = depolama or _depolama.VARSAYILAN
        self.oturum = oturum or requests.Session()

    def _basliklar(self, anahtar):
        return {"Authorization": f"Bearer {anahtar}", "Content-Type": "application/json"}

    def _istek(self, yontem, url, anahtar, **kw):
        yanit = self.oturum.request(yontem, url, headers=self._basliklar(anahtar),
                                    timeout=60, **kw)
        if yanit.status_code >= 400:
            # İki biçim görülür: `{"error": {"message": …}}` ve `{"code": …, "message": …}`.
            try:
                govde = yanit.json()
            except ValueError:
                govde = {}
            hata = govde.get("error") if isinstance(govde.get("error"), dict) else {}
            tur = str(hata.get("code") or govde.get("code") or "")
            ayrinti = hata.get("message") or govde.get("message") or yanit.text
            raise AgnesHatasi(yanit.status_code, tur, ilk_satir(ayrinti, 400))
        return yanit.json()

    @staticmethod
    def _bekle(saniye, iptal=None):
        """`saniye` kadar bekle; durdurma istenirse hemen çık."""
        bitis = time.monotonic() + saniye
        while time.monotonic() < bitis:
            if iptal is not None and iptal.is_set():
                raise RuntimeError("Kullanıcı durdurdu.")
            time.sleep(min(1.0, max(0.0, bitis - time.monotonic())))

    def _is_ac(self, govde, anahtar, iptal=None):
        """İşi aç; kuyruk dolu / sınır / geçici sunucu hatasında artan aralıklarla yeniden dene.

        Üreteç: bekleme sırasında durum metinleri verir, sonunda `("", yanıt)` döner.
        """
        basla = time.monotonic()
        for deneme in range(1, 1000):
            try:
                yield "", self._istek("POST", f"{API_TABAN}/videos", anahtar, json=govde)
                return
            except AgnesHatasi as hata:
                gecen = time.monotonic() - basla
                bekleme = KUYRUK_BEKLEMELERI[min(deneme, len(KUYRUK_BEKLEMELERI)) - 1]
                if not hata.gecici or gecen + bekleme > KUYRUK_SURE:
                    raise
                neden = ("Agnes video kuyruğu dolu" if hata.tur == "video_queue_full"
                         else "Agnes sınırı doldu" if hata.kod == 429
                         else f"Agnes sunucusu geçici hata verdi (HTTP {hata.kod})")
                yield (f"{neden} · {bekleme} sn sonra yeniden denenecek "
                       f"(deneme {deneme}, {int(gecen)} sn geçti)"), None
                self._bekle(bekleme, iptal)

    def kontrol(self, anahtar):
        """Anahtar geçerli mi? `/v1/models` ile dener; açıklama döner, olmazsa hata yükseltir."""
        anahtar = (anahtar or "").strip()
        if not anahtar:
            raise ValueError("Token not provided: Agnes AI anahtarı kayıtlı değil.")
        veri = self._istek("GET", f"{API_TABAN}/models", anahtar)
        adlar = {m.get("id") for m in veri.get("data") or [] if isinstance(m, dict)}
        if adlar and MODEL_FLASH not in adlar:
            # Model listeden düşerse üretimi denemeden önce söylenir.
            return (f"Agnes AI anahtarı geçerli, ama **{MODEL_FLASH}** hesabın model listesinde "
                    "yok; model kapatılmış olabilir. Başka modele geçilmez; video üretilemez.")
        return (f"Agnes AI bağlantısı hazır · anahtar geçerli · {MODEL_FLASH} kullanılabilir. "
                "Ücretsiz anahtar dakikada 1 video isteği alır.")

    def istek_govdesi(self, model, prompt, saniye, oran, gorsel=None, negatif=""):
        """Modele göre `POST /v1/videos` gövdesi (belgedeki alan adlarıyla).

        Negatif prompt yalnızca V2.0'da vardır; 2.5 Flash bu alanı tanımlamaz.
        """
        if model == MODEL_V20:
            genislik, yukseklik = V20_OLCU.get(oran, V20_OLCU[ORAN_VARSAYILAN])
            govde = {"model": model, "prompt": prompt, "width": genislik, "height": yukseklik,
                     "num_frames": v20_kare_sayisi(saniye), "frame_rate": V20_FPS,
                     "num_inference_steps": V20_ADIM}
            if gorsel:
                govde["image"] = gorsel
            if (negatif or "").strip():
                govde["negative_prompt"] = negatif.strip()
            return govde
        govde = {"model": model, "prompt": prompt, "seconds": str(int(saniye)),
                 "size": "720P", "aspect_ratio": oran, "n": 1}
        if gorsel:
            govde.update(mode="keyframe", first_frame=gorsel)
        else:
            govde["mode"] = "text"
        return govde

    def uret(self, image_path, prompt, model=MODEL_VARSAYILAN, saniye=SURE_VARSAYILAN,
             oran=ORAN_VARSAYILAN, anahtar="", iptal=None, negatif="", hedef_klasor=None):
        """`(durum, kaydedilen video yolu ya da None)` çiftleri üretir.

        Fotoğraf verilirse ilk kare olarak kullanılır (fotoğraftan video); verilmezse
        yalnızca metinden video üretilir. Süre V2.0'da 0,5–18 sn (ondalıklı olabilir),
        2.5 Flash'ta 4–12 sn tam sayıdır. `hedef_klasor` verilirse (proje üretimi) video
        yalnızca oraya indirilir.
        """
        anahtar = (anahtar or "").strip()
        if not anahtar:
            raise ValueError("Token not provided: Agnes AI anahtarı kayıtlı değil.")
        if not prompt or not prompt.strip():
            raise ValueError("Videoda olmasını istediğin hareketi yaz.")
        model = model if model in DESTEKLENEN else MODEL_VARSAYILAN
        if model == MODEL_V20:
            saniye = round(sinirla(saniye, V20_SURE_ALT, V20_SURE_UST, SURE_VARSAYILAN, float), 2)
        else:
            # Yukarı yuvarlanır: 3,4 sn'lik sahne 4 sn istenir (en az 4); klip istenen
            # süreden kısa kalmasın, fazlasını birleştirme keser.
            saniye = int(sinirla(math.ceil(float(saniye or SURE_VARSAYILAN) - 1e-9),
                                 SURE_ALT, SURE_UST, SURE_VARSAYILAN, int))
        oran = oran if oran in ORANLAR else ORAN_VARSAYILAN
        gorsel = None
        if image_path:
            if not Path(image_path).is_file():
                raise ValueError("Seçilen fotoğraf bulunamadı.")
            gorsel = _data_uri(image_path)
        tur = "fotoğraftan" if gorsel else "metinden"
        if gorsel and model == MODEL_FLASH:
            prompt = prompt.strip() + KORUMA
        yield f"Parametreler: {model} · {saniye:g} sn · {oran} · {tur} video · iş açılıyor…", None
        govde = self.istek_govdesi(model, prompt.strip(), saniye, oran, gorsel, negatif)
        is_ = None
        for durum, yanit in self._is_ac(govde, anahtar, iptal):
            if yanit is not None:
                is_ = yanit
            else:
                yield durum, None
        video_id = is_.get("video_id") or is_.get("id") or is_.get("task_id")
        if not video_id:
            raise RuntimeError("Agnes AI iş kimliği döndürmedi: " + ilk_satir(json.dumps(is_), 300))
        yield f"İş açıldı ({video_id}) · sırada…", None

        basla = time.monotonic()
        bekleme = SORGU_ARALIGI
        while True:
            if iptal is not None and iptal.is_set():
                raise RuntimeError("Kullanıcı durdurdu. Uzak sunucuda başlamış iş sürebilir.")
            gecen = int(time.monotonic() - basla)
            if gecen > ZAMAN_ASIMI:
                raise TimeoutError(f"{ZAMAN_ASIMI // 60} dakika içinde sonuç alınamadı ({video_id}).")
            self._bekle(bekleme, iptal)
            try:
                veri = self._istek("GET", SONUC_URL, anahtar,
                                   params={"video_id": video_id, "model_name": model})
            except AgnesHatasi as hata:
                if not hata.gecici:
                    raise
                # Sorgu da dakikalık sınıra sayılır: vazgeçmeden daha seyrek sor.
                bekleme = min(BEKLEME_UST, bekleme * 2)
                yield (f"Agnes geçici olarak yanıt vermedi (HTTP {hata.kod}), {bekleme} sn sonra "
                       f"yeniden sorulacak • {gecen} sn"), None
                continue
            bekleme = SORGU_ARALIGI
            durum = str(veri.get("status") or "").lower()
            if durum == "failed":
                ayrinti = (veri.get("error") or {}).get("message") or "Video üretilemedi."
                raise RuntimeError(f"Agnes AI işi başarısız: {ayrinti}")
            adres = _video_adresi(veri)
            if durum == "completed" or (adres and durum not in ("queued", "in_progress")):
                if not adres:
                    raise RuntimeError("İş tamamlandı ama indirilebilir video adresi gelmedi.")
                break
            ilerleme = veri.get("progress")
            yield (("Video üretiliyor" if durum == "in_progress" else "Sırada bekleniyor")
                   + (f" • %{ilerleme}" if ilerleme not in (None, "") else "")
                   + f" • {gecen} sn"), None

        yield "Video indiriliyor…", None
        if hedef_klasor:
            klasor = Path(hedef_klasor)
            klasor.mkdir(parents=True, exist_ok=True)
        else:
            klasor = self.depolama.hedef_klasoru("")
        cikti = klasor / f"agnes_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.mp4"
        ham = cikti.with_name(cikti.stem + "-ham.mp4")
        with self.oturum.get(adres, stream=True, timeout=120) as yanit:
            yanit.raise_for_status()
            with open(ham, "wb") as dosya:
                for parca in yanit.iter_content(1 << 16):
                    dosya.write(parca)
        # Flash klibe kendi ürettiği bir ses izi (müzik) ekliyor: kayıtta silinir.
        FFMPEG.sessiz_kopyala(ham, cikti)
        ham.unlink(missing_ok=True)
        cikti.with_suffix(".json").write_text(json.dumps({
            "servis": "agnes", "model": model, "prompt": prompt, "seconds": saniye,
            "aspect_ratio": oran, "fotograf": bool(gorsel), "video_id": video_id,
            "boyut": veri.get("size"), "video": cikti.name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        yield f"Tamamlandı ({int(time.monotonic() - basla)} sn). Dosya: {cikti}", str(cikti)


VARSAYILAN = AgnesVideo()
