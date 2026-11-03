"""Araçlar › Prompt sekmesi: beş alt düğme; mevcut prompt üretimi **Sahne planla**da."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_prompt import (
    prompt_ai_kontrol, prompt_ai_secenekleri, prompt_uret)
from studioflow.arayuz.sabitler import PROMPT_AI_LINKLERI, STYLE
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import metin_ortak, ses_edge
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS, VOICES


class PromptAraciSayfasi(Sayfa):
    """Araçlar › Prompt: Araştırma · Video konusu bul · Seslendirme promptu · Tasarım
    promptu · Sahne planla.

    **Araştırma**, **Video konusu bul**, **Seslendirme promptu** ve **Tasarım promptu** alt
    sekmeleri kendi sayfa sınıflarıdır (`ArastirmaAraciSayfasi`, `KonuBulSayfasi`,
    `SeslendirmePromptuSayfasi`, `TasarimPromptuSayfasi`); bileşenleri burada, alt sekme
    çubuğunun içinde kurulur, olayları kendi `bagla`larında bağlanır.
    """

    ad = "prompt"

    def __init__(self, arastirma, konu_bul, seslendirme, tasarim):
        self.arastirma = arastirma
        self.konu_bul = konu_bul
        self.seslendirme = seslendirme
        self.tasarim = tasarim

    def kur(self, b):
        with gr.Tab("Prompt", elem_id="sf-prompt-tool"):
            gr.HTML(tema.PROMPT_HEADING)
            # Beş alt düğme, akış sırasıyla: araştır → viral konu bul → seslendirme →
            # tasarım → sahneleri planla. Görünüm Araçlar'ın sekme çubuğuyla aynıdır
            # (`sf-tool-tabs`).
            with gr.Tabs(elem_classes=["sf-tool-tabs", "sf-prompt-tabs"]):
                self.arastirma.kur(b)
                self.konu_bul.kur(b)
                self.seslendirme.kur(b)
                self.tasarim.kur(b)
                with gr.Tab("Sahne planla", elem_id="sf-scene-plan"):
                    with gr.Accordion('Prompt üretimi nasıl çalışır?', open=False, elem_classes=["sf-help"]):
                        gr.Markdown(
                            "# Video prompt'ları\n"
                            "Anlatım metnini yaz; uygulama sesi **gerçekten üretip** toplam süreyi ölçer, süreyi parça "
                            "süresine (varsayılan 5 saniye) böler ve **her parça için** görsel üretim (image) ve video "
                            "üretim (image-to-video) prompt'larını bir yapay zekâ servisiyle yazar. Sonuç masaüstüne ve "
                            "**outputs/prompts** klasörüne metin dosyası olarak kaydedilir."
                        )
                    with gr.Row(elem_classes=["sf-tool-grid"]):
                        with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                            gr.HTML(tema.panel_heading('01', 'Anlatım ve zamanlama', 'Metni, dili ve seslendirme tercihini belirle.'))
                            b.pr_metin = gr.Textbox(label="Videonun anlatım metni", lines=10,
                                                  placeholder="Seslendirilecek metni buraya yapıştır…")
                            b.pr_parca = gr.Slider(2, 10, value=5, step=0.5, label="Parça süresi (saniye)")
                            b.pr_dil = gr.Dropdown([(name, code) for code, name in LANGUAGES.items()],
                                                 value="tr", label="Anlatım dili")
                            gr.Markdown("**Seslendirme** · süre ölçümü bu ayarlarla yapılır; ses gerçekten üretilir.")
                            b.pr_ses_provider = gr.Radio(
                                [("Edge · anahtarsız, hızlı", "edge"), ("Gemini · en doğal", "gemini"),
                                 ("Chatterbox · ses klonu", "chatterbox")],
                                value="gemini", label="Seslendirme servisi")
                            with gr.Group(visible=False) as b.pr_edge_box:
                                b.pr_edge_ses = gr.Dropdown(choices=ses_edge.VARSAYILAN.guvenli_sesler("tr"),
                                                          value="tr-TR-AhmetNeural", label="Edge sesi")
                                with gr.Row():
                                    b.pr_hiz = gr.Slider(-50, 50, value=0, step=5, label="Konuşma hızı (%)")
                                    b.pr_ton = gr.Slider(-50, 50, value=0, step=5, label="Ton (Hz)")
                            with gr.Group(visible=True) as b.pr_gemini_box:
                                with gr.Row():
                                    b.pr_gemini_model = gr.Dropdown(GEMINI_MODELS, value=GEMINI_MODELS[0],
                                                                  label="Gemini ses modeli")
                                    b.pr_gemini_ses = gr.Dropdown(VOICES, value="Charon", label="Gemini sesi")
                                b.pr_gemini_stil = gr.Textbox(label="Anlatım üslubu (İngilizce yaz)", value=STYLE, lines=2)
                            with gr.Group(visible=False) as b.pr_chatterbox_box:
                                b.pr_ref = gr.Audio(label="Referans ses · 3–30 saniye temiz kayıt", type="filepath",
                                                  sources=["upload", "microphone"])
                                with gr.Row():
                                    b.pr_exag = gr.Slider(0, 2, value=0.5, step=0.05, label="Duygu yoğunluğu")
                                    b.pr_cfg = gr.Slider(0, 1, value=0.5, step=0.05, label="Referansa bağlılık")
                        with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                            gr.HTML(tema.panel_heading('02', 'Yapay zekâ ve stil', 'Sahnelerin görsel dünyasını yönlendir.'))
                            gr.Markdown("**Prompt yapay zekâsı** · hesaplar *API hesapları* sekmesinde tutulur. "
                                        "Seçili servis kota, yetki ya da model hatası verirse **anahtarı "
                                        "kayıtlı yedek servise otomatik geçilir** (Gemini → EVREN → ChatGPT → Claude); "
                                        "akış durmaz. "
                                        f"Anahtar sayfaları: {PROMPT_AI_LINKLERI}")
                            b.pr_ai = gr.Radio(
                                [("Gemini", "gemini"), ("EVREN (SSB)", "evren"),
                                 ("ChatGPT (OpenAI)", "openai"),
                                 ("Claude (Anthropic)", "anthropic")],
                                value="gemini", label="Servis")
                            b.pr_ai_model = gr.Dropdown(
                                metin_ortak.AI_SAGLAYICILAR[metin_ortak.AI_VARSAYILAN]["models"],
                                value=metin_ortak.AI_SAGLAYICILAR[
                                    metin_ortak.AI_VARSAYILAN]["models"][0],
                                label="Model", allow_custom_value=True)
                            b.pr_gorsel_stil = gr.Textbox(
                                label="Genel görsel stil (opsiyonel, İngilizce)", lines=2,
                                placeholder="cinematic, photorealistic, warm natural light, 35mm")
                            with gr.Row():
                                b.pr_ai_kontrol_btn = gr.Button("Yapay zekâ bağlantısını kontrol et")
                                b.pr_uret_btn = gr.Button("Prompt'ları üret", variant="primary")
                            with gr.Group(elem_classes=["sf-result-group"]):
                                gr.HTML(tema.panel_heading('03', 'Sahne çıktıları', 'Ölçülen ses, prompt dosyaları ve önizleme.'))
                                b.pr_ses = gr.Audio(label="Ölçüm için üretilen seslendirme", type="filepath")
                                b.pr_dosyalar = gr.File(label="Prompt dosyaları", file_count="multiple")
                                b.pr_durum = gr.Textbox(label="Durum", interactive=False, lines=5,
                                    value="Hazır. Anlatımı yaz; seslendirme servisini ve prompt yapay zekâsını seç.")
                                b.pr_onizleme = gr.Textbox(label="Prompt önizleme (ilk parçalar)", interactive=False, lines=10)
                    with gr.Accordion("Kayıt ve kullanım notları", open=False, elem_classes=["sf-help"]):
                        gr.Markdown(
                            "Seslendirme gerçek olarak üretilir; başarısız olursa süre kelime hızından tahmin edilir ve "
                            "durum bunu belirtir. Her parça 5 saniyelik **image-to-video** üretimine göre planlanır: "
                            "önce görsel prompt'u, sonra o görseli hareket ettiren video prompt'u yazılır."
                        )

    def bagla(self, b):
        b.pr_ses_provider.change(
            lambda name: [gr.Group(visible=name == ad) for ad in ("edge", "gemini", "chatterbox")],
            [b.pr_ses_provider], [b.pr_edge_box, b.pr_gemini_box, b.pr_chatterbox_box], api_name=False)
        b.pr_dil.change(lambda lang: gr.update(choices=ses_edge.VARSAYILAN.guvenli_sesler(lang),
                                             value=(ses_edge.VARSAYILAN.guvenli_sesler(lang) or [None])[0]),
                      [b.pr_dil], [b.pr_edge_ses], api_name=False)
        b.pr_ai.change(prompt_ai_secenekleri, [b.pr_ai], [b.pr_ai_model], api_name=False)
        b.pr_ai_kontrol_btn.click(prompt_ai_kontrol, [b.pr_ai, b.pr_ai_model], [b.pr_durum], api_name=False)
        b.pr_uret_btn.click(prompt_uret,
                          [b.pr_ai, b.pr_ai_model, b.pr_metin, b.pr_dil, b.pr_ses_provider, b.pr_edge_ses, b.pr_hiz,
                           b.pr_ton, b.pr_gemini_model, b.pr_gemini_ses, b.pr_gemini_stil, b.pr_gorsel_stil,
                           b.pr_ref, b.pr_exag, b.pr_cfg, b.pr_parca],
                          [b.pr_ses, b.pr_dosyalar, b.pr_onizleme, b.pr_durum],
                          concurrency_limit=1, api_name=False)
