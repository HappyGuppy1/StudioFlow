"""StudioFlow görünüm kaynakları (tema): CSS, logo ve statik başlık parçaları.

Üretim ve dosya işlemlerinden bağımsızdır; yalnızca arayüz katmanı kullanır.
"""
from base64 import b64encode
from html import escape

import gradio as gr

from studioflow.cekirdek.yollar import ASSETS, LOGO_PNG

# Gradio teması: vurgu rengi StudioFlow mavisi (#375bdd = 600). Sekme çizgisi, kaydırıcı,
# onay kutusu gibi Gradio'nun kendi çizdiği öğeler varsayılan turuncu yerine bu
# skaladan renk alır; CSS'teki `--sf-accent` ile aynı aile.
_SF_MAVI = gr.themes.Color(
    c50="#eef2fd", c100="#dde5fb", c200="#bccbf6", c300="#93abf0", c400="#6c8ae8",
    c500="#4b6fe2", c600="#375bdd", c700="#2949c5", c800="#243d9e", c900="#22367d",
    c950="#172249", name="sf_mavi")
GRADIO_TEMASI = gr.themes.Default(primary_hue=_SF_MAVI)

CSS = (ASSETS / "studioflow.css").read_text(encoding="utf-8")
# Sayfa başlığına eklenen davranış betiği (bkz. `studioflow.js`): `launch(head=...)`.
HEAD_JS = "<script>" + (ASSETS / "studioflow.js").read_text(encoding="utf-8") + "</script>"

_LOGO = b64encode(LOGO_PNG.read_bytes()).decode("ascii")

HEADER = f"""
<div class="sf-brandbar">
  <img class="sf-brandmark" src="data:image/png;base64,{_LOGO}" alt="StudioFlow logosu" width="44" height="44">
  <div><div class="sf-brandname">StudioFlow<span class="sf-brand-dot">.</span></div>
  <div class="sf-brandcaption">Fikrinden son kareye.</div></div>
  <span class="sf-brandlabel">YARATICI STÜDYO</span>
</div>
"""

PROJECT_HERO = """
<div class="sf-hero">
  <div class="sf-hero-copy">
    <div class="sf-eyebrow">PROJE KÜTÜPHANESİ</div>
    <h1>Bir hikâye.<br><span>Sayısız kare.</span></h1>
    <p>Yeni bir fikirle başla veya kaldığın yerden devam et.<br>
    Anlatım, görsel ve ses; hepsi aynı projede.</p>
  </div>
  <div class="sf-storyboard" aria-hidden="true">
    <div class="sf-film sf-film-back"><span>ANLATIM</span><div class="sf-scriptline"></div><div class="sf-scriptline short"></div><div class="sf-scriptline"></div></div>
    <div class="sf-film sf-film-front"><span>STUDIOFLOW</span><div class="sf-play">▶</div><div class="sf-film-bottom"><span>HİKÂYEN BAŞLASIN</span><span>16:9</span></div></div>
    <div class="sf-wave"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
  </div>
</div>
"""



def page_heading(kicker, title, description):
    """Araç ve ayar sayfalarında yalnızca statik başlık üretir."""
    return (f'<div class="sf-page-heading"><div class="sf-page-kicker">{escape(kicker)}</div>'
            f'<h1>{escape(title)}</h1><p>{escape(description)}</p></div>')


def adim_basligi(numara, baslik, aciklama):
    """Üretim sütunundaki adım başlığı: küçük numara rozeti + tek satırlık not."""
    return (f'<div class="sf-adim-baslik"><span>{escape(numara)}</span><div><b>{escape(baslik)}</b>'
            f'<small>{escape(aciklama)}</small></div></div>')


def panel_heading(number, title, description):
    return (f'<div class="sf-panel-heading"><span class="sf-panel-number">{escape(number)}</span>'
            f'<div><h2>{escape(title)}</h2><p>{escape(description)}</p></div></div>')


TOOLS_HEADING = page_heading("YARATICI ARAÇLAR", "Fikrine bir adım daha yaklaş.",
                             "Görüntüye hareket, metne ses, hikâyene yeni bir dünya kat.")
VIDEO_HEADING = page_heading("FOTOĞRAFTAN VİDEO", "Bir kareyi harekete geçir.",
                             "Fotoğrafını seç, hareketi tarif et ve klibini oluştur.")
IMAGE_HEADING = page_heading("GÖRSEL ÜRETİMİ", "Aklındaki görüntüyü oluştur.",
                             "Sahneni anlat; model, boyut ve stilini sen belirle.")
CHARACTER_HEADING = page_heading("SABİT KARAKTER", "Her sahnede aynı karakter.",
                                 "Karakterini bir kez belirle; her sahne o referansla üretilsin.")
VOICE_HEADING = page_heading("SESLENDİRME", "Kelimelerine bir ses ver.",
                             "Anlatımını hazırla, sesini seç, ses ve altyazı dosyalarını birlikte al.")
PROMPT_HEADING = page_heading("PROMPT STÜDYOSU", "Araştırmadan sahneye.",
                              "Olayı araştır, seslendirme ve tasarım yönergelerini hazırla, sahneleri planla.")
MUSIC_HEADING = page_heading("MÜZİK ÜRETİMİ", "Hikâyene bir melodi yaz.",
                             "Müziği tarif et; Lyria ücretsiz ve telifsiz enstrümantal müzik üretsin.")
SFX_HEADING = page_heading("SES EFEKTİ", "Sahneye sesini ver.",
                           "İsteğini anlat; yapay zekâ telifsiz (CC0) kütüphaneden en uygun sesleri bulsun.")
TRANSCRIBE_HEADING = page_heading("SESTEN YAZIYA", "Konuşmayı metne dök.",
                                  "Video ya da ses dosyanı ver; Gemini metni ve istersen zamanlı altyazısını çıkarsın.")
MAP_HEADING = page_heading("HARİTA ANİMASYONU", "Hikâyeni haritada yürüt.",
                           "Durakları yaz; kamera haritada uçsun, rota kendini çizsin.")
UPSCALE_HEADING = page_heading("VİDEO BÜYÜTME", "Kliplerini 1080×1920'ye taşı.",
                               "Videoların Kaggle'ın ücretsiz GPU'sunda büyütülür; bilgisayarın yorulmaz.")
ACCOUNTS_HEADING = page_heading("BAĞLANTILAR", "Tüm hesapların, tek bir yerde.",
                                "Servisini seç, hesabını bağla ve üretimde kullanılacak hesabı yönet.")
SETTINGS_DRAWER_HEADING = page_heading("STÜDYO AYARLARI", "Çalışma alanın.",
                                       "Görünüm ve uygulama tercihlerini buradan yönet.")
