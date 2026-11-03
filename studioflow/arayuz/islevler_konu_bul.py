"""Araçlar › Prompt › **Video konusu bul** — geri çağrı işlevleri.

Kullanıcı aradığı konuyu kendi cümleleriyle yazar; yapay zekâ isteği alt konulara ve
platform başına arama sorgularına çevirir, YouTube Shorts (API ya da anahtarsız yt-dlp)
ve TikTok (Apify) verisi çekilir. Sonuç izlenmeye göre sıralanır, özetlenir ve
`outputs/viral/` klasörüne `.json` + `.csv` + `.txt` olarak (yani videoların **listesi**)
yazılır; liste, tabloda tıklanabilir başlıklarla ve bir **Listeyi indir** düğmesiyle sunulur.
"""
import html

import gradio as gr

from studioflow.arayuz.sabitler import KONU_BUL_IPTAL
from studioflow.hikaye.konu_bul import KonuBulucu
from studioflow.hikaye.yanit import Durduruldu
from studioflow.saglayicilar.metin_ortak import kisa
from studioflow.ayarlar import api_hesaplari

# Durum kutusunda tutulan en fazla satır: uzun aramada kutu sonsuza uzamasın.
GUNLUK_SATIR = 60

# Sonuç listesi boşken gösterilen metin (bileşen ilk değeri ve boş sonuç için ortak).
BOS_LISTE = ("<p class='sf-viral-bos'>Henüz sonuç yok. Konuyu yazıp "
             "<b>Konuları bul</b>'a bas.</p>")


def _kayitli_hesap(hizmet, alan):
    """Alanı dolu olan hesap sayısı (eksik anahtar sayılmaz)."""
    try:
        return sum(1 for ad in api_hesaplari.VARSAYILAN.hesap_adlari(hizmet)
                   if (api_hesaplari.VARSAYILAN.hesap_degerleri(hizmet, ad).get(alan) or "").strip())
    except Exception:
        return 0


def kb_kaynak_durumu(servis="gemini"):
    """Kullanılabilir arama kaynakları (tek paragraf); sekme açılınca tazelenir."""
    youtube = _kayitli_hesap("youtube", "youtube_key")
    apify = _kayitli_hesap("apify", "apify_token")
    youtube_not = (f"{youtube} YouTube API anahtarı" if youtube
                   else "YouTube anahtarı yok · anahtarsız **yt-dlp** ile aranır")
    tiktok_not = (f"{apify} Apify token'ı" if apify
                  else "Apify token'ı yok · TikTok atlanır")
    return (f"**YouTube:** {youtube_not} · `/shorts/` ile doğrulanır  \n"
            f"**TikTok:** {tiktok_not} (ücretsiz plan ~5 $/ay · ~2.900 video)  \n"
            f"**Yapay zekâ:** aktif servis **{servis}**")


def _hucre(metin):
    """Markdown tablosunda satır/kolon bozan karakterleri temizle."""
    return " ".join(str(metin or "").split()).replace("|", "/")


def _sayi(deger):
    """Rakamı binlik ayraçlı metne çevir (boş/bozuksa 0)."""
    try:
        return f"{int(deger):,}"
    except (TypeError, ValueError):
        return "0"


def kb_liste_html(videolar):
    """Videoları başlığı tıklanabilir bir HTML listesine çevir.

    Başlıklar `target="_blank"` ile **yeni sekmede** açılır; böylece video izlerken
    sonuç listesi kaybolmaz.
    """
    if not videolar:
        return BOS_LISTE
    ogeler = []
    for v in videolar:
        url = html.escape(str(v.get("url") or ""), quote=True)
        baslik = html.escape(str(v.get("baslik") or "(başlıksız)"))
        kanal = html.escape(str(v.get("kanal") or "—"))
        alt_konu = html.escape(str(v.get("alt_konu") or "—"))
        platform = html.escape(str(v.get("platform") or "—"))
        ogeler.append(
            f"<li class='sf-viral-satir'>"
            f"<a class='sf-viral-baslik' href='{url}' target='_blank' "
            f"rel='noopener noreferrer'>{baslik}</a>"
            f"<div class='sf-viral-meta'>"
            f"<span class='sf-viral-etiket'>{platform}</span>"
            f"<span>{kanal}</span><span>{_sayi(v.get('izlenme'))} izlenme</span>"
            f"<span>{alt_konu}</span></div></li>")
    return "<ol class='sf-viral-liste'>" + "".join(ogeler) + "</ol>"


def kb_ozet_metni(anlasilan, ozet, esik):
    """Anlaşılan istek ve alt konu × platform özetini Markdown tablosu yapar."""
    satirlar = [f"**Anlaşılan:** {_hucre(anlasilan)}",
                f"**Viral eşiği:** {esik:,} izlenme", "",
                "| Alt konu | Platform | Video | Viral | Medyan izlenme | En çok izlenen |",
                "| --- | --- | ---: | ---: | ---: | --- |"]
    for s in ozet or []:
        satirlar.append(
            f"| {_hucre(s['alt_konu'])} | {s['platform']} | {s['video']} | {s['viral']} | "
            f"{s['medyan']:,} | [{_hucre(s['en_cok_baslik'])[:70]}]({s['en_cok_url']}) |")
    return "\n".join(satirlar)


def kb_baslat(istek, platformlar, zaman, adet, alt_konu, esik, servis, model):
    """Aramayı yürüt; durum satırları canlı akar.

    Çıktılar: durum · özet · tıklanabilir video listesi · indirilecek metin (.txt).
    """
    KONU_BUL_IPTAL.clear()
    gunluk = []
    bos = (gr.update(),) * 3

    def durum(satir=None):
        if satir:
            gunluk.append(satir)
            del gunluk[:-GUNLUK_SATIR]
        return "\n".join(gunluk)

    istek = (istek or "").strip()
    platformlar = list(platformlar or [])
    if not istek:
        yield ("Önce aramak istediğin konuyu yaz.", *bos)
        return
    if not platformlar:
        yield ("En az bir platform seç (YouTube Shorts / TikTok).", *bos)
        return
    try:
        bulucu = KonuBulucu(istek, platformlar, zaman, adet, alt_konu, esik, servis, model,
                            iptal=KONU_BUL_IPTAL)
        for satir in bulucu.adimlar():
            yield (durum(satir), *bos)
    except Durduruldu:
        yield (durum("Durduruldu. Yarım kalan arama kaydedilmedi."), *bos)
        return
    except Exception as exc:
        yield (durum(f"Arama tamamlanamadı: {kisa(exc, 400)}"), *bos)
        return
    sonuc = bulucu.sonuc
    yield (durum("Tamamlandı. Listeyi incele; başlığa tıklayınca video yeni sekmede açılır."),
           kb_ozet_metni(sonuc["anlasilan"], sonuc["ozet"], esik),
           kb_liste_html(sonuc["videolar"]),
           str(sonuc["txt"]))


def kb_durdur():
    KONU_BUL_IPTAL.set()
    return "Durdurma istendi; sıradaki adımda duracak."
