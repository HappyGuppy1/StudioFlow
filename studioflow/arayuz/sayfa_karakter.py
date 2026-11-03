"""Araçlar › Sabit karakter sekmesi: tek referans görselle her sahnede aynı karakter."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_karakter import (
    MODEL_VARSAYILAN, STIL_VARSAYILAN, STILLER, karakter_iptal_et, karakter_kaynak_degisti,
    karakter_referans_uret, karakter_sahneleri_uret)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import gorsel_cloudflare

KAYNAKLAR = ("Prompt ile üret", "Kendi görselimi yükle")


class KarakterAraciSayfasi(Sayfa):
    ad = "karakter"

    def kur(self, b):
        with gr.Tab("Sabit karakter", elem_id="sf-character-tool"):
            gr.HTML(tema.CHARACTER_HEADING)
            with gr.Accordion("Nasıl çalışır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "# Sabit karakter\n"
                    "Karakter yalnızca metinle tarif edilince model her sahnede tarife uyan "
                    "**başka bir yüz** seçer. Burada karakter bir **referans görselle** "
                    "sabitlenir; her sahne o görsel modele verilerek üretilir, böylece yüz, "
                    "saç ve kıyafet sahneden sahneye korunur.\n"
                    "1. **Referans:** karakteri tarif edip üret ya da kendi görselini yükle "
                    "(önden, tam boy, sade arka plan en iyi sonucu verir).\n"
                    "2. **Sahneler:** her satıra bir sahne yaz; karakteri yeniden tarif etme, "
                    "yalnızca ne yaptığını, nerede olduğunu ve kamerayı yaz.\n\n"
                    "Model: **FLUX.2 klein** (Cloudflare, referans görsel alan tek ücretsiz "
                    "model). Referans görsel 496 piksele küçültülerek gönderilir. Kare başına "
                    "~110 nöron harcar (günlük ücretsiz 10.000 nöronla ~80 kare). Prompt'lar "
                    "İngilizce yazılırsa model daha iyi anlar.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Karakter referansı",
                                               "Prompt ile üret ya da kendi görselini yükle."))
                    b.karakter_kaynak = gr.Radio(list(KAYNAKLAR), value=KAYNAKLAR[0],
                                                 label="Referans kaynağı")
                    with gr.Group(visible=True) as b.karakter_tarif_grubu:
                        b.karakter_tarif = gr.Textbox(
                            label="Karakter tarifi · görünüşü ve kıyafeti", lines=3,
                            placeholder="ör. a cute cartoon fox named Tilki, orange fur, white belly, "
                                        "big green eyes, blue scarf and a small brown backpack")
                        b.karakter_referans_btn = gr.Button("Referansı üret", variant="secondary")
                    b.karakter_referans = gr.Image(
                        label="Referans görsel · üretilen buraya gelir, ya da kendi görselini bırak",
                        type="filepath", sources=["upload", "clipboard"], height=320)
                    with gr.Row():
                        b.karakter_stil = gr.Dropdown([etiket for etiket, _ in STILLER],
                                                      value=STIL_VARSAYILAN, label="Stil")
                        b.karakter_model = gr.Dropdown(gorsel_cloudflare.referans_modelleri(),
                                                       value=MODEL_VARSAYILAN, label="Model")
                    gr.HTML(tema.panel_heading("02", "Sahneler",
                                               "Her satır bir sahne; karakter referanstan gelir."))
                    b.karakter_sahneler = gr.Textbox(
                        label="Sahneler · her satıra bir sahne", lines=5,
                        placeholder="walking through a busy city market at sunset, medium shot\n"
                                    "sitting at a kitchen table drinking tea, close-up\n"
                                    "running across a green meadow, full body wide shot")
                    with gr.Row():
                        b.karakter_genislik = gr.Slider(256, 2048, value=768, step=16,
                                                        label="Genişlik (px)")
                        b.karakter_yukseklik = gr.Slider(256, 2048, value=1344, step=16,
                                                         label="Yükseklik (px)")
                    with gr.Row():
                        b.karakter_basla = gr.Button("Sahneleri üret", variant="primary")
                        b.karakter_iptal = gr.Button("İptal", size="sm", scale=0)
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("03", "Sahne galerisi",
                                               "Aynı karakterle üretilen kareler."))
                    b.karakter_galeri = gr.Gallery(label="Sahneler", columns=2, height=420)
                    b.karakter_dosyalar = gr.File(label="İndirilecek dosyalar", file_count="multiple")
                    b.karakter_durum = gr.Textbox(
                        label="Durum", interactive=False, lines=5,
                        value="Hazır. Önce referansı üret ya da yükle, sonra sahneleri yaz.")

    def bagla(self, b):
        b.karakter_kaynak.change(karakter_kaynak_degisti, [b.karakter_kaynak],
                                 [b.karakter_tarif_grubu], api_name=False)
        b.karakter_referans_btn.click(karakter_referans_uret,
                                      [b.karakter_tarif, b.karakter_stil, b.karakter_model],
                                      [b.karakter_referans, b.karakter_durum],
                                      concurrency_limit=1, api_name=False)
        b.karakter_basla.click(karakter_sahneleri_uret,
                               [b.karakter_referans, b.karakter_sahneler, b.karakter_stil,
                                b.karakter_model, b.karakter_genislik, b.karakter_yukseklik],
                               [b.karakter_galeri, b.karakter_dosyalar, b.karakter_durum],
                               concurrency_limit=1, api_name=False)
        # İptal kuyruğa girmemeli: düğme basıldığı anda çalışır.
        b.karakter_iptal.click(karakter_iptal_et, None, [b.karakter_durum], queue=False,
                               api_name=False)
