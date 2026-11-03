"""Sayfa okuma: bir URL'nin menü, reklam ve alt bilgi dışındaki **asıl metni**.

İki katman:

1. **trafilatura** (yerel, anahtarsız): sayfa `requests` ile indirilir, asıl metin
   çıkarılır. Çoğu haber/ansiklopedi sayfası burada biter.
2. **Jina Reader** (`r.jina.ai`): yerel okuyucunun açamadığı sayfalar (JavaScript ile
   dolan, PDF, indirmeyi engelleyen). Anahtarsız dakikada 20 sayfa; anahtar varsa
   sınır yükselir.

Okunamayan sayfa hata değildir: boş metin döner, araştırma o kaynağın özetiyle sürer.
"""
import requests

try:
    import trafilatura
except ImportError:          # paket kurulu değil: yalnızca Jina kullanılır
    trafilatura = None

JINA_URL = "https://r.jina.ai/"

# Bazı siteler tanımadığı istemcilere boş sayfa döndürüyor; sıradan bir tarayıcı gibi görünülür.
TARAYICI = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

# Bu uzunluğun altındaki çıkarım "okunamadı" sayılır ve sıradaki katman denenir.
YETERLI_METIN = 600


def _yerel(url):
    if trafilatura is None:
        return ""
    try:
        yanit = requests.get(url, timeout=(10, 30), headers={"User-Agent": TARAYICI})
    except requests.RequestException:
        return ""
    tur = yanit.headers.get("content-type", "").lower()
    if not yanit.ok or "html" not in tur:
        return ""
    try:
        return trafilatura.extract(yanit.text, url=url, include_comments=False,
                                   include_tables=True, favor_precision=True) or ""
    except Exception:
        return ""


def jina_oku(url, anahtar=""):
    basliklar = {"X-Return-Format": "text"}
    if (anahtar or "").strip():
        basliklar["Authorization"] = f"Bearer {anahtar.strip()}"
    try:
        yanit = requests.get(JINA_URL + url, headers=basliklar, timeout=(10, 60))
    except requests.RequestException:
        return ""
    return yanit.text if yanit.ok else ""


def oku(url, jina_anahtari=""):
    """`(metin, okuyucu)`; okunamazsa `("", "")`."""
    metin = _yerel(url).strip()
    if len(metin) >= YETERLI_METIN:
        return metin, "yerel"
    jina = jina_oku(url, jina_anahtari).strip()
    if len(jina) > len(metin):
        return jina, "Jina Reader"
    return (metin, "yerel") if metin else ("", "")
