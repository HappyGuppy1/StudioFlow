"""Araçlar › Prompt › **Tasarım promptu** alt sekmesi: araştırmadan prompt belgesi.

Kayıtlı bir araştırmadan genel (pozitif) prompt, görsel stil katmanı, negatif ve isteğe
bağlı ilk sahne (kanca) prompt'ları üretilir, düzenlenir ve ad verilerek kaydedilir.
Kayıt, Proje oluştur sayfasında **Prompt belgesi** olarak seçilince aynı adlı alanlara dolar.
"""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_arastirma import arastirma_model_secenekleri
from studioflow.arayuz.islevler_seslendirme_promptu import (
    sp_arastirma_ac, sp_arastirma_secildi, sp_arastirma_sil, sp_listesi)
from studioflow.arayuz.islevler_tasarim_promptu import (
    tp_durdur, tp_ilk_sahne_gorunum, tp_kayit_ac, tp_kayit_listesi, tp_kayit_sil, tp_kaydet,
    tp_model_notu, tp_onizle, tp_seslendirme_listesi, tp_uret)
from studioflow.arayuz.sabitler import PJ_VARSAYILAN_GORSEL
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import gorsel_cloudflare
from studioflow.saglayicilar.metin_ortak import EN_IYI_MODELLER, ai_secenekleri

TP_VARSAYILAN_AI = "gemini"
TP_VARSAYILAN_GORSEL = PJ_VARSAYILAN_GORSEL.get("model") or gorsel_cloudflare.VARSAYILAN_MODEL


class TasarimPromptuSayfasi(Sayfa):
    ad = "tasarim_promptu"

    def kur(self, b):
        # Prompt sayfasının üçüncü alt sekmesi; `PromptAraciSayfasi.kur` içinde çağrılır.
        with gr.Tab("Tasarım promptu", elem_id="sf-design-prompt") as b.tp_tab:
            with gr.Accordion("Tasarım promptu nasıl yazılır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Kayıtlı bir araştırmayı seç; yapay zekâ projenin prompt alanlarını yazar:\n\n"
                    "- **Genel video prompt'u (pozitif):** videonun tamamına hâkim çerçeve — konu, "
                    "karakterler, mekân, atmosfer, kamera dili. Sahneleri yazan yapay zekâ her "
                    "sahnede bunu okur.\n"
                    "- **Görsel stil katmanı:** her karenin başına eklenen fotoğraf stili (ayrı alan).\n"
                    "- **Negatif prompt:** bütün karelerde bastırılacaklar.\n"
                    "- **İlk sahne (isteğe bağlı):** kanca karesinin pozitif ve negatif prompt'u; "
                    "kayıtlı bir seslendirme seçersen kare metnin ilk cümlesini gösterir.\n\n"
                    "Kaydettiğin belge, **Proje oluştur** sayfasında proje adının altındaki "
                    "**Prompt belgesi** listesinden seçilince bu alanların hepsi kendiliğinden dolar. "
                    "Dönemin kıyafet, mimari ve karakterleri ayrıca bir **görsel rehberde** toplanır.\n\n"
                    "Kurallar `docs/STIL-PROMPT-KILAVUZU.md` ölçümlerinden gelir ve kodla da "
                    "denetlenir: stil **12–18 kelime**, ilk kelime **Photorealistic**, ressam dili "
                    "(painterly, palette, haze…) yok; negatifte **painting, signature, canvas "
                    "texture** bulunur. Stil her karenin başına otomatik eklendiği için ilk sahne "
                    "prompt'u yalnızca sahnenin içeriğini taşır.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Araştırma", "Kayıtlı araştırmalardan birine tıkla."))
                    with gr.Column(elem_classes=["sf-proje-paneli"]):
                        b.tp_arastirma = gr.Radio(choices=[], value=None, label="Kayıtlı araştırmalar")
                    with gr.Row(visible=False) as b.tp_ar_dugmeler:
                        b.tp_ar_ac_btn = gr.Button("Aç", variant="primary", size="sm")
                        b.tp_ar_sil_btn = gr.Button("Sil", size="sm")
                    b.tp_yenile_btn = gr.Button("Listeyi yenile", size="sm")
                    b.tp_ar_durum = gr.Markdown("")
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    b.tp_onizleme_rapor = gr.Textbox(label="Araştırma raporu (önizleme)", lines=16,
                                                     max_lines=16, interactive=False)
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("02", "Görsel modeli ve ilk sahne",
                                               "Prompt'lar seçilen görsel modelinin okuduğu kadar yazılır."))
                    b.tp_gorsel = gr.Dropdown(gorsel_cloudflare.cf_model_choices(),
                                              value=TP_VARSAYILAN_GORSEL, label="Görsel modeli")
                    b.tp_gorsel_not = gr.Markdown(tp_model_notu(TP_VARSAYILAN_GORSEL))
                    b.tp_ilk = gr.Checkbox(value=False, label="İlk sahne (kanca karesi) promptunu da üret")
                    b.tp_seslendirme = gr.Dropdown(choices=[("(seçme · kanca araştırmadan kurulsun)", "")],
                                                   value="", visible=False,
                                                   label="Kanca cümlesi için kayıtlı seslendirme (isteğe bağlı)")
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("03", "Yapay zekâ", "Prompt'ları yazacak modeli seç."))
                    b.tp_ai = gr.Radio(ai_secenekleri(), value=TP_VARSAYILAN_AI, label="Servis")
                    b.tp_model = gr.Dropdown([EN_IYI_MODELLER[TP_VARSAYILAN_AI]],
                                             value=EN_IYI_MODELLER[TP_VARSAYILAN_AI],
                                             label="Model (yalnızca bu model kullanılır)",
                                             allow_custom_value=True)
                    with gr.Row():
                        b.tp_uret_btn = gr.Button("Tasarım promptlarını yaz", variant="primary")
                        b.tp_durdur_btn = gr.Button("Durdur")
            with gr.Group(elem_classes=["sf-result-group"]):
                gr.HTML(tema.panel_heading("04", "Tasarım",
                                           "Prompt'ları gözden geçir, gerekirse düzelt, bir ad verip kaydet."))
                b.tp_durum = gr.Textbox(label="Durum ve kontroller", interactive=False, lines=6,
                                        max_lines=14,
                                        value="Hazır. Bir araştırma seç ve **Tasarım promptlarını yaz**'a bas.")
                # Etiketler Proje oluştur sayfasındaki alan adlarıdır: kayıt orada
                # **Prompt belgesi** seçilince aynı alanlara dolar.
                b.tp_genel = gr.Textbox(label="Genel video prompt'u · pozitif (konu, karakterler, "
                                              "mekân, atmosfer, kamera dili)", lines=5, interactive=True)
                b.tp_stil = gr.Textbox(label="Görsel stil katmanı (her karenin başına eklenir)",
                                       lines=2, interactive=True)
                b.tp_negatif = gr.Textbox(label="Negatif prompt (bütün kareler)", lines=3,
                                          interactive=True)
                with gr.Group(visible=False) as b.tp_ilk_grup:
                    with gr.Row():
                        b.tp_ilk_prompt = gr.Textbox(label="İlk sahne · ne görünsün (+)",
                                                     lines=5, interactive=True)
                        b.tp_ilk_negatif = gr.Textbox(label="İlk sahne · negatif prompt (−)", lines=5,
                                                      interactive=True)
                    b.tp_onizleme = gr.Textbox(label="Görsel modeline gidecek hâli (stil + ilk sahne)",
                                               lines=4, interactive=False)
                with gr.Accordion("Görsel rehber (dönem · kıyafet · mimari · karakterler)", open=False):
                    b.tp_rehber = gr.Textbox(show_label=False, lines=12, max_lines=24, interactive=False)
                with gr.Row():
                    b.tp_ad = gr.Textbox(label="Tasarım adı", scale=3,
                                         placeholder="ör. Alesia · tasarım · aynı ad kaydı günceller")
                    b.tp_kaydet_btn = gr.Button("Tasarımı kaydet", variant="primary", scale=1)
                with gr.Row():
                    b.tp_kayitli = gr.Dropdown(choices=[], value=None, label="Kayıtlı tasarımlar", scale=3)
                    b.tp_kayit_ac_btn = gr.Button("Aç", scale=1)
                    b.tp_kayit_sil_btn = gr.Button("Sil", scale=1)
                b.tp_kayit_durum = gr.Markdown("")
                b.tp_dosyalar = gr.File(label="Dosyalar (.txt okunur tasarım · .json ham veri)",
                                        file_count="multiple")
                b.tp_ham = gr.State("")

    def bagla(self, b):
        # Araştırma / seslendirme sekmelerinde yeni kayıt yapılmış olabilir: sekmeye her
        # gelişte iki liste de tazelenir.
        b.tp_tab.select(sp_listesi, [b.tp_arastirma], [b.tp_arastirma], api_name=False)
        b.tp_tab.select(tp_seslendirme_listesi, [b.tp_seslendirme], [b.tp_seslendirme], api_name=False)
        b.tp_yenile_btn.click(sp_listesi, [b.tp_arastirma], [b.tp_arastirma], api_name=False)
        b.tp_arastirma.change(sp_arastirma_secildi, [b.tp_arastirma], [b.tp_ar_dugmeler], api_name=False)
        b.tp_ar_ac_btn.click(sp_arastirma_ac, [b.tp_arastirma], [b.tp_onizleme_rapor, b.tp_ar_durum],
                             api_name=False)
        b.tp_ar_sil_btn.click(sp_arastirma_sil, [b.tp_arastirma],
                              [b.tp_arastirma, b.tp_ar_dugmeler, b.tp_onizleme_rapor, b.tp_ar_durum],
                              api_name=False)
        b.tp_gorsel.change(tp_model_notu, [b.tp_gorsel], [b.tp_gorsel_not], api_name=False)
        b.tp_ilk.change(tp_ilk_sahne_gorunum, [b.tp_ilk], [b.tp_seslendirme, b.tp_ilk_grup],
                        api_name=False)
        b.tp_ai.change(arastirma_model_secenekleri, [b.tp_ai], [b.tp_model], api_name=False)
        for bilesen in (b.tp_stil, b.tp_ilk_prompt, b.tp_gorsel):
            bilesen.change(tp_onizle, [b.tp_stil, b.tp_ilk_prompt, b.tp_gorsel], [b.tp_onizleme],
                           api_name=False)
        b.tp_uret_btn.click(tp_uret, [b.tp_arastirma, b.tp_gorsel, b.tp_ilk, b.tp_seslendirme,
                                      b.tp_ai, b.tp_model],
                            [b.tp_durum, b.tp_genel, b.tp_stil, b.tp_negatif, b.tp_ilk_prompt,
                             b.tp_ilk_negatif,
                             b.tp_onizleme, b.tp_rehber, b.tp_dosyalar, b.tp_ham, b.tp_ad],
                            concurrency_limit=1, api_name=False)
        b.tp_durdur_btn.click(tp_durdur, None, [b.tp_kayit_durum], api_name=False)
        b.tp_kaydet_btn.click(tp_kaydet, [b.tp_ad, b.tp_genel, b.tp_stil, b.tp_negatif, b.tp_ilk_prompt,
                                          b.tp_ilk_negatif, b.tp_rehber, b.tp_gorsel, b.tp_ham],
                              [b.tp_kayit_durum, b.tp_kayitli, b.tp_ad, b.tp_ham, b.tp_dosyalar],
                              api_name=False)
        b.tp_kayit_ac_btn.click(tp_kayit_ac, [b.tp_kayitli],
                                [b.tp_kayit_durum, b.tp_genel, b.tp_stil, b.tp_negatif, b.tp_ilk_prompt,
                                 b.tp_ilk_negatif, b.tp_onizleme, b.tp_rehber, b.tp_ilk, b.tp_gorsel,
                                 b.tp_ad, b.tp_ham, b.tp_dosyalar], api_name=False)
        b.tp_kayit_sil_btn.click(tp_kayit_sil, [b.tp_kayitli], [b.tp_kayit_durum, b.tp_kayitli],
                                 api_name=False)
        b.demo.load(sp_listesi, None, [b.tp_arastirma], api_name=False)
        b.demo.load(tp_seslendirme_listesi, None, [b.tp_seslendirme], api_name=False)
        b.demo.load(tp_kayit_listesi, None, [b.tp_kayitli], api_name=False)
