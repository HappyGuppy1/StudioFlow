"""Google Lyria RealTime ile enstrümantal müzik üretimi (Gemini API, şimdilik ücretsiz).

Model (`models/lyria-realtime-exp`) müziği bir WebSocket oturumunda **gerçek zamanlı**
akıtır: 48 kHz, stereo, 16 bit ham PCM. Bir dakikalık müzik yaklaşık bir dakikada
gelir; istenen süre dolunca oturum kapatılır ve ses WAV olarak yazılır. Yerel GPU/RAM
kullanılmaz.

- **Telif:** Gemini API şartlarına göre Google üretilen içerik üzerinde hak iddia
  etmez; çıktı atıfsız ve ticari kullanılabilir. Her çıktıda duyulmayan bir **SynthID**
  filigranı vardır (kapatılamaz).
- **Kota:** sınırlar model ve proje başınadır; seslendirme (TTS) kotasından yemez.
  Oturum en fazla 10 dakika sürer, bu yüzden süre `SURE_SINIRI` ile sınırlıdır.
- **Hesaplar:** Gemini hesapları aktif olandan başlayarak denenir; hata alan hesap
  bırakılır ve **aynı servisin sıradaki hesabı** geçer. Anahtar hata metnine yazılmaz.
"""
import asyncio
import time
import warnings
import wave
from pathlib import Path

import numpy as np

from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir

MODEL = "models/lyria-realtime-exp"
HIZMET = "gemini"
ALAN = "gemini_key"
ORNEKLEME, KANAL, GENISLIK = 48000, 2, 2
SURE_SINIRI = (10, 300)            # saniye; oturum sınırı 10 dk, pay bırakılır
BPM_SINIRI = (60, 200)             # 0 = tempo modele bırakılır
PARCA_ZAMAN_ASIMI = 30             # bu kadar sn ses gelmezse oturum takılmış sayılır
BITIS_KARARTMA = 2.0               # kesilen son, bu kadar sn'de yavaşça susar

# SDK her bağlantıda "deneysel" uyarısı basıyor; model zaten `-exp`, günlüğü kirletmesin.
warnings.filterwarnings("ignore", message="Realtime music generation is experimental")


class LyriaHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilebilen hata (anahtar içermez)."""


def sure_siniri(deger):
    try:
        deger = float(deger)
    except (TypeError, ValueError):
        deger = 60.0
    return int(min(max(deger, SURE_SINIRI[0]), SURE_SINIRI[1]))


def bpm_degeri(deger):
    """0 ya da geçersiz → `None` (tempo modele kalır); yoksa sınıra çekilir."""
    try:
        deger = int(float(deger))
    except (TypeError, ValueError):
        return None
    if deger <= 0:
        return None
    return min(max(deger, BPM_SINIRI[0]), BPM_SINIRI[1])


def istemleri_temizle(istemler):
    """`[{"text", "weight"}]` → geçerli olanlar (boş metin atılır, ağırlık 0,1–3)."""
    temiz = []
    for istem in istemler or []:
        if isinstance(istem, str):
            istem = {"text": istem, "weight": 1.0}
        metin = " ".join(str((istem or {}).get("text") or "").split())[:200]
        if not metin:
            continue
        try:
            agirlik = float(istem.get("weight", 1.0))
        except (TypeError, ValueError):
            agirlik = 1.0
        temiz.append({"text": metin, "weight": round(min(max(agirlik, 0.1), 3.0), 2)})
    return temiz[:6]


def karart(pcm, saniye=BITIS_KARARTMA):
    """Kesilen müziğin sonuna doğrusal karartma uygula (16 bit stereo PCM)."""
    ornek = np.frombuffer(pcm, dtype=np.int16).reshape(-1, KANAL).astype(np.float32)
    uzunluk = min(len(ornek), int(saniye * ORNEKLEME))
    if uzunluk > 1:
        ornek[-uzunluk:] *= np.linspace(1.0, 0.0, uzunluk, dtype=np.float32)[:, None]
    return np.clip(ornek, -32768, 32767).astype(np.int16).tobytes()


def wav_yaz(pcm, hedef):
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_suffix(".gecici.wav")
    with wave.open(str(gecici), "wb") as dosya:
        dosya.setnchannels(KANAL)
        dosya.setsampwidth(GENISLIK)
        dosya.setframerate(ORNEKLEME)
        dosya.writeframes(pcm)
    gecici.replace(hedef)
    return hedef


class LyriaMuzik:
    """Lyria RealTime istemcisi; hesap havuzu `api_hesaplari` dosyasından okunur."""

    def __init__(self, hesaplar=None):
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.kullanilan = ""

    def _hesaplar(self):
        adlar = self.hesaplar.hesap_adlari(HIZMET)
        aktif = self.hesaplar.aktif_hesap(HIZMET)
        for ad in ([aktif] if aktif in adlar else []) + [ad for ad in adlar if ad != aktif]:
            anahtar = (self.hesaplar.hesap_degerleri(HIZMET, ad).get(ALAN) or "").strip()
            if anahtar:
                yield ad, anahtar

    def anahtar_var_mi(self):
        return any(True for _ in self._hesaplar())

    async def _oturum(self, anahtar, istemler, sure, bpm, bildir):
        from google import genai
        from google.genai import types

        istemci = genai.Client(api_key=anahtar, http_options={"api_version": "v1alpha"})
        hedef = sure * ORNEKLEME * KANAL * GENISLIK
        ses, filtrelenen = bytearray(), []
        ayar = {"temperature": 1.0, "guidance": 4.0}
        if bpm:
            ayar["bpm"] = bpm
        async with istemci.aio.live.music.connect(model=MODEL) as oturum:
            await oturum.set_weighted_prompts(prompts=[
                types.WeightedPrompt(text=i["text"], weight=i["weight"]) for i in istemler])
            await oturum.set_music_generation_config(
                config=types.LiveMusicGenerationConfig(**ayar))
            await oturum.play()
            son_bildirim = 0.0
            akis = oturum.receive().__aiter__()
            while len(ses) < hedef:
                try:
                    mesaj = await asyncio.wait_for(akis.__anext__(), PARCA_ZAMAN_ASIMI)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise LyriaHatasi(f"{PARCA_ZAMAN_ASIMI} sn boyunca ses gelmedi.")
                if getattr(mesaj, "filtered_prompt", None):
                    filtrelenen.append(str(getattr(mesaj.filtered_prompt, "text", "") or ""))
                    bildir("Güvenlik filtresi bir istemi yok saydı: "
                           + (filtrelenen[-1] or "?"))
                icerik = getattr(mesaj, "server_content", None)
                for parca in (getattr(icerik, "audio_chunks", None) or []):
                    ses.extend(parca.data or b"")
                simdi = time.monotonic()
                if simdi - son_bildirim >= 5:
                    son_bildirim = simdi
                    bildir(f"Müzik akıyor: {len(ses) / hedef * sure:.0f} / {sure} sn")
            try:
                await oturum.stop()
            except Exception:
                pass
        if filtrelenen and len(filtrelenen) >= len(istemler):
            raise LyriaHatasi("Bütün istemler güvenlik filtresine takıldı (sanatçı/şarkı adı "
                              "yazma; tarzı tarif et).")
        return bytes(ses[:hedef])

    def uret(self, istemler, sure, hedef, bpm=None, bildir=None):
        """Müziği üret ve `hedef` WAV dosyasına yaz; yolu döndür.

        `istemler`: `[{"text": "...", "weight": 1.0}, ...]` (İngilizce en iyi sonucu verir).
        Hesaplar sırayla denenir; hiçbiri üretemezse `LyriaHatasi` yükseltilir.
        """
        bildir = bildir or (lambda _mesaj: None)
        istemler = istemleri_temizle(istemler)
        if not istemler:
            raise LyriaHatasi("Müziği tarif eden en az bir istem gerekli.")
        sure = sure_siniri(sure)
        son = "API hesapları sekmesinde Gemini anahtarı yok."
        for ad, anahtar in list(self._hesaplar()):
            bildir(f"Lyria RealTime · '{ad}' hesabıyla bağlanılıyor…")
            try:
                pcm = asyncio.run(self._oturum(anahtar, istemler, sure, bpm_degeri(bpm), bildir))
            except LyriaHatasi as exc:
                if "güvenlik filtresine" in str(exc):
                    raise
                son = f"'{ad}': {exc}"
                bildir(son + " Sıradaki hesap deneniyor.")
                continue
            except Exception as exc:
                son = f"'{ad}': {type(exc).__name__}: {_ilk_satir(exc, 160)}"
                bildir(son + " · sıradaki hesap deneniyor.")
                continue
            if len(pcm) < ORNEKLEME * KANAL * GENISLIK:
                son = f"'{ad}': ses gelmedi."
                bildir(son + " Sıradaki hesap deneniyor.")
                continue
            self.kullanilan = ad
            return wav_yaz(karart(pcm), hedef)
        raise LyriaHatasi("Müzik üretilemedi: " + son)
