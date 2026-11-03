"""Ekrandaki stratejiyi mevcut projeye kayıpsız uygula."""
import shutil
from datetime import datetime
from uuid import uuid4

from studioflow.proje.sahne_stratejileri import strateji_normallestir


def stratejiyi_uygula(veri, klasor, gelen):
    video = (gelen or {}).get("video") or {}
    if "sahne_stratejisi" not in video:
        return ""
    secili = strateji_normallestir(video["sahne_stratejisi"])
    kayitli = veri["ayarlar"]["video"]
    if secili == strateji_normallestir(kayitli.get("sahne_stratejisi")):
        return ""
    # Önce bütün eski görsel/video çıktıları ve tek kayıt kopyalanır. Kopyalama
    # başarısızsa aktif ayar ve sahneler değiştirilmez.
    arsiv = klasor / "surumler" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    kok = klasor.resolve()
    if not arsiv.resolve().is_relative_to(kok):
        raise ValueError("Sürüm klasörü proje dışında olamaz.")
    arsiv.mkdir(parents=True)
    for ad in ("proje.txt", "gorseller", "videolar", "proje.mp4", "proje-ham.mp4"):
        kaynak = klasor / ad
        if not kaynak.exists():
            continue
        if not kaynak.resolve().is_relative_to(kok) or kaynak.is_symlink():
            raise ValueError("Proje dışına bağlantılı üretim dosyası arşivlenemez.")
        if kaynak.is_dir():
            if any(p.is_symlink() for p in kaynak.rglob("*")):
                raise ValueError("Bağlantılı üretim klasörü arşivlenemez.")
            shutil.copytree(kaynak, arsiv / ad)
        else:
            shutil.copy2(kaynak, arsiv / ad)
    # Eski nihai video yeni stratejinin sonucuymuş gibi gösterilmesin. Güvenli
    # hedef kontrolü yukarıda yapıldı; diğer varlıkların kopyası arşivde korunur.
    for ad in ("proje.mp4", "proje-ham.mp4"):
        if (klasor / ad).is_file():
            (klasor / ad).replace(arsiv / ad)
    kayitli["sahne_stratejisi"] = secili
    for alan in ("genel", "stil", "ilk_prompt", "ilk_negatif"):
        if alan in video:
            kayitli[alan] = video[alan]
    veri["adimlar"] = []
    veri["gorsel_onay"] = "BEKLİYOR"
    veri["kanca_izi"] = ""
    veri["deneme"] = {}
    for alan in ("birlestirme", "ses_ekleme", "altyazi_ekleme", "muzik_ekleme"):
        veri[alan] = "BEKLİYOR"
        veri[alan + "_bitti"] = ""
    for alan in ("birlestirme_bicim", "birlestirme_dosya", "ham_video", "ekli_dil",
                 "ekli_dublaj", "ekli_altyazi"):
        veri[alan] = ""
    veri["muzikler"] = []
    return str(arsiv.relative_to(klasor))
