"""`python -m sunucu.ffmpeg_indir`: ffmpeg yoksa kodun yanındaki `ffmpeg/` klasörüne indirir.

GitHub'dan indirilen StudioFlow ffmpeg getirmez (kurulum programı getirir). `Baslat.bat`
ffmpeg'i PATH'te ya da `ffmpeg/` klasöründe bulamazsa bunu bir kez çalıştırır; uygulama
nasıl açılırsa açılsın (kısayol, `python -m sunucu`) açılışta `arka_planda_hazirla` da
aynı işi yapar (bkz. `hazirla`). Paket
gyan.dev'in Windows "essentials" derlemesidir; SHA-256 özeti doğrulanır, zip'ten yalnızca
`ffmpeg.exe` ve `ffprobe.exe` çıkarılır. `studioflow.cekirdek.yollar` bu klasörü PATH'in
başına ekler. Yalnızca standart kitaplık kullanılır.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

PAKET = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
OZET = PAKET + ".sha256"
HEDEF = Path(__file__).resolve().parents[1] / "ffmpeg"
# Kod yazılamayan bir klasördeyse (ör. Program Files) kullanıcının yerel klasörü kullanılır;
# `studioflow.cekirdek.yollar.FFMPEG_KLASORLERI` bu klasörü de tanır.
YEDEK_HEDEF = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "StudioFlow" / "ffmpeg"
ARACLAR = ("ffmpeg.exe", "ffprobe.exe")
WINDOWS = sys.platform == "win32"
BASLIK = {"User-Agent": "StudioFlow-ffmpeg-indirici"}


def _ac(adres):
    return urllib.request.urlopen(urllib.request.Request(adres, headers=BASLIK), timeout=60)


def indir(hedef=HEDEF):
    """ffmpeg ve ffprobe'u `hedef` klasörüne kur; zaten varsa hiçbir şey yapmaz."""
    if all((hedef / arac).is_file() for arac in ARACLAR):
        print(f"  ffmpeg zaten kurulu: {hedef}")
        return hedef
    with _ac(OZET) as yanit:
        beklenen = yanit.read().decode("ascii", "replace").split()[0].strip().lower()
    with tempfile.TemporaryDirectory(prefix="sf-ffmpeg-") as gecici:
        zip_yolu = Path(gecici) / "ffmpeg.zip"
        ozet = hashlib.sha256()
        with _ac(PAKET) as yanit, open(zip_yolu, "wb") as dosya:
            toplam = int(yanit.headers.get("Content-Length") or 0)
            inen, son = 0, -1
            while parca := yanit.read(1 << 20):
                dosya.write(parca)
                ozet.update(parca)
                inen += len(parca)
                yuzde = inen * 100 // toplam if toplam else -1
                if yuzde != son and yuzde % 10 == 0:
                    print(f"  ffmpeg indiriliyor: %{yuzde} ({inen >> 20} MB)", flush=True)
                    son = yuzde
        if ozet.hexdigest() != beklenen:
            raise RuntimeError("İndirilen ffmpeg paketinin SHA-256 özeti tutmadı; dosya bozuk "
                               "ya da değiştirilmiş. Baslat.bat'ı yeniden çalıştırarak tekrar dene.")
        hazirlik = Path(gecici) / "ffmpeg"
        hazirlik.mkdir()
        with zipfile.ZipFile(zip_yolu) as arsiv:
            for arac in ARACLAR:
                uye = next((ad for ad in arsiv.namelist() if ad.endswith("/bin/" + arac)), None)
                if uye is None:
                    raise RuntimeError(f"ffmpeg paketinde {arac} bulunamadı.")
                with arsiv.open(uye) as kaynak, open(hazirlik / arac, "wb") as cikti:
                    shutil.copyfileobj(kaynak, cikti)
        hedef.mkdir(parents=True, exist_ok=True)
        for arac in ARACLAR:
            shutil.move(str(hazirlik / arac), str(hedef / arac))
    print(f"  ffmpeg kuruldu: {hedef}")
    return hedef


_KILIT = threading.Lock()


def _yazilabilir(klasor):
    try:
        klasor.mkdir(parents=True, exist_ok=True)
        deneme = klasor / ".yazma-denemesi"
        deneme.write_bytes(b"")
        deneme.unlink()
        return True
    except OSError:
        return False


def hazirla():
    """ffmpeg PATH'te yoksa indir ve PATH'e ekle; ffmpeg'in yolunu döndür.

    `Baslat.bat` ffmpeg'i yalnızca kendisiyle açılınca indirir; masaüstü kısayolu
    (`Baslat.vbs`, pythonw) ya da `python -m sunucu` ile açılan uygulama indirmeyi hiç
    yapmıyordu (12.11.2026: güncel kurulumda dışa aktarma "ffmpeg bulunamadı" ile durdu).
    Uygulama açılışta bunu arka planda çağırır; dışa aktarma da ffmpeg'i bulamazsa çağırıp
    süren indirmenin bitmesini bekler. Hata olursa `RuntimeError` yükselir.
    """
    with _KILIT:
        yol = shutil.which("ffmpeg")
        if yol:
            return yol
        if not WINDOWS:
            raise RuntimeError("ffmpeg bulunamadı; bu sistemde paket yöneticisiyle kur "
                               "(otomatik indirme yalnızca Windows'ta).")
        hedef = next((k for k in (HEDEF, YEDEK_HEDEF) if _yazilabilir(k)), None)
        if hedef is None:
            raise RuntimeError(f"ffmpeg indirilemedi: {HEDEF} ve {YEDEK_HEDEF} klasörlerine "
                               "yazılamıyor.")
        try:
            indir(hedef)
        except Exception as hata:
            raise RuntimeError(f"ffmpeg indirilemedi: {hata}") from hata
        os.environ["PATH"] = str(hedef) + os.pathsep + os.environ.get("PATH", "")
        yol = shutil.which("ffmpeg")
        if not yol:
            raise RuntimeError(f"ffmpeg indirildi ama bulunamadı: {hedef}")
        return yol


def arka_planda_hazirla():
    """Açılışta ffmpeg'i arka planda hazırla; pencerenin açılmasını bekletmez."""
    def calis():
        try:
            hazirla()
        except Exception as hata:  # uygulama ffmpeg'siz de açılır; dışa aktarma yeniden dener
            print(f"  {hata}", file=sys.stderr)

    threading.Thread(target=calis, name="ffmpeg-hazirla", daemon=True).start()


if __name__ == "__main__":
    try:
        indir()
    except Exception as hata:  # Baslat.bat uyarı yazıp StudioFlow'u yine açar
        print(f"  ffmpeg indirilemedi: {hata}", file=sys.stderr)
        sys.exit(1)
