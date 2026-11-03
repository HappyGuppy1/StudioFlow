"""Sahne sözleşmesi: plan, kare ve hareketin ortak doğrulanabilir kararları."""
import hashlib
import json
import re
from pathlib import Path

from studioflow.proje.sahne_stratejileri import (
    STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT, strateji_normallestir)

SURUM = 2
PLAN_KURALI = """
Before writing a segment's prompts, decide its scene_plan (a key inside that segment's
element) with these fields: camera; body_pose; time_of_day: one lighting/time condition;
location: a concrete location; main_action: ONE physically possible action; continuity:
recurring object/body/route features to keep; motion: the one camera or subject motion.
The selected strategy decides the camera, whatever the brief or style says about cameras;
the scene's time_of_day decides the light, whatever the style says about dawn or sunset.
One body position and one main action per clip; a steady view is allowed after scene 1.
Keep the same object shape, route and character details through the whole narration.
Describe complete frames, never edit commands such as 'replace X' or 'add X'. Preserve
story facts; do not invent exact historical measurements, material species or dialogue.
"""


# Birinci kişiye özel plan kuralı. **Yalnızca** `birinci_kisi` istemine eklenir;
# tarih (gözlemci) stratejisinde bu metin hiç gönderilmez (bkz. `plan_kurali`).
# El/kol/alt beden görünürlüğüne dair kısıt **yoktur** (29.09.2026): hangi uzvun
# karede olacağına anlatılan eylem karar verir; tek şart kameranın gözler olmasıdır.
PLAN_KURALI_BIRINCI_KISI = """
For first_person all scenes use camera='first_person': the camera is the narrator's eyes.
There is no forced opening pose and no rule about which own limbs must appear or stay out
of frame; the narrated action decides it.
"""

# Tarih (gözlemci) stratejisine özel plan kuralı: kamera dışarıdadır, anlatıcı bedeni yoktur.
PLAN_KURALI_TARIH = """
For history use camera='observer', an external/witness camera appropriate to the narration.
"""

# Default (filtresiz) stratejide kamera kuralı yoktur; plan alanı yalnızca kayıt için "free".
PLAN_KURALI_DEFAULT = """
For default use camera='free': no camera rule; pick the framing that best shows each scene.
"""


def plan_kurali(strateji):
    """Ortak plan kuralını stratejiye özel kamera kuralıyla birleştir.

    `PLAN_KURALI` iki stratejide de geçerlidir; birinci kişi kuralı yalnızca
    `birinci_kisi` istemine, gözlemci kuralı yalnızca tarih istemine eklenir.
    """
    secili = strateji_normallestir(strateji)
    if secili == STRATEJI_BIRINCI_KISI:
        return PLAN_KURALI + PLAN_KURALI_BIRINCI_KISI
    if secili == STRATEJI_DEFAULT:
        return PLAN_KURALI + PLAN_KURALI_DEFAULT
    return PLAN_KURALI + PLAN_KURALI_TARIH


# Stratejinin plandaki kamera değeri; tarih (ve bilinmeyen) `observer`dır.
PLAN_KAMERASI = {STRATEJI_BIRINCI_KISI: "first_person", STRATEJI_DEFAULT: "free"}


def plan_sablonu(strateji=STRATEJI_BIRINCI_KISI, negatif_destekli=True):
    """Yanıtın **tek** JSON şablonu: scene_plan her öğenin içinde, alanları doldurulmuş.

    Ölçüm (27.09.2026, piramit 7-12 grubu, Workers AI qwen3-30b): model diziyi doğru
    yazdı ama altı kaydın hiçbirine `scene_plan` koymadı; sistem mesajının başındaki
    plansız şablonu izledi. O zaman çözüm, sona "önceki şablonun yerine geçer" diye
    ikinci bir şablon eklemekti; mesajda iki çelişen şablon kaldı. Artık mesajda
    yalnızca bu şablon vardır (bkz. `adim_promptlari.sistem_mesaji`). Kamera değeri
    seçili stratejiden yazılır; model iki seçenek arasında karar vermez.
    """
    kamera = PLAN_KAMERASI.get(strateji_normallestir(strateji), "observer")
    negatif = '"negative_prompt": "...", ' if negatif_destekli else ""
    return (
        "\nReply ONLY with ONE flat JSON array, one element per segment in the order given, no "
        "markdown fences or comments. scene_plan is a KEY INSIDE each element, never a "
        "separate element and never omitted; fill every plan field before that segment's "
        "prompts:\n"
        '[{"index": 7,\n'
        f'  "scene_plan": {{"camera": "{kamera}", "body_pose": "standing",\n'
        '                 "time_of_day": "<one lighting/time condition>",\n'
        '                 "location": "<one concrete location>",\n'
        '                 "main_action": "<one physically possible action>",\n'
        '                 "continuity": "<recurring object/body/route features>",\n'
        '                 "motion": "<one camera or subject motion>"},\n'
        f'  "image_prompt": "...", {negatif}"video_prompt": "..."}}]\n'
        f"camera is always {kamera}; body_pose is one of standing|walking|seated|kneeling|"
        "crouched|lying|other.\n")


PLAN_SABLONU = plan_sablonu()


# Eski kayıtlarda `lying_waking` duruşu vardır; okunurken geçerli sayılır ama artık istenmez.
BEDEN_POZLARI = ("standing", "walking", "seated", "kneeling", "crouched", "lying", "other",
                 "lying_waking")


def plan_dogrula(plan, strateji, ilk=False, ozel_acilis=False):
    """Sahne planını doğrula ve temiz kopyasını döndür.

    El/kol/alt beden alanları (`hands`, `hand_count`, `hand_action`, `lower_body`)
    **kaldırıldı** (29.09.2026): eski kayıtlarda bulunsalar da okunmaz, doğrulanmaz.
    Tek strateji kapısı kameradır: birinci kişide `first_person`, tarihte `observer`.
    `ilk` ve `ozel_acilis` parametreleri API uyumu için durur.
    """
    if not isinstance(plan, dict):
        raise ValueError("Sahne planı eksik; görsel üretimi başlatılmadı.")
    alanlar = ("camera", "body_pose", "time_of_day", "location", "main_action",
               "continuity", "motion")
    sonuc = {}
    for alan in alanlar:
        deger = plan.get(alan)
        if not isinstance(deger, str) or not deger.strip() or len(deger) > 600:
            raise ValueError(f"Sahne planında geçersiz alan: {alan}")
        sonuc[alan] = " ".join(deger.split())
    if sonuc["camera"] not in ("first_person", "observer", "free"):
        raise ValueError("Sahne kamera kararı geçersiz.")
    if sonuc["body_pose"] not in BEDEN_POZLARI:
        raise ValueError("Sahne beden pozisyonu geçersiz.")
    secili = strateji_normallestir(strateji)
    # Default filtresizdir: kamera kapısı yok, hangi değer yazıldıysa kabul edilir.
    if secili == STRATEJI_BIRINCI_KISI and sonuc["camera"] != "first_person":
        raise ValueError("Birinci kişi stratejisi dış kamera planı kabul etmez.")
    if secili not in (STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT) and sonuc["camera"] != "observer":
        raise ValueError("Tarih stratejisi gözlemci kamera planı kullanmalı.")
    sonuc.update(version=SURUM, strategy=strateji_normallestir(strateji))
    return sonuc


def stil_arindir(stil):
    """Zaman ve bakış açısı talimatları stil yoluyla sahne kararını ezmesin."""
    zaman = re.compile(r"\b(dawn|sunrise|sunset|midday|noon|morning|afternoon|evening|"
                       r"night|golden hour|blue hour|şafak|sabah|öğle|akşam|gece)\b", re.I)
    kamera = re.compile(r"\b(first[- ]person|third[- ]person|POV|selfie|drone|"
                        r"external camera|birinci kişi)\b", re.I)
    return ", ".join(s.strip() for s in re.split(r"[,;\n]", stil or "")
                     if s.strip() and not zaman.search(s) and not kamera.search(s))


def kare_izi(dosya, adim):
    """Kare veya hareket/plan elle değişirse önceki onay geçersiz olur."""
    ozet = hashlib.sha256(Path(dosya).read_bytes())
    alanlar = {k: adim.get(k) for k in
               ("sahne_plani", "image_prompt", "video_prompt", "start", "end",
                "sureklilik_kare", "sureklilik_izi")}
    # Boş süreklilik alanları proje.txt'e yazılmaz. Bellekteki "" ile diskten
    # okunan eksik alan aynı olmalı; aksi hâlde onay her açılışta bozulur.
    for alan in ("sureklilik_kare", "sureklilik_izi"):
        alanlar[alan] = alanlar[alan] or None
    ozet.update(json.dumps(alanlar,
                          sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return ozet.hexdigest()
