"""StudioFlow uygulama paketi.

Katmanlar (bağımlılık yalnızca aşağı doğru akar):

    arayuz  →  proje  →  saglayicilar / altyazi  →  ayarlar  →  cekirdek

`cekirdek` hiçbir üst katmanı içe aktarmaz; `saglayicilar` Gradio'yu ve projeyi bilmez;
Gradio yalnızca `arayuz` içinde kullanılır. Kuralı `tests/altin/test_bagimlilik.py`
denetler.
"""
