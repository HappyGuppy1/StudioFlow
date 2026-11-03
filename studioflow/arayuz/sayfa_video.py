"""Araçlar › Fotoğraftan video sekmesi.

Üstte iki düğme iki sayfa arasında geçiş yapar: **Hugging Face** (Wan 2.2, ZeroGPU
kotası) ve **Agnes AI** (Video V2.0, ücretsiz API anahtarı). Sayfalar
birbirinden bağımsızdır; her biri kendi fotoğrafını, prompt'unu ve çıktısını tutar.
"""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_video import (
    agnes_baglanti, agnes_run, connection, kaynak_agnes, kaynak_hf, run)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.cekirdek.yollar import ASSETS
from studioflow.saglayicilar import video_agnes, video_huggingface
from studioflow.saglayicilar.video_huggingface import PROMPT, SPACE_URL


class VideoAraciSayfasi(Sayfa):
    ad = "video"

    def kur(self, b):
        with gr.Tab("Fotoğraftan video", elem_id="sf-video-tool"):
            gr.HTML(tema.VIDEO_HEADING)
            # Kaynak seçimi: seçili sayfanın düğmesi `primary` görünür.
            with gr.Row(equal_height=True, elem_classes=["sf-video-kaynak"]):
                b.vid_hf_btn = gr.Button("🤗 Hugging Face · Wan 2.2", variant="primary")
                b.vid_agnes_btn = gr.Button("Agnes AI · Video 2.5 Flash", variant="secondary")
            with gr.Column(visible=True) as b.vid_hf_sayfa:
                self._hf_sayfasi(b)
            with gr.Column(visible=False) as b.vid_agnes_sayfa:
                self._agnes_sayfasi(b)

    def _hf_sayfasi(self, b):
        with gr.Accordion('Servis ve kullanım bilgisi', open=False, elem_classes=["sf-help"]):
            gr.Markdown(f"İşlem [Hugging Face ZeroGPU]({SPACE_URL}) üzerinde gerçekleşir. Fotoğraf ve prompt seçili topluluk Space'ine gönderilir. Ücretsiz kota ve sıra geçerlidir.")
        with gr.Row(elem_classes=["sf-tool-grid"]):
            with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                gr.HTML(tema.panel_heading('01', 'Kaynak ve hareket', 'Fotoğrafını ve hareket yönergelerini hazırla.'))
                b.photo = gr.Image(label="Fotoğraf", type="filepath", sources=["upload"], value=str(ASSETS / "ornek.jpg"))
                b.prompt = gr.Textbox(label="Nasıl hareket etsin?", value=PROMPT, lines=4)
                with gr.Row():
                    # Sınırlar Space'in kendi imzasından: 0,5–10 sn, 1–10 adım, kalite 1–10.
                    b.duration = gr.Slider(video_huggingface.SURE_ALT, video_huggingface.SURE_UST, value=2,
                                         step=0.5, label="Video süresi (saniye)",
                                         info="Space 8–160 kare üretir (16 fps): 0,5–10 saniye.")
                    b.steps = gr.Slider(video_huggingface.ADIM_ALT, video_huggingface.ADIM_UST, value=4, step=1,
                                      label="Üretim adımı", info="4–8 adım önerilir.")
                with gr.Row():
                    b.fps = gr.Dropdown(
                        [(f"{kare} fps" + (" · önerilen" if kare == video_huggingface.FPS_VARSAYILAN
                                           else " · araya kare eklenir"), kare)
                         for kare in video_huggingface.FPS_SECENEKLERI],
                        value=video_huggingface.FPS_VARSAYILAN, label="Akıcılık (kare hızı)",
                        info="Yükseldikçe Space araya kare üretir: daha akıcı, daha yavaş.")
                    b.quality = gr.Slider(video_huggingface.KALITE_ALT, video_huggingface.KALITE_UST,
                                        value=video_huggingface.KALITE_VARSAYILAN, step=1,
                                        label="Video kalitesi",
                                        info="Yüksek değer dosyayı büyütür.")
                with gr.Row():
                    b.check = gr.Button("Bağlantıyı kontrol et")
                    b.start = gr.Button("Videoyu üret", variant="primary")
            with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                gr.HTML(tema.panel_heading('02', 'Video önizleme', 'Üretilen klibini izle ve indir.'))
                b.video = gr.Video(label="Üretilen video")
                b.download = gr.File(label="MP4 dosyasını indir")
                b.status = gr.Textbox(label="Durum", value="Hazır. Örnek fotoğraf yüklü; ilk deneme 2 saniye / 4 adım.", interactive=False, lines=4)
        with gr.Accordion("Kayıt ve kullanım notları", open=False, elem_classes=["sf-help"]):
            gr.Markdown("Video, **Ayarları kaydet** panelindeki **otomatik kaydet** kutusu işaretliyse **outputs** klasörüne yazılır; "
                        "kapalıyken geçici klasörde kalır ve yalnızca indirme kutusundan alınır. "
                        "Kota hatasında otomatik yeniden deneme yapılmaz. Ücretsiz kullanım, servisin güncel kotasına ve erişilebilirliğine bağlıdır.  \n"
                        "**Sınırlar Space'in kendisinden gelir** (tahmin değil): süre **0,5–10 saniye** "
                        "(8–160 kare ÷ 16 fps), adım **1–10**, akıcılık **16/32/64/128 fps**, kalite **1–10**. "
                        "10 saniyelik klip, 5 saniyelikten yaklaşık **iki kat GPU süresi** harcar.")

    def _agnes_sayfasi(self, b):
        with gr.Accordion('Servis ve kullanım bilgisi', open=False, elem_classes=["sf-help"]):
            gr.Markdown(
                f"İşlem [Agnes AI]({video_agnes.PLATFORM_URL}) sunucularında gerçekleşir (Sapiens AI, "
                "Singapur). Anahtarı **API hesapları** sekmesinde **Agnes AI** hizmetine kaydet; "
                "kayıt ücretsizdir, kredi kartı istemez.  \n"
                "Model **Agnes Video 2.5 Flash**'tır (720P, fotoğraf **ilk kare** olur). Eski "
                "V2.0 belgeden kalktı ve kareye sadık değildi.  \n"
                "Ücretsiz anahtar video için **dakikada 1 istek** alır; belgede sayısı verilmeyen bir "
                "**günlük süre kotası** da vardır.  \n"
                "**Gizlilik:** ücretsiz kullanımda gönderdiğin fotoğraf, prompt ve üretilen video "
                "Agnes'in modellerini geliştirmek için kullanılabilir.")
        with gr.Row(elem_classes=["sf-tool-grid"]):
            with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                gr.HTML(tema.panel_heading('01', 'Kaynak ve hareket',
                                           'Fotoğraf isteğe bağlıdır: boş bırakırsan yalnızca metinden üretilir.'))
                b.ag_photo = gr.Image(label="Fotoğraf · ilk kare (isteğe bağlı)", type="filepath",
                                      sources=["upload"], value=str(ASSETS / "ornek.jpg"))
                b.ag_prompt = gr.Textbox(label="Nasıl hareket etsin?", value=video_agnes.PROMPT, lines=4)
                b.ag_model = gr.Dropdown(list(video_agnes.MODELLER), value=video_agnes.MODEL_VARSAYILAN,
                                         label="Model")
                with gr.Row():
                    b.ag_duration = gr.Slider(video_agnes.SURE_ALT, video_agnes.SURE_UST,
                                              value=video_agnes.SURE_VARSAYILAN, step=1,
                                              label="Video süresi (saniye)",
                                              info="Agnes 4–12 saniye kabul eder.")
                    b.ag_oran = gr.Dropdown(list(video_agnes.ORANLAR), value=video_agnes.ORAN_VARSAYILAN,
                                            label="En-boy oranı",
                                            info="720P: 16:9 → 1248×704, 9:16 → 720×1280.")
                with gr.Row():
                    b.ag_check = gr.Button("Anahtarı kontrol et")
                    b.ag_start = gr.Button("Videoyu üret", variant="primary")
            with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                gr.HTML(tema.panel_heading('02', 'Video önizleme', 'Üretilen klibini izle ve indir.'))
                b.ag_video = gr.Video(label="Üretilen video")
                b.ag_download = gr.File(label="MP4 dosyasını indir")
                b.ag_status = gr.Textbox(label="Durum", interactive=False, lines=4,
                                         value="Hazır. Önce **Anahtarı kontrol et** ile Agnes AI anahtarını dene.")
        with gr.Accordion("Kayıt ve kullanım notları", open=False, elem_classes=["sf-help"]):
            gr.Markdown("Video, **otomatik kaydet** açıksa **outputs** klasörüne, kapalıysa geçici klasöre yazılır "
                        "(Hugging Face sayfasıyla aynı kural).  \n"
                        "Fotoğraf gönderilmeden önce en çok 1280 piksele küçültülür ve EXIF bilgisi silinir. "
                        "Agnes belgesi ilk kareyi herkese açık bir adres olarak ister; uygulama fotoğrafı dosya "
                        "içeriği (base64) olarak gönderir. Agnes reddederse durum kutusu bunu yazar; o durumda "
                        "fotoğrafı kaldırıp yalnızca metinle deneyebilirsin.  \n"
                        "Sonuç sorgusu da dakikalık sınıra sayıldığı için durum birkaç saniyede bir sorulur; "
                        "sınır dolarsa uygulama bekleyip kendiliğinden yeniden sorar.")

    def bagla(self, b):
        kaynak_ciktilari = [b.vid_hf_sayfa, b.vid_agnes_sayfa, b.vid_hf_btn, b.vid_agnes_btn]
        b.vid_hf_btn.click(kaynak_hf, None, kaynak_ciktilari, api_name=False)
        b.vid_agnes_btn.click(kaynak_agnes, None, kaynak_ciktilari, api_name=False)
        b.check.click(connection, None, [b.status], api_name=False)
        b.start.click(run, [b.photo, b.prompt, b.duration, b.steps, b.fps, b.quality], [b.video, b.download, b.status],
                    concurrency_limit=1, api_name=False)
        b.ag_check.click(agnes_baglanti, None, [b.ag_status], api_name=False)
        b.ag_start.click(agnes_run, [b.ag_photo, b.ag_prompt, b.ag_model, b.ag_duration, b.ag_oran],
                         [b.ag_video, b.ag_download, b.ag_status], concurrency_limit=1, api_name=False)
