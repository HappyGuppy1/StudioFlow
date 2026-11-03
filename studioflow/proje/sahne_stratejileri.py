"""Sahne planlama anlatım stratejileri."""
import re

STRATEJI_TARIH = "tarih"
STRATEJI_BIRINCI_KISI = "birinci_kisi"
# Filtresiz strateji: tarih/birinci kişiye özgü hiçbir kamera ya da anlatı kuralı eklenmez;
# yapay zekâ kamerayı ve sahne kurgusunu her sahne için anlatıma göre kendi seçer.
STRATEJI_DEFAULT = "default"
VARSAYILAN_STRATEJI = STRATEJI_TARIH

STRATEJI_SECENEKLERI = (
    ("Default", STRATEJI_DEFAULT),
    ("Tarih", STRATEJI_TARIH),
    ("Birinci kişi anlatım", STRATEJI_BIRINCI_KISI),
)

_TARIH = """HISTORY NARRATION STRATEGY:
- Preserve the existing historical scene logic: one documented human-scale event, a clear
  information gap, cause and effect, rising tension, and the most surprising detail near the
  climax.
- Use a historically grounded external observer camera.
- Keep documented facts separate from reconstruction; never invent a quotation, exact private
  thought, or unsupported detail.
- Group consecutive sentences into the fewest coherent scenes. Each scene should show one
  concrete, filmable moment and one main action.
"""

# Yalnızca **sahne/hikâye** düzeyi kurallar. Karenin nasıl yazılacağı (bakış açısıyla
# başlama, "my …" sahipliği, görülemeyen beden) tek yerde, prompt yazarının sistem
# mesajında durur (bkz. `adim_promptlari._POV_KARE_KURALLARI`). Eskiden aynı kurallar
# sistem mesajında üç, kullanıcı mesajında bir kez daha gidiyordu (~1.470 kelime) ve
# model bir kısmını atlıyordu.
_BIRINCI_KISI = """FIRST-PERSON POV SCENE STRATEGY:
- The camera is the narrator's eyes in every scene: no external observer, third-person
  establishing shot, selfie, drone or overhead view, and no visible narrator face. The
  viewer stays inside the body, never watching it from outside.
- Scene 1 shows what the narration's first segment says; there is no default opening.
  A user-supplied scene 1 content is applied as given.
- Group consecutive narration sentences into visual beats by what the viewer can see from
  one body position; never combine incompatible viewpoints in one scene.
- Use short beats for a hook, discovery, obstacle, choice, consequence and final reveal;
  reserve the strongest reveal for the climax.
- Keep the same unseen character, route, wardrobe, light progression and screen direction
  across scenes.
- Turn abstract narration into a concrete subjective moment; if a fact cannot be seen from
  first person, show the nearest visible evidence instead of inventing a cutaway.
"""

# Default: strateji kuralı yok. Tek satır yalnızca modelin "hangi strateji?" diye boşluk
# görmemesi için: kamera ve kurgu kararı sahneye bırakılır.
_DEFAULT = """DEFAULT STRATEGY (no strategy-specific rules):
- No fixed camera: for each scene choose whatever camera, angle and framing best shows the
  narration (wide, close-up, observer or any other).
"""


# Birinci kişi stratejisinde **her** görsel prompt'u bakış açısı kalıbıyla başlar.
# Bu yalnızca isteme yazılıyordu ve bir garanti değildi: piramit projesinde
# (28.09.2026) 12 sahnenin 4.'sü kamerayı bedenin dışına çıkardı ("worker in hat
# pouring water from clay jar, bare feet bracing on sand, …, first-person
# viewpoint") — bakış açısı prompt'un **sonunda** kalınca CLIP'in 77 tokenlık
# penceresinde okunmuyor (bkz. `metin.stil_ekle`: aynı stil kelimeleri başta
# fotoğraf, sonda yağlı boya üretti). Bu yüzden kalıp prompt birleştirilirken koda
# da **zorlanır**.
POV_ONEKI = "First-person POV, the camera is my eyes"

# Kalıp yalnızca prompt'un **başında** sayılır: gövdede geçmesi yetmez (yukarıdaki
# ölçüm). Bakış açısı en fazla bir-iki niteleyici sonra gelebilir
# ("Photorealistic first-person view …" geçer), ama kare özneye kaydıysa geçmez
# ("Worker pouring water, … first-person viewpoint" → kalıp başa eklenir).
_POV_KALIBI = re.compile(
    r"first[-\s]person|\bpov\b|point[-\s]of[-\s]view|through my eyes|"
    r"camera[-\s]as[-\s](?:my|the viewer's|the narrator's)[-\s]eyes", re.I)
_POV_BAKI = 3


def pov_ekle(prompt):
    """Görsel prompt'u birinci kişi bakış açısıyla **başlat**; başlıyorsa dokunma.

    Yapay zekâ strateji kuralını atladığında bile kare "kamerayı benim gözlerim"
    diye okunur. Tarih stratejisinde çağrılmaz: orada kamera bilinçli olarak
    dışarıdadır. Zaten bakış açısıyla başlayan prompt'a kalıp ikinci kez eklenmez.
    """
    metin = " ".join(str(prompt or "").split())
    if not metin:
        return metin
    if _POV_KALIBI.search(" ".join(metin.split()[:_POV_BAKI])):
        return metin
    return POV_ONEKI + ", " + metin


# Birinci kişide prompt **gözle görülebilir** olanı yazmak zorundadır. Ölçüm (piramit5,
# 28.09.2026): kalıp başa eklendiği hâlde "My back presses against cold, rough stone
# wall", "sun-darkened back muscles tense", "sun-darkened face tilts upward" gibi
# ifadeler kareyi anlatıcının dışına çevirdi; başa eklenen kalıp tek başına yetmiyor.
# Bu iki desen, anlatıcıyı dışarıdan gösteren somut ifadeleri yakalar: düzeltme isteği
# ve günlük uyarısı bunlar üzerinden kurulur (bkz. `adim_promptlari._sema_hatasi`).
# Arada en fazla iki niteleyici olabilir: kıyafet tanımı "my shaved head",
# "my sun-darkened back" biçiminde giriyordu ve düz "my head" deseni kaçırıyordu.
_GORULEMEZ_BEDEN = re.compile(
    r"\bmy\s+(?:own\s+)?(?:[\w-]+\s+){0,2}?(?:back|nape|backside|behind|face|head|hair|"
    r"profile|whole\s+body|full\s+body|entire\s+body)\b", re.I)
_POV_DISI = re.compile(
    r"\b(?:third[- ]person|external\s+(?:camera|view|shot)|observer\s+camera|"
    r"overhead\s+(?:shot|view|camera)|from\s+the\s+outside|seen\s+from\s+(?:behind|above)|"
    r"bird'?s[- ]?eye|drone\s+(?:shot|view)|behind\s+the\s+narrator)\b", re.I)


def pov_ihlalleri(prompt):
    """Birinci kişi prompt'unda gözle görülemeyen bedeni ya da dış kamerayı yakala.

    Dönüş: bulunan ifadelerin listesi (tekrarsız, küçük harfli). Boş liste = temiz.
    Yalnızca **yüksek güvenli** desenler aranır: "my back", "my face", "my head",
    "third-person", "external camera", "overhead" gibi. Yorum gerektiren ifadeler
    (ör. "sun-darkened chest") burada yakalanmaz; onlar görsel hakemin `pov`
    denetimine bırakılır. Yakalamak, isteği bir kez düzeltmeye iter; kesin olmayan
    desen ucuz bir yeniden yazım turu harcardı.
    """
    metin = " ".join(str(prompt or "").split())
    if not metin:
        return []
    bulunan = [m.group(0).casefold() for m in _GORULEMEZ_BEDEN.finditer(metin)]
    bulunan += [m.group(0).casefold() for m in _POV_DISI.finditer(metin)]
    return sorted(set(bulunan))


# Anlatıcının kendi eli prompt'ta geçiyor mu ("my hands", "my dusty right hand"). Yasak
# değildir; bir grupta **çoğu** sahnede geçmesi, yazarın eli bakış açısını kanıtlamak
# için kalıp olarak kullandığını gösterir (claudetest, 29.09.2026: 3–7. sahnelerin hepsi
# "hasırı kavrayan eller"). Bkz. `adim_promptlari._sema_hatasi`.
_KENDI_EL = re.compile(r"\bmy\s+(?:[\w-]+\s+){0,2}?(?:hands?|fingers?|palms?|fists?)\b", re.I)


# Sahipsiz uzuv: birinci kişi prompt'unda bacak/ayak/el geçiyor ama kimseye ait değil.
# claudetest4 (29.09.2026): ilk sahne "…lying on woven reed mat, dusty bare legs and
# cracked feet stretched toward narrow doorway" diye yazıldı ("my" düştü); FLUX hasırda
# yatan bir adamı **dışarıdan** çizdi, hakem de geçirdi.
_UZUV = re.compile(r"\b(?:legs?|feet|foot|knees?|lap|thighs?|shins?|hands?|arms?|forearms?|"
                   r"fingers?|toes?)\b", re.I)
_SAHIP = re.compile(r"\b(?:my|his|her|their|its|whose|other|another|workers?'?s?|men's|"
                    r"man's|scribe's|overseer's)\b", re.I)


def sahipsiz_uzuv(prompt):
    """Prompt'ta hiç "my" yokken sahibi yazılmamış uzuv varsa ilkini döndür, yoksa `None`."""
    metin = " ".join(str(prompt or "").split())
    if re.search(r"\bmy\b", metin, re.I):
        return None
    for eslesme in _UZUV.finditer(metin):
        onceki = metin[:eslesme.start()].split()[-3:]
        if not _SAHIP.search(" ".join(onceki)):
            return eslesme.group(0)
    return None


def kendi_el_var(prompt):
    """Prompt anlatıcının kendi elini/parmaklarını gösteriyor mu?"""
    return bool(_KENDI_EL.search(" ".join(str(prompt or "").split())))


def strateji_normallestir(deger):
    """Bilinmeyen/eski kayıtları geriye dönük uyumlu tarih stratejisine düşür."""
    return (deger if deger in {STRATEJI_TARIH, STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT}
            else VARSAYILAN_STRATEJI)


def strateji_etiketi(deger):
    anahtar = strateji_normallestir(deger)
    return dict((deger, etiket) for etiket, deger in STRATEJI_SECENEKLERI)[anahtar]


def strateji_kurallari(deger):
    """Seçili stratejiyi yapay zekâ istemine eklenecek İngilizce kurallara çevir."""
    return {STRATEJI_BIRINCI_KISI: _BIRINCI_KISI,
            STRATEJI_DEFAULT: _DEFAULT}.get(strateji_normallestir(deger), _TARIH)
