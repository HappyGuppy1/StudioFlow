"""Seslendirme şablonları: biçim (Shorts…) → alt şablon (Tarihî anlatım…) → bölüm planı.

Bir alt şablon, anlatımın **bölümlerini** (sıra, zaman aralığı, görev) ve bütün metne
uygulanan **kuralları** taşır. Bölümlerin süresi hedef süreden hesaplanır; kelime
bütçesi `süre × KELIME_HIZI`dır (saniyede ~2,2 kelime, ölçülen Gemini hızı; `proje/sahneleme.py`).

**Shorts › Tarihî anlatım** `docs/TARIH-SHORTS-STRATEJISI.md` belgesine dayanır:
beş bölüm (6.2), süre/kelime bütçesi (6.1), yapı seçimi (6.3), doğruluk (6.4) ve prompt
şablonu (7). Kurallar yapay zekâya İngilizce verilir (talimata en tutarlı böyle uyuyor);
metnin dili ayrıca seçilir.

Yeni şablon eklemek: `SABLONLAR`a bir biçim ya da mevcut biçime bir `alt` kaydı.
"""
from studioflow.proje.sahneleme import KELIME_HIZI

# Shorts en fazla 3 dakika (strateji 2.2). Alt sınır 30 sn: daha kısa sürede kanca (3 sn)
# ve bağlam (7 sn) videonun yarısını kaplıyor, gelişmeye yer kalmıyor.
SURE_ARALIGI = (30, 180)
VARSAYILAN_SURE = 70

# ── Shorts › Tarihî anlatım ──────────────────────────────────────────────────
# Bölüm sınırları hedef süreye (T) göre: kanca 0–3 sn, bağlam 3–10 sn, gelişme
# 10 sn → %75, doruk %75–90, sonuç son %10 (strateji 6.2).
TARIH_BOLUMLERI = (
    {"ad": "kanca", "etiket": "Kanca", "bas": lambda t: 0, "son": lambda t: 3,
     "kelime_ust": 12,
     "gorev": (
         "ONE sentence, at most 12 words, that opens a specific information gap. The story starts "
         "with the first word: no greeting, no 'today I will tell you', no 'have you ever "
         "wondered'. Include something concrete (a name, date, number or object). Combine a "
         "familiar thing with an unknown detail. Use the hook type chosen in the plan. It must be "
         "true and it must be answered later. Do NOT spend the biggest surprise here.")},
    {"ad": "baglam", "etiket": "Bağlam", "bas": lambda t: 3, "son": lambda t: 10,
     "gorev": (
         "1-2 sentences: who, where, when, with the minimum information. Introduce ONE human "
         "(ruler, soldier, engineer, witness) and his or her GOAL. No history-lesson background.")},
    {"ad": "gelisme", "etiket": "Gelişme", "bas": lambda t: 10, "son": lambda t: 0.75 * t,
     "gorev": (
         "A cause-and-effect chain: connect events with 'but' and 'so' (Turkish: 'ama', 'bu "
         "yüzden'), never with 'and then' (obstacle -> solution -> new obstacle). A new piece of "
         "information every 1-2 sentences (every 5-8 seconds). Concrete details and numbers, but "
         "at most one number per sentence. Tension rises. Keep the plan's surprise hidden.")},
    {"ad": "doruk", "etiket": "Doruk", "bas": lambda t: 0.75 * t, "son": lambda t: 0.9 * t,
     "gorev": (
         "The emotionally most intense moment. Reveal the most surprising detail HERE (the "
         "plan's surprise). Target emotion: awe / admiration ('how did a human do this?').")},
    {"ad": "sonuc", "etiket": "Sonuç", "bas": lambda t: 0.9 * t, "son": lambda t: t,
     "gorev": (
         "Answer the question opened by the hook EXPLICITLY. End with one short, strong, "
         "memorable sentence (a result, an irony, a link to today). Optionally the last sentence "
         "flows naturally back into the first sentence (loop). No call to action.")},
)

TARIH_KURALLARI = """STRATEGY (history Shorts narration; evidence-based):
- Viewers decide in the first 1-3 seconds; attention must be renewed every few seconds.
- Tell ONE human's story: a person -> a goal -> an obstacle -> a result. Not a list of facts.
- Choose the structure by what the audience knows:
  * famous event, result known  -> CURIOSITY: start from the result, then tell HOW;
  * little-known event          -> SUSPENSE: start in the middle of the event, hide the result;
  * a common misconception      -> EXPECTATION-BREAKING hook + evidence + surprise climax.
- In every structure keep the single most surprising detail for the CLIMAX.
- Hook types: expectation-breaking / start from the result / start in the middle of the event /
  hidden knowledge / a specific question (never a generic question).
- Spoken language: short, clear sentences meant to be read aloud. No headings, no stage
  directions, no emojis, no parentheses, no lists.
ACCURACY:
- Use ONLY facts from the research report. Never invent facts, numbers, names or quotes.
- Legends, anecdotes and disputed facts must be marked in the narration ("according to legend",
  "historians disagree" / "rivayete göre", "tarihçiler tartışıyor").
- No invented dialogue presented as a real quote.
- Prefer awe and curiosity; avoid anger narratives that target a community."""

SABLONLAR = {
    "shorts": {
        "etiket": "Shorts",
        "aciklama": "Dikey kısa video (YouTube Shorts · Reels · TikTok), 30–180 sn.",
        "alt": {
            "tarihi_anlatim": {
                "etiket": "Tarihî anlatım",
                "aciklama": ("Kanca → Bağlam → Gelişme → Doruk → Sonuç. Kaynak: "
                             "`docs/TARIH-SHORTS-STRATEJISI.md` (merak boşluğu, doruk-son kuralı, "
                             "en büyük sürpriz doruğa)."),
                "bolumler": TARIH_BOLUMLERI,
                "kurallar": TARIH_KURALLARI,
            },
        },
    },
}
VARSAYILAN_SABLON = "shorts"
VARSAYILAN_ALT = "tarihi_anlatim"


def sablon_secenekleri():
    return [(bilgi["etiket"], ad) for ad, bilgi in SABLONLAR.items()]


def alt_secenekleri(sablon):
    alt = (SABLONLAR.get(sablon) or {}).get("alt") or {}
    return [(bilgi["etiket"], ad) for ad, bilgi in alt.items()]


def alt_sablon(sablon, alt):
    try:
        return SABLONLAR[sablon]["alt"][alt]
    except KeyError:
        raise ValueError("Şablon bulunamadı; listeden bir şablon ve alt şablon seç.") from None


def sure_sinirla(sure):
    try:
        sure = float(sure)
    except (TypeError, ValueError):
        sure = VARSAYILAN_SURE
    return max(SURE_ARALIGI[0], min(SURE_ARALIGI[1], sure))


def bolum_plani(sablon, alt, sure, hiz=KELIME_HIZI):
    """Bölümlerin zaman aralığı ve kelime bütçesi: `[{ad, etiket, bas, son, kelime, gorev}]`.

    Toplam kelime ≈ `süre × hız`; tek istisna kancadır: tek cümledir ve 12 kelimeyi aşmaz.
    """
    sure = sure_sinirla(sure)
    plan = []
    for bolum in alt_sablon(sablon, alt)["bolumler"]:
        bas, son = round(bolum["bas"](sure), 1), round(bolum["son"](sure), 1)
        kelime = max(4, round((son - bas) * hiz))
        if bolum.get("kelime_ust"):
            kelime = min(kelime, bolum["kelime_ust"])
        plan.append({"ad": bolum["ad"], "etiket": bolum["etiket"], "bas": bas, "son": son,
                     "kelime": kelime, "gorev": bolum["gorev"]})
    return plan


def plan_tablosu(plan):
    """Arayüz için Markdown tablo."""
    satirlar = ["| Bölüm | Zaman | Hedef kelime |", "|---|---|---|"]
    satirlar += [f"| {b['etiket']} | {b['bas']:g}–{b['son']:g} sn | ~{b['kelime']} |" for b in plan]
    toplam = sum(b["kelime"] for b in plan)
    satirlar.append(f"| **Toplam** | **{plan[-1]['son']:g} sn** | **~{toplam}** |")
    return "\n".join(satirlar)
