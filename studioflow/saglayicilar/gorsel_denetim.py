"""Görsel hakem: üretilen kareyi **yalnızca stratejinin özel filtresiyle** denetler.

Genel denetim kaldırıldı (05.10.2026). Hakem eskiden her kareyi bir denetim listesine
(nesne maddeleri, kolaj, sahne çelişkisi) ve kalite alanlarına (anatomi, fizik, ışık,
süreklilik, hareket) göre denetliyordu. Ölçüm (160 elle puanlı kare, `llama-4-scout`):
hatalı karelerin yalnızca %47'sini yakaladı (kopya karakter, yakın plan yerine tam
gövde, fazladan boynuz, kanatlı tek gözlü ejder geçti), doğru karelerin %15'ini
reddetti; referans görselleri görmediği için karakter kimliğine kördü. Geçmeyen kare
aynı prompt'la yeniden üretiliyordu ve aynı prompt 31 sahnenin 30'unda aynı sonucu
verdi: kota harcanıyor, kare düzelmiyordu. Türk mitolojisi projesinde 154 karenin
55'i yeniden üretildi; kalma gerekçelerinin çoğu "tek kareden süreklilik
değerlendirilemez", "durağan görselde hareket yok" gibi asılsız kalite kararlarıydı.
Kareyi baştan doğru kurmak prompt yazımının işidir (bkz. `adim_promptlari._MELEZ_KURALLARI`).

Kalan iki filtre, her biri yalnızca kendi stratejisinde:
- **Tarih**: dönem kıyafeti ve dönem mekânı (`kiyafet` analizi `tarihsel: true` ise);
- **Birinci kişi**: kamera anlatıcının gözü mü (`pov`).
Default stratejide hakem hiç çağrılmaz.

Görsel üretimiyle aynı Cloudflare hesabını kullanır; ayrı anahtar istemez. Hakem hata
verirse (ağ, kota) `None` döner.
"""
import base64
import io
import json
import re

import requests

from studioflow.cekirdek.cloudflare_http import CF_API, cf_error

# Sırayla denenir: ilki ölçüldü; ikincisi yalnızca ilki hata verirse (model kaldırıldı,
# geçici arıza) devreye girer.
HAKEM_MODELLERI = ("@cf/meta/llama-4-scout-17b-16e-instruct",
                   "@cf/mistralai/mistral-small-3.1-24b-instruct")

# Hakeme gönderilen kare küçültülür: karar için yeterli, token (nöron) maliyeti düşük.
# Yalnızca hakemin kopyası küçülür; üretilen kare dosyası değişmez.
HAKEM_BOYUTU = (896, 896)

SISTEM = (
    "You are a strict visual QA inspector for AI-generated film frames. You receive one "
    "image and the prompt it was generated from. Check ONLY the checks listed below; "
    "nothing else (composition, anatomy, style, missing objects) is your concern.\n"
    "Unassessed or uncertain checks mean false.\n")

# Tarih stratejisi: kıyafet ve çağ (mimari, araç, nesne) iki **bağımsız** kontroldür.
DONEM_SISTEM = (
    "PERIOD checks (this is a HISTORICAL reconstruction; strict, never 'minor nuances'):\n"
    "wardrobe_ok (boolean) and wardrobe_reason (short text): evaluate ALL visible people, "
    "including background workers, against the supplied era and role-specific wardrobe. "
    "Wrong-era garments (e.g. trousers, buttoned shirts, caps, boots in an Old Kingdom "
    "labourer reconstruction) fail. Do not require hidden garments or add people to an "
    "empty landscape.\n"
    "era_ok (boolean) and era_reason (short text): buildings, architecture, construction "
    "state, building materials, tools, vehicles, furniture, vessels and other objects must "
    "fit the supplied era and place (and its 'mimari' description when given). Later-era or "
    "other-culture architecture (medieval castles, Greco-Roman columns, domes, arches, "
    "concrete, glass, metal machinery, wheels where unknown) or a monument shown finished "
    "while the narration is about its construction fail. 'mimari' lists what MAY appear in "
    "this era, never what every frame must show: judge era_ok only by what IS visible.\n")

# Birinci kişi stratejisi: kamera anlatıcının gözüdür.
POV_SISTEM = (
    "VIEWPOINT check (first-person video):\n"
    "pov_ok (boolean) and pov_reason (short text): the camera is the narrator's own eyes. "
    "The frame must NOT show the narrator's own back, face, head, nape or whole body from "
    "outside: that is an external camera and fails. Own limbs may or may not be visible; "
    "they are NOT required as proof of first-person. A sensation such as stone against the "
    "back is acceptable only when the visible frame shows its evidence (the wall, the "
    "shadow, the mat), never the narrator seen from outside.\n")

# Karar maddeleri: (JSON anahtarı, gerekçe anahtarı, kayıtta görünen ad).
KONTROLLER = {
    "wardrobe": ("wardrobe_ok", "wardrobe_reason", "dönem kıyafeti"),
    "era": ("era_ok", "era_reason", "dönem mekânı"),
    "pov": ("pov_ok", "pov_reason", "birinci kişi bakış açısı"),
}


def _kucult(dosya):
    from PIL import Image
    with Image.open(dosya) as kare:
        kare = kare.convert("RGB")
        kare.thumbnail(HAKEM_BOYUTU)
        tampon = io.BytesIO()
        kare.save(tampon, "JPEG", quality=85)
    return base64.b64encode(tampon.getvalue()).decode("ascii")


def _json_nesnesi(metin):
    """Yanıttaki ilk JSON nesnesini çöz (kod bloğu, ön/son metin olabilir)."""
    if isinstance(metin, dict):
        return metin
    metin = str(metin or "")
    bas, son = metin.find("{"), metin.rfind("}")
    if bas < 0 or son <= bas:
        return None
    try:
        return json.loads(metin[bas:son + 1])
    except ValueError:
        return None


def karar_ozeti(karar):
    """Kararı `proje.txt`e yazılacak tek satıra çevir.

    `2/2 geçti` · `1/2 · kaldı: dönem kıyafeti (trousers and caps on workers)`.
    """
    if not karar:
        return "denetlenemedi"
    parca = [f"{karar['puan']}/{karar['toplam']}" + (" geçti" if karar["gecti"] else "")]
    kalan = [f"{m['madde']} ({m['gorulen']})" if m.get("gorulen") else m["madde"]
             for m in karar["maddeler"] if not m["ok"]]
    if kalan:
        parca.append("kaldı: " + "; ".join(kalan))
    return " · ".join(parca)


def denetim_gerekli(kiyafet=None, pov=False):
    """Bu karede çalışacak özel filtre var mı? Yoksa hakem hiç çağrılmaz."""
    return bool(kiyafet and kiyafet.get("tarihsel") is True) or bool(pov)


class GorselHakem:
    """Kareyi stratejinin özel filtresiyle denetleyen Cloudflare görsel dil modeli."""

    def __init__(self, modeller=HAKEM_MODELLERI, zaman_asimi=120):
        self.modeller = tuple(modeller)
        self.zaman_asimi = zaman_asimi

    def _istek(self, model, hesap, token, sistem, kullanici, resim):
        govde = {"messages": [
            {"role": "system", "content": sistem},
            {"role": "user", "content": [
                {"type": "text", "text": kullanici},
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + resim}}]}],
            "max_tokens": 600, "temperature": 0}
        yanit = requests.post(f"{CF_API}/accounts/{hesap}/ai/run/{model}",
                              headers={"Authorization": f"Bearer {token}"},
                              json=govde, timeout=(20, self.zaman_asimi))
        if not yanit.ok:
            raise RuntimeError(cf_error(yanit))
        sonuc = (yanit.json() or {}).get("result") or {}
        metin = sonuc.get("response")
        if not metin:
            secim = (sonuc.get("choices") or [{}])[0]
            metin = (secim.get("message") or {}).get("content") or ""
        return metin

    def denetle(self, dosya, *, prompt, cf_account="", cf_token="", hatalar=None,
                kiyafet=None, pov=False):
        """Kareyi özel filtrelerle denetle. Dönüş: karar sözlüğü ya da `None`.

        `kiyafet` (Tarih stratejisi, `tarihsel: true` analiz) dönem kıyafeti ve mekânını,
        `pov` (Birinci kişi stratejisi) bakış açısını açar. İkisi de yoksa denetlenecek
        bir şey yoktur, `None` döner (çağıran hakemi zaten çağırmaz).

        Karar: `maddeler` (`madde`, `ok`, `gorulen`), `puan`, `toplam`, `gecti`,
        `kalite_hatalari` (kalan kontrollerin anahtarları), `model`.
        `hatalar` listesi verilirse denenen modellerin hata metinleri oraya eklenir.
        """
        tarihsel = bool(kiyafet and kiyafet.get("tarihsel") is True)
        anahtarlar = (("wardrobe", "era") if tarihsel else ()) + (("pov",) if pov else ())
        if not anahtarlar or not cf_account or not cf_token:
            return None
        try:
            resim = _kucult(dosya)
        except Exception as exc:          # bozuk/eksik dosya: denetlenemez
            if hatalar is not None:
                hatalar.append(f"kare okunamadı: {exc}")
            return None
        sistem = SISTEM + (DONEM_SISTEM if tarihsel else "") + (POV_SISTEM if pov else "")
        json_anahtarlari = ", ".join(f'"{KONTROLLER[k][0]}": <bool>, "{KONTROLLER[k][1]}": '
                                     '"<short text>"' for k in anahtarlar)
        sistem += "Reply ONLY with JSON: {" + json_anahtarlari + "}"
        kullanici = f"Prompt: {prompt}"
        if tarihsel:
            kullanici += ("\nPERIOD WARDROBE AND SETTING: "
                          + json.dumps(kiyafet, ensure_ascii=False))
        for model in self.modeller:
            try:
                ham = self._istek(model, cf_account.strip(), cf_token.strip(), sistem,
                                  kullanici, resim)
            except Exception as exc:
                if hatalar is not None:
                    hatalar.append(f"{model}: {exc}")
                continue
            karar = self._coz(ham, anahtarlar)
            if karar is not None:
                karar["model"] = model
                return karar
            if hatalar is not None:
                hatalar.append(f"{model}: yanıt okunamadı ({str(ham)[:80]})")
        return None

    @staticmethod
    def _coz(ham, anahtarlar):
        veri = _json_nesnesi(ham)
        if not isinstance(veri, dict):
            return None
        maddeler = []
        for anahtar in anahtarlar:
            alan, gerekce, ad = KONTROLLER[anahtar]
            # Yanıtsız kontrol **geçmedi** sayılır: sessiz atlama geçti anlamına gelmemeli.
            maddeler.append({"anahtar": anahtar, "madde": ad, "ok": veri.get(alan) is True,
                             "gorulen": " ".join(str(veri.get(gerekce) or "").split())[:100]})
        puan = sum(1 for m in maddeler if m["ok"])
        return {"maddeler": maddeler, "puan": puan, "toplam": len(maddeler),
                "gecti": puan == len(maddeler),
                "kalite_hatalari": [m["anahtar"] for m in maddeler if not m["ok"]]}


VARSAYILAN = GorselHakem()
