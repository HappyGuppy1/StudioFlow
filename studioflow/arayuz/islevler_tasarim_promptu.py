"""Araçlar › Prompt › Tasarım promptu — geri çağrı işlevleri.

Araştırma paneli (liste · Aç · Sil) Seslendirme promptu'nunkiyle aynı işlevleri kullanır
(`islevler_seslendirme_promptu.sp_*`).
"""
import gradio as gr

from studioflow.arayuz.sabitler import TASARIM_PROMPTU_IPTAL
from studioflow.cekirdek.metin import kelime_sayisi, stil_ekle
from studioflow.hikaye import kayitlar, seslendirme, tasarim
from studioflow.hikaye.yanit import Durduruldu
from studioflow.saglayicilar import gorsel_cloudflare
from studioflow.saglayicilar.metin_ortak import kisa

GUNLUK_SATIR = 30
SESLENDIRMESIZ = ("(seçme · kanca araştırmadan kurulsun)", "")


def tp_model_notu(gorsel_model):
    """Seçili görsel modelinin prompt'tan okuduğu kelime ve negatif desteği."""
    spec = gorsel_cloudflare.cf_model_spec(gorsel_model) or {}
    sinir = gorsel_cloudflare.prompt_kelime_siniri(gorsel_model)
    negatif = ("negatif prompt **destekler**" if gorsel_cloudflare.supports_negative(gorsel_model)
               else "negatif prompt **almaz** (yasaklar prompt'ta olumlu tarif edilir; negatif "
                    "yine üretilir ve SDXL için saklanır)")
    return f"**{spec.get('label', gorsel_model)}** · prompt'tan ~{sinir} kelime okur · {negatif}"


def tp_seslendirme_listesi(secili=""):
    """İlk sahnenin kancası için kayıtlı seslendirmeler (isteğe bağlı)."""
    adlar = seslendirme.SESLENDIRMELER.listele()
    return gr.update(choices=[SESLENDIRMESIZ] + [(ad, ad) for ad in adlar],
                     value=secili if secili in adlar else "")


def tp_ilk_sahne_gorunum(ilk_sahne):
    """İlk sahne kutusu işaretliyse kanca seçimi ve ilk sahne alanları görünür."""
    return gr.update(visible=bool(ilk_sahne)), gr.update(visible=bool(ilk_sahne))


def tp_onizle(stil, ilk_prompt, gorsel_model):
    """Görsel modeline gidecek hâl: stil başa eklenmiş ilk sahne (akışın yaptığı gibi)."""
    if not (ilk_prompt or "").strip():
        return ""
    sinir = gorsel_cloudflare.prompt_kelime_siniri(gorsel_model)
    tam = stil_ekle(ilk_prompt, stil, sinir)
    return f"{tam}\n\n({kelime_sayisi(tam)} / {sinir} kelime)"


def tp_uret(ad, gorsel_model, ilk_sahne, seslendirme_adi, servis, model):
    """Seçili araştırmadan stil, negatif ve (isteğe bağlı) ilk sahne prompt'larını yaz.

    Çıktılar: durum · genel · stil · negatif · ilk prompt · ilk negatif · önizleme · rehber ·
    dosyalar · ham veri yolu · önerilen ad.
    """
    TASARIM_PROMPTU_IPTAL.clear()
    gunluk = []
    bos = (gr.update(),) * 10

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
        kanca = ""
        if ilk_sahne and seslendirme_adi:
            kanca = tasarim.kanca_cumlesi(seslendirme.SESLENDIRMELER.oku(seslendirme_adi)[0])
        yazar = tasarim.TasarimYazari(ad, rapor_metni, gorsel_model, ilk_sahne, kanca, servis,
                                      model, iptal=TASARIM_PROMPTU_IPTAL)
        for satir in yazar.adimlar():
            yield (durum(satir), *bos)
    except Durduruldu:
        yield (durum("Durduruldu. Yarım kalan tasarım kaydedilmedi."), *bos)
        return
    except Exception as exc:
        yield (durum(f"Tasarım yazılamadı: {kisa(exc, 400)}"), *bos)
        return
    s = yazar.sonuc
    kontrol = "\n".join(f"{d} {a}" for d, a in yazar.kontroller)
    yield (durum(f"{kontrol}\nGözden geçir; bir ad verip **Tasarımı kaydet**'e bas."),
           s["genel"], s["stil"], s["negatif"], s["ilk_prompt"], s["ilk_negatif"],
           tp_onizle(s["stil"], s["ilk_prompt"], gorsel_model), s["rehber_metni"],
           [str(s["txt"]), str(s["json"])], str(s["json"]), s["onerilen_ad"])


def tp_durdur():
    TASARIM_PROMPTU_IPTAL.set()
    return "Durdurma istendi; sıradaki adımdan önce duracak."


# ── Tasarım kütüphanesi ────────────────────────────────────────────────────

def tp_kayit_listesi(secili=None):
    adlar = tasarim.TASARIMLAR.listele()
    return gr.update(choices=adlar, value=secili if secili in adlar else None)


def tp_kaydet(ad, genel, stil, negatif, ilk_prompt, ilk_negatif, rehber, gorsel_model, ham):
    """Ekrandaki (düzenlenmiş) tasarımı verilen adla kaydet.

    JSON anahtarları proje sayfasının içerik anahtarlarıdır (`genel`, `stil`, `negatif`,
    `ilk_prompt`, `ilk_negatif`): proje sayfasındaki **Prompt belgesi** bunları okur.
    """
    if not (genel or "").strip() and not (stil or "").strip():
        return ("Genel prompt ve stil boş; önce tasarımı üret.", gr.update(), gr.update(),
                gr.update(), gr.update())
    temiz = kayitlar.ad_temizle(ad)
    alanlar = {"genel": (genel or "").strip(), "stil": (stil or "").strip(),
               "negatif": (negatif or "").strip(),
               "ilk_prompt": (ilk_prompt or "").strip(), "ilk_negatif": (ilk_negatif or "").strip(),
               "rehber_metni": (rehber or "").strip(), "gorsel_model": gorsel_model,
               "onizleme": tp_onizle(stil, ilk_prompt, gorsel_model).split("\n\n")[0]}
    metin = tasarim.tasarim_metni(temiz or "tasarım", alanlar["genel"], alanlar["stil"],
                                  alanlar["negatif"],
                                  alanlar["ilk_prompt"], alanlar["ilk_negatif"],
                                  alanlar["rehber_metni"])
    try:
        temiz, txt, jsn, guncellendi = tasarim.TASARIMLAR.kaydet(ad, metin, ham or None, alanlar)
    except ValueError as exc:
        return str(exc), gr.update(), gr.update(), gr.update(), gr.update()
    except OSError as exc:
        return (f"Kaydedilemedi: {exc.strerror or exc}", gr.update(), gr.update(), gr.update(),
                gr.update())
    fiil = "güncellendi" if guncellendi else "kaydedildi"
    return (f"**{temiz}** {fiil} · `{txt}`", tp_kayit_listesi(temiz), gr.update(value=temiz),
            str(jsn), [str(txt), str(jsn)])


def tp_kayit_ac(ad):
    """Kayıtlı tasarımı alanlara yükle."""
    bos = (gr.update(),) * 12
    if not ad:
        return ("Listeden bir tasarım seç.", *bos)
    if not tasarim.TASARIMLAR.var_mi(ad):
        return (f"Kayıtlı tasarım bulunamadı: {ad}", *bos)
    txt, jsn = tasarim.TASARIMLAR.yollar(ad)
    v = tasarim.TASARIMLAR.veri(ad)
    ilk_var = bool(v.get("ilk_prompt"))
    gorsel_model = v.get("gorsel_model") or gr.update()
    return (f"**{ad}** açıldı. Düzenleyip aynı adla kaydedersen kayıt güncellenir.",
            v.get("genel", ""), v.get("stil", ""), v.get("negatif", ""), v.get("ilk_prompt", ""),
            v.get("ilk_negatif", ""),
            tp_onizle(v.get("stil", ""), v.get("ilk_prompt", ""), v.get("gorsel_model", "")),
            v.get("rehber_metni", ""), gr.update(value=ilk_var), gorsel_model,
            gr.update(value=ad), str(jsn), [str(y) for y in (txt, jsn) if y.is_file()])


def tp_kayit_sil(ad):
    if not ad:
        return "Listeden silinecek tasarımı seç.", gr.update()
    try:
        tasarim.TASARIMLAR.sil(ad)
    except (FileNotFoundError, OSError) as exc:
        return str(exc), gr.update()
    return f"**{ad}** silindi.", tp_kayit_listesi()
