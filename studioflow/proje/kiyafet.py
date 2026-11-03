"""Dönem/kıyafet ön kontrolü: Tarih ve Birinci kişi stratejilerinde prompt'tan ÖNCE çalışır.

Default stratejisi **filtresizdir**: tarihe özgü hiçbir kural eklemez, bu yüzden dönem/
kıyafet/ortam analizi orada hiç çalışmaz ve hakeme de verilmez (bkz. `filtre_acik`).
"""
import hashlib
import json

from studioflow.cekirdek.metin import kelime_kirp
from studioflow.hikaye.istemler import TASARIM_DONEM, TASARIM_KIYAFET
from studioflow.proje.json_yardim import json_listesi
from studioflow.proje.sahne_stratejileri import STRATEJI_TARIH, strateji_normallestir
from studioflow.saglayicilar import metin_ai

# 2: analiz dönemin mimari/ortam tanımını (`mimari`) da taşır. Sürüm önbellek izine
# girdiği için eski analizler bir kez yeniden üretilir.
SURUM = 2


def filtre_acik(strateji):
    """Dönem/kıyafet/ortam filtresi bu stratejide çalışır mı? **Yalnızca Tarih.**

    Kural kodda yoktu: Default (filtresiz) strateji eklendiğinde analiz koşulsuz
    çalışmaya devam etti; tarihsel sayılan bir çizgi filmde kıyafet süzgeci prompt'ları
    yeniden yazabiliyordu. 05.10.2026: kullanıcı kararıyla Birinci kişide de kapalı;
    orada yalnızca bakış açısı filtresi çalışır.
    """
    return strateji_normallestir(strateji) == STRATEJI_TARIH
# Mimari tanımının üst sınırı: her sahneye girebilecek kadar kısa kalmalı.
MIMARI_KELIME = 30


def _nesne(cevap):
    if isinstance(cevap, dict):
        return cevap
    try:
        metin = str(cevap or "")
        veri = json.loads(metin[metin.index("{"):metin.rindex("}") + 1])
    except (ValueError, TypeError):
        raise ValueError("Dönem/kıyafet analizi okunamadı; prompt üretimi başlatılmadı.")
    if not isinstance(veri, dict):
        raise ValueError("Dönem/kıyafet analizi nesne olmalı.")
    return veri


def baglam(veri):
    video = veri.get("ayarlar", {}).get("video", {})
    return {"narration": veri.get("metin", ""), "brief": video.get("genel", ""),
            "opening": video.get("ilk_prompt", ""), "version": SURUM}


def analiz_hazirla(veri, provider, anahtar, model, **secenekler):
    """Önbellek yalnızca aynı anlatım/brief/açılış için kullanılır; hata sessiz atlanmaz."""
    kaynak = json.dumps(baglam(veri), ensure_ascii=False, sort_keys=True)
    iz = hashlib.sha256(kaynak.encode("utf-8")).hexdigest()
    onceki = veri.get("kiyafet_analizi")
    if isinstance(onceki, dict) and onceki.get("iz") == iz:
        if onceki.get("tarihsel") is False or (
                onceki.get("tarihsel") is True and onceki.get("kilit")):
            return onceki
    # `TASARIM_DONEM` araştırma raporu için yazıldı ("yalnızca raporu kullan, bellekten
    # ekleme"). Burada girdi brief ve anlatımdır; o kural dönemi zayıf ya da "tarihsel
    # değil" çıkarabiliyordu. Ön kontrol için genel tarih bilgisi açıkça serbest bırakılır.
    donem = _nesne(metin_ai.VARSAYILAN.metin(
        provider, anahtar, model, TASARIM_DONEM + (
            "\nProject preflight: the input is a project brief and narration, not a research "
            "report. Identify the era and place from them, using general historical knowledge "
            "to date it; cite nothing and leave 'kaynak' empty."),
        "Project context (source for era detection, not a scene plan):\n" + kaynak,
        json_modu=True, **secenekler))
    if type(donem.get("tarihsel")) is not bool:
        raise ValueError("Dönem analizi tarihsel bilgisini vermedi; prompt üretimi durdu.")
    sonuc = {"iz": iz, "version": SURUM, "tarihsel": donem["tarihsel"],
             "donem": str(donem.get("donem") or ""),
             "neden": str(donem.get("neden") or ""), "kilit": "", "kacin": []}
    if donem["tarihsel"]:
        if not sonuc["donem"].strip():
            raise ValueError("Tarihsel projenin dönemi eksik; kıyafet analizi yapılamadı.")
        sistem = TASARIM_KIYAFET + (
            "\nProject preflight: the input may be a brief and narration rather than a research "
            "report. For an identified historical era use conservative period-appropriate "
            "knowledge even if clothing is not explicitly described. Do not invent citations. "
            "Describe the actual roles/class/occupation, not royal clothing for workers. "
            "Different roles may wear different garments. Never equate the material linen "
            "with modern linen trousers or shirts. This analysis does not force hidden "
            "body parts, faces or extra people into images. Do not create scenes.\n"
            "Also return \"mimari\": ONE positive sentence, at most "
            f"{MIMARI_KELIME} words, describing the period setting of this era and place: "
            "building types and materials, construction state, tools and everyday objects "
            "(e.g. 'mudbrick houses with flat reed roofs, copper chisels, wooden sledges, "
            "limestone blocks, clay beer jugs'). Always name the material of vessels "
            "('clay beer jug', never a bare 'beer jar'). Describe only what existed; never "
            "list what did not.")
        kiyafet = _nesne(metin_ai.VARSAYILAN.metin(
            provider, anahtar, model, sistem,
            "ERA:\n" + json.dumps(donem, ensure_ascii=False) + "\nCONTEXT:\n" + kaynak,
            json_modu=True, **secenekler))
        kilit = " ".join(str(kiyafet.get("kilit") or "").split())
        if not kilit or len(kilit.split()) > 40:
            raise ValueError("Tarihsel kıyafet tanımı eksik veya aşırı uzun; prompt üretimi durdu.")
        kacin = kiyafet.get("kacin", [])
        if not isinstance(kacin, list) or any(not isinstance(k, str) for k in kacin):
            raise ValueError("Döneme aykırı kıyafet listesi okunamadı.")
        # Mimari tanımı zorunlu değildir (eksikse üretim durmaz); uzunsa kırpılır.
        mimari = kiyafet.get("mimari")
        mimari = kelime_kirp(mimari, MIMARI_KELIME) if isinstance(mimari, str) else ""
        sonuc.update(kilit=kilit, kacin=[k.strip() for k in kacin if k.strip()],
                     mimari=mimari)
    veri["kiyafet_analizi"] = sonuc
    return sonuc


# Birinci kişide kıyafet tanımı **anlatıcıya bütünüyle** uygulanırsa kamera bedenin
# dışına çıkar: kalıp "her kişi ne giyer" diye yazılır ("Bare-chested men…, shaved
# heads, sun-darkened skin") ve bu cümle POV prompt'una girince anlatıcının başı ve
# göğsü dışarıdan tarif edilmiş olur. Anlatıcıya yalnızca karede gerçekten görünen
# kendi giysisi/uzvu yazılır; tam tanım karedeki **diğer** kişilere uygulanır.
POV_KIYAFET_KURALI = (
    "FIRST-PERSON: the narrator is the unseen camera. Apply wardrobe to the narrator ONLY as "
    "own garments or limbs actually inside the frame, with ownership ('my linen kilt at the "
    "bottom edge', 'my bare feet'). Never describe the narrator's head, hair, face, neck, "
    "back, skin tone or whole body, and never turn the narrator into a visible subject. "
    "Apply the full period wardrobe to OTHER people visible in the frame.")


# Dönem prompt'a **görünen şeylerle** girer, etiketle değil. claudetest'te (29.09.2026)
# süzgeç her prompt'a "Old Kingdom Egypt, Fourth Dynasty, 2560 BCE. Bare-chested men…"
# kalıbını yapıştırdı: insan olmayan kareye bile işçi girdi, mimari listesindeki piramit
# iç mekân sahnesini açık havaya taşıdı (hasır elde sokakta kaldı).
DONEM_YAZIM_KURALI = (
    "Never write dates, dynasty names or era labels into an image prompt; an image model "
    "cannot draw them. Show the period through visible garments, buildings and objects. Use "
    "only the 'mimari' items that belong to this scene's own location (an indoor room keeps "
    "its walls, mats and jars; the pyramid, ramps and sledges belong outdoors); never move a "
    "scene to another place, never later-era or other-culture architecture, and an unfinished "
    "monument stays unfinished. Always name the material of vessels and containers ('clay beer "
    "jug', 'reed basket', 'wooden bowl'): a bare 'jar' or 'bottle' becomes modern glass.")


def kiyafet_baglami(analiz, pov=False, yasaklar=True):
    """Prompt isteğine eklenecek kıyafet bağlamı (tarihsel değilse boş).

    `yasaklar=False` (negatif almayan model): döneme aykırı öğe listesi (`kacin`)
    yazılmaz. Negatif alanı olmayan modelde bu liste ancak olumsuz cümle olarak
    ("no hats") pozitif prompt'a sızabiliyordu; görsel modeli de adı geçeni çizer.
    """
    if not analiz or analiz.get("tarihsel") is not True:
        return ""
    gorunen = analiz if yasaklar else {k: v for k, v in analiz.items() if k != "kacin"}
    return (
        "PERIOD WARDROBE PREFLIGHT (applies to visible clothing only):\n"
        + json.dumps(gorunen, ensure_ascii=False)
        + "\nWhere people are clearly visible, name their garments in a few positive words "
        "(about 8 at most), including background workers. Describe only what IS worn, never "
        "what is not ('no hats'). " + DONEM_YAZIM_KURALI + " "
        "Preserve the planned crop: do not reveal hidden faces, heads, "
        "legs or torsos just to show costume; bare forearms may suffice in hand close-ups. "
        "Previous prompts "
        "with anachronistic clothes are not continuity references for wardrobe. Do not "
        "change scene boundaries, actions or locations."
        + ("\n" + POV_KIYAFET_KURALI if pov else ""))


def promptlari_suz(kayitlar, analiz, provider, anahtar, model, *, kelime_siniri=100,
                  hedef=None, pov=False, **secenekler):
    """Üretilen pozitif metni ayrıca kontrol et; plan/indeks/hareket alanlarına dokunma.

    `pov` birinci kişi stratejisinde verilir: kıyafet anlatıcıya yalnızca karede görünen
    kendi giysisi olarak yazılır (bkz. `POV_KIYAFET_KURALI`). `hedef` yazdırılan kelime
    sayısıdır; `kelime_siniri`ni aşan yanıt artık üretimi durdurmaz, kuyruğu kırpılır
    (dil modeli kelime sayamaz; bir kelime taşma bütün grubu düşürüyordu).
    """
    if not kiyafet_baglami(analiz):
        return kayitlar
    if not isinstance(kayitlar, list) or not kayitlar:
        raise ValueError("Kıyafet süzgecine geçerli prompt listesi gelmedi.")
    sistem = (
        "You check historical wardrobe in EXISTING image prompts before image generation. "
        "Return ONLY a JSON array with the SAME indexes, each with index and image_prompt. "
        "Correct anachronistic or vague garments using the supplied period wardrobe, and "
        "anachronistic or other-culture buildings, tools and objects using its 'mimari' "
        "description. "
        "Keep POV, visible limb counts, pose, main action, objects, location and lighting "
        "unchanged. Never add hidden anatomy or extra people. "
        "For first-person prompts preserve the opening viewpoint and ownership ('my hand', "
        "'my lap'); describe only the clothing actually visible. Never insert a separate "
        "'laborer', a head, haircut or full-body description of the unseen viewer. "
        "Add SHORT positive garment words (about 8 at most) only for people who are clearly "
        "visible; never add people. A prompt that is already correct is returned unchanged. "
        + DONEM_YAZIM_KURALI + " "
        "Write only what IS worn or visible; never add what is absent ('no hats', 'without "
        "shirts') because image models draw every thing a prompt names. "
        f"Aim for about {int(hedef or kelime_siniri)} words per image_prompt (hard maximum "
        f"{int(kelime_siniri)}). "
        "Do not create, combine, split or renumber segments."
        + (" " + POV_KIYAFET_KURALI if pov else ""))
    cevap = metin_ai.VARSAYILAN.metin(
        provider, anahtar, model, sistem,
        kiyafet_baglami(analiz, pov) + "\nEXISTING PROMPTS:\n"
        + json.dumps(kayitlar, ensure_ascii=False), json_modu=True, **secenekler)
    duzeltilen = json_listesi(cevap)
    if not isinstance(duzeltilen, list) or len(duzeltilen) != len(kayitlar):
        raise ValueError("Kıyafet süzgeci eksik yanıt verdi; görsel üretimi durdu.")
    indeksler = [str(k.get("index")) for k in kayitlar]
    gelen = [str(k.get("index")) for k in duzeltilen if isinstance(k, dict)]
    if sorted(gelen) != sorted(indeksler) or len(set(gelen)) != len(gelen):
        raise ValueError("Kıyafet süzgeci sahne indekslerini değiştirdi.")
    eslesen = {str(k["index"]): k for k in duzeltilen}
    sonuc = []
    for kayit in kayitlar:
        prompt = eslesen[str(kayit["index"])].get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Kıyafet süzgeci boş prompt verdi.")
        sonuc.append(dict(kayit, image_prompt=kelime_kirp(prompt, kelime_siniri)))
    return sonuc
