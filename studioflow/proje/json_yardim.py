"""Yapay zekâ yanıtından JSON çıkarma: kod bloğu ve fazladan metin tolere edilir."""
import json
import re


def _nesne_dizisi(metin):
    """Ard arda yazılmış JSON **nesnelerini** listeye topla (dizi parantezi yoksa).

    Bazı modeller (ör. Workers AI qwen3) uzun isteklerde diziyi sarmayı bırakıp
    nesneleri satır satır döndürüyor:

        {"index": 7, ...}
        {"index": 8, ...}

    Bu biçim eskiden hiç okunamıyordu: `json_listesi` `None` döndürüyor, çağıran
    taraf da sessizce yedek prompt'a düşüyordu. Nesneler sırayla çözülür; araya
    karışan metin (açıklama, virgül, satır sonu) atlanır.
    """
    cozucu = json.JSONDecoder()
    nesneler, konum = [], 0
    while konum < len(metin):
        bas = metin.find("{", konum)
        if bas == -1:
            break
        try:
            nesne, son = cozucu.raw_decode(metin, bas)
        except ValueError:
            konum = bas + 1
            continue
        if isinstance(nesne, dict):
            nesneler.append(nesne)
        konum = son
    return nesneler or None


# Tek bir kaydı tanıyan alanlar. Yalnızca bu alanlara bakılır: içinde yalnızca
# yardımcı bir dizi taşıyan nesne (ör. `{"uyarılar": [...]}`) kayıt sayılmaz.
_KAYIT_ALANLARI = ("index", "image_prompt", "video_prompt", "negative_prompt",
                   "scene_plan", "checklist", "cumleler", "saniye")


def _kayit_mi(veri):
    """Sözlük **tek bir kayıt** gibi mi görünüyor? (sahne prompt'u ya da plan nesnesi)"""
    return isinstance(veri, dict) and any(alan in veri for alan in _KAYIT_ALANLARI)


def json_listesi(cvp):
    """Yanıttan **kayıt listesini** çıkar; hiç kayıt yoksa `None` dön.

    Kabul edilen biçimler: düz dizi, kod bloğu içinde dizi, `parts`/`segments`/
    `results`/`items` sarmalayıcısı, **tek başına yazılmış tek nesne** ve dizi
    parantezi olmadan ard arda yazılmış nesneler (`_nesne_dizisi`).

    Tek nesne biçimi kritiktir: tek sahne yeniden yazılırken model diziyi
    sarmalamayıp yalnızca `{...}` yazıyor. Eskiden bu yanıt aşağıdaki `[...]`
    aramasına düşüyor ve nesnenin **içindeki** dizi (`checklist`) kayıt listesi
    sanılıyordu; eşleştirme bozuluyor, hata "yanlış index" gibi görünüyordu.
    """
    metin = (cvp or "").strip()
    if not metin:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", metin, re.S)
    if fence:
        metin = fence.group(1).strip()
    try:
        veri = json.loads(metin)
    except (ValueError, TypeError):
        veri = None
    if isinstance(veri, list):
        return veri
    if isinstance(veri, dict):
        sarmal = (veri.get("parts") or veri.get("segments")
                  or veri.get("results") or veri.get("items"))
        if isinstance(sarmal, list):
            return sarmal
        if _kayit_mi(sarmal):
            return [sarmal]
        if _kayit_mi(veri):
            return [veri]
    # Metnin içine gömülü **kayıt dizisi** ara. İç diziler (checklist, cumleler …)
    # kayıt listesi sayılmaz: dizinin en az bir nesne taşıması şart.
    a, b = metin.find("["), metin.rfind("]")
    if a != -1 and b > a:
        try:
            veri = json.loads(metin[a:b + 1])
            if isinstance(veri, list) and any(isinstance(oge, dict) for oge in veri):
                return veri
        except (ValueError, TypeError) as _:
            pass
    # Son çare: dizi parantezi olmadan ard arda yazılmış nesneler.
    return _nesne_dizisi(metin)


def json_nesnesi(cvp):
    """Yanıttan tek bir JSON nesnesi çıkar (kod bloğu ve fazladan metin tolere edilir)."""
    metin = (cvp or "").strip()
    if not metin:
        return None
    fence = re.search(r"```(?:json)?\s*(.+?)```", metin, re.S)
    if fence:
        metin = fence.group(1).strip()
    try:
        veri = json.loads(metin)
        if isinstance(veri, dict):
            return veri
        if isinstance(veri, list) and veri and isinstance(veri[0], dict):
            return veri[0]
    except (ValueError, TypeError):
        pass
    a, b = metin.find("{"), metin.rfind("}")
    if a != -1 and b > a:
        try:
            veri = json.loads(metin[a:b + 1])
            if isinstance(veri, dict):
                return veri
        except (ValueError, TypeError) as _:
            pass
    return None
