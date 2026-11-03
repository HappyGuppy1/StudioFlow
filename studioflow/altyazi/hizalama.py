"""Sesin kelime zamanlarını Cloudflare whisper ile çözme ve metinle hizalama."""
import base64
import io

import numpy as np
import requests
import soundfile as sf

from studioflow.altyazi.bloklar import tahmini_kelimeler
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.metin import kelime_sayisi
from studioflow.cekirdek.cloudflare_http import CF_API, cf_error

# Cloudflare whisper büyük ses dosyasını tek istekte işlemiyor; sessiz noktalardan bölünür.
SUB_ASR_MODEL = "@cf/openai/whisper-large-v3-turbo"
SUB_ASR_RATE = 16000
SUB_ASR_WINDOW = 45.0
# Hizalama denetimi: whisper zaman zaman sesi yanlış çözer (koca bir cümleyi tek
# kelime olarak döndürür). Hizalanan kelime sayısı, metnin kelime sayısının bu
# oranının altındaysa hizalama güvenilmez sayılır ve zamanlar metinden tahmin edilir.
SUB_ASR_MIN_ORAN = 0.5


def _quiet_cut(mono, rate, target, window=0.08, search=2.5):
    """Kesim noktasını hedefin çevresindeki en sessiz pencereye kaydır: kelime bölünmesin."""
    step = max(int(rate * window), 1)
    low = max(int((target - search) * rate), 0)
    high = min(int((target + search) * rate), max(len(mono) - step, 0))
    if high <= low:
        return max(min(int(target * rate), len(mono)), 0)
    position, energy = low, None
    for start in range(low, high, max(step // 2, 1)):
        part = mono[start:start + step]
        if not len(part):
            continue
        current = float(np.mean(part ** 2))
        if energy is None or current < energy:
            position, energy = start, current
    return position


def _cf_asr(audio_bytes, account, token, language):
    """Bir ses parçasını Cloudflare whisper'a gönder ve sonucu döndür.

    `initial_prompt` **bilinçli olarak gönderilmez**: metnin kendisi prompt olarak
    verildiğinde model onu "zaten yazılmış" sanıp sesi çözmek yerine prompt'u
    tamamlıyor; ölçümde 16 saniyelik anlatım tek kelimeye (`past.`) düşüyordu.
    Prompt'suz istek sesi doğru çözüyor.
    """
    if not (account or "").strip() or not (token or "").strip():
        raise RuntimeError("Cloudflare Account ID ve API token kayıtlı değil.")
    payload = {"audio": base64.b64encode(audio_bytes).decode()}
    if language in LANGUAGES and language != "auto":
        payload["language"] = language
    response = requests.post(f"{CF_API}/accounts/{account.strip()}/ai/run/{SUB_ASR_MODEL}",
                             headers={"Authorization": f"Bearer {token.strip()}"},
                             json=payload, timeout=(20, 300))
    if not response.ok:
        hint = "Altyazı isteği başarısız: "
        if response.status_code in (401, 403):
            hint += ("Cloudflare token'ında 'Account → Workers AI' izni yok. "
                     "Araçlar › Görsel üret sekmesindeki anahtar bölümünden düzelt. ")
        raise RuntimeError(hint + cf_error(response))
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("Cloudflare boş yanıt döndürdü (konuşma tanıma).")
    return result


def cf_listen(audio, account, token, language="tr", offset=0.0):
    """Sesi Cloudflare whisper ile dinle ve kelime zamanlarını döndür.

    Ses 45 saniyeden uzunsa sessiz noktalardan parçalara bölünür; zamanlar
    `offset` (parçanın birleşik ses içindeki başlangıcı) kadar kaydırılır.
    """
    samples, rate = sf.read(audio, dtype="float32", always_2d=True)
    mono = samples.mean(axis=1)
    if rate != SUB_ASR_RATE and len(mono):
        length = max(int(round(len(mono) * SUB_ASR_RATE / rate)), 1)
        mono = np.interp(np.linspace(0, len(mono) - 1, length), np.arange(len(mono)), mono).astype("float32")
    words, start = [], 0
    while start < len(mono):
        end = min(start + int(SUB_ASR_WINDOW * SUB_ASR_RATE), len(mono))
        if end < len(mono):
            end = max(_quiet_cut(mono, SUB_ASR_RATE, end / SUB_ASR_RATE), start + 1)
        buffer = io.BytesIO()
        sf.write(buffer, mono[start:end], SUB_ASR_RATE, format="FLAC")
        body = _cf_asr(buffer.getvalue(), account, token, language)
        base = offset + start / SUB_ASR_RATE
        for segment in body.get("segments") or []:
            for word in segment.get("words") or []:
                text = (word.get("word") or "").strip()
                if text:
                    words.append((base + float(word.get("start") or 0),
                                  base + float(word.get("end") or 0), text))
        start = end
    return words


def align_parts(parts, texts, account, token, language="tr"):
    """Parçaları sırayla dinleyip tek zaman çizelgesinde kelime zamanları üret.

    Edge dışındaki servisler (Gemini, Chatterbox) kelime zamanı vermez; altyazı
    için ses yeniden dinlenir. Bu istekler Cloudflare'in ücretsiz günlük
    neuron kotasından harcar (dakikada ~47 neuron).

    Whisper bir parçayı yanlış çözerse (hizalanan kelime sayısı metnin yarısından
    azsa) o parçanın zamanları `tahmini_kelimeler` ile kurtarılır. Dönüş:
    `(kelimeler, tahmin edilen parça sayısı)`. Böylece tek bir kötü çözümleme
    altyazının tamamını bozmaz.
    """
    words, offset, tahmin = [], 0.0, 0
    for path, text in zip(parts, texts):
        sure = sf.info(path).duration
        bolum = cf_listen(path, account, token, language=language, offset=offset)
        beklenen = kelime_sayisi(text)
        if beklenen and len(bolum) < beklenen * SUB_ASR_MIN_ORAN:
            bolum = tahmini_kelimeler(text, sure, offset)
            tahmin += 1
        words += bolum
        offset += sure
    return words, tahmin


class AltyaziHizalayici:
    """Cloudflare hesabına bağlı hizalayıcı: aynı kimlikle dinle ve parçaları hizala."""

    def __init__(self, account="", token=""):
        self.account = account
        self.token = token

    def dinle(self, audio, language="tr", offset=0.0):
        return cf_listen(audio, self.account, self.token, language=language, offset=offset)

    def parcalari_hizala(self, parts, texts, language="tr"):
        return align_parts(parts, texts, self.account, self.token, language=language)
