"""Araçlar › Müzik üret sekmesi (Lyria RealTime, projeden bağımsız)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_muzik_uretimi import MU_HAZIR, mu_uret
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR
from studioflow.saglayicilar.muzik_lyria import BPM_SINIRI, SURE_SINIRI
from studioflow.saglayicilar import metin_ortak


def ai_secenekleri():
    return [(bilgi["label"], kod) for kod, bilgi in AI_SAGLAYICILAR.items()]


class MuzikAraciSayfasi(Sayfa):
    ad = "muzik"

    def kur(self, b):
        with gr.Tab("Müzik üret", elem_id="sf-music-tool"):
            gr.HTML(tema.MUSIC_HEADING)
            with gr.Accordion("Nasıl çalışır? · telif · filigran · kota", open=False,
                              elem_classes=["sf-help"]):
                gr.Markdown(
                    "Müzik Google **Lyria RealTime** ile bulutta üretilir; bilgisayarının GPU'su "
                    "ve belleği kullanılmaz. **API hesapları** sekmesindeki Gemini anahtarı "
                    "kullanılır; model şimdilik ücretsizdir ve **seslendirme kotasından yemez** "
                    "(sınırlar model başınadır). Kota dolarsa sıradaki Gemini hesabı denenir.\n\n"
                    "- **Yalnızca enstrümantal** müzik üretir (sözlü şarkı yok).\n"
                    "- Tarifi Türkçe yazabilirsin; seçtiğin yapay zekâ onu Lyria'nın anladığı "
                    "İngilizce istemlere ve bir tempoya çevirir.\n"
                    "- Müzik **gerçek zamanlı** gelir: 60 sn müzik yaklaşık 1 dakikada üretilir.\n"
                    "- **Telif:** Google üretilen içerik üzerinde hak iddia etmez; atıf "
                    "gerekmez, ticari kullanılabilir. Sanatçı ya da şarkı adı yazma: güvenlik "
                    "filtresi bu istemleri yok sayar.\n"
                    "- **Filigran:** her çıktıda duyulmayan bir **SynthID** filigranı vardır; "
                    "kaldırılamaz. YouTube'da *değiştirilmiş veya sentetik içerik* beyanını aç.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Tarif", "Müziğin havasını, çalgılarını ve temposunu anlat."))
                    b.mu_tarif = gr.Textbox(
                        label="Müzik tarifi", lines=4,
                        placeholder="ör. eski Mısır esintisi, gizemli ve görkemli; ud ve ney "
                                    "melodisi, darbuka ile yavaş tören ritmi, sinematik yaylılar")
                    with gr.Row():
                        b.mu_sure = gr.Slider(*SURE_SINIRI, value=60, step=5, label="Süre (sn)")
                        b.mu_bpm = gr.Slider(0, BPM_SINIRI[1], value=0, step=1,
                                             label="Tempo (BPM)",
                                             info="0 = yapay zekâ tarife göre seçer.")
                    b.mu_ai = gr.Dropdown(ai_secenekleri(), value=metin_ortak.AI_VARSAYILAN,
                                          label="Tarifi çeviren yapay zekâ")
                    b.mu_uret_btn = gr.Button("🎵 Müzik üret", variant="primary")
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("02", "Durum ve çıktı", "Dinle, beğenirsen indir."))
                    b.mu_durum = gr.Textbox(label="Durum", interactive=False, lines=10, value=MU_HAZIR)
                    b.mu_ses = gr.Audio(label="Üretilen müzik", type="filepath", interactive=False)
                    b.mu_dosya = gr.File(label="Müzik dosyası (WAV)")

    def bagla(self, b):
        b.mu_uret_btn.click(mu_uret, [b.mu_tarif, b.mu_sure, b.mu_bpm, b.mu_ai],
                            [b.mu_durum, b.mu_ses, b.mu_dosya],
                            concurrency_limit=1, api_name=False)
