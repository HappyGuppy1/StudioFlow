"""Araçlar › Prompt › **Seslendirme promptu** alt sekmesi: araştırmadan seslendirme metni.

Ses üretilmez; kayıtlı bir araştırmadan, seçilen şablona ve hedef süreye göre
seslendirilecek metin bölüm bölüm yazılır.
"""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_arastirma import arastirma_model_secenekleri
from studioflow.arayuz.islevler_seslendirme_promptu import (
    sp_alt_secenekleri, sp_arastirma_ac, sp_arastirma_secildi, sp_arastirma_sil, sp_ceviri_yenile,
    sp_durdur, sp_kaydet, sp_kayit_ac, sp_kayit_listesi, sp_kayit_sil, sp_listesi, sp_plan_ozeti,
    sp_uret)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.hikaye import sablonlar
from studioflow.saglayicilar.metin_ortak import EN_IYI_MODELLER, ai_secenekleri

SP_VARSAYILAN_AI = "gemini"


class SeslendirmePromptuSayfasi(Sayfa):
    ad = "seslendirme_promptu"

    def kur(self, b):
        # Prompt sayfasının ikinci alt sekmesi; `PromptAraciSayfasi.kur` içinde çağrılır.
        with gr.Tab("Seslendirme promptu", elem_id="sf-voice-prompt") as b.sp_tab:
            with gr.Accordion("Seslendirme metni nasıl yazılır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Kayıtlı bir araştırmayı seç, şablonu ve hedef süreyi belirle. Yapay zekâ önce "
                    "**hikâye planını** çıkarır (yapı, kanca türü, kancanın açtığı soru, merkezdeki "
                    "insan, doruğa saklanacak sürpriz), sonra metni **bölüm bölüm** yazar: "
                    "Kanca → Bağlam → Gelişme → Doruk → Sonuç. Her bölümün kelime bütçesi hedef "
                    "süreden hesaplanır (saniyede 2,5 kelime); bütçeden çok sapan bölüm yeniden "
                    "yazdırılır.\n\n"
                    "Bölümler **tek, kesintisiz bir metin** olarak birleştirilir. İngilizce yazılan "
                    "metin okuyabilmen için Türkçeye çevrilir (çeviri seslendirilmez).\n\n"
                    "**Bu adımda ses üretilmez**, yalnızca seslendirilecek metin yazılır. Metni bir "
                    "ad vererek kaydet; ses aşaması kayıtlı seslendirmelerden seçecek. Plan, "
                    "doğrulama ve kontrol listesi panelde gösterilmez, `outputs/seslendirme/` "
                    "klasöründeki `- rapor.txt` dosyasına yazılır.\n\n"
                    "Şablon kuralları: `docs/TARIH-SHORTS-STRATEJISI.md`.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Araştırma", "Kayıtlı araştırmalardan birine tıkla."))
                    # Sabit yükseklikli panel: araştırmalar çoğaldıkça sayfa itilmez, liste
                    # kendi içinde kaydırılır (proje panelinin sınıfı).
                    with gr.Column(elem_classes=["sf-proje-paneli"]):
                        b.sp_arastirma = gr.Radio(choices=[], value=None, label="Kayıtlı araştırmalar")
                    with gr.Row(visible=False) as b.sp_ar_dugmeler:
                        b.sp_ar_ac_btn = gr.Button("Aç", variant="primary", size="sm")
                        b.sp_ar_sil_btn = gr.Button("Sil", size="sm")
                    b.sp_yenile_btn = gr.Button("Listeyi yenile", size="sm")
                    b.sp_ar_durum = gr.Markdown("")
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    b.sp_onizleme = gr.Textbox(label="Araştırma raporu (önizleme)", lines=16,
                                               max_lines=16, interactive=False)
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("02", "Şablon ve süre",
                                               "Hazır şablonu ve videonun tahmini seslendirme süresini seç."))
                    with gr.Row():
                        b.sp_sablon = gr.Dropdown(sablonlar.sablon_secenekleri(),
                                                  value=sablonlar.VARSAYILAN_SABLON, label="Şablon")
                        b.sp_alt = gr.Dropdown(sablonlar.alt_secenekleri(sablonlar.VARSAYILAN_SABLON),
                                               value=sablonlar.VARSAYILAN_ALT, label="Alt şablon")
                    b.sp_sure = gr.Slider(*sablonlar.SURE_ARALIGI, value=sablonlar.VARSAYILAN_SURE,
                                          step=5, label="Tahmini seslendirme süresi (saniye)")
                    b.sp_dil = gr.Radio([("Türkçe", "tr"), ("English", "en")], value="tr",
                                        label="Seslendirme dili")
                    b.sp_plan = gr.Markdown(sp_plan_ozeti(sablonlar.VARSAYILAN_SABLON,
                                                          sablonlar.VARSAYILAN_ALT,
                                                          sablonlar.VARSAYILAN_SURE))
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("03", "Yapay zekâ", "Metni yazacak modeli seç."))
                    b.sp_ai = gr.Radio(ai_secenekleri(), value=SP_VARSAYILAN_AI, label="Servis")
                    b.sp_model = gr.Dropdown([EN_IYI_MODELLER[SP_VARSAYILAN_AI]],
                                             value=EN_IYI_MODELLER[SP_VARSAYILAN_AI],
                                             label="Model (yalnızca bu model kullanılır)",
                                             allow_custom_value=True)
                    with gr.Row():
                        b.sp_uret_btn = gr.Button("Seslendirme metnini yaz", variant="primary")
                        b.sp_durdur_btn = gr.Button("Durdur")
                    gr.Markdown("Bu adımda **ses üretilmez**; yalnızca seslendirilecek metin yazılır.",
                                elem_classes=["sf-storage-note"])
            with gr.Group(elem_classes=["sf-result-group"]):
                gr.HTML(tema.panel_heading("04", "Seslendirme metni",
                                           "Metni gözden geçir, gerekirse düzelt, bir ad verip kaydet."))
                b.sp_durum = gr.Textbox(label="Durum", interactive=False, lines=6, max_lines=12,
                                        value="Hazır. Bir araştırma seç ve **Seslendirme metnini yaz**'a bas.")
                with gr.Row():
                    b.sp_metin = gr.Textbox(label="Seslendirme metni (düzenlenebilir)", lines=14,
                                            max_lines=24, interactive=True)
                    b.sp_ceviri = gr.Textbox(label="Türkçe önizleme (çeviri · seslendirilmez)",
                                             lines=14, max_lines=24, interactive=False)
                b.sp_ceviri_btn = gr.Button("Türkçe önizlemeyi yenile", size="sm")
                with gr.Row():
                    b.sp_ad = gr.Textbox(label="Seslendirme adı", scale=3,
                                         placeholder="ör. Alesia · 70 sn · en · aynı ad kaydı günceller")
                    b.sp_kaydet_btn = gr.Button("Seslendirmeyi kaydet", variant="primary", scale=1)
                with gr.Row():
                    b.sp_kayitli = gr.Dropdown(choices=[], value=None, label="Kayıtlı seslendirmeler",
                                               scale=3)
                    b.sp_kayit_ac_btn = gr.Button("Aç", scale=1)
                    b.sp_kayit_sil_btn = gr.Button("Sil", scale=1)
                b.sp_kayit_durum = gr.Markdown("")
                b.sp_dosyalar = gr.File(label="Dosyalar (.txt metin · .json ham veri · - rapor.txt plan ve kontroller)",
                                        file_count="multiple")
                # Ekrandaki metnin ham verisi (.json); kayda kopyalanır.
                b.sp_ham = gr.State("")

    def bagla(self, b):
        # Araştırma sekmesinde yeni kayıt yapılmış olabilir: sekmeye her gelişte liste tazelenir.
        b.sp_tab.select(sp_listesi, [b.sp_arastirma], [b.sp_arastirma], api_name=False)
        b.sp_yenile_btn.click(sp_listesi, [b.sp_arastirma], [b.sp_arastirma], api_name=False)
        b.sp_arastirma.change(sp_arastirma_secildi, [b.sp_arastirma], [b.sp_ar_dugmeler], api_name=False)
        b.sp_ar_ac_btn.click(sp_arastirma_ac, [b.sp_arastirma], [b.sp_onizleme, b.sp_ar_durum],
                             api_name=False)
        b.sp_ar_sil_btn.click(sp_arastirma_sil, [b.sp_arastirma],
                              [b.sp_arastirma, b.sp_ar_dugmeler, b.sp_onizleme, b.sp_ar_durum],
                              api_name=False)
        b.sp_sablon.change(sp_alt_secenekleri, [b.sp_sablon], [b.sp_alt], api_name=False)
        for bilesen in (b.sp_alt, b.sp_sure):
            bilesen.change(sp_plan_ozeti, [b.sp_sablon, b.sp_alt, b.sp_sure], [b.sp_plan],
                           api_name=False)
        b.sp_ai.change(arastirma_model_secenekleri, [b.sp_ai], [b.sp_model], api_name=False)
        b.sp_uret_btn.click(sp_uret, [b.sp_arastirma, b.sp_sablon, b.sp_alt, b.sp_sure, b.sp_ai,
                                      b.sp_model, b.sp_dil],
                            [b.sp_durum, b.sp_metin, b.sp_ceviri, b.sp_dosyalar, b.sp_ham, b.sp_ad],
                            concurrency_limit=1, api_name=False)
        b.sp_durdur_btn.click(sp_durdur, None, [b.sp_kayit_durum], api_name=False)
        b.sp_ceviri_btn.click(sp_ceviri_yenile, [b.sp_metin, b.sp_dil, b.sp_ai, b.sp_model],
                              [b.sp_ceviri], api_name=False)
        b.sp_kaydet_btn.click(sp_kaydet, [b.sp_ad, b.sp_metin, b.sp_ceviri, b.sp_ham],
                              [b.sp_kayit_durum, b.sp_kayitli, b.sp_ad, b.sp_ham, b.sp_dosyalar],
                              api_name=False)
        b.sp_kayit_ac_btn.click(sp_kayit_ac, [b.sp_kayitli],
                                [b.sp_kayit_durum, b.sp_metin, b.sp_ceviri, b.sp_dil, b.sp_ad,
                                 b.sp_ham, b.sp_dosyalar], api_name=False)
        b.sp_kayit_sil_btn.click(sp_kayit_sil, [b.sp_kayitli], [b.sp_kayit_durum, b.sp_kayitli],
                                 api_name=False)
        b.demo.load(sp_listesi, None, [b.sp_arastirma], api_name=False)
        b.demo.load(sp_kayit_listesi, None, [b.sp_kayitli], api_name=False)
