"""Yollar ve StudioFlow bağlantısı.

Editör StudioFlow'un kodunu kopyalamaz: `studioflow` paketini ve `projects/` klasörünü
doğrudan kullanır. StudioFlow klasörü varsayılan olarak bu klasörün yanındadır
(`Desktop/StudioFlow`); başka yerdeyse `STUDIOFLOW_KOK` ortam değişkeniyle verilir.
"""
import os
import sys
from pathlib import Path

EDITOR_KOK = Path(__file__).resolve().parents[1]
WEB = EDITOR_KOK / "web"
# Kurulu uygulamada `studioflow` paketi aynı klasördedir (`{program}\uygulama`); geliştirmede
# yandaki StudioFlow klasöründedir.
STUDIOFLOW_KOK = Path(os.environ.get("STUDIOFLOW_KOK")
                      or (EDITOR_KOK if (EDITOR_KOK / "studioflow" / "__init__.py").is_file()
                          else EDITOR_KOK.parent / "StudioFlow")).resolve()

# Yalnızca bu bilgisayardan erişilir; StudioFlow 7860'ı kullanır, editör yanında çalışır.
ADRES = "127.0.0.1"
PORT = int(os.environ.get("STUDIOFLOW_EDITOR_PORT") or 7870)


def studioflow_bagla():
    """`studioflow` paketini içe aktarılabilir yap; StudioFlow bulunamazsa açık hata ver."""
    if not (STUDIOFLOW_KOK / "studioflow" / "__init__.py").is_file():
        raise RuntimeError(
            f"StudioFlow bulunamadı: {STUDIOFLOW_KOK}. Klasör başka yerdeyse "
            "STUDIOFLOW_KOK ortam değişkenine yolunu yaz.")
    if str(STUDIOFLOW_KOK) not in sys.path:
        sys.path.insert(0, str(STUDIOFLOW_KOK))


studioflow_bagla()

# ── Veri ve önbellek yerleri (StudioFlow'un kipine uyar: bkz. `studioflow.cekirdek.yollar`)
from studioflow.cekirdek import yollar  # noqa: E402  (studioflow_bagla'dan sonra)

# Kullanıcı verisi: taslaklar ve yüklenen dosyalar (kurulu: `<veri>\Taslaklar`, `<veri>\Yuklenenler`).
TASLAKLAR = yollar.VERI / "Taslaklar" if yollar.KURULU else EDITOR_KOK / "taslaklar"
YUKLENENLER = yollar.VERI / "Yuklenenler" if yollar.KURULU else EDITOR_KOK / "dosyalar"
# Yeniden üretilebilenler: geçici önizlemeler, WebView belleği, günlük.
GECICI = yollar.ONBELLEK / "pencere" if yollar.KURULU else EDITOR_KOK / ".gecici"
WEBVIEW = yollar.YEREL / "WebView" if yollar.KURULU else EDITOR_KOK / ".uygulama-verisi"
GUNLUK = yollar.GUNLUK if yollar.KURULU else EDITOR_KOK / "baslatma-gunlugu.txt"
