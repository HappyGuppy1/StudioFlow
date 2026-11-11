"""Proje klasörleri: ad → klasör, listeleme, adım dosya adları, güvenli klasör kontrolü."""
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import soundfile as sf

from studioflow.ayarlar.bicimler import YASAK_ADLAR
from studioflow.cekirdek.yollar import PROJELER
from studioflow.proje.sabitler import ADIM_SANIYE, SAHNE_TAVAN_ARALIGI
from studioflow.saglayicilar import gorsel_cloudflare


def slug(ad):
    """Proje adını klasör adına çevir: geçersiz karakterler atılır, boşluk `-` olur."""
    temiz = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (ad or "").strip())
    temiz = re.sub(r"\s+", "-", temiz).strip(".-")[:60].strip(".-")
    if temiz.upper() in YASAK_ADLAR:
        temiz += "-proje"
    return temiz or "proje"


def kayit_adi(deger, ek="kayit"):
    """Kullanıcının yazdığı kayıt adını dosya adına çevir (müzik, dublaj, altyazı).

    `slug` ile aynı kuralı uygular ama **boş ad üretebilir**: proje adı boş kalamaz,
    kayıt adı kalabilir. Boş dönende çağıran kendi varsayılanını koyar (müzikte
    yüklenen dosyanın adı, dublaj ve altyazıda dil kodu).
    """
    temiz = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(deger or "").strip())
    temiz = re.sub(r"\s+", "-", temiz).strip(".-")[:60].strip(".-")
    if temiz.upper() in YASAK_ADLAR:
        temiz += "-" + ek
    return temiz


def proje_klasoru(ad):
    """Projenin klasörünü döndür (oluşturmaz)."""
    return PROJELER / slug(ad)


def klasoru_hazirla():
    """`projects` klasörünü oluştur (yoksa) ve yolunu döndür."""
    try:
        PROJELER.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return PROJELER


def liste():
    """`projects` altındaki projeleri en son değiştirilen önce olacak şekilde listele.

    Silinirken kilitli dosya yüzünden yarım kalan klasörler (`zorla_sil`) listelenmez;
    her listelemede yeniden silinmeye çalışılır.
    """
    klasoru_hazirla()
    try:
        klasorler = [yol for yol in PROJELER.iterdir() if yol.is_dir()]
    except OSError:
        return []
    artiklar = [yol for yol in klasorler if _silinecek_mi(yol)]
    for yol in artiklar:
        _artigi_temizle(yol)
    klasorler = [yol for yol in klasorler if yol not in artiklar]
    klasorler.sort(key=lambda yol: yol.stat().st_mtime, reverse=True)
    return [yol.name for yol in klasorler]


# ── Zorla silme ─────────────────────────────────────────────────────────────────
# Silme hiçbir durumda reddedilmez. Windows'ta açık kalan bir dosya (ör. hâlâ süren bir
# ffmpeg) `rmtree`'yi yarıda keser; klasör o zaman `.silinecek-…` adıyla kenara alınır ya
# da içine `SILINECEK` işareti konur: listeden düşer ve sonraki listelemelerde silinir.
SILINECEK = ".silinecek"
# Silinirken işi süren projeler: iş bittiğinde klasörü yeniden yazmışsa yine silinir
# (bkz. `silineni_temizle`).
SILINENLER = set()


def _silinecek_mi(yol):
    return yol.name.startswith(SILINECEK) or (yol / SILINECEK).exists()


def _salt_okunuru_ac(islev, yol, _hata):
    """`rmtree` hata kancası: salt okunur dosyayı yazılabilir yapıp bir kez daha dene."""
    try:
        os.chmod(yol, stat.S_IWRITE)
        islev(yol)
    except OSError:
        pass


def _rmtree(yol):
    if sys.version_info >= (3, 12):
        shutil.rmtree(yol, onexc=_salt_okunuru_ac)
    else:
        shutil.rmtree(yol, onerror=_salt_okunuru_ac)


def _ffmpeg_sureclerini_kapat(klasor):
    """Klasördeki dosyalarla çalışan ffmpeg/ffprobe süreçlerini kapat (yalnızca Windows)."""
    if os.name != "nt":
        return
    komut = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe' or Name='ffprobe.exe'\" | "
             "Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($env:SF_SILINEN_KLASOR, "
             "[StringComparison]::OrdinalIgnoreCase) -ge 0 } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", komut],
                       capture_output=True, timeout=30,
                       env={**os.environ, "SF_SILINEN_KLASOR": str(klasor)},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def zorla_sil(klasor, deneme=5):
    """Klasörü ne olursa olsun kaldır; tamamen silindiyse True.

    Salt okunur dosyalar yazılabilir yapılır; kilitli dosya kalırsa klasördeki ffmpeg
    süreçleri kapatılıp birkaç saniye yeniden denenir. Yine de kalan dosya varsa klasör
    listeden düşürülür (`SILINECEK`) ve sonraki listelemelerde silinir.
    """
    klasor = Path(klasor)
    for sira in range(deneme):
        if not klasor.exists():
            return True
        _rmtree(klasor)
        if not klasor.exists():
            return True
        if sira == 0:
            _ffmpeg_sureclerini_kapat(klasor)
        time.sleep(0.5 + 0.25 * sira)
    try:
        klasor.rename(klasor.with_name(f"{SILINECEK}-{klasor.name}-{int(time.time())}"))
    except OSError:
        try:
            (klasor / SILINECEK).touch()
        except OSError:
            pass
    return False


def _artigi_temizle(yol):
    _rmtree(yol)
    if yol.exists() and not yol.name.startswith(SILINECEK):
        try:
            (yol / SILINECEK).touch()
        except OSError:
            pass


def silineni_temizle(ad):
    """Silinirken çalışan iş bitti: klasörü yeniden yazdıysa onu da kaldır."""
    ad_slug = slug(ad)
    if ad_slug in SILINENLER:
        SILINENLER.discard(ad_slug)
        if proje_klasoru(ad_slug).exists():
            zorla_sil(proje_klasoru(ad_slug))


def gorsel_adim_sinirlari(model):
    """Görsel üretiminde adım sayısının **gerçek** aralığı: `(en az, en çok, varsayılan)`.

    Modelin kendi sınırı geçerlidir (FLUX 1–8, SDXL 1–20, Lucid 1–40).
    """
    return gorsel_cloudflare.cf_steps_range(model or "")


def proje_adim_saniyesi(veri):
    """Projenin **üst sınır** adım süresi (saniye): `video.adim_saniye`, yoksa varsayılan.

    Sahne süreleri artık anlatımın içeriğine göre **adım başına değişir**; bu değer bir
    sahnenin alabileceği en uzun süredir (kaydırıcı) ve yalnızca eski/süresiz adımlar için
    varsayılan olarak kullanılır. Gerçek süre `adim_suresi` ile adımın `start`/`end`
    aralığından okunur. Eski projelerde satır olmadığı için varsayılana düşer.

    Değer `SAHNE_TAVAN_ARALIGI` aralığına **kırpılır**: bu sayı aynı zamanda sahne
    planı istenirken yapay zekâya verilen tavandır, dolayısıyla aralık dışında
    kaydedilmiş bir ayar burada da geçerli olmamalıdır.
    """
    ham = ((veri.get("ayarlar") or {}).get("video") or {}).get("adim_saniye")
    alt, ust = SAHNE_TAVAN_ARALIGI
    return max(alt, min(ust, float(ham or ADIM_SANIYE)))


def adim_suresi(adim, varsayilan=None):
    """Bir adımın kendi süresi (saniye): `end - start`, okunamazsa `varsayilan`.

    Sahne süreleri adım başına değiştiği için video üretimi, tuval kurpması ve birleştirme
    hep bu değeri kullanır; `start`/`end` yazılmamış (bozuk/eski) bir adımda üst sınır
    değerine düşülür.
    """
    try:
        sure = float(adim.get("end")) - float(adim.get("start"))
    except (TypeError, ValueError, AttributeError):
        sure = 0.0
    if sure > 0:
        return round(sure, 3)
    return round(float(varsayilan if varsayilan is not None else ADIM_SANIYE), 3)


def dosya_kopyala(kaynak, hedef):
    """Üretilen dosyayı proje klasörüne kopyala (aynı dosyaysa dokunma)."""
    kaynak, hedef = Path(kaynak), Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    if kaynak.resolve() != hedef.resolve():
        shutil.copy2(kaynak, hedef)
    return hedef


# Proje üretimi ara dosyalarını (aday kareler, ses parçaları, indirilen videolar)
# `.cache` ya da `outputs` yerine projenin **kendi** klasöründe tutar; son dosyalar buradan
# projeye kopyalanır, kalanlar iş bitince `calismayi_temizle` ile silinir.
CALISMA_KLASORU = ".calisma"


def calisma_klasoru(veri, ad):
    """Projenin çalışma alt klasörü `<proje>/.calisma/<ad>` (oluşturmaz; yazan oluşturur).

    Projesi belli olmayan veride `None` döner: sağlayıcı kendi varsayılan klasörüne yazar.
    """
    proje = (veri or {}).get("slug")
    return proje_klasoru(proje) / CALISMA_KLASORU / ad if proje else None


def calismayi_temizle(klasor, *adlar):
    """Projenin çalışma alt klasörlerini sil; `.calisma` boş kalırsa onu da kaldır."""
    kok = Path(klasor) / CALISMA_KLASORU
    for ad in adlar:
        shutil.rmtree(kok / ad, ignore_errors=True)
    try:
        kok.rmdir()
    except OSError:
        pass


def dosya_suresi(yol):
    try:
        return float(sf.info(yol).duration)
    except Exception:
        return 0.0


def adim_dosya_adi(adim, uzanti):
    """Bir adımın proje içindeki dosya yolu: `gorseller/adim-03.png`."""
    return f"{'videolar' if uzanti == '.mp4' else 'gorseller'}/adim-{adim['index']:02d}{uzanti}"


def adim_tamam(klasor, adim):
    """Adım gerçekten bitti mi? Metin TAMAM dese de dosya diskte olmalı."""
    if adim.get("durum") != "TAMAM":
        return False
    return all(adim.get(alan) and (klasor / adim[alan]).exists() for alan in ("gorsel", "video"))


def proje_dosyalari(klasor):
    # `proje.txt` listede yok: Gradio her ilerleme paketinde listedeki dosyaları açıp
    # özetler; çoklu üretimde iş parçacıkları proje.txt'yi sürekli yerine koyduğu için
    # Windows o an okumayı "Permission denied" ile reddeder ve tüm akış "Hata"yla düşer
    # (14.10.2026). Kaydın içeriği zaten "proje.txt" kutusunda görünür.
    try:
        return sorted(str(yol) for yol in klasor.rglob("*")
                      if yol.is_file() and yol.suffix != ".gecici" and yol.name != "proje.txt"
                      and CALISMA_KLASORU not in yol.relative_to(klasor).parts)
    except OSError:
        return []


def _dogal_sira(yol):
    """Ad içindeki sayıları sayı olarak sırala: `adim-9` → `adim-10` → `adim-100`."""
    return [int(parca) if parca.isdigit() else parca.lower()
            for parca in re.split(r"(\d+)", Path(yol).name)]


def proje_gorselleri(klasor):
    # Düz metin sıralaması `adim-10`u `adim-9`un, `adim-100`ü `adim-11`in önüne
    # koyardı; yeni kareler galerinin ortasına dağılır, sonda hep `adim-99` kalırdı.
    try:
        return sorted((str(yol) for yol in (klasor / "gorseller").iterdir()
                       if yol.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")),
                      key=_dogal_sira)
    except OSError:
        return []


def guvenli_klasor(ad):
    """Yalnızca `projects` içindeki gerçek bir proje klasörünü döndür, yoksa None.

    `slug()` yoldan ayıraçları temizler; yine de yolun `projects` dışına çıkamadığı
    burada bir kez daha doğrulanır.
    """
    ad = (ad or "").strip()
    if not ad:
        return None
    klasor = proje_klasoru(ad)
    try:
        kok = PROJELER.resolve()
        hedef = klasor.resolve()
        hedef.relative_to(kok)
    except (OSError, ValueError):
        return None
    return klasor if hedef != kok and klasor.is_dir() else None
