"""Hugging Face ZeroGPU'daki Lightricks LTX-2.3 Space'iyle fotoğraftan video üretimi.

Neden: Wan2.2 Space'leri en fazla 832×480 ve 16 fps üretiyor (`MAX_DIM = 832`); 1080p
tuvale 2,25 kat büyütülünce görüntü yumuşuyordu. Agnes 1080p veriyor ama kareye sadık
kalmıyor: Turkic-Mythology-8-Monsters'ta (04.10.2026) ilk yarım saniyede tek gözlü dev iki
gözlü bir adama döndü, sahne başka bir vadiye geçti. LTX-2.3 aynı denemede kareyi (tek göz,
kayalık, stil) baştan sona korudu ve **1280×704 · 24 fps** verdi; 3, 5 ve 8 saniyelik
klipler ücretsiz hesapla ~45 sn'de üretildi.

Sınırlar (ölçüldü): Space'in varsayılan yüksek çözünürlüğü (1536×1024; 16:9 için
1536×864) ücretsiz hesapta **sonuçsuz** döndü (video yerine `None`), muhtemelen ZeroGPU
çağrı süresi yetmiyor; güvenilir üst sınır 1280×704'tür. Space kendi ürettiği bir ses
izi (müzik) de ekler: klip kaydedilirken bu iz silinir (`FFMPEG.sessiz_kopyala`), çünkü sahne
klipleri atölyede ve önizlemede tek tek oynatılıyor; seslendirme ve müzik projeye
sonradan ayrıca eklenir.

Kendi Space'imiz (22.10.2026): resmî Space'te istekler `Waiting for a GPU slot on this Space`
kuyruğunda bekliyor, 60 sn'de GPU alamayan her deneme ("No GPU was available") hesabın
ZeroGPU kotasından **75 sn** yiyordu (HF quota uç noktasıyla ölçüldü). `KENDI_SPACELER` aynı
kodun kopyasıdır; yuvaları yalnızca bizimdir, kuyruk oluşmaz (3 eşzamanlı istekte ölçüldü,
video başına ~37 sn kota). Space erişim anahtarıyla kilitlidir (`ANAHTAR_DOSYA`); anahtarsız
istek GPU sırasına girmeden reddedilir. Kendi Space'imiz çalışmıyorsa resmî Space'e dönülür.
"""
import json
import random
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests
from gradio_client import Client, handle_file
from PIL import Image, ImageOps

from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.hatalar import gpu_yok_mu
from studioflow.cekirdek.yollar import AYAR_KLASORU
from studioflow.saglayicilar.video_huggingface import mp4_bul

SPACE = "Lightricks/LTX-2-3"
SPACE_URL = f"https://huggingface.co/spaces/{SPACE}"
# Kendi Space'lerimiz, deneme sırasıyla (hepsi aynı kodun kopyası, aynı erişim anahtarı):
# `SPACE_DOSYA`'da her satıra bir `kullanici/space-adi`. Dosya yoksa resmî Space kullanılır.
# Bir Space günde ~90 videodan sonra her isteğe "No GPU" verebiliyor; aynı dakikalarda resmî
# Space kuyruksuz çalışıyordu. GPU vermeyen Space `GPU_YOK_BEKLEME` boyunca atlanır,
# sıradakine (en sonda resmî Space'e) geçilir.
SPACE_DOSYA = AYAR_KLASORU / "ltx-spaceler.txt"


def _kendi_spaceler():
    try:
        satirlar = SPACE_DOSYA.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ()
    return tuple(s.strip() for s in satirlar if s.strip() and not s.strip().startswith("#"))


KENDI_SPACELER = _kendi_spaceler()
GPU_YOK_BEKLEME = 30 * 60
# Çoklu üretimde gruplar Space'lere sırayla bölünür (grup 1 → 1. Space, grup 2 → 2. …); bir
# Space son 24 saatte bu kadar video ürettiyse atlanır (~90'da kesildiği ölçüldü).
GUNLUK_SINIR = 80
SAYAC_DOSYA = AYAR_KLASORU / "ltx-space-sayac.json"
ANAHTAR_DOSYA = AYAR_KLASORU / "ltx-space-erisim.txt"
# Kendi Space'imize aynı anda giden istek sınırı (çoklu üretimde grup sayısı). 3'te ölçüldü:
# üçü de kuyruksuz GPU aldı. Daha yükseği ölçülmeden artırma.
ESZAMANLI = 3
SECIM_SANIYE = 60                  # hangi Space'in kullanılacağı bu süre önbellekte kalır
SURE_ALT, SURE_UST = 1.0, 8.0
# Oranına göre çıktı ölçüsü: kenarlar 32'nin katı (Space ölçüyü buna yuvarlıyor).
OLCULER = {"yatay": (1280, 704), "dikey": (704, 1280), "kare": (960, 960)}
ZAMAN_ASIMI = 600
# Her hareket prompt'unun sonuna eklenen koruma: Space negatif prompt almıyor. Ölçüldü
# (04.10.2026, adim-01): "Slow push-in toward giant's face" tek başına gidince LTX kareden
# kopup **iki gözlü yeni bir yüz** üretti; bu ekle giden 3/5/8 sn denemelerinde tek göz,
# sahne ve stil baştan sona korundu.
KORUMA = (" The camera stays steady or moves only slightly. Keep exactly the same scene, the "
          "same characters with the same faces and the same art style as the first frame; no "
          "new characters, no cuts.")


def olcu_sec(genislik, yukseklik):
    """Karenin oranına en yakın çıktı ölçüsü: yatay · dikey · kare."""
    oran = float(genislik) / float(yukseklik or 1)
    if oran >= 1.2:
        return OLCULER["yatay"]
    if oran <= 1 / 1.2:
        return OLCULER["dikey"]
    return OLCULER["kare"]


def erisim_anahtari():
    """Kendi Space'imizin erişim anahtarı; dosya yoksa boş (o zaman resmî Space kullanılır)."""
    try:
        return ANAHTAR_DOSYA.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def hata_metni(hata, token=""):
    """Hata metninden token'ı ve erişim anahtarını ayıkla; kota hatası 'kota' kelimesini taşır."""
    metin = str(hata)
    for gizli in (token, erisim_anahtari()):
        if gizli:
            metin = metin.replace(gizli, "[gizli]")
    metin = re.sub(r"hf_[A-Za-z0-9]+", "[gizli]", metin)
    if any(k in metin.lower() for k in ("quota", "exceeded", "gpu limit")):
        return "LTX-2.3 · ücretsiz GPU kotası doldu. Ayrıntı: " + metin[:600]
    return metin[:800]


class LTXVideo:
    ad = "ltx"

    def __init__(self):
        self._secim = {}                # başlangıç sırası → (zaman, space, ek parametreler, açıklama)
        self._gpu_yok = {}              # space → GPU vermediği an (monotonic)
        self._kilit = threading.Lock()
        self._yerel = threading.local()

    @contextmanager
    def space_sabitle(self, sira):
        """Çoklu üretimde bu iş parçacığının grubu: `sira`. Space'ler bu sıradan başlanarak denenir."""
        self._yerel.sira = sira
        try:
            yield
        finally:
            self._yerel.sira = None

    def gpu_yok_isaretle(self, space):
        """Space GPU vermedi: `GPU_YOK_BEKLEME` boyunca seçilmez."""
        with self._kilit:
            self._gpu_yok[space] = time.monotonic()
            self._secim.clear()

    def _gpu_vermiyor(self, space):
        zaman = self._gpu_yok.get(space)
        return zaman is not None and time.monotonic() - zaman < GPU_YOK_BEKLEME

    @staticmethod
    def _sayac_oku():
        """`{space: [başarılı video zamanları (epoch)]}`; yalnızca son 24 saat."""
        try:
            veri = json.loads(SAYAC_DOSYA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        sinir = time.time() - 24 * 3600
        return {space: [z for z in zamanlar if z > sinir] for space, zamanlar in veri.items()}

    def _sayac_ekle(self, space):
        with self._kilit:
            veri = self._sayac_oku()
            veri.setdefault(space, []).append(time.time())
            try:
                SAYAC_DOSYA.write_text(json.dumps(veri), encoding="utf-8")
            except OSError:
                pass
            if len(veri[space]) >= GUNLUK_SINIR:
                self._secim.clear()

    @staticmethod
    def _space_durumu(space, token=""):
        """Space çalışıyor ve ZeroGPU mu? `(hazır mı, açıklama)`; hata yükseltmez."""
        try:
            yanit = requests.get(f"https://huggingface.co/api/spaces/{space}", timeout=30,
                                 headers={"Authorization": f"Bearer {token}"} if token else None)
            yanit.raise_for_status()
            calisma = yanit.json().get("runtime") or {}
        except Exception as hata:
            return False, hata_metni(hata, token)
        donanim = str((calisma.get("hardware") or {}).get("current") or "")
        if calisma.get("stage") != "RUNNING":
            return False, f"{space} hazır değil: {calisma.get('stage')}"
        if not donanim.startswith("zero-"):
            return False, f"{space} artık ZeroGPU görünmüyor ({donanim})"
        return True, f"{space} hazır · ZeroGPU"

    def space_sec(self, token=""):
        """Kullanılacak Space: `(space, ek parametreler, açıklama)`.

        Anahtar kayıtlıysa çalışan, günlük sınırı dolmamış ve yakın zamanda GPU reddetmemiş
        ilk kendi Space'imiz; çoklu üretimde arama grubun sırasındaki Space'ten başlar (bkz.
        `space_sabitle`). Hiçbiri yoksa resmî Space. Seçim `SECIM_SANIYE` boyunca önbellekte
        kalır (çoklu üretimde her adım sorgu atmasın).
        """
        sira = getattr(self._yerel, "sira", None) or 0
        bas = sira % (len(KENDI_SPACELER) or 1)
        with self._kilit:
            onbellek = self._secim.get(bas)
            if onbellek and time.monotonic() - onbellek[0] < SECIM_SANIYE:
                return onbellek[1:]
            anahtar = erisim_anahtari()
            if not KENDI_SPACELER:
                secim = (SPACE, {}, f"kendi Space listesi yok ({SPACE_DOSYA.name}); resmî Space kullanılıyor")
            elif anahtar:
                secim, sebepler, sayac = None, [], self._sayac_oku()
                for space in KENDI_SPACELER[bas:] + KENDI_SPACELER[:bas]:
                    if self._gpu_vermiyor(space):
                        sebepler.append(f"{space} GPU vermiyor")
                        continue
                    if len(sayac.get(space, ())) >= GUNLUK_SINIR:
                        sebepler.append(f"{space} günlük {GUNLUK_SINIR} video sınırında")
                        continue
                    hazir, sebep = self._space_durumu(space, token)
                    if hazir:
                        secim = (space, {"erisim_anahtari": anahtar}, f"{sebep} (kendi Space'imiz)")
                        break
                    sebepler.append(sebep)
                if secim is None:
                    secim = (SPACE, {}, f"kendi Space'lerimiz kullanılamıyor "
                                        f"({'; '.join(sebepler)}); resmî Space'e dönüldü")
            else:
                secim = (SPACE, {}, f"erişim anahtarı yok ({ANAHTAR_DOSYA.name}); resmî Space kullanılıyor")
            self._secim[bas] = (time.monotonic(), *secim)
            return secim

    def space_kontrol(self, token=""):
        """Kullanılacak Space hazır mı? `(hazır mı, açıklama)`; hata yükseltmez."""
        with self._kilit:
            self._secim.clear()         # her çalışma başında taze seçim
        space, _ek, aciklama = self.space_sec(token)
        if space in KENDI_SPACELER:
            return True, aciklama
        hazir, sebep = self._space_durumu(SPACE, token)
        return hazir, f"{aciklama} · {sebep}"

    def uret(self, image_path, prompt, duration, token="", iptal=None, hedef_klasor=None):
        """`(durum, video yolu ya da None)` üretir; başarısızlıkta istisna yükseltir."""
        if not image_path or not Path(image_path).is_file():
            raise ValueError("Önce bir fotoğraf seç.")
        if not (prompt or "").strip():
            raise ValueError("Fotoğrafta olmasını istediğin hareketi yaz.")
        sure = max(SURE_ALT, min(SURE_UST, float(duration or SURE_UST)))
        token = (token or "").strip()
        temp = Path(hedef_klasor) if hedef_klasor else Path.cwd() / ".calisma"
        temp = temp / f"ltx-{uuid4().hex}"
        temp.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(image_path) as resim:
                resim = ImageOps.exif_transpose(resim).convert("RGB")
                genislik, yukseklik = olcu_sec(*resim.size)
                hazir = temp / "input.jpg"
                resim.save(hazir, quality=95)
            yield f"LTX-2.3 · {genislik}×{yukseklik} · {sure:g} sn · GPU sırasına giriliyor…", None
            while True:
                space, ek, _aciklama = self.space_sec(token)
                try:
                    yield from self._calistir(space, ek, hazir, prompt.strip() + KORUMA, sure,
                                              genislik, yukseklik, token, iptal, temp, hedef_klasor)
                    if space in KENDI_SPACELER:
                        self._sayac_ekle(space)
                    return
                except Exception as hata:
                    # Kendi Space'imiz GPU vermedi: aynı adım hemen sıradaki Space'le denenir.
                    if space not in KENDI_SPACELER or not gpu_yok_mu(hata):
                        raise
                    self.gpu_yok_isaretle(space)
                    yield (f"LTX-2.3 · {space} GPU vermedi; {GPU_YOK_BEKLEME // 60} dk atlanacak, "
                           "sıradaki Space deneniyor…"), None
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def _calistir(self, space, ek, hazir, prompt, sure, genislik, yukseklik, token, iptal, temp,
                  hedef_klasor):
        istemci = Client(space, token=token or None, verbose=False, download_files=temp,
                         analytics_enabled=False, httpx_kwargs={"timeout": 60.0})
        is_ = None
        try:
            is_ = istemci.submit(
                input_image=handle_file(str(hazir)), prompt=prompt, duration=float(sure),
                enhance_prompt=False, seed=random.randint(0, 2**31 - 1), randomize_seed=False,
                height=int(yukseklik), width=int(genislik), api_name="/generate_video", **ek)
            basla = time.monotonic()
            while not is_.done():
                if iptal is not None and iptal.is_set():
                    is_.cancel()
                    raise RuntimeError("Kullanıcı durdurdu.")
                gecen = int(time.monotonic() - basla)
                if gecen > ZAMAN_ASIMI:
                    is_.cancel()
                    raise TimeoutError("LTX-2.3 10 dakika içinde sonuç vermedi.")
                yield f"LTX-2.3 · video üretiliyor • {gecen} sn", None
                time.sleep(2)
            video = next(mp4_bul(is_.result()), None)
            if video is None:
                # Ölçüldü: GPU süresi yetmeyince Space hata değil boş sonuç döndürüyor.
                # Metin "kota" taşır ki hesap sırası sıradaki hesaba geçsin.
                raise RuntimeError("LTX-2.3 video döndürmedi: hesabın GPU kotası yetmemiş olabilir.")
            klasor = Path(hedef_klasor) if hedef_klasor else temp.parent
            klasor.mkdir(parents=True, exist_ok=True)
            cikti = klasor / f"ltx_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.mp4"
            FFMPEG.sessiz_kopyala(video, cikti)
            yield f"LTX-2.3 · tamamlandı: {cikti.name}", str(cikti)
        finally:
            if is_ is not None and not is_.done():
                is_.cancel()
            istemci.close()


VARSAYILAN = LTXVideo()
