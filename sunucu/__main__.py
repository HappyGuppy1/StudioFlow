"""`python -m sunucu`: editörü kendi uygulama penceresinde açar.

`python -m sunucu --tarayici` eski yolla çalışır: sunucu 127.0.0.1:7870'te kalkar ve
tarayıcı açılır (pencere kitaplığı yoksa ya da hata ayıklarken).
"""
import sys
import threading
import time
import webbrowser

import uvicorn

from sunucu import ayar


def _gunluge_yonlendir():
    """Kısayol (`Baslat.vbs`) editörü pythonw ile konsolsuz açar; çıktı ve hatalar günlüğe yazılır.

    Konsol varsa (Baslat.bat) hiçbir şey değişmez. Günlük açılamazsa editör yine açılır.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        gunluk = ayar.GUNLUK
        gunluk.parent.mkdir(parents=True, exist_ok=True)
        if gunluk.exists() and gunluk.stat().st_size > 1_000_000:
            gunluk.unlink()
        sys.stdout = sys.stderr = open(gunluk, "a", encoding="utf-8", errors="replace",
                                       buffering=1)
        print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} StudioFlow başlatılıyor ---")
    except Exception:  # günlük açılamazsa editör yine de açılmalı
        pass


def main():
    _gunluge_yonlendir()
    # ffmpeg yalnızca Baslat.bat ile açılınca indiriliyordu; kısayolla açılınca da indirilsin.
    from studioflow.cekirdek import yollar  # noqa: F401  (indirilmiş ffmpeg'i PATH'e ekler)
    from sunucu import ffmpeg_indir
    ffmpeg_indir.arka_planda_hazirla()
    if "--tarayici" not in sys.argv:
        try:
            from sunucu import pencere
        except ImportError as exc:      # pywebview kurulu değil: tarayıcıyla açılır
            print(f"Uygulama penceresi açılamadı ({exc}); editör tarayıcıda açılıyor. "
                  "Kurmak için: requirements.txt")
        else:
            pencere.calistir()
            return
    from sunucu.uygulama import app  # günlükten sonra: açılış hataları da kaydedilir

    adres = f"http://{ayar.ADRES}:{ayar.PORT}/"
    print(f"StudioFlow · {adres} · StudioFlow: {ayar.STUDIOFLOW_KOK}")
    threading.Timer(1.2, lambda: webbrowser.open(adres)).start()
    uvicorn.run(app, host=ayar.ADRES, port=ayar.PORT, log_level="warning")


if __name__ == "__main__":
    main()
