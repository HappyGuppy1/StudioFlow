"""Chatterbox (Hugging Face ZeroGPU Space): çok dilli ses klonlama."""
from pathlib import Path

import requests
import soundfile as sf
from gradio_client import Client, handle_file

from studioflow.saglayicilar.ses_ortak import (CHATTERBOX_LANGUAGES, CHATTERBOX_SPACE,
                                               http_json, find_audio, hf_identity)
from studioflow.saglayicilar.taban import SesSaglayici


class ChatterboxSes(SesSaglayici):
    """Space sağlık kontrolü, istemci açma, referans ses hazırlama ve istek gönderme.

    Parça üretimi bir Gradio işi (`job`) olarak çalışır; ilerleme döngüsü ve iptal
    `SesUretici` içinde kalır ki iş her koşulda kapatılabilsin.
    """

    ad = "chatterbox"
    diller = CHATTERBOX_LANGUAGES

    def kontrol(self, token=""):
        data = http_json(requests.get(f"https://huggingface.co/api/spaces/{CHATTERBOX_SPACE}", timeout=30))
        runtime = data.get("runtime", {})
        if runtime.get("stage") != "RUNNING":
            raise RuntimeError(f"Chatterbox hazır değil: {runtime.get('stage', 'bilinmiyor')}")
        if not runtime.get("hardware", {}).get("current", "").startswith("zero-"):
            raise RuntimeError("Chatterbox sunucusu artık ZeroGPU değil. İşlem durduruldu.")
        return f"Chatterbox hazır · Resmî Hugging Face ZeroGPU sunucusu · Kimlik: {hf_identity(token)}"

    def istemci_ac(self, token, run_dir):
        return Client(CHATTERBOX_SPACE, token=(token or "").strip() or None,
                      verbose=False, analytics_enabled=False,
                      download_files=run_dir / "downloads", httpx_kwargs={"timeout": 60.0})

    def referans_hazirla(self, reference, run_dir):
        """Referans sesi tek kanallı 16 bit WAV'a çevir; 3–30 saniye olmalı."""
        reference = Path(reference)
        data, rate = sf.read(reference, dtype="float32", always_2d=True)
        if not 3 <= len(data) / rate <= 30:
            raise ValueError("Referans ses 3–30 saniye olmalı. Temiz WAV, FLAC veya MP3 kullan.")
        normalized = run_dir / "reference.wav"
        sf.write(normalized, data.mean(axis=1), rate, subtype="PCM_16")
        return handle_file(str(normalized))

    def istek_gonder(self, client, chunk, language, audio_ref, exaggeration, cfg):
        return client.submit(text_input=chunk, language_id=language,
            audio_prompt_path_input=audio_ref, exaggeration_input=float(exaggeration),
            temperature_input=0.8, seed_num_input=42, cfgw_input=float(cfg),
            api_name="/generate_tts_audio")

    def sonucu_yaz(self, job, output):
        downloaded = find_audio(job.result())
        if downloaded is None:
            raise RuntimeError("Chatterbox indirilebilir ses döndürmedi.")
        samples, rate = sf.read(downloaded, dtype="float32", always_2d=True)
        if not samples.size:
            raise RuntimeError("Chatterbox boş ses döndürdü.")
        sf.write(output, samples, rate, subtype="PCM_16")

    def parca_uret(self, text, output, **secenekler):
        """Tek parça: istek gönderilir ve sonuç beklenir (ilerleme bildirimi olmadan)."""
        job = self.istek_gonder(secenekler["client"], text, secenekler["language"],
                                secenekler.get("audio_ref"), secenekler.get("exaggeration", 0.5),
                                secenekler.get("cfg", 0.5))
        self.sonucu_yaz(job, output)
        return []


VARSAYILAN = ChatterboxSes()
