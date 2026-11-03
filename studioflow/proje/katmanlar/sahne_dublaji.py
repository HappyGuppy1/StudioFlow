"""Sahnelere göre dublaj: çeviriyi ve sesi adım zamanlarına oturtmak.

Düz dublajda anlatım tek parça çevrilip tek parça seslendiriliyordu; çeviri orijinalden
uzun ya da kısa olduğu için ses birkaç dakika içinde görüntüden kayıyordu (sahneler
orijinal sesin kelime zamanlarına göre kesilmiştir). Bu modül dublajı **sahne sahne**
kurar:

1. `bloklari_kur` — adımlar cümle sonlarından gruplanır; her blok bir zaman penceresi
   taşır (ilk adımın başı → son adımın sonu). Cümle ortasından kesilmez ki tonlama doğal
   kalsın.
2. `ceviri_istegi` / `ceviri_coz` — bütün bloklar **tek istekte** çevrilir (bağlam ve
   terim tutarlılığı), her bloğa pencereye sığacak bir kelime bütçesi yazılır.
3. Her blok ayrı seslendirilir (akış `diller` modülündedir).
4. `yerlestir` — blok kendi penceresinin başında başlar; uzunsa en fazla `AZAMI_HIZ`
   kadar hızlandırılır; hâlâ uzunsa sonraki pencereye taşar ama sonraki blok ancak o
   bitince başlar: sesler **asla üst üste binmez**. Kayma birikmez, çünkü her blok yine
   kendi penceresinin başını bekler.
5. `karistir` — bloklar sessiz bir zemine yerleştirilip tek WAV yazılır; altyazı
   kelimeleri de aynı yerleşimden tahmin edilir (`altyazi_kelimeleri`).

Çıktı düz dublajla aynı dosyadır (`seslendirme-<ad>.wav`); kayıt, videoya ekleme ve
müzik akışları değişmez. Seçenek kapalıyken (varsayılan) düz dublaj eskisi gibi çalışır.
"""
import difflib
import json
import re
import unicodedata

import numpy as np
import soundfile as sf

from studioflow.altyazi.bloklar import tahmini_kelimeler
from studioflow.proje.json_yardim import json_listesi
from studioflow.proje.sahneleme import KELIME_HIZI

# Kulağa doğal gelen en yüksek hızlandırma; ötesinde ses aceleci duyuluyor.
AZAMI_HIZ = 1.12
# Hızlandırmadan sonra bu kadar saniyeden fazla taşan blok bir kez daha, daha kısa çevrilir.
TASMA_SINIRI = 0.75
# Bütçe hiç bu kadardan küçük olmaz: tek kelimelik "Albastı." gibi başlıklar da okunabilsin.
EN_AZ_KELIME = 2

_CUMLE_SONU = re.compile(r"[.!?…。！？][\"'”’)\]」』]*$")
# Boşluksuz yazılan diller (Çince, Japonca): eşleştirme karakter karakter yapılır ve bir
# karakter okunurken Latin harfinden çok daha uzun sürer (bkz. `metin_agirligi`).
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]")
CJK_AGIRLIK = 3

CEVIRI_SISTEM = (
    "You are a professional dubbing scriptwriter. You receive a narration split into "
    "numbered blocks; each block is spoken over its own scene and has a word budget. "
    "Translate every block into the target language so it can be read aloud naturally "
    "within its budget: keep the meaning, tone and facts, keep proper names, keep numbers "
    "speakable. If a literal translation would exceed the budget, shorten it by dropping "
    "filler words, never by dropping facts. Translate each block on its own (do not move "
    "words between blocks), but keep terminology consistent across blocks. Never add "
    "commentary, notes, stage directions or markup. Reply ONLY with a JSON array: "
    '[{"id": <int>, "text": "<translation>"}, ...] with exactly one element per block.')


def bloklari_kur(adimlar):
    """Adımları cümle sonlarından gruplayıp `[{"text", "bas", "son"}]` blokları kur.

    Zamanı okunamayan adım atlanmaz: metni bir önceki bloğa eklenir (bloklar anlatımın
    tamamını kapsamalı). Son blok, cümle sonu olmasa da kapatılır.
    """
    bloklar, acik = [], None
    for adim in adimlar or []:
        metin = " ".join(str(adim.get("text") or "").split())
        if not metin:
            continue
        bas, son = float(adim.get("start") or 0.0), float(adim.get("end") or 0.0)
        if acik is None:
            acik = {"text": metin, "bas": bas, "son": max(son, bas)}
        else:
            acik["text"] += " " + metin
            acik["son"] = max(acik["son"], son)
        if _CUMLE_SONU.search(metin):
            bloklar.append(acik)
            acik = None
    if acik is not None:
        bloklar.append(acik)
    return bloklar


def pencereler(bloklar, toplam_sure):
    """Her bloğun kullanabileceği süre: kendi başından sonraki bloğun başına kadar.

    Son blok videonun sonuna kadar uzanır; böylece adımlar arasındaki doğal duraklar da
    bloğa sayılır.
    """
    sonuc = []
    for sira, blok in enumerate(bloklar):
        bitis = bloklar[sira + 1]["bas"] if sira + 1 < len(bloklar) else max(toplam_sure, blok["son"])
        sonuc.append(max(0.1, bitis - blok["bas"]))
    return sonuc


def kelime_butcesi(sure, oran=1.0):
    """Pencereye sığacak kelime sayısı (konuşma hızı `KELIME_HIZI` ile)."""
    return max(EN_AZ_KELIME, int(sure * KELIME_HIZI * oran))


def ceviri_istegi(bloklar, butceler, dil_adi):
    """Toplu çeviri isteğinin kullanıcı mesajı."""
    satirlar = [f"Target language: {dil_adi}", "Blocks:"]
    for sira, (blok, butce) in enumerate(zip(bloklar, butceler)):
        satirlar.append(json.dumps({"id": sira, "max_words": butce, "text": blok["text"]},
                                   ensure_ascii=False))
    return "\n".join(satirlar)


def ceviri_coz(cevap, adet):
    """Yanıtı `adet` uzunluğunda metin listesine çevir; eksik/bozuksa `ValueError`."""
    metinler = ceviri_parcalari(cevap, adet)
    eksik = [sira for sira in range(adet) if sira not in metinler]
    if eksik:
        raise ValueError(f"Çeviride {len(eksik)} blok eksik (ör. {eksik[:5]}).")
    return [metinler[sira] for sira in range(adet)]


def ceviri_parcalari(cevap, adet):
    """Yanıttaki **sağlam** blokları `{sıra: metin}` olarak ver; eksikler sorun değildir.

    Gemini bazen 15 bloğun yalnızca ilk 10'unu döndürüyor (İspanyolca, 17.10.2026);
    gelen bloklar atılmaz, yalnızca eksikler yeniden istenir (bkz. `diller._blok_cevir`).
    Yanıt hiç dizi değilse `ValueError`.
    """
    liste = json_listesi(cevap)
    if not isinstance(liste, list):
        raise ValueError("Çeviri yanıtı JSON dizisi değil.")
    metinler = {}
    for oge in liste:
        if not isinstance(oge, dict):
            continue
        try:
            sira = int(oge.get("id"))
        except (TypeError, ValueError):
            continue
        metin = " ".join(str(oge.get("text") or "").split())
        if 0 <= sira < adet and metin:
            metinler[sira] = metin
    return metinler


def yerlestir(bloklar, sureler, toplam_sure, azami_hiz=AZAMI_HIZ):
    """Blokları çakışmadan yerleştir: `[{"bas", "hiz", "sure", "tasma", "asim"}]`.

    `sureler` her bloğun seslendirilmiş (hızlandırılmamış) süresidir. Blok, kendi
    penceresinin başında ya da bir önceki ses bitince (hangisi geçse) başlar; penceresine
    sığmıyorsa `azami_hiz`'e kadar hızlandırılır. `tasma`, hızlandırmadan sonra sonraki
    bloğun penceresine taşan saniyedir (önceki bloğun gecikmesi de dahil). `asim`, bloğun
    **kendi** penceresine en yüksek hızda bile sığmayan saniyesidir: kısaltılacak blok
    buna göre seçilir, yalnızca öncekinin gecikmesiyle kayan kısa blok seçilmez.
    """
    sonuc, onceki_son = [], 0.0
    for sira, (blok, sure) in enumerate(zip(bloklar, sureler)):
        bas = max(blok["bas"], onceki_son)
        bitis = bloklar[sira + 1]["bas"] if sira + 1 < len(bloklar) else max(toplam_sure, blok["son"])
        kullanilabilir = max(0.1, bitis - bas)
        hiz = 1.0
        if sure > kullanilabilir:
            hiz = min(azami_hiz, sure / kullanilabilir)
        gercek = sure / hiz
        pencere = max(0.1, bitis - blok["bas"])
        sonuc.append({"bas": round(bas, 3), "hiz": round(hiz, 3), "sure": round(gercek, 3),
                      "tasma": round(max(0.0, bas + gercek - bitis), 3),
                      "asim": round(max(0.0, sure / azami_hiz - pencere), 3)})
        onceki_son = bas + gercek
    return sonuc


def kisaltilacaklar(yerlesim, sinir=TASMA_SINIRI):
    """En yüksek hızda bile kendi penceresini `sinir`'dan fazla aşan blokların sıraları."""
    return [sira for sira, yer in enumerate(yerlesim) if yer["asim"] > sinir]


def kisa_butce(kelime_sayisi, sure, pencere, azami_hiz=AZAMI_HIZ):
    """Kısaltılacak bloğun yeni kelime bütçesi: penceresine en yüksek hızda sığacak kadar."""
    oran = (pencere * azami_hiz) / max(0.1, sure) * 0.9
    return max(EN_AZ_KELIME, int(kelime_sayisi * oran))


def karistir(dosyalar, yerlesim, toplam_sure, cikti):
    """Blok seslerini yerleşimdeki zamanlara koyup tek WAV yaz; yazılan süreyi döndür.

    Bütün bloklar aynı örnekleme hızında olmalıdır (aynı servisle üretilirler). Son blok
    videodan uzun sürerse dosya da o kadar uzar; ses kesilmez.
    """
    if not dosyalar:
        raise ValueError("Yerleştirilecek blok sesi yok.")
    bilgi = sf.info(str(dosyalar[0]))
    oran, kanal = bilgi.samplerate, bilgi.channels
    sesler = []
    for dosya in dosyalar:
        veri, hiz = sf.read(str(dosya), dtype="float32", always_2d=True)
        if hiz != oran or veri.shape[1] != kanal:
            raise ValueError("Blok seslerinin biçimleri farklı; aynı servisle yeniden üret.")
        sesler.append(veri)
    son = max([toplam_sure] + [yer["bas"] + len(ses) / oran for yer, ses in zip(yerlesim, sesler)])
    zemin = np.zeros((int(np.ceil(son * oran)) + 1, kanal), dtype="float32")
    for yer, ses in zip(yerlesim, sesler):
        bas = int(round(yer["bas"] * oran))
        zemin[bas:bas + len(ses)] += ses[:len(zemin) - bas]
    np.clip(zemin, -1.0, 1.0, out=zemin)
    sf.write(str(cikti), zemin, oran, subtype="PCM_16")
    return len(zemin) / oran


# ── büyük parçalı seslendirme ────────────────────────────────────────────────
# Her blok ayrı istekle seslendirilince ses her blokta sıfırdan üretiliyor, sınırlarda
# "başka biri konuşuyor" gibi kayıyordu (Türkçe dublaj, 08.10.2026: 121 blok = 121
# istek, günlük kotayı da aştı). Bloklar artık ~PARCA_KARAKTER'lik parçalar hâlinde
# **tek seferde** seslendirilir; parça whisper ile dinlenir ve blok sınırlarından
# kesilir. Ses kesintisiz bir okumadan geldiği için tını sabit kalır, istek sayısı ~20
# kat düşer.
PARCA_KARAKTER = 1500
# Kesim aranırken tahmini noktanın iki yanında bakılan whisper kelimesi sayısı.
KESIM_ARAMA = 4
# Kesilen bloğun başında/sonunda bırakılan sessizlik (sn) ve sessizlik eşiği (tepeye göre).
KENAR_PAY = 0.06
SESSIZ_ORAN = 0.04
# Bloğun **sonu** daha yumuşak kırpılır: cümle sonundaki alçalan hece (Türkçe "solur")
# tepenin %4'ünün altında kalıp kırpılıyor, blok yarım bitmiş gibi duyuluyordu
# (Betta Türkçe dublajı, 26.10.2026).
SON_SESSIZ_ORAN = 0.015
SON_KENAR_PAY = 0.15


def metin_agirligi(metin):
    """Okuma süresiyle orantılı uzunluk: Çince/Japonca karakter `CJK_AGIRLIK` sayılır."""
    return len(metin) + (CJK_AGIRLIK - 1) * len(_CJK.findall(metin))


def belirtecler(metin):
    """Eşleştirme birimleri: boşluklu dillerde kelime, Çince/Japoncada tek tek karakter.

    Karakterlere bölünen kelimenin cümle sonu noktalaması son karaktere eklenir ki
    kesim cümle sonunu yine tanısın.
    """
    sonuc = []
    for kelime in metin.split():
        if not _CJK.search(kelime):
            sonuc.append(kelime)
            continue
        harfler = [h for h in kelime if h.isalnum()]
        if harfler and _cumle_sonu_mu(kelime):
            harfler[-1] += kelime[-1]
        sonuc += harfler or [kelime]
    return sonuc


def belirtec_zamanlari(kelimeler):
    """Whisper kelimelerini `belirtecler` birimlerine böl; süre eşit paylaştırılır."""
    sonuc = []
    for bas, son, kelime in kelimeler:
        parcalar = belirtecler(kelime) or [kelime]
        adim = (son - bas) / len(parcalar)
        sonuc += [(bas + i * adim, bas + (i + 1) * adim, parca)
                  for i, parca in enumerate(parcalar)]
    return sonuc


def ses_parcalari(metinler, sinir=PARCA_KARAKTER):
    """Ardışık blok sıralarını en fazla `sinir` karakterlik parçalara grupla.

    Blok bölünmez; tek başına sınırı aşan blok kendi parçasını oluşturur.
    """
    parcalar, acik, boy = [], [], 0
    for sira, metin in enumerate(metinler):
        uzunluk = metin_agirligi(metin) + 1
        if acik and boy + uzunluk > sinir:
            parcalar.append(acik)
            acik, boy = [], 0
        acik.append(sira)
        boy += uzunluk
    if acik:
        parcalar.append(acik)
    return parcalar


def _cumle_sonu_mu(kelime):
    return bool(_CUMLE_SONU.search(kelime.strip()))


def _en_sessiz(ses, oran, bas, son):
    """[bas, son] aralığındaki en sessiz 20 ms'lik noktanın saniyesi."""
    pen = max(1, int(0.02 * oran))
    i, j = max(0, int(bas * oran)), min(len(ses), int(son * oran))
    if j - i <= pen:
        return (bas + son) / 2
    enerji = np.convolve(ses[i:j] ** 2, np.ones(pen) / pen, mode="valid")
    return (i + int(np.argmin(enerji)) + pen // 2) / oran


# Whisper yoksa kesim gerçek duraklamalara oturtulur: en az bu kadar süren sessizlik
# duraklama sayılır; tahmini noktanın iki yanında bu kadar saniye aranır.
EN_KISA_DURAKLAMA = 0.15
DURAKLAMA_ARAMA = 2.5


def duraklamalar(ses, oran, en_kisa=EN_KISA_DURAKLAMA, esik_orani=SESSIZ_ORAN):
    """Sesteki duraklamalar: `[(başlangıç sn, bitiş sn)]` (20 ms'lik enerji karelerinden)."""
    pen = max(1, int(0.02 * oran))
    kare = len(ses) // pen
    if not kare:
        return []
    enerji = np.sqrt((ses[:kare * pen].reshape(kare, pen) ** 2).mean(axis=1))
    esik = float(enerji.max()) * esik_orani
    sonuc, bas = [], None
    for i, sessiz in enumerate(enerji <= esik):
        if sessiz and bas is None:
            bas = i
        elif not sessiz and bas is not None:
            if (i - bas) * pen / oran >= en_kisa:
                sonuc.append((bas * pen / oran, i * pen / oran))
            bas = None
    return sonuc


# Duraklama ataması: blok süresinin metne göre beklenen süreden sapmasının (log oran)
# karesi bu katsayıyla cezalanır; seçilen duraklamanın uzunluğu (sn) ödüllendirilir.
SAPMA_CEZASI = 2.0


def _duraklamaya_oturt(blok_metinleri, ses, oran):
    """Whisper yokken kesimler: bütün sınırlar **birlikte** gerçek duraklamalara atanır.

    Her blokun beklenen süresi metin ağırlığıyla orantılıdır. Dinamik programlama,
    blok sürelerinin beklenenden sapmasını en aza indiren ve uzun (cümle arası)
    duraklamaları seçen sıralı kesim kümesini bulur. Tek tek seçmek blok içindeki
    duraklamalara kanıyor, bazı blokları neredeyse boş bırakıyordu (İrlandaca,
    09.10.2026: whisper İrlandacayı tanımıyor). Yeterli duraklama yoksa her sınır tek tek
    en yakın uzun duraklamaya oturtulur.
    """
    sure = len(ses) / oran
    uzunluklar = [max(1, metin_agirligi(metin)) for metin in blok_metinleri]
    toplam = sum(uzunluklar)
    adaylar = duraklamalar(ses, oran)
    gerekli = len(uzunluklar) - 1
    if gerekli and len(adaylar) >= gerekli:
        return _duraklama_atamasi(uzunluklar, adaylar, ses, oran)
    kesimler, birikim, alt = [], 0, 0.0
    for uzunluk in uzunluklar[:-1]:
        birikim += uzunluk
        tahmin = sure * birikim / toplam
        en_iyi, en_iyi_puan = None, None
        for bas, son in adaylar:
            orta = (bas + son) / 2
            if orta <= alt + 0.1 or abs(orta - tahmin) > DURAKLAMA_ARAMA:
                continue
            puan = (son - bas) - 0.12 * abs(orta - tahmin)
            if en_iyi_puan is None or puan > en_iyi_puan:
                en_iyi, en_iyi_puan = (bas, son), puan
        if en_iyi:
            kesim = _en_sessiz(ses, oran, *en_iyi)
        else:
            kesim = _en_sessiz(ses, oran, max(alt, tahmin - 0.3), min(sure, tahmin + 0.3))
        kesim = min(max(kesim, alt + 0.1), sure)
        kesimler.append(kesim)
        alt = kesim
    return kesimler


def _duraklama_atamasi(uzunluklar, adaylar, ses, oran):
    """`len(uzunluklar) - 1` kesimi duraklama adaylarına en düşük maliyetle ata (DP)."""
    sure = len(ses) / oran
    toplam = sum(uzunluklar)
    beklenen = [sure * u / toplam for u in uzunluklar]
    orta = [(bas + son) / 2 for bas, son in adaylar]
    odul = [son - bas for bas, son in adaylar]
    n, m = len(uzunluklar) - 1, len(adaylar)

    def maliyet(blok, bas, son):
        return SAPMA_CEZASI * np.log(max(son - bas, 0.05) / beklenen[blok]) ** 2

    sonsuz = float("inf")
    dp = [[sonsuz] * m for _ in range(n)]
    geri = [[-1] * m for _ in range(n)]
    for j in range(m):
        dp[0][j] = maliyet(0, 0.0, orta[j]) - odul[j]
    for i in range(1, n):
        for j in range(i, m):
            en_iyi, kaynak = sonsuz, -1
            for k in range(i - 1, j):
                if dp[i - 1][k] == sonsuz:
                    continue
                deger = dp[i - 1][k] + maliyet(i, orta[k], orta[j])
                if deger < en_iyi:
                    en_iyi, kaynak = deger, k
            if kaynak >= 0:
                dp[i][j], geri[i][j] = en_iyi - odul[j], kaynak
    son_maliyet = [dp[n - 1][j] + maliyet(n, orta[j], sure) for j in range(m)]
    j = int(np.argmin(son_maliyet))
    secim = []
    for i in range(n - 1, -1, -1):
        secim.append(j)
        j = geri[i][j]
    secim.reverse()
    return [_en_sessiz(ses, oran, *adaylar[j]) for j in secim]


def _sade(kelime):
    """Eşleştirme için kelime: aksansız, küçük harf, yalnız harf ve rakam."""
    ayrik = unicodedata.normalize("NFD", kelime.lower())
    return "".join(h for h in ayrik if h.isalnum())


# Kelimeler ilk bu kadar harfiyle karşılaştırılır: whisper çekim ekini ya da son harfi
# farklı yazabiliyor ("hånden"/"hånd", "Jormungand"/"Jormungant"); tam eşleşme isteyince
# blok sınırı kaçıyor ve cümle önceki bloğa kayıyordu (Norveççe, 09.10.2026).
ESLESME_ONEKI = 4


def _anahtar(kelime):
    return _sade(kelime)[:ESLESME_ONEKI]


def _kelime_eslesmesi(metin_kelimeleri, duyulan):
    """Metin kelimesi sırası → whisper kelimesi sırası (yalnız eşleşenler)."""
    a = [_anahtar(k) for k in metin_kelimeleri]
    b = [_anahtar(k) for k in duyulan]
    eslesme = {}
    for blok in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for i in range(blok.size):
            if a[blok.a + i]:
                eslesme[blok.a + i] = blok.b + i
    return eslesme


def _eslesen_konum(eslesme, metin_sira, adet):
    """Metin kelimesinin whisper'daki tahmini sırası: komşu eşleşmeler arasında oranla."""
    if metin_sira in eslesme:
        return min(adet - 2, eslesme[metin_sira])
    onceki = max((i for i in eslesme if i < metin_sira), default=None)
    sonraki = min((i for i in eslesme if i > metin_sira), default=None)
    if onceki is None and sonraki is None:
        return 0
    if onceki is None:
        return max(0, eslesme[sonraki] - (sonraki - metin_sira))
    if sonraki is None:
        return min(adet - 2, eslesme[onceki] + (metin_sira - onceki))
    oran = (metin_sira - onceki) / (sonraki - onceki)
    return min(adet - 2, round(eslesme[onceki] + oran * (eslesme[sonraki] - eslesme[onceki])))


def kesim_noktalari(blok_metinleri, kelimeler, ses, oran):
    """Parça sesindeki blok sınırlarının saniyeleri (`len(blok_metinleri) - 1` adet).

    `kelimeler` parçanın whisper kelime zamanlarıdır: `(bas, son, kelime)`. Metnin
    kelimeleri whisper'ınkilerle **sıra hizalamasıyla** eşlenir (aksan, büyük harf ve
    noktalama yok sayılır); her sınır, bloğun son kelimesinin eşlendiği whisper
    kelimesinden hemen sonraya düşer. Eşleşmeyen kelime varsa (whisper yanlış duydu)
    en yakın eşleşmeler arasında oranla tahmin edilip yakındaki en uzun duraklama
    seçilir. Kesim o aralıktaki en sessiz noktaya oturtulur; kelime ortasından kesilmez.

    Eskiden sınır yalnızca kelime **oranıyla** tahmin ediliyordu; "Νούμερο ένα. Κρόνος."
    gibi içinde uzun duraklama olan bloklar onu yanıltıyor, bloklar bir cümle kayıyordu
    (Yunanca, 09.10.2026).
    """
    sayilar = [len(belirtecler(metin)) for metin in blok_metinleri]
    sure = len(ses) / oran
    if len(kelimeler) < 2:
        # Whisper yok (kota, hata): metinden tahmin edilen kelime aralıkları gerçek
        # değildir ve kelime ortasından kestiriyordu (Yunanca, 09.10.2026: 118 blokta 7).
        return _duraklamaya_oturt(blok_metinleri, ses, oran)
    kelimeler = belirtec_zamanlari(kelimeler)
    adet = len(kelimeler)
    eslesme = _kelime_eslesmesi([k for metin in blok_metinleri for k in belirtecler(metin)],
                                [k[2] for k in kelimeler])
    kesimler, birikim, alt = [], 0, 0
    for sayi in sayilar[:-1]:
        birikim += sayi
        tahmin = _eslesen_konum(eslesme, birikim - 1, adet)
        if birikim - 1 in eslesme and eslesme[birikim - 1] + 1 < adet:
            # Bloğun son kelimesi doğrudan eşleşti: aralık kesin.
            aday_bas = aday_son = max(alt, eslesme[birikim - 1])
        elif birikim in eslesme and 0 < eslesme[birikim] < adet:
            # Son kelime eşleşmedi ama sonraki bloğun ilk kelimesi eşleşti: hemen öncesi.
            aday_bas = aday_son = max(alt, eslesme[birikim] - 1)
        else:
            aday_bas = max(alt, tahmin - KESIM_ARAMA)
            aday_son = min(adet - 2, tahmin + KESIM_ARAMA)
        en_iyi, en_iyi_puan = None, None
        for k in range(aday_bas, max(aday_bas, aday_son) + 1):
            if k >= adet - 1:
                break
            bosluk = kelimeler[k + 1][0] - kelimeler[k][1]
            puan = (bosluk + (0.5 if _cumle_sonu_mu(kelimeler[k][2]) else 0.0)
                    - 0.03 * abs(k - tahmin))
            if en_iyi_puan is None or puan > en_iyi_puan:
                en_iyi, en_iyi_puan = k, puan
        if en_iyi is None:
            en_iyi = min(max(alt, tahmin), adet - 2)
        bas, son = kelimeler[en_iyi][1], kelimeler[en_iyi + 1][0]
        if son - bas < 0.05:
            bas, son = bas - 0.15, son + 0.15
        kesim = _en_sessiz(ses, oran, bas, son)
        if kesimler:
            kesim = max(kesim, kesimler[-1] + 0.1)
        kesimler.append(min(kesim, sure))
        alt = en_iyi + 1
    return kesimler


def parcayi_kes(ses, oran, kesimler):
    """Parça sesini kesim noktalarından böl; her parçanın kenar sessizliği kırpılır."""
    sinirlar = [0.0] + list(kesimler) + [len(ses) / oran]
    tepe = float(np.max(np.abs(ses))) if len(ses) else 0.0
    esik, son_esik = tepe * SESSIZ_ORAN, tepe * SON_SESSIZ_ORAN
    pay, son_pay = int(KENAR_PAY * oran), int(SON_KENAR_PAY * oran)
    sonuc = []
    for bas, son in zip(sinirlar, sinirlar[1:]):
        parca = ses[int(bas * oran):int(son * oran)]
        dolu = np.nonzero(np.abs(parca) > esik)[0] if esik > 0 else []
        if len(dolu):
            sonda = np.nonzero(np.abs(parca) > son_esik)[0]
            # Sönüm en fazla 0,35 sn uzatılır; ötesi sonraki cümlenin nefesidir.
            bitis = min(max(dolu[-1], sonda[-1]), dolu[-1] + int(0.35 * oran))
            parca = parca[max(0, dolu[0] - pay):min(len(parca), bitis + son_pay + 1)]
        sonuc.append(parca)
    return sonuc


def altyazi_kelimeleri(metinler, yerlesim):
    """Altyazı için kelime zamanları: her bloğun kelimeleri kendi yerleşimine dağıtılır."""
    kelimeler = []
    for metin, yer in zip(metinler, yerlesim):
        kelimeler += tahmini_kelimeler(metin, yer["sure"], offset=yer["bas"])
    return kelimeler
