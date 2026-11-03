"""Gömülü altyazı görünümü: yazı tipi, renk, seviye, libass ölçüleri ve önizleme."""
import hashlib
import re

from studioflow.altyazi.bloklar import wrap_lines
from studioflow.altyazi.kural import SUB_AYAR
from studioflow.ayarlar.bicimler import bicim_bilgisi
from studioflow.cekirdek import depolama
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir

# ---------------------------------------------- altyazı görünümü (ayarlar)
# Yazı tipi, rengi ve kalınlığı **kullanıcı ayarıdır** (arayüzde *Altyazı ayarları*
# paneli); videoya gömülürken `force_style`e buradan yazılır. Font listesi Windows'ta
# libass'ın çözdüğü yaygın fontlardan seçildi; listede olmayan bir ad yazılırsa libass
# Arial'e düşer (ölçüldü), bu yüzden serbest metin de güvenlidir.
ALTYAZI_FONT = "Arial"


ALTYAZI_RENK = "#FFFFFF"


# Altyazı **seviyesi**: yazının alt kenardan yüksekliği, tuval yüksekliğinin yüzdesi.
# TikTok / Reels / Shorts arayüzünde açıklama satırı ve düğmeler videonun **alt
# bölgesini** kaplar; yazı alışıldık alt boşlukta kalırsa arayüz çubuğunun arkasında
# kalır ve okunmaz. Bu yüzden seviye bir kullanıcı ayarıdır: varsayılan %25'tir ve
# bütün hazır ayarlar aynı değeri getirir (tuval yönüne göre oynamaz); kaydırıcıyla
# yazı istenen yere çekilir.
ALTYAZI_SEVIYE = 25.0           # varsayılan seviye: alttan %25


ALTYAZI_SEVIYE_SINIR = (0.0, 40.0)


# Altyazı **boyutu**: yazı yüksekliği, tuval yüksekliğinin yüzdesi (üst sınır; satır
# genişliği daha dar bir sınır koyarsa yazı ondan da küçük olur). Varsayılan %4,5 eski
# sabit değerdir; küçük altyazı isteyen proje bunu düşürür.
ALTYAZI_BOYUT = 4.5


ALTYAZI_BOYUT_SINIR = (2.0, 8.0)


def altyazi_boyut(deger, varsayilan=ALTYAZI_BOYUT):
    """Altyazı boyutunu doğrula (tuval yüksekliğinin %'si); geçersiz değer varsayılana düşer."""
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return round(float(varsayilan), 1)
    return round(min(max(sayi, ALTYAZI_BOYUT_SINIR[0]), ALTYAZI_BOYUT_SINIR[1]), 1)


ALTYAZI_FONTLARI = ("Arial", "Calibri", "Verdana", "Tahoma", "Segoe UI", "Trebuchet MS",
                    "Georgia", "Times New Roman", "Comic Sans MS", "Impact",
                    "Franklin Gothic Medium", "Candara", "Corbel", "Cambria")


# ------------------------------------------------- altyazı görünümü (libass)
# libass, SRT dosyasını **384×288'lik** bir ASS betiği kabul eder ve `force_style`
# içindeki bütün sayıları `kare yüksekliği / 288` oranıyla büyütür. Yani oraya
# yazılan değerler piksel değil **betik birimidir**: hedef pikseli bu ölçeğe bölmek
# gerekir. Bölünmezse yazı, tuval büyüdükçe iki kez büyür — 1080p yatayda ekranın
# üçte biri, dikey Shorts'ta yazı ekranın tepesine taşacak kadar devasa olur.
ALTYAZI_BETIK_YUKSEKLIK = 288.0


# Arial'de ortalama karakter genişliği ~0,41 em'dir (ölçüldü); satır genişliği sınırı
# emniyet payıyla 0,48 em üzerinden hesaplanır: dar kutu/CapCut ayarında satır taşmaz,
# yazı da boşuna küçülmez.
ALTYAZI_KARAKTER_EM = 0.48


def altyazi_font_adi(deger):
    """Yazı tipi adını güvenli hâle getir.

    Ad doğrudan ffmpeg filtresinin içine yazıldığı için virgül, iki nokta, tırnak ve
    ters bölü gibi ayraçlar atılır: kullanıcı arayüze ne yazarsa yazsın filtre zinciri
    bozulmaz. Boş sonuç varsayılana düşer.
    """
    temiz = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü ._-]", "", str(deger or "").strip())
    return temiz.strip()[:40] or ALTYAZI_FONT


def altyazi_rengi(deger, varsayilan=ALTYAZI_RENK):
    """`#RRGGBB` rengini doğrula (küçük harf/# olmadan da kabul edilir)."""
    eslesme = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(deger or "").strip())
    return "#" + eslesme.group(1).upper() if eslesme else varsayilan


def _altyazi_ass_rengi(renk):
    """`#RRGGBB` → ASS rengi `&H00BBGGRR` (ASS'te kanal sırası terstir)."""
    onalti = altyazi_rengi(renk)[1:]
    kirmizi, yesil, mavi = (onalti[sira:sira + 2] for sira in (0, 2, 4))
    return f"&H00{mavi}{yesil}{kirmizi}"


def altyazi_seviye(deger, varsayilan=None):
    """Altyazı seviyesini doğrula: yazının alttan yüksekliği, tuval yüksekliğinin %'si.

    Arayüzdeki kaydırıcı, `proje.txt` ve genel ayar dosyası aynı sınırı paylaşır
    (`ALTYAZI_SEVIYE_SINIR`). Okunamayan ya da aralık dışı değer sessizce varsayılana
    çekilir; böylece eski projeler ve elle bozulmuş dosyalar hatasız açılır.
    """
    varsayilan = ALTYAZI_SEVIYE if varsayilan is None else varsayilan
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return round(float(varsayilan), 1)
    return round(min(max(sayi, ALTYAZI_SEVIYE_SINIR[0]), ALTYAZI_SEVIYE_SINIR[1]), 1)


def srt_olculeri(satirlar):
    """SRT metninden `(en uzun satırın karakter sayısı, bir blokta en çok satır)` çıkar.

    Zaman damgası ve blok numarası satırları sayılmaz; boş satır bloğu bitirir.
    """
    en_uzun, en_cok, sayac = 0, 1, 0
    for satir in satirlar:
        metin = (satir or "").strip()
        if not metin:
            sayac = 0
            continue
        if "-->" in metin or metin.isdigit():
            continue
        sayac += 1
        en_cok = max(en_cok, sayac)
        en_uzun = max(en_uzun, len(metin))
    return en_uzun, en_cok


def altyazi_olcu(genislik, yukseklik, altyazi=None, satirlar=None):
    """Altyazı stilini tuvalin **gerçek** ölçüsüne ve ayarlara göre hesapla.

    `altyazi` projenin (ya da genel ayarın) `altyazi` sözlüğüdür: `ayar` blok kuralları
    (`line_chars`/`max_lines`) ile görünüm (`font`, `renk`, `kalin`) birlikte okunur.

    Dönüş: `(force_style metni, yazı boyutu px, alt boşluk px)`. Alt boşluk **seviyeden**
    gelir (`altyazi.seviye`: yazının alttan yüksekliği, tuval yüksekliğinin yüzdesi; bkz.
    `ALTYAZI_SEVIYE`). Yazı boyutu üç sınıra birlikte uyar:

    1. kare yüksekliği (yazı tuvali kaplamasın),
    2. satırdaki karakter sayısı (dar kutu/Shorts'ta satır taşmasın),
    3. çok satırlı altyazıda blok ekranın alt üçte birini aşmasın.

    `satirlar` verilirse (SRT'nin satırları) genişlik sınırı **gerçek** en uzun
    satırdan hesaplanır: ayardaki `line_chars` yalnızca üst sınırdır, gerçek satırlar
    genelde daha kısa olur ve yazı boşuna küçülmemelidir.

    Dönen `px` değerleri **ekranda görünen** ölçüdür; `force_style`e yazılan sayılar
    ise libass betik birimidir (bkz. `ALTYAZI_BETIK_YUKSEKLIK`).
    """
    genislik, yukseklik = max(int(genislik or 0), 1), max(int(yukseklik or 0), 1)
    altyazi = altyazi or {}
    kural = altyazi.get("ayar") or {}
    font = altyazi_font_adi(altyazi.get("font"))
    renk = _altyazi_ass_rengi(altyazi.get("renk"))
    kalin = -1 if altyazi.get("kalin") else 0
    karakter = max(8, int(kural.get("line_chars") or SUB_AYAR["line_chars"]))
    satir = max(1, int(kural.get("max_lines") or 1))
    if satirlar:
        uzun, cok = srt_olculeri(satirlar)
        karakter = max(8, uzun or karakter)
        satir = max(satir, cok)
    yazi = min(yukseklik * altyazi_boyut(altyazi.get("boyut")) / 100.0,
               (genislik * 0.92) / (karakter * ALTYAZI_KARAKTER_EM),
               (yukseklik * 0.32) / satir)
    yazi = max(12.0, yazi)
    # Seviye: yazının alt kenardan yüksekliği (tuval yüksekliğinin yüzdesi). Ayar
    # yazılmamışsa (eski proje) varsayılana düşülür; hedef tuval yönü sonucu değiştirmez.
    seviye = altyazi_seviye(altyazi.get("seviye"))
    alt = yukseklik * seviye / 100.0
    kontur = min(4.0, max(1.5, yazi * 0.06))
    olcek = yukseklik / ALTYAZI_BETIK_YUKSEKLIK
    # Gölge kapalıysa yazının arkasında koyu gölge/fon kalmaz; okunabilirlik için yalnızca
    # ince bir dış çizgi bırakılır.
    golge = altyazi.get("golge", True) is not False
    if not golge:
        kontur = max(1.0, yazi * 0.035)
    stil = (f"FontName={font},FontSize={max(6, round(yazi / olcek))},"
            f"PrimaryColour={renk},OutlineColour=&H00000000,"
            f"Outline={max(0.3, round(kontur / olcek, 1)):g},Bold={kalin},"
            f"Shadow={1 if golge else 0},BorderStyle=1,"
            f"Alignment=2,MarginV={max(2, round(alt / olcek))}")
    return stil, round(yazi), round(alt)


def altyazi_ayari(veri):
    """Projenin altyazı ayarları (blok kuralları + görünüm); yoksa boş sözlük."""
    return ((veri.get("ayarlar") or {}).get("altyazi") or {}) if isinstance(veri, dict) else {}


# ---------------------------------------------- altyazı önizlemesi (arayüz)
# Arayüzdeki **Altyazı ayarları** panelinde küçük bir önizleme kutusu durur. Kutu,
# tarayıcıda çizilen bir taklit değildir: gömme yolunun **aynısı** kullanılır
# (`altyazi_olcu` + libass) ve yalnızca kare küçültülür. Böylece yazı tipi, rengi,
# kalınlığı ve konumu, videoya gömülecek hâliyle aynı görünür.
ONIZLEME_ORNEK = "Sevimli bir geyik ovada koşuyor ve etrafı sessizce izliyor."


ONIZLEME_YUKSEKLIK = 360        # önizleme karesinin yüksekliği; küçük tutulur (hızlı)


# Önizleme zemini: amaç yazının **her koşulda** okunup okunmadığını görebilmek. Her
# değer bir lavfi girişidir; renkli zeminde yumuşak bir renk geçişi kullanılır (düz
# renklerden daha gerçekçi). Bu ayar **yalnızca önizlemeyi** etkiler, gömülen videoya
# karışmaz; bu yüzden proje ayarlarına da yazılmaz.
ONIZLEME_ZEMINLERI = {
    "koyu": ("Koyu · gece / karanlık sahne",
             "color=c=0x15181e:s={g}x{y}:d=1:r=1"),
    "acik": ("Açık · gündüz / parlak sahne",
             "color=c=0xe9eaee:s={g}x{y}:d=1:r=1"),
    "renkli": ("Renkli · renk geçişli sahne",
               "gradients=s={g}x{y}:d=1:r=1:n=4:c0=0x2b1b4d:c1=0x0f6f8f:"
               "c2=0xc9722a:c3=0x8a2b52:x0=0:y0=0:x1={g}:y1={y}"),
}


ONIZLEME_ZEMIN = "koyu"


def onizleme_zemin_secenekleri():
    """Arayüzdeki **Önizleme zemini** listesi: `(etiket, anahtar)` çiftleri."""
    return [(etiket, anahtar) for anahtar, (etiket, _girdi) in ONIZLEME_ZEMINLERI.items()]


def _onizleme_metni(kural):
    """Önizleme için **gerçek bir blok gibi** örnek metin seç.

    Metin, satır sınırına göre kelime ortasından bölünmeden kısaltılır: dar kutuda
    tek satır, geniş kutuda iki satır görünür — önizleme kırpılmış değil, dolu görünür.
    """
    limit = max(8, int(kural.get("line_chars") or SUB_AYAR["line_chars"]))
    sinir = limit * max(1, int(kural.get("max_lines") or 1))
    secilen = []
    for kelime in ONIZLEME_ORNEK.split():
        aday = " ".join(secilen + [kelime])
        if secilen and len(aday) > sinir:
            break
        secilen.append(kelime)
    return wrap_lines(" ".join(secilen) or ONIZLEME_ORNEK, kural)


def altyazi_onizleme(bicim, altyazi=None, zemin=None):
    """Altyazı görünümünü küçük bir karede üret.

    Dönüş: `(görüntü yolu ya da None, durum metni)`. Kare, hedef tuvalin oranı korunarak
    küçültülür ve gömme yoluyla **aynı** stil hesaplanır; durum metninde ise **gerçek**
    tuvalde görünecek yazı boyutu ve alt boşluk yazar. `zemin` yalnızca önizlemenin
    arka planını seçer (bkz. `ONIZLEME_ZEMINLERI`); gömülen videoya etkisi yoktur.
    """
    altyazi = altyazi or {}
    bilgi = bicim_bilgisi(bicim)
    genislik, yukseklik = max(int(bilgi["genislik"]), 2), max(int(bilgi["yukseklik"]), 2)
    kural = altyazi.get("ayar") or {}
    satirlar = _onizleme_metni(kural)
    # Gerçek tuval: kullanıcıya bildirilecek ölçüler buradan gelir.
    _stil, yazi, alt = altyazi_olcu(genislik, yukseklik, altyazi, satirlar)
    etiket = (f"**{bilgi['ad']}** · {genislik}×{yukseklik} tuvalde yazı {yazi} px, "
              f"alttan {alt} px · seviye %{round(alt * 100 / yukseklik)} · "
              f"{altyazi_font_adi(altyazi.get('font'))} · "
              f"{altyazi_rengi(altyazi.get('renk'))}"
              f"{' · kalın' if altyazi.get('kalin') else ''}")
    # Zemin: seçenek anahtarı bilinmiyorsa varsayılana düşülür (bozuk ayar kareyi bozmaz).
    _zemin_etiket, zemin_girdisi = ONIZLEME_ZEMINLERI.get(
        zemin or ONIZLEME_ZEMIN, ONIZLEME_ZEMINLERI[ONIZLEME_ZEMIN])
    ffmpeg = FFMPEG.ffmpeg()
    if not ffmpeg:
        return None, ("Önizleme için ffmpeg gerekir (altyazıyı videoya gömmek için de "
                      "gerekir). ffmpeg'i kurup tekrar dene. " + etiket)
    olcek = ONIZLEME_YUKSEKLIK / yukseklik
    p_genislik = max(2, round(genislik * olcek))
    p_yukseklik = max(2, round(yukseklik * olcek))
    stil, _pyazi, _palt = altyazi_olcu(p_genislik, p_yukseklik, altyazi, satirlar)
    klasor = depolama.GECICI
    try:
        klasor.mkdir(parents=True, exist_ok=True)
    except OSError as hata:
        return None, "Önizleme klasörü açılamadı: " + _ilk_satir(hata, 200)
    # Dosya adı stile göre değişir: ayar değişince adres de değişir, tarayıcı eski
    # kareyi önbellekten göstermez. Eski önizlemeler birikmesin diye silinir.
    imza = hashlib.md5((stil + "|" + zemin_girdisi).encode("utf-8")).hexdigest()[:10]
    for eski in klasor.glob("altyazi-onizleme-*.png"):
        eski.unlink(missing_ok=True)
    srt = klasor / "altyazi-onizleme.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:30,000\n" + "\n".join(satirlar) + "\n",
                   encoding="utf-8")
    hedef = klasor / f"altyazi-onizleme-{imza}.png"
    komut = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i",
             zemin_girdisi.format(g=p_genislik, y=p_yukseklik),
             "-vf", f"subtitles={srt.name}:force_style='{stil}'",
             "-frames:v", "1", hedef.name]
    # SRT göreli adla verilir (ffmpeg `GECICI` klasöründe çalışır): Windows'ta `C:`
    # iki noktası filtre zincirini bozmasın.
    ok, mesaj = FFMPEG.calistir(komut, cwd=klasor)
    if not ok or not hedef.exists():
        return None, "Önizleme üretilemedi: " + (mesaj or "bilinmeyen ffmpeg hatası")
    return str(hedef), etiket
