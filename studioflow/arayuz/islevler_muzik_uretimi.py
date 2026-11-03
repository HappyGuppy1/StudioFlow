"""Yapay zekâ ile müzik üretimi — geri çağrılar (proje müzik paneli ve Araçlar › Müzik üret).

Proje panelinde üretilen müzik doğrudan kaydedilmez: **Müzik dosyası** kutusuna konur,
kullanıcı onu dinleyip her yüklenen müzik gibi kırpar, seviyesini ayarlar ve **Müziği
kaydet**'e basar. Araç sekmesinde müzik, otomatik kaydetme ayarına göre `outputs/muzik`
ya da geçici klasöre yazılır ve indirme kutusunda verilir.
"""
import gradio as gr

from studioflow.cekirdek import depolama
from studioflow.proje.depo import CALISMA_KLASORU, calismayi_temizle, guvenli_klasor
from studioflow.proje.katmanlar.muzik_uretimi import URETIM_KLASORU, muzik_uret, proje_baglami

PJ_MUZIK_YZ_HAZIR = ("Müziği tarif et (ya da boş bırak: projenin anlatımından çıkarılır) ve "
                     "**Müzik üret**'e bas. Üretilen müzik yukarıdaki dosya kutusuna gelir; "
                     "dinle, kırp ve **Müziği kaydet**.")
MU_HAZIR = "Hazır. Müziği tarif et ve **Müzik üret**'e bas."


def _satirlar():
    satirlar = []

    def ekle(metin):
        satirlar.append(metin)
        return "\n".join(satirlar[-30:])
    return ekle


def pj_muzik_yz_uret(ad, tarif, sure, bpm, servis):
    """Proje paneli. Çıkışlar: (durum, müzik dosyası, müzik adı)."""
    durum = _satirlar()
    if not (ad or "").strip():
        yield durum("Önce bir proje aç."), gr.skip(), gr.skip()
        return
    baglam = proje_baglami(ad)
    if not (tarif or "").strip() and not baglam:
        yield durum("Projenin anlatımı okunamadı; müziği kendin tarif et."), gr.skip(), gr.skip()
        return
    # Taslak müzik projenin kendi `.calisma` klasörüne yazılır (başka yere değil); her
    # yeni üretim önceki kaydedilmemiş taslağı siler.
    proje = guvenli_klasor(ad)
    if proje is None:
        yield durum("Proje klasörü bulunamadı."), gr.skip(), gr.skip()
        return
    calismayi_temizle(proje, URETIM_KLASORU)
    klasor = proje / CALISMA_KLASORU / URETIM_KLASORU
    for olay in muzik_uret(tarif, sure, bpm, klasor, baglam, servis):
        if olay[0] == "durum":
            yield durum("⏳ " + olay[1]), gr.skip(), gr.skip()
        elif olay[0] == "hata":
            yield durum("❌ " + olay[1]), gr.skip(), gr.skip()
        else:
            _tur, yol, isim, ozet = olay
            yield (durum(f"✅ Müzik üretildi ve dosya kutusuna kondu.\n{ozet}\n"
                         "Dinle → gerekirse kırp/seviye ayarla → **Müziği kaydet**. "
                         "(Çıktıda duyulmayan SynthID filigranı vardır.)"),
                   str(yol), isim)


def mu_uret(tarif, sure, bpm, servis):
    """Araçlar › Müzik üret. Çıkışlar: (durum, dinleme, indirme dosyası)."""
    durum = _satirlar()
    if not (tarif or "").strip():
        yield durum("Müziği tarif et (ör. 'eski Mısır, gizemli, ney ve darbuka')."), None, None
        return
    klasor = depolama.VARSAYILAN.hedef_klasoru("muzik")
    for olay in muzik_uret(tarif, sure, bpm, klasor, "", servis):
        if olay[0] == "durum":
            yield durum("⏳ " + olay[1]), gr.skip(), gr.skip()
        elif olay[0] == "hata":
            yield durum("❌ " + olay[1]), gr.skip(), gr.skip()
        else:
            _tur, yol, _isim, ozet = olay
            yield (durum(f"✅ Müzik üretildi: {yol}\n{ozet}\n"
                         "Telifsizdir, atıf gerekmez; duyulmayan SynthID filigranı taşır. "
                         "YouTube'da 'değiştirilmiş veya sentetik içerik' beyanını aç."),
                   str(yol), str(yol))
