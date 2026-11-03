"""Karakter kütüphanesi: hazır karakterler (referans görsel + İngilizce tarif) ve arama.

Kütüphane veri klasöründedir (`<veri>\\Karakterler`): `karakterler.json` her karakterin
adını, Latince adını, grubunu, tarifini ve görselin kütüphaneye göreli yolunu taşır.
Karakter kadroya eklenince görsel projeye kopyalanır (bkz. `icerik.kadro_kaydet`), yani
kütüphane yalnızca okunur.

Arama iki katmanlıdır: önce ad/grup/tarif içinde yerel kelime eşleşmesi (anında, kota
harcamaz), sonra metin yapay zekâsı katalogdan anlamca alakalı karakterleri seçer
("kırmızı balık", "Afrika gölü", "salyangoz yiyen"). Yapay zekâ yanıt veremezse yerel
sonuçlar yine döner.
"""
import json
import random
import re
import threading
from pathlib import Path

from sunucu import ayar
from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek import yollar
from studioflow.saglayicilar import metin_ai
from studioflow.saglayicilar.metin_ortak import ai_anahtari

KOK = yollar.VERI / "Karakterler" if yollar.KURULU else ayar.EDITOR_KOK / "karakterler"
ORNEK_SAYISI = 4
AZAMI_SONUC = 12

_kilit = threading.Lock()
_onbellek = {"zaman": None, "liste": []}


def _oku():
    """Kataloğu oku; dosya değişmediyse bellekteki kopya kullanılır."""
    dosya = KOK / "karakterler.json"
    try:
        zaman = dosya.stat().st_mtime
    except OSError:
        return []
    with _kilit:
        if _onbellek["zaman"] != zaman:
            try:
                ham = json.loads(dosya.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                ham = []
            liste = []
            for sira, k in enumerate(ham if isinstance(ham, list) else []):
                yol = KOK / str(k.get("gorsel") or "")
                if k.get("ad") and yol.is_file():
                    liste.append({"no": sira, "ad": str(k["ad"]), "latin": str(k.get("latin") or ""),
                                  "grup": str(k.get("grup") or ""), "tarif": str(k.get("tarif") or ""),
                                  "gorsel": str(k["gorsel"])})
            _onbellek.update(zaman=zaman, liste=liste)
        return _onbellek["liste"]


def _disari(k):
    return {"ad": k["ad"], "latin": k["latin"], "grup": k["grup"], "tarif": k["tarif"],
            "yol": str((KOK / k["gorsel"]).resolve()),
            "adres": "/kutuphane/" + "/".join(Path(k["gorsel"]).parts)}


_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def _sade(metin):
    return re.sub(r"[^a-z0-9 ]+", " ", str(metin).casefold().translate(_TR))


def _yerel(liste, sorgu):
    """Kelime eşleşmesi: adda geçen kelime grup/tariftekinden ağır basar."""
    kelimeler = [k for k in _sade(sorgu).split() if len(k) > 1]
    if not kelimeler:
        return []
    puanli = []
    for k in liste:
        ad, ust, tarif = _sade(f"{k['ad']} {k['latin']}"), _sade(k["grup"]), _sade(k["tarif"])
        puan = sum(3 * (w in ad) + 2 * (w in ust) + (w in tarif) for w in kelimeler)
        if puan:
            puanli.append((puan, k["no"]))
    puanli.sort(key=lambda x: -x[0])
    return [no for _, no in puanli]


_SISTEM = (
    "You pick characters from an aquarium character catalog for a video editor. The user "
    "types a search in Turkish or English. Return the catalog numbers of the characters that "
    "match the search by species, common name, group, color, pattern, habitat, size or "
    "behaviour, best match first, at most {azami}. If nothing fits, return an empty list. "
    'Answer only with JSON: {{"sonuc": [numbers]}}')


def _yapay_zeka(liste, sorgu):
    """Metin yapay zekâsından alakalı katalog numaralarını iste; yanıt yoksa `None`."""
    katalog = "\n".join(f"{k['no']}|{k['ad']}|{k['latin']}|{k['grup']}|"
                        f"{' '.join(k['tarif'].split()[:16])}" for k in liste)
    try:
        anahtar = ai_anahtari("cloudflare", api_hesaplari.VARSAYILAN.aktif_degerler("cloudflare"))
        yanit = metin_ai.VARSAYILAN.metin(
            "cloudflare", anahtar, "", _SISTEM.format(azami=AZAMI_SONUC),
            f"Search: {sorgu}\n\nCatalog (number|name|latin|group|look):\n{katalog}", json_modu=True)
    except Exception:
        return None
    eslesme = re.search(r"\{.*\}", str(yanit or ""), re.S)
    try:
        sayilar = json.loads(eslesme.group(0)).get("sonuc") if eslesme else None
    except ValueError:
        sayilar = re.findall(r"\d+", eslesme.group(0)) if eslesme else None
    if not isinstance(sayilar, list):
        return None
    gecerli = {k["no"] for k in liste}
    sonuc = []
    for s in sayilar:
        try:
            no = int(s)
        except (TypeError, ValueError):
            continue
        if no in gecerli and no not in sonuc:
            sonuc.append(no)
    return sonuc


def ara(sorgu="", yapay_zeka=True):
    """Boş sorgu: rastgele örnek karakterler. Dolu sorgu: alakalı karakterler (en fazla 12)."""
    liste = _oku()
    if not liste:
        return {"karakterler": [], "toplam": 0, "sorgu": "", "klasor": str(KOK),
                "mesaj": f"Karakter kütüphanesi boş: {KOK} klasörüne karakterler.json ve görselleri koy."}
    sorgu = " ".join(str(sorgu or "").split())[:120]
    if not sorgu:
        # Örnekler farklı gruplardan seçilir: kütüphanenin çeşitliliği görünsün.
        gruplar = {}
        for k in liste:
            gruplar.setdefault(k["grup"], []).append(k)
        secilen = [random.choice(g) for g in random.sample(list(gruplar.values()), min(ORNEK_SAYISI, len(gruplar)))]
        return {"karakterler": [_disari(k) for k in secilen], "toplam": len(liste), "sorgu": "",
                "mesaj": ""}
    yerel = _yerel(liste, sorgu)
    yz = _yapay_zeka(liste, sorgu) if yapay_zeka else None
    sirali = (yz or []) + [no for no in yerel if no not in (yz or [])]
    bul = {k["no"]: k for k in liste}
    sonuc = [_disari(bul[no]) for no in sirali[:AZAMI_SONUC]]
    if yz is None and yapay_zeka:
        mesaj = "Yapay zekâ yanıt vermedi; yalnızca ad ve tarif eşleşmeleri gösteriliyor."
    else:
        mesaj = "" if sonuc else f"“{sorgu}” için karakter bulunamadı."
    return {"karakterler": sonuc, "toplam": len(liste), "sorgu": sorgu, "mesaj": mesaj}


def dosya(yol):
    """Kütüphane görseli; kütüphane dışına çıkan yol reddedilir."""
    try:
        hedef = (KOK / yol).resolve()
        hedef.relative_to(KOK.resolve())
    except (ValueError, OSError):
        return None
    return hedef if hedef.is_file() else None
