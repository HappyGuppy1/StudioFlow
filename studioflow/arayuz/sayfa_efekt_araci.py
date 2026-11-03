"""Araçlar › Ses efekti üret sekmesi (Freesound CC0 + yapay zekâ, projeden bağımsız)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_efekt_araci import EF_HAZIR, aday_html, ef_bul, ef_indir
from studioflow.arayuz.sayfa import Sayfa
from studioflow.arayuz.sayfa_muzik_araci import ai_secenekleri
from studioflow.saglayicilar import metin_ortak


class EfektAraciSayfasi(Sayfa):
    ad = "efekt"

    def kur(self, b):
        with gr.Tab("Ses efekti üret", elem_id="sf-sfx-tool"):
            gr.HTML(tema.SFX_HEADING)
            with gr.Accordion("Nasıl çalışır? · telif", open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Sesler **Freesound** kütüphanesinden, yalnızca **CC0** lisanslı gerçek "
                    "kayıtlardan gelir: atıf gerekmez, ticari kullanım serbesttir, GPU ya da "
                    "kota harcanmaz. İsteğini Türkçe yazabilirsin; seçtiğin yapay zekâ onu "
                    "kütüphanenin dilinde 3 aramaya çevirir, bulunan seslerin adlarını ve "
                    "etiketlerini okuyup isteğe uyanları en iyisinden sıralar. Dinle, "
                    "beğendiğini **İndir**.\n\n"
                    "Ücretsiz ve telifsiz bir **yapay zekâ ses efekti üreticisi** API'si "
                    "bulunmadığı için (ElevenLabs'in ücretsiz planı atıf ister, ticari "
                    "kullanım için ücretli) sesler kütüphaneden seçilir. Freesound anahtarı "
                    "**API hesapları** sekmesindedir.")
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading("01", "İstek", "Hangi sesi istediğini anlat."))
                    b.ef_istek = gr.Textbox(label="Ses isteği", lines=2,
                                            placeholder="ör. kumda yavaş ayak sesi · taş "
                                                        "kapı gıcırdayarak açılıyor")
                    with gr.Row():
                        b.ef_tur = gr.Radio([("Eylem · belirli an", "eylem"),
                                             ("Ortam · sürekli", "ortam")],
                                            value="eylem", label="Ses türü")
                        b.ef_sure = gr.Slider(1, 60, value=5, step=1,
                                              label="Yaklaşık süre (sn)")
                    b.ef_ai = gr.Dropdown(ai_secenekleri(), value=metin_ortak.AI_VARSAYILAN,
                                          label="Aramayı yapan yapay zekâ")
                    b.ef_bul_btn = gr.Button("🔎 Ses bul", variant="primary")
                    b.ef_durum = gr.Textbox(label="Durum", interactive=False, lines=4,
                                            value=EF_HAZIR)
                    b.ef_dosya = gr.File(label="İndirilen ses")
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading("02", "Bulunan sesler", "En uygunu en üstte; dinle ve indir."))
                    b.ef_adaylar = gr.State([])

                    @gr.render(inputs=[b.ef_adaylar], queue=False)
                    def _ef_adaylar(adaylar):
                        if not adaylar:
                            gr.Markdown("Henüz ses yok: soldan isteğini yaz ve **Ses bul**'a bas.")
                            return
                        for aday in adaylar:
                            with gr.Row(equal_height=True, elem_classes=["sf-saved-music-row"]):
                                gr.HTML(aday_html(aday), scale=5)
                                indir_btn = gr.Button("⬇ İndir", size="sm", scale=0,
                                                      min_width=90)
                            indir_btn.click(lambda a=aday: ef_indir(a), None,
                                            [b.ef_durum, b.ef_dosya], api_name=False)

    def bagla(self, b):
        b.ef_bul_btn.click(ef_bul, [b.ef_istek, b.ef_tur, b.ef_sure, b.ef_ai],
                           [b.ef_durum, b.ef_adaylar], concurrency_limit=1, api_name=False)
