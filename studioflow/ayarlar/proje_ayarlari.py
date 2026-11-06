"""Proje sekmesinin bütün ayarlarını tek bir **genel** dosyada saklar.

Yer: `C:\\Canlandir\\proje-ayarlari.txt` — proje klasörünün **dışında**, bu bilgisayara
özel (API anahtarları da aynı klasörde durur). Bir kez kaydettiğin seslendirme, altyazı,
görsel ve video/prompt ayarları **her yeni projede** aynen kullanılabilir; proje klasörü
kopyalansa/taşınsa bu dosya onunla gitmez.

Proje adı ve anlatım metni **kaydedilmez**: onlar içeriktir, ayar değildir.

Biçim (`#` ile başlayan satırlar açıklamadır)::

    ses.provider = edge
    gorsel.model = stable-diffusion-xl-lightning
    video.adim = 4

Uzun metinler (üslup, negatif prompt, genel video prompt'u) çok satırlı tutulur::

    video.genel <<<
    A lone astronaut drifting through a decaying orbital station. ...
    >>>

Dosya elle düzenlenebilir; uygulama her açılışta bu dosyayı okuyup alanları doldurur.
Okunan değerler `ayarlari_normalize` ile doğrulanıp sınırlandığı için bozuk ya da eksik
bir dosya uygulamayı bozmaz.

Altyazı blok ölçüleri (karakter/satır/saniye) `altyazi.preset` ile belirlenir; bu yüzden
ayrı sayı olarak kaydedilmezler. Gömme görünümü (yazı tipi, renk, kalınlık) ve **seviye**
(yazının alttan yüksekliği, tuval yüksekliğinin yüzdesi) ise `altyazi.font` ·
`altyazi.renk` · `altyazi.kalin` · `altyazi.seviye` satırlarındadır.
"""
from pathlib import Path

from studioflow.cekirdek.ayar_dosyasi import AnahtarDegerDosyasi
from studioflow.cekirdek.yollar import AYAR_KLASORU

# Kaydedilen/okunan alanlar: (bölüm, alan, tip)
#   metin: düz metin · blok: çok satırlı metin · sayi: tam sayı
#   ondalik: ondalık sayı · evet: açık/kapalı
ALANLAR = (
    ("ses", "provider", "metin"),
    ("ses", "dil", "metin"),
    ("ses", "edge_ses", "metin"),
    ("ses", "hiz", "sayi"),
    ("ses", "ton", "sayi"),
    # Seslendirmenin videodaki seviyesi (%): 100 = ses dosyasının kendi seviyesi.
    ("ses", "seviye", "sayi"),
    ("ses", "gemini_model", "metin"),
    ("ses", "gemini_ses", "metin"),
    ("ses", "exag", "ondalik"),
    ("ses", "cfg", "ondalik"),
    ("ses", "stil", "blok"),
    ("ses", "ref", "metin"),
    ("altyazi", "acik", "evet"),
    ("altyazi", "preset", "metin"),
    # Gömme görünümü: yazı tipi, rengi (#RRGGBB), kalınlığı ve **seviyesi** (yazının
    # alttan yüksekliği, tuval yüksekliğinin yüzdesi; TikTok/Shorts arayüzünün açıklama
    # satırı altyazıyı kapatmasın diye varsayılan %25).
    ("altyazi", "font", "metin"),
    ("altyazi", "renk", "metin"),
    ("altyazi", "kalin", "evet"),
    ("altyazi", "seviye", "ondalik"),
    ("gorsel", "provider", "metin"),
    ("gorsel", "model", "metin"),
    ("gorsel", "width", "sayi"),
    ("gorsel", "height", "sayi"),
    ("gorsel", "steps", "sayi"),
    ("gorsel", "guidance", "ondalik"),
    ("gorsel", "negatif", "blok"),
    # Çıktı biçimi: hedef platform + tuval ölçüsü (bkz. `ayarlar.bicimler.CIKTI_BICIMLERI`).
    # Görsel oranını, altyazı önerisini ve birleştirme tuvalini birlikte belirlediği için
    # yeni projenin ilk ayarıdır.
    ("video", "bicim", "metin"),
    # Seçili **ön ayar** ("shorts-kalite" gibi): alanların değerleri ayrıca kaydedilir,
    # bu satır listede hangi kurulumun seçili geldiğini saklar. Satır yoksa (eski
    # kayıt) liste "— elle ayarla —" gösterir.
    ("video", "on_ayar", "metin"),
    ("video", "adim", "sayi"),
    # Adım süresi üst sınırı: 0,5–10 sn (video Space'inin kendi sınırı). Sahne süreleri
    # anlatımın içeriğine göre değişir; bu değer bir sahnenin alabileceği en uzun süredir.
    ("video", "adim_saniye", "ondalik"),
    ("video", "ai", "metin"),
    ("video", "model", "metin"),
    ("video", "stil", "blok"),
    ("video", "genel", "blok"),
    ("video", "space", "metin"),
)

_TIPLER = {f"{bolum}.{alan}": tip for bolum, alan, tip in ALANLAR}

BASLIK = """# StudioFlow · genel proje ayarları
#
# Proje sekmesindeki bütün ayarlar (çıktı biçimi · seslendirme · altyazı · görsel ·
# video/prompt) bu dosyada tutulur. "Ayarları kaydet" bu dosyayı yazar; uygulama her açılışta okur.
# Proje adı ve anlatım metni buraya yazılmaz: onlar içeriktir, ayar değildir.
#
# Biçim:  bolum.alan = değer
# Uzun metinler `<<<` ve `>>>` arasında çok satırlı durur.
#
# Dosyayı elle düzenleyebilirsin; değerler okunurken doğrulanıp geçerli aralığa
# çekilir, bu yüzden bozuk bir satır uygulamayı bozmaz.
# Altyazı blok ölçüleri `altyazi.preset` ile belirlenir; gömme görünümü ve seviye
# `altyazi.font` · `altyazi.renk` · `altyazi.kalin` · `altyazi.seviye` satırlarındadır."""


# ------------------------------------------------------------------ yardımcı


def _metin(deger):
    return "" if deger is None else str(deger).strip()


def _evet(deger, varsayilan=True):
    """`açık`/`kapalı`, `evet`/`hayır`, 1/0 ve true/false değerlerini oku."""
    metin = _metin(deger).lower()
    if not metin:
        return bool(varsayilan)
    if metin in ("açık", "acik", "evet", "1", "true", "yes", "on"):
        return True
    if metin in ("kapalı", "kapali", "hayır", "hayir", "0", "false", "no", "off"):
        return False
    return bool(varsayilan)


def _sayi(deger, tip):
    """Sayıyı oku; okunamıyorsa 0. Ondalık ayraç olarak virgül de kabul edilir."""
    try:
        return tip(str(deger).strip().replace(",", "."))
    except (TypeError, ValueError):
        return tip(0)


def _deger(tip, ham):
    if tip == "evet":
        return _evet(ham)
    if tip == "sayi":
        return _sayi(ham, int)
    if tip == "ondalik":
        return _sayi(ham, float)
    return _metin(ham)


def _koy(veri, anahtar, ham, tip=None):
    """Okunan/yazılan tek alanı iç içe sözlüğe koy (bilinmeyen anahtar yok sayılır)."""
    tip = tip or _TIPLER.get(anahtar)
    if tip is None:
        return
    bolum, _, alan = anahtar.partition(".")
    veri.setdefault(bolum, {})[alan] = _deger(tip, ham)


def _ham(tip, deger):
    """Sözlükteki değeri dosyaya yazılacak metne çevir."""
    if tip == "evet":
        return "açık" if _evet(deger) else "kapalı"
    if tip == "sayi":
        return str(_sayi(deger, int))
    if tip == "ondalik":
        return f"{_sayi(deger, float):g}"
    return _metin(deger)


def _al(ayarlar, bolum, alan, varsayilan=""):
    return (ayarlar.get(bolum) or {}).get(alan, varsayilan)


class ProjeAyarlari(AnahtarDegerDosyasi):
    """`proje-ayarlari.txt` dosyasının okuyucusu/yazıcısı."""

    def __init__(self, klasor=AYAR_KLASORU):
        self.klasor = Path(klasor)
        super().__init__(self.klasor / "proje-ayarlari.txt", BASLIK)

    def kaydet(self, ayarlar):
        """Ayarları dosyaya yaz ve dosyadan geri okuyup döndür."""
        veri = ayarlar or {}
        satirlar = [BASLIK]
        for bolum, alan, tip in ALANLAR:
            deger = (veri.get(bolum) or {}).get(alan)
            if tip == "blok":
                satirlar += [f"{bolum}.{alan} <<<", _metin(deger), ">>>"]
            else:
                satirlar.append(f"{bolum}.{alan} = {_ham(tip, deger)}")
        self.satirlari_yaz(satirlar)
        return self.oku()

    def oku(self):
        """Kayıtlı ayarları oku; dosya yoksa **None** döner.

        Dönen sözlük yalnızca dosyada bulunan alanları taşır; eksikleri
        `ayarlari_normalize` varsayılanlarıyla tamamlar.
        """
        satirlar = self.satirlari_oku()
        if satirlar is None:
            return None
        veri, sira = {}, 0
        while sira < len(satirlar):
            satir = satirlar[sira]
            sira += 1
            if not satir.strip() or satir.lstrip().startswith("#"):
                continue
            if satir.rstrip().endswith("<<<"):
                anahtar = satir.replace("<<<", "").strip()
                blok = []
                while sira < len(satirlar) and satirlar[sira].strip() != ">>>":
                    blok.append(satirlar[sira])
                    sira += 1
                sira += 1                      # `>>>` satırını atla
                _koy(veri, anahtar, "\n".join(blok).strip(), "blok" if
                     _TIPLER.get(anahtar) == "blok" else None)
                continue
            anahtar, ayirac, deger = satir.partition("=")
            if ayirac:
                _koy(veri, anahtar.strip(), deger)
        return veri or None

    def ozet(self, ayarlar=None):
        """Durum satırında gösterilecek kısa, okunur özet."""
        ayarlar = self.oku() if ayarlar is None else ayarlar
        if not ayarlar:
            return (f"Kayıtlı ayar yok. **Ayarları kaydet**'e basınca bu dosya oluşur:\n{self.yol}")
        acik = _al(ayarlar, "altyazi", "acik", True)
        genel = _al(ayarlar, "video", "genel")
        satirlar = [
            # Dosyada satır yoksa biçim varsayılan ön ayardan gelir (bkz.
            # `on_ayarlar.VARSAYILAN_ON_AYAR`): dikey Shorts tuvali.
            f"Çıktı biçimi: {_al(ayarlar, 'video', 'bicim') or 'shorts-1080 (varsayılan)'}",
            f"Seslendirme : {_al(ayarlar, 'ses', 'provider')} · dil {_al(ayarlar, 'ses', 'dil')} · "
            f"hız {_al(ayarlar, 'ses', 'hiz')} · ton {_al(ayarlar, 'ses', 'ton')} · "
            f"seviye %{_al(ayarlar, 'ses', 'seviye') or 100}",
            f"Altyazı     : {'açık' if acik else 'kapalı'} · preset {_al(ayarlar, 'altyazi', 'preset')} · "
            f"{_al(ayarlar, 'altyazi', 'font') or 'Arial'} "
            f"{_al(ayarlar, 'altyazi', 'renk') or '#FFFFFF'}"
            # `seviye` satırı olmayan eski dosyada asıl varsayılan `ALTYAZI_SEVIYE`dir
            # (döngüsel içe aktarma olmasın diye burada yalnızca özet için yazılır).
            f" · seviye %{_sayi(_al(ayarlar, 'altyazi', 'seviye') or 25, float):g}"
            f"{' · kalın' if _al(ayarlar, 'altyazi', 'kalin') else ''}",
            f"Görsel      : {_al(ayarlar, 'gorsel', 'provider')} · {_al(ayarlar, 'gorsel', 'model')} · "
            f"{_al(ayarlar, 'gorsel', 'width')}×{_al(ayarlar, 'gorsel', 'height')} · "
            f"{_al(ayarlar, 'gorsel', 'steps')} adım",
            f"Video/prompt: {_al(ayarlar, 'video', 'adim')} adım · "
            f"{_al(ayarlar, 'video', 'adim_saniye')} sn/adım · {_al(ayarlar, 'video', 'ai')} · "
            f"{_al(ayarlar, 'video', 'model')}",
            f"Genel prompt: {'kayıtlı' if str(genel or '').strip() else 'boş'}",
            f"Dosya       : {self.yol}",
        ]
        return "\n".join(satirlar)


# Uygulamanın paylaşılan genel ayar dosyası.
VARSAYILAN = ProjeAyarlari()
