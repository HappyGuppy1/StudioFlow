"""Araçlar › Prompt › **Video konusu bul** alt sekmesi: viral Shorts / TikTok araştırması.

Kullanıcı ne aradığını kendi cümleleriyle yazar; yapay zekâ isteği alt konulara ve
platform başına arama sorgularına çevirir. YouTube Shorts (resmî API ya da anahtarsız
yt-dlp) ve TikTok (Apify) sonuçları izlenmeye göre sıralanıp özetlenir; ham veri
`outputs/viral/` klasörüne `.json` + `.csv` + `.txt` olarak yazılır. Sonuç listesi
başlıkları tıklanınca video yeni sekmede açılır; liste **Listeyi indir** ile `.txt` alınır.
"""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_arastirma import arastirma_model_secenekleri
from studioflow.arayuz.islevler_konu_bul import (
    kb_baslat, kb_durdur, kb_kaynak_durumu, kb_liste_html)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.hikaye.konu_bul import VARSAYILAN_ESIK, ZAMAN_ETIKETLERI
from studioflow.saglayicilar.metin_ortak import EN_IYI_MODELLER, ai_secenekleri

KB_VARSAYILAN_AI = "gemini"


class KonuBulSayfasi(Sayfa):
    ad = "konu_bul"

    def kur(self, b):
        # Prompt sayfasının alt sekmesi; `PromptAraciSayfasi.kur` alt sekme çubuğunun
        # içinde çağırır.
        with gr.Tab("Video konusu bul", elem_id="sf-topic-find") as b.kb_tab:
            with gr.Accordion("Video konusu nasıl bulunur?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "# Viral Shorts / TikTok araştırması\n"
                    "1. **Anlama** · yapay zekâ isteğini farklı açılardan alt konulara ve "
                    "platform başına arama sorgularına çevirir.\n"
                    "2. **YouTube Shorts** · anahtar varsa resmî **YouTube Data API** "
                    "(izlenmeye göre sıralı, tarihli arama), yoksa anahtarsız **yt-dlp**. "
                    "Sonuçlar `/shorts/` kontrolüyle kesinleştirilir.\n"
                    "3. **TikTok** · Apify `clockworks/tiktok-scraper` (ücretsiz plan ayda 5 $). "
                    "Token yoksa TikTok atlanır.\n"
                    "4. **Özet** · alt konu × platform: video sayısı, viral sayısı, medyan "
                    "izlenme ve en çok izlenen video; tarih bilinirse **günlük izlenme** de "
                    "hesaplanır.\n"
                    "5. **Kayıt** · `outputs/viral/<tarih>_<istek>.json` + `.csv` + `.txt`.\n"
                    "6. **Liste** · başlığa tıklayınca video yeni sekmede açılır; **Listeyi "
                    "indir** ile videoların listesi `.txt` olarak kaydedilir.\n\n"
                    "Gizlilik notu: **izleyici tutma grafiği, trafik kaynağı ve demografi** "
                    "hiçbir ücretsiz yolla toplanamaz; yalnızca kanal sahibinin Studio/TikTok "
                    "Analytics ekranında görünür. Buradaki veriler herkese açık "
                    "izlenme/beğeni/yorum sayılarıdır.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "İstek",
                                               "Ne aradığını kendi cümlelerinle yaz."))
                    b.kb_istek = gr.Textbox(
                        label="Araştırmak istediğin konu", lines=3,
                        placeholder="ör. Osmanlı'yla ilgili az bilinen ilginç olaylar")
                    b.kb_platformlar = gr.CheckboxGroup(
                        [("YouTube Shorts", "youtube"), ("TikTok", "tiktok")],
                        value=["youtube", "tiktok"], label="Platformlar")
                    b.kb_zaman = gr.Radio([(etiket, ad) for ad, etiket in ZAMAN_ETIKETLERI.items()],
                                          value="ay", label="Zaman aralığı")
                    with gr.Row():
                        b.kb_adet = gr.Slider(5, 50, value=20, step=5,
                                              label="Sorgu başına video")
                        b.kb_alt_konu = gr.Slider(1, 8, value=5, step=1, label="Alt konu sayısı")
                    b.kb_esik = gr.Number(value=VARSAYILAN_ESIK, precision=0,
                                          label="Viral eşiği (izlenme)")
                    with gr.Row():
                        b.kb_baslat_btn = gr.Button("Konuları bul", variant="primary")
                        b.kb_durdur_btn = gr.Button("Durdur")
                    b.kb_not = gr.Markdown("")
                    gr.HTML(tema.panel_heading("02", "Yapay zekâ ve kaynaklar",
                                               "İsteği anlayıp arama sorgularını yazacak modeli seç."))
                    b.kb_ai = gr.Radio(ai_secenekleri(), value=KB_VARSAYILAN_AI, label="Servis")
                    b.kb_model = gr.Dropdown(
                        [EN_IYI_MODELLER[KB_VARSAYILAN_AI]],
                        value=EN_IYI_MODELLER[KB_VARSAYILAN_AI],
                        label="Model (yalnızca bu model kullanılır)", allow_custom_value=True)
                    b.kb_kaynaklar = gr.Markdown(kb_kaynak_durumu(KB_VARSAYILAN_AI))
                    gr.Markdown("YouTube ve Apify anahtarları **API hesapları** sekmesinde "
                                "eklenir. YouTube anahtarı yoksa arama yine de anahtarsız "
                                "yt-dlp ile sürer; TikTok yalnızca Apify token'ı varsa çalışır.",
                                elem_classes=["sf-storage-note"])
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("03", "Bulunan videolar",
                                               "İstediğin konuyla ilgili videolar izlenmeye göre sıralı."))
                    b.kb_durum = gr.Textbox(label="Durum", interactive=False, lines=6, max_lines=14,
                                            value="Hazır. Konuyu yaz ve **Konuları bul**'a bas.")
                    b.kb_ozet = gr.Markdown("")
                    # Başlıklar tıklanabilir; tıklayınca video yeni sekmede açılır.
                    b.kb_liste = gr.HTML(label="Videolar (izlenmeye göre sıralı)",
                                         value=kb_liste_html([]))
                    b.kb_liste_dosya = gr.DownloadButton("Listeyi indir (.txt)", variant="primary")
                    gr.Markdown("İndirilen videolar değil, **videoların listesidir** (.txt). "
                                "Bir başlığa tıklayınca video yeni sekmede açılır.",
                                elem_classes=["sf-storage-note"])

    def bagla(self, b):
        b.kb_ai.change(arastirma_model_secenekleri, [b.kb_ai], [b.kb_model], api_name=False)
        b.kb_ai.change(kb_kaynak_durumu, [b.kb_ai], [b.kb_kaynaklar], api_name=False)
        b.kb_baslat_btn.click(
            kb_baslat,
            [b.kb_istek, b.kb_platformlar, b.kb_zaman, b.kb_adet, b.kb_alt_konu, b.kb_esik,
             b.kb_ai, b.kb_model],
            [b.kb_durum, b.kb_ozet, b.kb_liste, b.kb_liste_dosya],
            concurrency_limit=1, api_name=False)
        b.kb_durdur_btn.click(kb_durdur, None, [b.kb_not], api_name=False)
