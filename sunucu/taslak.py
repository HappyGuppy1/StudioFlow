"""Taslak projeler: adı verilmiş ama henüz başlatılmamış projeler.

StudioFlow'da yeni proje önce **adla** açılır; anlatım metni, prompt'lar, strateji, ses,
altyazı ve görsel ayarları ekranda doldurulur, **Projeye başlat** denince klasör kurulur
ve akış başlar. Editörde ekranın yerini taslak dosyası tutar:

    taslaklar/<ad>.json     metin, ayarlar (proje.txt AYARLAR yapısı), 🎬 sahne planı
    dosyalar/<ad>/          editöre yüklenen dosyalar (karakter görselleri, referans ses)

Taslak, proje başlatılıp `projects/<ad>/proje.txt` oluşunca kendiliğinden silinir;
yüklenen dosyalar kalır (proje kaydı onlara yol olarak bakabilir).
"""
import json
import time
from pathlib import Path

from sunucu import ayar
from studioflow.ayarlar import proje_ayarlari
from studioflow.proje import ayar_normalize, depo, on_ayarlar, yonetim

KLASOR = ayar.TASLAKLAR
VARSAYILAN_SAHNE_SURESI = 10.0
DOSYALAR = ayar.YUKLENENLER


class TaslakYok(LookupError):
    """İstenen taslak yok."""


def _yol(ad):
    ad = depo.slug(ad or "")
    if not ad:
        raise TaslakYok(ad)
    return KLASOR / f"{ad}.json"


def dosya_klasoru(ad):
    """Projeye/taslağa editörden yüklenen dosyaların kalıcı klasörü."""
    klasor = DOSYALAR / depo.slug(ad)
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def var_mi(ad):
    try:
        return _yol(ad).is_file()
    except TaslakYok:
        return False


def baslangic_ayarlari():
    """Yeni taslağın ayarları: StudioFlow'un açılışta yüklediği genel ayar dosyası, yoksa
    varsayılan ön ayar (StudioFlow arayüzünün ilk açılıştaki alanlarıyla aynı)."""
    try:
        ham = proje_ayarlari.VARSAYILAN.oku()
    except Exception:
        ham = None
    ayarlar = ayar_normalize.ayarlari_normalize(ham or {})
    if not ham:
        ayarlar["video"]["on_ayar"] = on_ayarlar.VARSAYILAN_ON_AYAR
    icerik = yonetim.icerik_varsayilanlari()
    ayarlar["video"].update(genel=icerik["genel"], ilk_prompt=icerik["ilk_prompt"],
                            ilk_negatif=icerik["ilk_negatif"])
    if icerik["stil"]:
        ayarlar["video"]["stil"] = icerik["stil"]
    ayarlar["gorsel"]["negatif"] = icerik["negatif"]
    ayarlar["video"]["karakterler"] = []
    # Editörde yeni projenin sahne süresi tavanı 10 sn (kullanıcı tercihi); ön ayar bunu değiştirmez.
    ayarlar["video"]["adim_saniye"] = VARSAYILAN_SAHNE_SURESI
    return ayarlar


def olustur(ham_ad):
    """Adı doğrula ve taslağı kur. Ad zaten bir projeyse ya da taslaksa hata."""
    if not (ham_ad or "").strip():
        raise ValueError("Proje adı gerekli.")
    ad = depo.slug(ham_ad.strip())
    if ad in depo.liste():
        raise ValueError(f"'{ad}' adında bir proje zaten var; kütüphaneden aç ya da başka ad seç.")
    if var_mi(ad):
        raise ValueError(f"'{ad}' adında bir taslak zaten var; kütüphaneden aç.")
    veri = {"ad": ad, "metin": "", "ayarlar": baslangic_ayarlari(), "sahne_on_plan": None,
            "olusturuldu": time.strftime("%Y-%m-%d %H:%M:%S")}
    yaz(veri)
    return veri


def oku(ad):
    try:
        veri = json.loads(_yol(ad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TaslakYok(ad) from None
    veri["ayarlar"] = ayar_normalize.ayarlari_normalize(veri.get("ayarlar") or {})
    veri["ayarlar"]["video"]["karakterler"] = list(
        (veri.get("ayarlar") or {}).get("video", {}).get("karakterler") or [])
    return veri


def yaz(veri):
    KLASOR.mkdir(parents=True, exist_ok=True)
    veri["guncellendi"] = time.strftime("%Y-%m-%d %H:%M:%S")
    gecici = _yol(veri["ad"]).with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(_yol(veri["ad"]))
    return veri


def sil(ad):
    try:
        _yol(ad).unlink(missing_ok=True)
    except TaslakYok:
        pass


def liste():
    """Taslakların özeti; klasörü kurulmuş (başlatılmış) taslak temizlenir."""
    if not KLASOR.is_dir():
        return []
    sonuc = []
    for yol in sorted(KLASOR.glob("*.json"), key=lambda y: y.stat().st_mtime, reverse=True):
        ad = yol.stem
        if (depo.PROJELER / ad / "proje.txt").is_file():
            yol.unlink(missing_ok=True)
            continue
        try:
            veri = oku(ad)
        except TaslakYok:
            continue
        sonuc.append(veri)
    return sonuc


def basladi_mi(ad):
    """Proje başlatıldı mı (klasörde proje.txt oluştu mu)? Oluştuysa taslak silinir."""
    if (depo.PROJELER / depo.slug(ad) / "proje.txt").is_file():
        sil(ad)
        return True
    return False


def dosya_kaydet(ad, dosya_adi, icerik, onek=""):
    """Yüklenen dosyayı `dosyalar/<ad>/` altına güvenli adla yaz; tam yolu döndür."""
    temiz = "".join(c if c.isalnum() or c in "-_." else "-" for c in Path(dosya_adi or "dosya").name)
    temiz = temiz.strip(".-") or "dosya"
    hedef = dosya_klasoru(ad) / f"{onek}{time.strftime('%H%M%S')}-{temiz}"
    hedef.write_bytes(icerik)
    return hedef
