"""Uygulamanın bütün klasör yolları tek yerde.

Kök, paketin iki üstü olan proje klasörüdür (`app.py`'nin bulunduğu yer); kod ve
`assets/` hep buradadır. Kullanıcı verisinin yeri iki kipe göre değişir:

* **Kurulu uygulama** (kurulum programı `ROOT/veri-klasoru.txt` yazar ya da
  `STUDIOFLOW_VERI` verilir): projeler, kayıtlar ve ayarlar seçilen veri klasöründe
  (varsayılan `Belgeler\\StudioFlow`); önbellek ve günlükler `%LOCALAPPDATA%\\StudioFlow`
  altında. Program klasörü yalnızca kodu taşır; güncelleme/kaldırma veriye dokunmaz.
* **Geliştirme** (dosya yok): eskisi gibi `ROOT/projects`, `ROOT/outputs`, `ROOT/.cache`
  ve `C:\\Canlandir`.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
LOGO_PNG = ROOT / "StudioFlow_logo.png"
LOGO_ICO = ROOT / "StudioFlow_logo.ico"

# Kurulumda kod `{program}\uygulama` içindedir; ffmpeg `{program}\ffmpeg` içinde gelir.
# GitHub'dan indirilen sürümde `Baslat.bat` ffmpeg'i kodun yanındaki `ffmpeg/` klasörüne
# indirir (bkz. `sunucu.ffmpeg_indir`).
KURULUM_DOSYASI = ROOT / "veri-klasoru.txt"
FFMPEG_KLASORU = ROOT.parent / "ffmpeg"
FFMPEG_KLASORLERI = (ROOT / "ffmpeg", FFMPEG_KLASORU)


def _veri_klasoru():
    """Kurulu uygulamanın veri klasörü; geliştirme kipinde None."""
    deger = os.environ.get("STUDIOFLOW_VERI", "").strip()
    if not deger:
        try:
            deger = KURULUM_DOSYASI.read_text(encoding="utf-8-sig").strip()
        except OSError:
            deger = ""
    return Path(os.path.expandvars(deger)).expanduser() if deger else None


VERI = _veri_klasoru()
KURULU = VERI is not None

if KURULU:
    YEREL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "StudioFlow"
    PROJELER = VERI / "Projeler"
    OUTPUTS = VERI / "Kayitlar"
    AYAR_KLASORU = VERI / "Ayarlar"
    ONBELLEK = YEREL / "Onbellek"
    GUNLUK = YEREL / "Gunlukler" / "studioflow.txt"
    for _klasor in (PROJELER, OUTPUTS, AYAR_KLASORU, ONBELLEK, GUNLUK.parent):
        _klasor.mkdir(parents=True, exist_ok=True)
else:
    YEREL = ROOT
    PROJELER = ROOT / "projects"
    OUTPUTS = ROOT / "outputs"
    ONBELLEK = ROOT / ".cache"
    GUNLUK = ROOT / "baslatma-gunlugu.txt"
    # API hesapları ve genel proje ayarları proje klasörünün **dışında**, bu bilgisayara
    # özel durur: proje kopyalansa/paylaşılsa anahtarlar birlikte gitmez.
    AYAR_KLASORU = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Canlandir"

GECICI = ONBELLEK / "studioflow"        # araç sekmelerinin kaydedilmemiş çıktıları
GRADIO_GECICI = ONBELLEK / "gradio"     # Gradio'nun yükleme/önizleme dosyaları


def ortam_degiskenlerini_kur():
    """Hugging Face / Gradio ortam değişkenleri: **`import gradio`'dan önce** çağrılmalı.

    `GRADIO_TEMP_DIR` Gradio içe aktarılırken okunur; sonradan değiştirmek işe yaramaz.
    Bu modül içe aktarılır aktarılmaz çağrılır; çekirdek her şeyden önce yüklendiği
    için sıra kendiliğinden doğru olur.
    """
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("GRADIO_TEMP_DIR", str(GRADIO_GECICI))
    # Kurulumla gelen ya da Baslat.bat'ın indirdiği ffmpeg/ffprobe önce bulunsun (başka
    # bilgisayarda PATH'te ffmpeg yoktur).
    klasor = next((k for k in FFMPEG_KLASORLERI if (k / "ffmpeg.exe").is_file()), None)
    if klasor is not None:
        yol = os.environ.get("PATH", "")
        if str(klasor) not in yol.split(os.pathsep):
            os.environ["PATH"] = str(klasor) + os.pathsep + yol


ortam_degiskenlerini_kur()
