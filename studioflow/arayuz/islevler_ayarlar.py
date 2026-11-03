"""Üst çubuk ve sağ ayar çekmecesi — geri çağrı işlevleri."""
import os
import subprocess
import threading

from studioflow.cekirdek import depolama


def kayit_tercihi(acik):
    """Otomatik kaydetme tercihini uygula ve durum metnini döndür."""
    depolama.VARSAYILAN.otomatik(acik)
    return depolama.VARSAYILAN.durum_metni()


def shutdown():
    """Kısayolla açılan uygulamada konsol yok; kapatmak için tek yol bu düğme."""
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return "Uygulama kapatılıyor. Bu sekmeyi kapatabilirsin. Tekrar açmak için masaüstündeki StudioFlow kısayolunu kullan."


def app_surecleri():
    """Bu bilgisayarda app.py çalıştıran python süreçlerinin kimliklerini döndür.

    Aynı uygulamanın arka planda kalmış kopyalarını bulmak için kullanılır.
    Yalnızca okuma yapar; hiçbir süreci kapatmaz.
    """
    komut = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
             "Where-Object { $_.CommandLine -like '*app.py*' } | "
             "ForEach-Object { $_.ProcessId }")
    sonuc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", komut],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [int(satir) for satir in sonuc.stdout.split() if satir.strip().isdigit()]


def close_servers():
    """Açık kalan tüm StudioFlow sunucularını kapat: arka plan kopyaları ve bu oturum.

    Kendi sürecini de kapatır, çünkü "tüm sunucular" isteği bunu gerektirir. Cevap
    tarayıcıya ulaşsın diye kapanış kısa bir gecikmeyle yapılır.
    """
    try:
        kimlikler = app_surecleri()
    except Exception as exc:
        return "Sunucular listelenemedi: " + str(exc)[:200]
    benim = os.getpid()
    kapatilan = 0
    for kimlik in kimlikler:
        if kimlik == benim:
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(kimlik), "/T", "/F"], capture_output=True,
                           timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            kapatilan += 1
        except Exception:
            pass
    threading.Timer(1.5, lambda: os._exit(0)).start()
    return (f"{kapatilan + 1} sunucu kapatıldı: {kapatilan} arka plan kopyası ve bu pencere. "
            "Sekmeyi kapatabilirsin. Tekrar açmak için masaüstündeki StudioFlow kısayolunu kullan.")
