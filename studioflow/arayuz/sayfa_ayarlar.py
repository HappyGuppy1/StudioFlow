"""Üst çubuk ve sağ ayar çekmecesi: kayıt tercihi, kapatma, sunucuları kapatma."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_ayarlar import close_servers, kayit_tercihi, shutdown
from studioflow.arayuz.sayfa import Sayfa


class AyarCekmecesi(Sayfa):
    ad = "ayarlar"

    def kur(self, b):
        # Üst çubuk: solda logo, ortada durum yazısı, **en sağda** ☰ ve uygulamayı kapatan ✕.
        with gr.Row(equal_height=True, elem_classes=["sf-ust-cubuk"]):
            gr.HTML(tema.HEADER, elem_classes=["sf-marka"])
            b.quit_status = gr.Markdown("", elem_classes=["sf-kapat-durum"])
            # ☰ sağdaki ayar çekmecesini açar; ✕ uygulamayı kapatır (ikisi de en sağda).
            b.ayar_ac_btn = gr.Button("☰", size="sm", scale=0, min_width=46,
                                    variant="secondary", elem_classes=["sf-menu-btn"])
            b.quit_button = gr.Button("✕", size="sm", scale=0, min_width=46, variant="stop",
                                    elem_classes=["sf-kapat-btn"])

        # ── Sağ menü: ayarlar ─────────────────────────────────────────────────────
        # Sağ kenardaki tutamaçla ya da üstteki ☰ düğmesiyle açılan çekmece
        # (`gr.Sidebar`, `position="right"`). İçindeki **Ayarlar** düğmesi Gradio'nun kendi
        # ayar panelini açar: görünüm teması, arayüz dili, PWA desteği ve ekran kaydı orada
        # seçilir. O panel Gradio'nun alt çubuğundaki dişli düğmesiyle açılan hazır bir
        # katmandır; bu düğmeye basmak için `js` olayı kullanılır (sunucuya istek gitmez,
        # `fn=None`) ve görünüşü CSS ile sağ çekmeceye çevrilir (bkz. `gradio_ayar_btn`).
        with gr.Sidebar("Ayarlar", open=False, position="right", width=420,
                        elem_id="sf-settings", elem_classes=["sf-secondary"]) as b.ayar_panel:
            gr.HTML(tema.SETTINGS_DRAWER_HEADING)
            b.gradio_ayar_btn = gr.Button("Ayarlar", variant="primary")
            gr.Markdown("---")
            with gr.Accordion("Açık sunucuları kapat", open=False):
                gr.Markdown(
                    "**Açık sunucuları kapat** — bu bilgisayarda `app.py` çalıştıran bütün "
                    "StudioFlow sunucularını kapatır: arka planda kalmış kopyalar ve bu pencere. "
                    "Kapattıktan sonra bu sekmeyle çalışamazsın; tekrar açmak için masaüstündeki "
                    "StudioFlow kısayolunu kullan.\n\n"
                    "Tek bir pencereyi kapatmak için sağ üstteki **✕** düğmesi yeterlidir.")
                with gr.Row():
                    b.close_servers_button = gr.Button("Açık sunucuları kapat", variant="stop",
                                                     size="sm", scale=0)
                    b.close_servers_status = gr.Markdown("")

    def bagla(self, b):
        b.otomatik_kaydet.change(kayit_tercihi, [b.otomatik_kaydet], [b.kayit_durum], api_name=False)
        b.quit_button.click(shutdown, None, [b.quit_status], api_name=False)
        # Sağdaki çekmece: ☰ düğmesi açar; çekmecedeki **Ayarlar** düğmesi Gradio'nun kendi
        # ayar katmanını açar (tarayıcı tarafında `js`, sunucuya istek gitmez).
        b.ayar_ac_btn.click(lambda: gr.update(open=True), None, [b.ayar_panel], api_name=False)
        b.gradio_ayar_btn.click(
            fn=None,
            js="() => { const d = document.querySelector('footer button.settings');"
               " if (d) d.click(); }",
            queue=False, api_name=False)
        b.close_servers_button.click(close_servers, None, [b.close_servers_status], queue=False, api_name=False)
