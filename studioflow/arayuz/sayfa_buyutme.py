"""Araçlar › Video büyütme (Kaggle) sekmesi.

Bağımsız bir araçtır: ana üretim hattına bağlı değildir. Seçilen videolar Kaggle'ın
ücretsiz T4 GPU'sunda büyütülür; yerel GPU/RAM kullanılmaz.
"""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_buyutme import (
    CIKTI_KOKU, buyutme_baglanti_testi, buyutme_calistir, buyutme_yontemi)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import buyutme_kaggle as kaggle


class BuyutmeAraciSayfasi(Sayfa):
    ad = "buyutme"

    def kur(self, b):
        with gr.Tab("Video büyütme (Kaggle)", elem_id="sf-upscale-tool"):
            gr.HTML(tema.UPSCALE_HEADING)
            with gr.Accordion("Nasıl çalışır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Videolar **özel** bir Kaggle veri setine yüklenir, tek hücreli bir notebook "
                    "Kaggle'ın ücretsiz **T4 GPU**'sunda çalıştırılır ve sonuç "
                    f"`{CIKTI_KOKU}` altında, çalıştırma saatini taşıyan bir klasöre indirilir. "
                    "Bilgisayarının GPU'su ve belleği kullanılmaz.\n\n"
                    "Kaggle hesabını **API hesapları** sekmesinde *Kaggle* hizmetine kaydet "
                    f"(token: [Kaggle › Settings › API]({kaggle.TOKEN_URL}) › **Generate New "
                    f"Token**); aktif hesap `{kaggle.ACCESS_TOKEN.parent}` klasörüne yazılır ve araç "
                    "kimliği oradan okur. GPU ve internet için hesapta telefon doğrulaması "
                    "gerekir. Kimlik bilgisi hiçbir günlüğe ya da proje dosyasına yazılmaz.\n\n"
                    "Çıktı videoda **ses olmayabilir**; bu normaldir, ses projede sonradan eklenir.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading('01', 'Girdi', 'Videoları seç ya da sürükleyip bırak.'))
                    # Sahne klasörünün tamamı için: klasörü aç, Ctrl+A ile hepsini seç.
                    b.bu_girdi = gr.File(label="Videolar · bir ya da birden çok (sahne klipleri için Ctrl+A)",
                                         file_count="multiple", file_types=["video"])
                    b.bu_yontem = gr.Radio(
                        [("SeedVR2 · önerilen", kaggle.YONTEM_SEEDVR2),
                         (f"Real-ESRGAN · yedek ({kaggle.REALESRGAN_MODEL}, "
                          f"{kaggle.REALESRGAN_OLCEK}× büyütme)", kaggle.YONTEM_REALESRGAN)],
                        value=kaggle.YONTEM_SEEDVR2, label="Yöntem")
                    with gr.Group(visible=True) as b.bu_seedvr2_box:
                        b.bu_model = gr.Dropdown(kaggle.MODELLER, value=kaggle.MODEL_VARSAYILAN,
                                                 label="SeedVR2 modeli", allow_custom_value=True)
                        with gr.Row():
                            b.bu_cozunurluk = gr.Number(kaggle.COZUNURLUK_VARSAYILAN, precision=0,
                                                        label="resolution (kısa kenar)")
                            b.bu_max_cozunurluk = gr.Number(kaggle.MAX_COZUNURLUK_VARSAYILAN,
                                                            precision=0, label="max_resolution")
                        with gr.Row():
                            # 5'ten başlayıp 4'er artan kaydırıcı yalnızca 4n+1 değer verir.
                            b.bu_batch = gr.Slider(5, 81, value=kaggle.BATCH_VARSAYILAN, step=4,
                                                   label="batch_size (4n+1)")
                            b.bu_gurultu = gr.Slider(*kaggle.GURULTU_SINIRI, value=0.0, step=0.01,
                                                     label="latent_noise_scale")
                        gr.Markdown("Sabit parametreler: `" + " ".join(kaggle.SABIT_PARAMETRELER) + "`")
                    with gr.Row():
                        b.bu_kimlik_btn = gr.Button("Kaggle bağlantısını test et")
                        gr.Button("🔗 Kaggle anahtar sayfası", link=kaggle.TOKEN_URL)
                        b.bu_calistir_btn = gr.Button("Kaggle'da büyüt", variant="primary")
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading('02', 'Durum ve çıktı', 'Kaggle çalışmasını canlı izle.'))
                    b.bu_durum = gr.Textbox(label="Durum", interactive=False, lines=10,
                                            value="Hazır. Video ya da sahne klasörünü seç.")
                    b.bu_video = gr.Video(label="Önizleme (ilk çıktı)", interactive=False)
                    b.bu_dosyalar = gr.File(label="Büyütülmüş videolar", file_count="multiple")
                    with gr.Accordion("Kaggle günlüğü", open=False):
                        b.bu_gunluk = gr.Textbox(label="Son satırlar", interactive=False, lines=14)

    def bagla(self, b):
        b.bu_yontem.change(buyutme_yontemi, [b.bu_yontem], [b.bu_seedvr2_box], api_name=False)
        b.bu_kimlik_btn.click(buyutme_baglanti_testi, None, [b.bu_durum], api_name=False)
        b.bu_calistir_btn.click(
            buyutme_calistir,
            [b.bu_girdi, b.bu_yontem, b.bu_model, b.bu_cozunurluk,
             b.bu_max_cozunurluk, b.bu_batch, b.bu_gurultu],
            [b.bu_durum, b.bu_video, b.bu_dosyalar, b.bu_gunluk],
            concurrency_limit=1, api_name=False)
