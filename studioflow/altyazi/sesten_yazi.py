"""Sesten yazıya: video/ses dosyasını metne ve isteğe bağlı zamanlı altyazıya (SRT) dök.

Akış:

1. Dosyanın sesi ~`PARCA_SANIYE`'lik parçalara **sessiz noktalardan** bölünür (ffmpeg
   `silencedetect`); kelime ortasından kesilmez. Kısa parçalar modelin cümle atlama
   riskini düşürür ve tek bir kotalı hesabın bütün işi düşürmesini önler.
2. Her parça Gemini ile yazıya dökülür (`saglayicilar.yazi_gemini`). Hesaplar sırayla
   denenir: dakikalık sınırda sıradakine geçilir (hepsi sınırdaysa beklenir), günlük kota
   ya da yetki hatası veren hesap elenir, 503 "yoğunluk" hatasında sıradakine geçilir.
3. Zamanlı kipte kelime zamanları parçanın başlangıcı kadar kaydırılır, bozuk zamanlar
   düzeltilir, dolgu sözcükleri ayıklanır; metin ve SRT **aynı kelime listesinden**
   kurulur ki ikisi birbirini tutsun.

14.10.2026'da 27,5 dakikalık bir uygulama tanıtım videosuyla denendi: 6 parça, kelime
zamanları sesteki gerçek sessizliklerle karşılaştırıldı (3.159 kelimeden hiçbiri bir
sessizliğe düşmedi).
"""
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from studioflow.altyazi.bloklar import build_subtitles
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.hatalar import dakikalik_bekleme, hata_etiketle, ses_hatasi_temizle
from studioflow.cekirdek.metin import ilk_satir
from studioflow.saglayicilar import yazi_gemini
from studioflow.saglayicilar.hesap_havuzu import (
    hesap_aktif_yap, hesap_ele, hesap_elendi, hesap_listesi)

# Hedef parça uzunluğu ve kesimin aranacağı pay (sn): hedefin ±payı içindeki en uzun
# sessizlikten kesilir.
PARCA_SANIYE = 300
KESIM_PAYI = 60
# Kesim adayı sayılan sessizlik: bu eşiğin altı, en az bu kadar sürmeli.
SESSIZLIK_DB = -35
SESSIZLIK_SURE = 0.4
# Parçalar 16 kHz mono MP3 olarak gönderilir: 5 dakika ~2,3 MB (istek sınırı 20 MB).
PARCA_BIT_HIZI = "64k"
# Bütün hesaplar dakikalık sınırdaysa turlar arası bekleme (sn).
TUR_BEKLEMELERI = (30, 60, 90)
# Geçici (503, kopan bağlantı) hata en fazla bu kadar kez yeniden denenir.
GECICI_TEKRAR = 6

# Dolgu sözcükleri: "eee", "ııı", "hmm" ve uzatmaları. Noktalama atılıp karşılaştırılır.
_DOLGU = re.compile(r"^(?:e{2,}h?|ı{2,}|a{3,}|h?m{2,}|hı+m*|ı?mm+|eh+)$")
_CUMLE_SONU = re.compile(r"[.!?…][\"'”’)]*$")
# Paragraf: cümle sonundan sonra bu kadar saniyelik duraklama yeni paragraf başlatır.
PARAGRAF_BOSLUGU = 2.0


class SestenYaziHatasi(RuntimeError):
    """Kullanıcıya gösterilecek, anlaşılır hata."""


def _gecici_mi(mesaj):
    dusuk = str(mesaj).lower()
    return (hata_etiketle(mesaj) == "BAĞLANTI"
            or any(k in dusuk for k in ("503", "500", "502", "504", "unavailable",
                                        "high demand", "overloaded", "internal error")))


def sessizlikler(kaynak):
    """Kaynaktaki sessizlikler: `[(başlangıç, bitiş)]` (ffmpeg `silencedetect`)."""
    ffmpeg = FFMPEG.ffmpeg()
    if not ffmpeg:
        raise SestenYaziHatasi("ffmpeg bulunamadı; kurulum adımlarını (KURULUM.md) kontrol et.")
    sonuc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(kaynak), "-vn", "-ac", "1",
         "-af", f"silencedetect=noise={SESSIZLIK_DB}dB:d={SESSIZLIK_SURE}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    sonuclar = []
    for satir in sonuc.stderr.splitlines():
        eslesme = re.search(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", satir)
        if eslesme:
            son, sure = float(eslesme.group(1)), float(eslesme.group(2))
            sonuclar.append((son - sure, son))
    return sonuclar


def kesim_noktalari(toplam, sessiz, hedef=PARCA_SANIYE, pay=KESIM_PAYI):
    """Parça sınırları `[0, …, toplam]`.

    Parça sayısı süreye göre seçilir (`toplam / hedef`, yuvarlanmış) ve süre parçalara
    eşit paylaştırılır; her kesim kendi eşit noktasının ±payı içindeki **en uzun**
    sessizliğin ortasına oturur, yoksa tam o noktadan kesilir. Böylece son parça kısa bir
    artık olarak kalmaz (700 sn → 300 + 300 + 100 değil, ~350 + 350).
    """
    adet = max(1, round(toplam / hedef))
    sinirlar = [0.0]
    for sira in range(1, adet):
        aranan = toplam * sira / adet
        adaylar = [(son - bas, (bas + son) / 2) for bas, son in sessiz
                   if aranan - pay <= (bas + son) / 2 <= aranan + pay
                   and (bas + son) / 2 > sinirlar[-1] + 1]
        sinirlar.append(max(adaylar)[1] if adaylar else aranan)
    sinirlar.append(toplam)
    return sinirlar


def parcayi_cikar(kaynak, bas, son, hedef):
    """[bas, son] aralığının sesini 16 kHz mono MP3 olarak yaz."""
    ok, hata = FFMPEG.calistir([FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                                "-ss", f"{bas:.3f}", "-to", f"{son:.3f}", "-i", str(kaynak),
                                "-vn", "-ac", "1", "-ar", "16000", "-b:a", PARCA_BIT_HIZI,
                                str(hedef)])
    if not ok or not Path(hedef).is_file():
        raise SestenYaziHatasi("Ses parçası çıkarılamadı: " + hata)
    return Path(hedef)


def dolgu_mu(kelime):
    sade = re.sub(r"[^\wçğıöşü]", "", kelime.lower())
    return bool(sade) and bool(_DOLGU.match(sade))


def _buyut(kelime):
    """İlk harfi büyüt (Türkçe i → İ)."""
    if not kelime:
        return kelime
    ilk = "İ" if kelime[0] == "i" else kelime[0].upper()
    return ilk + kelime[1:]


def dolgulari_ayikla(kelimeler):
    """Dolgu sözcüklerini zamanlı kelime listesinden çıkar; `(liste, çıkarılan sayısı)`.

    Cümle başındaki "Eee, …" atılınca arkasındaki kelime büyük harfle başlar.
    """
    sonuc, atilan, cumle_basi = [], 0, True
    for bas, son, kelime in kelimeler:
        if dolgu_mu(kelime):
            atilan += 1
            continue
        if cumle_basi:
            kelime = _buyut(kelime)
        sonuc.append((bas, son, kelime))
        cumle_basi = bool(_CUMLE_SONU.search(kelime))
    return sonuc, atilan


def kelimelerden_metin(kelimeler):
    """Zamanlı kelimelerden paragraflı metin: cümle sonundaki uzun duraklama paragraf açar."""
    parcalar = []
    for i, (bas, _son, kelime) in enumerate(kelimeler):
        if i:
            onceki = kelimeler[i - 1]
            ayrac = ("\n\n" if _CUMLE_SONU.search(onceki[2]) and bas - onceki[1] >= PARAGRAF_BOSLUGU
                     else " ")
            parcalar.append(ayrac)
        parcalar.append(kelime)
    return "".join(parcalar)


def metinleri_birlestir(metinler):
    """Parça metinlerini birleştir: önceki cümle sonuyla bitiyorsa paragraf, değilse boşluk."""
    sonuc = ""
    for metin in (m.strip() for m in metinler):
        if not metin:
            continue
        if sonuc:
            sonuc += "\n\n" if _CUMLE_SONU.search(sonuc) else " "
        sonuc += metin
    return sonuc


def _hesapla_dok(veri, dil, zamanli, terimler, bekle=time.sleep):
    """Parçayı Gemini hesaplarını sırayla deneyerek dök; `(metin, kelimeler, hesap adı)`."""
    gecici, son_hata = 0, None
    for tur in range(len(TUR_BEKLEMELERI) + 1):
        hesaplar = [h for h in hesap_listesi("gemini") if not hesap_elendi("gemini", h)]
        if not hesaplar:
            break
        dakikalik = []
        for hesap in hesaplar:
            anahtar = (hesap["degerler"] or {}).get("gemini_key", "")
            if not anahtar:
                continue
            try:
                metin, kelimeler = yazi_gemini.dok(anahtar, veri, "audio/mp3", dil, zamanli, terimler)
                hesap_aktif_yap("gemini", hesap)
                return metin, kelimeler, hesap["ad"]
            except Exception as exc:
                son_hata = ses_hatasi_temizle(exc, anahtar)
                etiket = hata_etiketle(str(exc))
                if etiket == "KOTA":
                    bekleme = dakikalik_bekleme(str(exc))
                    if bekleme is None:
                        hesap_ele("gemini", hesap, str(exc))    # günlük kota
                    else:
                        dakikalik.append(bekleme)
                elif etiket == "YETKİ":
                    hesap_ele("gemini", hesap, str(exc))
                elif _gecici_mi(str(exc)) and gecici < GECICI_TEKRAR:
                    gecici += 1
                else:
                    raise SestenYaziHatasi(son_hata) from exc
        if not dakikalik or tur == len(TUR_BEKLEMELERI):
            break
        bekle(max(TUR_BEKLEMELERI[tur], min(dakikalik)))
    raise SestenYaziHatasi("Hiçbir Gemini hesabı parçayı yazıya dökemedi"
                           + (f": {son_hata}" if son_hata else " (kayıtlı hesap yok)."))


def yaziya_dok(kaynak, cikti_klasoru, dil="", zamanli=True, terimler=(), bekle=time.sleep):
    """Üreteç: ilerleme satırları verir; sonunda `{"metin", "dosyalar", "notlar"}` döndürür."""
    kaynak = Path(kaynak)
    if not kaynak.is_file():
        raise SestenYaziHatasi(f"Dosya bulunamadı: {kaynak}")
    toplam = FFMPEG.medya_suresi(kaynak)
    if toplam <= 0:
        raise SestenYaziHatasi("Dosyanın süresi okunamadı; içinde ses olan bir video ya da ses dosyası seç.")
    if not FFMPEG.probe(["-select_streams", "a", "-show_entries", "stream=index",
                         "-of", "csv=p=0"], kaynak).strip():
        raise SestenYaziHatasi("Dosyada ses kanalı yok.")
    cikti = Path(cikti_klasoru)
    calisma = cikti / "parcalar"
    calisma.mkdir(parents=True, exist_ok=True)

    yield f"Ses inceleniyor ({toplam / 60:.1f} dk); sessiz noktalar aranıyor…"
    sinirlar = kesim_noktalari(toplam, sessizlikler(kaynak))
    adet = len(sinirlar) - 1
    metinler, kelimeler, notlar, duzeltilen = [], [], [], 0
    for no in range(adet):
        bas, son = sinirlar[no], sinirlar[no + 1]
        yield (f"Parça {no + 1}/{adet} yazıya dökülüyor "
               f"({_saat(bas)}–{_saat(son)})…")
        mp3 = parcayi_cikar(kaynak, bas, son, calisma / f"parca_{no + 1:02d}.mp3")
        metin, parca_kelimeleri, hesap = _hesapla_dok(mp3.read_bytes(), dil, zamanli, terimler, bekle)
        if zamanli:
            parca_kelimeleri, kac = yazi_gemini.zamanlari_duzelt(parca_kelimeleri, son - bas)
            duzeltilen += kac
            kelimeler += [(bas + b, bas + s, k) for b, s, k in parca_kelimeleri]
        metinler.append(metin)
        (calisma / f"parca_{no + 1:02d}.txt").write_text(metin + "\n", encoding="utf-8")
        yield f"Parça {no + 1}/{adet} tamam · '{hesap}' hesabı · {len(metin.split())} kelime"

    dosyalar = []
    if zamanli:
        kelimeler, atilan = dolgulari_ayikla(kelimeler)
        metin = kelimelerden_metin(kelimeler)
        if atilan:
            notlar.append(f"{atilan} dolgu sözcüğü ('eee' vb.) çıkarıldı")
        if duzeltilen:
            notlar.append(f"{duzeltilen} bozuk kelime zamanı düzeltildi")
        yazilan, satir, _uzun = build_subtitles(kelimeler, calisma)
        for yol in yazilan:
            hedef = cikti / f"{kaynak.stem}{Path(yol).suffix}"
            Path(yol).replace(hedef)
            dosyalar.append(hedef)
        notlar.append(f"altyazı: {satir} satır")
    else:
        metin = metinleri_birlestir(metinler)
        notlar.append("dolgu sözcüklerini model temizledi (SMART kipi)")
    metin_yolu = cikti / f"{kaynak.stem}.txt"
    metin_yolu.write_text(metin + "\n", encoding="utf-8")
    return {"metin": metin, "dosyalar": [metin_yolu] + dosyalar, "notlar": notlar,
            "parca": adet, "sure": toplam}


def _saat(saniye):
    saniye = int(saniye)
    return f"{saniye // 60:02d}:{saniye % 60:02d}"


def cikti_klasoru(kok, kaynak):
    """Her döküm kendi klasörüne: `<kök>/<dosya adı>-<tarih saat>`."""
    ad = re.sub(r"[^\w\-]+", "_", Path(kaynak).stem).strip("_")[:60] or "kayit"
    return Path(kok) / f"{ad}-{datetime.now():%Y%m%d-%H%M%S}"
