"""Proje klasöründeki ses, altyazı, dil ve müzik dosyalarının yolları."""

from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.metin import sayi as _sayi
from studioflow.proje.depo import adim_suresi, proje_adim_saniyesi
from studioflow.proje.sabitler import (
    ALTYAZI_KLASORU, ALTYAZI_LISTE_ADI, DIL_KLASORU, DUBLAJ_LISTE_ADI, HAM_VIDEO_ADI,
    MUZIK_KLASORU, MUZIK_LISTE_ADI, SES_SEVIYE_SINIR, SES_VARSAYILAN_SEVIYE)


def ses_seviyesi(deger):
    """Seslendirme seviyesini doğrula (yüzde): `SES_SEVIYE_SINIR` aralığına çekilir."""
    sayi = _sayi(deger, SES_VARSAYILAN_SEVIYE)
    return min(max(sayi, SES_SEVIYE_SINIR[0]), SES_SEVIYE_SINIR[1])


def anlatim_suzgeci(veri):
    """Anlatım/dublaj sesine uygulanacak ffmpeg ses süzgeci; %100'de boş metin.

    Seviye `veri["ayarlar"]["ses"]["seviye"]`dan okunur. Yükseltmede tepe noktaları
    kırpılmasın diye yumuşak sınırlayıcı eklenir: `level=0` sınırlayıcının kendi
    otomatik seviyelemesini kapatır (seçilen seviye olduğu gibi kalır), `latency=1`
    gecikmeyi telafi eder (ses altyazıyla kaymaz).
    """
    seviye = ses_seviyesi(((veri or {}).get("ayarlar", {}).get("ses") or {}).get("seviye"))
    if seviye == 100:
        return ""
    suzgec = f"volume={seviye / 100:.2f}"
    if seviye > 100:
        suzgec += ",alimiter=limit=0.97:level=0:latency=1"
    return suzgec


def ses_dosyasi(klasor, veri):
    """Projenin seslendirme dosyası; yoksa None."""
    kayit = (veri or {}).get("ses") or {}
    adaylar = [kayit.get("dosya"), "ses/seslendirme.wav", "ses/seslendirme.mp3"]
    for aday in adaylar:
        if not aday:
            continue
        yol = klasor / aday
        if yol.is_file():
            return yol
    return None


def altyazi_dosyasi(klasor):
    """Yakılmaya uygun altyazı dosyası: önce SRT, yoksa VTT."""
    for ad in ("seslendirme.srt", "seslendirme.vtt"):
        yol = klasor / "ses" / ad
        if yol.is_file():
            return yol
    return None


def sure_ozeti(veri):
    """Durum metni için süre özeti: video adım sayısı × adım süresi, ses ölçülen süre."""
    video_sure = sum(adim_suresi(a, proje_adim_saniyesi(veri))
                     for a in veri.get("adimlar") or [] if a.get("video"))
    ses_sure = float((veri.get("ses") or {}).get("sure") or 0)
    if not video_sure and not ses_sure:
        return ""
    return f"Video {video_sure:.1f} sn · ses {ses_sure:.1f} sn."


def dil_kodu(dil):
    """Dil kodunu doğrula: seslendirilebilir bir kod değilse boş metin döner."""
    kod = (dil or "").strip()
    return kod if kod in LANGUAGES and kod != "auto" else ""


def dil_klasoru(klasor):
    """Dil dosyalarının klasörü: `ses/diller/`."""
    return klasor / "ses" / DIL_KLASORU


def ham_video(klasor):
    """Ham video (ses ve altyazısı olmayan temel dosya) varsa yolunu döndür."""
    yol = klasor / HAM_VIDEO_ADI
    return yol if yol.is_file() else None


def dil_dosyasi(klasor, dil, uzanti):
    """Bir dilin proje içindeki dosyası (yoksa None): `ses/diller/seslendirme-<dil><uzantı>`."""
    kod = dil_kodu(dil)
    if not kod:
        return None
    yol = dil_klasoru(klasor) / f"seslendirme-{kod}{uzanti}"
    return yol if yol.is_file() else None


def dil_dosyalari(klasor):
    """`ses/diller/` altındaki hazır dil seslerini `{dil kodu: yol}` olarak listele."""
    dosyalar = {}
    try:
        yollar = sorted(dil_klasoru(klasor).glob("seslendirme-*.wav"))
    except OSError:
        return dosyalar
    for yol in yollar:
        kod = yol.stem.split("-", 1)[1] if "-" in yol.stem else ""
        if dil_kodu(kod):
            dosyalar[kod] = yol
    return dosyalar


def dil_dosya_listesi(klasor, dil):
    """Bir dilin indirilebilir dosyaları: ses, altyazılar ve çevrilmiş metin."""
    kod = dil_kodu(dil)
    if not kod:
        return []
    kok = dil_klasoru(klasor)
    adaylar = [kok / f"seslendirme-{kod}{uzanti}" for uzanti in (".wav", ".srt", ".vtt")]
    adaylar.append(kok / f"metin-{kod}.txt")
    return [str(yol) for yol in adaylar if yol.is_file()]


def sure_metni(saniye):
    """Saniyeyi `dakika:saniye` biçiminde yaz (ör. 192,4 → `3:12`)."""
    toplam = int(round(max(0.0, _sayi(saniye, 0.0, float))))
    return f"{toplam // 60}:{toplam % 60:02d}"


def dublaj_liste_yolu(klasor):
    """Kayıtlı dublajların listesi: `ses/diller/dublajlar.json`."""
    return dil_klasoru(klasor) / DUBLAJ_LISTE_ADI


def dublaj_dosyasi(klasor, ad, uzanti=".wav"):
    """Bir dublaj kaydının dosyası: `ses/diller/seslendirme-<ad><uzantı>` (yoksa None).

    Ad, kaydın adıdır; yazılmadıysa dil kodudur, yani tek dilli eski projelerin
    `seslendirme-en.wav` dosyaları aynı yoldan bulunur (bkz. `dil_dosyasi`).
    """
    temiz = str(ad or "").strip()
    if not temiz:
        return None
    yol = dil_klasoru(klasor) / f"seslendirme-{temiz}{uzanti}"
    return yol if yol.is_file() else None


def altyazi_klasoru(klasor):
    """Kaydedilmiş altyazıların klasörü: proje kökünde `altyazi/`."""
    return klasor / ALTYAZI_KLASORU


def altyazi_liste_yolu(klasor):
    """Kayıtlı altyazıların listesi: `altyazi/altyazilar.json`."""
    return altyazi_klasoru(klasor) / ALTYAZI_LISTE_ADI


def muzik_klasoru(klasor):
    """Müziklerin klasörü: proje kökünde `muzik/`."""
    return klasor / MUZIK_KLASORU


def muzik_liste_yolu(klasor):
    return muzik_klasoru(klasor) / MUZIK_LISTE_ADI
