"""Anlatımı sahnelere bölme: süre tahmini, sabit parçalama, içerik/yapay zekâ temelli plan.

Video sahne sahne üretilir: her sahne tek bir görselden çıkan bir kliptir ve **kendi
süresini** taşır. Anlatım cümlelere bölünür, yapay zekâ ardışık cümleleri sahnelere
gruplayıp her sahneye içeriğine/temposuna uygun bir süre verir (ör. kısa cümle 2 sn,
uzun betimleme 5 sn); süreler 0,5–`üst` aralığında kalır. Yapay zekâ yanıt vermezse
cümle uzunluğuna dayalı içerik yedeği devreye girer.
"""
import hashlib
import math
import re
from pathlib import Path

import soundfile as sf

from studioflow.cekirdek.hatalar import ses_hatasi_temizle
from studioflow.cekirdek.metin import kelime_sayisi, kirp
from studioflow.proje.json_yardim import json_listesi
from studioflow.proje.sahne_stratejileri import (
    VARSAYILAN_STRATEJI, strateji_kurallari, strateji_normallestir)
from studioflow.saglayicilar import metin_ai, ses_uretim
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS

PARCA_SANIYE = 5.0          # her video parçasının hedef süresi
# Tahmin için saniyede okunan kelime. 2,5 (150/dk) gerçek sesten hızlıydı: Gemini TTS
# ölçümleri 131 (piramit), 132 (claudetest), 128 (claudetest4) kelime/dk. Tahmin kısa
# kalınca sayfadaki plan 8 sn'ye sığan sahneleri gerçek seste tavanı aşıp bölünüyordu.
KELIME_HIZI = 2.2           # ~130 kelime/dk


def tahmini_sure(metin, hiz=0):
    """Ses üretilemezse kelime sayısından süre tahmini (~150 kelime/dk)."""
    kelimeler = [k for k in (metin or "").split() if k.strip()]
    if not kelimeler:
        return 0.0
    saniye = len(kelimeler) / KELIME_HIZI
    try:
        carpan = 1 - (float(hiz) / 100.0)
    except (TypeError, ValueError):
        carpan = 1.0
    return max(saniye * carpan, 1.0)


def ses_suresi(provider, metin, dil, *, key="", model=None, voice="Charon", style="",
               token="", reference=None, exag=0.5, cfg=0.5, edge_ses="", hiz=0, ton=0,
               ses=None):
    """Seçili servisle sesi gerçekten üretip süresini ölç.

    Döndürdüğü değer: (süre_saniye, ses_dosyası|None, not). Ses üretilemezse
    süre tahminle hesaplanır ve `not` sebebi açıklar.
    """
    uretici = ses or ses_uretim.VARSAYILAN
    son = None
    try:
        for _, ses, _, _ in uretici.uret(
                provider, metin, dil, key=key or "", model=model or GEMINI_MODELS[0],
                voice=voice, style=style, token=token or "", reference=reference,
                exaggeration=exag, cfg=cfg, edge_voice=edge_ses, rate=int(hiz), pitch=int(ton),
                subtitles=False):
            if ses:
                son = Path(ses)
    except Exception as exc:
        return (tahmini_sure(metin, hiz), None,
                "Ses üretilemedi, süre tahminle hesaplandı: " + ses_hatasi_temizle(exc, key, token))
    if not son or not son.exists():
        return (tahmini_sure(metin, hiz), None,
                "Ses dosyası oluşmadı, süre tahminle hesaplandı.")
    try:
        return float(sf.info(son).duration), son, ""
    except Exception:
        return tahmini_sure(metin, hiz), son, "Ses süresi okunamadı, tahmin kullanıldı."


def parcalara_bol(metin, toplam_sure, parca_saniye=PARCA_SANIYE):
    """Anlatımı zamanla orantılı olarak `parca_saniye`lik parçalara böl.

    Her parça şu alanları taşır: index, start, end, text.
    """
    metin = (metin or "").strip()
    kelimeler = metin.split()
    if not kelimeler:
        return []
    if toplam_sure <= 0:
        toplam_sure = tahmini_sure(metin)
    try:
        parca_saniye = max(float(parca_saniye), 0.5)
    except (TypeError, ValueError):
        parca_saniye = PARCA_SANIYE
    adet = max(1, int(math.ceil(toplam_sure / parca_saniye)))
    parcalar = []
    for index in range(adet):
        bas = index * parca_saniye
        bit = min(toplam_sure, (index + 1) * parca_saniye)
        a = min(round(len(kelimeler) * bas / toplam_sure), len(kelimeler))
        if index == adet - 1:
            b = len(kelimeler)
        else:
            b = min(round(len(kelimeler) * bit / toplam_sure), len(kelimeler))
        b = max(b, a)
        parcalar.append({"index": index + 1, "start": round(bas, 2), "end": round(bit, 2),
                         "text": " ".join(kelimeler[a:b]).strip()})
    return parcalar


def _yarim(saniye):
    """Yarım saniyenin katına **yukarı** yuvarla: video anlatımdan kısa kalmasın."""
    return math.ceil(float(saniye) * 2) / 2


SAHNE_DETAY_SISTEM = (
    "You are a video editor planning the scene structure of ONE narrated video. "
    "The video is generated scene by scene: every scene is a single clip made from one "
    "still frame, and the narration is spoken over the scene in order. "
    "You receive the narration split into NUMBERED SENTENCES, its spoken language and the "
    "estimated spoken duration. Group CONSECUTIVE sentences into scenes and give each "
    "scene its OWN duration in seconds. Rules:\n"
    "- every sentence must be used exactly once and in order; a scene covers one or more "
    "consecutive sentences (never split a sentence),\n"
    "- each scene duration must stay between {alt} and {ust} seconds,\n"
    "- let the duration follow the content and pace: a slow descriptive sentence gets more "
    "time, a short punchy line less; do NOT give every scene the same duration,\n"
    "- the sum of all scene durations must be >= the estimated spoken duration, so the "
    "video never ends before the narration,\n"
    "- prefer fewer, coherent scenes over many tiny ones,\n"
    "- a sentence that shows nothing new on screen (a comment, feeling, thought or short "
    "punchline such as 'They call it duty.') never gets its own scene: group it with the "
    "neighbouring sentence that has a visible action or place,\n"
    "- start a new scene when the narration moves to a new place or a new visible action.\n"
    "Reply ONLY with a JSON array, without markdown fences and without extra keys: "
    '[{{"cumleler": [<sentence numbers>], "saniye": <number>}}, ...]'
)


def _cumlelere_bol(metin):
    """Anlatımı cümlelere böl (`. ! ? …` ve satır sonları sınır sayılır).

    Noktalama metinde kalır; boş parçalar atılır. Sınır bulunamazsa tek parça döner.
    """
    metin = " ".join((metin or "").split())
    if not metin:
        return []
    parcalar = re.split(r"(?<=[.!?…])\s+|\n+", metin)
    return [p.strip() for p in parcalar if p.strip()]


def sahne_tavani(azami_sahne, toplam_sure, ust):
    """Sahne sayısı tavanı: verilen tavan ama **anlatımı kapsayacak kadar** büyük.

    Sabit 60'lık tavan 8 dakikayı aşan anlatımda yetmiyordu: 60 sahne × 8 sn = 480 sn.
    Greek Mythology 8 Monsters (05.10.2026, 507 sn ses): içerik yedeği 140 cümleyi 60'ta
    kesti, anlatımın yarısı (245/507 sn) sahnesiz kaldı. Tavan en az `⌈2 × süre / üst⌉`dir:
    tam `⌈süre / üst⌉`te cümleler eşit bölünemediği için sahneler okunma uzunluğuyla
    sığdırılamıyor, hepsi `üst`e doldurulup aynı süreyi alıyordu.
    """
    gereken = math.ceil(2 * float(toplam_sure or 0) / float(ust)) if float(ust or 0) > 0 else 0
    return max(1, int(azami_sahne), gereken)


def _tavana_indir(sahneler, azami):
    """Tavanı aşan planı **metin atmadan** küçült: süresi en kısa komşu çift birleşir.

    Eskiden liste dilimleniyordu (`[:azami]`) ve fazla sahnelerin anlatımı sessizce
    kayboluyordu. Birleşen sahnenin süresi `üst`ü aşarsa ses hizalaması kelime/cümle
    sınırından yeniden böler (bkz. `akis_sahne.sahneleri_zamanla`).
    """
    sahneler = [dict(s) for s in sahneler]
    while len(sahneler) > max(1, int(azami)):
        k = min(range(1, len(sahneler)),
                key=lambda i: float(sahneler[i - 1]["saniye"]) + float(sahneler[i]["saniye"]))
        sahneler[k - 1:k + 1] = [{
            "text": f"{sahneler[k - 1]['text']} {sahneler[k]['text']}".strip(),
            "saniye": float(sahneler[k - 1]["saniye"]) + float(sahneler[k]["saniye"])}]
    return sahneler


# Bölme kuralları (05.10.2026, Greek Mythology 8 Monsters): sahne cümle ortasından
# "…from the cliff, and" / "six sailors…", "gave birth to" / "a monster", "in the" /
# "dark" diye kesiliyordu. Bir parça asılı kalan bir işlev kelimesiyle bitmez; bağlaç
# ve ilgi kelimeleri sonraki parçayı başlatır.
ASILI_KELIMELER = frozenset((
    # İngilizce: tanımlık, edat, iyelik, bağlaç, yardımcı fiil — parça bunlarla bitmez.
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "from", "into",
    "onto", "over", "under", "about", "through", "across", "toward", "towards", "without",
    "his", "her", "its", "their", "my", "your", "our", "this", "that", "these", "those",
    "and", "or", "but", "nor", "so", "as", "than", "if", "when", "while", "until", "because",
    "who", "whom", "whose", "which", "where", "was", "were", "is", "are", "be", "been",
    "had", "has", "have", "would", "could", "should", "will", "can", "not", "very", "no",
    # Türkçe: bağlaç ve edatlar.
    "ve", "ile", "ya", "veya", "ama", "fakat", "ki", "bir", "bu", "şu", "çok", "en",
))
BAGLAC_BASI = frozenset((
    "and", "but", "or", "so", "then", "until", "when", "while", "because", "where", "who",
    "which", "after", "before", "as", "if", "though", "although", "still",
    "ama", "fakat", "çünkü", "sonra", "ve",
))
_NOKTALAMA = '"\'”’)]}'


def _yalin(kelime):
    return kelime.strip(_NOKTALAMA + "(\"'“‘[{").rstrip(".,;:!?…—–").casefold()


def bolme_puani(onceki, sonraki):
    """İki kelime arasından kesmenin uygunluğu: küçük daha iyi, `None` yasak.

    0 cümle sonu · 1 virgül/noktalı virgül/iki nokta/tire · 2 bağlaç ya da ilgi kelimesinin
    önü · 3 sıradan kelime sınırı · `None` önceki kelime asılı kalan bir işlev kelimesi.
    """
    bitis = onceki.rstrip(_NOKTALAMA)
    if bitis.endswith((".", "!", "?", "…")):
        return 0
    if bitis.endswith((",", ";", ":", "—", "–")):
        return 1
    if _yalin(onceki) in ASILI_KELIMELER:
        return None
    if _yalin(sonraki) in BAGLAC_BASI:
        return 2
    return 3


def bolum_basligi_mi(metin):
    """"Number four." · "And finally, number eight." gibi bölüm başlığı mı?

    Başlık bir sonraki bölümün ilk sahnesine aittir; önceki bölümün sahnesine eklenirse
    "…for years. Number four." karesi yanlış canavarı gösterir.
    """
    kelimeler = (metin or "").split()
    if not kelimeler or len(kelimeler) > 6:
        return False
    yalin = [_yalin(k) for k in kelimeler]
    return "number" in yalin[:4] or "numara" in yalin[:4]


def _bolme_noktasi(kelimeler):
    """Sahneyi ikiye bölecek kelime indeksi: en iyi puanlı sınır, eşitlikte ortaya en yakın.

    İki tarafta da en az iki kelime kalır ("…başlayacaktı," / "ve" kırıntısı olmaz).
    """
    orta = len(kelimeler) / 2
    adaylar = []
    for k in range(2, len(kelimeler) - 1):
        puan = bolme_puani(kelimeler[k - 1], kelimeler[k])
        if puan is not None:
            adaylar.append((puan, abs(k - orta), k))
    return min(adaylar)[2] if adaylar else len(kelimeler) // 2


def _plan_normalize(sahneler, toplam_sure, alt, ust, azami_sahne=60):
    """Sahne sürelerini aralığa kırp ve toplamı anlatım süresini karşılayacak hâle getir.

    Süreler içeriğe göre **değişken kalır**; yalnızca hiçbir süre 0,5–üst dışına taşmaz ve
    toplam süre anlatımdan kısa olmaz. Önce boşluğu olan sahnelere oransal olarak süre
    eklenir; bütün sahneler üst sınıra dayandıysa **en uzun sahne ikiye bölünerek** yeni
    kapasite açılır (video kesinlikle anlatımdan kısa kalmaz).
    """
    alt, ust = float(alt), float(ust)
    if ust < alt:
        alt, ust = ust, alt
    hedef = max(float(toplam_sure or 0), 0.0)
    azami = sahne_tavani(azami_sahne, hedef, ust)
    for sahne in sahneler:
        sahne["saniye"] = kirp(sahne.get("saniye"), alt, ust)
    for _ in range(400):
        toplam = sum(sahne["saniye"] for sahne in sahneler)
        if not sahneler or hedef <= 0 or toplam + 1e-6 >= hedef:
            break
        # 1) Okunması `üst`ü aşan sahne var mı? (plan anlatımı kapsayamıyor) Varsa en uzun
        # metinli sahne ortaya en yakın cümle sonundan bölünür ve **bütün** süreler okunma
        # uzunluğuna (kelime sayısına) göre yeniden verilir.
        # Eskiden önce boşluk dağıtılıyor, sonra "en uzun süreli" sahne bölünüyordu:
        # süreler `üst`e kırpıldığı için hepsi eşitti, eşitlikte ilk sahne seçiliyordu
        # (05.10.2026, 🎬 plan: "You" / "are on" doğranırken 1088 kelimelik son sahneye
        # dokunulmadı; 22 sahnenin hepsi 6 sn, toplam 132/569 sn).
        kelime = [max(1, len((s.get("text") or "").split())) for s in sahneler]
        birim = hedef / sum(kelime)
        # %15 pay: tavanı azıcık aşan sahne bölünmez (kırıntı üretir); kırpılması yeter.
        uzun = [i for i, k in enumerate(kelime) if k * birim > ust * 1.15 and k >= 4]
        if uzun and len(sahneler) < azami:
            sira = max(uzun, key=lambda i: kelime[i])
            kelimeler = sahneler[sira]["text"].split()
            orta = _bolme_noktasi(kelimeler)
            sahneler[sira:sira + 1] = [{"text": " ".join(kelimeler[:orta])},
                                       {"text": " ".join(kelimeler[orta:])}]
            kelime[sira:sira + 1] = [orta, len(kelimeler) - orta]
            for sahne, k in zip(sahneler, kelime):
                sahne["saniye"] = kirp(k * birim, alt, ust)
            continue
        # 2) Plan anlatımı kapsıyor: kalan küçük eksik, boşluğu olan sahnelere oransal
        # dağıtılır (yapay zekânın verdiği süre farkları korunur).
        pay = [max(0.0, ust - sahne["saniye"]) for sahne in sahneler]
        havuz = sum(pay)
        if havuz <= 1e-6:
            break
        eksik = hedef - toplam
        for sahne, yer in zip(sahneler, pay):
            sahne["saniye"] += min(yer, eksik * yer / havuz)
    for sahne in sahneler:
        sahne["saniye"] = kirp(_yarim(sahne["saniye"]), alt, ust)
    return sahneler


def icerik_sahneleri(metin, toplam_sure, alt, ust, hiz=0, azami_sahne=60):
    """Yapay zekâ olmadan **içerik tabanlı** sahne planı (yedek).

    Bir cümle = bir sahne; süresi kelime sayısına (okunma uzunluğuna) göre değişir. `üst`
    saniyeyi aşan uzun cümle kelime düzeyinde parçalara bölünür. Süreler aralığa kırpılır ve
    toplam anlatım süresini karşılayacak şekilde dengelenir.
    """
    metin = (metin or "").strip()
    cumleler = _cumlelere_bol(metin) or ([metin] if metin else [])
    if not cumleler:
        return []
    alt, ust = float(alt), float(ust)
    if ust < alt:
        alt, ust = ust, alt
    if toplam_sure <= 0:
        toplam_sure = tahmini_sure(metin, hiz)
    toplam_kelime = sum(kelime_sayisi(c) for c in cumleler) or 1
    birim = max(float(toplam_sure), alt) / toplam_kelime    # kelime başına saniye
    sahneler = []
    for cumle in cumleler:
        kelimeler = cumle.split()
        if not kelimeler:
            continue
        dogal = len(kelimeler) * birim
        if dogal > ust:
            # Uzun cümleyi `üst`e yakın parçalara böl; her parça tam cümle olmasa da okunur.
            adet = max(2, int(math.ceil(dogal / ust)))
            boy = max(1, int(math.ceil(len(kelimeler) / adet)))
            for i in range(0, len(kelimeler), boy):
                parca = kelimeler[i:i + boy]
                if not parca:
                    continue
                sahneler.append({"text": " ".join(parca),
                                 "saniye": max(alt, len(parca) * birim)})
        else:
            sahneler.append({"text": cumle, "saniye": max(alt, dogal)})
    tavan = sahne_tavani(azami_sahne, toplam_sure, ust)
    return _plan_normalize(_tavana_indir(sahneler, tavan), toplam_sure, alt, ust, tavan)


def _detay_adimlari(veri, cumleler, alt, ust, notlar=None):
    """Yapay zekâ JSON yanıtını sahne listesine çevir; okunamazsa None döndür.

    Numaralar okunur ama kapsama bozuksa plan atılmaz, onarılır (bkz. `_plan_onar`);
    onarım `notlar`a yazılır.
    """
    if not isinstance(veri, list):
        return None
    kapsanan, sahneler = [], []
    for oge in veri:
        if not isinstance(oge, dict):
            return None
        idler = oge.get("cumleler")
        if not isinstance(idler, (list, tuple)):
            return None
        try:
            idler = [int(i) for i in idler]
        except (TypeError, ValueError):
            return None
        if not idler or any(i < 1 or i > len(cumleler) for i in idler):
            return None
        kapsanan.extend(idler)
        metin = " ".join(cumleler[i - 1] for i in idler).strip()
        if not metin:
            return None
        sahneler.append({"text": metin, "saniye": oge.get("saniye")})
    # Cümlelerin tamamı, sırayla ve bir kez kapsanmalı.
    if kapsanan == list(range(1, len(cumleler) + 1)):
        return sahneler
    return _plan_onar(veri, cumleler, notlar)


def _plan_onar(veri, cumleler, notlar=None):
    """Numaraları eksik/tekrarlı/sırasız planı gruplama niyetini koruyarak onar.

    Eskiden tek bir numara hatası **bütün planı** attırıp içerik yedeğine düşürüyordu
    (29.09.2026: 14 cümlelik metinde plan reddedildi, sahne gruplaması kayboldu). Her
    grubun **ilk** cümlesi bir sahne başlangıcı sayılır; sahneler bu başlangıçlardan
    ardışık aralıklar olarak yeniden kurulur. Böylece atlanan cümle bir önceki sahneye
    katılır, tekrar eden cümle bir kez kullanılır. Süre, başlangıcı taşıyan grubun
    süresidir (sonra `_plan_normalize` ve ses hizalaması düzeltir).
    """
    baslar = {}
    for oge in veri:
        idler = [int(i) for i in oge["cumleler"]]
        bas = min(idler)
        baslar.setdefault(bas, oge.get("saniye"))
    baslar[1] = baslar.get(1, next(iter(baslar.values()), None))
    sirali = sorted(baslar)
    sahneler = []
    for k, bas in enumerate(sirali):
        son = sirali[k + 1] if k + 1 < len(sirali) else len(cumleler) + 1
        sahneler.append({"text": " ".join(cumleler[bas - 1:son - 1]).strip(),
                         "saniye": baslar[bas]})
    if notlar is not None:
        notlar.append(f"yapay zekâ planındaki cümle numaraları eksik/tekrarlı çıktı; "
                      f"gruplama korunarak onarıldı ({len(sahneler)} sahne)")
    return sahneler


def sahneleri_sureye_uydur(sahneler, toplam_sure, alt, ust, azami_sahne=60):
    """Sahne sürelerini toplam anlatım süresine yetiştir (bkz. `_plan_normalize`).

    Yapay zekâ planı zaten `sahne_plani_detayli` içinde dengelenir; bu sarmalayıcı
    **hazır bir plan** akışa verildiğinde (ör. ana sayfa planı, hizalama yapılamadığında)
    sürelerin ses süresine uydurulması için dışarıya açılır.
    """
    return _plan_normalize(sahneler, toplam_sure, alt, ust, azami_sahne)


def plan_izi(metin, strateji):
    """Ana sayfada üretilen planı **anlatıma ve stratejiye** bağlayan kısa iz.

    Anlatım ya da strateji değişirse iz de değişir; akış, eline geçen planı yalnızca
    kendi iziyle eşleşiyorsa kullanır (bkz. `plan_sahneleri`).
    """
    temiz = " ".join((metin or "").split())
    anahtar = strateji_normallestir(strateji) + "\n" + temiz
    return hashlib.sha1(anahtar.encode("utf-8")).hexdigest()[:12]


def plan_kaydi(metin, strateji, sahneler, tavan=None):
    """Ana sayfada üretilen sahne planını akışa taşınacak sade kayda çevir.

    Arayüz planı bir `State`te bu biçimde tutar; akış `plan_sahneleri` ile doğrulayıp
    **aynen** kullanır. Böylece "ana sayfada planla" ile "üretim" arasında ikinci bir
    yapay zekâ isteği olmaz ve sahne sayısı değişmez.
    """
    return {"iz": plan_izi(metin, strateji), "strateji": strateji_normallestir(strateji),
            "tavan": float(tavan or 0),
            "sahneler": [{"text": str(s.get("text") or "").strip(),
                          "saniye": float(s.get("saniye") or 0)}
                         for s in (sahneler or [])
                         if str(s.get("text") or "").strip()]}


def plan_sahneleri(kayit, metin, strateji):
    """Kayıt **bu** anlatıma ve stratejiye aitse sahne listesini döndür, değilse `None`.

    İki kapı vardır: iz eşleşmesi (metin + strateji) ve sahne metinlerinin anlatımı
    kelime kelime kapsaması. Böylece metni değişmiş bir projeye eski plan uygulanmaz.
    """
    if not isinstance(kayit, dict) or kayit.get("iz") != plan_izi(metin, strateji):
        return None
    sahneler = kayit.get("sahneler")
    if not isinstance(sahneler, list) or not sahneler:
        return None
    if sum(len(str(s.get("text") or "").split()) for s in sahneler) != len(
            (metin or "").split()):
        return None
    return sahneler


def sahne_plani_detayli(provider, anahtar, model, metin, dil, sinirlar,
                        toplam_sure=None, hiz=0, azami_sahne=60, bildir=None, ai=None,
                        strateji=VARSAYILAN_STRATEJI):
    """Anlatımı içerik sınırlarına göre sahnelere böl ve **her sahneye ayrı süre** ver.

    Yapay zekâ ardışık cümleleri sahnelere gruplar ve her sahneye temposuna uygun bir süre
    yazar; süreler 0,5–`üst` aralığında kalır ve toplam anlatım süresini karşılar. Yapay
    zekâ yanıt vermezse ya da geçersiz bir plan döndürürse `icerik_sahneleri` yedeğine düşülür.

    Dönen sözlük: `adimlar` (`[{text, saniye}]`), `toplam_sure`, `kaynak` (`ai`/`icerik`),
    `gerekce`.
    """
    metin = (metin or "").strip()
    if not metin:
        raise ValueError("Önce anlatım metnini yaz: sahne planı metne göre çıkarılır.")
    alt, ust = float(sinirlar[0]), float(sinirlar[1])
    if ust < alt:
        alt, ust = ust, alt
    if not toplam_sure or float(toplam_sure) <= 0:
        toplam_sure = tahmini_sure(metin, hiz)
    toplam_sure = float(toplam_sure)
    cumleler = _cumlelere_bol(metin) or [metin]
    numarali = "\n".join(f"{i}. {c}" for i, c in enumerate(cumleler, 1))
    strateji = strateji_normallestir(strateji)
    istek = (f"Narration language: {dil}\n"
             f"Estimated spoken duration: {toplam_sure:.1f} seconds\n"
             f"Allowed scene duration: {alt:g}-{ust:g} seconds\n"
             f"Selected scene planning strategy: {strateji}\n"
             f"Numbered sentences:\n{numarali}")
    kaynak, gerekce, sahneler = "icerik", "", None
    try:
        sistem = (SAHNE_DETAY_SISTEM.format(alt=f"{alt:g}", ust=f"{ust:g}")
                  + "\n\n" + strateji_kurallari(strateji))
        cevap = (ai or metin_ai.VARSAYILAN).metin(provider, anahtar, model,
                         sistem,
                         istek, json_modu=True, bildir=bildir)
        onarim = []
        sahneler = _detay_adimlari(json_listesi(cevap), cumleler, alt, ust, notlar=onarim)
        if sahneler:
            kaynak = "ai"
            gerekce = "; ".join(onarim)
        else:
            # İçerik yedeğine düşmek **sessiz olmaz**: eskiden yanıt şemaya uymadığında
            # sebep boş kalıyor, günlükte yalnızca "kaynak: içerik" yazıyordu ve kullanıcı
            # sahne sayısının neden değiştiğini göremiyordu (bkz. `_detay_adimlari`).
            gerekce = ("yapay zekâ planı şemaya uymadı (cümle numaraları eksik/bozuk); "
                       "içerik yedeği kullanıldı · yanıt: "
                       + " ".join(str(cevap or "").split())[:120])
    except Exception as exc:
        gerekce = f"yapay zekâ planı alınamadı ({type(exc).__name__}); içerik yedeği kullanıldı"
    if not sahneler:
        sahneler = icerik_sahneleri(metin, toplam_sure, alt, ust, hiz=hiz,
                                    azami_sahne=azami_sahne)
    else:
        tavan = sahne_tavani(azami_sahne, toplam_sure, ust)
        sahneler = _plan_normalize(_tavana_indir(
            [dict(s, saniye=kirp(s.get("saniye"), alt, ust)) for s in sahneler], tavan),
            toplam_sure, alt, ust, tavan)
    return {"adimlar": sahneler, "toplam_sure": round(sum(s["saniye"] for s in sahneler), 2),
            "kaynak": kaynak, "gerekce": gerekce}


class Sahneleyici:
    """Belirli bir metin yapay zekâsı ve ses üreticiyle bağlı sahneleyici."""

    def __init__(self, ai=None, ses=None):
        self.ai = ai or metin_ai.VARSAYILAN
        self.ses = ses or ses_uretim.VARSAYILAN

    def parcalar(self, metin, toplam_sure, parca_saniye=PARCA_SANIYE):
        return parcalara_bol(metin, toplam_sure, parca_saniye)

    def icerik_plani(self, metin, toplam_sure, alt, ust, hiz=0, azami_sahne=60):
        return icerik_sahneleri(metin, toplam_sure, alt, ust, hiz=hiz, azami_sahne=azami_sahne)

    def plan(self, provider, anahtar, model, metin, dil, sinirlar, **secenekler):
        return sahne_plani_detayli(provider, anahtar, model, metin, dil, sinirlar,
                                   ai=self.ai, **secenekler)
