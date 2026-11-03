"""Adım karelerinin üretimi ve stratejiye özel görsel denetim (Tarih: dönem kıyafeti ve
mekânı; Birinci kişi: bakış açısı). Genel denetim yoktur; geçmeyen kare aynı prompt'la
yeniden üretilir, hak bitince en iyi kare tutulur.
"""
from pathlib import Path

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.adim_promptlari import ILK_SAHNE_INDEX
from studioflow.proje.akis_servis import gorsel_kontrol, gorsel_uretici
from studioflow.proje.calisma_kilidi import IPTAL
from studioflow.proje.depo import adim_dosya_adi, dosya_kopyala
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.kiyafet import filtre_acik
from studioflow.proje.sabitler import GORSEL_DENETIM_DENEME, YAZI_DENEME
from studioflow.proje.sahne_kalitesi import kare_izi, plan_dogrula
from studioflow.proje.sahne_stratejileri import STRATEJI_BIRINCI_KISI, strateji_normallestir
from studioflow.proje.yeniden_deneme import adim_hesapli, dur_turu, hata_yaz
from studioflow.saglayicilar import gorsel_denetim, yazi_denetimi
from studioflow.saglayicilar.gorsel_denetim import karar_ozeti
from studioflow.saglayicilar.hesap_havuzu import aktif_kimlik, hesap_elendi, hesap_listesi


def kare_uret(veri, adim, baslik):
    """Adımın **tek** karesini hesap havuzuyla üret (dosyaya kopyalamadan).

    Üreteç: ara iletileri üretir; dönüş `("ok", geçici dosya)` · `("hata", mesaj)` ·
    `("dur", None)` (hesaplar tükendi ya da durduruldu).
    """
    for tur, deger in adim_hesapli(
            veri, adim, baslik, veri["ayarlar"]["gorsel"]["provider"],
            lambda hesap, kimlik: gorsel_uretici(veri, adim, kimlik), gorsel_kontrol):
        if tur == "bildir":
            yield deger
            continue
        if tur == "dur":
            yield deger
            return "dur", None
        kayitlar = deger[1] if deger else []
        if not kayitlar:
            return "hata", (deger[0] if deger else "Görsel dönmedi.")
        return "ok", kayitlar[0][0]
    return "hata", "Görsel dönmedi."


def hakem_kimlikleri(hizmet):
    """Hakemin deneyeceği hesaplar: aktif hesap önce, elenenler hariç.

    Uçtan uca denemede görüldü: aktif hesabın günlük nöron kotası kare üretimiyle
    dolduğunda hakem aynı hesapta takılıp kareyi "denetlenemedi" bırakıyordu, oysa
    havuzda kotası dolu olmayan ikinci bir Cloudflare hesabı vardı.
    """
    kayitlar = [kayit for kayit in hesap_listesi(hizmet) if not hesap_elendi(hizmet, kayit)]
    kimlikler = [kayit["degerler"] for kayit in kayitlar if kayit.get("degerler")]
    return kimlikler or [aktif_kimlik(hizmet) or {}]


def hakeme_sor(kimlikler, dosya, **secenek):
    """Kareyi sıradaki hesaplarla denetle; çalışan hesabı listenin başına al.

    Dönüş: `(karar ya da None, hata metinleri)`.
    """
    hatalar = []
    for sira, kimlik in enumerate(list(kimlikler)):
        karar = gorsel_denetim.VARSAYILAN.denetle(
            dosya, cf_account=kimlik.get("cf_account_id", ""),
            cf_token=kimlik.get("cf_token", ""), hatalar=hatalar, **secenek)
        if karar is not None:
            if sira:
                kimlikler.insert(0, kimlikler.pop(sira))
            return karar, hatalar
    return None, hatalar


def denetim_puani(karar):
    """Kareleri karşılaştırmak için sıralanabilir puan: geçen > çok kontrolü tutan."""
    return (karar["gecti"], karar["puan"])


def _ozel_filtreler(veri, adim):
    """Bu karede çalışacak özel filtreler: `(kıyafet analizi ya da None, pov)`.

    Dönem kıyafeti/mekânı **yalnızca Tarih**, bakış açısı **yalnızca Birinci kişi**
    stratejisinde denetlenir (05.10.2026, kullanıcı kararı). Default'ta ikisi de yoktur;
    kayıtlı eski bir analiz de hakeme verilmez (proje önce Tarih ile üretilip sonra
    Default'a geçirilmiş olabilir).
    """
    strateji = veri["ayarlar"]["video"].get("sahne_stratejisi")
    kiyafet = veri.get("kiyafet_analizi")
    if not (isinstance(kiyafet, dict) and kiyafet.get("tarihsel") is True
            and filtre_acik(strateji)):
        kiyafet = None
    pov = (strateji_normallestir(strateji) == STRATEJI_BIRINCI_KISI
           and (adim.get("sahne_plani") or {}).get("camera") == "first_person")
    return kiyafet, pov


def _video_hazir_isaretle(adim, dosya):
    """Planlı karenin videosu üretilebilir: kalite kapısı açılır, kare izi tutulur."""
    adim["kalite_durumu"] = "gecti"
    adim["hareket_izi"] = kare_izi(dosya, adim)


def kare_denetimi(veri, adim, baslik, dosya, yeniden_uret=True):
    """Kareyi stratejinin **özel filtresiyle** denetle; geçmezse yeniden üret.

    Genel denetim (nesne listesi, kolaj, çelişki, anatomi/ışık/süreklilik/hareket)
    05.10.2026'da kaldırıldı (gerekçe ve ölçüm: `gorsel_denetim` modül açıklaması).
    Yalnızca şu filtreler kalır:

    - Tarih stratejisi + tarihsel analiz → dönem kıyafeti ve dönem mekânı;
    - Birinci kişi stratejisi → bakış açısı.

    Özel filtre yoksa (Default, ya da `gorsel.denetim` kapalı) hakem çağrılmaz; planlı
    kare doğrudan videoya hazır işaretlenir ve yazılan video prompt'u kullanılır.
    Filtre varsa geçmeyen kare aynı prompt'la yeniden üretilir, `gorsel.denetim_deneme`
    hakkı bitince en iyi kare tutulur; hakem çalışmazsa planlı karenin videosu kilitli
    kalır (kullanıcının görsel onayı kilidi açar).

    `yeniden_uret=False`: yalnızca denetle, kareye ve prompt'a dokunma (tek deneme).
    Dönüş: tutulan karenin dosya yolu.
    """
    ayar = veri["ayarlar"]["gorsel"]
    planli = "sahne_plani" in adim
    if planli:
        adim["hareket_izi"] = ""
        adim["sureklilik_kare"] = ""
        adim["sureklilik_izi"] = ""
        adim["kalite_durumu"] = "denetlenemedi"
        plan_dogrula(adim["sahne_plani"], veri["ayarlar"]["video"].get("sahne_stratejisi"),
                     ilk=int(adim.get("index") or 0) == ILK_SAHNE_INDEX,
                     ozel_acilis=bool(veri["ayarlar"]["video"].get("ilk_prompt")))
    kiyafet, pov = _ozel_filtreler(veri, adim)
    if not ayar.get("denetim", True) or not gorsel_denetim.denetim_gerekli(kiyafet, pov):
        adim.pop("denetim", None)
        if planli:
            _video_hazir_isaretle(adim, dosya)
        return dosya
    toplam = int(ayar.get("denetim_deneme") or GORSEL_DENETIM_DENEME) if yeniden_uret else 1
    kimlikler = hakem_kimlikleri(ayar["provider"])
    en_iyi, deneme = None, 0
    for deneme in range(1, toplam + 1):
        yield (f"{baslik} · kare denetleniyor ({deneme}/{toplam})…" if yeniden_uret else
               f"{baslik} · kare değişmedi; yalnızca özel filtre denetimi yenileniyor…")
        karar, hatalar = hakeme_sor(kimlikler, dosya, prompt=adim["image_prompt"],
                                     kiyafet=kiyafet, pov=pov)
        if karar is None:
            if en_iyi is None:
                adim["denetim"] = "denetlenemedi"
                not_ekle(veri, f"{baslik} · kare denetlenemedi, "
                               + ("video üretimi kilitli" if planli else "denetimsiz kabul edildi")
                               + (f" ({_ilk_satir(hatalar[-1])})" if hatalar else "") + ".")
                return dosya
            break
        if en_iyi is None or denetim_puani(karar) > denetim_puani(en_iyi[0]):
            en_iyi = (karar, dosya, deneme)
        if karar["gecti"] or deneme == toplam or IPTAL.is_set():
            break
        # Hakem prompt'u yeniden yazmaz: yeni deneme aynı prompt'la yapılır (FLUX her
        # üretimde farklı kare verir). goldetest'te (29.09.2026) hakemin yazdığı prompt'lar
        # "my" sahipliğini silip birinci kişiyi bozdu.
        not_ekle(veri, f"{baslik} · denetim: {karar_ozeti(karar)} → yeniden üretiliyor "
                       f"({deneme + 1}/{toplam}, aynı prompt).")
        proje_yaz(veri)
        yield (f"{baslik} · özel filtreden geçmedi ({karar['puan']}/{karar['toplam']}); "
               "yeniden üretiliyor…")
        durum, deger = yield from kare_uret(veri, adim, baslik)
        if durum != "ok":
            not_ekle(veri, f"{baslik} · yeniden üretim yapılamadı ({_ilk_satir(deger or durum)}); "
                           "o ana kadarki en iyi kare tutuldu.")
            break
        dosya = deger
    karar, dosya, secilen = en_iyi
    adim["denetim"] = karar_ozeti(karar) + f" · deneme {secilen}/{deneme}"
    if planli:
        if karar["gecti"]:
            _video_hazir_isaretle(adim, dosya)
        else:
            adim["kalite_durumu"] = "kaldi"
    if not karar["gecti"]:
        if yeniden_uret:
            not_ekle(veri, f"{baslik} · UYARI: {deneme} denemede özel filtreden geçen kare "
                           f"çıkmadı; en iyisi tutuldu ({karar_ozeti(karar)}). Onay panelinde "
                           "bu kareye bak.")
        else:
            not_ekle(veri, f"{baslik} · yalnızca yeniden denetlendi, kare değişmedi · "
                           f"özel filtreden geçmedi ({karar_ozeti(karar)}); videosu kilitli. "
                           "Değiştirmek istersen onay panelinden yenile.")
    elif not yeniden_uret:
        not_ekle(veri, f"{baslik} · yalnızca yeniden denetlendi, kare değişmedi · geçti.")
    return dosya


def yazisiz_kare(veri, adim, baslik, dosya):
    """Karede yazı varsa yeniden üret; `YAZI_DENEME` hakkı bitince işaretle.

    Kullanıcı kararı (09.10.2026): karede hiçbir yazı kabul edilmez (bkz.
    `yazi_denetimi`). Bütün stratejilerde çalışır; `gorsel.yazi_denetimi` kapalıysa
    atlanır. Dönüş: `(tutulan kare, sorun notu)`; not boşsa kare yazısızdır ya da
    denetlenemedi (denetlenemeyen kare üretimi durdurmaz, günlüğe yazılır).
    """
    if not veri["ayarlar"]["gorsel"].get("yazi_denetimi", True):
        return dosya, ""
    for deneme in range(1, YAZI_DENEME + 1):
        yield f"{baslik} · yazı denetimi ({deneme}/{YAZI_DENEME})…"
        hatalar = []
        sonuc = yazi_denetimi.VARSAYILAN.denetle(dosya, hatalar)
        if sonuc is None:
            not_ekle(veri, f"{baslik} · yazı denetlenemedi"
                           + (f" ({_ilk_satir(hatalar[-1])})" if hatalar else "") + ".")
            return dosya, ""
        var, nerede = sonuc
        if not var:
            if deneme > 1:
                not_ekle(veri, f"{baslik} · yazısız kare {deneme}. denemede çıktı.")
            return dosya, ""
        if deneme == YAZI_DENEME:
            break
        not_ekle(veri, f"{baslik} · karede yazı var ({nerede}) → yeniden üretiliyor "
                       f"({deneme + 1}/{YAZI_DENEME}).")
        proje_yaz(veri)
        durum, deger = yield from kare_uret(veri, adim, baslik)
        if durum != "ok":
            break
        dosya = deger
    not_ekle(veri, f"{baslik} · UYARI: {YAZI_DENEME} denemede yazısız kare çıkmadı "
                   f"({nerede}); videosu kilitli. Prompt'u düzeltip kareyi yenile.")
    return dosya, f"YAZI VAR: {nerede}"


def adim_gorsel(veri, klasor, adim):
    """Adımın karesini üret, denetle ve projeye yaz. Dönüş: `"ok"` · `"hata"` · `"durdu"`."""
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])} görsel"
    yield f"{baslik} üretiliyor…"
    durum, deger = yield from kare_uret(veri, adim, baslik)
    if durum == "dur":
        return dur_turu(veri)
    if durum == "hata":
        yield hata_yaz(veri, adim, baslik, deger)
        return "hata"
    deger, yazi_notu = yield from yazisiz_kare(veri, adim, baslik, deger)
    dosya = yield from kare_denetimi(veri, adim, baslik, deger)
    if yazi_notu:
        # Yazılı kare kabul edilmez: denetim satırına yazılır, videosu kilitlenir.
        adim["denetim"] = " · ".join(x for x in (adim.get("denetim"), yazi_notu) if x)
        if "sahne_plani" in adim:
            adim["kalite_durumu"] = "kaldi"
    hedef = dosya_kopyala(dosya, klasor / adim_dosya_adi(adim, Path(dosya).suffix or ".png"))
    adim["gorsel"] = adim_dosya_adi(adim, hedef.suffix)
    denetim = f" · denetim {adim['denetim']}" if adim.get("denetim") else ""
    not_ekle(veri, f"{baslik} hazır: {adim['gorsel']}{denetim} (video bekliyor)")
    proje_yaz(veri)
    yield f"{baslik} tamam: {adim['gorsel']}"
    return "ok"


def gorsel_hazir(klasor, adim):
    """Adımın **karesi** diskte hazır mı? Video ayrı bir aşamadır (bkz. `adim_tamam`)."""
    return bool(adim.get("gorsel")) and (klasor / adim["gorsel"]).exists()
