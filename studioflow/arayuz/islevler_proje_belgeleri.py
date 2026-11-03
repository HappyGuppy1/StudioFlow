"""Proje oluştur › proje adının altındaki belge seçiciler — geri çağrı işlevleri.

Araçlar › Prompt'ta kaydedilen belgeler projeye buradan girer, **ayrı ayrı**:

- **Seslendirme belgesi** (`seslendirme.SESLENDIRMELER`) → anlatım metni;
- **Prompt belgesi** (`tasarim.TASARIMLAR`) → genel video prompt'u, görsel stil katmanı,
  negatif prompt, ilk sahne (+) ve ilk sahne (−).

Belge seçilince alanlar kendiliğinden dolar; ekrandaki değerler üzerine yazılır. Prompt
belgesinde bulunmayan bir anahtar (eski kayıt) ekrandaki değere dokunmaz.
"""
import gradio as gr

from studioflow.cekirdek.metin import kelime_sayisi
from studioflow.hikaye import seslendirme, tasarim
from studioflow.proje.sahneleme import KELIME_HIZI

# Prompt belgesinin anahtarları, proje sayfasındaki alanların sırasıyla.
PROMPT_ALANLARI = ("genel", "stil", "negatif", "ilk_prompt", "ilk_negatif")


def pj_belge_listeleri(ses_secili=None, prompt_secili=None):
    """İki belge listesini tazele (seçili ad listede kalıyorsa korunur)."""
    ses = seslendirme.SESLENDIRMELER.listele()
    prompt = tasarim.TASARIMLAR.listele()
    return (gr.update(choices=ses, value=ses_secili if ses_secili in ses else None),
            gr.update(choices=prompt, value=prompt_secili if prompt_secili in prompt else None))


def pj_seslendirme_belgesi_ac(ad):
    """Seçilen seslendirme belgesini anlatım metnine yükle: `(metin, not)`."""
    if not ad:
        return gr.update(), ""
    try:
        metin = seslendirme.SESLENDIRMELER.oku(ad)[0].strip()
    except (FileNotFoundError, OSError) as exc:
        return gr.update(), f"⚠ {exc}"
    adet = kelime_sayisi(metin)
    return (gr.update(value=metin),
            f"✅ **{ad}** anlatım metnine yüklendi · {adet} kelime (~{adet / KELIME_HIZI:.0f} sn).")


def pj_prompt_belgesi_ac(ad):
    """Seçilen prompt belgesini prompt alanlarına yükle: 5 alan + not."""
    bos = tuple(gr.update() for _ in PROMPT_ALANLARI)
    if not ad:
        return (*bos, "")
    if not tasarim.TASARIMLAR.var_mi(ad):
        return (*bos, f"⚠ Kayıtlı prompt belgesi bulunamadı: {ad}")
    veri = tasarim.TASARIMLAR.veri(ad)
    guncel = tuple(gr.update(value=str(veri.get(anahtar) or "")) if anahtar in veri else gr.update()
                   for anahtar in PROMPT_ALANLARI)
    dolu = [ad_ for ad_, anahtar in zip(("genel prompt", "stil", "negatif", "ilk sahne (+)",
                                         "ilk sahne (−)"), PROMPT_ALANLARI)
            if str(veri.get(anahtar) or "").strip()]
    return (*guncel, f"✅ **{ad}** prompt alanlarına yüklendi: {', '.join(dolu) or 'boş belge'}.")
