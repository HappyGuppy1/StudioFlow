"""Araçlar › Harita animasyonu — geri çağrılar.

Duraklar çözülür (gerekirse Nominatim ile), önizleme tek kare olarak, video MP4 olarak
üretilir. Çıktı otomatik kaydetme ayarına göre `outputs/harita` ya da geçici klasöre gider.
"""
import re
import threading
import time
from queue import Empty, Queue

from studioflow.cekirdek import depolama
from studioflow.harita import animasyon
from studioflow.harita.karolar import KaroDeposu

HR_HAZIR = ("Hazır. Her satıra bir durak yaz ve **Önizle** ile son kareye bak; beğenince "
            "**Video üret**.")
HR_ORNEK = ("Aulis | 38.43, 23.59\n"
            "Truva | Hisarlık, Çanakkale\n"
            "İthaka | 38.37, 20.72")


def renk_coz(deger, varsayilan=(230, 57, 70)):
    """ColorPicker değerini (`#rrggbb` ya da `rgb(a)(…)`) RGB üçlüsüne çevir."""
    metin = str(deger or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", metin):
        return tuple(int(metin[i:i + 2], 16) for i in (1, 3, 5))
    sayilar = re.findall(r"[\d.]+", metin)
    if metin.startswith("rgb") and len(sayilar) >= 3:
        return tuple(max(0, min(255, round(float(v)))) for v in sayilar[:3])
    return varsayilan


def _hazirla(duraklar_metni, stil, cizgi, renk, bicim, bacak_suresi, fps, kamera, etiketler,
             karartma):
    genislik, yukseklik = animasyon.FORMATLAR.get(bicim, animasyon.FORMATLAR["yatay"])
    ayar = animasyon.Ayarlar(
        genislik=genislik, yukseklik=yukseklik, fps=int(fps or 30),
        bacak_suresi=float(bacak_suresi or 3), renk=renk_coz(renk),
        cizgi=cizgi if cizgi in animasyon.CIZGI_TURLERI else "kavis",
        kamera_izle=kamera == "izle", etiketler=bool(etiketler), karartma=bool(karartma))
    return animasyon.duraklari_coz(duraklar_metni), ayar, KaroDeposu(stil)


def hr_onizle(*girdiler):
    """Çıkışlar: (durum, önizleme resmi)."""
    try:
        duraklar, ayar, depo = _hazirla(*girdiler)
        resim = animasyon.onizleme(duraklar, ayar, depo)
    except animasyon.HaritaHatasi as hata:
        return f"⚠ {hata}", None
    adlar = " → ".join(d.ad or f"{d.enlem:.2f}, {d.boylam:.2f}" for d in duraklar)
    return f"Önizleme hazır (son kare): {adlar}", resim


def hr_uret(*girdiler):
    """Videoyu arka planda üret, durum satırlarını akıt. Çıkışlar: (durum, video)."""
    yield "⏳ Duraklar aranıyor…", None
    try:
        duraklar, ayar, depo = _hazirla(*girdiler)
    except animasyon.HaritaHatasi as hata:
        yield f"⚠ {hata}", None
        return
    klasor = depolama.VARSAYILAN.hedef_klasoru("harita")
    hedef = klasor / f"harita-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    mesajlar, sonuc = Queue(), {}

    def calis():
        try:
            sonuc["yol"] = animasyon.video_uret(duraklar, ayar, depo, hedef, mesajlar.put)
        except Exception as hata:
            sonuc["hata"] = hata

    is_parcacigi = threading.Thread(target=calis, daemon=True)
    is_parcacigi.start()
    while is_parcacigi.is_alive() or not mesajlar.empty():
        try:
            yield f"⏳ {mesajlar.get(timeout=0.5)}", None
        except Empty:
            continue
    if "hata" in sonuc:
        yield f"⚠ Video üretilemedi: {sonuc['hata']}", None
        return
    yield f"✅ Video hazır: {sonuc['yol']}", str(sonuc["yol"])
