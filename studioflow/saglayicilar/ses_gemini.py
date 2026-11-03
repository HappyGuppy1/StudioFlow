"""Gemini TTS: REST üzerinden seslendirme (Interactions API ve generateContent)."""
import base64
import io
import json
import re

import numpy as np
import requests
import soundfile as sf

from studioflow.cekirdek.diller import LANGUAGES
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS, http_json
from studioflow.saglayicilar.taban import SesSaglayici


def gemini_prompt(text, language, style):
    """TTS istemi: yönetmen notu ile okunacak metin ayrı, etiketli bloklardadır.

    claudetest3 (29.09.2026): sahne sahne ipucu içeren stil ("Quiet and heavy at waking,
    flat and hungry at breakfast…") eskiden "Delivery: …" diye metnin hemen önüne
    yazılıyordu; model bunu anlatım sanıp 24 saniye boyunca sesli okudu (151 kelime
    114 sn sürdü). Not bloğu açıkça "asla söylenmez" diye işaretlenir ve okunacak ilk
    kelime ayrıca belirtilir.
    """
    if language not in LANGUAGES:
        raise ValueError("Geçersiz dil seçimi.")
    ilk = (text or "").split()[:3]
    return ("Synthesize speech. Speak ONLY the transcript between TRANSCRIPT BEGIN and "
            "TRANSCRIPT END, exactly as written. Do not translate, summarize or add words.\n"
            "VOICE DIRECTION (never spoken; it only describes how to sound):\n"
            f"[{style.strip() or 'Natural, conversational narration'}]\n"
            f"Language: {LANGUAGES[language]}. The first spoken words are: "
            f"\"{' '.join(ilk)}\".\n"
            f"TRANSCRIPT BEGIN\n{text}\nTRANSCRIPT END")


AUDIO_KEYS = ("outputaudio", "inlinedata", "audio", "audiodata")


def find_audio_blocks(value, key=""):
    """Yanıtın hangi şekilde geldiğine bakmadan base64 ses bloklarını topla.

    REST katmanı alanları camelCase verir (outputAudio, inlineData, mimeType);
    SDK örnekleri snake_case gösterir. İkisi de, iç içe geçmiş biçimleri de kabul edilir.
    """
    blocks = []
    if isinstance(value, dict):
        data = value.get("data")
        mime = str(value.get("mimeType") or value.get("mime_type") or "")
        if isinstance(data, str) and data and ("audio" in mime.lower() or "l16" in mime.lower()
                                               or key.replace("_", "").lower() in AUDIO_KEYS):
            blocks.append({"data": data, "mime_type": mime or "audio/pcm;rate=24000"})
        else:
            for name, item in value.items():
                blocks += find_audio_blocks(item, name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            blocks += find_audio_blocks(item, key)
    return blocks


def describe_response(body):
    """Tanı için yanıtın yapısını özetle. Base64 ses ve anahtar taşımaz."""
    notes = []
    if isinstance(body, dict):
        notes.append("Yanıt alanları: " + ", ".join(sorted(body)[:12]))
        for field in ("finishReason", "finish_reason", "blockReason", "block_reason", "refusal", "status"):
            for found in re.findall(rf'"{field}"\s*:\s*"([^"]{{0,60}})"', json.dumps(body)):
                notes.append(f"{field}: {found}")
        message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else None
        if message:
            notes.append("Sunucu mesajı: " + str(message)[:200])
    return " · ".join(dict.fromkeys(notes))[:400]


class GeminiSes(SesSaglayici):
    """Anahtar/model doğrulama ve tek parça üretimi."""

    ad = "gemini"

    def kontrol(self, key, model):
        if not (key or "").strip():
            raise ValueError("Gemini API anahtarını Bağlantılar alanına gir.")
        if model not in GEMINI_MODELS:
            raise ValueError("Desteklenmeyen Gemini modeli.")
        http_json(requests.get(f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
                               headers={"x-goog-api-key": key.strip()}, timeout=30))
        return "Gemini anahtarı ve model erişimi doğrulandı. Üretim kotası ayrıca uygulanır."

    def parca_uret(self, text, language, style, voice, model, key, output):
        prompt = gemini_prompt(text, language, style)
        headers = {"x-goog-api-key": key.strip(), "Content-Type": "application/json"}
        if model == "gemini-3.1-flash-tts-preview":
            payload = {"model": model, "input": prompt, "store": False,
                       "response_format": {"type": "audio"},
                       "generation_config": {"speech_config": [{"voice": voice}]}}
            body = http_json(requests.post("https://generativelanguage.googleapis.com/v1beta/interactions",
                                           headers=headers, json=payload, timeout=(20, 240)))
        else:
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
            body = http_json(requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                           headers=headers, json=payload, timeout=(20, 240)))
        blocks = find_audio_blocks(body)
        if not blocks:
            raise RuntimeError("Gemini ses verisi döndürmedi. Metin veya model isteği reddedilmiş olabilir. "
                               + describe_response(body))
        # Current TTS responses are PCM16 mono 24 kHz; honor an explicit sample rate.
        pcm_parts, sample_rate = [], None
        for block in blocks:
            raw = base64.b64decode(block.get("data", ""), validate=True)
            mime = block.get("mime_type", block.get("mimeType", "audio/pcm;rate=24000"))
            if not raw:
                raise RuntimeError("Gemini boş ses verisi döndürdü.")
            if raw[:4] == b"RIFF" or "wav" in mime:
                samples, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
            elif mime.startswith(("audio/pcm", "audio/L16", "audio/l16")):
                if len(raw) % 2:
                    raise RuntimeError("Gemini PCM verisi eksik; tekrar üretilmedi.")
                match = re.search(r"rate=(\d+)", mime)
                rate = int(match.group(1)) if match else 24000
                samples = np.frombuffer(raw, dtype="<i2").astype(np.float32).reshape(-1, 1) / 32768
            else:
                samples, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
            if sample_rate is not None and rate != sample_rate:
                raise RuntimeError("Gemini ses parçalarının örnekleme hızları farklı.")
            sample_rate = rate
            pcm_parts.append(samples)
        sf.write(output, np.concatenate(pcm_parts), sample_rate, subtype="PCM_16")


VARSAYILAN = GeminiSes()
