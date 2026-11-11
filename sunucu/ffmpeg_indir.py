"""`python -m sunucu.ffmpeg_indir`: ffmpeg yoksa kodun yanındaki `ffmpeg/` klasörüne indirir.

GitHub'dan indirilen StudioFlow ffmpeg getirmez (kurulum programı getirir). `Baslat.bat`
ffmpeg'i PATH'te ya da `ffmpeg/` klasöründe bulamazsa bunu bir kez çalıştırır. Paket
gyan.dev'in Windows "essentials" derlemesidir; SHA-256 özeti doğrulanır, zip'ten yalnızca
`ffmpeg.exe` ve `ffprobe.exe` çıkarılır. `studioflow.cekirdek.yollar` bu klasörü PATH'in
başına ekler. Yalnızca standart kitaplık kullanılır.
"""
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PAKET = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
OZET = PAKET + ".sha256"
HEDEF = Path(__file__).resolve().parents[1] / "ffmpeg"
ARACLAR = ("ffmpeg.exe", "ffprobe.exe")
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


if __name__ == "__main__":
    try:
        indir()
    except Exception as hata:  # Baslat.bat uyarı yazıp StudioFlow'u yine açar
        print(f"  ffmpeg indirilemedi: {hata}", file=sys.stderr)
        sys.exit(1)
