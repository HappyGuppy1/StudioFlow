"""Araçlar › Seslendirme sekmesi (ses testi dâhil). — geri çağrı işlevleri."""
import shutil

import gradio as gr

from studioflow.arayuz.sabitler import SES_TESTI_IPTAL, SUB_PRESET_AYAR
from studioflow.ayarlar import api_hesaplari
from studioflow.saglayicilar import ses_chatterbox, ses_edge, ses_gemini, ses_uretim
from studioflow.altyazi.kural import sub_rules
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.hatalar import ses_hatasi_temizle as clean_error
from studioflow.saglayicilar.ses_ortak import VOICES, test_cumlesi, test_klasoru


def subtitle_preset(ad):
    """Hazır altyazı ayarını seçili karakter/satır sınırlarına uygula."""
    karakter, satir, _seviye = SUB_PRESET_AYAR.get(ad, SUB_PRESET_AYAR["yatay"])
    return gr.update(value=karakter), gr.update(value=satir)


def voice_options(language):
    names = ses_edge.VARSAYILAN.guvenli_sesler(language)
    return gr.Dropdown(choices=names, value=names[0] if names else None)


def ilk_ses(dil):
    """Dilin Edge seslerinden ilkini seç (liste boşsa None)."""
    sesler = ses_edge.VARSAYILAN.guvenli_sesler(dil)
    return sesler[0] if sesler else None


def check_voice_service(provider, language, model):
    key = api_hesaplari.VARSAYILAN.aktif_deger("gemini", "gemini_key")
    token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    try:
        if provider == "edge":
            return ses_edge.VARSAYILAN.kontrol(language)
        if provider == "gemini":
            return ses_gemini.VARSAYILAN.kontrol(key, model)
        return ses_chatterbox.VARSAYILAN.kontrol(token)
    except Exception as exc:
        return "Kontrol başarısız: " + clean_error(exc, key, token)


def ses_test_sesleri(provider, dil):
    """Test panelinde seçilebilecek sesler: Edge'de dilin sesleri, Gemini'de otuz ses."""
    if provider == "edge":
        sesler = ses_edge.VARSAYILAN.guvenli_sesler(dil)
    elif provider == "gemini":
        sesler = list(VOICES)
    else:
        sesler = []      # Chatterbox referans kaydıyla çalışır.
    return gr.update(choices=sesler, value=sesler[0] if sesler else None,
                     interactive=bool(sesler))


def ses_test_metni(dil):
    """Dil değişince o dilin test cümlesini yaz."""
    return gr.update(value=test_cumlesi(dil))


def ses_testi_durdur():
    """Süren ses testini durdur."""
    SES_TESTI_IPTAL.set()
    return "Test durduruldu; o ana kadar üretilen sesler dinlenebilir."


def ses_testi_akisi(provider, dil, cumle, sesler, model, style, hiz, ton, ref, exag, cfg):
    """Test cümlesiyle sesleri sırayla dene: (ses, dosyalar, durum) üretir.

    Çıktı **yalnızca** geçici test klasörüne yazılır ve yeni bir testte silinir: otomatik
    kaydetme açık olsa bile `outputs` klasörüne tek dosya bile düşmez.
    """
    cumle = (cumle or "").strip() or test_cumlesi(dil)
    sesler = [sesler] if isinstance(sesler, str) else list(sesler or [])
    if provider == "chatterbox":
        sesler = [""]      # Chatterbox ses klonlar: tek deneme yapılır.
    if not sesler:
        sesler = [""]
    key = api_hesaplari.VARSAYILAN.aktif_deger("gemini", "gemini_key")
    token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    klasor = test_klasoru()
    SES_TESTI_IPTAL.clear()
    dosyalar, son, hatalar = [], None, []
    for sira, ses in enumerate(sesler, start=1):
        if SES_TESTI_IPTAL.is_set():
            break
        ad = ses or "referans ses"
        yield son, dosyalar, f"{sira}/{len(sesler)} · {ad} deneniyor… (test · kaydedilmez)"
        try:
            for _durum, ses_yolu, _dosyalar, _altyazilar in ses_uretim.VARSAYILAN.uret(
                    provider, cumle, dil, key=key, model=model, voice=ses or "Charon",
                    style=style, token=token, reference=ref, exaggeration=exag, cfg=cfg,
                    edge_voice=ses if provider == "edge" else "",
                    rate=int(hiz), pitch=int(ton), subtitles=False, hedef_klasor=klasor):
                if ses_yolu:
                    son = ses_yolu
        except Exception as exc:
            hatalar.append(f"{ad}: " + clean_error(exc, key, token))
            continue
        if not son:
            hatalar.append(f"{ad}: ses üretilemedi.")
            continue
        # Dosyayı "<ses>.wav" adıyla test klasörüne kopyala: listeden seçip dinlemek kolay olsun.
        try:
            hedef = klasor / f"{ses or 'referans'}.wav"
            shutil.copyfile(son, hedef)
            dosyalar.append(str(hedef))
        except Exception as exc:
            hatalar.append(f"{ad}: dosya kopyalanamadı ({exc}).")
    if not dosyalar:
        yield None, [], ("Test sesi üretilemedi.\n" + "\n".join(hatalar[:3])).strip()
        return
    durum = (f"Test tamam · {len(dosyalar)} ses · dil: {LANGUAGES.get(dil, dil)}\n"
             f"Test cümlesi: {cumle}")
    if hatalar:
        durum += "\nDenenemeyen sesler: " + " · ".join(hatalar[:3])
    yield dosyalar[-1], dosyalar, durum


def ses_testi(provider, dil, cumle, ses, model, style, hiz, ton, ref, exag, cfg):
    """Seçili tek sesi test cümlesiyle dene (kaydedilmez)."""
    yield from ses_testi_akisi(provider, dil, cumle, ses, model, style, hiz, ton, ref, exag, cfg)


def ses_testi_tumu(provider, dil, cumle, model, style, hiz, ton, ref, exag, cfg):
    """Seçili dildeki bütün sesleri sırayla dene (kaydedilmez)."""
    if provider == "edge":
        sesler = ses_edge.VARSAYILAN.guvenli_sesler(dil)
    elif provider == "gemini":
        sesler = list(VOICES)
    else:
        sesler = [""]
    yield from ses_testi_akisi(provider, dil, cumle, sesler, model, style, hiz, ton, ref, exag,
                                cfg)


def narrate(provider, text, language, edge_voice, rate, pitch,
            model, voice, style, reference, exaggeration, cfg, altyazi,
            sub_line_chars, sub_max_lines, sub_max_seconds, sub_min_seconds):
    """Seslendir; anahtarlar ve altyazı için Cloudflare bilgileri aktif hesaplardan okunur."""
    key = api_hesaplari.VARSAYILAN.aktif_deger("gemini", "gemini_key")
    token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    cf = api_hesaplari.VARSAYILAN.aktif_degerler("cloudflare")
    ayar = sub_rules(line_chars=sub_line_chars, max_lines=sub_max_lines,
                     min_seconds=sub_min_seconds, max_seconds=sub_max_seconds)
    try:
        for status, audio, files, altyazilar in ses_uretim.VARSAYILAN.uret(
                provider, text, language, key=key, model=model, voice=voice, style=style,
                token=token, reference=reference, exaggeration=exaggeration, cfg=cfg,
                edge_voice=edge_voice, rate=rate, pitch=pitch,
                cf_account=cf.get("cf_account_id", ""), cf_token=cf.get("cf_token", ""),
                subtitles=bool(altyazi), subtitle_ayar=ayar):
            yield audio, files, altyazilar, status
    except Exception as exc:
        yield None, [], [], clean_error(exc, key, token)
