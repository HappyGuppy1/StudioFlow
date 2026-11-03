"""Araçlar › Prompt › Seslendirme promptu — geri çağrı işlevleri (ses üretilmez, metin yazılır)."""
import gradio as gr

from studioflow.arayuz.sabitler import SESLENDIRME_PROMPTU_IPTAL
from studioflow.hikaye import kayitlar, sablonlar, seslendirme
from studioflow.hikaye.yanit import Durduruldu
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import kisa

GUNLUK_SATIR = 40

TURKCE_NOT = "Seslendirme dili Türkçe; çeviri gerekmiyor."


# ── Araştırma seçimi ───────────────────────────────────────────────────────

def sp_listesi(secili=None):
    """Kayıtlı araştırmalar (en son kaydedilen önce); seçili ad listede kalıyorsa korunur."""
    adlar = kayitlar.listele()
    return gr.update(choices=adlar, value=secili if secili in adlar else None)


def sp_arastirma_secildi(ad):
    """Listeden bir araştırmaya tıklanınca Aç / Sil düğmelerini göster."""
    return gr.update(visible=bool(ad))


def sp_arastirma_ac(ad):
    """Seçili araştırmanın raporunu önizlemede aç."""
    if not ad:
        return "", "Önce listeden bir araştırma seç."
    try:
        return kayitlar.oku(ad)[0], f"**{ad}** açıldı."
    except (FileNotFoundError, OSError) as exc:
        return "", str(exc)


def sp_arastirma_sil(ad):
    """Seçili araştırmayı kütüphaneden sil; liste, düğmeler ve önizleme tazelenir."""
    if not ad:
        return gr.update(), gr.update(), gr.update(), "Önce listeden bir araştırma seç."
    try:
        kayitlar.sil(ad)
    except (FileNotFoundError, OSError) as exc:
        return gr.update(), gr.update(), gr.update(), str(exc)
    return sp_listesi(), gr.update(visible=False), "", f"**{ad}** silindi."


# ── Şablon ─────────────────────────────────────────────────────────────────

def sp_alt_secenekleri(sablon):
    secenekler = sablonlar.alt_secenekleri(sablon)
    return gr.update(choices=secenekler, value=secenekler[0][1] if secenekler else None)


def sp_plan_ozeti(sablon, alt, sure):
    """Seçili şablonun açıklaması ve hedef süreye göre bölüm/kelime tablosu."""
    try:
        bilgi = sablonlar.alt_sablon(sablon, alt)
        plan = sablonlar.bolum_plani(sablon, alt, sure)
    except ValueError as exc:
        return str(exc)
    return f"**{bilgi['etiket']}** · {bilgi['aciklama']}\n\n{sablonlar.plan_tablosu(plan)}"


# ── Üretim ─────────────────────────────────────────────────────────────────

def sp_uret(ad, sablon, alt, sure, servis, model, dil):
    """Seçili araştırmadan seslendirme metnini bölüm bölüm yaz.

    Çıktılar: durum · metin · Türkçe önizleme · dosyalar · ham veri yolu · önerilen kayıt adı.
    """
    SESLENDIRME_PROMPTU_IPTAL.clear()
    gunluk = []
    bos = (gr.update(),) * 5

    def durum(satir=None):
        if satir:
            gunluk.append(satir)
            del gunluk[:-GUNLUK_SATIR]
        return "\n".join(gunluk)

    if not ad:
        yield ("Önce araştırma listesinden bir araştırma seç.", *bos)
        return
    try:
        rapor_metni = kayitlar.oku(ad)[0]
        yazar = seslendirme.SeslendirmeYazari(ad, rapor_metni, sablon, alt, sure, servis, model, dil,
                                              iptal=SESLENDIRME_PROMPTU_IPTAL)
        for satir in yazar.adimlar():
            yield (durum(satir), *bos)
    except Durduruldu:
        yield (durum("Durduruldu. Yarım kalan metin kaydedilmedi."), *bos)
        return
    except Exception as exc:
        yield (durum(f"Seslendirme metni yazılamadı: {kisa(exc, 400)}"), *bos)
        return
    sonuc = yazar.sonuc
    yield (durum("Metni gözden geçir; bir ad verip **Seslendirmeyi kaydet**'e bas."),
           sonuc["metin"], sonuc["ceviri"] or TURKCE_NOT,
           [str(sonuc["txt"]), str(sonuc["rapor_txt"]), str(sonuc["json"])], str(sonuc["json"]),
           sonuc["onerilen_ad"])


def sp_durdur():
    SESLENDIRME_PROMPTU_IPTAL.set()
    return "Durdurma istendi; sıradaki bölümden önce duracak."


def sp_ceviri_yenile(metin, dil, servis, model):
    """Düzenlenen metnin Türkçe önizlemesini yeniden çevir."""
    if dil == "tr":
        return TURKCE_NOT
    if not (metin or "").strip():
        return "Çevrilecek metin yok."
    try:
        return seslendirme.turkce_onizleme(HesapliMetin(servis, model), metin)
    except Exception as exc:
        return f"Çevrilemedi: {kisa(exc, 300)}"


# ── Seslendirme kütüphanesi ────────────────────────────────────────────────

def sp_kayit_listesi(secili=None):
    adlar = seslendirme.SESLENDIRMELER.listele()
    return gr.update(choices=adlar, value=secili if secili in adlar else None)


def sp_kaydet(ad, metin, ceviri, ham):
    """Ekrandaki (düzenlenmiş) seslendirme metnini verilen adla kaydet."""
    ek = {"metin": (metin or "").strip()}
    if ceviri and ceviri != TURKCE_NOT and not ceviri.startswith("Çevril"):
        ek["ceviri"] = ceviri.strip()
    try:
        temiz, txt, jsn, guncellendi = seslendirme.SESLENDIRMELER.kaydet(ad, metin, ham or None, ek)
    except ValueError as exc:
        return str(exc), gr.update(), gr.update(), gr.update(), gr.update()
    except OSError as exc:
        return (f"Kaydedilemedi: {exc.strerror or exc}", gr.update(), gr.update(), gr.update(),
                gr.update())
    fiil = "güncellendi" if guncellendi else "kaydedildi"
    return (f"**{temiz}** {fiil} · `{txt}`", sp_kayit_listesi(temiz), gr.update(value=temiz),
            str(jsn), [str(txt), str(jsn)])


def sp_kayit_ac(ad):
    """Kayıtlı seslendirmeyi düzenleyiciye yükle (metin, çeviri, dil, ad)."""
    bos = (gr.update(),) * 6
    if not ad:
        return ("Listeden bir seslendirme seç.", *bos)
    try:
        metin, txt, jsn = seslendirme.SESLENDIRMELER.oku(ad)
    except (FileNotFoundError, OSError) as exc:
        return (str(exc), *bos)
    veri = seslendirme.SESLENDIRMELER.veri(ad)
    dil = veri.get("dil") if veri.get("dil") in ("tr", "en") else "tr"
    ceviri = veri.get("ceviri") or (TURKCE_NOT if dil == "tr" else "")
    return (f"**{ad}** açıldı. Düzenleyip aynı adla kaydedersen kayıt güncellenir.",
            metin.strip(), ceviri, gr.update(value=dil), gr.update(value=ad),
            str(jsn) if jsn.is_file() else "", [str(y) for y in (txt, jsn) if y.is_file()])


def sp_kayit_sil(ad):
    if not ad:
        return "Listeden silinecek seslendirmeyi seç.", gr.update()
    try:
        seslendirme.SESLENDIRMELER.sil(ad)
    except (FileNotFoundError, OSError) as exc:
        return str(exc), gr.update()
    return f"**{ad}** silindi.", sp_kayit_listesi()
