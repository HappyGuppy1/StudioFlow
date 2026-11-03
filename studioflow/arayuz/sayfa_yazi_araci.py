"""Araçlar › Sesten yazıya sekmesi (Gemini 3.5 Transcribe, projeden bağımsız)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_yazi_araci import YA_HAZIR, yazi_dok
from studioflow.arayuz.sayfa import Sayfa
from studioflow.cekirdek.diller import LANGUAGES


class YaziAraciSayfasi(Sayfa):
    ad = "yazi"

    def kur(self, b):
        with gr.Tab("Sesten yazıya", elem_id="sf-transcribe-tool"):
            gr.HTML(tema.TRANSCRIBE_HEADING)
            with gr.Accordion("Nasıl çalışır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Ses, Google'ın yazıya dökme modeli **Gemini 3.5 Transcribe** ile metne "
                    "çevrilir; GPU gerekmez, Gemini'nin ücretsiz katmanı yeter. Dosya, kelime "
                    "ortasından kesilmesin diye **sessiz noktalardan** ~5 dakikalık parçalara "
                    "bölünür; her parça ayrı istekle gider, kotası dolan hesabın yerine "
                    "sıradaki Gemini hesabı kullanılır.\n\n"
                    "- **Zamanlı altyazı açık:** her kelimenin zamanı alınır; metinle birlikte "
                    "SRT/VTT altyazı yazılır, 'eee' gibi dolgu sözcükleri ayıklanır.\n"
                    "- **Kapalı:** yalnızca metin; dolgu sözcüklerini model kendisi temizler "
                    "ve **özel kelimeler** (ad, terim) kullanılabilir. Gemini bu ikisini "
                    "birlikte kabul etmiyor.\n\n"
                    "Tarayıcıdan en fazla 20 MB yüklenebilir; büyük videolar için dosyanın "
                    "bilgisayardaki yolunu yapıştır.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Kaynak", "Videonu ya da ses dosyanı ver."))
                    b.ya_dosya = gr.File(label="Video veya ses dosyası (20 MB'a kadar)",
                                         file_types=["audio", "video"])
                    b.ya_yol = gr.Textbox(label="ya da bilgisayardaki dosyanın yolu",
                                          placeholder=r"ör. C:\Users\…\Desktop\video.mp4")
                    b.ya_dil = gr.Dropdown([("Otomatik algıla", "")]
                                           + [(ad, kod) for kod, ad in LANGUAGES.items()],
                                           value="tr", label="Konuşma dili")
                    b.ya_zamanli = gr.Checkbox(value=True, label="Zamanlı altyazı (SRT) da üret")
                    b.ya_terimler = gr.Textbox(label="Özel kelimeler (virgülle; altyazısız kipte)",
                                               placeholder="ör. lepistes, Caridina, Akvaryum Defteri")
                    b.ya_btn = gr.Button("📝 Yazıya dök", variant="primary")
                    b.ya_durum = gr.Textbox(label="Durum", interactive=False, lines=6,
                                            value=YA_HAZIR)
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("02", "Metin", "Kopyala ya da dosyaları indir."))
                    b.ya_metin = gr.Textbox(label="Döküm", lines=18, interactive=True,
                                            buttons=["copy"])
                    b.ya_dosyalar = gr.File(label="Dosyalar (.txt · .srt · .vtt)",
                                            file_count="multiple", interactive=False)

    def bagla(self, b):
        b.ya_btn.click(yazi_dok, [b.ya_dosya, b.ya_yol, b.ya_dil, b.ya_zamanli, b.ya_terimler],
                       [b.ya_durum, b.ya_metin, b.ya_dosyalar], concurrency_limit=1,
                       api_name=False)
