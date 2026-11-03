"""Dublaj kayıtları: üretilen dil seslerinin listesi, seçimi ve silinmesi.

Dublajın **üretimi** `studioflow.proje.katmanlar.diller`dedir; kaydın kendisi burada durur.
Böylece müzik katmanı videoda duyulan dublajı üretim koduna bağlanmadan bulur ve
arayüz, müzik listesiyle **aynı kalıbı** kullanır: panelde kaydet, listede gör,
videoya eklemeyi üretim sayfasında yap.

Liste `ses/diller/dublajlar.json`dadır:

    {"parcalar": [{"ad","dil","dosya","altyazi","metin","provider","ses","sure","tarih"}],
     "secim": "<ad>"}

Dosyalar `ses/diller/seslendirme-<ad>.wav` adıyla durur ve **ad yazılmazsa dil
kodudur**: tek dilli eski projelerin `seslendirme-en.wav` dosyaları listeye olduğu
gibi girer (bkz. `dublajlari_tazele`). Kayıtta tutulan yollar proje klasörüne
görelidir (müzik kayıtlarında olduğu gibi).
"""
import json
import os

from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.metin import sayi as _sayi
from studioflow.proje.depo import kayit_adi
from studioflow.proje.dosya_yollari import (
    dil_dosyalari, dil_klasoru, dil_kodu, dublaj_dosyasi, dublaj_liste_yolu, sure_metni)


def dublaj_adi(deger, dil=""):
    """Dublaj adını dosya adına çevir; ad yazılmadıysa **dil kodu** kullanılır."""
    return kayit_adi(deger, "dublaj") or dil_kodu(dil)


def _kayit(ham):
    """Tek dublaj kaydını güvenli değerlere indirge (bozuk alan varsayılana düşer)."""
    return {"ad": dublaj_adi(ham.get("ad"), ham.get("dil")),
            "dil": dil_kodu(ham.get("dil")),
            "dosya": str(ham.get("dosya") or "").replace("\\", "/"),
            "altyazi": str(ham.get("altyazi") or "").replace("\\", "/"),
            "metin": str(ham.get("metin") or "").replace("\\", "/"),
            "provider": str(ham.get("provider") or "").strip(),
            "ses": str(ham.get("ses") or "").strip(),
            "sure": max(0.0, _sayi(ham.get("sure"), 0.0, float)),
            "tarih": str(ham.get("tarih") or "")}


def _varsa(klasor, ad, uzanti, on_ek="seslendirme"):
    """`ses/diller/<ön ek>-<ad><uzantı>` varsa proje klasörüne göreli yolu, yoksa boş."""
    yol = dil_klasoru(klasor) / f"{on_ek}-{ad}{uzanti}"
    return yol.relative_to(klasor).as_posix() if yol.is_file() else ""


def dublaj_durumu(klasor):
    """Kalıcı dublaj durumu: `{"parcalar": [...], "secim": "<ad>"}` (diskten okunur)."""
    try:
        ham = json.loads(dublaj_liste_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = {}
    if isinstance(ham, list):          # yalnızca kayıt listesi tutan yalın biçim
        ham = {"parcalar": ham}
    if not isinstance(ham, dict):
        ham = {}
    parcalar = [_kayit(kayit) for kayit in (ham.get("parcalar") or [])
                if isinstance(kayit, dict) and (kayit.get("ad") or kayit.get("dil"))]
    parcalar = [kayit for kayit in parcalar if kayit["ad"]]
    adlar = {kayit["ad"] for kayit in parcalar}
    secim = str(ham.get("secim") or "").strip()
    return {"parcalar": parcalar, "secim": secim if secim in adlar else ""}


def dublaj_durumu_yaz(klasor, durum):
    """Dublaj durumunu diske yaz (yarım dosya kalmasın diye önce geçiciye)."""
    dil_klasoru(klasor).mkdir(parents=True, exist_ok=True)
    hedef = dublaj_liste_yolu(klasor)
    gecici = hedef.with_suffix(".gecici")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, hedef)


def dublajlari_tazele(klasor):
    """Listeyi diskle eşitle: dosyası silinen kayıt düşer, listede olmayan dosya girer.

    Dublaj listesi olmayan **eski projeler** böylece listeli hâle gelir: daha önce
    üretilmiş `seslendirme-<dil>.wav` dosyaları dil kodu adıyla listeye girer. Dönüş
    `dublaj_durumu` ile aynı sözlüktür (diske yazmaz).
    """
    durum = dublaj_durumu(klasor)
    parcalar = [kayit for kayit in durum["parcalar"] if (klasor / kayit["dosya"]).is_file()]
    bilinen = {kayit["ad"] for kayit in parcalar}
    for kod, yol in dil_dosyalari(klasor).items():
        if kod in bilinen:
            continue
        parcalar.append(_kayit({"ad": kod, "dil": kod,
                                "dosya": yol.relative_to(klasor).as_posix(),
                                "altyazi": _varsa(klasor, kod, ".srt"),
                                "metin": _varsa(klasor, kod, ".txt", "metin")}))
    durum["parcalar"] = parcalar
    if durum["secim"] not in {kayit["ad"] for kayit in parcalar}:
        durum["secim"] = ""
    return durum


def dublaj_kayitlari(klasor):
    """Dosyası diskte duran dublaj kayıtları (kayıt sırası korunur)."""
    return dublajlari_tazele(klasor)["parcalar"]


def dublaj_bul(klasor, isim):
    """Ada göre dublaj kaydı (yoksa None)."""
    aranan = dublaj_adi(isim)
    return next((kayit for kayit in dublaj_kayitlari(klasor) if kayit["ad"] == aranan), None)


def dublaj_yolu(klasor, kayit, alan="dosya"):
    """Kaydın bir dosyasının tam yolu (yoksa None): `dosya` · `altyazi` · `metin`."""
    ad = (kayit or {}).get(alan) or ""
    yol = (klasor / ad) if ad else None
    return yol if yol is not None and yol.is_file() else None


def dublaj_yaz(klasor, kayit):
    """Bir dublajı listeye ekle ya da **aynı adlıyı güncelle**; yeni durumu döndür."""
    durum = dublajlari_tazele(klasor)
    yeni = _kayit(kayit)
    durum["parcalar"] = [eski for eski in durum["parcalar"]
                         if eski["ad"] != yeni["ad"]] + [yeni]
    dublaj_durumu_yaz(klasor, durum)
    return durum


def dublaj_kaydini_sil(klasor, isim):
    """Dublajı listeden ve diskten kaldır. Dönüş: `(silindi mi, kayıt)`."""
    durum = dublajlari_tazele(klasor)
    aranan = dublaj_adi(isim)
    kayit = next((oge for oge in durum["parcalar"] if oge["ad"] == aranan), None)
    if kayit is None:
        return False, None
    yollar = [dublaj_yolu(klasor, kayit, alan) for alan in ("dosya", "altyazi", "metin")]
    # `.vtt` kaydın alanlarında durmaz ama aynı adla üretilir; o da kalkar.
    yollar.append(dublaj_dosyasi(klasor, aranan, ".vtt"))
    for yol in yollar:
        if yol is None:
            continue
        try:
            yol.unlink()
        except OSError:
            pass
    durum["parcalar"] = [oge for oge in durum["parcalar"] if oge["ad"] != aranan]
    if durum["secim"] == aranan:
        durum["secim"] = ""
    dublaj_durumu_yaz(klasor, durum)
    return True, kayit


def dublaj_secimi_yaz(klasor, isim):
    """Üretim sayfasında seçilen dublajı listeye yaz; geçerli seçimi döndürür."""
    durum = dublajlari_tazele(klasor)
    aranan = dublaj_adi(isim)
    durum["secim"] = aranan if any(kayit["ad"] == aranan for kayit in durum["parcalar"]) else ""
    try:
        dublaj_durumu_yaz(klasor, durum)
    except OSError:
        pass
    return durum["secim"]


def dublaj_ozeti(kayit, ekli=False):
    """Liste satırının özeti: dil · süre · servis/ses · altyazı · videoda mı."""
    parcalar = [LANGUAGES.get(kayit.get("dil"), kayit.get("dil") or "—")]
    if float(kayit.get("sure") or 0) > 0:
        parcalar.append(sure_metni(kayit.get("sure")))
    if kayit.get("provider"):
        parcalar.append(kayit["provider"] + (f" · {kayit['ses']}" if kayit.get("ses") else ""))
    parcalar.append("altyazı var" if kayit.get("altyazi") else "altyazı yok")
    if ekli:
        parcalar.append("**videoda**")
    return " · ".join(parca for parca in parcalar if parca)


def ekli_dublaj_dosyasi(klasor, veri):
    """Videoya **eklenmiş** dublajın ses dosyası (yoksa None).

    `proje.txt`teki `Ekli dublaj` kaydın adını yazar; eski projelerdeki `Ekli dil`
    ise dil kodunu — ikisi de aynı dosya adlandırmasına çıkar.
    """
    for aday in ((veri or {}).get("ekli_dublaj"), (veri or {}).get("ekli_dil")):
        ad = str(aday or "").strip()
        if not ad:
            continue
        kayit = dublaj_bul(klasor, ad)
        yol = dublaj_yolu(klasor, kayit) if kayit else dublaj_dosyasi(klasor, ad, ".wav")
        if yol is not None:
            return yol
    return None
