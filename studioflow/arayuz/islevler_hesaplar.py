"""API hesapları sekmesi — geri çağrı işlevleri."""
import re

import gradio as gr

from studioflow.arayuz.sabitler import API_ALANLAR
from studioflow.saglayicilar import (arama_exa, arama_tavily, buyutme_kaggle, kota_listesi,
                                     sayfa_okuma)
from studioflow.saglayicilar.hesap_havuzu import HIZMET_ADI
from studioflow.cekirdek import hatalar
from studioflow.saglayicilar.arama_ortak import AramaHatasi
from studioflow.saglayicilar.metin_ortak import kisa
from studioflow.ayarlar import api_hesaplari


def aktif_metni(hizmet):
    aktif = api_hesaplari.VARSAYILAN.aktif_hesap(hizmet)
    return f"Aktif hesap: **{aktif}**" if aktif else "Bu hizmette kayıtlı hesap yok."


def hesap_ozeti():
    """**Durum** kutusundaki hesap sayıları. Kaggle'ın kimliği hesap dosyasında değil
    `~/.kaggle/` altında da durabilir; öyleyse Kaggle "hesap yok" görünmez."""
    dis = {}
    try:
        buyutme_kaggle.kimlik_oku()
        dis["kaggle"] = "kimlik ~/.kaggle/ klasöründe"
    except Exception:
        pass
    return api_hesaplari.VARSAYILAN.ozet(dis_kimlikler=dis)


def _alan_gorunumu(hizmet, degerler):
    """Seçili hizmetin alanlarını göster, diğerlerini gizle."""
    gecerli = {ad: etiket for ad, etiket, _g in api_hesaplari.HIZMETLER[hizmet]["fields"]}
    guncellemeler = []
    for ad, etiket, _gizli in API_ALANLAR:
        if ad in gecerli:
            guncellemeler.append(gr.update(visible=True, label=gecerli[ad],
                                           value=degerler.get(ad, "")))
        else:
            guncellemeler.append(gr.update(visible=False, value=""))
    return guncellemeler


def api_servis_degisti(hizmet):
    """Hizmet seçilince hesaplarını, aktifini ve alanlarını yükle."""
    bilgi = api_hesaplari.HIZMETLER[hizmet]
    adlar = api_hesaplari.VARSAYILAN.hesap_adlari(hizmet)
    aktif = api_hesaplari.VARSAYILAN.aktif_hesap(hizmet)
    degerler = api_hesaplari.VARSAYILAN.hesap_degerleri(hizmet, aktif)
    not_metni = (f"**{bilgi['label']}** · {bilgi['kullanim']}  \n"
                 f"**Nasıl kurulur:** {bilgi['adimlar']}")
    return ([gr.update(choices=adlar, value=aktif or None), gr.update(value=""),
             gr.update(value=aktif_metni(hizmet)), gr.update(value=hesap_ozeti()),
             not_metni,
             gr.update(value=f"🔗 {bilgi['label']} · anahtar sayfasını aç", link=bilgi["link"]),
             gr.update(visible=(hizmet == "cloudflare")), gr.update(visible=(hizmet == "kaggle")),
             gr.update(visible=(hizmet in ARAMA_HIZMETLERI))]
            + _alan_gorunumu(hizmet, degerler))


def api_hesap_degisti(hizmet, ad):
    """Listeden hesap seçilince alanları o hesabın değerleriyle doldur."""
    degerler = api_hesaplari.VARSAYILAN.hesap_degerleri(hizmet, ad)
    return _alan_gorunumu(hizmet, degerler) + [gr.update(value=aktif_metni(hizmet))]


def _kaggle_esitle(hizmet, silinen=None):
    """Kaggle'ın aktif hesabını Kaggle'ın okuduğu kimlik dosyasına yaz; durum satırı döndürür.

    Hesap kalmadıysa dosya yalnızca silinen hesaba aitse kaldırılır: kullanıcının
    kendi koyduğu başka bir kimlik dosyasına dokunulmaz.
    """
    if hizmet != "kaggle":
        return ""
    degerler = api_hesaplari.VARSAYILAN.aktif_degerler("kaggle")
    kullanici, anahtar = degerler.get("kaggle_username"), degerler.get("kaggle_key")
    try:
        if anahtar:
            return f"Kaggle kimliği yazıldı: {buyutme_kaggle.kimlik_yaz(kullanici, anahtar)}\n"
        if silinen and buyutme_kaggle.kimlik_sil_eslesirse(
                silinen.get("kaggle_username"), silinen.get("kaggle_key")):
            return "Silinen Kaggle hesabının kimlik dosyası kaldırıldı.\n"
    except buyutme_kaggle.KaggleHatasi as exc:
        return f"Kaggle: {exc}\n"
    except OSError as exc:
        return f"Kaggle kimlik dosyası yazılamadı: {exc.strerror or exc}\n"
    return "Kaggle: API anahtarı boş; kimlik dosyası yazılmadı.\n" if degerler else ""


def kaggle_baglanti_testi():
    """Kaydedilmiş aktif Kaggle hesabını Kaggle'a sor (yalnızca okur, kota harcamaz)."""
    return buyutme_kaggle.baglanti_testi()


# Hikâye araştırmasının arama/okuma servisleri: API sayfasında test paneli bunlarda açılır.
ARAMA_HIZMETLERI = ("tavily", "exa", "jina")

TEST_SORGUSU = "Fall of Constantinople 1453"
TEST_SAYFASI = "https://en.wikipedia.org/wiki/Fall_of_Constantinople"


def arama_baglanti_testi(hizmet, *degerler):
    """Alandaki anahtarla (kaydetmeden) küçük bir arama/okuma dene."""
    alanlar = {ad: (deger or "").strip() for (ad, _e, _g), deger in zip(API_ALANLAR, degerler)}
    anahtar = alanlar.get(f"{hizmet}_key", "")
    if hizmet == "jina":
        metin = sayfa_okuma.jina_oku(TEST_SAYFASI, anahtar)
        if not metin:
            return "❌ Jina Reader sayfayı okuyamadı (anahtar geçersiz ya da hız sınırı)."
        kip = "anahtarla" if anahtar else "anahtarsız"
        return f"✅ Jina Reader çalışıyor ({kip}) · test sayfasından {len(metin):,} karakter okundu."
    saglayici = {"tavily": arama_tavily.VARSAYILAN, "exa": arama_exa.VARSAYILAN}.get(hizmet)
    if saglayici is None:
        return "Bu hizmet için arama testi yok."
    if not anahtar:
        return "Önce anahtar alanını doldur."
    try:
        sonuclar = saglayici.ara(TEST_SORGUSU, 2, anahtar, "en")
    except AramaHatasi as exc:
        neden = {"KOTA": "kota/kredi bitti", "YETKİ": "anahtar geçersiz"}.get(exc.tur, "hata")
        return f"❌ {api_hesaplari.HIZMETLER[hizmet]['label']} · {neden}: {kisa(exc, 200)}"
    if not sonuclar:
        return "⚠ Bağlantı kuruldu ama sonuç dönmedi."
    ilk = sonuclar[0]
    return (f"✅ {api_hesaplari.HIZMETLER[hizmet]['label']} çalışıyor · {len(sonuclar)} sonuç · "
            f"ilk: [{ilk['baslik']}]({ilk['url']}) · {len(ilk['metin']):,} karakter metin")


def _api_panel(hizmet, durum):
    adlar = api_hesaplari.VARSAYILAN.hesap_adlari(hizmet)
    aktif = api_hesaplari.VARSAYILAN.aktif_hesap(hizmet)
    degerler = api_hesaplari.VARSAYILAN.hesap_degerleri(hizmet, aktif)
    return ([gr.update(choices=adlar, value=aktif or None), gr.update(value=""),
             gr.update(value=aktif_metni(hizmet)), gr.update(value=durum)]
            + _alan_gorunumu(hizmet, degerler))


def api_kaydet(hizmet, secili, yeni_ad, *degerler):
    """Hesabı kaydet; yeni ad verilmişse onu oluştur, yoksa seçiliyi güncelle."""
    alan_adlari = [ad for ad, _e, _g in api_hesaplari.HIZMETLER[hizmet]["fields"]]
    alanlar = {ad: deger for (ad, _e, _g), deger in zip(API_ALANLAR, degerler)
               if ad in alan_adlari}
    hedef = (yeni_ad or "").strip() or (secili or "").strip() or api_hesaplari.VARSAYILAN_HESAP
    try:
        kaydedilen = api_hesaplari.VARSAYILAN.hesap_yaz(hizmet, hedef, **alanlar)
        durum = (f"Kaydedildi ve aktif yapıldı: {kaydedilen}\n" + _kaggle_esitle(hizmet)
                 + hesap_ozeti())
    except Exception as exc:
        return ([gr.update(), gr.update(), gr.update(value=aktif_metni(hizmet)),
                 gr.update(value="Kaydedilemedi: " + str(exc))] + [gr.update()] * len(API_ALANLAR))
    return _api_panel(hizmet, durum)


def api_aktif_yap(hizmet, secili):
    try:
        ad = api_hesaplari.VARSAYILAN.hesap_sec(hizmet, secili or "")
        durum = ((f"Aktif hesap: {ad}\n" if ad else "Bu hizmette kayıtlı hesap yok.\n")
                 + _kaggle_esitle(hizmet) + hesap_ozeti())
    except Exception as exc:
        return gr.update(value=aktif_metni(hizmet)), gr.update(value="Hata: " + str(exc))
    return gr.update(value=aktif_metni(hizmet)), gr.update(value=durum)


def api_sil(hizmet, secili):
    try:
        silinen = api_hesaplari.VARSAYILAN.hesap_degerleri(hizmet, api_hesaplari.ad_temizle(secili or ""))
        api_hesaplari.VARSAYILAN.hesap_sil(hizmet, secili or "")
        durum = "Hesap silindi.\n" + _kaggle_esitle(hizmet, silinen) + hesap_ozeti()
    except Exception as exc:
        return ([gr.update(), gr.update(), gr.update(value=aktif_metni(hizmet)),
                 gr.update(value="Silinemedi: " + str(exc))] + [gr.update()] * len(API_ALANLAR))
    return _api_panel(hizmet, durum)


def api_yenile(hizmet):
    """Dosya elle düzenlendiyse paneli yeniden oku."""
    return _api_panel(hizmet, "Dosyadan yeniden okundu.\n" + hesap_ozeti())


# ── Kota bekleme listesi (bkz. `saglayicilar.kota_listesi`) ─────────────────────

def kota_listesi_metni():
    """Kotası yenilenmeyi bekleyen hesaplar: hizmet, hesap, açılış saati, kalan kota."""
    kayitlar = kota_listesi.VARSAYILAN.liste()
    if not kota_listesi.VARSAYILAN.acik():
        return "Kota bekleme listesi kapalı."
    if not kayitlar:
        return "Bekleyen hesap yok: kota uyarısı veren hesap yok, hepsi kullanıma açık."
    satirlar = ["| Hizmet | Hesap | Açılış | Sebep |", "|---|---|---|---|"]
    for k in kayitlar:
        kalan = re.search(r"vs\. (\d+)s left", k.get("sebep") or "")
        dakikalik = hatalar.dakikalik_bekleme(k.get("sebep") or "") is not None
        sebep = (f"{kalan.group(1)} sn kalmıştı" if kalan
                 else "dakikalık hız sınırı" if dakikalik else "günlük kota bitti")
        satirlar.append(f"| {HIZMET_ADI.get(k['hizmet'], k['hizmet'])} | {k['ad']} | "
                        f"{kota_listesi.saat_metni(k['acilis'])} | {sebep} |")
    return (f"**{len(kayitlar)} hesap** kotasının yenilenmesini bekliyor; bu hesaplar "
            "açılış saatine kadar üretimde kullanılmaz.\n\n" + "\n".join(satirlar))


def kota_hesabi_cikar(hizmet, ad):
    """Seçili hesabı listeden çıkar (ör. kotası beklenenden erken yenilendiyse)."""
    sayi = kota_listesi.VARSAYILAN.cikar(hizmet, ad) if ad else 0
    durum = (f"'{ad}' kota bekleme listesinden çıkarıldı; bir sonraki istekte yeniden "
             "denenecek." if sayi else f"'{ad or '-'}' listede değil.")
    return kota_listesi_metni(), durum


def kota_listesini_temizle():
    sayi = kota_listesi.VARSAYILAN.cikar()
    return kota_listesi_metni(), f"Kota bekleme listesi temizlendi ({sayi} hesap çıkarıldı)."
