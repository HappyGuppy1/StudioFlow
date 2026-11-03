"""Yapay zekâ ile müzik üretimi: Türkçe tarif → Lyria istemleri → WAV.

Kullanıcı müziği kendi dilinde tarif eder ("eski Mısır, gizemli, ney ve darbuka").
Metin yapay zekâsı (seçilen servis, en iyi model) bunu Lyria RealTime'ın en iyi
anladığı **İngilizce ağırlıklı istemlere**, bir tempoya ve kısa bir dosya adına çevirir;
müzik `muzik_lyria` ile üretilir. Yapay zekâ yanıt vermezse tarif olduğu gibi tek istem
olarak kullanılır (Lyria Türkçeyi de kısmen anlar), üretim durmaz.

Proje panelinde tarif boş bırakılırsa istemler projenin **anlatımından ve stilinden**
yazılır. Aynı akış Araçlar › Müzik üret sekmesinde projeden bağımsız çalışır.
"""
import queue
import re
import threading
from datetime import datetime
from pathlib import Path

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.json_yardim import json_nesnesi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR
from studioflow.saglayicilar.muzik_lyria import LyriaHatasi, LyriaMuzik, bpm_degeri, sure_siniri

TARIF_SISTEM = (
    "You write prompts for Google Lyria RealTime, an instrumental music generator. You get "
    "a music description (often Turkish) and sometimes the video it is for. Write 2-4 "
    "weighted English prompts: genre/mood, lead instruments (with the musical scale or "
    "mode if it fits the culture/era), rhythm/percussion, and texture/production. Only "
    "instrumental music; never name real artists, songs or copyrighted works. Weights "
    "0.5-2.0, the most important prompt highest. Suggest a tempo (bpm 60-180) that fits.\n"
    'Return ONLY JSON: {"prompts": [{"text": "...", "weight": 1.5}, ...], "bpm": 90, '
    '"name": "short-ascii-kebab-case-file-name"}')

URETIM_KLASORU = "muzik-uretim"
# Tarif boşken yapay zekâ da yanıt vermezse (kota) kullanılan genel fon müziği istemi.
YEDEK_ISTEM = "calm cinematic documentary background score, atmospheric, instrumental"


def ad_uret(metin, varsayilan="yz-muzik"):
    """Dosya adına uygun kısa ad (ASCII, kebab-case)."""
    ceviri = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")
    metin = re.sub(r"[^a-z0-9]+", "-", str(metin or "").translate(ceviri).lower()).strip("-")
    return metin[:40].strip("-") or varsayilan


def proje_baglami(ad):
    """Projenin anlatımından ve stilinden kısa müzik bağlamı; proje yoksa boş metin."""
    veri, _klasor, hata = proje_hedefi(ad, "müzik üret")
    if hata or not veri:
        return ""
    video = (veri.get("ayarlar") or {}).get("video") or {}
    anlatim = " ".join(str(veri.get("metin") or "").split())[:1500]
    return (f"Video narration: \"{anlatim}\"\nVisual style: {video.get('stil') or '-'}\n"
            "The music is quiet background under the narration.")


def _yapay_zeka(servis, ai):
    if ai is not None:
        return ai
    return HesapliMetin(servis if servis in AI_SAGLAYICILAR else "gemini",
                        bekle=lambda _saniye: None)


def tarifi_cevir(tarif, baglam="", servis="gemini", ai=None, bildir=None):
    """Tarifi Lyria istemlerine çevir: `(istemler, bpm|None, ad, mesaj)`.

    Yapay zekâ yanıt vermezse tarif tek istem olarak döner (bpm modele kalır); tarif de
    boşsa genel fon müziği istemi (`YEDEK_ISTEM`) kullanılır.
    """
    tarif = " ".join(str(tarif or "").split())
    kullanici = (f"Music description: \"{tarif or 'fits the video'}\"\n" + (baglam or ""))
    try:
        plan = json_nesnesi(_yapay_zeka(servis, ai).metin(TARIF_SISTEM, kullanici,
                                                          json_modu=True, bildir=bildir)) or {}
        istemler = [{"text": str(i.get("text") or ""), "weight": i.get("weight", 1.0)}
                    for i in plan.get("prompts") or [] if isinstance(i, dict)]
        istemler = [i for i in istemler if i["text"].strip()]
        if not istemler:
            raise ValueError("istem yazılmadı")
        return (istemler, bpm_degeri(plan.get("bpm")), ad_uret(plan.get("name") or tarif),
                "🤖 Tarif Lyria istemlerine çevrildi.")
    except Exception as exc:
        if not tarif:
            return ([{"text": YEDEK_ISTEM, "weight": 1.0}], None, "fon-muzigi",
                    f"Yapay zekâ projeden tarif çıkaramadı ({_ilk_satir(exc, 80)}); genel "
                    "belgesel fonu üretiliyor. Daha iyisi için müziği kendin tarif et.")
        return ([{"text": tarif, "weight": 1.0}], None, ad_uret(tarif),
                f"Yapay zekâ yanıt vermedi ({_ilk_satir(exc, 80)}); tarif olduğu gibi kullanıldı.")


def istem_ozeti(istemler, bpm):
    satirlar = [f"  • {i['text']} (ağırlık {float(i['weight']):g})" for i in istemler]
    return "\n".join(satirlar + [f"  • tempo: {bpm} BPM" if bpm else "  • tempo: model seçer"])


def muzik_uret(tarif, sure, bpm, klasor, baglam="", servis="gemini", ai=None, lyria=None):
    """Üretim akışı (üreteç): `("durum", metin)` … sonra `("bitti", yol, ad, özet)` ya da
    `("hata", metin)`.

    `bpm` 0 ise yapay zekânın önerdiği tempo kullanılır (o da yoksa model seçer).
    Lyria müziği gerçek zamanlı akıttığı için üretim ayrı iş parçacığında yürür ve
    durum satırları bekletilmeden iletilir.
    """
    kuyruk = queue.Queue()
    bildir = lambda mesaj: kuyruk.put(("durum", mesaj))

    def calis():
        try:
            if not (lyria or LyriaMuzik()).anahtar_var_mi():
                raise LyriaHatasi("Gemini anahtarı yok: **API hesapları** sekmesinden ekle.")
            bildir("Tarif yapay zekâyla Lyria istemlerine çevriliyor…")
            istemler, onerilen, ad, mesaj = tarifi_cevir(tarif, baglam, servis, ai, bildir)
            tempo = bpm_degeri(bpm) or onerilen
            saniye = sure_siniri(sure)
            ozet = istem_ozeti(istemler, tempo)
            bildir(mesaj + "\n" + ozet)
            bildir(f"Lyria RealTime ile {saniye} sn müzik üretiliyor (gerçek zamanlı: "
                   f"yaklaşık {saniye} sn sürer)…")
            hedef = Path(klasor) / f"{datetime.now():%Y%m%d-%H%M%S}-{ad}.wav"
            motor = lyria or LyriaMuzik()
            yol = motor.uret(istemler, saniye, hedef, tempo, bildir)
            kuyruk.put(("bitti", yol, ad, f"Hesap: '{motor.kullanilan}'\n{ozet}"))
        except Exception as exc:
            kuyruk.put(("hata", str(exc) if isinstance(exc, LyriaHatasi)
                        else f"{type(exc).__name__}: {_ilk_satir(exc, 200)}"))

    is_parcacigi = threading.Thread(target=calis, daemon=True)
    is_parcacigi.start()
    while True:
        try:
            olay = kuyruk.get(timeout=0.5)
        except queue.Empty:
            if not is_parcacigi.is_alive() and kuyruk.empty():
                yield ("hata", "Üretim beklenmedik biçimde durdu.")
                return
            continue
        yield olay
        if olay[0] in ("bitti", "hata"):
            return
