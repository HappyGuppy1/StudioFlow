"""Araçlar › Prompt › **Araştırma** alt sekmesi (hikâye araştırması ve kayıtlı araştırmalar)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_arastirma import (
    arastirma_ac, arastirma_baslat, arastirma_durdur, arastirma_kaydet, arastirma_katmanlari,
    arastirma_listesi, arastirma_model_secenekleri, arastirma_sil)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.hikaye.arastirma import DERINLIKLER, VARSAYILAN_DERINLIK
from studioflow.saglayicilar.metin_ortak import EN_IYI_MODELLER, ai_secenekleri

ARASTIRMA_VARSAYILAN_AI = "gemini"


class ArastirmaAraciSayfasi(Sayfa):
    ad = "arastirma"

    def kur(self, b):
        # Prompt sayfasının ilk alt sekmesi; `PromptAraciSayfasi.kur` alt sekme çubuğunun
        # içinde çağırır.
        with gr.Tab("Araştırma", elem_id="sf-research-tool"):
            with gr.Accordion("Araştırma nasıl çalışır?", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "# Katmanlı araştırma\n"
                    "1. **Plan** · yapay zekâ olayı çözer ve farklı bakış açılarından araştırma "
                    "soruları yazar (iki taraf, lojistik, sayılar, görgü tanıkları, görsel detaylar).\n"
                    "2. **Wikipedia** (Türkçe + İngilizce) · kesin tarih, kişi ve yer bilgisinin omurgası.\n"
                    "3. **Web araması** · Tavily → Exa → DDGS sırasıyla; anahtarlı serviste kotası "
                    "biten hesabın yerine sıradaki hesap geçer. Metni kısa gelen sayfalar yerel "
                    "okuyucuyla, açılamazsa Jina Reader ile okunur.\n"
                    "4. **Bilgi çıkarma** · yalnızca kaynakta yazan, kaynak numaralı bilgiler alınır; "
                    "kaynaksız bilgi rapora girmez.\n"
                    "5. **Boşluk kontrolü** · cevapsız sorular için yeni aramalar (Standart 2, Derin 3 tur).\n"
                    "6. **Sentez** · özet, zaman çizelgesi, kişiler, tartışmalı noktalar, görsel "
                    "detaylar ve anlatım önerileri.\n\n"
                    "Yapay zekâ yalnızca seçilen **en iyi modeli** kullanır; daha zayıf yedek modele "
                    "düşülmez. Kota bitince aynı servisin **sıradaki hesabına** geçilir, dakikalık "
                    "sınıra takılan hesap kısa süre bekletilir.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "Olay", "Araştırılacak olayı bir iki cümleyle yaz."))
                    b.ar_konu = gr.Textbox(
                        label="Araştırılacak olay", lines=3,
                        placeholder="ör. Fatih'in gemileri karadan yürütmesi (1453)")
                    b.ar_derinlik = gr.Radio(
                        [(ayar["etiket"], ad) for ad, ayar in DERINLIKLER.items()],
                        value=VARSAYILAN_DERINLIK, label="Araştırma derinliği")
                    b.ar_dil = gr.Radio([("Türkçe", "tr"), ("English", "en")], value="tr",
                                        label="Rapor dili")
                    with gr.Row():
                        b.ar_baslat_btn = gr.Button("Araştır", variant="primary")
                        b.ar_durdur_btn = gr.Button("Durdur")
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("02", "Yapay zekâ ve kaynaklar",
                                               "Bilgileri okuyup ayıklayacak modeli seç."))
                    b.ar_ai = gr.Radio(ai_secenekleri(), value=ARASTIRMA_VARSAYILAN_AI, label="Servis")
                    b.ar_model = gr.Dropdown(
                        [EN_IYI_MODELLER[ARASTIRMA_VARSAYILAN_AI]],
                        value=EN_IYI_MODELLER[ARASTIRMA_VARSAYILAN_AI],
                        label="Model (yalnızca bu model kullanılır)", allow_custom_value=True)
                    b.ar_katmanlar = gr.Markdown("")
                    gr.Markdown("Arama anahtarları (Tavily, Exa, Jina) **API hesapları** sekmesinde "
                                "eklenir. Hiç anahtar yoksa araştırma Wikipedia ve anahtarsız "
                                "DDGS ile yürür.", elem_classes=["sf-storage-note"])
            with gr.Group(elem_classes=["sf-result-group"]):
                gr.HTML(tema.panel_heading("03", "Araştırma raporu",
                                           "Kaynaklı bilgileri gözden geçir, gerekirse düzelt ve kaydet."))
                b.ar_durum = gr.Textbox(label="Durum", interactive=False, lines=8, max_lines=14,
                                        value="Hazır. Olayı yaz ve **Araştır**'a bas.")
                b.ar_rapor = gr.Textbox(label="Rapor (düzenlenebilir)", lines=24, max_lines=40,
                                        interactive=True)
                with gr.Row():
                    b.ar_ad = gr.Textbox(label="Araştırma adı", scale=3,
                                         placeholder="ör. Fatih'in gemileri · aynı ad kaydı günceller")
                    b.ar_kaydet_btn = gr.Button("Araştırmayı kaydet", variant="primary", scale=1)
                with gr.Row():
                    b.ar_kayitli = gr.Dropdown(choices=[], value=None, label="Kayıtlı araştırmalar",
                                               scale=3)
                    b.ar_ac_btn = gr.Button("Aç", scale=1)
                    b.ar_sil_btn = gr.Button("Sil", scale=1)
                b.ar_kayit_durum = gr.Markdown("")
                b.ar_dosyalar = gr.File(label="Rapor dosyaları (.txt rapor · .json ham veri)",
                                        file_count="multiple")
                # Ekrandaki raporun ham verisi (.json); kayda kopyalanır.
                b.ar_ham = gr.State("")

    def bagla(self, b):
        b.ar_ai.change(arastirma_model_secenekleri, [b.ar_ai], [b.ar_model], api_name=False)
        b.ar_ai.change(arastirma_katmanlari, [b.ar_ai], [b.ar_katmanlar], api_name=False)
        b.ar_baslat_btn.click(arastirma_baslat, [b.ar_konu, b.ar_derinlik, b.ar_ai, b.ar_model, b.ar_dil],
                              [b.ar_durum, b.ar_rapor, b.ar_dosyalar, b.ar_ham, b.ar_ad],
                              concurrency_limit=1, api_name=False)
        b.ar_durdur_btn.click(arastirma_durdur, None, [b.ar_kayit_durum], api_name=False)
        b.ar_kaydet_btn.click(arastirma_kaydet, [b.ar_ad, b.ar_rapor, b.ar_ham],
                              [b.ar_kayit_durum, b.ar_kayitli, b.ar_ad, b.ar_dosyalar], api_name=False)
        b.ar_ac_btn.click(arastirma_ac, [b.ar_kayitli],
                          [b.ar_kayit_durum, b.ar_rapor, b.ar_ad, b.ar_ham, b.ar_dosyalar],
                          api_name=False)
        b.ar_sil_btn.click(arastirma_sil, [b.ar_kayitli], [b.ar_kayit_durum, b.ar_kayitli],
                           api_name=False)
        b.demo.load(arastirma_katmanlari, [b.ar_ai], [b.ar_katmanlar], api_name=False)
        b.demo.load(arastirma_listesi, None, [b.ar_kayitli], api_name=False)
