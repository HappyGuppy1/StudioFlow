"""İçerik: kayıtlı belgeler, 🎬 sahne planı, ses testi, karakter kadrosu ve yüklenen dosyalar.

StudioFlow'un proje sayfasındaki **Metin** bölümünün (belgeler, 🎬 Video sürelerini yapay
zekâ ayarlasın), **Seslendirme**'deki **Sesi test et**'in ve **👥 Karakterler** panelinin
karşılığı. İşlevler StudioFlow'un kendi geri çağrılarını kullanır.
"""
import copy
from pathlib import Path

from sunucu import ayar  # noqa: F401  (studioflow paketini bağlar)
from sunucu import katman, proje_ayar, taslak, uretim, veri
from studioflow.arayuz import islevler_proje, islevler_proje_belgeleri
from studioflow.cekirdek.metin import kelime_sayisi
from studioflow.hikaye import seslendirme, tasarim
from studioflow.proje import ayar_normalize, depo
from studioflow.proje import karakterler as kadro
from studioflow.proje.dosya import proje_oku, proje_yaz
from studioflow.proje.sahneleme import KELIME_HIZI
from studioflow.saglayicilar import gorsel_cloudflare


# ── Kayıtlı belgeler (Araçlar › Prompt'ta kaydedilenler) ───────────────────────
def belgeler():
    return {"seslendirme": seslendirme.SESLENDIRMELER.listele(),
            "prompt": tasarim.TASARIMLAR.listele()}


def seslendirme_belgesi(ad):
    try:
        metin = seslendirme.SESLENDIRMELER.oku(ad)[0].strip()
    except (FileNotFoundError, OSError) as hata:
        raise uretim.UretimHatasi(str(hata)) from None
    adet = kelime_sayisi(metin)
    return {"metin": metin, "not": f"{ad} anlatım metnine yüklendi · {adet} kelime "
                                   f"(~{adet / KELIME_HIZI:.0f} sn)."}


def prompt_belgesi(ad):
    if not tasarim.TASARIMLAR.var_mi(ad):
        raise uretim.UretimHatasi(f"Kayıtlı prompt belgesi bulunamadı: {ad}")
    kayit = tasarim.TASARIMLAR.veri(ad)
    hedef = {"genel": "video.genel", "stil": "video.stil", "negatif": "gorsel.negatif",
             "ilk_prompt": "video.ilk_prompt", "ilk_negatif": "video.ilk_negatif"}
    alanlar = {hedef[k]: str(kayit.get(k) or "") for k in islevler_proje_belgeleri.PROMPT_ALANLARI
               if k in kayit}
    dolu = [ad_ for ad_, k in zip(("genel prompt", "stil", "negatif", "ilk sahne (+)",
                                   "ilk sahne (−)"), islevler_proje_belgeleri.PROMPT_ALANLARI)
            if str(kayit.get(k) or "").strip()]
    return {"alanlar": alanlar, "not": f"{ad} prompt alanlarına yüklendi: {', '.join(dolu) or 'boş belge'}."}


# ── 🎬 Video sürelerini yapay zekâ ayarlasın ──────────────────────────────────
def sahne_plani(ad):
    """Anlatımı seçili strateji ve tavanla sahnelere böl (StudioFlow'un `pj_sahne_planla`ı).

    Projede plan `proje.txt`'e yazılır (kare üretilmediyse); taslakta saklanır ve proje
    başlarken akışa **aynen** verilir. Arka plan işidir; rapor işin sonucundadır.
    """
    tur, kayit = proje_ayar._kayit(ad)
    a = ayar_normalize.ayarlari_normalize(copy.deepcopy(kayit["ayarlar"]))
    metin = (kayit.get("metin") or "").strip()
    if not metin:
        raise uretim.UretimHatasi("Önce anlatım metnini yaz.")
    v, s = a["video"], a["ses"]

    def akis():
        for rapor, plan in islevler_proje.pj_sahne_planla(
                metin, v.get("ai"), v.get("model"), s.get("dil"), s.get("hiz"),
                v.get("adim_saniye"), v.get("sahne_stratejisi"), kayit["ad"] if tur == "proje" else ""):
            if plan and tur == "taslak":
                guncel = taslak.oku(ad)
                guncel["sahne_on_plan"] = plan
                taslak.yaz(guncel)
            yield (rapor.splitlines()[0] if rapor else "", rapor)

    def sonuc(paket):
        return {"rapor": paket[1]} if paket[1] and not paket[1].startswith("⏳") else None
    if tur == "proje":
        return uretim.islem(ad, "plan", "Sahne planı · video süreleri", akis, sonuc)
    return uretim._baslat(depo.slug(ad), "plan", "Sahne planı · video süreleri", akis,
                          klasor_sart=False, sonuc_al=sonuc)


# ── Ses testi (kaydedilmez) ────────────────────────────────────────────────────
def ses_testi(ad):
    """Projenin ses ayarlarıyla dilin test cümlesini oku; dinleme adresini döndür."""
    _tur, kayit = proje_ayar._kayit(ad)
    s = uretim.edge_sesini_tamamla(ayar_normalize.ayarlari_normalize(copy.deepcopy(kayit["ayarlar"])))["ses"]
    son, durum = None, ""
    for yol, mesaj in islevler_proje.pj_ses_testi(
            s["provider"], s["dil"], s.get("edge_ses") or "", s.get("gemini_ses") or "Charon",
            s.get("gemini_model") or "", s.get("stil") or "", s.get("hiz") or 0, s.get("ton") or 0,
            s.get("ref") or None, s.get("exag"), s.get("cfg")):
        son, durum = yol or son, mesaj or durum
    return {"adres": katman.gecici_adresi(son) if son else None,
            "mesaj": katman._temiz(durum) or ("Test sesi hazır." if son else "Ses üretilemedi.")}


# ── Karakter kadrosu ───────────────────────────────────────────────────────────
def _kadro_ve_klasor(ad):
    tur, kayit = proje_ayar._kayit(ad)
    liste = kadro.normalize(kayit["ayarlar"]["video"].get("karakterler") or [])
    klasor = depo.guvenli_klasor(ad) if tur == "proje" else None
    return tur, kayit, liste, klasor


def dosya_adresi(ad, yol):
    """Editör dosyası (`dosyalar/<ad>/`), proje dosyası ya da başka bir yerel dosyanın adresi."""
    if not yol:
        return None
    yol = Path(yol)
    try:
        goreli = yol.resolve().relative_to(taslak.dosya_klasoru(ad).resolve())
        return f"/dosyalar/{depo.slug(ad)}/{goreli.as_posix()}"
    except ValueError:
        pass
    klasor = depo.guvenli_klasor(ad)
    if klasor is not None and klasor.is_dir():
        hedef = yol if yol.is_absolute() else klasor / yol
        try:
            return veri.medya_adresi(ad, hedef.resolve().relative_to(klasor.resolve()).as_posix())
        except ValueError:
            pass
    return katman.gecici_adresi(yol)


def kadro_listesi(ad):
    tur, _kayit, liste, klasor = _kadro_ve_klasor(ad)
    model = _kayit["ayarlar"]["gorsel"].get("model") or ""
    return {"karakterler": [{**k, "adres": dosya_adresi(ad, kadro.mutlak_yol(k, klasor) if klasor else k["gorsel"])}
                            for k in liste],
            "azami_kare": kadro.AZAMI_KARAKTER, "azami_kadro": kadro.AZAMI_KADRO,
            "model_uygun": bool(gorsel_cloudflare.referans_siniri(model)),
            "kare_var": tur == "proje" and any(a.get("gorsel") for a in _kayit.get("adimlar") or [])}


def _kadroyu_yaz(ad, tur, kayit, yeni, klasor):
    if tur == "proje":
        if proje_ayar.calisiyor_mu(ad):
            raise uretim.UretimHatasi("Proje çalışırken kadro değiştirilmez; önce durdur.")
        try:
            # Proje kaydı görsele projeye göreli bakar: görseller proje klasörüne kopyalanır.
            mutlak = kadro.mutlak_kadro(yeni, klasor)
            kayit["ayarlar"]["video"]["karakterler"] = kadro.projeye_kopyala(mutlak, klasor) if mutlak else []
        except (OSError, ValueError) as hata:
            raise uretim.UretimHatasi(str(hata)) from None
        proje_yaz(kayit)
    else:
        kayit["ayarlar"]["video"]["karakterler"] = yeni
        taslak.yaz(kayit)


def kadro_kaydet(ad, karakter_adi, tarif, gorsel):
    tur, kayit, liste, klasor = _kadro_ve_klasor(ad)
    if klasor is not None:
        liste = kadro.mutlak_kadro(liste, klasor)
    yeni, hata = kadro.kadroya_ekle(liste, karakter_adi, tarif, gorsel)
    if hata:
        raise uretim.UretimHatasi(katman._temiz(hata))
    _kadroyu_yaz(ad, tur, kayit, yeni, klasor)
    sonuc = kadro_listesi(ad)
    notlar = []
    if not sonuc["model_uygun"]:
        notlar.append("Seçili görsel modeli referans görsel almıyor: karakterli proje için "
                      "Ayarlar › Görsel modelini FLUX.2 klein 4B yap.")
    if sonuc["kare_var"]:
        notlar.append("Bu projede kareler zaten üretildi: kadro yeni üretilen karelerde kullanılır.")
    sonuc["mesaj"] = " ".join([f"{' '.join(str(karakter_adi).split())} kadroya kaydedildi."] + notlar)
    return sonuc


def kadro_sil(ad, karakter_adi):
    tur, kayit, liste, klasor = _kadro_ve_klasor(ad)
    yeni = kadro.kadrodan_sil(liste, karakter_adi)
    if tur == "proje" and proje_ayar.calisiyor_mu(ad):
        raise uretim.UretimHatasi("Proje çalışırken kadro değiştirilmez; önce durdur.")
    kayit["ayarlar"]["video"]["karakterler"] = yeni
    if tur == "proje":
        proje_yaz(kayit)
    else:
        taslak.yaz(kayit)
    return {**kadro_listesi(ad), "mesaj": f"{karakter_adi} kadrodan çıkarıldı."}


def karakter_referansi(ad, karakter_adi, tarif):
    """✨ Tariften görsel üret: projenin stili ve modeliyle tam boy referans (kota harcar)."""
    _tur, kayit = proje_ayar._kayit(ad)
    a = kayit["ayarlar"]
    yol, mesaj = islevler_proje.pj_karakter_referans_uret(
        karakter_adi, tarif, a["video"].get("stil") or "", a["gorsel"].get("model") or "")
    if not isinstance(yol, (str, Path)) or not Path(str(yol)).is_file():
        raise uretim.UretimHatasi(katman._temiz(mesaj))
    hedef = taslak.dosya_kaydet(ad, Path(str(yol)).name, Path(str(yol)).read_bytes(), "karakter-")
    return {"yol": str(hedef), "adres": dosya_adresi(ad, hedef), "mesaj": katman._temiz(mesaj)}


# ── Yüklenen dosyalar ──────────────────────────────────────────────────────────
def yukle(ad, tur, dosya_adi, icerik):
    """Tarayıcıdan gelen dosyayı kaydet. `tur`: karakter · referans · muzik."""
    proje_ayar._kayit(ad)          # proje ya da taslak olmalı
    if not icerik:
        raise uretim.UretimHatasi("Dosya boş.")
    if len(icerik) > 200 * 1024 * 1024:
        raise uretim.UretimHatasi("Dosya çok büyük (en fazla 200 MB).")
    hedef = taslak.dosya_kaydet(ad, dosya_adi, icerik, f"{tur}-")
    sonuc = {"yol": str(hedef), "adres": dosya_adresi(ad, hedef)}
    if tur == "referans":
        proje_ayar.ayarlari_yaz(ad, {"ses.ref": str(hedef)})
    if tur == "muzik":
        sonuc.update(katman.muzik_suresi(str(hedef)))
    return sonuc
