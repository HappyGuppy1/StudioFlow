"""ffmpeg / ffprobe erişimi tek sınıfta: araç bulma, çalıştırma, süre ve ölçü okuma."""
import shutil
import subprocess
from pathlib import Path

from studioflow.cekirdek.metin import ilk_satir, sayi


class FFmpeg:
    """Kurulu ffmpeg'i sarmalar; araç yoksa yöntemler sessizce boş/0 döner."""

    def ffmpeg(self):
        """ffmpeg yolu; kurulu değilse None."""
        return shutil.which("ffmpeg")

    def ffprobe(self):
        """ffprobe yolu: önce ffmpeg'in yanındaki, sonra PATH'teki; yoksa None."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            yanindaki = Path(ffmpeg).with_name("ffprobe" + (Path(ffmpeg).suffix or ""))
            if yanindaki.exists():
                return str(yanindaki)
        return shutil.which("ffprobe")

    def calistir(self, komut, cwd=None):
        """ffmpeg komutunu çalıştır; `(başarılı mı, hata metni)` döndür."""
        try:
            sonuc = subprocess.run(
                komut, capture_output=True, text=True, timeout=3600,
                cwd=str(cwd) if cwd else None,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as hata:
            return False, "ffmpeg çalıştırılamadı: " + ilk_satir(hata, 200)
        if sonuc.returncode == 0:
            return True, ""
        return False, ilk_satir(sonuc.stderr or sonuc.stdout, 300)

    def sessiz_kopyala(self, kaynak, hedef):
        """Videoyu ses izi olmadan kopyala (görüntü yeniden kodlanmaz).

        Video servisleri (LTX-2.3, Agnes 2.5 Flash) kendi ürettikleri bir ses izini (müzik)
        klibe ekliyor; sahne klipleri atölyede tek tek oynatıldığı için kayıtta silinir.
        ffmpeg yoksa ya da başarısızsa klip olduğu gibi kopyalanır: birleştirme sesi
        zaten atar (`-an`).
        """
        ffmpeg = self.ffmpeg()
        if ffmpeg:
            ok, _hata = self.calistir([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                                       "-i", str(kaynak), "-map", "0:v:0", "-c:v", "copy",
                                       "-an", str(hedef)])
            if ok and Path(hedef).is_file() and Path(hedef).stat().st_size > 0:
                return
        shutil.copy2(kaynak, hedef)

    def probe(self, secenekler, yol):
        """ffprobe'u çalıştır ve çıktısını döndür (araç yoksa/okunamazsa boş metin)."""
        ffprobe = self.ffprobe()
        if not ffprobe:
            return ""
        try:
            sonuc = subprocess.run(
                [ffprobe, "-v", "error", *secenekler, str(yol)],
                capture_output=True, text=True, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            return ""
        return sonuc.stdout if sonuc.returncode == 0 else ""

    def medya_suresi(self, yol):
        """Ses/video dosyasının saniye cinsinden süresi; okunamazsa 0,0 döner.

        Müzik eklemede kırpma sınırları, "müzik videodan kısa mı" kararı ve karışımın
        video sonunda kesilmesi bu değere dayanır; bu yüzden önce dosyanın toplam süresi,
        olmazsa ses akışının süresi okunur.
        """
        metin = self.probe(["-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1"], yol).strip()
        sure = sayi(metin.splitlines()[0] if metin else "", 0.0, float)
        if sure > 0:
            return sure
        metin = self.probe(["-select_streams", "a:0", "-show_entries",
                            "stream=duration", "-of", "default=nw=1:nk=1"], yol).strip()
        return max(0.0, sayi(metin.splitlines()[0] if metin else "", 0.0, float))

    def video_olcusu(self, yol):
        """Videonun `(genişlik, yükseklik)` ölçüsü; okunamazsa `(0, 0)`.

        ffprobe yoksa sessizce başarısız olur; çağıran varsayılana düşer.
        """
        try:
            genislik, _, yukseklik = self.probe(
                ["-select_streams", "v:0", "-show_entries", "stream=width,height",
                 "-of", "csv=p=0:s=x"], yol).strip().splitlines()[0].partition("x")
            return int(genislik), int(yukseklik)
        except Exception:
            return 0, 0


VARSAYILAN = FFmpeg()
