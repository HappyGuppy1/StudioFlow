"""Araçlar › Harita animasyonu sekmesi (duraklar arası kendini çizen rota, uçan kamera)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_harita import HR_HAZIR, HR_ORNEK, hr_onizle, hr_uret
from studioflow.arayuz.sayfa import Sayfa
from studioflow.harita.karolar import VARSAYILAN_STIL, stil_secenekleri


class HaritaAraciSayfasi(Sayfa):
    ad = "harita"

    def kur(self, b):
        with gr.Tab("Harita animasyonu", elem_id="sf-map-tool"):
            gr.HTML(tema.MAP_HEADING)
            with gr.Accordion("Nasıl çalışır? · durak yazımı · telif", open=False,
                              elem_classes=["sf-help"]):
                gr.Markdown(
                    "Her satıra bir durak yaz; rota yukarıdan aşağı sırayla çizilir.\n\n"
                    "- `Atina`: yer adı OpenStreetMap'te aranır.\n"
                    "- `Truva | Hisarlık, Çanakkale`: soldaki **etiket** videoda yazar, "
                    "sağdaki **arama** konumu bulur (antik adlar için).\n"
                    "- `Truva | 39.957, 26.239`: enlem, boylam (en kesini).\n"
                    "- `# …` satırları atlanır.\n\n"
                    "Kamera önce tüm rotayı gösterir, sonra her bacağa uçar; çizgi kendini "
                    "çizerken ucu izler, durak yaylanarak belirir, sonda yeniden genel "
                    "bakışa çekilir. Altlık haritalar **yazısızdır** (modern adlar tarihi "
                    "sahneye karışmaz).\n\n"
                    "Haritalar Esri ve CARTO'nun ücretsiz karolarıdır; kullanım şartı **atıf** "
                    "ister, atıf videonun sağ alt köşesine küçük yazılır. Karolar önbelleğe "
                    "alınır; aynı bölgede ikinci video çok daha hızlıdır.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Rota", "Durakları sırayla yaz, görünümü seç."))
                    b.hr_duraklar = gr.Textbox(label="Duraklar (her satıra bir tane)", lines=6,
                                               value=HR_ORNEK)
                    with gr.Row():
                        b.hr_stil = gr.Dropdown(stil_secenekleri(), value=VARSAYILAN_STIL,
                                                label="Harita stili")
                        b.hr_cizgi = gr.Dropdown([("Kavisli yay (Vox tarzı)", "kavis"),
                                                  ("Büyük daire (gerçek en kısa yol)",
                                                   "buyuk_daire"),
                                                  ("Düz çizgi", "duz")],
                                                 value="kavis", label="Çizgi")
                    with gr.Row():
                        b.hr_bicim = gr.Radio([("Yatay 1920×1080", "yatay"),
                                               ("Dikey 1080×1920 · Shorts", "dikey")],
                                              value="yatay", label="Biçim")
                        b.hr_renk = gr.ColorPicker(value="#e63946", label="Rota rengi")
                    with gr.Row():
                        b.hr_sure = gr.Slider(1, 8, value=3, step=0.5,
                                              label="Bacak başına çizim süresi (sn)")
                        b.hr_fps = gr.Radio([30, 60], value=30, label="FPS")
                    with gr.Row():
                        b.hr_kamera = gr.Radio([("Rotayı izle", "izle"), ("Sabit", "sabit")],
                                               value="izle", label="Kamera")
                        b.hr_etiket = gr.Checkbox(value=True, label="Durak adlarını yaz")
                        b.hr_karartma = gr.Checkbox(value=True, label="Kenar karartma")
                    with gr.Row():
                        b.hr_onizle_btn = gr.Button("🖼 Önizle")
                        b.hr_uret_btn = gr.Button("🎬 Video üret", variant="primary")
                    b.hr_durum = gr.Textbox(label="Durum", interactive=False, lines=3,
                                            value=HR_HAZIR)
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("02", "Sonuç", "Önizleme son kareyi gösterir."))
                    b.hr_onizleme = gr.Image(label="Önizleme", interactive=False, type="pil")
                    b.hr_video = gr.Video(label="Harita videosu", interactive=False)

    def bagla(self, b):
        girdiler = [b.hr_duraklar, b.hr_stil, b.hr_cizgi, b.hr_renk, b.hr_bicim, b.hr_sure,
                    b.hr_fps, b.hr_kamera, b.hr_etiket, b.hr_karartma]
        b.hr_onizle_btn.click(hr_onizle, girdiler, [b.hr_durum, b.hr_onizleme],
                              concurrency_limit=1, api_name=False)
        b.hr_uret_btn.click(hr_uret, girdiler, [b.hr_durum, b.hr_video],
                            concurrency_limit=1, api_name=False)
