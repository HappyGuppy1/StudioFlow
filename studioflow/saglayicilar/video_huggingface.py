"""Hugging Face ZeroGPU Space'lerinde (Wan2.2) fotoğraftan video üretimi.

Video üretimi tek bir Space'e bağlı kalmasın: istek sırayla `VIDEO_SPACELER`de denenir.
Biri uykuda, ZeroGPU kotasını doldurmuş ya da yanıt vermiyorsa sıradakine geçilir ve
kullanıcıya hangi Space'in denendiği yazılır. Tek bir Space zorlamak için `space=`,
sırayı değiştirmek için `saglayicilar=` verilebilir.
"""
import json
import random
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests
from gradio_client import Client, handle_file
from PIL import Image, ImageOps

from studioflow.cekirdek import depolama as _depolama
from studioflow.cekirdek.metin import ilk_satir, negatif_birlestir, sinirla
from studioflow.cekirdek.yollar import ONBELLEK
from studioflow.saglayicilar.taban import VideoSaglayici

VIDEO_SPACELER = (
    "Saravutw/WAN2.2_I2V_LIGHTNING_4-8step_custom",
    "zerogpu-aoti/wan2-2-fp8da-aoti-faster",
    "r3gm/wan2-2-fp8da-aoti-preview",
)
SPACE = VIDEO_SPACELER[0]
SPACE_URL = f"https://huggingface.co/spaces/{SPACE}"

# Space sağlık sorgusu bu süre önbellekte tutulur: adım adım üretimde her adımda
# Hugging Face'e yeniden sorulmaz, ama uzun bir aradan sonra durum tazelenir.
# Hazır olmayan Space daha kısa süre önbellekte kalır ki dalgalanma çabuk görülsün.
SPACE_ONBELLEK_SANIYE = 60
SPACE_HATA_SANIYE = 20
# Üretim sırasında hata veren Space'ler: sıradaki adımlarda en sona alınırlar ki
# çalışan bir Space varsa önce o denensin. Kalıcı değildir; bir süre sonra sıfırlanır.
SORUN_TTL_SANIYE = 900

PROMPT = "The white cat gently turns its head and blinks. A soft sea breeze moves its fur. Small ocean waves move in the background. Slow cinematic camera push in, natural motion, preserve the cat's appearance."
NEGATIVE = "blurry, low quality, deformed, watermark, bad anatomy, shaky camera"

# ── video sınırları: Space'in kendi değerleri ────────────────────────
# Aşağıdaki aralıklar **tahmin değil**: Space'in kaynağından (`MAX_DIM`, `MIN_DIM`,
# `FIXED_FPS = 16`, `MIN_FRAMES_MODEL = 8`, `MAX_FRAMES_MODEL = 160`) ve canlı API
# imzasından (`docs/referans/space-api.json`: "numeric value between 0.5 and 10.0",
# "between 1 and 10", "between 1 and 10") doğrulandı. Kare sayısı
# `1 + clip(round(süre × 16), 8, 160)` olduğu için en uzun klip **10 saniyedir** ve en
# kısa klip 0,5 saniyedir.
FIXED_FPS = 16
MIN_FRAMES = 8
MAX_FRAMES = 160
SURE_ALT, SURE_UST, SURE_VARSAYILAN = 0.5, 10.0, 5.0
ADIM_ALT, ADIM_UST, ADIM_VARSAYILAN = 1, 10, 4
# `quality`: Space'in çıktı kodlaması (değişken bit hızı; 10 en yüksek). Space'in kendi
# varsayılanı 5'tir; 5'te 832×480 klip ~600 kbps çıktı ve 1080p tuvale büyütülünce
# sıkıştırma artığı belirgindi (Turkic-Mythology-8-Monsters, 04.10.2026). Proje akışı bu
# değeri göndermediği için varsayılan doğrudan proje videolarının kalitesidir.
KALITE_ALT, KALITE_UST, KALITE_VARSAYILAN = 1, 10, 10
# `frame_multiplier`: akıcılık. Space son kare hızını bu değere çıkarır (16 → 32 → 64
# → 128). Yükseldikçe araya kare üretimi eklenir: akıcı ama daha yavaş.
FPS_SECENEKLERI = (16, 32, 64, 128)
FPS_VARSAYILAN = 16
# Üretilen klip uzunluğu kare sayısından gelir: 5 sn istesen bile 81 kare = 5,0625 sn
# döner. Proje akışında tuval klibi tam `video.adim_saniye`ye kesilir.
KARE_ADIMI = 1.0 / FIXED_FPS


def fps_sec(deger):
    """`frame_multiplier` seçimini geçerli bir değere indir.

    Space yalnızca 16/32/64/128 kabul eder. Bant içindeki bir değer en yakın seçeneğe
    yuvarlanır (ör. 30 → 32); bandın dışındaki bir değer ise kazayla 8 kat yavaş bir
    üretim başlatmasın diye varsayılana düşer (ör. 999 → 16).
    """
    try:
        sayi = int(float(deger))
    except (TypeError, ValueError):
        return FPS_VARSAYILAN
    if sayi in FPS_SECENEKLERI:
        return sayi
    if min(FPS_SECENEKLERI) <= sayi <= max(FPS_SECENEKLERI):
        return min(FPS_SECENEKLERI, key=lambda kare: abs(kare - sayi))
    return FPS_VARSAYILAN


def kare_sayisi(duration):
    """Space'in `get_num_frames` hesabı: istenen sürenin karşılığı kare sayısı."""
    return 1 + int(max(MIN_FRAMES, min(MAX_FRAMES, round(float(duration) * FIXED_FPS))))


def error_message(exc, token=""):
    message = str(exc)
    if token:
        message = message.replace(token, "[gizli]")
    message = re.sub(r"hf_[A-Za-z0-9]+", "[gizli]", message)
    low = message.lower()
    if any(x in low for x in ("quota", "exceeded", "gpu limit")):
        return "Ücretsiz GPU kotası yetersiz. Hugging Face hesabınla dene veya kotanın yenilenmesini bekle. Ayrıntı: " + message[:800]
    if any(x in low for x in ("401", "unauthorized", "authentication", "sign in", "log in")):
        return "Hugging Face giriş doğrulaması gerekiyor. Hesabından bir erişim tokenı oluşturup uygulamadaki gizli alana gir. Ayrıntı: " + message[:800]
    return message[:1000]


def check_connection(token="", space=SPACE):
    """Space'in şu an kullanılabilir olduğunu doğrula: çalışıyor ve ZeroGPU."""
    space = (space or SPACE).strip() or SPACE
    response = requests.get(f"https://huggingface.co/api/spaces/{space}", timeout=30)
    response.raise_for_status()
    runtime = response.json().get("runtime", {})
    hardware = runtime.get("hardware", {}).get("current", "")
    if not str(hardware).startswith("zero-"):
        raise RuntimeError(f"{space} artık ZeroGPU olarak görünmüyor; ücretsiz kullanım için atlandı.")
    if runtime.get("stage") != "RUNNING":
        raise RuntimeError(f"{space} hazır değil: {runtime.get('stage')}.")
    return f"Bağlantı hazır • ZeroGPU • {space}"


def mp4_bul(deger):
    """Gradio yanıtının içinden ilk indirilebilir MP4 yolunu çıkar."""
    if isinstance(deger, str) and deger.lower().endswith(".mp4") and Path(deger).is_file():
        yield Path(deger)
    elif isinstance(deger, dict):
        for oge in deger.values():
            yield from mp4_bul(oge)
    elif isinstance(deger, (tuple, list)):
        for oge in deger:
            yield from mp4_bul(oge)


class HFVideo(VideoSaglayici):
    """Sırayla denenen Space'ler, sağlık önbelleği ve sorunlu Space listesi tek nesnede."""

    ad = "huggingface"

    def __init__(self, depolama=None, spaceler=VIDEO_SPACELER, onbellek=ONBELLEK):
        self.depolama = depolama or _depolama.VARSAYILAN
        self.spaceler = tuple(spaceler)
        self.onbellek = Path(onbellek)
        self._saglik = {}      # {(space, token var mı): (zaman, (hazır, açıklama))}
        self._sorunlu = {}     # {space: son hata zamanı}

    # ------------------------------------------------------------ sağlık

    def space_kontrol(self, space, token=""):
        """Space erişilebilir mi? `(hazır mı, açıklama)` döndür; **hata yükseltmez**.

        Video üretiminden önce yapılan kontrol burada yapılır: sıradaki Space'ler tek tek
        yoklanır, çalışanların listesi kurulur ve kullanıcı hangi Space'in denendiğini görür.
        """
        space = (space or "").strip()
        if not space:
            return False, "Space adı boş"
        anahtar = (space, bool((token or "").strip()))
        simdi = time.time()
        kayit = self._saglik.get(anahtar)
        if kayit:
            omur = SPACE_ONBELLEK_SANIYE if kayit[1][0] else SPACE_HATA_SANIYE
            if simdi - kayit[0] < omur:
                return kayit[1]
        try:
            check_connection(token, space)
            sonuc = (True, "hazır")
        except Exception as hata:
            sonuc = (False, ilk_satir(error_message(hata, token), 180))
        self._saglik[anahtar] = (simdi, sonuc)
        return sonuc

    def sorunlulari_sifirla(self):
        """Space sağlık ve hata önbelleğini sıfırla.

        Proje akışındaki otomatik yeniden başlatma bunu çağırır: uykudan kalkan ya da
        kotası yenilenen Space bir sonraki denemede **baştan** kontrol edilip sıranın
        önüne geçebilsin. Uzun süreli kullanımda `saglayicilar=` sırası yine korunur.
        """
        self._sorunlu.clear()
        self._saglik.clear()

    def _sira_anahtari(self, space):
        """Sıralama anahtarı: yakın zamanda hata veren Space sona gitsin."""
        son = self._sorunlu.get(space)
        if son is None or time.time() - son >= SORUN_TTL_SANIYE:
            return 0.0
        return son

    def aday_spaceler(self, space=None, saglayicilar=None):
        """Denenecek Space sırası: önce zorlanan Space, sonra verilen sıra, sonra varsayılanlar.

        Yakın zamanda üretim hatası veren Space'ler, çalışanların arkasına alınır.
        """
        adaylar = ([space] if space else []) + list(saglayicilar or []) + list(self.spaceler)
        benzersiz = list(dict.fromkeys(a.strip() for a in adaylar if a and a.strip()))
        return sorted(benzersiz, key=self._sira_anahtari)

    # ------------------------------------------------------------ üretim

    def _tek_space(self, space, prepared, prompt, duration, steps, token, temp, iptal=None,
                   fps=FPS_VARSAYILAN, quality=KALITE_VARSAYILAN, negatif="", cikti_klasor=None):
        """Tek Space'te video üret. Üreteç; başarısızlıkta istisna yükseltir (geçiş çağıranda)."""
        client = Client(space, token=token or None, verbose=False,
                        download_files=temp, analytics_enabled=False,
                        httpx_kwargs={"timeout": 60.0})
        job = None
        # Video negatifi: modülün kendi temel listesi + çağıranın verdiği (projenin
        # görsel negatif prompt'u). Verilmezse davranış eskisiyle birebir aynıdır.
        negative_prompt = negatif_birlestir(NEGATIVE, negatif)
        # Her üretimde yeni seed: sabit 42 ile aynı kare + aynı prompt birebir aynı klibi
        # veriyordu; panelden "sil ve yeniden üret" eski videoyu geri getiriyordu
        # (goldetest, 30.09.2026: 6. sahnenin "yeni" klibi eskisiyle bayt bayt aynıydı).
        seed = random.randint(0, 2**31 - 1)
        try:
            yield "Fotoğraf yükleniyor ve GPU sırasına giriliyor…", None
            job = client.submit(
                input_image=handle_file(str(prepared)), last_image=None,
                prompt=prompt.strip(), steps=int(steps), negative_prompt=negative_prompt,
                duration_seconds=float(duration), guidance_scale=1,
                guidance_scale_2=1, seed=seed, randomize_seed=False, quality=int(quality),
                scheduler="UniPCMultistep", flow_shift=3.0, frame_multiplier=int(fps),
                safe_mode=False, video_component=True, api_name="/generate_video",
            )
            started = time.monotonic()
            while not job.done():
                if iptal is not None and iptal.is_set():
                    job.cancel()
                    raise RuntimeError("Kullanıcı durdurdu.")
                elapsed = int(time.monotonic() - started)
                if elapsed > 600:
                    job.cancel()
                    raise TimeoutError("10 dakika içinde sonuç alınamadı. İptal istendi; uzak sunucuda başlamış işlem sürebilir.")
                status = job.status()
                rank = getattr(status, "rank", None)
                phase = str(getattr(status, "code", ""))
                label = "Video üretiliyor" if "ITERATING" in phase or "PROCESSING" in phase else "GPU sırası / sunucu yanıtı bekleniyor"
                yield f"{label} • {elapsed} sn" + (f" • Sıra: {rank}" if rank is not None else ""), None
                time.sleep(2)
            result = job.result()
            video = next(mp4_bul(result), None)
            if video is None:
                raise RuntimeError("Sunucu yanıt verdi ancak indirilebilir MP4 bulunamadı.")
            if cikti_klasor:
                klasor = Path(cikti_klasor)
                klasor.mkdir(parents=True, exist_ok=True)
            else:
                klasor = self.depolama.hedef_klasoru("")
            output = klasor / f"wan_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.mp4"
            shutil.copy2(video, output)
            output.with_suffix(".json").write_text(json.dumps({
                "space": space, "prompt": prompt, "negative_prompt": negative_prompt,
                "duration_seconds": duration,
                "steps": steps, "fps": fps, "quality": quality, "seed": seed,
                "video": output.name,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            yield f"Tamamlandı. Dosya: {output}", str(output)
        finally:
            if job is not None and not job.done():
                job.cancel()
            client.close()

    def uret(self, image_path, prompt, duration=SURE_VARSAYILAN, steps=ADIM_VARSAYILAN, token="",
             space=None, saglayicilar=None, iptal=None, fps=FPS_VARSAYILAN,
             quality=KALITE_VARSAYILAN, negatif="", hedef_klasor=None):
        """Yield (status, saved_video).

        `hedef_klasor` verilirse (proje üretimi) video ve ara dosyalar yalnızca oraya
        yazılır. Ara dosyalar (hazırlanan kare, sunucudan inen ham video) iş bitince silinir.

        Video Space'leri **sırayla** denenir: her aday önce sağlık kontrolünden geçer; hazır
        olmayan aday atlanır, üretim sırasında hata alan aday elenir ve sıradakine geçilir.
        Bütün adaylar tükenirse toplu hata yükseltilir. Yani tek bir Space'in dalgalanması
        bütün üretimi durdurmaz.

        Süre **0,5–10 saniye** arasındadır (Space: 8–160 kare ÷ 16 fps), adım 1–10, kalite
        1–10, akıcılık 16/32/64/128 fps. Aralık dışı değer hata vermez, kırpılır ve gerçek
        kullanılan değer üretim metninde yazılır.
        """
        if not image_path or not Path(image_path).is_file():
            raise ValueError("Önce bir fotoğraf seç.")
        if not prompt or not prompt.strip():
            raise ValueError("Fotoğrafta olmasını istediğin hareketi yaz.")
        duration = sinirla(duration, SURE_ALT, SURE_UST, SURE_VARSAYILAN, float)
        steps = int(sinirla(steps, ADIM_ALT, ADIM_UST, ADIM_VARSAYILAN, int))
        quality = int(sinirla(quality, KALITE_ALT, KALITE_UST, KALITE_VARSAYILAN, int))
        fps = fps_sec(fps)
        token = (token or "").strip()
        task_id = uuid4().hex
        temp = (Path(hedef_klasor) if hedef_klasor else self.onbellek) / task_id
        temp.mkdir(parents=True, exist_ok=True)
        try:
            yield from self._spacelerde_uret(image_path, prompt, duration, steps, token, space,
                                             saglayicilar, iptal, fps, quality, negatif,
                                             temp, hedef_klasor)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def _spacelerde_uret(self, image_path, prompt, duration, steps, token, space, saglayicilar,
                         iptal, fps, quality, negatif, temp, hedef_klasor):
        """`uret`'in gövdesi: kareyi hazırla, Space'leri sırayla dene."""
        # Decode locally, correct orientation and omit EXIF before uploading.
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1280, 1280))
            prepared = temp / "input.jpg"
            image.save(prepared, quality=95)

        adaylar = self.aday_spaceler(space, saglayicilar)
        hatalar = []
        yield (f"Parametreler: {duration:g} sn (≈{kare_sayisi(duration)} kare) · {steps} adım · "
               f"{fps} fps · kalite {quality} · Space sırası: {len(adaylar)}", None)
        for sira, aday in enumerate(adaylar, 1):
            if iptal is not None and iptal.is_set():
                raise RuntimeError("Kullanıcı durdurdu.")
            yield f"Video Space {sira}/{len(adaylar)} kontrol ediliyor: {aday}…", None
            hazir, sebep = self.space_kontrol(aday, token)
            if not hazir:
                hatalar.append(f"{aday}: {sebep}")
                yield f"{aday} atlandı ({sebep}) · sıradaki video Space'ine geçiliyor.", None
                continue
            yield f"{aday} hazır · üretim bu Space'te başlıyor.", None
            try:
                for durum, dosya in self._tek_space(aday, prepared, prompt, duration, steps, token,
                                                    temp, iptal, fps, quality, negatif,
                                                    hedef_klasor):
                    yield durum, dosya
                return
            except Exception as hata:
                if iptal is not None and iptal.is_set():
                    raise
                self._sorunlu[aday] = time.time()
                mesaj = ilk_satir(error_message(hata, token), 180)
                hatalar.append(f"{aday}: {mesaj}")
                yield (f"{aday} başarısız ({mesaj}) · sıradaki video Space'i denenecek."), None
        raise RuntimeError("Hiçbir video Space'i yanıt vermedi. " + " | ".join(hatalar))


VARSAYILAN = HFVideo()
