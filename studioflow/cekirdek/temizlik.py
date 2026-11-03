"""Açılışta eski geçici dosyaları temizler; `.cache` kendiliğinden şişmesin.

Yalnızca **geçici** klasörlere dokunulur: Gradio'nun yükleme/önizleme kopyaları, araç
sekmelerinin kaydedilmemiş çıktıları, video üretiminin ara klasörleri ve projelerin
yarıda kalmış `.calisma` klasörleri. `projects/` içindeki gerçek proje dosyaları,
`outputs/` ve ayarlar asla silinmez.

Bir dosya ancak belirlenen süreden **daha eskiyse** silinir; yeni üretilmiş ya da
açık sayfada gösterilen dosyalar yerinde kalır. Boşalan alt klasörler de kaldırılır.
"""
import threading
import time
from pathlib import Path

from studioflow.cekirdek.yollar import GECICI, GRADIO_GECICI, ONBELLEK, PROJELER

GUN = 24 * 60 * 60
# Gradio kopyaları yalnızca sayfa açıkken gerekir; araç çıktıları indirilmek üzere bir
# hafta bekler (kullanıcı indirmediyse sonra gider).
GRADIO_OMRU = 1 * GUN
ARAC_OMRU = 7 * GUN
ARA_KLASOR_OMRU = 1 * GUN      # `.cache/<iş kimliği>` ve projelerin `.calisma` klasörleri
CALISMA_KLASORU = ".calisma"   # `proje.depo.CALISMA_KLASORU` ile aynı (çekirdek projeyi içe aktarmaz)


def _eski_dosyalari_sil(kok, omur, simdi):
    """`kok` altında `omur` saniyeden eski dosyaları sil, boşalan alt klasörleri kaldır.

    Dönüş: silinen dosya sayısı. Kök klasörün kendisi silinmez.
    """
    kok = Path(kok)
    if not kok.is_dir():
        return 0
    silinen = 0
    for yol in kok.rglob("*"):
        try:
            if not yol.is_file():
                continue
            if simdi - yol.stat().st_mtime > omur:
                yol.unlink()
                silinen += 1
        except OSError:
            continue
    # En derindekiler önce: boşalan klasör ancak içi boşaldıktan sonra kaldırılabilir.
    for yol in sorted((y for y in kok.rglob("*") if y.is_dir()),
                      key=lambda y: len(y.parts), reverse=True):
        try:
            yol.rmdir()
        except OSError:
            pass
    return silinen


def _ara_klasorler():
    """`.cache` altındaki ara klasörler: video üretiminin iş kimlikli klasörleri."""
    try:
        return [yol for yol in ONBELLEK.iterdir()
                if yol.is_dir() and yol not in (GECICI, GRADIO_GECICI)]
    except OSError:
        return []


def _calisma_klasorleri():
    """Projelerin yarıda kalmış (uygulama kapanırken silinememiş) `.calisma` klasörleri."""
    try:
        return [yol / CALISMA_KLASORU for yol in PROJELER.iterdir()
                if (yol / CALISMA_KLASORU).is_dir()]
    except OSError:
        return []


def gradio_onbellegini_temizle(simdi=None):
    """Gradio önbelleğinde süresi dolmuş dosyaları sil. Dönüş: silinen dosya sayısı.

    Arayüz **kurulmadan önce** çağrılmalı (bkz. `app.py`): Gradio kurulumda örnek
    dosyaları (ör. `assets/ornek.jpg`) önbelleğe kopyalar, kopya zaten varsa yeniden
    kopyalamaz. Önceki açılışta oluşmuş kopya kurulumdan sonra silinirse sayfa onu
    istediğinde 403 alıyordu; önce silinirse Gradio kurulumda yeniden kopyalar.
    """
    simdi = time.time() if simdi is None else simdi
    return _eski_dosyalari_sil(GRADIO_GECICI, GRADIO_OMRU, simdi)


def eski_gecicileri_temizle(simdi=None, gradio=True):
    """Bütün geçici klasörlerde süresi dolmuş dosyaları sil. Dönüş: silinen dosya sayısı.

    `gradio=False`: Gradio önbelleği atlanır (arayüz kurulduktan sonra çalışan açılış
    temizliği; o klasör kurulumdan önce `gradio_onbellegini_temizle` ile temizlenir).
    """
    simdi = time.time() if simdi is None else simdi
    silinen = gradio_onbellegini_temizle(simdi) if gradio else 0
    silinen += _eski_dosyalari_sil(GECICI, ARAC_OMRU, simdi)
    for klasor in _ara_klasorler() + _calisma_klasorleri():
        silinen += _eski_dosyalari_sil(klasor, ARA_KLASOR_OMRU, simdi)
        try:
            klasor.rmdir()      # tamamen boşaldıysa klasörün kendisi de gider
        except OSError:
            pass
    return silinen


def arka_planda_temizle(gradio=True):
    """Temizliği ayrı iş parçacığında başlat: açılışı yavaşlatmaz, hata uygulamayı durdurmaz."""
    def calis():
        try:
            silinen = eski_gecicileri_temizle(gradio=gradio)
            if silinen:
                print(f"Geçici dosya temizliği: {silinen} eski dosya silindi.")
        except Exception as hata:  # temizlik hiçbir zaman uygulamayı bozmamalı
            print(f"Geçici dosya temizliği atlandı: {hata}")
    threading.Thread(target=calis, name="gecici-temizlik", daemon=True).start()


__all__ = ["eski_gecicileri_temizle", "gradio_onbellegini_temizle", "arka_planda_temizle"]
