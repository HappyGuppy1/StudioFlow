"""Ses efektleri: kayıtlar, sahne zaman çizelgesi ve videoya hizalı efekt izi.

Müzik, dublaj ve altyazı ile aynı kalıp — **kaydet**, **listele**, **videoya ekle** —
ve kaydın kendisi videodan bağımsızdır. Bir kayıt, projenin bütün sahnelerini kapsayan
**tek bir efekt izidir** (`efektler/<ad>.wav`, video uzunluğunda, 48 kHz stereo): her
sahnenin katmanları o sahnenin videodaki başlangıç anına yerleştirilmiştir. Böylece
videoya eklerken yalnızca bir ses girdisi karışıma girer ve sahne süreleri değişmedikçe
iz yeniden kurulmaz.

Durum `efektler/efektler.json`dadır: kayıtlar, videoda duyulan kayıt (`ekli`), panelde
seçili kayıt (`secim`) ve efekt seviyesi. `proje.txt` biçimine bilinçli olarak
dokunulmaz (dış sözleşme); videodaki efekt bilgisi bu dosyadan okunur.

Bu modül `muzik`i içe aktarmaz: karışımı kuran `muzik._muzigi_uygula` efekt izini
buradan okur (`ekli_efekt`). Videoya ekleme/kaldırma `efekt_ekleme`dedir.
"""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import sayi as _sayi
from studioflow.proje.depo import adim_suresi, kayit_adi, proje_adim_saniyesi
from studioflow.proje.dosya_yollari import sure_metni
from studioflow.proje.sabitler import (
    EFEKT_KATMAN_DB, EFEKT_KAYNAK_KLASORU, EFEKT_KLASORU, EFEKT_LISTE_ADI, EFEKT_SEVIYE_SINIR,
    EFEKT_VARSAYILAN_SEVIYE)

ORNEK_HIZI = 48000
YONTEM_ADLARI = {"yapay_zeka": "yapay zekâ", "manuel": "manuel"}


# ── Yollar ve kayıt adları ────────────────────────────────────────────────────────

def efekt_klasoru(klasor):
    return Path(klasor) / EFEKT_KLASORU


def efekt_liste_yolu(klasor):
    return efekt_klasoru(klasor) / EFEKT_LISTE_ADI


def efekt_kaynak_klasoru(klasor):
    return efekt_klasoru(klasor) / EFEKT_KAYNAK_KLASORU


def efekt_adi(deger):
    """Kayıt adını dosya adına çevir (boşluk `-` olur); boş kalabilir."""
    return kayit_adi(deger, "efekt")


def efekt_seviyesi(deger):
    """Efekt seviyesini doğrula (yüzde): `EFEKT_SEVIYE_SINIR` aralığına çekilir."""
    sayi = _sayi(deger, EFEKT_VARSAYILAN_SEVIYE)
    return min(max(sayi, EFEKT_SEVIYE_SINIR[0]), EFEKT_SEVIYE_SINIR[1])


# ── Kalıcı durum ──────────────────────────────────────────────────────────────────

def _kayit(ham):
    """Tek kaydı güvenli değerlere indirge (bozuk alan varsayılana düşer)."""
    return {"ad": efekt_adi(ham.get("ad")),
            "dosya": str(ham.get("dosya") or "").replace("\\", "/"),
            "yontem": ham.get("yontem") if ham.get("yontem") in YONTEM_ADLARI else "manuel",
            "sure": max(0.0, _sayi(ham.get("sure"), 0.0, float)),
            "sahneler": [s for s in (ham.get("sahneler") or []) if isinstance(s, dict)],
            "servis": str(ham.get("servis") or ""),
            "tarih": str(ham.get("tarih") or "")}


def efekt_durumu_oku(klasor):
    """`{"kayitlar": [...], "ekli": ad, "secim": ad, "seviye": %}` (dosya yoksa boş)."""
    try:
        ham = json.loads(efekt_liste_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = {}
    if not isinstance(ham, dict):
        ham = {}
    kayitlar = [_kayit(k) for k in (ham.get("kayitlar") or [])
                if isinstance(k, dict) and efekt_adi(k.get("ad"))]
    adlar = {k["ad"] for k in kayitlar}
    ekli = efekt_adi(ham.get("ekli"))
    secim = efekt_adi(ham.get("secim"))
    return {"kayitlar": kayitlar, "ekli": ekli if ekli in adlar else "",
            "secim": secim if secim in adlar else "",
            "seviye": efekt_seviyesi(ham.get("seviye"))}


def efekt_durumu_yaz(klasor, durum):
    """Durumu diske yaz (yarım dosya kalmasın diye önce geçiciye)."""
    efekt_klasoru(klasor).mkdir(parents=True, exist_ok=True)
    gecici = efekt_liste_yolu(klasor).with_suffix(".gecici")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, efekt_liste_yolu(klasor))


def efekt_kayitlari(klasor):
    """Dosyası diskte duran kayıtlar (kayıt sırasıyla)."""
    return [k for k in efekt_durumu_oku(klasor)["kayitlar"]
            if k["dosya"] and (Path(klasor) / k["dosya"]).is_file()]


def kaydi_yaz(klasor, kayit):
    """Kaydı ekle ya da aynı adlı kaydı güncelle; yeni kayıt panelde seçili olur."""
    durum = efekt_durumu_oku(klasor)
    adlar = [k["ad"] for k in durum["kayitlar"]]
    if kayit["ad"] in adlar:
        durum["kayitlar"][adlar.index(kayit["ad"])] = kayit
    else:
        durum["kayitlar"].append(kayit)
    durum["secim"] = kayit["ad"]
    efekt_durumu_yaz(klasor, durum)


def ekli_efekt(klasor):
    """Videoda duyulan efekt: `(iz dosyası, seviye %)`; ekli değilse `(None, 0)`.

    Karışımı kuran `muzik._muzigi_uygula` bunu okur; kayıt ya da dosyası silinmişse
    efekt yok sayılır (video bozuk bir yola bakmaz).
    """
    durum = efekt_durumu_oku(klasor)
    if not durum["ekli"]:
        return None, 0
    kayit = next((k for k in durum["kayitlar"] if k["ad"] == durum["ekli"]), None)
    yol = Path(klasor) / kayit["dosya"] if kayit and kayit["dosya"] else None
    if yol is None or not yol.is_file():
        return None, 0
    return yol, durum["seviye"]


def ekli_efekti_yaz(klasor, ad, seviye=None):
    """Videodaki efekt kaydını yaz (`""` = efekt yok); seviye verilirse o da yazılır."""
    durum = efekt_durumu_oku(klasor)
    durum["ekli"] = efekt_adi(ad)
    if durum["ekli"]:
        durum["secim"] = durum["ekli"]
    if seviye is not None:
        durum["seviye"] = efekt_seviyesi(seviye)
    efekt_durumu_yaz(klasor, durum)


def efekt_ozeti(kayit, ekli=False):
    """Liste satırının özeti: yöntem · sahne ve ses sayısı · süre (· videoda)."""
    sahneler = [s for s in kayit.get("sahneler") or [] if s.get("katmanlar")]
    ses = sum(len(s["katmanlar"]) for s in sahneler)
    parcalar = [YONTEM_ADLARI.get(kayit.get("yontem"), "manuel"),
                f"{len(sahneler)} sahne · {ses} ses", sure_metni(kayit.get("sure"))]
    if ekli:
        parcalar.append("🔊 videoda")
    return " · ".join(p for p in parcalar if p)


def plan_metni(kayit):
    """Kaydın sahne sahne okunur dökümü (durum kutusu ve kaynak dosyası için)."""
    satirlar = []
    for sahne in kayit.get("sahneler") or []:
        baslik = f"Sahne {sahne.get('index')}"
        if sahne.get("istek"):
            baslik += f" · istek: {sahne['istek']}"
        satirlar.append(baslik)
        katmanlar = sahne.get("katmanlar") or []
        for katman in katmanlar:
            satirlar.append(f"  • {katman.get('etiket') or katman.get('sorgu')} "
                            f"({katman.get('tur')}) → #{katman.get('id')} "
                            f"\"{katman.get('ad')}\" · {katman.get('sahip')}")
        for eksik in sahne.get("bulunamayan") or []:
            satirlar.append(f"  ✗ {eksik} · uygun CC0 ses bulunamadı")
        if not katmanlar and not sahne.get("bulunamayan"):
            satirlar.append("  (efekt yok)")
    return "\n".join(satirlar)


# ── Sahne zaman çizelgesi ─────────────────────────────────────────────────────────

def efekt_sahneleri(veri, klasor):
    """Videodaki sahneler, **videodaki** başlangıç anlarıyla.

    `birlestirme.birlestir` klibi olan adımları sırayla ve her birini kendi süresinde
    (`adim_suresi`) birleştirir; sahnenin videodaki başlangıcı bu yüzden önceki
    sahnelerin sürelerinin toplamıdır. Dönüş: `{"index", "bas", "sure", "metin",
    "video_prompt"}` listesi.
    """
    varsayilan = proje_adim_saniyesi(veri)
    sahneler, bas = [], 0.0
    for adim in veri.get("adimlar") or []:
        if not adim.get("video"):
            continue
        sure = adim_suresi(adim, varsayilan)
        sahneler.append({"index": int(_sayi(adim.get("index"), len(sahneler) + 1)),
                         "bas": round(bas, 3), "sure": sure,
                         "metin": str(adim.get("text") or "").strip(),
                         "video_prompt": str(adim.get("video_prompt") or "").strip()})
        bas += sure
    return sahneler


# ── Efekt izi ─────────────────────────────────────────────────────────────────────

def ses_oku(yol):
    """Ses dosyasını 48 kHz stereo `float32` diziye çöz (ffmpeg; mp3/wav/ogg)."""
    komut = [FFMPEG.ffmpeg() or "ffmpeg", "-v", "error", "-i", str(yol), "-f", "f32le",
             "-ac", "2", "-ar", str(ORNEK_HIZI), "-"]
    sonuc = subprocess.run(komut, capture_output=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if sonuc.returncode != 0:
        raise ValueError("ses çözülemedi: " + sonuc.stderr.decode("utf-8", "replace")[-200:])
    return np.frombuffer(sonuc.stdout, dtype=np.float32).reshape(-1, 2).copy()


def _hareketli_bolum(ses, uzunluk):
    """`uzunluk` örneklik pencereler arasında enerjisi en yüksek olanın başlangıcı."""
    if len(ses) <= uzunluk:
        return 0
    enerji = np.concatenate([[0.0], np.cumsum((ses.astype(np.float64) ** 2).mean(axis=1))])
    adim = max(1, ORNEK_HIZI // 20)
    baslar = np.arange(0, len(ses) - uzunluk + 1, adim)
    return int(baslar[np.argmax(enerji[baslar + uzunluk] - enerji[baslar])])


def _solma(parca, giris, cikis):
    n = len(parca)
    for sure, ters in ((giris, False), (cikis, True)):
        k = min(int(sure * ORNEK_HIZI), n // 3)
        if k > 1:
            egri = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
            if ters:
                parca[-k:] *= egri[::-1]
            else:
                parca[:k] *= egri
    return parca


def katman_parcasi(ses, tur, uzunluk, kazanc_db=0.0):
    """Bir sesi sahne katmanına çevir: uzunluğa getir, seviyesini ayarla, soldur.

    Ortam sesi sahne boyunca sürer (kısa kalırsa döngüye alınır, baştaki ilk saniyeler
    çoğu kayıtta kıpırtı olduğu için dosyanın dörtte birinden başlanır). Eylem sesi
    kaydın **en hareketli** bölümünden alınır ve sahneden uzun olamaz. Seviye türün
    hedef RMS'ine (`EFEKT_KATMAN_DB`) çekilir; kısa bir tepe (darbe, kopma) yalnızca bu
    katmanda yumuşak sınırlanır — bütün izi kısmaz.
    """
    uzunluk = max(1, int(uzunluk))
    if len(ses) == 0:
        return np.zeros((uzunluk, 2), dtype=np.float32)
    if tur == "ortam":
        bas = len(ses) // 4 if len(ses) > uzunluk * 1.5 else 0
        parca = ses[bas:bas + uzunluk]
        if len(parca) < uzunluk:
            parca = np.tile(ses, (int(np.ceil(uzunluk / len(ses))) + 1, 1))[:uzunluk]
        giris, cikis = 0.4, 0.4
    else:
        uzunluk = min(uzunluk, len(ses))
        bas = _hareketli_bolum(ses, uzunluk)
        parca = ses[bas:bas + uzunluk]
        giris, cikis = 0.03, 0.25
    parca = parca.astype(np.float32).copy()
    rms = float(np.sqrt(np.mean(parca.astype(np.float64) ** 2))) + 1e-9
    parca *= 10 ** ((EFEKT_KATMAN_DB.get(tur, EFEKT_KATMAN_DB["eylem"]) + kazanc_db) / 20) / rms
    parca = np.tanh(parca / 0.5) * 0.5
    return _solma(parca, giris, cikis)


def iz_kur(sahneler, katmanlar, toplam_sure):
    """Efekt izini kur: `katmanlar` = `[(sahne, tür, ses dizisi, sahne içi başlangıç
    [, kazanç dB])]`.

    Her katman sahnesinin videodaki başlangıcına (+ sahne içi başlangıç) yerleşir ve
    sahnenin sonunda biter; iz `toplam_sure` uzunluğundadır. Kazanç, elle düzenlemede
    katmana verilen seviye farkıdır (türün hedef seviyesine eklenir).
    """
    toplam = max(1, int(round(toplam_sure * ORNEK_HIZI)))
    iz = np.zeros((toplam, 2), dtype=np.float32)
    for sahne, tur, ses, ic_bas, *ek in katmanlar:
        kazanc = float(ek[0]) if ek else 0.0
        ic_bas = min(max(0.0, float(ic_bas or 0)), max(0.0, sahne["sure"] - 0.2))
        bas = int(round((sahne["bas"] + ic_bas) * ORNEK_HIZI))
        bit = min(toplam, int(round((sahne["bas"] + sahne["sure"]) * ORNEK_HIZI)))
        if bit - bas < ORNEK_HIZI // 10:
            continue
        parca = katman_parcasi(ses, tur, bit - bas, kazanc)
        iz[bas:bas + len(parca)] += parca
    # Üst üste binen katmanlar birlikte sınırı aşmasın: yalnızca tepeler yumuşatılır.
    return (np.tanh(iz / 0.9) * 0.9).astype(np.float32)


def iz_yaz(iz, hedef):
    """İzi 16 bit WAV olarak yaz (önce geçiciye)."""
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.stem + ".gecici.wav")
    sf.write(str(gecici), iz, ORNEK_HIZI, subtype="PCM_16")
    os.replace(gecici, hedef)
    return hedef


def yeni_kayit(ad, yontem, sure, sahneler, servis=""):
    return {"ad": ad, "dosya": f"{EFEKT_KLASORU}/{ad}.wav", "yontem": yontem,
            "sure": round(float(sure), 3), "sahneler": sahneler, "servis": servis,
            "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}


# ── Kayıttan yeniden kurma (elle düzenleme) ───────────────────────────────────────

ONIZLEME_KLASORU = "onizleme"
KAZANC_SINIR = (-18.0, 12.0)


def kaynak_yolu(klasor, kimlik):
    """İndirilmiş Freesound sesinin yolu (`efektler/kaynak/<id>.mp3`)."""
    return efekt_kaynak_klasoru(klasor) / f"{int(kimlik)}.mp3"


def onizleme_klasoru(klasor, isim):
    return efekt_klasoru(klasor) / ONIZLEME_KLASORU / efekt_adi(isim)


def sahne_onizleme_yolu(klasor, isim, index):
    return onizleme_klasoru(klasor, isim) / f"sahne-{int(index):02d}.wav"


def kazanc(deger):
    """Katman kazancını doğrula (dB): `KAZANC_SINIR` aralığına çekilir."""
    sayi = _sayi(deger, 0.0, float)
    return round(min(max(sayi, KAZANC_SINIR[0]), KAZANC_SINIR[1]), 1)


def kayittan_iz_kur(klasor, kayit, sahneler, getir=None, oku=None):
    """Kaydın katmanlarından izi **baştan** kur; `(iz, toplam süre, eksikler)`.

    Sesler `efektler/kaynak/`tan okunur; dosyası olmayan katman için `getir(katman)`
    çağrılır (indirir, yolu döndürür) — verilmemişse ya da indiremezse katman atlanır ve
    `eksikler`e yazılır. Zaman çizelgesi **bugünkü** sahnelerden kurulur: sahne süreleri
    değiştiyse iz yeni sürelere oturur.
    """
    oku = oku or ses_oku
    zaman = {s["index"]: s for s in sahneler}
    katmanlar, eksikler, cozulen = [], [], {}
    for sahne in kayit.get("sahneler") or []:
        hedef = zaman.get(int(_sayi(sahne.get("index"), 0)))
        if hedef is None:
            continue
        for katman in sahne.get("katmanlar") or []:
            yol = kaynak_yolu(klasor, katman["id"])
            if not yol.is_file() and getir is not None:
                try:
                    yol = Path(getir(katman))
                except Exception:
                    pass
            if not yol.is_file():
                eksikler.append(f"sahne {hedef['index']} · #{katman['id']}")
                continue
            if katman["id"] not in cozulen:
                cozulen[katman["id"]] = oku(yol)
            katmanlar.append((hedef, katman.get("tur") or "eylem", cozulen[katman["id"]],
                              katman.get("bas") or 0.0, kazanc(katman.get("kazanc"))))
    toplam = (sahneler[-1]["bas"] + sahneler[-1]["sure"]) if sahneler else 0.0
    return iz_kur(sahneler, katmanlar, toplam), toplam, eksikler


def sahne_onizlemelerini_yaz(klasor, isim, iz, sahneler):
    """İzden her sahnenin kendi parçasını ayrı WAV olarak yaz (panelde dinlemek için)."""
    hedef = onizleme_klasoru(klasor, isim)
    hedef.mkdir(parents=True, exist_ok=True)
    for eski in hedef.glob("sahne-*.wav"):
        eski.unlink(missing_ok=True)
    for sahne in sahneler:
        bas = int(round(sahne["bas"] * ORNEK_HIZI))
        bit = int(round((sahne["bas"] + sahne["sure"]) * ORNEK_HIZI))
        parca = iz[bas:bit]
        if len(parca) and float(np.abs(parca).max()) > 1e-4:
            sf.write(str(sahne_onizleme_yolu(klasor, isim, sahne["index"])), parca,
                     ORNEK_HIZI, subtype="PCM_16")
