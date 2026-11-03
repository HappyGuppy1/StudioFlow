"""Altyazı kayıtları: dile göre kaydedilen altyazılar, seçimi ve silinmesi.

Altyazı artık dublaja iliştirilmiş bir kutucuk değildir: her dil için **ayrı ayrı
kaydedilir** (`altyazi/<ad>.srt`) ve listede görünür; videoya gömmek üretim
sayfasındaki altyazı panelindedir. Kalıp müzik ve dublaj listeleriyle aynıdır.

Liste `altyazi/altyazilar.json`dadır:

    {"parcalar": [{"ad","dil","dosya","vtt","kaynak","blok","sure","tarih"}],
     "secim": "<ad>"}

Kayıt üç kaynaktan üretilir (`kaynak` alanı hangisi olduğunu yazar):

* **dublaj** · bir dublaj üretilirken yazılan `seslendirme-<ad>.srt` kopyalanır,
* **anlatım** · projenin kendi altyazısı (`ses/seslendirme.srt`) kopyalanır,
* **metin** · altyazı dosyası yoksa metin ve süreden kelime zamanları **tahmin
  edilerek** yazılır (hiçbir servise istek gitmez; bkz. `metinden_kaydet`).
"""
import json
import os
import shutil
from datetime import datetime

from studioflow.altyazi.bloklar import build_cues, tahmini_kelimeler, write_srt, write_vtt
from studioflow.altyazi.kural import sub_rules
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.metin import sayi as _sayi
from studioflow.proje.depo import kayit_adi
from studioflow.proje.dosya_yollari import (
    altyazi_klasoru, altyazi_liste_yolu, dil_kodu, sure_metni)

KAYNAK_ADI = {"dublaj": "dublajdan", "anlatim": "anlatımdan", "metin": "metinden"}


def altyazi_kayit_adi(deger, dil=""):
    """Altyazı adını dosya adına çevir; ad yazılmadıysa **dil kodu** kullanılır."""
    return kayit_adi(deger, "altyazi") or dil_kodu(dil)


def _kayit(ham):
    """Tek altyazı kaydını güvenli değerlere indirge."""
    return {"ad": altyazi_kayit_adi(ham.get("ad"), ham.get("dil")),
            "dil": dil_kodu(ham.get("dil")),
            "dosya": str(ham.get("dosya") or "").replace("\\", "/"),
            "vtt": str(ham.get("vtt") or "").replace("\\", "/"),
            "kaynak": str(ham.get("kaynak") or "").strip(),
            "blok": max(0, _sayi(ham.get("blok"), 0)),
            "sure": max(0.0, _sayi(ham.get("sure"), 0.0, float)),
            "tarih": str(ham.get("tarih") or "")}


def altyazi_durumu(klasor):
    """Kalıcı altyazı durumu: `{"parcalar": [...], "secim": "<ad>"}`."""
    try:
        ham = json.loads(altyazi_liste_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = {}
    if isinstance(ham, list):
        ham = {"parcalar": ham}
    if not isinstance(ham, dict):
        ham = {}
    parcalar = [_kayit(kayit) for kayit in (ham.get("parcalar") or [])
                if isinstance(kayit, dict) and (kayit.get("ad") or kayit.get("dil"))]
    parcalar = [kayit for kayit in parcalar if kayit["ad"]]
    adlar = {kayit["ad"] for kayit in parcalar}
    secim = str(ham.get("secim") or "").strip()
    return {"parcalar": parcalar, "secim": secim if secim in adlar else ""}


def altyazi_durumu_yaz(klasor, durum):
    """Altyazı durumunu diske yaz (önce geçiciye, sonra yerine)."""
    altyazi_klasoru(klasor).mkdir(parents=True, exist_ok=True)
    hedef = altyazi_liste_yolu(klasor)
    gecici = hedef.with_suffix(".gecici")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, hedef)


def altyazilari_tazele(klasor):
    """Listeyi diskle eşitle: dosyası silinmiş kayıtlar düşer (diske yazmaz)."""
    durum = altyazi_durumu(klasor)
    durum["parcalar"] = [kayit for kayit in durum["parcalar"]
                         if (klasor / kayit["dosya"]).is_file()]
    if durum["secim"] not in {kayit["ad"] for kayit in durum["parcalar"]}:
        durum["secim"] = ""
    return durum


def altyazi_kayitlari(klasor):
    """Dosyası diskte duran altyazı kayıtları (kayıt sırası korunur)."""
    return altyazilari_tazele(klasor)["parcalar"]


def altyazi_bul(klasor, isim):
    """Ada göre altyazı kaydı (yoksa None)."""
    aranan = altyazi_kayit_adi(isim)
    return next((kayit for kayit in altyazi_kayitlari(klasor) if kayit["ad"] == aranan), None)


def altyazi_yolu(klasor, kayit, alan="dosya"):
    """Kaydın dosyasının tam yolu (yoksa None)."""
    ad = (kayit or {}).get(alan) or ""
    yol = (klasor / ad) if ad else None
    return yol if yol is not None and yol.is_file() else None


def _olcu(yol):
    """Altyazı dosyasının blok sayısı ve son bitiş zamanı: `(blok, süre)`."""
    try:
        satirlar = yol.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 0.0
    zamanlar = [satir for satir in satirlar if "-->" in satir]
    if not zamanlar:
        return 0, 0.0
    son = zamanlar[-1].split("-->")[-1].strip().replace(",", ".")
    try:
        saat, dakika, saniye = son.split(":")
        sure = int(saat) * 3600 + int(dakika) * 60 + float(saniye)
    except (ValueError, IndexError):
        sure = 0.0
    return len(zamanlar), sure


def altyazi_yaz(klasor, kayit):
    """Bir altyazıyı listeye ekle ya da **aynı adlıyı güncelle**; durumu döndürür."""
    durum = altyazilari_tazele(klasor)
    yeni = _kayit(kayit)
    durum["parcalar"] = [eski for eski in durum["parcalar"]
                         if eski["ad"] != yeni["ad"]] + [yeni]
    altyazi_durumu_yaz(klasor, durum)
    return durum


def dosyadan_kaydet(klasor, kaynak_yol, ad, dil, kaynak="dublaj"):
    """Var olan bir SRT'yi `altyazi/<ad>.srt` olarak kaydet. Dönüş: `(kayıt, hata)`.

    Yanında `.vtt` varsa o da kopyalanır: indirme kutusundan ikisi de alınabilir.
    """
    isim = altyazi_kayit_adi(ad, dil)
    if not isim:
        return None, "Altyazı için bir ad ya da dil gerekiyor."
    if kaynak_yol is None or not kaynak_yol.is_file():
        return None, "Kopyalanacak altyazı dosyası bulunamadı."
    hedef_klasor = altyazi_klasoru(klasor)
    try:
        hedef_klasor.mkdir(parents=True, exist_ok=True)
        hedef = hedef_klasor / f"{isim}.srt"
        if kaynak_yol.resolve() != hedef.resolve():
            shutil.copy2(kaynak_yol, hedef)
        vtt_kaynak = kaynak_yol.with_suffix(".vtt")
        vtt = ""
        if vtt_kaynak.is_file():
            vtt_hedef = hedef_klasor / f"{isim}.vtt"
            if vtt_kaynak.resolve() != vtt_hedef.resolve():
                shutil.copy2(vtt_kaynak, vtt_hedef)
            vtt = vtt_hedef.relative_to(klasor).as_posix()
    except OSError as hata:
        return None, "Altyazı kaydedilemedi: " + str(hata).splitlines()[0][:200]
    blok, sure = _olcu(hedef)
    kayit = {"ad": isim, "dil": dil_kodu(dil), "dosya": hedef.relative_to(klasor).as_posix(),
             "vtt": vtt, "kaynak": kaynak, "blok": blok, "sure": sure,
             "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    altyazi_yaz(klasor, kayit)
    return _kayit(kayit), ""


def metinden_kaydet(klasor, metin, sure, ad, dil, ayar=None):
    """Altyazıyı **metinden** yaz: kelime zamanları uzunluğa göre tahmin edilir.

    Altyazı dosyası hiç üretilmemiş bir dil için (ör. dublaj üretilirken `Altyazı
    üret` kapalıydı) kullanılır: hiçbir servise istek gitmez, ses yeniden üretilmez.
    Bloklar projenin altyazı kurallarıyla (`ayar`) kurulur. Dönüş: `(kayıt, hata)`.
    """
    isim = altyazi_kayit_adi(ad, dil)
    if not isim:
        return None, "Altyazı için bir ad ya da dil gerekiyor."
    metin = (metin or "").strip()
    if not metin:
        return None, "Altyazı yazılacak metin yok."
    sure = max(0.0, _sayi(sure, 0.0, float))
    if sure <= 0:
        return None, ("Altyazı için süre bilinmiyor: önce bu dilin dublajını üret, "
                      "sonra altyazıyı kaydet.")
    ham = dict(ayar or {})
    kural = sub_rules(**{alan: ham.get(alan) for alan in ("line_chars", "max_lines",
                                                          "min_seconds", "max_seconds")})
    cues = build_cues(tahmini_kelimeler(metin, sure), kural)
    if not cues:
        return None, "Altyazı blokları kurulamadı; metin çok kısa olabilir."
    hedef_klasor = altyazi_klasoru(klasor)
    try:
        hedef_klasor.mkdir(parents=True, exist_ok=True)
        srt = write_srt(cues, hedef_klasor / f"{isim}.srt")
        vtt = write_vtt(cues, hedef_klasor / f"{isim}.vtt")
    except OSError as hata:
        return None, "Altyazı yazılamadı: " + str(hata).splitlines()[0][:200]
    kayit = {"ad": isim, "dil": dil_kodu(dil), "dosya": srt.relative_to(klasor).as_posix(),
             "vtt": vtt.relative_to(klasor).as_posix(), "kaynak": "metin",
             "blok": len(cues), "sure": sure,
             "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    altyazi_yaz(klasor, kayit)
    return _kayit(kayit), ""


def altyazi_kaydini_sil(klasor, isim):
    """Altyazıyı listeden ve diskten kaldır. Dönüş: `(silindi mi, kayıt)`."""
    durum = altyazilari_tazele(klasor)
    aranan = altyazi_kayit_adi(isim)
    kayit = next((oge for oge in durum["parcalar"] if oge["ad"] == aranan), None)
    if kayit is None:
        return False, None
    for alan in ("dosya", "vtt"):
        yol = altyazi_yolu(klasor, kayit, alan)
        if yol is None:
            continue
        try:
            yol.unlink()
        except OSError:
            pass
    durum["parcalar"] = [oge for oge in durum["parcalar"] if oge["ad"] != aranan]
    if durum["secim"] == aranan:
        durum["secim"] = ""
    altyazi_durumu_yaz(klasor, durum)
    return True, kayit


def altyazi_secimi_yaz(klasor, isim):
    """Üretim sayfasında seçilen altyazıyı listeye yaz; geçerli seçimi döndürür."""
    durum = altyazilari_tazele(klasor)
    aranan = altyazi_kayit_adi(isim)
    durum["secim"] = aranan if any(kayit["ad"] == aranan for kayit in durum["parcalar"]) else ""
    try:
        altyazi_durumu_yaz(klasor, durum)
    except OSError:
        pass
    return durum["secim"]


def altyazi_kayit_ozeti(kayit, ekli=False):
    """Liste satırının özeti: dil · blok sayısı · süre · kaynak · videoda mı."""
    parcalar = [LANGUAGES.get(kayit.get("dil"), kayit.get("dil") or "—")]
    if kayit.get("blok"):
        parcalar.append(f"{kayit['blok']} blok")
    if float(kayit.get("sure") or 0) > 0:
        parcalar.append(sure_metni(kayit.get("sure")))
    if kayit.get("kaynak"):
        parcalar.append(KAYNAK_ADI.get(kayit["kaynak"], kayit["kaynak"]))
    if ekli:
        parcalar.append("**videoda**")
    return " · ".join(parca for parca in parcalar if parca)


def ekli_altyazi_dosyasi(klasor, veri):
    """Videoya **gömülmüş** kayıtlı altyazının dosyası (yoksa None)."""
    ad = str((veri or {}).get("ekli_altyazi") or "").strip()
    if not ad:
        return None
    return altyazi_yolu(klasor, altyazi_bul(klasor, ad))
