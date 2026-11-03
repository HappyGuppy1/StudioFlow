"""Harita animasyonu: durak listesi → kamera planı → kare kare çizim → MP4.

Akış:
1. **Duraklar** satır satır okunur: `Atina`, `Truva | Hisarlık, Çanakkale` (etiket |
   arama) ya da `Truva | 39.957, 26.239` (etiket | enlem, boylam). Koordinatı olmayan
   satır OpenStreetMap Nominatim ile bulunur (saniyede en fazla bir istek).
2. **Kamera planı:** genel bakış → her bacak için (yolu çerçeveleyen yakınlık) rota
   çizilirken kamera ucu izler → bacaklar arası MapLibre'nin `flyTo` eğrisiyle
   (van Wijk & Nuij) uçuş → sonda yeniden genel bakış.
3. **Çizim:** karolar kameranın kesirli yakınlığına göre birleştirilip piksel altı
   hassasiyetle ölçeklenir (titreme olmaz), rota/durak/etiket katmanı 2× çizilip
   küçültülür (yumuşak kenarlar), kareler ffmpeg'e ham RGB olarak akıtılır.
"""
import math
import re
import subprocess
import time
from dataclasses import dataclass

import requests
from PIL import Image, ImageDraw, ImageFont

from studioflow.cekirdek.ffmpeg import FFmpeg
from studioflow.harita.karolar import KARO

NOMINATIM = "https://nominatim.openstreetmap.org/search"
FORMATLAR = {"yatay": (1920, 1080), "dikey": (1080, 1920)}
CIZGI_TURLERI = ("kavis", "buyuk_daire", "duz")
EN_YAKIN_ZOOM = 12            # kısa bacaklarda kamera bundan daha fazla yaklaşmaz
KENAR_PAYI = 0.2              # çerçevelemede her kenarda bırakılan pay (oran)
IZLEME = 0.35                 # "rotayı izle": kamera bacak merkezinden uca bu oranda kayar
SS = 2                        # katman süper örnekleme katsayısı
_YAZI_TIPLERI = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
_SAYI = r"(-?\d+(?:[.]\d+)?)"
_KOORDINAT = re.compile(rf"^\s*\(?\s*{_SAYI}\s*[,;\s]\s*{_SAYI}\s*\)?\s*$")


class HaritaHatasi(Exception):
    """Kullanıcıya gösterilecek açıklamalı hata."""


@dataclass
class Durak:
    ad: str
    enlem: float
    boylam: float


@dataclass
class Ayarlar:
    genislik: int = 1920
    yukseklik: int = 1080
    fps: int = 30
    bacak_suresi: float = 3.0       # bir bacağın çizim süresi (sn)
    cizgi: str = "kavis"
    renk: tuple = (230, 57, 70)
    kalinlik: float = 0.006         # çizgi kalınlığı: kısa kenarın oranı
    kamera_izle: bool = True
    etiketler: bool = True
    karartma: bool = True


# ── Durak listesi ─────────────────────────────────────────────────────────────────

def satirlari_ayir(metin):
    """Her satır için `(etiket, sorgu, koordinat ya da None)`; boş ve # satırları atlanır."""
    sonuc = []
    for satir in str(metin or "").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        etiket, _, sorgu = satir.partition("|")
        etiket, sorgu = etiket.strip(), (sorgu.strip() or etiket.strip())
        eslesme = _KOORDINAT.match(sorgu)
        koordinat = None
        if eslesme:
            enlem, boylam = float(eslesme.group(1)), float(eslesme.group(2))
            if not (-85 <= enlem <= 85 and -180 <= boylam <= 180):
                raise HaritaHatasi(f"Geçersiz koordinat: '{satir}' (enlem ±85, boylam ±180).")
            koordinat = (enlem, boylam)
            if etiket == sorgu:
                etiket = ""
        sonuc.append((etiket, sorgu, koordinat))
    return sonuc


def konum_bul(sorgu, oturum=None):
    """Nominatim ile yer adını `(enlem, boylam)`a çevir; bulunamazsa HaritaHatasi."""
    try:
        yanit = (oturum or requests).get(
            NOMINATIM, params={"q": sorgu, "format": "json", "limit": 1},
            headers={"User-Agent": "StudioFlow/1.0 (harita animasyonu)",
                     "Accept-Language": "tr,en"}, timeout=20)
        yanit.raise_for_status()
        veri = yanit.json()
    except Exception as hata:
        raise HaritaHatasi(f"'{sorgu}' aranamadı (Nominatim): {hata}") from None
    if not veri:
        raise HaritaHatasi(f"'{sorgu}' bulunamadı. Daha açık yaz (ör. 'Hisarlık, Çanakkale') "
                           f"ya da koordinat ver: 'Truva | 39.957, 26.239'.")
    return float(veri[0]["lat"]), float(veri[0]["lon"])


def duraklari_coz(metin, bul=konum_bul, bekle=time.sleep):
    """Durak metnini `Durak` listesine çevir (en az iki durak)."""
    satirlar = satirlari_ayir(metin)
    if len(satirlar) < 2:
        raise HaritaHatasi("En az iki durak yaz (her satıra bir yer).")
    duraklar, ilk_arama = [], True
    for etiket, sorgu, koordinat in satirlar:
        if koordinat is None:
            if not ilk_arama:
                bekle(1.1)                      # Nominatim: saniyede en fazla bir istek
            ilk_arama = False
            koordinat = bul(sorgu)
        duraklar.append(Durak(etiket, *koordinat))
    return duraklar


# ── Geometri (Web Mercator, birim kare: dünya 0..1) ───────────────────────────────

def birim(enlem, boylam):
    """Enlem/boylamı Web Mercator birim koordinatına çevir."""
    enlem = max(-85.05, min(85.05, enlem))
    s = math.sin(math.radians(enlem))
    return (boylam + 180) / 360, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def bacak_noktalari(a, b, tur="kavis", n=96):
    """İki durak arasındaki yolun birim koordinat noktaları (tarih çizgisinde sürekli)."""
    xa, ya = birim(a.enlem, a.boylam)
    xb, yb = birim(b.enlem, b.boylam)
    if xb - xa > 0.5:                           # kısa yoldan git: tarih çizgisini aş
        xb -= 1
    elif xa - xb > 0.5:
        xb += 1
    if tur == "duz":
        return [(xa + (xb - xa) * t, ya + (yb - ya) * t) for t in _araliklar(n)]
    if tur == "buyuk_daire":
        noktalar = _buyuk_daire(a, b, n)
        sonuc, onceki = [], None
        for enlem, boylam in noktalar:
            x, y = birim(enlem, boylam)
            if onceki is not None:              # tarih çizgisi sıçramasını aç
                x += round(onceki - x)
            sonuc.append((x, y))
            onceki = x
        return sonuc
    # kavis: Vox tarzı yay; düz çizginin soluna doğru, uzunluğun %18'i kadar kabarır
    dx, dy = xb - xa, yb - ya
    kx, ky = (xa + xb) / 2 - dy * 0.18 * 2, (ya + yb) / 2 + dx * 0.18 * 2
    return [((1 - t) ** 2 * xa + 2 * (1 - t) * t * kx + t * t * xb,
             (1 - t) ** 2 * ya + 2 * (1 - t) * t * ky + t * t * yb) for t in _araliklar(n)]


def _araliklar(n):
    return [i / (n - 1) for i in range(n)]


def _buyuk_daire(a, b, n):
    def vektor(d):
        e, bo = math.radians(d.enlem), math.radians(d.boylam)
        return (math.cos(e) * math.cos(bo), math.cos(e) * math.sin(bo), math.sin(e))
    va, vb = vektor(a), vektor(b)
    aci = math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(va, vb)))))
    if aci < 1e-9:
        return [(a.enlem, a.boylam)] * n
    sonuc = []
    for t in _araliklar(n):
        ka, kb = math.sin((1 - t) * aci) / math.sin(aci), math.sin(t * aci) / math.sin(aci)
        x, y, z = (ka * p + kb * q for p, q in zip(va, vb))
        sonuc.append((math.degrees(math.atan2(z, math.hypot(x, y))),
                      math.degrees(math.atan2(y, x))))
    return sonuc


class Yol:
    """Bir bacağın noktaları ve yay uzunluğuna göre kesir → nokta dönüşümü."""

    def __init__(self, noktalar):
        self.noktalar = noktalar
        self.birikim = [0.0]
        for (x0, y0), (x1, y1) in zip(noktalar, noktalar[1:]):
            self.birikim.append(self.birikim[-1] + math.hypot(x1 - x0, y1 - y0))
        self.uzunluk = self.birikim[-1] or 1e-12

    def kesit(self, f):
        """Yolun başından `f` (0..1) kesrine kadarki noktalar (son nokta ara değer)."""
        if f >= 1:
            return list(self.noktalar)
        hedef = max(0.0, f) * self.uzunluk
        sonuc = [self.noktalar[0]]
        for i in range(1, len(self.noktalar)):
            if self.birikim[i] >= hedef:
                onceki = self.birikim[i - 1]
                t = (hedef - onceki) / ((self.birikim[i] - onceki) or 1e-12)
                (x0, y0), (x1, y1) = self.noktalar[i - 1], self.noktalar[i]
                sonuc.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
                return sonuc
            sonuc.append(self.noktalar[i])
        return sonuc

    def uc(self, f):
        return self.kesit(f)[-1]


# ── Kamera ────────────────────────────────────────────────────────────────────────

@dataclass
class Kamera:
    x: float        # merkez, birim koordinat
    y: float
    z: float        # kesirli yakınlık (Web Mercator zoom)


def cercevele(noktalar, genislik, yukseklik, en_buyuk_zoom):
    """Noktaları kenar paylarıyla ekrana sığdıran kamera."""
    xs, ys = [p[0] for p in noktalar], [p[1] for p in noktalar]
    w, h = max(max(xs) - min(xs), 1e-9), max(max(ys) - min(ys), 1e-9)
    kullanilan = 1 - 2 * KENAR_PAYI
    z = math.log2(min(genislik * kullanilan / (w * KARO), yukseklik * kullanilan / (h * KARO)))
    z = max(1.0, min(z, EN_YAKIN_ZOOM, en_buyuk_zoom + 1.5))
    return Kamera((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, z)


def ucus(a, b, genislik, yukseklik, rho=1.42):
    """MapLibre `flyTo` eğrisi: `(k → Kamera, S)`; S yolun göreli uzunluğudur."""
    w0 = max(genislik, yukseklik)
    w1 = w0 / 2 ** (b.z - a.z)
    olcek0 = KARO * 2 ** a.z
    u1 = math.hypot(b.x - a.x, b.y - a.y) * olcek0
    rho2 = rho * rho

    if u1 < 1e-6:
        S = abs(math.log(w1 / w0)) / rho if w1 != w0 else 0.0
        isaret = -1 if w1 < w0 else 1

        def w(s):
            return math.exp(isaret * rho * s)

        def u(_s):
            return 0.0
    else:
        def r(i):
            wi = w1 if i else w0
            bi = (w1 * w1 - w0 * w0 + (-1) ** i * rho2 * rho2 * u1 * u1) / (2 * wi * rho2 * u1)
            return math.log(math.sqrt(bi * bi + 1) - bi)
        r0 = r(0)
        S = (r(1) - r0) / rho

        def w(s):
            return math.cosh(r0) / math.cosh(r0 + rho * s)

        def u(s):
            return w0 * ((math.cosh(r0) * math.tanh(r0 + rho * s) - math.sinh(r0)) / rho2) / u1

    def kamera(k):
        if k <= 0:
            return a
        if k >= 1 or S == 0:
            return b if k >= 1 else a
        s = k * S
        oran = u(s)
        return Kamera(a.x + (b.x - a.x) * oran, a.y + (b.y - a.y) * oran,
                      a.z + math.log2(1 / w(s)))
    return kamera, S


def _yumusak(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _yumusak_cikis(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


@dataclass
class Kare:
    kamera: Kamera
    ilerleme: float     # tamamlanan bacak sayısı + yarımın kesri (0..bacak sayısı)


def plan_yap(duraklar, ayar, en_buyuk_zoom):
    """Videonun tüm karelerini (kamera + rota ilerlemesi) üret. `(kareler, yollar)`."""
    W, H, fps = ayar.genislik, ayar.yukseklik, ayar.fps
    yollar = [Yol(bacak_noktalari(a, b, ayar.cizgi)) for a, b in zip(duraklar, duraklar[1:])]
    hepsi = [p for yol in yollar for p in yol.noktalar]
    genel = cercevele(hepsi, W, H, en_buyuk_zoom)
    genel_uzak = Kamera(genel.x, genel.y, max(1.0, genel.z - 0.35))
    cerceveler = [cercevele(yol.noktalar, W, H, en_buyuk_zoom) for yol in yollar]

    def bacak_kamerasi(i, f):
        c = cerceveler[i]
        if not ayar.kamera_izle:
            return c
        ux, uy = yollar[i].uc(f)
        return Kamera(c.x + (ux - c.x) * IZLEME, c.y + (uy - c.y) * IZLEME, c.z)

    kareler = []

    def bekle(kamera, ilerleme, saniye):
        kareler.extend(Kare(kamera, ilerleme) for _ in range(round(saniye * fps)))

    def uc(a, b, ilerleme):
        kamera, S = ucus(a, b, W, H)
        if S < 0.05 and abs(a.z - b.z) < 0.05:
            return
        n = round(max(1.0, min(3.5, S / 1.2)) * fps)
        kareler.extend(Kare(kamera(_yumusak((i + 1) / n)), ilerleme) for i in range(n))

    # Açılış: genel bakışa hafif yaklaşma, sonra ilk bacağa uçuş.
    n = round(1.2 * fps)
    for i in range(n):
        t = _yumusak_cikis(i / max(1, n - 1))
        kareler.append(Kare(Kamera(genel.x, genel.y,
                                   genel_uzak.z + (genel.z - genel_uzak.z) * t), 0.0))
    uc(genel, bacak_kamerasi(0, 0.0), 0.0)
    for i in range(len(yollar)):
        n = max(2, round(ayar.bacak_suresi * fps))
        for j in range(n):
            f = _yumusak((j + 1) / n)
            kareler.append(Kare(bacak_kamerasi(i, f), i + f))
        bekle(bacak_kamerasi(i, 1.0), i + 1.0, 0.6)
        if i + 1 < len(yollar):
            uc(bacak_kamerasi(i, 1.0), bacak_kamerasi(i + 1, 0.0), i + 1.0)
    uc(bacak_kamerasi(len(yollar) - 1, 1.0), genel, float(len(yollar)))
    bekle(genel, float(len(yollar)), 2.0)
    return kareler, yollar


# ── Çizim ─────────────────────────────────────────────────────────────────────────

def _karo_duzeyi(z, en_buyuk_zoom):
    return max(0, min(en_buyuk_zoom, math.ceil(z - 0.25)))


def gorunen_karolar(kamera, W, H, en_buyuk_zoom):
    """Kameranın gördüğü karolar `(z, x, y)` (x sarılmamış) ve kaynak kutusu."""
    zi = _karo_duzeyi(kamera.z, en_buyuk_zoom)
    olcek = 2 ** (kamera.z - zi)
    boyut = KARO * 2 ** zi
    x0, y0 = kamera.x * boyut - W / (2 * olcek), kamera.y * boyut - H / (2 * olcek)
    x1, y1 = x0 + W / olcek, y0 + H / olcek
    tx0, ty0 = math.floor(x0 / KARO), math.floor(y0 / KARO)
    tx1, ty1 = math.floor((x1 - 1e-6) / KARO), math.floor((y1 - 1e-6) / KARO)
    karolar = [(zi, tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]
    return karolar, (zi, tx0, ty0, tx1, ty1, x0, y0, x1, y1)


def zemin_ciz(kamera, W, H, depo):
    """Kameranın gördüğü haritayı W×H RGB olarak birleştir."""
    _karolar, (zi, tx0, ty0, tx1, ty1, x0, y0, x1, y1) = gorunen_karolar(
        kamera, W, H, depo.en_buyuk_zoom)
    mozaik = Image.new("RGB", ((tx1 - tx0 + 1) * KARO, (ty1 - ty0 + 1) * KARO), depo.zemin)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            karo = depo.karo(zi, tx, ty)
            if karo is not None:
                mozaik.paste(karo, ((tx - tx0) * KARO, (ty - ty0) * KARO))
    kutu = (x0 - tx0 * KARO, y0 - ty0 * KARO, x1 - tx0 * KARO, y1 - ty0 * KARO)
    return mozaik.resize((W, H), Image.BILINEAR, box=kutu)


def yazi_tipi(boyut):
    for ad in _YAZI_TIPLERI:
        try:
            return ImageFont.truetype(ad, boyut)
        except OSError:
            continue
    return ImageFont.load_default(boyut)


def _karartma(W, H):
    """Kenarları hafifçe koyulaştıran sabit maske (belgesel görünümü; siyah bununla basılır)."""
    kucuk = Image.new("L", (64, 36 if W >= H else 114))
    kw, kh = kucuk.size
    piksel = kucuk.load()
    for j in range(kh):
        for i in range(kw):
            d = math.hypot((i + 0.5) / kw - 0.5, (j + 0.5) / kh - 0.5) / 0.7071
            piksel[i, j] = int(150 * max(0.0, d - 0.45) ** 1.6 / 0.55 ** 1.6)
    return kucuk.resize((W, H), Image.BICUBIC)


class Cizici:
    """Planın karelerini sırayla çizer (durak beliriş zamanlarını kendisi tutar)."""

    def __init__(self, duraklar, yollar, ayar, depo):
        self.duraklar, self.yollar, self.ayar, self.depo = duraklar, yollar, ayar, depo
        W, H = ayar.genislik, ayar.yukseklik
        kisa = min(W, H)
        self.kalinlik = max(2.0, kisa * ayar.kalinlik) * SS
        self.yazi = yazi_tipi(round(kisa * 0.036 * SS))
        self.atif_yazi = yazi_tipi(round(kisa * 0.015))
        self.karartma = _karartma(W, H) if ayar.karartma else None
        self.belirme = {}           # durak sırası → beliriş karesi
        self.sayac = 0

    def _ekran(self, kamera, p):
        olcek = KARO * 2 ** kamera.z
        return ((p[0] - kamera.x) * olcek + self.ayar.genislik / 2) * SS, \
               ((p[1] - kamera.y) * olcek + self.ayar.yukseklik / 2) * SS

    def ciz(self, kare):
        ayar, W, H = self.ayar, self.ayar.genislik, self.ayar.yukseklik
        resim = zemin_ciz(kare.kamera, W, H, self.depo)
        if self.karartma is not None:
            resim.paste((0, 0, 0), mask=self.karartma)
        katman = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        cizim = ImageDraw.Draw(katman)
        k = self.kalinlik
        renk = tuple(ayar.renk)

        # Rota: tamamlanan bacaklar + yarım bacak; altta gölge, üstte renkli çizgi.
        noktalar = []
        for i, yol in enumerate(self.yollar):
            if kare.ilerleme <= i:
                break
            kesit = yol.kesit(min(1.0, kare.ilerleme - i))
            noktalar.append([self._ekran(kare.kamera, p) for p in kesit])
        for parca in noktalar:
            if len(parca) > 1:
                cizim.line(parca, fill=(0, 0, 0, 110), width=round(k + 3 * SS), joint="curve")
        for parca in noktalar:
            if len(parca) > 1:
                cizim.line(parca, fill=renk + (255,), width=round(k), joint="curve")

        # Duraklar: ulaşılınca yaylanarak belirir; etiket aynı anda solarak gelir.
        for j, durak in enumerate(self.duraklar):
            if kare.ilerleme + 1e-9 < j:
                continue
            self.belirme.setdefault(j, self.sayac)
            t = min(1.0, (self.sayac - self.belirme[j]) / max(1, 0.4 * ayar.fps))
            buyume = 1 + 2.2 * (t - 1) ** 3 + 1.2 * (t - 1) ** 2      # hafif taşan yaylanma
            x, y = self._ekran(kare.kamera, birim(durak.enlem, durak.boylam))
            r = k * 1.7 * max(0.0, buyume)
            if r > 0.5:
                cizim.ellipse((x - r - SS, y - r - SS, x + r + SS, y + r + SS),
                              fill=(0, 0, 0, 120))
                cizim.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 255))
                ic = r * 0.55
                cizim.ellipse((x - ic, y - ic, x + ic, y + ic), fill=renk + (255,))
            if ayar.etiketler and durak.ad:
                saydam = round(255 * _yumusak(t))
                cizim.text((x + k * 2.6, y - k * 2.2), durak.ad, font=self.yazi,
                           fill=(255, 255, 255, saydam), anchor="ls",
                           stroke_width=round(3 * SS), stroke_fill=(0, 0, 0, round(saydam * 0.8)))

        # Rotanın ucu: yalnızca çizim sürerken.
        if noktalar and 0 < kare.ilerleme < len(self.yollar) and kare.ilerleme % 1 > 1e-6:
            x, y = noktalar[-1][-1]
            r = k * 1.25
            cizim.ellipse((x - r, y - r, x + r, y + r), fill=renk + (255,),
                          outline=(255, 255, 255, 255), width=round(SS * 2))

        # Yalnızca çizilen bölge küçültülür (kare başına en pahalı adım buydu).
        kutu = katman.getbbox()
        if kutu:
            kutu = tuple(v // SS * SS for v in kutu[:2]) + tuple(-(-v // SS) * SS for v in kutu[2:])
            parca = katman.crop(kutu).reduce(SS)
            resim.paste(parca, (kutu[0] // SS, kutu[1] // SS), mask=parca)
        if self.depo.atif:
            ImageDraw.Draw(resim).text(
                (W - 12, H - 10), self.depo.atif, font=self.atif_yazi, anchor="rs",
                fill=(225, 225, 225), stroke_width=1, stroke_fill=(30, 30, 30))
        self.sayac += 1
        return resim


# ── Üretim ────────────────────────────────────────────────────────────────────────

def gerekli_karolar(kareler, ayar, depo):
    kume = set()
    for kare in kareler:
        karolar, _ = gorunen_karolar(kare.kamera, ayar.genislik, ayar.yukseklik,
                                     depo.en_buyuk_zoom)
        for z, x, y in karolar:
            if 0 <= y < (1 << z):
                kume.add((z, x % (1 << z), y))
    return kume


def onizleme(duraklar, ayar, depo):
    """Videonun son karesi (tüm rota, genel bakış) RGB resim olarak."""
    kareler, yollar = plan_yap(duraklar, ayar, depo.en_buyuk_zoom)
    son = kareler[-1]
    depo.toplu_indir(gerekli_karolar([son], ayar, depo))
    cizici = Cizici(duraklar, yollar, ayar, depo)
    cizici.belirme = {j: -10 ** 6 for j in range(len(duraklar))}
    return cizici.ciz(son)


def video_uret(duraklar, ayar, depo, hedef, ilerleme=lambda _m: None):
    """MP4'ü üret ve yolunu döndür. `ilerleme(metin)` durum satırları alır."""
    ffmpeg = FFmpeg().ffmpeg()
    if not ffmpeg:
        raise HaritaHatasi("ffmpeg bulunamadı: KURULUM.md'deki ffmpeg adımını uygula.")
    kareler, yollar = plan_yap(duraklar, ayar, depo.en_buyuk_zoom)
    karolar = gerekli_karolar(kareler, ayar, depo)
    ilerleme(f"Harita karoları hazırlanıyor ({len(karolar)} karo)…")
    depo.toplu_indir(karolar, lambda b, t: ilerleme(f"Karolar indiriliyor: {b}/{t}"))
    if depo.hatali and depo.hatali >= len(karolar) // 2:
        raise HaritaHatasi("Harita karolarının çoğu indirilemedi; internet bağlantısını "
                           "ya da başka bir harita stilini dene.")
    W, H = ayar.genislik, ayar.yukseklik
    komut = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(ayar.fps),
             "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(hedef)]
    surec = subprocess.Popen(komut, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    cizici = Cizici(duraklar, yollar, ayar, depo)
    try:
        for i, kare in enumerate(kareler):
            surec.stdin.write(cizici.ciz(kare).tobytes())
            if i % ayar.fps == 0:
                ilerleme(f"Kareler çiziliyor: {i}/{len(kareler)} "
                         f"({len(kareler) / ayar.fps:.1f} sn video)")
        surec.stdin.close()
        with surec.stderr:
            hata = surec.stderr.read().decode("utf-8", "replace")
        surec.wait()
    except Exception:
        surec.kill()
        raise
    if surec.returncode != 0:
        raise HaritaHatasi("ffmpeg kodlaması başarısız: " + hata.strip()[:300])
    return hedef
