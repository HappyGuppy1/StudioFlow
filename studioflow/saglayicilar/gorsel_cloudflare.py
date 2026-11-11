"""Cloudflare Workers AI ile görsel üretimi.

Servis uzakta çalışır: hiçbir model bu bilgisayara indirilmez, istek uzaktaki
sunucuya gider ve inen görsel hedef klasöre kaydedilir (bkz. `cekirdek.depolama`: üretim
varsayılan olarak geçici klasöre yazılır, `outputs` yalnızca açıkça istenirse).

Kuyruk yoktur, tek REST çağrısı görseli saniyeler içinde döndürür. Account ID + API
token gerekir. Model tablosu (`CF_MODELS`) ve boyut/adım kuralları modül düzeyinde saf
işlevlerdir; üretim, doğrulama ve teşhis `CloudflareGorsel` sınıfındadır.
"""
import base64
import io
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import requests
from PIL import Image, ImageOps

from studioflow.cekirdek import depolama as _depolama
from studioflow.cekirdek.hatalar import gorsel_hatasi_temizle
from studioflow.cekirdek.cloudflare_http import (CF_API, CF_TOKENS_URL, cf_error,
                                                     cf_status_hint, is_plausible_cf_token,
                                                     cf_verify_urls, mask_account)
from studioflow.saglayicilar.taban import GorselSaglayici


CF_MODELS = [
    # ── FLUX.2 [klein] · sahneye sadakat ────────────────────────────────────
    # Ölçüm (Timur projesi, 14 sahne, aynı prompt'lar): SDXL base "yay geren atlı +
    # arkasında zırhlı fil", "çivi serpen askerler", "yalnızca yükü yanan develer" gibi
    # iki özneli / eylemli sahnelerin neredeyse hiçbirini kuramadı (kar, kum tepesi,
    # kolaj, eksik özne); klein 4B aynı prompt'larla 13 karenin 13'ünü sahneye uygun
    # kurdu. Sebep metin kodlayıcısı: SDXL'in CLIP'i 77 token okur ve özneleri
    # birbirine karıştırır, FLUX.2 bir dil modeli kodlayıcısıyla uzun cümleyi okur.
    #
    # Şema multipart form'dur (`istek`). Ölçülen davranış: `steps`, `guidance` ve
    # `seed` **kabul edilir ama yok sayılır** (aynı seed farklı kare verdi; bilinmeyen
    # alan da reddedilmedi), negatif prompt yoktur; boyut 16'nın katına yuvarlanır
    # (1080 → 1072). Bu yüzden tabloda yalnızca boyut vardır.
    # Maliyet (Cloudflare fiyat tablosu, 768×1344 ≈ 4 karo): 4B ≈ 105 nöron/kare
    # (günlük ücretsiz 10.000 nöronla ~95 kare), 9B ≈ 1370 nöron/kare (~7 kare).
    {
        "id": "@cf/black-forest-labs/flux-2-klein-4b",
        "label": "FLUX.2 klein 4B",
        "note": "Sahneyi en iyi kuran ücretsiz seçenek: iki özneli ve eylemli sahneleri "
                "(yay geren atlı, arkasında fil) doğru kurar. Dikey/yatay boyut serbest. "
                "Negatif prompt almaz; yasaklar prompt'un kendisinde tarif edilir. "
                "Kare başına ~105 nöron (günlük ücretsiz kotayla ~95 kare).",
        "tag": "önerilen",
        "response": "json",
        "istek": "multipart",
        "kelime_siniri": 100,
        "stil_ayri": True,
        "size": {"min": 256, "max": 2048, "step": 16, "default": 1024},
        "size_label": None,
        "negative_prompt": False,
        "seed": False,
        # Referans görsel (`input_image_0..3`): Araçlar › Sabit karakter bununla
        # karakteri sahneden sahneye taşır. Belge: en fazla 4 görsel, her biri <512×512.
        "referans": 4,
        "fields": [],
    },
    {
        "id": "@cf/black-forest-labs/flux-2-klein-9b",
        "label": "FLUX.2 klein 9B",
        "note": "Klein 4B'nin büyük kardeşi: aynı özellikler, biraz daha iyi el ve doku. "
                "Kare başına ~1370 nöron — günlük ücretsiz kota yalnızca ~7 kareye yeter.",
        "tag": "yüksek maliyet",
        "response": "json",
        "istek": "multipart",
        "kelime_siniri": 100,
        "stil_ayri": True,
        "size": {"min": 256, "max": 2048, "step": 16, "default": 1024},
        "size_label": None,
        "negative_prompt": False,
        "seed": False,
        # Referans görsel (`input_image_0..3`): Araçlar › Sabit karakter bununla
        # karakteri sahneden sahneye taşır. Belge: en fazla 4 görsel, her biri <512×512.
        "referans": 4,
        "fields": [],
    },
    {
        "id": "@cf/black-forest-labs/flux-1-schnell",
        "label": "FLUX.1 schnell",
        "note": "Hızlı ve zengin sahne. Çözünürlük 1024×1024 sabittir, adım en fazla 8.",
        "tag": "",
        "kelime_siniri": 100,
        "stil_ayri": True,
        "response": "json",
        "size": None,
        "size_label": "1024 × 1024 (model sabit tutar)",
        "negative_prompt": False,
        # FLUX'ın şeması **yalnızca** `prompt` ve `steps` kabul eder: seed gönderilirse
        # Cloudflare isteğin tamamını reddeder ("Bad input: '/seed' not allowed").
        "seed": False,
        "fields": [{"name": "steps", "min": 1, "max": 8, "default": 4}],
    },
    {
        "id": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "label": "Stable Diffusion XL base 1.0",
        "note": "Klasik SDXL, 1024×1024 native. Negatif prompt destekler. Prompt "
                "bağlılığı (guidance) 6 önerilir.",
        "tag": "",
        "response": "binary",
        "size": {"min": 256, "max": 2048, "step": 64, "default": 1024},
        "size_label": None,
        "negative_prompt": True,
        # Guidance varsayılanı **6,0**. 4 sahne x 2 seed x 4 değer (5 / 6 / 7 / 7,5)
        # ile 32 kare üretilip ölçüldü; sonuç şu: **5–7,5 aralığında tutarlı bir
        # kazanan yok** — aynı değer bir sahnede öne çıkıp diğerinde geriye düşüyor,
        # yani seed farkı guidance farkından büyük. Ölçülebilir tek sistematik etki
        # renkte: doygunluk guidance ile tekdüze artıyor ve kırpılmış (yanmış/ezilmiş)
        # piksel oranı 7,5'te ortalama %1,33'e çıkarken 6,0'da %0,01'de kalıyor.
        # Ayrı bir deneme alt sınırı gösterdi: 3,0'da model fotogerçekçiliği bırakıp
        # resme kayıyor, 4,5 puslu kalıyor. Yani 6,0 "her karede en iyi" değil,
        # **en güvenli orta** değerdir; 5,5–7 arası pratikte eşdeğerdir.
        "fields": [{"name": "num_steps", "min": 1, "max": 20, "default": 20},
                   {"name": "guidance", "min": 1, "max": 15, "default": 6.0}],
    },
    {
        "id": "@cf/bytedance/stable-diffusion-xl-lightning",
        "label": "SDXL Lightning (ByteDance)",
        "note": "SDXL'in hızlandırılmış sürümü: 4 adımda 1024×1024 üretir.",
        "tag": "",
        "response": "binary",
        "size": {"min": 256, "max": 2048, "step": 64, "default": 1024},
        "size_label": None,
        "negative_prompt": True,
        "seed": True,
        "fields": [{"name": "num_steps", "min": 1, "max": 20, "default": 4},
                   {"name": "guidance", "min": 1, "max": 15, "default": 7.5}],
    },
    {
        "id": "@cf/lykon/dreamshaper-8-lcm",
        "label": "DreamShaper 8 LCM",
        "note": "Fotoğraf gerçekçi SD 1.5 tabanlı: 512-768'de kal. LCM olduğu için 4-8 adım yeter.",
        "tag": "",
        "response": "binary",
        "size": {"min": 256, "max": 2048, "step": 64, "default": 512},
        "size_label": None,
        "onerilen": (512, 768),
        "negative_prompt": True,
        "seed": True,
        "fields": [{"name": "num_steps", "min": 1, "max": 20, "default": 8},
                   {"name": "guidance", "min": 1, "max": 15, "default": 7.5}],
    },
    {
        "id": "@cf/leonardo/lucid-origin",
        "label": "Lucid Origin (Leonardo) — ücretli",
        "note": "Leonardo'nun partner modeli: prompt'u en iyi takip eder. Ücretli plan gerekir.",
        "tag": "ücretli",
        "response": "json",
        # Cloudflare şeması 0–2500 diyor; 0 "otomatik" anlamına geldiği için alt sınırı
        # 256 alıyoruz. Ücretlendirme karo (512×512) başına olduğundan büyük boyutta
        # maliyet hızla artar.
        "size": {"min": 256, "max": 2500, "step": 16, "default": 1120},
        "size_label": None,
        "negative_prompt": False,
        "seed": True,
        "fields": [{"name": "num_steps", "min": 1, "max": 40, "default": 25},
                   {"name": "guidance", "min": 0, "max": 10, "default": 4.5}],
    },
]


CF_VERIFY_MODEL = "@cf/lykon/dreamshaper-8-lcm"


# Model kısa adları: ön ayarlar ve arayüz uzun `@cf/...` kimliklerini elle yazmasın.
CF_MODEL_ID = {spec["id"].rsplit("/", 1)[-1]: spec["id"] for spec in CF_MODELS}


# Varsayılan görsel üretim yolu: Cloudflare Workers AI. Kuyruk yoktur, anahtar girildiği
# anda saniyeler içinde üretir; varsayılan model de en hızlısıdır (SDXL Lightning: 4 adım,
# 1024×1024 ve negatif prompt destekli), böylece ücretli plana gerek kalmaz.
VARSAYILAN_SAGLAYICI = "cloudflare"


VARSAYILAN_MODEL = CF_MODEL_ID["stable-diffusion-xl-lightning"]


def cf_run_url(account_id, model_id):
    """Workers AI üretim adresi.

    Dikkat: model adı yolda `@cf/...` olarak, eğik çizgiler kodlanmadan yazılmalıdır.
    `%2F` ile kodlanırsa Cloudflare "No route for that URI" hatası döndürür.
    """
    return (f"{CF_API}/accounts/{quote(account_id.strip(), safe='')}"
            f"/ai/run/{quote(model_id, safe='@/')}")


# Arayüzde tek bir "adım" ve "guidance" alanı var; model hangi adı bekliyorsa ona yazılır.
CF_FIELD_SOURCES = {"steps": "steps", "num_steps": "steps", "guidance": "guidance"}


def cf_model_spec(model_id):
    for spec in CF_MODELS:
        if spec["id"] == model_id:
            return spec
    return None


def cf_model_choices():
    return [(f"{spec['label']}  [{spec['tag']}]" if spec["tag"] else spec["label"], spec["id"])
            for spec in CF_MODELS]


def cf_note(model_id):
    spec = cf_model_spec(model_id)
    if spec is None:
        return ""
    onerilen = spec.get("onerilen")
    if onerilen:
        return (spec["note"] + f" En iyi sonuç {onerilen[0]}–{onerilen[1]} px arasında "
                "alınır; üstüne çıkarsan hız düşer ve detay bozulabilir.")
    return spec["note"]


def cf_size_options(model_id):
    spec = cf_model_spec(model_id)
    size = spec["size"] if spec else None
    if not size:
        return None
    return list(range(size["min"], size["max"] + 1, size["step"]))


def cf_size_default(model_id):
    spec = cf_model_spec(model_id)
    return (spec["size"] or {}).get("default") if spec and spec["size"] else None


def cf_size_range(model_id):
    """Cloudflare'in o model için izin verdiği `(min, max, step)`; sabitse `None`.

    Aralıklar model tablosundaki değerlerdir; tablo Cloudflare dokümanlarıyla
    eşleşir (SDXL ailesi 256–2048, Lucid 256–2500/16, FLUX boyut almaz).
    """
    size = (cf_model_spec(model_id) or {}).get("size")
    return (size["min"], size["max"], size["step"]) if size else None


def cf_size_recommended(model_id):
    """Modelin en iyi sonuç verdiği boyut (varsa); yalnızca nota/uyarı için."""
    return (cf_model_spec(model_id) or {}).get("onerilen")


def size_range(model=""):
    """Seçili modelin boyut aralığı: `(min, max, step, varsayılan)`.

    Boyutu model sabitliyorsa (FLUX 1024×1024) `None` döner: çağıran slider'ları
    kilitleyip model notunu gösterir.
    """
    spec = cf_model_spec(model)
    if not spec or not spec.get("size"):
        return None
    size = spec["size"]
    return size["min"], size["max"], size["step"], size["default"]


def size_clamp(model, width, height):
    """Boyutu servisin aralığına **ve adımına** oturt.

    Arayüz slider'ı da bu aralıktan beslenir; `proje.txt` elle düzenlenirse aynı
    kurala göre kırpılır (64'ün katı, modelin alt–üst sınırı). Sabit boyutlu
    modelde `(None, None)` döner.
    """
    aralik = size_range(model)
    if aralik is None:
        return None, None
    alt, ust, adim, varsayilan = aralik

    def oturt(deger):
        try:
            sayi = int(float(deger))
        except (TypeError, ValueError):
            sayi = varsayilan
        sayi = max(alt, min(ust, sayi))
        return max(alt, int(round(sayi / adim) * adim)) if adim > 1 else sayi

    return oturt(width), oturt(height)


def cf_steps_range(model_id):
    spec = cf_model_spec(model_id)
    for field in (spec or {}).get("fields", []):
        if field["name"] in ("steps", "num_steps"):
            return field["min"], field["max"], field["default"]
    return 1, 20, 8


def cf_guidance_range(model_id):
    spec = cf_model_spec(model_id)
    for field in (spec or {}).get("fields", []):
        if field["name"] == "guidance":
            return field["min"], field["max"], field["default"]
    return 1, 15, 7.5


def cf_supports_negative(model_id):
    spec = cf_model_spec(model_id)
    return bool(spec and spec["negative_prompt"])


def prompt_kelime_siniri(model="", varsayilan=55):
    """Görsel modelinin prompt'tan **gerçekten okuduğu** kelime sayısı.

    SDXL ailesinin metin kodlayıcısı (CLIP) 77 token okur ≈ 55 kelime; sonrası sessizce
    atılır (bkz. `docs/PROMPT-OLCUMLERI.md`). FLUX modelleri uzun metin okuyan bir dil
    modeli kodlayıcısı kullanır; tablodaki `kelime_siniri` bu modellerde sahneye daha
    çok yer bırakır. Tabloda yazmayan model CLIP varsayılır (güvenli taraf).
    """
    return int((cf_model_spec(model) or {}).get("kelime_siniri") or varsayilan)


def stil_butce_disi(model=""):
    """Stil katmanı kelime bütçesinin **dışında** mı (tamamı her zaman eklenir mi)?

    CLIP'li modellerde (SDXL ailesi) bütçe gerçek bir okuma sınırıdır: stil ile sahne
    aynı ~55 kelimeyi paylaşır. FLUX modelleri uzun metni okur; orada `kelime_siniri`
    yalnızca **sahne içeriğine** ayrılır ve stil üstüne eklenir. Ölçüm (piramit,
    28.09.2026): 12 sahnenin 7'si 90–100 kelimeydi; stil içerikle aynı 100 kelimeyi
    paylaştığı için sahneden sahneye farklı parçası düşüyor, birinci kişide sona
    yazılan "photorealistic" kısmı ilk atılan oluyordu.
    """
    return bool((cf_model_spec(model) or {}).get("stil_ayri"))


def cf_supports_seed(model_id):
    """Model `seed` alanını kabul ediyor mu? (şema tablosundan)"""
    spec = cf_model_spec(model_id)
    return bool(spec is None or spec.get("seed", True))


def supports_seed(model=""):
    """Seçili görsel modeli seed (tekrarlanabilirlik) destekliyor mu?

    FLUX.1 schnell desteklemez: şeması yalnızca `prompt` ve `steps` alır. Desteklemeyen
    modelde seed **gönderilmez**; arayüz de kutuyu kilitler (bkz. `seed_alan_gorunumu`).
    """
    return cf_supports_seed(model)


def supports_negative(model=""):
    """Seçili görsel modeli negatif prompt destekliyor mu?

    Modelin kendi şeması belirler: SDXL tabanlılar destekler, FLUX.1 schnell ve Lucid
    Origin desteklemez.
    """
    return cf_supports_negative(model)


# Referans görselin uzun kenarı: belge "512×512'den küçük" ister, sınırın hemen altı.
REFERANS_KENAR = 496


def referans_siniri(model=""):
    """Model kaç referans görsel kabul ediyor? (0: referans almaz)"""
    spec = cf_model_spec(model) or {}
    return int(spec.get("referans") or 0)


def referans_modelleri():
    """Referans görsel alan modeller (açılır liste seçenekleri)."""
    return [(etiket, deger) for etiket, deger in cf_model_choices() if referans_siniri(deger)]


def referans_hazirla(yol):
    """Referans görseli Cloudflare'in kabul ettiği boyuta küçült; PNG baytları döndür.

    Saydam arka plan beyaza oturtulur: yüklenen PNG karakterlerde saydam alan modele
    siyah gidip karakterin rengini bozabiliyor.
    """
    with Image.open(yol) as kaynak:
        gorsel = ImageOps.exif_transpose(kaynak)
        if gorsel.mode in ("RGBA", "LA", "P"):
            gorsel = gorsel.convert("RGBA")
            zemin = Image.new("RGB", gorsel.size, "white")
            zemin.paste(gorsel, mask=gorsel.getchannel("A"))
            gorsel = zemin
        gorsel = gorsel.convert("RGB")
        gorsel.thumbnail((REFERANS_KENAR, REFERANS_KENAR))
        tampon = io.BytesIO()
        gorsel.save(tampon, "PNG")
        return tampon.getvalue()


def build_cf_payload(spec, *, prompt, negative="", seed="", width=None, height=None,
                     steps=None, guidance=None):
    def sinirla(deger, alt, ust, varsayilan, tip):
        try:
            return max(alt, min(ust, tip(deger)))
        except (TypeError, ValueError):
            return varsayilan

    payload = {"prompt": (prompt or "").strip()}
    if spec.get("negative_prompt") and (negative or "").strip():
        payload["negative_prompt"] = negative.strip()

    # Seed yalnızca **şemasında olan** modele gönderilir: FLUX fazladan alan gelince
    # isteğin tamamını reddeder, kullanıcı da anlamsız bir "Bad input" hatası görürdü.
    seed = str(seed or "").strip()
    if seed and spec.get("seed", True):
        try:
            payload["seed"] = int(seed)
        except ValueError:
            pass  # geçersiz seed -> rastgele bırak

    size = spec.get("size")
    if size:
        payload["width"] = sinirla(width, size["min"], size["max"], size["default"], int)
        payload["height"] = sinirla(height, size["min"], size["max"], size["default"], int)

    verilen = {"steps": steps, "guidance": guidance}
    for field in spec["fields"]:
        kaynak = verilen.get(CF_FIELD_SOURCES.get(field["name"], ""))
        if kaynak is None:
            payload[field["name"]] = field["default"]
            continue
        tip = int if field["name"] in ("steps", "num_steps") else float
        payload[field["name"]] = sinirla(kaynak, field["min"], field["max"], field["default"], tip)
    return payload


def guess_image_extension(data):
    """Uzantıyı baytların kendisinden bul; yanlış Content-Type arayüzü bozmasın."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def cf_read_images(response):
    """Cloudflare yanıtını görüntüye çevirir: ya ham bayt ya da base64 JSON."""
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "json" in content_type:
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("Cloudflare yanıtı okunamadı (geçersiz JSON).") from None
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(cf_error(response))
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, dict) and result.get("image"):
            blob = base64.b64decode(result["image"])
            return [(blob, guess_image_extension(blob))]
        raise RuntimeError("Yanıtta görsel yok: " + json.dumps(data, ensure_ascii=False)[:300])

    blob = response.content or b""
    if not blob:
        raise RuntimeError("Cloudflare boş yanıt döndürdü.")
    if not blob.startswith((b"\x89PNG", b"\xff\xd8\xff", b"RIFF")):
        # Hata gövdesi görsel yerine inmesin; metni olduğu gibi bildir.
        raise RuntimeError("Cloudflare görsel yerine şu yanıtı döndürdü: "
                           + blob[:300].decode("utf-8", "replace"))
    return [(blob, guess_image_extension(blob))]


CF_NO_ACCOUNT_MESSAGE = ("Bu token hiçbir hesap listelemiyor; yani token'a bir hesap kaynağı "
                         "atanmamış görünüyor. Account ID'yi elle girmeyi deneyebilirsin.")


CF_SCOPE_FIX = ("Token oluştururken en sık yapılan hata: izinleri seçtikten sonra 'Account "
                "Resources' kısmında hesabını seçmemek. Yapılacak: My Profile > API Tokens > "
                "(yeni token ya da mevcut token'ı Edit) → Permissions: Account · Workers AI · "
                "Edit → Account Resources: hesabını işaretle → Zone Resources: boş bırak → "
                "Create/Save.")


# ---------------------------------------------------------- ön ayarlar
# Her ön ayar tek seçimle birkaç alanı birlikte kurar: model, boyut, adım ve guidance.
# Değerler yukarıdaki model tablosundan gelir, yani modelin izin verdiği aralığın
# dışına çıkamaz. Liste sabittir, ağ çağrısı yapmaz.
GORSEL_ON_AYARLAR = {
    "": {"ad": "— elle ayarla —", "not": "Alanları kendin seç."},
    "taslak": {
        "ad": "Hızlı taslak · SDXL Lightning 1024×1024 · 4 adım",
        "not": "Cloudflare, kuyruk yok: en hızlı deneme. 4 adımda 1024×1024 üretir.",
        "provider": "cloudflare", "model": CF_MODEL_ID["stable-diffusion-xl-lightning"],
        "width": 1024, "height": 1024, "steps": 4, "guidance": 7.5},
    "flux2": {
        "ad": "Sahneye sadık · FLUX.2 klein 4B 1024×1024",
        "not": "Prompt'taki sahneyi en iyi kuran ücretsiz model; boyut serbest, negatif "
               "prompt kullanmaz.",
        "provider": "cloudflare", "model": CF_MODEL_ID["flux-2-klein-4b"],
        "width": 1024, "height": 1024, "steps": 4, "guidance": 6.0},
    "flux": {
        "ad": "Yüksek kalite · FLUX.1 schnell 1024×1024 · 8 adım",
        "not": "En kaliteli model; boyutu kendisi sabitler (1024×1024) ve negatif "
               "prompt kullanmaz.",
        "provider": "cloudflare", "model": CF_MODEL_ID["flux-1-schnell"],
        "width": 1024, "height": 1024, "steps": 8, "guidance": 7.5},
    "sdxl": {
        "ad": "SDXL detaylı · 1024×1024 · 20 adım",
        "not": "Klasik SDXL: negatif prompt destekler, 20 adımda detaylı sonuç verir.",
        "provider": "cloudflare", "model": CF_MODEL_ID["stable-diffusion-xl-base-1.0"],
        "width": 1024, "height": 1024, "steps": 20, "guidance": 7.5},
    "dreamshaper": {
        "ad": "DreamShaper gerçekçi · 512×768 · 8 adım",
        "not": "Fotoğraf gerçekçi yüzler ve dokular; SD 1.5 tabanlı olduğu için "
               "768 px üstünde bozulur.",
        "provider": "cloudflare", "model": CF_MODEL_ID["dreamshaper-8-lcm"],
        "width": 512, "height": 768, "steps": 8, "guidance": 7.5},
    "lucid": {
        "ad": "Lucid Origin · 1120×1120 · 25 adım (ücretli)",
        "not": "Prompt'u en iyi takip eden model; ücretli plan gerekir ve karo başına "
               "ücretlendirilir.",
        "provider": "cloudflare", "model": CF_MODEL_ID["lucid-origin"],
        "width": 1120, "height": 1120, "steps": 25, "guidance": 4.5},
}


def on_ayar_secenekleri():
    """Gradio Dropdown için ön ayar listesi: `(etiket, değer)`."""
    return [(bilgi["ad"], anahtar) for anahtar, bilgi in GORSEL_ON_AYARLAR.items()]


def on_ayar_uygula(ad):
    """Ön ayarı alan değerlerine çevir; "elle" ya da bilinmeyen adda `None` döner."""
    ayar = GORSEL_ON_AYARLAR.get((ad or "").strip())
    if not ayar or "provider" not in ayar:
        return None
    alanlar = ("model", "width", "height", "steps", "guidance")
    return {alan: ayar[alan] for alan in alanlar}


def on_ayar_notu(ad):
    """Ön ayarın kısa açıklaması."""
    return (GORSEL_ON_AYARLAR.get((ad or "").strip()) or {}).get("not", "")


class CloudflareGorsel(GorselSaglayici):
    """Görsel üretimi, hesap listeleme, token doğrulama ve teşhis."""

    ad = "cloudflare"

    def __init__(self, depolama=None):
        self.depolama = depolama or _depolama.VARSAYILAN

    def modeller(self):
        return cf_model_choices()

    def _kaydet(self, blob, extension, prefix, klasor=None):
        """Görseli hedef klasöre yaz (otomatik kaydetme kapalıysa geçici klasöre).

        `klasor` verilirse (proje üretimi) görsel yalnızca oraya yazılır.
        """
        if klasor:
            klasor = Path(klasor)
            klasor.mkdir(parents=True, exist_ok=True)
        else:
            klasor = self.depolama.hedef_klasoru("images")
        filename = f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}{extension}"
        path = klasor / filename
        path.write_bytes(blob)
        return path

    def uret(self, *, prompt, model="", width=512, height=512, steps=30,
                        guidance=7.5, count=1, seed="", negative="",
                        cf_account="", cf_token="", iptal=None, hedef_klasor=None,
                        referanslar=()):
        """Görsel üretir ve hedef klasöre kaydeder (otomatik kaydetme kapalıysa geçici klasöre).

        `hedef_klasor` verilirse (proje üretimi) görseller yalnızca oraya yazılır.
        `referanslar`: referans görsel dosyaları; prompt'ta sırayla "image 0", "image 1"…
        diye anılır. Yalnızca referans alan modelde (`referans_siniri`) kullanılabilir.

        Yield: (durum metni, [(dosya yolu, açıklama), ...], [indirilecek dosyalar])
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("Önce ne üretmek istediğini yaz.")

        images = []
        try:
            spec = cf_model_spec(model)
            if spec is None:
                raise ValueError(f"Desteklenmeyen Cloudflare modeli: {model}")
            if not cf_account or not cf_token:
                raise ValueError("Cloudflare için Account ID ve API token gerekir. "
                                 "Anahtar bölümünden bir kez gir ve kaydet.")
            referanslar = [yol for yol in (referanslar or ()) if yol]
            sinir = int(spec.get("referans") or 0)
            if referanslar and not sinir:
                raise ValueError(f"{spec['label']} referans görsel almaz; FLUX.2 klein seç.")
            if len(referanslar) > sinir:
                raise ValueError(f"{spec['label']} en fazla {sinir} referans görsel alır.")
            payload = build_cf_payload(spec, prompt=prompt, negative=negative, seed=seed,
                                       width=width, height=height, steps=steps, guidance=guidance)
            url = cf_run_url(cf_account, spec["id"])
            for durum, saved in self._calistir(url, cf_token, spec, payload, count, iptal,
                                               hedef_klasor, referanslar):
                images = saved
                yield durum, saved, [str(path) for path, _ in saved]
            if images:
                klasor = hedef_klasor or self.depolama.hedef_metni('images')
                yield (f"Tamamlandı · {len(images)} görsel üretildi.\nKlasör: {klasor}",
                       images, [str(path) for path, _ in images])
            else:
                yield "Görsel dönmedi.", [], []
        except Exception as exc:
            message = gorsel_hatasi_temizle(exc, cf_token)
            if images:
                yield (f"{message}\nTamamlanan {len(images)} görsel korundu. Otomatik tekrar yapılmadı.",
                       images, [str(path) for path, _ in images])
            else:
                yield message + "\nOtomatik tekrar yapılmadı.", [], []

    def _calistir(self, url, token, spec, payload, count, iptal, klasor=None, referanslar=()):
        """Cloudflare isteklerini sırayla çalıştır; her turda (durum, kaydedilenler) yield et."""
        saved = []
        # Referanslar bir kez küçültülür; her istekte aynı baytlar gider.
        ekler = {f"input_image_{sira}": (f"ref{sira}.png", referans_hazirla(yol), "image/png")
                 for sira, yol in enumerate(referanslar or ())}
        for index in range(max(1, min(4, int(count)))):
            if iptal is not None and iptal.is_set():
                yield "İstek iptal edildi.", saved
                return
            yield f"Cloudflare · {index + 1}/{count} üretiliyor… ({spec['id']})", saved
            basladi = time.time()
            # FLUX.2 modelleri JSON değil **multipart form** bekler: her alan metin
            # parçası olarak gider (bkz. model tablosundaki `istek`).
            govde = ({"files": {**{ad: (None, str(deger)) for ad, deger in payload.items()}, **ekler}}
                     if spec.get("istek") == "multipart" else {"json": payload})
            # Geçici sunucu hatası (5xx / "Internal server error") aynı istekte birkaç kez
            # beklenerek yeniden denenir; akışın deneme hakkından düşmez. Betta belgeselinde
            # (23.10.2026) FLUX.2 klein 9B isteklerinin ~%30'u bu hatayla döndü, tek bir
            # adımın 3 hakkı bitince bütün proje duruyordu. Kota, yetki ve içerik filtresi
            # hataları eskisi gibi hemen bildirilir.
            for tekrar, bekle in enumerate((4, 8, 16, None)):
                try:
                    response = requests.post(url, headers={"Authorization": f"Bearer {token.strip()}"},
                                             timeout=300, **govde)
                except requests.exceptions.Timeout:
                    raise TimeoutError("Cloudflare 300 saniyede yanıt vermedi.") from None
                except requests.exceptions.ConnectionError:
                    raise RuntimeError("api.cloudflare.com adresine bağlanılamadı (internet?).") from None
                gecici = (response.status_code >= 500
                          or b"internal server error" in (response.content or b"")[:500].lower())
                if not gecici or bekle is None:
                    break
                if iptal is not None and iptal.is_set():
                    yield "İstek iptal edildi.", saved
                    return
                yield (f"Cloudflare geçici sunucu hatası; {bekle} sn sonra aynı istek yeniden "
                       f"deneniyor ({tekrar + 1}/3)."), saved
                time.sleep(bekle)
            if not response.ok:
                raise RuntimeError(cf_status_hint(response.status_code) + cf_error(response))
            for blob, extension in cf_read_images(response):
                path = self._kaydet(blob, extension, "cloudflare", klasor)
                saved.append((path, f"Cloudflare · {spec['label']} · {round(time.time() - basladi, 1)} sn"))
            yield f"Cloudflare · {index + 1}/{count} tamamlandı ({round(time.time() - basladi, 1)} sn)", saved

    def hesaplari_listele(self, token):
        """Token'ın erişebildiği hesapları listeler; Account ID'yi elle aramak gerekmesin."""
        token = (token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not is_plausible_cf_token(token):
            return [], "API token'ı geçersiz görünüyor (çok kısa ya da bozuk)."
        try:
            response = requests.get(f"{CF_API}/accounts",
                                    headers={"Authorization": f"Bearer {token}"}, timeout=60)
        except requests.exceptions.ConnectionError:
            return [], "api.cloudflare.com adresine bağlanılamadı (internet?)."
        except requests.exceptions.Timeout:
            return [], "Cloudflare 60 saniyede yanıt vermedi."
        except requests.exceptions.RequestException:
            return [], "Token biçimi HTTP başlığı olarak gönderilemedi."

        if response.status_code == 403:
            return [], ("Bu token hesap listesini okuma iznine sahip değil (403). Account ID'yi "
                        "panelden elle girebilirsin: sağ sütunda 'Account ID'.")
        if not response.ok:
            return [], cf_status_hint(response.status_code) + cf_error(response)
        try:
            data = response.json()
        except ValueError:
            return [], "Cloudflare yanıtı okunamadı (geçersiz JSON)."

        accounts = []
        for item in data.get("result") or []:
            if isinstance(item, dict) and item.get("id"):
                accounts.append({"id": str(item["id"]), "name": str(item.get("name") or "")})
        # Boş liste hata değil: dar kapsamlı token'larda bu uç nokta boş döner.
        return accounts, ""

    def token_dogrula(self, token, account_id=""):
        """Token'ın kendisini Cloudflare'e sorar.

        Önce `/user/tokens/verify` (kullanıcı token'ı), 401 dönerse ve Account ID varsa
        `/accounts/{id}/tokens/verify` (hesaba ait token) denenir; bkz. `cf_verify_urls`.
        """
        for adres in cf_verify_urls(account_id):
            try:
                response = requests.get(adres, headers={"Authorization": f"Bearer {token.strip()}"},
                                        timeout=45)
            except requests.exceptions.ConnectionError:
                return "error", "api.cloudflare.com adresine bağlanılamadı (internet?)."
            except requests.exceptions.Timeout:
                return "error", "Cloudflare 45 saniyede yanıt vermedi."
            except requests.exceptions.RequestException:
                return "error", "Token biçimi HTTP başlığı olarak gönderilemedi."
            if response.status_code != 401:
                break
        if response.status_code == 401:
            return "invalid", "Cloudflare bu token'ı tanımıyor (401)."
        if not response.ok:
            return "error", cf_status_hint(response.status_code) + cf_error(response)
        try:
            data = response.json()
        except ValueError:
            return "error", "Cloudflare yanıtı okunamadı (geçersiz JSON)."
        result = data.get("result") if isinstance(data, dict) else None
        return str((result or {}).get("status") or "unknown"), ""

    def hesap_token_durumu(self, account_id, token):
        """Token bu hesap için geçerli mi? (401'in asıl sebebi genelde buradadır.)"""
        try:
            response = requests.get(f"{CF_API}/accounts/{account_id.strip()}/tokens/verify",
                                    headers={"Authorization": f"Bearer {token.strip()}"}, timeout=45)
        except requests.exceptions.ConnectionError:
            return "error", "api.cloudflare.com adresine bağlanılamadı (internet?)."
        except requests.exceptions.Timeout:
            return "error", "Cloudflare 45 saniyede yanıt vermedi."
        except requests.exceptions.RequestException:
            return "error", "Token biçimi HTTP başlığı olarak gönderilemedi."
        if response.status_code == 401:
            return "invalid", "Cloudflare bu token'ı bu hesap için tanımıyor (401)."
        if response.status_code == 403:
            return "forbidden", cf_error(response)
        if not response.ok:
            return "error", cf_status_hint(response.status_code) + cf_error(response)
        try:
            data = response.json()
        except ValueError:
            return "error", "Cloudflare yanıtı okunamadı (geçersiz JSON)."
        result = data.get("result") if isinstance(data, dict) else None
        return str((result or {}).get("status") or "active"), ""

    def teshis(self, token, account_id=""):
        """401 gibi hataların sebebini madde madde bulur. Hiçbir şeyi değiştirmez."""
        findings = []

        def ekle(seviye, baslik, ayrinti=""):
            findings.append({"level": seviye, "title": baslik, "detail": ayrinti})

        token = (token or "").strip()
        account_id = (account_id or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            ekle("error", "Token boş", "Cloudflare için bir API token'ı oluşturup buraya yapıştır.")
            return {"verdict": "error", "findings": findings}

        if any(harf.isspace() for harf in token):
            ekle("error", "Token'ın içinde boşluk/satır sonu var",
                 "Kopyalama yarım ya da fazla olmuş olabilir. Baştan sona, boşluksuz kopyala.")
        if len(token) < 20:
            ekle("error", f"Token çok kısa ({len(token)} karakter)",
                 "Gerçek token'lar uzun olur; kopyalarken bir kısmı eksik kalmış.")
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", token):
            ekle("error", "Token'da beklenmeyen karakter var",
                 "Kopyalarken başka bir metin (tırnak, parantez, virgül) karışmış olabilir.")
        if re.fullmatch(r"[0-9a-fA-F]{37}", token):
            ekle("error", "Bu bir 'Global API Key' gibi görünüyor",
                 "Global API Key 'Authorization: Bearer' şemasıyla çalışmaz (X-Auth-Email + "
                 "X-Auth-Key ister) — bu yüzden 401 alıyorsun. My Profile > API Tokens yolundan "
                 "bir API Token oluştur.")
        if not token.startswith(("cfut_", "cfat_")):
            ekle("info", "Token 'cfut_' ya da 'cfat_' ile başlamıyor",
                 "Yeni Cloudflare API token'ları cfut_ (kullanıcı) ya da cfat_ (hesaba ait) ile "
                 "başlar. Eski bir token da çalışabilir.")

        gonderilebilir = len(token) >= 20 and not any(harf.isspace() for harf in token)
        durum, mesaj = ("skipped", "")
        if not gonderilebilir:
            ekle("info", "Cloudflare'e sorulmadı",
                 "Token'ın biçimi bozuk olduğu için uzak doğrulama atlandı. Önce kopyalama "
                 "sorununu düzelt, sonra tekrar teşhis et.")
        else:
            durum, mesaj = self.token_dogrula(token, account_id)

        if durum == "active":
            ekle("ok", "Token geçerli ve aktif", "Cloudflare bu token'ı tanıyor.")
        elif durum == "invalid":
            ekle("error", "Token geçersiz: Cloudflare bu token'ı tanımıyor",
                 "Token yanlış kopyalanmış, silinmiş ya da 'Roll' ile yenilenmiş. Yeni bir token "
                 "oluşturup yeniden yapıştır.")
        elif durum in ("disabled", "expired"):
            ekle("error", f"Token durumu: {durum}",
                 "Token devre dışı bırakılmış ya da süresi dolmuş. Yeni bir token oluştur.")
        elif durum != "skipped":
            ekle("warn", "Token doğrulanamadı", mesaj or "Bilinmeyen hata.")

        accounts = []
        hesap_durumu = None
        if durum == "active":
            if account_id:
                hesap_durumu, hesap_mesaji = self.hesap_token_durumu(account_id, token)
                if hesap_durumu == "active":
                    hesap_durumu = True
                    ekle("ok", "Token bu hesap için geçerli",
                         f"{account_id} numaralı hesapta yetkili görünüyor.")
                elif hesap_durumu in ("invalid", "forbidden"):
                    hesap_durumu = False
                    ekle("error", "Token'ın bu hesapta Workers AI yetkisi yok",
                         (hesap_mesaji + " " if hesap_mesaji else "") + CF_SCOPE_FIX)
                else:
                    ekle("warn", "Hesap yetkisi denetlenemedi", hesap_mesaji)
            else:
                ekle("info", "Hesap yetkisi denetlenmedi",
                     "Account ID girilmediği için bu kontrol atlandı.")

            accounts, hata = self.hesaplari_listele(token)
            if hata:
                if hesap_durumu is False:
                    ekle("info", "Hesap listesi de alınamadı", "Yukarıdaki yetki sorunu bunu açıklar.")
                else:
                    ekle("warn", "Hesap listesi alınamadı", hata)
            elif not accounts:
                ekle("info", "Token hesap listesini göstermiyor",
                     "Dar kapsamlı token'larda normaldir; hesap yetkisi ayrıca onaylandı."
                     if hesap_durumu else
                     "Bu uç nokta, hesap kaynağı atanmamış token'larda boş liste döner; "
                     "sebebi ve çözümü yukarıdaki yetki maddesinde.")
            else:
                ekle("ok", f"Token {len(accounts)} hesaba erişiyor",
                     "; ".join(f"{a['name'] or 'isimsiz'} → {a['id']}" for a in accounts))
                if account_id:
                    eslesen = [a for a in accounts if a["id"].lower() == account_id.lower()]
                    if eslesen:
                        ekle("ok", "Account ID token'la eşleşiyor",
                             f"{account_id} → {eslesen[0]['name'] or 'isimsiz'}")
                    else:
                        ekle("error", "Account ID bu token'a ait değil",
                             "Token'ın eriştiği hesaplar yukarıda listeli; kayıtlı kimlik: "
                             f"{account_id}. Yukarıdaki kimliklerden birini kullan.")

        seviyeler = {finding["level"] for finding in findings}
        verdict = "error" if "error" in seviyeler else "warn" if "warn" in seviyeler else "ok"
        return {"verdict": verdict, "accounts": accounts, "findings": findings}

    def dogrula(self, account_id, token):
        """Kimlik bilgilerini gerçek bir üretimle doğrular (256×256, 4 adım)."""
        spec = cf_model_spec(CF_VERIFY_MODEL)
        if spec is None:
            return False, "Doğrulama modeli tanımlı değil."
        # Küçük ve çok az adımlı istekler boş (tek renk) görsel döndürebiliyor; test
        # görselinin gerçekten anlamlı olması için 512 px ve 8 adım kullanılır.
        payload = {"prompt": "a red apple on a wooden table", "width": 512, "height": 512,
                   "num_steps": 8, "guidance": 7.5}
        url = cf_run_url(account_id, spec["id"])
        basladi = time.time()
        try:
            response = requests.post(url, headers={"Authorization": f"Bearer {token.strip()}"},
                                     json=payload, timeout=180)
        except requests.exceptions.ConnectionError:
            return False, "api.cloudflare.com adresine bağlanılamadı (internet?)."
        except requests.exceptions.Timeout:
            return False, "Cloudflare 180 saniyede yanıt vermedi."
        except requests.exceptions.RequestException:
            return False, "Token biçimi HTTP başlığı olarak gönderilemedi."
        if not response.ok:
            return False, cf_status_hint(response.status_code) + cf_error(response)
        try:
            blobs = cf_read_images(response)
        except RuntimeError as exc:
            return False, str(exc)
        bayt = len(blobs[0][0]) if blobs else 0
        return True, (f"Bağlantı çalışıyor: {spec['label']} ile {bayt / 1024:.0f} KB'lık test görseli "
                      f"üretildi ({round(time.time() - basladi, 1)} saniye).")

    def durum(self, account_id, token):
        """Kayıtlı Cloudflare bilgilerinin durumunu kısa bir metinle bildir."""
        account_id = (account_id or "").strip()
        token = (token or "").strip()
        if not account_id or not token:
            return ("Cloudflare bilgileri eksik. Account ID ve API token'ı girip kaydet; "
                    f"token'ı {CF_TOKENS_URL} adresinde oluşturursun.")
        durum, mesaj = self.token_dogrula(token, account_id)
        if durum == "active":
            return (f"Cloudflare bilgileri kayıtlı (hesap {mask_account(account_id)}) ve token aktif. "
                    "Worker AI kotası hesabından harcanır.")
        if durum == "invalid":
            return "Cloudflare token'ı geçersiz. Yeni bir token oluşturup kaydet."
        return "Cloudflare bağlantısı doğrulanamadı: " + (mesaj or durum)


VARSAYILAN = CloudflareGorsel()
