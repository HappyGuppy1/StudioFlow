"""Araçlar › Görsel üret sekmesi."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_gorsel import (
    gorsel_iptal_et, gorsel_model_degisti, gorsel_modeller, gorsel_on_ayar_degisti,
    gorsel_servis_kontrol, gorsel_uret)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import gorsel_cloudflare


class GorselAraciSayfasi(Sayfa):
    ad = "gorsel"

    def kur(self, b):
        with gr.Tab("Görsel üret", elem_id="sf-image-tool"):
            gr.HTML(tema.IMAGE_HEADING)
            with gr.Accordion('Modeller, boyutlar ve servis bilgisi', open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "# Görsel üret\n"
                    "Metni yaz, modeli seç, görseli üret. Üretim **uzakta** çalışır; **model bu "
                    "bilgisayara inmez**, yalnızca istek gider ve hazır görsel iner.\n"
                    "- **Cloudflare Workers AI** · Kuyruk yoktur; istek doğrudan "
                    "Cloudflare'e gider ve görsel saniyeler içinde gelir. Hesabının **Account ID** ve "
                    "**API token**'ı gerekir.\n\n"
                    "Yerel GPU ve PyTorch gerekmez. Üretim sınırsız değildir: hesabının ücretsiz kotası "
                    "geçerlidir, otomatik tekrar yapılmaz.  \n"
                    "**Boyut sınırları** modelin kendi değerleridir; arayüzdeki slider model "
                    "değişince ona göre daralır: SDXL 256–2048 (64'ün katı), Lucid 256–2500 (16'nın katı), "
                    "FLUX 1024×1024 (sabit)."
                )
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading('01', 'Sahneni tarif et', 'Prompt, model ve görsel ayarlarını belirle.'))
                    b.gorsel_prompt = gr.Textbox(label="Prompt · ne üretilsin?", lines=3,
                        placeholder="ör. a red apple on a wooden table, photorealistic, soft light")
                    b.gorsel_on_ayar = gr.Dropdown(gorsel_cloudflare.on_ayar_secenekleri(), value="",
                                                 label="Ön ayar · tek seçimle hazır kurulum",
                                                 info="Servisi, modeli, boyutu, adımı ve CFG'yi "
                                                      "birlikte kurar; sonra istediğin alanı elle "
                                                      "değiştirebilirsin.")
                    b.gorsel_on_ayar_not = gr.Markdown("")
                    with gr.Row():
                        b.gorsel_model = gr.Dropdown(choices=gorsel_cloudflare.cf_model_choices(),
                                                   value=gorsel_cloudflare.VARSAYILAN_MODEL,
                                                   label="Model", scale=3)
                        b.gorsel_modelleri_yenile = gr.Button("Modelleri yenile", scale=1)
                    b.gorsel_model_not = gr.Markdown(gorsel_cloudflare.cf_note(gorsel_cloudflare.VARSAYILAN_MODEL))
                    with gr.Row():
                        b.gorsel_width = gr.Slider(256, 2048, value=1024, step=64, label="Genişlik (px)")
                        b.gorsel_height = gr.Slider(256, 2048, value=1024, step=64, label="Yükseklik (px)")
                    with gr.Row():
                        b.gorsel_steps = gr.Slider(1, 20, value=4, step=1, label="Adım (steps)")
                        b.gorsel_count = gr.Slider(1, 4, value=1, step=1, label="Adet")
                    b.gorsel_seed = gr.Textbox(label="Seed · boş bırakırsan rastgele", placeholder="opsiyonel")
                    b.gorsel_guidance = gr.Slider(0, 15, value=7.5, step=0.5, label="Guidance (CFG)")
                    b.gorsel_negative = gr.Textbox(label="Negatif prompt · istenmeyen şeyler", lines=2,
                        placeholder="blurry, low quality, watermark, deformed hands, extra fingers")
                    gr.Markdown("Negatif prompt yalnızca destekleyen modellerde kullanılır "
                                "(FLUX.1 schnell, Lucid Origin ve Leonardo modelleri desteklemez).")
                    with gr.Row():
                        b.gorsel_kontrol = gr.Button("Bağlantıyı kontrol et")
                        b.gorsel_basla = gr.Button("Görseli üret", variant="primary")
                        b.gorsel_iptal = gr.Button("İptal", size="sm", scale=0)
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading('02', 'Görsel galerisi', 'Üretilen karelerini incele ve indir.'))
                    b.gorsel_gallery = gr.Gallery(label="Üretilen görseller", columns=2, height=420)
                    b.gorsel_dosyalar = gr.File(label="İndirilecek dosyalar", file_count="multiple")
                    b.gorsel_durum = gr.Textbox(label="Durum", interactive=False, lines=5,                        value="Hazır. Cloudflare Workers AI: kuyruk yok, saniyeler içinde üretir. "
                              "Önce **API hesapları** sekmesinden Account ID ve token kaydet.")
            with gr.Accordion("Kayıt ve kullanım notları", open=False, elem_classes=["sf-help"]):
                gr.Markdown("Görseller, **Ayarları kaydet** panelindeki **otomatik kaydet** kutusu işaretliyse **outputs/images** "
                            "klasörüne yazılır; kapalıyken geçici klasörde kalır ve yalnızca indirme kutusundan alınır. "
                            "Cloudflare'de her görsel hesabının Workers AI kotasından (neurons) harcar.")

                gr.Markdown(
                    "### Bu sekmeyi besleyen anahtarlar\n"
                    "Cloudflare anahtarları **API hesapları** sekmesinde, diğer bütün "
                    "servislerle birlikte tutulur. Cloudflare araçları (Account ID bulma, bağlantı testi, "
                    "teşhis) de o sekmede, Cloudflare hizmetini seçtiğinde görünür.\n\n"
                    "Anahtarlar hata mesajlarında gizlenir ve hiçbir çıktı dosyasına yazılmaz."
                )

    def bagla(self, b):
        b.gorsel_modelleri_yenile.click(gorsel_modeller, None, [b.gorsel_model], api_name=False)
        b.gorsel_model.change(gorsel_model_degisti, [b.gorsel_model],
                            [b.gorsel_model_not, b.gorsel_steps, b.gorsel_guidance, b.gorsel_width,
                             b.gorsel_height, b.gorsel_seed], api_name=False)
        b.gorsel_on_ayar.change(gorsel_on_ayar_degisti, [b.gorsel_on_ayar],
                              [b.gorsel_model, b.gorsel_model_not, b.gorsel_width, b.gorsel_height,
                               b.gorsel_steps, b.gorsel_guidance, b.gorsel_on_ayar_not],
                              api_name=False)
        b.gorsel_kontrol.click(gorsel_servis_kontrol, None, [b.gorsel_durum], api_name=False)
        b.gorsel_basla.click(gorsel_uret,
                           [b.gorsel_prompt, b.gorsel_negative, b.gorsel_model, b.gorsel_width,
                            b.gorsel_height, b.gorsel_steps, b.gorsel_guidance, b.gorsel_count,
                            b.gorsel_seed],
                           [b.gorsel_gallery, b.gorsel_dosyalar, b.gorsel_durum],
                           concurrency_limit=1, api_name=False)
        # İptal kuyruğa girmemeli: düğme basıldığı anda çalışır.
        b.gorsel_iptal.click(gorsel_iptal_et, None, [b.gorsel_durum], queue=False, api_name=False)
