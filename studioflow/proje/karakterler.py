"""Projenin karakter kadrosu: tek ya da çok karakterli senaryo.

Her karakterin bir **adı**, kısa bir **tarifi** ve bir **referans görseli** vardır. Kadro
projenin kaydında (`video.karakterler`) durur; referans görseller proje kurulurken
projenin kendi `karakterler/` klasörüne kopyalanır, böylece proje taşınsa da kadro
onunla gider.

Akış üç yerde kadroyu kullanır:

1. prompt yazımı: yapay zekâya kadro verilir; görünen her karakteri **tam adıyla**
   anar, görünüşünü yeniden tarif etmez (bkz. `istek_blogu`);
2. adım kaydı: prompt yazılınca sahnede görünen karakterler adıma yazılır
   (`Karakterler` satırı); hakem prompt'u düzeltip bir adı düşürse de referans kaybolmaz;
3. kare üretimi: sahnedeki karakterlerin referans görselleri `input_image_0..3` olarak
   gider ve prompt'un başına "image 0 = …" eşlemesi eklenir (bkz. `referans_oneki`).

Neden: karakter yalnızca metinle tarif edilince model her sahnede tarife uyan başka bir
yüz seçiyordu. Deneme (02.10.2026, FLUX.2 klein 4B): referanslı karelerde yüz, saç ve
kıyafet korundu; referanssız karelerde gerçekçi karakter her sahnede başka biri oldu.
"""
import json
import re
from pathlib import Path

from studioflow.proje.depo import dosya_kopyala, slug

# FLUX.2 klein en fazla 4 referans görsel alır: **bir karede** en fazla 4 karakter görünür.
AZAMI_KARAKTER = 4
# Projenin kaydındaki kadro bundan büyük olabilir: her kare yalnızca kendi sahnesindeki
# karakterlerin referansını alır. Bölüm bölüm ilerleyen videolarda (ör. 10 mitolojik
# varlık) karakterler aynı karede buluşmaz. 16'lık sınır 8 canavarlı bir videoda
# (canavar + kahraman + çocukluk hâli) doldu ve 17. karakter sessizce düşüyordu.
# 40 da Betta belgeselinde (23.10.2026) yetmedi: 14 beta çeşidi + kap içindeki betalar
# ayrı karakter olunca kadro 47 oldu. Pleco belgeselinde (30.10.2026) vatozun farklı
# hâlleri (camda, alttan, makro…) ayrı karakter olunca 79 oldu; 60'ın üstü sessizce düşüyordu.
AZAMI_KADRO = 120
KLASOR = "karakterler"
TARIF_SINIRI = 400


def _tek_satir(deger):
    return " ".join(str(deger or "").split())


def normalize(deger):
    """Kadroyu güvenli listeye çevir: adı olan, adı yinelenmeyen en fazla 16 karakter.

    Liste ya da JSON metni kabul eder (proje.txt'teki bölüm JSON'dur).
    """
    if isinstance(deger, str):
        try:
            deger = json.loads(deger) if deger.strip() else []
        except ValueError:
            deger = []
    sonuc, adlar = [], set()
    for oge in deger if isinstance(deger, list) else []:
        if not isinstance(oge, dict):
            continue
        ad = _tek_satir(oge.get("ad"))
        if not ad or ad.casefold() in adlar:
            continue
        adlar.add(ad.casefold())
        sonuc.append({"ad": ad, "tarif": _tek_satir(oge.get("tarif"))[:TARIF_SINIRI],
                      "gorsel": str(oge.get("gorsel") or "").strip()})
        if len(sonuc) == AZAMI_KADRO:
            break
    return sonuc


def kadroya_ekle(kadro, ad, tarif, gorsel):
    """Karakteri kadroya kaydet: `(yeni kadro, hata metni)`; hata yoksa metin boştur.

    Aynı adlı karakter (büyük/küçük harf duyarsız) varsa yerinde güncellenir, yoksa
    sona eklenir. Referans görsel şarttır: referanssız karakter her sahnede başka
    biri olur (bkz. `projeye_kopyala`).
    """
    kadro = normalize(kadro)
    ad, tarif, gorsel = _tek_satir(ad), _tek_satir(tarif), str(gorsel or "").strip()
    if not ad:
        return kadro, "Önce karakterin **adını** yaz."
    if not gorsel:
        return kadro, (f"**{ad}** için referans görsel yok: tariften üret ya da kendi "
                       "görselini bırak.")
    yeni = {"ad": ad, "tarif": tarif[:TARIF_SINIRI], "gorsel": gorsel}
    for sira, karakter in enumerate(kadro):
        if karakter["ad"].casefold() == ad.casefold():
            kadro[sira] = yeni
            return kadro, ""
    if len(kadro) >= AZAMI_KADRO:
        return kadro, f"Kadro dolu: en fazla {AZAMI_KADRO} karakter kaydedilebilir."
    return kadro + [yeni], ""


def kadrodan_sil(kadro, ad):
    """Adı verilen karakteri kadrodan çıkar (büyük/küçük harf duyarsız)."""
    ad = _tek_satir(ad).casefold()
    return [k for k in normalize(kadro) if k["ad"].casefold() != ad]


def _ad_kalibi(ad):
    # Adın parçaları arasında boşluk, tire ya da alt çizgi kabul edilir: yapay zekâ
    # "Mosquitofish Female"ı "Mosquitofish-Female" yazınca referans düşüyordu.
    parcalar = [re.escape(p) for p in re.split(r"[\s\-_]+", ad) if p]
    return re.compile(r"(?<!\w)" + r"[\s\-_]+".join(parcalar) + r"(?!\w)", re.IGNORECASE)


def prompttaki_adlar(prompt, karakterler):
    """Prompt'ta adı geçen karakterlerin adları (kadro sırasıyla).

    Uzun adlar önce aranır ve bulunan yer silinir: kadroda "Ali" ile "Ali Baba" varken
    "Ali Baba" yazan sahneye ikisinin de referansı gidiyordu (22.10.2026 testi).
    """
    prompt = str(prompt or "")
    bulunan = set()
    for karakter in sorted(karakterler, key=lambda k: len(k["ad"]), reverse=True):
        kalip = _ad_kalibi(karakter["ad"])
        if kalip.search(prompt):
            bulunan.add(karakter["ad"].casefold())
            prompt = kalip.sub(lambda m: " " * len(m.group(0)), prompt)
    return [k["ad"] for k in karakterler if k["ad"].casefold() in bulunan]


def sahne_karakterleri(adim, karakterler):
    """Sahnede görünen karakterler: prompt'taki adlar + adımın kayıtlı listesi.

    Kayıtlı liste prompt yazılırken çıkarılır; hakem prompt'u yeniden yazıp bir adı
    düşürse de karakter referansıyla üretilmeye devam eder.

    Sınırı (`AZAMI_KARAKTER`) aşan karede prompt'ta **önce anılanlar** kalır; eskiden
    kadro sırasıyla kesildiği için sahnenin asıl karakteri dışarıda kalabiliyordu.
    Sınır aşılmadıkça sıra (ve görsel eşlemesi) eskisi gibi kadro sırasıdır.
    """
    kayitli = {ad.casefold() for ad in adim.get("karakterler") or []}
    prompt = str(adim.get("image_prompt") or "")
    adlar = {ad.casefold() for ad in prompttaki_adlar(prompt, karakterler)}
    secilen = [k for k in karakterler if k["ad"].casefold() in kayitli | adlar]
    if len(secilen) <= AZAMI_KARAKTER:
        return secilen

    def ilk_yer(karakter):
        eslesme = _ad_kalibi(karakter["ad"]).search(prompt)
        return eslesme.start() if eslesme and karakter["ad"].casefold() in adlar else len(prompt) + 1
    kalan = {id(k) for k in sorted(secilen, key=ilk_yer)[:AZAMI_KARAKTER]}
    return [k for k in secilen if id(k) in kalan]


def referans_oneki(adlar):
    """Görsel modeline giden eşleme: hangi referans görsel hangi karakter."""
    if not adlar:
        return ""
    eslesme = "; ".join(f"image {sira} is {ad}" for sira, ad in enumerate(adlar))
    return (f"Reference images: {eslesme}. Draw every named character exactly as in their "
            "reference image, with the same face, hair, body colors and outfit; change only "
            "their pose, expression and position for this scene.")


def istek_blogu(karakterler):
    """Prompt yazan yapay zekâya verilen kadro bloğu (kadro yoksa boş metin)."""
    if not karakterler:
        return ""
    kadro = "\n".join(f"- {k['ad']}: {k['tarif'] or 'see reference image'}"
                      for k in karakterler)
    return ("Fixed cast of this video. Each character below has a reference image that the "
            "image model receives together with your image_prompt, so the reference fixes "
            "their face, hair, colors and outfit. Rules: (1) whenever a cast member is "
            "visible in a frame, name them in image_prompt with their EXACT name as written "
            "here; (2) do not re-describe their face, hair, body colors or clothing, describe "
            "only their pose, action, expression, position and size in the frame; (3) at most "
            f"{AZAMI_KARAKTER} cast members per frame; (4) do not invent other recurring main "
            "characters, unnamed background extras are fine; (5) a frame may show no cast "
            "member when the narration calls for it; (6) put a cast member in a frame only "
            "when that segment's narration involves them or the story places them there at "
            "that moment, never just to fill the frame; (7) if the overall brief or style also "
            "describes a cast member's looks, the reference image wins: do not copy those "
            "looks into image_prompt.\nCast:\n" + kadro)


def projeye_kopyala(karakterler, klasor):
    """Referans görselleri proje klasörüne kopyala; görsel yolu projeye göreli olur.

    Görseli olmayan ya da dosyası bulunamayan karakter varsa `ValueError`: referanssız
    karakter metinle tarif edilmiş olur ve her sahnede değişir; sessizce geçilmez.
    """
    klasor = Path(klasor)
    sonuc = []
    for sira, karakter in enumerate(karakterler, 1):
        kaynak = Path(karakter.get("gorsel") or "")
        if not kaynak.is_absolute():
            kaynak = klasor / kaynak
        if not karakter.get("gorsel") or not kaynak.is_file():
            raise ValueError(f"'{karakter['ad']}' karakterinin referans görseli yok. "
                             "Karakterler panelinde görseli üret ya da yükle.")
        hedef = Path(KLASOR) / f"{sira}-{slug(karakter['ad']) or 'karakter'}{kaynak.suffix or '.png'}"
        dosya_kopyala(kaynak, klasor / hedef)
        sonuc.append({**karakter, "gorsel": hedef.as_posix()})
    return sonuc


def mutlak_yol(karakter, klasor):
    """Karakterin referans görselinin tam yolu (göreli kayıt proje klasörüne göredir)."""
    yol = Path(karakter.get("gorsel") or "")
    return yol if yol.is_absolute() else Path(klasor) / yol


def mutlak_kadro(karakterler, klasor):
    """Arayüzde gösterilmek üzere görsel yolları tam yola çevrilmiş kadro."""
    return [{**k, "gorsel": str(mutlak_yol(k, klasor)) if k.get("gorsel") else ""}
            for k in karakterler]
