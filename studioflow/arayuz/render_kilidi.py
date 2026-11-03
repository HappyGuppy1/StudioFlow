"""Gradio 6 `@gr.render` yarışı için kilit.

`queue=False` olan render blokları (dublaj, müzik, altyazı listeleri…) aynı proje
seçiminde **aynı anda** çalışır. Gradio her render'ın sonunda ortak bileşen sözlüğünü
dolaşırken (`attach_load_events`) öbür render o sözlüğe bileşen ekler ve
`RuntimeError: dictionary changed size during iteration` doğar; hata alan blok
"Hata" yazısıyla boş kalır (ör. dublaj listesi görünmez). Render'lar kısa sürdüğü
için hepsi tek kilitle sıraya sokulur.
"""
import threading

from gradio.renderable import Renderable

_KILIT = threading.RLock()


def kur():
    """`Renderable.apply`ı kilitle sar (birden çok çağrı zararsız)."""
    if getattr(Renderable.apply, "_sf_kilitli", False):
        return
    asil = Renderable.apply

    def apply(self, *args, **kwargs):
        with _KILIT:
            return asil(self, *args, **kwargs)

    apply._sf_kilitli = True
    Renderable.apply = apply
