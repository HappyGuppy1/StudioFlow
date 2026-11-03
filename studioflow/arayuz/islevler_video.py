"""Araçlar › Fotoğraftan video sekmesi. — geri çağrı işlevleri."""
import gradio as gr

from studioflow.ayarlar import api_hesaplari
from studioflow.saglayicilar import video_agnes, video_huggingface
from studioflow.saglayicilar.video_huggingface import check_connection, error_message


def _kaynak(hf):
    """Sayfa görünürlükleri ve düğme vurguları: `[hf sayfası, agnes sayfası, hf düğmesi, agnes düğmesi]`."""
    return [gr.update(visible=hf), gr.update(visible=not hf),
            gr.update(variant="primary" if hf else "secondary"),
            gr.update(variant="secondary" if hf else "primary")]


def kaynak_hf():
    return _kaynak(True)


def kaynak_agnes():
    return _kaynak(False)


def connection():
    token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    try:
        return check_connection(token)
    except Exception as exc:
        return "Bağlantı kurulamadı: " + error_message(exc, token)


def run(image, prompt, duration, steps, fps, quality):
    """Fotoğraftan video üret: süre, adım, akıcılık ve kalite seçimleriyle."""
    token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    try:
        for status, video in video_huggingface.VARSAYILAN.uret(image, prompt, duration, steps, token,
                                      fps=fps, quality=quality):
            yield video, video, status
    except Exception as exc:
        yield None, None, error_message(exc, token)


def agnes_baglanti():
    anahtar = api_hesaplari.VARSAYILAN.aktif_deger("agnes", "agnes_key")
    try:
        return video_agnes.VARSAYILAN.kontrol(anahtar)
    except Exception as exc:
        return "Bağlantı kurulamadı: " + video_agnes.hata_metni(exc, anahtar)


def agnes_run(image, prompt, model, duration, oran):
    """Agnes AI ile video üret: fotoğraf varsa ilk kare olur, yoksa metinden üretilir."""
    anahtar = api_hesaplari.VARSAYILAN.aktif_deger("agnes", "agnes_key")
    try:
        for status, video in video_agnes.VARSAYILAN.uret(image, prompt, model, duration, oran,
                                                         anahtar):
            yield video, video, status
    except Exception as exc:
        yield None, None, video_agnes.hata_metni(exc, anahtar)
