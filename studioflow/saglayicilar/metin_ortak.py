"""Metin yapay zekâsı servislerinin ortak parçaları: anahtar gizleme, HTTP hatası, model tablosu."""
import requests

AI_SAGLAYICILAR = {
    "cloudflare": {
        # Görsel üretimiyle **aynı** hesap ve aynı ücretsiz nöron bütçesi kullanılır;
        # ayrı kayıt gerekmez. Varsayılan model ölçümle seçildi (29.09.2026, claudetest4:
        # aynı 14 sahne, uygulamanın gerçek prompt kodu, dört model):
        # - nemotron-3-120b: 14/14 sahne; her sahnede iç/dış mekân ve "my" sahipliği,
        #   günün saati hikâye boyunca tutarlı. Proje başına ~7.000 nöron, ~6,5 dakika.
        # - qwen3-30b (elendi): hızlı ama sahipsiz uzuv, fizik hatası (keskiden kıvılcım).
        # - glm-4.7-flash (elendi): akıcı ama sabah sahnesine gün batımı yazdı; ~10 dakika.
        # - gpt-oss-120b (elendi): iki çalıştırmada da ilk grubu yazamadı.
        # Kimi K2.6 ve DeepSeek V4 ücretsiz planda kapalı ("not available on the Workers
        # Free plan"). Akıl yürüten modeller için bkz. `metin_cloudflare.AZAMI_TOKEN`.
        "label": "Cloudflare Workers AI",
        "kisa": "Cloudflare",
        "models": ["@cf/nvidia/nemotron-3-120b-a12b",
                   "@cf/mistralai/mistral-small-3.1-24b-instruct",
                   "@cf/meta/llama-3.3-70b-instruct-fp8-fast"],
        "env": "cf_token",
        "alanlar": ("cf_account_id", "cf_token"),
    },
    "gemini": {
        "label": "Gemini",
        "kisa": "Gemini",
        "models": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
                   "gemini-flash-latest", "gemini-flash-lite-latest"],
        "env": "gemini_key",
        "alanlar": ("gemini_key",),
    },
    "evren": {
        # SSB'nin EVREN geçidi (yalnızca Türkiye, e-Devlet girişli); günde 15 milyon token.
        # Düşünme hiçbir koşulda kapatılmaz. Varsayılan model ölçümle seçildi; bkz.
        # `metin_evren` (glm-5.3 kurallara uyuyor ama grup başına 6,5–9,5 dakika).
        "label": "EVREN (SSB)",
        "kisa": "EVREN",
        "models": ["deepseek-v4.1-flash", "glm-5.3"],
        "env": "evren_key",
        "alanlar": ("evren_key",),
    },
    "openai": {
        # Güncel OpenAI sohbet modelleri; ilk sıradaki varsayılan (ucuz + güçlü mini).
        # GPT-4.1 / GPT-4o ailesi hâlâ destekleniyor, geriye dönük uyumluluk için sonda.
        "label": "ChatGPT (OpenAI)",
        "kisa": "ChatGPT",
        "models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5", "gpt-5.4",
                   "gpt-5.1", "gpt-5-mini", "gpt-4.1-mini", "gpt-4.1"],
        "env": "openai_key",
        "alanlar": ("openai_key",),
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "kisa": "Claude",
        "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet-latest"],
        "env": "anthropic_key",
        "alanlar": ("anthropic_key",),
    },
}


# Yeni proje açıldığında seçili gelen servis.
AI_VARSAYILAN = "cloudflare"

# Hikâye araştırmasında her servisin **tek** modeli: servisin en güçlü güncel modeli.
# Daha zayıf yedek model yoktur; kota biten hesabın yerine aynı servisin sıradaki
# hesabı geçer (`metin_ai.HesapliMetin`). Gemini'de Pro ailesi ücretsiz katmanda
# kapalı olduğu için en yeni Flash; Cloudflare'de en büyük akıl yürüten model.
EN_IYI_MODELLER = {"gemini": "gemini-3.8-flash",
                   "cloudflare": "@cf/nvidia/nemotron-3-120b-a12b",
                   "evren": "deepseek-v4.1-flash",
                   "openai": "gpt-5.5",
                   "anthropic": "claude-opus-5-5"}

# Yedek yapay zekâ sırası: yalnızca bu sıraya göre geçiş yapılır. Seçili servis her
# zaman ilk denenir; anahtarı kayıtlı olmayan servis hiç denenmez.
AI_YEDEK_SIRA = ("cloudflare", "gemini", "evren", "openai", "anthropic")


# Havuz tek bir "anahtar" metni taşır, ama Cloudflare iki alan ister (Account ID +
# token). Alanlar bu görünmez ayraçla tek metne indirilir; ayraç hiçbir anahtarın
# içinde geçemeyeceği için bölme işlemi güvenlidir.
ANAHTAR_AYRAC = chr(31)          # ASCII birim ayracı (US)


def ai_secenekleri():
    """Arayüz radyosu için `(kısa etiket, servis)` çiftleri.

    Liste elle yazıldığında yeni servis eklenince arayüzde görünmüyordu; tek
    kaynak `AI_SAGLAYICILAR` olsun diye buradan üretilir.
    """
    return [(bilgi.get("kisa") or bilgi["label"], ad)
            for ad, bilgi in AI_SAGLAYICILAR.items()]


def ai_anahtari(hizmet, kimlik):
    """Servisin anahtar alanlarını `kimlik` sözlüğünden tek metne indir.

    Alanlardan biri bile boşsa boş metin döner: eksik kimlikle istek atılmaz ve
    havuz o servisi hiç denemez.
    """
    alanlar = AI_SAGLAYICILAR.get(hizmet, {}).get("alanlar") or (f"{hizmet}_key",)
    degerler = [str((kimlik or {}).get(alan) or "").strip() for alan in alanlar]
    return ANAHTAR_AYRAC.join(degerler) if all(degerler) else ""


def anahtar_ayir(anahtar):
    """`ai_anahtari` ile birleştirilmiş metni alanlarına böl."""
    return str(anahtar or "").split(ANAHTAR_AYRAC)


def gizle(mesaj, *anahtarlar):
    mesaj = str(mesaj)
    for anahtar in anahtarlar:
        if anahtar and anahtar.strip():
            mesaj = mesaj.replace(anahtar.strip(), "[gizli]")
    return mesaj


def hata(response, anahtar):
    return RuntimeError(f"HTTP {response.status_code}: {gizle((response.text or '')[:400], anahtar)}")


def kisa(hata, sinir=150):
    """Hatayı tek satırlık kısa bir metne indir (bildirimler için)."""
    satir = str(hata or "").strip().splitlines()
    return (satir[0] if satir else "sebep yok").strip()[:sinir]


def baglanti_hatasi(hata):
    """Bağlantı ve zaman aşımı hatalarını okunur Türkçe metne çevir."""
    if isinstance(hata, requests.exceptions.ConnectionError):
        return RuntimeError("Yapay zekâ sunucusuna bağlanılamadı (internet?).")
    if isinstance(hata, requests.exceptions.Timeout):
        return RuntimeError("Yapay zekâ sunucusu 180 saniyede yanıt vermedi.")
    return hata
