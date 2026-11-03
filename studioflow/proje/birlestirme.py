"""Adım kliplerini tuvale oturtup tek `proje.mp4` hâline getirme."""
import shutil
import subprocess

from studioflow.ayarlar.bicimler import CIKTI_FPS, TUVAL_KLASORU, bicim_bilgisi, bicim_kunye
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.depo import adim_suresi
from studioflow.proje.dosya import gorsel_kaynak_bicim
from studioflow.proje.sabitler import ADIM_SANIYE


def adim_sifirla(klasor, adim):
    """Adımı baştan üretilecek hâle getir: eski kareyi, videoyu ve tuval klibini sil."""
    for klasor_adi in ("gorseller", "videolar"):
        yol = klasor / klasor_adi
        if not yol.is_dir():
            continue
        for eski in yol.glob(f"adim-{adim['index']:02d}.*"):
            try:
                eski.unlink()
            except OSError:
                pass
    # Tuval klipleri (`videolar/tuval/adim-01-1920x1080.mp4`) hedef biçime göre
    # üretilir; adım yeniden üretilince eski tuval klibi diskte kalmasın.
    for eski in (klasor / "videolar" / TUVAL_KLASORU).glob(f"adim-{adim['index']:02d}-*"):
        try:
            eski.unlink()
        except OSError:
            pass
    adim.update(gorsel="", video="", hata="", bitti="", durum="BEKLİYOR")
    # Eski karenin denetim kararı yeni kare için geçersizdir.
    adim.pop("denetim", None)
    adim.pop("kalite_durumu", None)
    adim.pop("hareket_izi", None)
    adim.pop("sureklilik_kare", None)
    adim.pop("sureklilik_izi", None)


def adim_videosunu_sifirla(klasor, adim):
    """Yalnızca adımın **klibini** sil (kare korunur): video baştan üretilecek.

    Adımın videosu ve tuval klibi diskten kaldırılır, kare ve denetim kararı
    olduğu gibi kalır. Adım `YARIM`a döner ("görsel var, video yok"), böylece akış
    görsel aşamasını atlar ve yalnızca bu adımın videosunu yeniden üretir.
    """
    for eski in (klasor / "videolar").glob(f"adim-{adim['index']:02d}.*"):
        try:
            eski.unlink()
        except OSError:
            pass
    for eski in (klasor / "videolar" / TUVAL_KLASORU).glob(f"adim-{adim['index']:02d}-*"):
        try:
            eski.unlink()
        except OSError:
            pass
    adim.update(video="", hata="", bitti="", durum="YARIM")


# Klip sahnesinden kısaysa en fazla bu kadar yavaşlatılır (bkz. `sure_doldurma`).
AZAMI_YAVASLATMA = 1.3


def sure_doldurma(klip_suresi, sahne_suresi):
    """Kısa klibi sahne süresine getiren süzgeçler: `(önce, sonra)`.

    20.10.2026 (Gambusia): LTX en fazla 8 sn üretir; 9,6 sn'lik sahnede son 1,6 sn son
    kare dondurulunca video "takıldı" gibi görünüyordu. Artık klip önce yavaşlatılır
    (`setpts`, en fazla `AZAMI_YAVASLATMA` kat; 8 → 9,6 sn = 1,2 kat, gözle fark edilmez),
    yalnızca bundan sonra kalan fark son kareyle (`tpad`) kapanır. `önce` ölçekten önce,
    `sonra` zincirin sonuna eklenir; süre `-t` ile kesilir.
    """
    try:
        klip_suresi, sahne_suresi = float(klip_suresi), float(sahne_suresi)
    except (TypeError, ValueError):
        return "", ""
    if klip_suresi <= 0 or sahne_suresi <= klip_suresi + 0.04:
        return "", ""
    kat = min(sahne_suresi / klip_suresi, AZAMI_YAVASLATMA)
    kalan = max(0.0, sahne_suresi - klip_suresi * kat)
    return f"setpts=PTS*{kat:.4f},", f",tpad=stop_mode=clone:stop_duration={kalan + 0.2:.3f}"


def klibi_sahneye_uzat(yol, sahne_suresi):
    """Klip sahnesinden kısaysa **dosyanın kendisini** sahne süresine uzat (yavaşlatarak).

    20.10.2026: kısa klip yalnızca birleştirmede/dışa aktarmada uzatılıyordu; editör
    önizlemesi ham klibi oynattığı için son saniyeler yine donuyordu. Artık klip
    üretildiği anda düzeltilir: önizleme, `proje.mp4` ve dışa aktarma aynı dosyayı görür.
    Dönüş: `(uzatildi_mi, mesaj)`. Hata olursa özgün dosya olduğu gibi kalır.
    """
    ffmpeg = shutil.which("ffmpeg")
    once, sonra = sure_doldurma(FFMPEG.medya_suresi(yol), sahne_suresi)
    if not ffmpeg or not once:
        return False, ""
    gecici = yol.with_name(yol.stem + ".uzatiliyor.mp4")
    komut = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(yol), "-an",
             "-vf", f"{once}fps={CIKTI_FPS},format=yuv420p{sonra}",
             "-t", f"{float(sahne_suresi):.3f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(gecici)]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if sonuc.returncode != 0 or not gecici.is_file() or gecici.stat().st_size == 0:
            gecici.unlink(missing_ok=True)
            return False, _ilk_satir(sonuc.stderr or sonuc.stdout, 200)
        gecici.replace(yol)
    except Exception as hata:
        gecici.unlink(missing_ok=True)
        return False, _ilk_satir(hata, 200)
    return True, f"klip {float(sahne_suresi):.1f} sn'lik sahneye yavaşlatılarak uzatıldı"


def _tuval_klibi(ffmpeg, kaynak, hedef, bilgi, saniye=ADIM_SANIYE):
    """Klibi hedef tuvale oturt: tuvali dolduracak şekilde kırp, kare hızını eşitle.

    Space klipleri 480–832 aralığında ve 16 fps gelir; farklı Space'ler farklı ölçü
    döndürebilir. Birleştirme ancak bütün klipler aynı ölçü, kare hızı, piksel biçimi
    ve SAR değerinde olursa çalışır; bu yüzden her klip önce buradan geçer. Klip,
    adım süresinden uzun dönebileceği için (ör. 5 sn istendi, 5,0625 sn geldi) `saniye`
    değerine kesilir; kısaysa yavaşlatılarak doldurulur (`sure_doldurma`). Eskiden kısa
    klip olduğu gibi kalıyor, sonraki bütün sahneler anlatımın önüne kayıyordu.
    """
    genislik, yukseklik = bilgi["genislik"], bilgi["yukseklik"]
    once, sonra = sure_doldurma(FFMPEG.medya_suresi(kaynak), saniye)
    zincir = (f"{once}scale={genislik}:{yukseklik}:force_original_aspect_ratio=increase,"
              f"crop={genislik}:{yukseklik},fps={CIKTI_FPS},setsar=1,format=yuv420p{sonra}")
    komut = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(kaynak),
             "-t", f"{saniye:.3f}", "-an", "-vf", zincir,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", str(hedef)]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=1800,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as hata:
        hedef.unlink(missing_ok=True)
        return False, _ilk_satir(hata, 200)
    if sonuc.returncode == 0 and hedef.exists() and hedef.stat().st_size > 0:
        return True, ""
    hedef.unlink(missing_ok=True)
    return False, _ilk_satir(sonuc.stderr or sonuc.stdout, 300)


def birlestir(klasor, adimlar, hedef, bicim=None, adim_saniye=ADIM_SANIYE):
    """Adım videolarını **hedef tuvalde** tek dosyada birleştir (ses eklenmez).

    Her klip önce hedef tuvale oturtulur (oranı tuvali dolduracak şekilde kırpılır),
    kare hızı `CIKTI_FPS`'e eşitlenir, piksel biçimi ve SAR tekilleştirilir; ancak o
    zaman tek dosyada birleştirilebilirler. Oturtulmuş klipler `videolar/tuval/`
    altında saklanır: aynı ayarla yeniden birleştirme yeniden kodlama yapmaz.

    Video süresi **adımların kendi sürelerinin toplamı** olur (sahne süreleri anlatımın
    içeriğine göre değişken); `adim_saniye` yalnızca süresiz/eski adımlar için varsayılandır.
    Space'ler istenen süreyi hafifçe aşan klip döndürebildiği için (ör. 5 sn → 81 kare =
    5,0625 sn) fazlası tuval klibi üretilirken ilgili adımın süresine kesilir.
    """
    bilgi = bicim_bilgisi(bicim)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg bulunamadı; adımlar tek tek kaldı, birleştirme yapılmadı."
    girilen = [adim for adim in adimlar if adim.get("video")]
    if not girilen:
        return False, "Birleştirilecek adım videosu yok."
    tuval = klasor / "videolar" / TUVAL_KLASORU
    try:
        tuval.mkdir(parents=True, exist_ok=True)
    except OSError as hata:
        return False, "Tuval klasörü açılamadı: " + _ilk_satir(hata, 200)
    etiket = f"{bilgi['genislik']}x{bilgi['yukseklik']}"
    # Biçim değiştiyse eski tuval klipleri işe yaramaz: yalnızca bu tuval tutulur.
    for eski in tuval.glob(f"adim-*-*.mp4"):
        if not eski.name.endswith(f"-{etiket}.mp4"):
            eski.unlink(missing_ok=True)
    hazir = []
    for adim in girilen:
        kaynak = klasor / adim["video"]
        cikti = tuval / f"adim-{adim['index']:02d}-{etiket}.mp4"
        # Tuval klibi kaynaktan yeniyse yeniden kodlanmaz (kaldığı yerden devam hızlı).
        if not (cikti.exists() and cikti.stat().st_mtime >= kaynak.stat().st_mtime):
            ok, mesaj = _tuval_klibi(ffmpeg, kaynak, cikti, bilgi,
                                     adim_suresi(adim, adim_saniye or ADIM_SANIYE))
            if not ok:
                return False, (f"Adım {adim['index']} klibi {bilgi['genislik']}×"
                               f"{bilgi['yukseklik']} tuvaline çevrilemedi: "
                               + (mesaj or "bilinmeyen ffmpeg hatası"))
        hazir.append(cikti)
    # Concat listesi kendi klasörüne yazılır: ffmpeg, listedeki göreli adları liste
    # dosyasının bulunduğu klasöre göre çözer.
    liste = klasor / "videolar" / "birlestir.txt"
    liste.write_text("".join(f"file '{TUVAL_KLASORU}/{yol.name}'\n" for yol in hazir),
                     encoding="utf-8")
    ortak = {"capture_output": True, "text": True, "timeout": 1800,
             "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    sure = sum(adim_suresi(adim, adim_saniye or ADIM_SANIYE) for adim in girilen)
    taban = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(liste), "-t", f"{sure:.3f}"]
    # Tuval klipleri aynı kodlayıcı ayarından geçtiği için önce kopyalama denenir;
    # başarısız olursa aynı tuvalde yeniden kodlanır.
    denemeler = (taban + ["-c", "copy", "-movflags", "+faststart", str(hedef)],
                 taban + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                          "-pix_fmt", "yuv420p", "-r", str(CIKTI_FPS), str(hedef)])
    son_hata = ""
    for komut in denemeler:
        try:
            sonuc = subprocess.run(komut, **ortak)
        except Exception as hata:
            return False, "Birleştirme çalıştırılamadı: " + _ilk_satir(hata, 200)
        if sonuc.returncode == 0 and hedef.exists():
            olcu = FFMPEG.video_olcusu(hedef)
            ek = (f" · {olcu[0]}×{olcu[1]} · {CIKTI_FPS} fps" if olcu[0]
                  else f" · {bilgi['genislik']}×{bilgi['yukseklik']}")
            return True, (f"Adımlar birleştirildi: {hedef.name} ({sure:.0f} saniye{ek}) · "
                          f"{bilgi['ad']}")
        son_hata = _ilk_satir(sonuc.stderr or sonuc.stdout, 300)
    return False, "Birleştirme başarısız: " + (son_hata or "bilinmeyen ffmpeg hatası")


def birlestirme_gerekli(klasor, veri):
    """`proje.mp4` yoksa, **biçim değiştiyse** ya da adım videoları ondan yeni ise birleştir."""
    hedef = klasor / "proje.mp4"
    if not hedef.exists():
        return True
    if veri.get("birlestirme_bicim") != bicim_kunye(gorsel_kaynak_bicim(veri)):
        return True
    try:
        hedef_zaman = hedef.stat().st_mtime
        return any((klasor / adim["video"]).stat().st_mtime > hedef_zaman
                   for adim in veri["adimlar"] if adim.get("video"))
    except OSError:
        return True
