"""Araçlar › Ses efekti üret — geri çağrılar.

Proje panelindeki yapay zekâlı aramanın projeden bağımsız hâli: istek (Türkçe olabilir)
yapay zekâyla Freesound sorgularına çevrilir, yalnızca **CC0** (atıfsız, ticari serbest)
kayıtlar aranır ve isteğe uyanlar en iyisinden sıralanır. Sesler dinlenir, beğenilen
indirilir (otomatik kaydetme ayarına göre `outputs/efektler` ya da geçici klasör).
Yapay zekâ yanıt vermezse istek olduğu gibi kelime aramasına gider.
"""
import html

import gradio as gr

from studioflow.cekirdek import depolama
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.katmanlar.efekt_duzenleme import alakaya_gore, yz_adaylari
from studioflow.proje.katmanlar.efekt_hazirlama import adaylari_topla
from studioflow.proje.katmanlar.muzik_uretimi import ad_uret
from studioflow.saglayicilar.efekt_freesound import FreesoundEfekt, FreesoundHatasi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR, AI_VARSAYILAN

ADAY_SINIRI = 8               # panelde gösterilen en fazla ses

EF_HAZIR = ("Hazır. Ne sesi istediğini yaz (ör. 'kumda yavaş ayak sesi') ve **Ses bul**'a bas. "
            "Freesound anahtarı **API hesapları** sekmesindedir.")


def ef_bul(istek, tur, sure, servis):
    """Çıkışlar: (durum, aday listesi). Önce bekleme satırı gelir: arama Freesound'un
    dakikalık sınırı yüzünden 30-60 sn sürebilir."""
    istek = " ".join(str(istek or "").split())
    if not istek:
        yield "Ne sesi istediğini yaz (ör. 'taş yuvarlanıp düşüyor').", []
        return
    freesound = FreesoundEfekt()
    if not freesound.anahtar_var_mi():
        yield "Freesound anahtarı yok: **API hesapları** sekmesinden ekle.", []
        return
    yield ("⏳ Yapay zekâ isteği kütüphane aramalarına çeviriyor; CC0 sesler toplanıp "
           "sıralanıyor (30-60 sn sürebilir)…"), []
    yield _ara(istek, tur, sure, servis, freesound)


def _ara(istek, tur, sure, servis, freesound):
    """Arama ve sıralama: `(durum, adaylar)`."""
    sure = float(sure or 5)
    baglam = (f"User request: \"{istek}\"\nSound type: {tur}\n"
              f"Wanted length: about {sure:g} seconds")
    ai = HesapliMetin(servis if servis in AI_SAGLAYICILAR else AI_VARSAYILAN,
                      bekle=lambda _saniye: None)
    try:
        adaylar, mesaj = yz_adaylari(ai, baglam, tur, sure, freesound)
    except FreesoundHatasi as exc:
        return str(exc), []
    except Exception as exc:
        try:
            adaylar = alakaya_gore(adaylari_topla(
                freesound, {"tur": tur, "sorgu": istek, "yedek_sorgu": ""}, sure, 16), istek)
        except FreesoundHatasi as hata:
            return str(hata), []
        mesaj = (f"Yapay zekâ yanıt vermedi ({_ilk_satir(exc, 60)}); '{istek}' kelime "
                 f"aramasıyla {len(adaylar)} ses bulundu (İngilizce yazmak daha iyi sonuç verir).")
    return mesaj, adaylar[:ADAY_SINIRI]


def aday_html(aday):
    """Adayın başlığı, bilgisi ve tarayıcıda çalan önizlemesi."""
    ad = html.escape(aday.get("ad") or f"#{aday.get('id')}")
    etiket = html.escape(", ".join((aday.get("etiketler") or [])[:5]))
    return (f"<div class='sf-ef-aday'><b>{ad}</b> · {aday.get('sure', 0):.1f} sn · CC0 · "
            f"<a href='{html.escape(aday.get('url') or '')}' target='_blank'>Freesound</a> "
            f"({html.escape(aday.get('sahip') or '')})<br><small>{etiket}</small><br>"
            f"<audio controls preload='none' style='width:100%' "
            f"src='{html.escape(aday.get('onizleme') or '')}'></audio></div>")


def ef_indir(aday):
    """Önizlemeyi (yüksek kaliteli MP3) indir. Çıkışlar: (durum, dosya)."""
    klasor = depolama.VARSAYILAN.hedef_klasoru("efektler")
    hedef = klasor / f"{aday['id']}-{ad_uret(aday.get('ad'), 'efekt')}.mp3"
    try:
        yol = FreesoundEfekt().indir(aday, hedef)
    except FreesoundHatasi as exc:
        return str(exc), gr.skip()
    return (f"✅ İndirildi: {yol}\nCC0: atıf gerekmez, ticari kullanım serbest.", str(yol))
