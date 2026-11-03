"""Sahne parçaları için görsel + video prompt'ları üretme ve rapor dosyası yazma."""
import os
import json
from datetime import datetime
from pathlib import Path

from studioflow.cekirdek.yollar import OUTPUTS
from studioflow.proje.json_yardim import json_listesi
from studioflow.proje.karakterler import istek_blogu as karakter_blogu
from studioflow.proje.kiyafet import kiyafet_baglami
from studioflow.proje.sabitler import ILK_SAHNE_INDEX, VARSAYILAN_NEGATIF
from studioflow.proje.sahne_stratejileri import (
    STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT, VARSAYILAN_STRATEJI, strateji_normallestir)


def strateji_etiketi_en(strateji):
    """İstekte stratejinin kısa İngilizce adı (kuralları sistem mesajındadır)."""
    return {STRATEJI_BIRINCI_KISI: "first-person POV (the camera is the narrator's eyes)",
            STRATEJI_DEFAULT: "default (no camera rule; free framing per scene)",
            }.get(strateji_normallestir(strateji), "history (external observer camera)")
from studioflow.saglayicilar import metin_ai

GRUP_BOYU = 6               # tek AI isteğinde işlenen parça sayısı


SISTEM_MESAJI = (
    "You are an expert film director and prompt engineer for AI image and video generators. "
    "You receive consecutive narration segments of one video plus its visual style. "
    "For each segment write two prompts in English:\n"
    "1) image_prompt: a detailed text-to-image prompt describing one still frame "
    "(subject, setting, lighting, camera lens, mood, style keywords; no text or watermarks; "
    "clean smooth surfaces, never gold leaf, flaking paint, cracks, scratches, dust or "
    "floating specks, which the video model animates as falling snow; the picture fills "
    "the whole frame edge to edge, never a border, frame, ornamental margin, vignette edge, "
    "medallion or panel).\n"
    "2) video_prompt: an image-to-video motion prompt describing how that still frame moves "
    "(camera move, subject action, pace), suitable for a ~5 second clip.\n"
    "Keep continuity across segments: same characters, wardrobe, palette, location and lighting.\n"
    "Reply ONLY with a JSON array. Every element must be exactly: "
    '{"index": <int>, "image_prompt": "<string>", "video_prompt": "<string>"}. '
    "Do not add markdown fences, comments or extra keys."
)


def _kayit_normalize(parca, kayit, stil):
    metin = (parca.get("text") or "").strip()
    gorsel = str((kayit or {}).get("image_prompt") or "").strip()
    video = str((kayit or {}).get("video_prompt") or "").strip()
    if not gorsel:
        gorsel = (f"Cinematic still frame illustrating: {metin}. "
                  + (stil or "realistic, consistent lighting, detailed")).strip()
    if not video:
        video = ("Slow cinematic camera push in, subtle natural subject motion, "
                 "smooth 5-second clip, keep the frame and character consistent")
    return {"index": parca["index"], "start": parca["start"], "end": parca["end"],
            "text": metin, "image_prompt": gorsel, "video_prompt": video}


def grup_istegi(grup, dil, stil, genel="", negatif="", tam_metin="", onceki=None,
                ilk_sahne=None, strateji=VARSAYILAN_STRATEJI, kiyafet=None,
                negatif_destekli=True, karakterler=None):
    """Bir grup parça için yapay zekâ isteğini kur.

    Katmanlar ayrı ayrı ve açıkça verilir: genel video prompt'u (brief), görsel stil,
    **varsayılan negatif prompt**, anlatımın tamamı (bağlam), **önceki sahnelerin
    yazılmış prompt'ları** ve gruptaki parçaların metinleri. Yapay zekâ bunları
    **birlikte** değerlendirip her parça için prompt yazar; böylece parçalar videonun
    tamamına ve birbirine uygun kalır. Genel prompt tek paragrafa indirilir.

    `tam_metin` ve `onceki` gruplar arası sürekliliği sağlar: istek yalnızca kendi
    altı sahnesini gördüğünde 6.→7. sahne geçişinde karakter/palet kayması oluyordu.
    `onceki` verilmezse (ilk grup) o blok hiç yazılmaz.

    `karakterler` (proje kadrosu) verilirse yapay zekâya kadro ve kuralları yazılır:
    görünen karakter tam adıyla anılır, görünüşü referans görsele bırakılır (bkz.
    `karakterler.istek_blogu`). Kadro yoksa istek eskisiyle birebir aynıdır.

    `negatif_destekli=False` (FLUX): negatif katmanı ve kıyafet analizinin yasak listesi
    isteğe **yazılmaz**. Model onları okumuyordu; isteğe girince yasaklanan şeyler
    ("hat", "trousers", "third-person view") yazan yapay zekânın dikkatine giriyor ve
    olumsuz cümle olarak pozitif prompt'a sızıyordu.
    """
    satirlar = [f"Segment {p['index']} ({p['start']:.1f}-{p['end']:.1f}s): {p['text']}"
                for p in grup]
    brief = " ".join((genel or "").split())
    bloklar = [
        f"Narration language: {dil}",
        "Overall video brief (applies to every segment): "
        + (brief or "not given — infer a consistent brief from the narration"),
        # Strateji kuralları yalnızca sistem mesajındadır (bkz. `adim_promptlari.sistem_mesaji`);
        # burada tekrar gitmesi mesajı uzatıyordu. Burada yalnızca adı hatırlatılır.
        "Selected scene and camera strategy: " + strateji_etiketi_en(strateji) + ".",
        "Continuity preserves identity and setting, not the previous composition. "
        "Advance the visible action with each narration segment. Never copy another "
        "segment's image prompt. Each segment shows its own narrated action, not an "
        "earlier segment's pose.",
        f"Overall visual style: {stil or 'cinematic, photorealistic, consistent lighting'}",
    ]
    if negatif_destekli:
        bloklar.append("Default negative prompt (include all of these in every negative_prompt): "
                       + (" ".join((negatif or "").split()) or VARSAYILAN_NEGATIF))
    kadro_metni = karakter_blogu(karakterler)
    if kadro_metni:
        bloklar.append(kadro_metni)
    kiyafet_metni = kiyafet_baglami(
        kiyafet, pov=strateji_normallestir(strateji) == STRATEJI_BIRINCI_KISI,
        yasaklar=negatif_destekli)
    if kiyafet_metni:
        bloklar.append(kiyafet_metni)
    if (tam_metin or "").strip():
        bloklar.append("Full narration (context only; write prompts only for the segments "
                       "listed below): " + " ".join(tam_metin.split()))
    # İlk sahnenin **içeriğini** kullanıcı yazdıysa yapay zekâya verilir: kareyi yine
    # yapay zekâ yazar, böylece 1. sahne diğer sahnelerle **aynı biçimde** (aynı stil
    # katmanı, aynı kamera dili, aynı uzunluk) kurulur. Kullanıcının metni birebir
    # kopyalanırsa kare kamera/plan ifadesi olmadan kalıyor ve model illüstrasyona
    # kayıyordu; bu yüzden metin "ne görünecek" bilgisi olarak geçer, "nasıl yazılacak"
    # kuralları diğer sahnelerle ortaktır.
    # Blok yalnızca 1. sahnenin **bu grupta** olduğu istekte yazılır: eskiden her
    # gruba gidiyordu ve model 7–12. sahneleri yazarken de "sahne 1'i şöyle yaz"
    # talimatı alıyordu (26 adımlık projede 5 grubun 4'ü).
    grupta_ilk_sahne = any(int(p.get("index") or 0) == ILK_SAHNE_INDEX for p in grup)
    if grupta_ilk_sahne and (ilk_sahne or {}).get("prompt"):
        bloklar.append("Scene 1 is the hook and the user has decided WHAT it shows. Write "
                       "scene 1's image_prompt so it shows exactly this content, but phrase "
                       "it in the same house format as the other scenes (same visual style "
                       "layer, same camera/shot language, same length). Do not copy the "
                       "user's wording verbatim, do not add subjects the user did not "
                       "mention, do not drop any subject the user did mention. User's scene "
                       "1 content: " + " ".join(str(ilk_sahne["prompt"]).split()))
        bloklar.append("Apply the user's scene 1 content to its scene_plan and "
                       "video_prompt too.")
    for parca in grup:
        if parca.get("image_prompt"):
            bloklar.append(
                f"Segment {parca['index']} has an approved image_prompt. Keep it EXACTLY: "
                + parca["image_prompt"] + "\nDerive a NEW scene_plan and video_prompt "
                "from this image content. It overrides narration and previous scene content "
                "for this segment. Do not reuse old objects or motion."
                + (" Keep negative_prompt: " + str(parca.get("negative_prompt") or "")
                   if negatif_destekli else ""))
    baslik_yazildi = False
    for kayit in onceki or []:
        gorsel = " ".join(str(kayit.get("image_prompt") or "").split())
        video = " ".join(str(kayit.get("video_prompt") or "").split())
        if not gorsel and not video:
            continue
        if not baslik_yazildi:
            bloklar.append("Prompts already written for other segments of this same "
                           "video (keep continuity with them):")
            baslik_yazildi = True
        bloklar.append(f"Segment {kayit.get('index')} image: {gorsel}")
        bloklar.append(f"Segment {kayit.get('index')} video: {video}")
        if kayit.get("sahne_plani"):
            bloklar.append("Previous scene plan: " + json.dumps(kayit["sahne_plani"], ensure_ascii=False))
    bloklar.append(f"There are {len(grup)} segments; write prompts for each one.")
    return "\n".join(bloklar) + "\n\n" + "\n".join(satirlar)


def prompt_grubu_uret(provider, anahtar, model, grup, dil, stil, *, bildir=None,
                      kullanilan=None, yedek=True, ai=None):
    """Bir grup parça için görsel + video prompt'ları üret.

    `bildir`, `kullanilan` ve `yedek` doğrudan `ai_metin`'e geçirilir: servis hatası
    olduğunda geçişler bildirilir ve prompt'ları yazan servis geri döndürülür.
    """
    cvp = (ai or metin_ai.VARSAYILAN).metin(provider, anahtar, model, SISTEM_MESAJI, grup_istegi(grup, dil, stil),
                   json_modu=True, bildir=bildir, kullanilan=kullanilan, yedek=yedek)
    kayitlar = json_listesi(cvp)
    sonuc = []
    for i, parca in enumerate(grup):
        kayit = None
        if isinstance(kayitlar, list):
            for item in kayitlar:
                if isinstance(item, dict) and str(item.get("index")) == str(parca["index"]):
                    kayit = item
                    break
            if kayit is None and i < len(kayitlar) and isinstance(kayitlar[i], dict):
                kayit = kayitlar[i]
        sonuc.append(_kayit_normalize(parca, kayit, stil))
    return sonuc


def onizleme(kayitlar, adet=3):
    satirlar = []
    for kayit in kayitlar[:adet]:
        satirlar += [f"PARÇA {kayit['index']} · {kayit['start']:.1f}–{kayit['end']:.1f} sn",
                     "Görsel: " + kayit["image_prompt"],
                     "Video : " + kayit["video_prompt"], ""]
    return "\n".join(satirlar).strip()


def metin_raporu(kayitlar, *, metin, sure, parca_saniye, ses_bilgi, ai_bilgi, not_=""):
    """Üretilen prompt'ları okunur bir metin dosyası içeriğine çevir."""
    satirlar = [
        "StudioFlow · video prompt'ları",
        f"Tarih: {datetime.now():%Y-%m-%d %H:%M}",
        f"Anlatım metni: {len(metin.split())} kelime · {len(metin)} karakter",
        f"Toplam süre: {sure:.1f} saniye" + (f" · NOT: {not_}" if not_ else ""),
        f"Parça süresi: {parca_saniye:g} saniye · parça sayısı: {len(kayitlar)}",
        f"Seslendirme: {ses_bilgi}",
        f"Prompt yapay zekâsı: {ai_bilgi}",
        "",
        "ANLATIM METNİ",
        metin.strip(),
        "",
    ]
    for kayit in kayitlar:
        satirlar += [
            "=" * 64,
            f"PARÇA {kayit['index']}/{len(kayitlar)} · {kayit['start']:.1f}–{kayit['end']:.1f} sn",
            f"Anlatım: {kayit['text']}",
            "",
            f"Görsel prompt: {kayit['image_prompt']}",
            "",
            f"Video prompt: {kayit['video_prompt']}",
            "",
        ]
    return "\n".join(satirlar)


def masaustu_klasoru():
    """Masaüstü klasörünü bul (OneDrive taşınmış masaüstünü de dener)."""
    ev = Path(os.path.expanduser("~"))
    adaylar = [ev / "Desktop"]
    try:
        for klasor in sorted(ev.glob("OneDrive*/Desktop")):
            adaylar.insert(0, klasor)
    except OSError:
        pass
    for aday in adaylar:
        if aday.is_dir():
            return aday
    return adaylar[0]


def dosyalari_yaz(icerik, ad=None):
    """İçeriği masaüstüne ve outputs/prompts klasörüne yaz."""
    ad = ad or f"prompt_{datetime.now():%Y%m%d_%H%M%S}.txt"
    yazilan = []
    for klasor in (masaustu_klasoru(), OUTPUTS / "prompts"):
        try:
            klasor.mkdir(parents=True, exist_ok=True)
            hedef = klasor / ad
            hedef.write_text(icerik, encoding="utf-8")
            yazilan.append(hedef)
        except OSError:
            continue
    return yazilan


class PromptUretici:
    """Belirli bir metin yapay zekâsıyla bağlı prompt üreticisi."""

    def __init__(self, ai=None):
        self.ai = ai or metin_ai.VARSAYILAN

    def grup(self, provider, anahtar, model, grup, dil, stil, **secenekler):
        return prompt_grubu_uret(provider, anahtar, model, grup, dil, stil, ai=self.ai,
                                 **secenekler)
