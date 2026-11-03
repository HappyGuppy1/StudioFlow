"""Adımlar için görsel (+/−) ve video prompt'larının yapay zekâya yazdırılması."""
import re

from studioflow.cekirdek.metin import (
    kelime_kirp as _kelime_kirp, kelime_sayisi as _kelime_sayisi, metin as _metin,
    negatif_birlestir as _negatif_birlestir,
    negatif_celiski_ayikla as _negatif_celiski_ayikla, olumsuz_ayikla as _olumsuz_ayikla,
    hedef_kelime as _hedef_kelime, stil_ekle as _stil_ekle,
    stil_ile_birlestir as _stil_ile_birlestir,
    tek_satir as _tek_satir,
    tek_satir_tam as _tek_satir_tam)
from studioflow.proje.json_yardim import json_listesi
from studioflow.proje.karakterler import prompttaki_adlar as _prompttaki_adlar
from studioflow.proje.kiyafet import promptlari_suz
from studioflow.proje.prompt_uretimi import grup_istegi
from studioflow.proje.sabitler import ILK_SAHNE_INDEX, PROMPT_KELIME_SINIRI
from studioflow.proje.sahne_stratejileri import (
    STRATEJI_BIRINCI_KISI, VARSAYILAN_STRATEJI, kendi_el_var, pov_ekle, pov_ihlalleri,
    sahipsiz_uzuv,
    strateji_kurallari, strateji_normallestir)
from studioflow.proje.sahne_kalitesi import plan_dogrula, plan_kurali, plan_sablonu, stil_arindir
from studioflow.saglayicilar import metin_ai

# Sahne planının prompt'a sızan duruş etiketi: yalnızca iki virgül arasında tek başına.
_PLAN_ETIKETI = re.compile(r",\s*other\s*(?=,)", re.IGNORECASE)

# Görsel modelinin prompt'u **harfiyen** çizdiği ölçülen durumlar (Timur projesi,
# SDXL base ve FLUX.2 klein, sabit seed): "winter plain" → karlı arazi (iki modelde
# de), "dusty plain" + "sandstone walls" → kum tepeleri, "red kaftan" → kırmızı
# başörtüsü/pelerin, "mail neck guard" → yüzü kapatan zincir maske, iki ayrı özne
# ("atlı" + "fil sürücüsü") → tek kişi. Zemini somut tarif etmek ("dry brown
# grassland, bare earth") karı iki seed'de de tamamen kaldırdı. Bu dersler prompt'u
# yazan yapay zekâya **kural** olarak verilir.
# İçerik filtresi (14.10.2026, Greek-Mythology): Cloudflare FLUX.2 klein'in çıktı
# filtresi ("Your output has been flagged") göğsü açık Zeus'u (adım 25, 81) ve dişlerini
# gösterip çömelen Medusa'yı (adım 91) üç denemede de reddetti; proje durdu. Aynı tarifli
# kareler bazen geçti, yani risk açık ten ve korku arttıkça büyüyor: son madde bunu önler.
_KARE_KURALLARI = (
    "Image models draw every word literally, so:\n"
    "- One main subject group in the foreground doing ONE clearly visible action; at most one "
    "secondary group, placed explicitly ('behind them', 'in the background'). Name each "
    "separate person or animal separately; never merge two subjects into one.\n"
    "- Describe the ground, vegetation and sky concretely (e.g. 'flat plain of dry brown grass "
    "and bare earth'). Never rely on season words: 'winter' alone becomes snow, 'dusty' or "
    "'sandstone' alone becomes desert dunes.\n"
    "- Describe garments and armour by shape, not only colour (e.g. 'knee-length red wool "
    "coat', 'pointed steel helmet, open face'); when a face must be seen, say so.\n"
    "- Use one lighting that matches the scene's time of day; do not combine contradictory "
    "light (golden hour with hard midday sun).\n"
    "- The first sentence of image_prompt names the scene's location and whether it is inside "
    "or outside ('inside the dark mudbrick barracks', 'outside on the open desert worksite'); "
    "objects stay where they belong (a sleeping mat stays in the sleeping room).\n"
    "- If the narration is abstract (a comment, a question, a summary), still show one "
    "concrete, filmable moment that carries its meaning, in a place the story has reached, "
    "never a copy of the previous frame.\n"
    "- Image models ignore negation and DRAW every thing a prompt names. Never write in "
    "image_prompt what is absent, hidden or outside the frame ('no snow', 'without hats', "
    "'my hands stay outside the frame', 'face not visible'). Describe only what IS visible.\n"
    "- The image service's content filter rejects frames with bare skin or horror, so every "
    "person (gods, heroes and human-bodied monsters too) wears a garment covering chest, "
    "shoulders and hips; name it right next to the person ('Zeus, wearing his white himation "
    "over both shoulders and chest'), even when the character's description or the period "
    "leaves the chest bare. Monsters threaten through posture, size and setting: no bared "
    "fangs or tusks, snarling close-ups, crouching to pounce, blood or wounds.\n"
)

# Melez strateji (05.10.2026): 4 örneklem, 387 kare, FLUX.2 klein 9B, her kare elle
# puanlandı. Zayıf yazım %36 hatalı; çok kısıtlamalı yazım (Ö2) %6 hatalı ama referanslı
# karakterde zayıf; sadeleştirip dönemi atlayan yazım (Ö3) modernleşti; bu blok (Ö4)
# yeni sahnelerde %73 doğru / %6 hatalı, referanslı karakterli karelerde %0 hatalı.
# Rehber: masaüstündeki `Gorsel-Prompt-Yazim-Rehberi.txt`.
_MELEZ_KURALLARI = (
    "Hybrid prompt strategy (measured on 387 frames; apply it to every image_prompt):\n"
    "- Few words in the right place: put the scene's ONE critical condition (a single eye, "
    "a direction, a pose, a count) in the first sentence, right next to the subject it "
    "belongs to. Never pile up several constraints.\n"
    "- Name the period or year once in every image_prompt, even briefly ('in 1850', 'in "
    "ancient Greece'); without it people and objects turn modern.\n"
    "- Build the background positively from period objects ('behind them only wooden houses, "
    "horses and carts'); never write bans such as 'no cars' or 'nothing modern'.\n"
    "- Show scale with framing, not ratios: a giant does not fit in the frame and the people "
    "stand beside one part of it (a foot, a toe, a wheel), 'his body rising out of the top of "
    "the frame'. 'Colossal' or 'reaching to his knee' alone is ignored.\n"
    "- A named cast member alone in the frame gets the word 'alone' ('Perseus alone, "
    "running...'). Never describe a named character a second time with another noun phrase "
    "('the Cyclops, a gigantic monster'): that draws a second copy.\n"
    "- Unusual anatomy (one eye, several heads, no wings): state it briefly next to the "
    "subject, show the creature head-on, facing the viewer, and avoid words that bring a "
    "default body ('dragon' brings wings); prefer the description to a famous name.\n"
    "- Emotion, pose and process are written as the visible body: face, hands, posture, and "
    "a direction tied to a frame edge ('running toward the left edge of the frame'). Show a "
    "frozen moment, not a process ('holding the moon with a bite missing from its edge', "
    "not 'eating the moon').\n"
    "- Two people: 'On the left, A doing X; on the right, B doing Y', each action right "
    "next to its own subject.\n"
    "- Counts: give every counted person, animal or object its own role ('one at the oars, "
    "one standing at the bow').\n"
    "- An extreme close-up of only a body part never uses a cast member's name; describe the "
    "part itself (a named character pulls the whole body into the frame).\n"
    "- A cross-section or cutaway is described on the object itself and kept simple ('the "
    "pyramid cut in half, showing a sloping corridor to a small chamber').\n"
)

# Birinci kişide yukarıdaki genel kare kuralları geçerlidir; yalnızca
# "ön plan özne" anlayışı **anlatıcının kendi bedeni** olarak değişir. Ölçüm (piramit5,
# 28.09.2026): başa eklenen kalıp ("First-person POV, the camera is my eyes") tek başına
# yetmedi, çünkü hemen ardından gelen cümleler anlatıcıyı dışarıdan anlatıyordu
# ("My back presses against cold, rough stone wall", "sun-darkened back muscles tense").
# Aşağıdaki blok, karenin yalnızca gözün görebildiğiyle kurulmasını ister.
_POV_KARE_KURALLARI = (
    "FIRST-PERSON OVERRIDE of the general frame rules:\n"
    "- The narrator is never the visible subject of the frame ('a worker lying on a mat'); "
    "the camera is their eyes. Write only what those eyes can see in that pose, with "
    "ownership for any own body part in frame ('my knees', 'my left palm'). Never describe a "
    "body part the eyes cannot see ('my back', 'my face', 'my head', 'my nape', back muscles, "
    "the whole body seen from outside).\n"
    "- A sensation is shown by its visible evidence: 'stone presses my back' becomes the "
    "rough wall, the rolled cloth and the shadow in front; sun or dust on the skin becomes "
    "the lit limb inside the frame.\n"
    # Eylem kuralı (29.09.2026, claudetest): yasak değil, alaka. Kural yokken yazar
    # "birinci kişiyi kanıtlamak" için 3–7. sahnelerin hepsine "hasırı kavrayan eller"
    # koydu, anlatıcı hep oturdu; 7. sahnede hasırı elinde sokağa çıktı.
    "- The frame follows the narrated ACTION. Own hands, arms, legs or feet enter the frame "
    "only when this segment's action uses them (eating, gripping, pulling, carrying, stepping "
    "onto something) or the narration names them; otherwise the eyes look out at eye level "
    "at the place, the path ahead and the other people. Hands are never added just to prove "
    "the viewpoint.\n"
    "- The body pose follows the narration: once up, the narrator stands, walks or works "
    "unless the narration says they sit or lie.\n"
)



def sistem_mesaji(kelime_siniri=PROMPT_KELIME_SINIRI, negatif_destekli=True,
                  strateji=VARSAYILAN_STRATEJI, hedef=None, plan=False):
    """Prompt yazan yapay zekânın sistem mesajı: **seçili görsel modeline** göre kurulur.

    İki şey modele bağlıdır ve ölçümle ayrıldı:
    - kelime bütçesi: SDXL'in CLIP'i ~55 kelime okur, FLUX'un kodlayıcısı çok daha
      uzun metni okur (bkz. `gorsel_cloudflare.prompt_kelime_siniri`);
    - negatif prompt: FLUX.2 negatif almaz. O modelde "olmaması gereken" her şey
      doğru hâli **olumlu** tarif edilerek önlenmelidir.

    `strateji` de modele bağlıdır ve burada **ezilir**: birinci kişide kare sıralaması
    artık "önce ana özne ve eylemi" değildir. Ölçüm (piramit5, 28.09.2026): genel
    "önce ana özne" kuralı sistem mesajında kaldığı sürece modele sonradan eklenen
    birinci kişi kuralı yalnızca bir "istisna" gibi okundu; promptlar biçim olarak
    kalıpla başlasa da içerik anlatıcının dışına kaydı ("My back presses against
    stone", "sun-darkened back muscles tense"). Bu yüzden birinci kişide çakışan
    genel kural basmak yerine kaldırılır, yerine bakış açısı sıralaması yazılır.

    Denetim listesi (`checklist`) artık **istenmez** (05.10.2026): genel görsel denetim
    kaldırıldı. 160 elle puanlı karede hakem hatalı karelerin yalnızca %47'sini yakaladı,
    doğruların %15'ini reddetti; aynı prompt'la yeniden üretim 31 sahnenin 30'unda aynı
    sonucu verdi. Yerine kareyi baştan doğru kuran melez strateji (`_MELEZ_KURALLARI`)
    yazdırılır.

    `hedef`: yazdırılan **hedef** kelime sayısı (bkz. `metin.hedef_kelime`). Dil modeli
    kelime sayamaz; sınırı sık aşıyordu (piramit/test5: 90–157 kelime) ve kod kuyruğu
    kesiyordu. Hedef sınırın altında tutulunca taşan yanıt da sınıra yetişmez.

    Negatif almayan modelde (FLUX) yapay zekâdan negatif **istenmez**: eskiden "kayıt
    için" yazdırılıyordu; hem gereksiz yazıydı hem de modelin dikkatini yasaklara çekip
    olumsuz cümlelerin pozitif prompt'a sızmasına yol açıyordu.

    Mesaj **tek parça** kurulur (29.09.2026): seçili strateji her zaman buradadır (artık
    kullanıcı mesajında tekrar gitmez); `plan=True` ise plan kuralı ve **tek** JSON
    şablonu (scene_plan içinde) eklenir. Eskiden önce plansız "tam olarak bu anahtarlar,
    fazlası yok" şablonu yazılıp sonra "scene_plan zorunlu, önceki kuralı ezer" ve
    "önceki şablonun yerine geçer" diye iki katman ekleniyordu; birinci kişi kuralları
    da üç kez tekrar ediyordu (~1.470 kelime).
    """
    pov = strateji_normallestir(strateji) == STRATEJI_BIRINCI_KISI
    hedef = int(hedef or kelime_siniri)
    uzunluk = (f"Aim for about {hedef} words (hard maximum {kelime_siniri}; the tail beyond "
               "it is cut).")
    if negatif_destekli:
        negatif_kurali = (
            "2) negative_prompt: a comma-separated list. Always include every item of the "
            "default negative prompt and every forbidden element named in the brief, then add "
            "defects specific to this frame. Never put into it anything this frame must SHOW, "
            "nor a synonym of it: a negative 'burning' erases wanted flames, a negative "
            "'blood' erases a wanted red cloth stain.\n")
        model_notu = (f"one still frame for an SDXL-type image model. {uzunluk} The image "
                      f"model reads only the first {kelime_siniri} words, "
                      "anything after that is ignored. Start with the main subject and its "
                      "action, the period and the key style words, then setting, lighting and "
                      "camera.")
    else:
        negatif_kurali = ""
        model_notu = (f"one still frame for a FLUX-type image model. {uzunluk} Use plain "
                      "descriptive sentences. Start with the main subject and "
                      "its action, then the secondary subject, setting, lighting and camera. "
                      "This model has NO negative prompt: prevent likely mistakes by describing "
                      "the correct version positively inside the prompt (e.g. 'flames only on "
                      "the hay loads; the camels themselves are untouched', 'flat plain of dry "
                      "brown grass and bare earth'). Never name the brief's forbidden elements.")
    kare_kurallari = _KARE_KURALLARI + _MELEZ_KURALLARI
    if pov:
        # Bakış açısı sıralaması `model_notu`na **yazılır**, ek kural olarak eklenmez:
        # aynı sistem mesajında kalan "önce ana özne ve eylemi" cümlesi onu ezip kareyi
        # anlatıcının dışına kaydırıyordu (bkz. fonksiyon docstring'i).
        model_notu = (
            f"one still frame seen through the narrator's own eyes. {uzunluk} Start with the "
            "optical first-person viewpoint (and an own body part only if the action really "
            "puts it inside the frame), then the one visible action, then setting, lighting "
            "and camera. This first-person ordering REPLACES the generic 'start with the main "
            "subject and its action' rule; period, wardrobe and style words come AFTER the "
            "opening sentence, never between the viewpoint and the action.")
        if not negatif_destekli:
            model_notu += (" This model has NO negative prompt: prevent likely mistakes by "
                           "describing the correct version positively inside the prompt. "
                           "Never name the brief's forbidden elements.")
        kare_kurallari = _POV_KARE_KURALLARI + _KARE_KURALLARI + _MELEZ_KURALLARI
    if plan:
        cikti = (strateji_kurallari(strateji) + plan_kurali(strateji)
                 + plan_sablonu(strateji, negatif_destekli))
    else:
        cikti = (strateji_kurallari(strateji)
                 + "Reply ONLY with a JSON array. Every element must be exactly: "
                 '{"index": <int>, "image_prompt": "<string>", '
                 + ('"negative_prompt": "<string>", ' if negatif_destekli else "")
                 + '"video_prompt": "<string>"}. '
                 "Do not add markdown fences, comments or extra keys.")
    katmanlar = ["an overall video brief (story, cast, world, continuity rules, forbidden "
                 "elements and prompt format rules) that holds for the whole video",
                 "an overall visual style"]
    if negatif_destekli:
        katmanlar.append("a default negative prompt")
    katmanlar += ["the full narration for context",
                  "the prompts already written for the previous scenes",
                  "the scenes to write now, each with its own time range"]
    n = 3 if negatif_destekli else 2
    return (
        "You are an expert film director and prompt engineer for AI image and video generators. "
        "You write the prompts for ONE short vertical video, scene by scene, from these layers: "
        + ", ".join(f"{i}) {k}" for i, k in enumerate(katmanlar, 1)) + ".\n"
        "Every prompt must belong to the brief and the style; the scene's narration decides "
        "only WHAT happens in that scene, never the world, look or cast. If no brief is given, "
        "infer one from the narration and stay consistent with it. If the brief gives format "
        "rules, follow them.\n"
        f"For each scene write {'its scene_plan (see below), ' if plan else ''}"
        f"{'three' if negatif_destekli else 'two'} English prompts:\n"
        f"1) image_prompt: {model_notu} Concrete and visual; no text or watermarks. "
        "Keep surfaces clean and smooth: never ask for gold leaf, flaking or peeling paint, "
        "cracks, scratches, dust, grain or floating specks (the video model animates them "
        "as falling snow). The picture fills the whole frame edge to edge: never a border, "
        "frame, ornamental or knotwork margin, vignette edge, medallion, panel or "
        "picture-in-picture; keep decorative patterns on objects and clothing only.\n"
        + negatif_kurali +
        f"{n}) video_prompt: image-to-video motion for this exact frame over the scene's "
        "duration. Under 30 words. One camera move and/or one clear subject motion, simple "
        "and physically plausible; do not re-describe the scene.\n"
        + kare_kurallari +
        "Scene 1 is the hook of the video: make its image the most striking frame of the video "
        "and give it clear motion from the first frame, never a slow static zoom.\n"
        "Keep continuity across all scenes: same characters, wardrobe, palette, location and "
        "lighting as the brief and the previous scenes; reuse the exact same descriptions for "
        "recurring characters, but vary the composition: consecutive segments never repeat the "
        "same pose and framing; alternate wide eye-level views, looking down at an action and "
        "close details. When the brief names period wardrobe or appearance, state it in "
        "a FEW words (garment, headwear, footwear) in every image_prompt where people or "
        "clothing are visible and never introduce clothing the brief does not name; do not "
        "write a long costume catalogue.\n"
        + cikti
    )


SISTEM_MESAJI = sistem_mesaji()


def ilk_sahne_kaydi(video_ayari):
    """Kullanıcının elle yazdığı **ilk sahne** prompt katmanları (yoksa `None`).

    Short'ta ilk kare videonun kancasıdır; yapay zekânın rastgele yazdığı bir kare
    yerine kullanıcı kendi prompt'unu verebilir. Üç katman da opsiyoneldir ve hepsi
    boşsa `None` döner — o zaman davranış eskisiyle birebir aynıdır (prompt'u yapay
    zekâ yazar). `negatif` tek başına da verilebilir: pozitif prompt boşsa yalnızca
    negatif katman uygulanır.

    Görsel stili burada **yoktur**: 1. sahne de projenin genel görsel stilini
    (`video.stil`) kullanır — prompt'u yazan yapay zekâ o stili zaten bütün sahnelere
    işler, ayrıca yazmak hem tekrar olur hem de kanca karesini diğerlerinden koparırdı.
    """
    ayar = dict(video_ayari or {})
    kayit = {"prompt": _metin(ayar.get("ilk_prompt")),
             "negatif": _metin(ayar.get("ilk_negatif"))}
    return kayit if any(kayit.values()) else None


def ilk_sahne_uygula(kayit, ilk_sahne, varsayilan_negatif=""):
    """İlk sahnenin **negatif** katmanını kayda işle; yeni kaydı döndür.

    Pozitif prompt **birebir kopyalanmaz**: kullanıcının yazdığı içerik isteğe bağlam
    olarak girer ve kareyi yine yapay zekâ yazar (bkz. `prompt_uretimi.grup_istegi`).
    Böylece 1. sahne diğer sahnelerle aynı biçimde kurulur — aynı stil katmanı, aynı
    kamera dili. Birebir kopyalandığında kare kamera/plan ifadesi olmadan kalıyor ve
    model illüstrasyona kayıyordu.

    Kullanıcının negatifi verilmişse projenin varsayılan negatifiyle birleştirilir;
    video (hareket) prompt'una dokunulmaz.
    """
    if not ilk_sahne or not ilk_sahne.get("negatif"):
        return kayit
    yeni = dict(kayit)
    yeni["negative_prompt"] = _negatif_birlestir(_tek_satir_tam(ilk_sahne["negatif"]),
                                                 _metin(kayit.get("negative_prompt")),
                                                 varsayilan_negatif)
    return yeni


def kayit_bul(kayitlar, index, sira):
    """Yanıttan o adımın kaydını index'e, bulunamazsa sıraya göre seç.

    Dönüş: `(kayıt, sıraya düşüldü mü)`. Sıraya düşmek sessiz bir risktir: yapay zekâ
    index'leri karıştırmışsa bir sahnenin prompt'u başka sahneye yazılır. Çağıran bu
    bayrağı günlüğe yazar (bkz. `prompt_grubu_uret`).
    """
    if not isinstance(kayitlar, list):
        return None, False
    for oge in kayitlar:
        if isinstance(oge, dict) and str(oge.get("index")) == str(index):
            return oge, False
    if sira < len(kayitlar) and isinstance(kayitlar[sira], dict):
        return kayitlar[sira], True
    return None, False


def _sema_hatasi(kayitlar, grup, strateji, ilk_sahne=None):
    """Yanıt doğrulamadan geçiyor mu? Geçmiyorsa **kısa sebebini** döndür, geçiyorsa `None`.

    Yalnızca "bir düzeltme isteği harcamaya değer mi" kararını verir; katı doğrulama
    (`plan_dogrula` ve index kontrolü) `prompt_grubu_uret` içinde aynen sürer ve tek
    doğruluk kaynağı orasıdır. Burada aynı üç kapı önceden yoklanır: okunabilen kayıt
    listesi, index eşleşmesi ve her sahnenin geçerli `scene_plan`'ı.
    """
    if not isinstance(kayitlar, list) or not kayitlar:
        return "yanıt JSON kayıt listesi olarak okunamadı"
    gelen = [str(k.get("index")) for k in kayitlar if isinstance(k, dict)]
    beklenen = [str(a["index"]) for a in grup]
    if len(gelen) != len(beklenen) or (len(beklenen) > 1 and sorted(gelen) != sorted(beklenen)):
        return f"beklenen indeksler {beklenen}, gelen {gelen}"
    for sira, adim in enumerate(grup):
        kayit, _sira = kayit_bul(kayitlar, adim["index"], sira)
        if not isinstance(kayit, dict):
            return f"{adim['index']} numaralı sahnenin kaydı yok"
        if not isinstance(kayit.get("scene_plan"), dict):
            return f"{adim['index']} numaralı sahnede scene_plan yok"
        try:
            plan_dogrula(kayit["scene_plan"], strateji,
                         ilk=int(adim.get("index") or 0) == ILK_SAHNE_INDEX,
                         ozel_acilis=bool(adim.get("image_prompt"))
                                     or bool((ilk_sahne or {}).get("prompt")))
        except ValueError as hata:
            # Ölçüm: şablon eklendikten sonra da 10-12. sahnelerin `body_pose`'u kural
            # dışı çıktı ("Sahne beden pozisyonu geçersiz."); düzeltme isteği bunu da
            # kapsamazsa grup yine tümden düşer.
            return f"{adim['index']} numaralı sahnenin planı geçersiz ({hata})"
        if any(not _metin(kayit.get(alan)) for alan in ("image_prompt", "video_prompt")):
            return f"{adim['index']} numaralı sahnenin prompt'ları eksik"
    # Birinci kişide kalıp başa eklenmiş olsa da prompt anlatıcıyı dışarıdan
    # anlatıyorsa kare üçüncü kişiye kayıyor (bkz. `sahne_stratejileri.pov_ihlalleri`).
    # Şema hatası gibi **aynı düzeltme turuyla** ele alınır; ayrı bir kapı açmak
    # zinciri gereksiz uzatırdı.
    if strateji_normallestir(strateji) == STRATEJI_BIRINCI_KISI:
        for sira, adim in enumerate(grup):
            if adim.get("image_prompt"):
                continue          # kullanıcının onayladığı kare değiştirilmez
            kayit, _sira = kayit_bul(kayitlar, adim["index"], sira)
            if not isinstance(kayit, dict):
                continue
            for alan in ("image_prompt", "video_prompt"):
                ihlal = pov_ihlalleri(kayit.get(alan))
                if ihlal:
                    return (f"{adim['index']} numaralı sahnenin {alan} alanı anlatıcıyı "
                            f"gözle görülemeyecek biçimde tarif ediyor ({', '.join(ihlal)})")
            uzuv = sahipsiz_uzuv(kayit.get("image_prompt"))
            if uzuv:
                return (f"{adim['index']} numaralı sahnede '{uzuv}' kimin olduğu yazılmadan "
                        "geçiyor; anlatıcının kendi uzvuysa 'my' ile yazılsın (ör. 'my dusty "
                        "legs'), yoksa görüntü dışarıdan bakan bir kameraya dönüşür")
        # Kalıp tekrar (claudetest, 29.09.2026): 3–7. sahnelerin hepsinde anlatıcı oturuyor
        # ve elleri hasırı kavrıyordu. Kural isteme yazılır (bkz. `_POV_KARE_KURALLARI`);
        # grubun çoğunda tekrarlanırsa aynı düzeltme turuyla bir kez düzelttirilir.
        yazilan = [(adim, kayit_bul(kayitlar, adim["index"], sira)[0])
                   for sira, adim in enumerate(grup) if not adim.get("image_prompt")]
        yazilan = [(a, k) for a, k in yazilan if isinstance(k, dict)]
        elli = [str(a["index"]) for a, k in yazilan if kendi_el_var(k.get("image_prompt"))]
        if len(yazilan) >= 3 and len(elli) * 2 > len(yazilan):
            return (f"anlatıcının kendi elleri {len(yazilan)} sahnenin {len(elli)} tanesinde "
                    f"görünüyor (sahne {', '.join(elli)}); eller yalnızca o sahnenin eylemi "
                    "onları kullanıyorsa görünsün, diğerlerinde göz hizasında yere, yola ve "
                    "insanlara bakılsın")
        # Yalnızca **aynı** poz sayılır: uyanma (yatıyor) → kahvaltı (oturuyor) doğal bir
        # dizidir; claudetest4'te (29.09.2026) ikisi bir sayılıp gereksiz düzeltme istendi.
        dizi, onceki = 0, None
        for a, k in yazilan:
            poz = str((k.get("scene_plan") or {}).get("body_pose") or "")
            poz = "lying" if poz == "lying_waking" else poz
            dizi = dizi + 1 if poz in ("seated", "lying") and poz == onceki else (
                1 if poz in ("seated", "lying") else 0)
            onceki = poz
            if dizi >= 3:
                return (f"{a['index']} numaralı sahneyle üç sahne art arda oturuyor/yatıyor; "
                        "anlatım söylemiyorsa anlatıcı ayağa kalkıp yürüsün ya da çalışsın, "
                        "art arda sahneler aynı poz ve çerçeveyi tekrar etmesin")


def _duzeltme_istegi(sebep, cevap, grup, pov=False, negatif_destekli=True):
    """Reddedilen yanıtı modele gösterip biçimi düzelttiren ek istek.

    Model kendi yanıtını görünce eksik anahtarı ekler; sıfırdan yazdırmak aynı hatayı
    yineleyebiliyordu.
    """
    return ("\n\n--- YOUR PREVIOUS ANSWER WAS REJECTED ---\n"
            f"Reason: {sebep}\n"
            f"Write one element for each of these indexes, in this order: "
            f"{[a['index'] for a in grup]}\n"
            "Every element must carry the keys index, scene_plan, image_prompt, "
            + ("negative_prompt and " if negatif_destekli else "and ") +
            "video_prompt. scene_plan is a KEY INSIDE the "
            "element (never a separate element) and is required for every segment.\n"
            "Use only these plan values: camera first_person|observer|free; body_pose "
            "standing|walking|seated|kneeling|crouched|lying|other.\n"
            + ("This video uses the first-person strategy: every image_prompt and "
               "video_prompt is written from the narrator's eyes. Remove any body part "
               "those eyes cannot see ('my back', 'my face', 'my head', 'my nape', back "
               "muscles, the whole body seen from outside) and any third-person, external "
               "or overhead camera. Show a sensation by its visible evidence instead "
               "(the wall ahead, the mat under the legs, the shadow on the ground). Start "
               "each image_prompt with the first-person viewpoint; period, wardrobe and "
               "style words come after.\n"
               if pov else "") +
            "Reply with the corrected flat JSON array only.\n"
            "Your previous answer:\n" + str(cevap or "")[:4000])


def prompt_grubu_uret(ai, anahtar, model, grup, dil, stil, varsayilan_negatif, genel="",
                      *, bildir=None, kullanilan=None, yedek=True, tam_metin="", onceki=None,
                      uyar=None, ilk_sahne=None, kelime_siniri=PROMPT_KELIME_SINIRI,
                      negatif_destekli=True, strateji=VARSAYILAN_STRATEJI, kalite=False, kiyafet=None,
                      stil_ayri=False, karakterler=None):
    """Bir grup adım için görsel (+) / (−) ve video prompt'larını yapay zekâya yazdır.

    Prompt yalnızca anlatımdan üretilmez: **genel video prompt'u** (brief), görsel stil,
    **varsayılan negatif prompt**, anlatımın tamamı ve **önceki sahnelerin prompt'ları**
    aynı istekte verilir, böylece her adım videonun tamamına ve kendinden öncekilere uyar.
    JSON ayrıştırması `prompt_uretimi` ile aynı kurallara uysun diye `json_yardim` çözümleyicisi
    kullanılır; böylece iki yerde farklı davranış oluşmaz.

    `uyar(mesaj)` verilirse yanıttaki kayıt sayısı eksik kaldığında ya da eşleştirme
    index yerine **sıraya** düştüğünde uyarı üretilir: bunlar sessizce yanlış sahneye
    prompt yazılmasına yol açabilir.

    `kelime_siniri` ve `negatif_destekli` **seçili görsel modelinden** gelir (bkz.
    `sistem_mesaji`); verilmezse SDXL varsayılır (eski davranış). `stil_ayri` de
    modelden gelir: uzun metin okuyan modelde `kelime_siniri` yalnızca sahne içeriğinin
    bütçesidir ve stil tamamıyla üstüne eklenir (bkz. `metin.stil_ile_birlestir`). Her kayıt ayrıca
    `kontrol` taşır: karede gözle doğrulanacak öğeler, `; ` ile ayrılmış (boş olabilir).

    Yanıt şemayı tutmazsa (okunamayan JSON, index kayması, eksik/geçersiz `scene_plan` ya
    da boş prompt) **aynı servisten bir kez** düzeltme istenir (`_duzeltme_istegi`); katı doğrulama
    ikinci yanıtta da sürer. Hesap/servis değiştirmek bu hatayı çözmez: aynı modeli
    taşıyan bütün hesaplar aynı yanıtı verir, zincir boşuna yanar (bkz. ölçüm notu).
    """
    if kalite:
        stil = stil_arindir(stil)
    # Yapay zekâya sınırın **altında** bir hedef verilir; sınır kodda kesme olarak kalır
    # (bkz. `metin.hedef_kelime`). CLIP'li modelde stil de aynı bütçeden yer tuttuğu
    # için içerik bütçesi stil kadar küçülür.
    icerik_siniri = (kelime_siniri if stil_ayri
                     else max(25, kelime_siniri - _kelime_sayisi(stil)))
    hedef = _hedef_kelime(icerik_siniri)
    # Strateji sistem mesajını **baştan** kurar: birinci kişide çakışan genel sıralama
    # kuralı yazılmaz (bkz. `sistem_mesaji`).
    sistem = sistem_mesaji(kelime_siniri, negatif_destekli, strateji, hedef=hedef, plan=kalite)
    pov = strateji_normallestir(strateji) == STRATEJI_BIRINCI_KISI
    istek = grup_istegi(grup, dil, stil, genel, varsayilan_negatif, tam_metin, onceki,
                        ilk_sahne, strateji, kiyafet=kiyafet, negatif_destekli=negatif_destekli,
                        karakterler=karakterler)
    cevap = metin_ai.VARSAYILAN.metin(ai, anahtar, model, sistem, istek, json_modu=True,
                                      bildir=bildir, kullanilan=kullanilan, yedek=yedek)
    kayitlar = json_listesi(cevap)
    # Ölçüm (piramit 7-12 grubu, 28.09.2026): Workers AI qwen3 diziyi doğru indekslerle ve
    # tam uzunlukta yazdı ama altı kaydın **hiçbirine** scene_plan koymadı; aynı modeli
    # taşıyan yedi hesap da birebir aynı yanıtı verdiği için zincir tümden düştü ve hiç
    # prompt yazılamadı. Hesap ya da servis değiştirmek bunu **çözmez**; sorun istekte
    # değil, modelin şemayı atlamasındadır. Tek düzeltme isteği bu kilidi açar.
    sebep = _sema_hatasi(kayitlar, grup, strateji, ilk_sahne) if kalite else None
    if sebep:
        mesaj = f"Yanıt şemaya uymadı ({sebep}); aynı yapay zekâdan düzeltmesi istendi."
        if uyar is not None:
            uyar(mesaj)
        elif bildir:
            bildir(mesaj)
        cevap = metin_ai.VARSAYILAN.metin(
            ai, anahtar, model, sistem, istek + _duzeltme_istegi(sebep, cevap, grup, pov=pov,
                                                                negatif_destekli=negatif_destekli),
            json_modu=True, bildir=bildir, kullanilan=kullanilan, yedek=yedek)
        kayitlar = json_listesi(cevap)
    if kalite:
        beklenen = [str(a["index"]) for a in grup]
        gelen = ([str(k.get("index")) for k in kayitlar if isinstance(k, dict)]
                 if isinstance(kayitlar, list) else [])
        # Tek sahnelik istekte index kayması **belirsizlik yaratmaz**: tek kayıt tek
        # sahneye aittir. (Ölçüm: Workers AI'ın akıl yürüten modelleri index'i 0'dan
        # başlatabiliyor; tek sahne — ör. kanca — yeniden yazılırken bu yüzden bütün
        # grup gereksizce düşüyordu. Eşleşme `kayit_bul` ile sıraya düşer ve günlüğe
        # uyarı yazılır, yani sessizce yanlış sahneye prompt yazılmaz.)
        tek_kayit = len(beklenen) == 1 and len(gelen) == 1
        if ((len(gelen) != len(beklenen) or sorted(gelen) != sorted(beklenen))
                and not tek_kayit):
            raise ValueError("Sahne yanıtı eksik, yinelenmiş veya yanlış index içeriyor; yeniden denenecek.")
    # Yanıt hiç okunamadığında da **uyarılır**. Eskiden uyarı yalnızca liste
    # döndüğünde veriliyordu; yanıt çözümlenemeyince (`None`) tek satır bile
    # yazılmadan bütün grup yedek prompt'a düşüyor ve günlüğe "Prompt yazıldı"
    # geçiyordu. Napolyon projesinde 26 sahnenin 20'si bu yüzden sessizce aynı
    # şablonla doldu.
    if uyar is not None:
        if not isinstance(kayitlar, list):
            uyar(f"yapay zekânın yanıtı JSON olarak okunamadı; adım {grup[0]['index']}–"
                 f"{grup[-1]['index']} arasındaki {len(grup)} sahnenin tamamı yedek "
                 "prompt'la dolduruldu (yanıtın ilk 120 karakteri: "
                 + _tek_satir(cevap)[:120] + ")")
        elif len(kayitlar) < len(grup):
            uyar(f"yapay zekâ {len(grup)} sahne için {len(kayitlar)} kayıt döndürdü; "
                 "eksik sahneler yedek prompt'la dolduruldu")
    # Dönem önce belirlenir; ilk taslak da pozitif kıyafet bakımından süzülür.
    # Onaylı elle yazılmış kareler değiştirilmez, görsel hakem kıyafeti ayrıca denetler.
    kilitli_indexler = {str(a["index"]) for a in grup if a.get("image_prompt")}
    if kiyafet and kiyafet.get("tarihsel") is True and isinstance(kayitlar, list):
        adaylar = [k for k in kayitlar if str(k.get("index")) not in kilitli_indexler]
        if adaylar:
            duzeltilen = promptlari_suz(
                adaylar, kiyafet, ai, anahtar, model,
                kelime_siniri=icerik_siniri, hedef=hedef, pov=pov,
                bildir=bildir, kullanilan=kullanilan, yedek=yedek)
            eslesen = {str(k["index"]): k for k in duzeltilen}
            # Kıyafet süzgeci POV denetiminden **sonra** çalışır; bozduğu bakış açısını
            # düzeltecek tur kalmaz. Ölçüm: kıyafet kalıbı ("shaved heads, bare chest")
            # anlatıcıyı dışarıdan tarif ediyordu. Süzgeç yeni bir POV ihlali getirdiyse
            # o sahnede süzgeçten önceki (POV denetiminden geçmiş) prompt tutulur.
            if pov:
                for eski in adaylar:
                    anahtar_ = str(eski.get("index"))
                    yeni = eslesen.get(anahtar_) or {}
                    ihlal = set(pov_ihlalleri(yeni.get("image_prompt")))
                    ihlal -= set(pov_ihlalleri(eski.get("image_prompt")))
                    if ihlal:
                        eslesen[anahtar_] = eski
                        if uyar is not None:
                            uyar(f"adım {anahtar_} kıyafet süzgeci anlatıcıyı dışarıdan tarif "
                                 f"etti ({', '.join(sorted(ihlal))}); süzgeçten önceki prompt "
                                 "tutuldu")
            kayitlar = [eslesen.get(str(k.get("index")), k) for k in kayitlar]
    siraya_dusen = []
    sonuc = []
    for sira, adim in enumerate(grup):
        kayit, sirayla = kayit_bul(kayitlar, adim["index"], sira)
        if sirayla:
            siraya_dusen.append(str(adim["index"]))
        kayit = kayit or {}
        kilitli = bool(adim.get("image_prompt"))
        plan = (plan_dogrula(kayit.get("scene_plan"), strateji,
                             ilk=int(adim.get("index") or 0) == ILK_SAHNE_INDEX,
                             ozel_acilis=kilitli or bool((ilk_sahne or {}).get("prompt")))
                if kalite else None)
        if kalite and any(not _metin(kayit.get(k)) for k in ("image_prompt", "video_prompt")):
            raise ValueError(f"Adım {adim['index']} promptları eksik; şablon kare üretilmedi.")
        gorsel = _metin(kayit.get("image_prompt"))
        if not gorsel:
            # Yapay zekâ prompt yazamazsa genel brief ve stil birlikte kullanılır.
            cerceve = " ".join(parca for parca in (_tek_satir(genel), _tek_satir(stil)) if parca)
            gorsel = (f"Cinematic still frame illustrating: {adim.get('text') or ''}. "
                      + (cerceve or "realistic, consistent lighting, detailed")).strip()
        # Görsel modeli olumsuzluğu anlamaz, adı geçeni çizer ("my hands stay outside
        # the frame" eli kareye çağırıyordu); bu ifadeler koda da ayıklanır
        # (bkz. `metin.olumsuz_ayikla`). Kullanıcının onayladığı kareye dokunulmaz.
        if not kilitli:
            temiz, atilan = _olumsuz_ayikla(gorsel)
            if temiz and atilan:
                gorsel = temiz
                if uyar is not None:
                    uyar(f"adım {adim['index']} görsel prompt'undan modelin çizeceği "
                         f"olumsuz ifadeler çıkarıldı: {'; '.join(atilan)}")
            # Planın `body_pose: other` etiketi prompt'a aynen kopyalanıyordu ("Tekir,
            # other, darts…", 22.10.2026 testi); virgüller arasındaki tek "other" atılır.
            gorsel = _PLAN_ETIKETI.sub("", gorsel)
        # Birinci kişide kare **bakış açısıyla başlar**: kural isteme de yazılır ama
        # garanti değildir; kalıp burada koda zorlanır (bkz. `sahne_stratejileri.pov_ekle`).
        povlu = pov_ekle(gorsel) if pov else gorsel
        if povlu != gorsel:
            gorsel = povlu
            if uyar is not None:
                uyar(f"adım {adim['index']} görsel prompt'u birinci kişi bakış "
                     "açısıyla başlamıyordu; başına bakış açısı kalıbı eklendi")
        # Stil **karenin kendisine** yazılır, yapay zekânın onu tekrarlamasına
        # bırakılmaz: ölçümde sahne başına stilin ortalama %10'u geçiyordu ve her
        # sahnede başka parçası geçtiği için kareler birbirinden kopuyordu
        # (bkz. `metin.stil_ekle`). Bütçeye sığmayan öğe atlanır, içerik kırpılmaz.
        # Uzun metin okuyan modelde stil bütçenin dışındadır: içerik sınıra kırpılır,
        # stilin tamamı üstüne eklenir.
        # Kelime sınırı **denetlenir**: yapay zekâ sınırı aşarsa kuyruğu zaten modele
        # ulaşmaz, kayıtta durması yanıltıcı olurdu (bkz. `PROMPT_KELIME_SINIRI`).
        uzunluk = _kelime_sayisi(gorsel if stil_ayri else _stil_ekle(gorsel, stil, kelime_siniri,
                                                                      sona=pov))
        gorsel = _stil_ile_birlestir(gorsel, stil, kelime_siniri, sona=pov, stil_ayri=stil_ayri)
        if uzunluk > kelime_siniri:
            if uyar is not None:
                uyar(f"adım {adim['index']} görsel prompt'u {uzunluk} kelimeydi; görsel "
                     f"modeli ilk {kelime_siniri} kelimeyi okuduğu için kuyruğu "
                     "kırpıldı")
        kayit_sonuc = {
            "image_prompt": gorsel,
            # Kareye özgü negatif **önce**, kullanıcının varsayılanı sonra: biri
            # diğerinin yerine geçmez, tekrarlar atılır (bkz. `negatif_birlestir`).
            # Negatif almayan modelde sahneye negatif yazılmaz: kayıtlı genel negatif
            # ayarda durur ve destekleyen modele geçilirse gönderim anında eklenir
            # (bkz. `akis_servis.gorsel_uretici`).
            "negative_prompt": (_negatif_birlestir(_metin(kayit.get("negative_prompt")),
                                                   varsayilan_negatif)
                                if negatif_destekli else ""),
            "video_prompt": _metin(kayit.get("video_prompt")) or (
                "Slow cinematic camera push in, subtle natural subject motion, "
                "smooth 5-second clip, keep the frame and character consistent"),
        }
        if plan:
            kayit_sonuc["sahne_plani"] = plan
        # Kadro varsa sahnede görünen karakterler kayda yazılır: kare bu karakterlerin
        # referans görselleriyle üretilir (bkz. `karakterler.sahne_karakterleri`).
        if karakterler:
            kayit_sonuc["karakterler"] = _prompttaki_adlar(
                adim["image_prompt"] if kilitli else gorsel, karakterler)
        if kilitli:
            # Yalnızca bağımlı alanlar yenilenir; kullanıcının karesi/stili kırpılmaz.
            kayit_sonuc["image_prompt"] = adim["image_prompt"]
            kayit_sonuc["negative_prompt"] = adim.get("negative_prompt") or ""
        # Kalıp başa eklense de içerik anlatıcıyı dışarıdan anlatıyorsa bu **kayda**
        # yazılır: kullanıcı hangi karenin bakış açısından kaydığını görsün (kararı
        # görsel hakem verir; burada yalnızca düzeltilemeyen artık bildirilir).
        if pov and not kilitli:
            ihlal = pov_ihlalleri(kayit_sonuc["image_prompt"])
            if ihlal and uyar is not None:
                uyar(f"adım {adim['index']} görsel prompt'u hâlâ birinci kişi dışı ifade "
                     f"içeriyor ({', '.join(ihlal)}); kare anlatıcının dışına kayabilir")
        # İlk sahne kullanıcının elindeyse yapay zekânın yazdığı kare prompt'u değişir.
        if int(adim.get("index") or 0) == ILK_SAHNE_INDEX and negatif_destekli:
            kayit_sonuc = ilk_sahne_uygula(kayit_sonuc, ilk_sahne, varsayilan_negatif)
        # Pozitifte **istenen** bir şeyi bastıracak negatif öğeleri atılır (ölçüldü:
        # "burning animal" istenen alevi 3 seed'in 3'ünde de sildi; bkz.
        # `negatif_celiski_ayikla`). Kullanıcının genel negatifi de bu süzgeçten geçer.
        temiz, atilan = _negatif_celiski_ayikla(kayit_sonuc["image_prompt"],
                                                kayit_sonuc["negative_prompt"])
        if atilan:
            kayit_sonuc["negative_prompt"] = temiz
            if uyar is not None:
                uyar(f"adım {adim['index']} negatifinden, karede istenen şeyi silecek "
                     f"öğeler çıkarıldı: {', '.join(atilan)}")
        sonuc.append(kayit_sonuc)
    if uyar is not None and siraya_dusen:
        uyar("yanıtta index bulunamadı, eşleştirme sıraya düştü · adım "
             + ", ".join(siraya_dusen) + " — prompt'lar yanlış sahneye yazılmış olabilir")
    return sonuc
