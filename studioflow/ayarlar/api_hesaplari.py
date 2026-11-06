"""Bütün API hesaplarını tek dosyada saklar; hizmet başına birden fazla hesap.

Yer: `C:\\Canlandir\\api-hesaplari.txt` — proje klasörünün dışında, bu bilgisayara özel.
Böylece proje kopyalansa, taşınsa veya paylaşılsa anahtarlar birlikte gitmez.

Biçim (`#` ile başlayan satırlar açıklamadır)::

    gemini.aktif = kişisel
    gemini.kişisel.gemini_key = AIza...
    gemini.iş.gemini_key = AIza...

    cloudflare.aktif = ev
    cloudflare.ev.cf_account_id = 023e105f...
    cloudflare.ev.cf_token = cfut_...

Aynı hizmete istediğin kadar hesap ekleyebilirsin. Her hizmetin bir **aktif** hesabı
vardır; üretim sekmeleri hep o hesabın değerlerini kullanır. Hesap adlarında nokta
kullanılamaz; nokta, boşluklar ve satır sonları otomatik temizlenir.

Eski ayrı dosyalar (`anahtarlar.txt`, `gorsel-anahtarlar.txt`) ilk okumada bu dosyaya
tek seferlik taşınır; hiçbir anahtar kaybolmaz.
"""
import re
from pathlib import Path

from studioflow.cekirdek.ayar_dosyasi import AnahtarDegerDosyasi
from studioflow.cekirdek.yollar import AYAR_KLASORU

VARSAYILAN_HESAP = "varsayılan"

# Hizmet başına alanlar: (alan adı, arayüz etiketi, gizli mi?)
HIZMETLER = {
    "huggingface": {
        "label": "Hugging Face",
        "kullanim": "Fotoğraftan video üretimi ve Chatterbox ses klonlama",
        "link": "https://huggingface.co/settings/tokens",
        "adimlar": "Ücretsiz hesap aç → Settings → Access Tokens → yeni token oluştur. "
                   "**read** yetkisi yeterlidir.",
        "fields": (("hf_token", "Hugging Face tokenı", True),),
    },
    "agnes": {
        "label": "Agnes AI",
        "kullanim": "Araçlar › Fotoğraftan video › **Agnes AI** sayfası (metinden / fotoğraftan video)",
        "link": "https://platform.agnes-ai.com",
        "adimlar": "platform.agnes-ai.com → ücretsiz kayıt ol → **API Keys** → yeni anahtar "
                   "oluştur. Kredi kartı istemez. Ücretsiz anahtar video için dakikada 1 istek "
                   "alır; ücretsiz kullanımda girdiler/çıktılar model eğitiminde kullanılabilir.",
        "fields": (("agnes_key", "Agnes AI API anahtarı", True),),
    },
    "gemini": {
        "label": "Gemini",
        "kullanim": "Araçlar › Seslendirme (en doğal tonlama) ve Araçlar › Prompt sekmesi",
        "link": "https://aistudio.google.com/apikey",
        "adimlar": "Google AI Studio → **Get API key** → yeni anahtar oluştur. "
                    "Ücretsiz günlük kota yeterlidir; kredi kartı istemez.",
        "fields": (("gemini_key", "Gemini API anahtarı", True),),
    },
    "openai": {
        "label": "ChatGPT (OpenAI)",
        "kullanim": "Yalnızca Araçlar › Prompt sekmesinde prompt üretimi",
        "link": "https://platform.openai.com/api-keys",
        "adimlar": "platform.openai.com → **API keys** → Create new secret key. "
                    "Anahtar `sk-` ile başlar ve yalnızca bir kez gösterilir. "
                    "Kullanım ücretlidir; hesapta bakiye/plan gerekir.",
        "fields": (("openai_key", "OpenAI API anahtarı", True),),
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "kullanim": "Yalnızca Araçlar › Prompt sekmesinde prompt üretimi",
        "link": "https://console.anthropic.com/settings/keys",
        "adimlar": "console.anthropic.com → **API Keys** → Create Key. "
                    "Anahtar `sk-ant-` ile başlar. Kullanım ücretlidir; hesapta bakiye gerekir.",
        "fields": (("anthropic_key", "Anthropic API anahtarı", True),),
    },
    "evren": {
        "label": "EVREN (SSB)",
        "kullanim": "Proje ve Araçlar › Prompt sekmesinde **prompt yazımı** (DeepSeek, düşünme açık)",
        "link": "https://evren.ssyz.org.tr/api-keys",
        "adimlar": "evren.ssyz.org.tr → **e-Devlet** ile giriş → **API Anahtarları** → yeni "
                   "anahtar oluştur (`evren_llm_` ile başlar). İlk kullanımdan önce **kullanım "
                   "şartlarını** onayla; onaysız anahtar reddedilir. Kota kişi başınadır (günde "
                   "15 milyon token, 03:00'te yenilenir); yeni anahtar kotayı artırmaz.",
        "fields": (("evren_key", "EVREN API anahtarı", True),),
    },
    "cloudflare": {
        "label": "Cloudflare Workers AI",
        "kullanim": "Görsel üretimi, **prompt yazımı** ve Gemini/Chatterbox altyazı hizalaması",
        "link": "https://dash.cloudflare.com/profile/api-tokens",
        "adimlar": "**Create Token → Workers AI** şablonunu kullan. İzin satırı "
                    "`Account · Workers AI · Edit` olmalı ve *Account Resources* kısmında hesabını "
                    "seçmelisin (en sık yapılan hata budur). Account ID'yi bu sekmedeki "
                    "**Token'dan Account ID'yi bul** düğmesiyle otomatik alabilirsin.",
        "fields": (("cf_account_id", "Cloudflare Account ID", False),
                   ("cf_token", "Cloudflare API token'ı", True)),
    },
    "kaggle": {
        "label": "Kaggle",
        "kullanim": "Araçlar › **Video büyütme (Kaggle)** · ücretsiz T4 GPU'da SeedVR2 / Real-ESRGAN",
        "link": "https://www.kaggle.com/settings/api",
        "adimlar": "kaggle.com → Settings → **API** → **Generate New Token**; `KGAT_` ile "
                   "başlayan token'ı anahtar alanına yapıştır (kullanıcı adı boş kalabilir, "
                   "Kaggle onu token'dan bulur). Eski tip anahtar (*Create Legacy API Key*, "
                   "kaggle.json) da olur; o zaman dosyadaki `username` değerini de yaz. GPU ve "
                   "internet için hesapta **telefon doğrulaması** gerekir. Aktif hesap Kaggle'ın "
                   "okuduğu `~/.kaggle/` dosyasına da yazılır.",
        "fields": (("kaggle_username", "Kaggle kullanıcı adı (yalnızca eski tip anahtarda)", False),
                   ("kaggle_key", "Kaggle API token'ı / anahtarı", True)),
    },
    "freesound": {
        "label": "Freesound (ses efektleri)",
        "kullanim": "Proje › Efekt bölümü › **Ses efektleri** · yalnızca CC0 "
                    "(atıfsız, ticari kullanım serbest) sesler",
        "link": "https://freesound.org/apiv2/apply/",
        "adimlar": "freesound.org → ücretsiz kayıt ol → **freesound.org/apiv2/apply** → formu "
                   "doldur (Callback URL: `http://freesound.org/home/app_permissions/"
                   "permission_granted/`) → listede oluşan **Client secret/Api key** değerini "
                   "kopyala. Ücretsizdir, kredi kartı istemez; dakikada 60, günde 2.000 istek.",
        "fields": (("freesound_key", "Freesound API anahtarı", True),),
    },
    # ── Hikâye araştırması · web araması ve sayfa okuma ──
    "tavily": {
        "label": "Tavily (web araması)",
        "kullanim": "Araçlar › Prompt › **Araştırma** · ana web araması (sayfa metniyle birlikte döner)",
        "link": "https://app.tavily.com/home",
        "adimlar": "app.tavily.com → ücretsiz kayıt ol → **API Keys** bölümündeki `tvly-` ile "
                   "başlayan anahtarı kopyala. Kredi kartı istemez; ayda **1.000 ücretsiz kredi** "
                   "(gelişmiş arama 2 kredi). Birden fazla hesap eklersen kotası biten hesabın "
                   "yerine sıradaki geçer.",
        "fields": (("tavily_key", "Tavily API anahtarı", True),),
    },
    "exa": {
        "label": "Exa (anlamsal web araması)",
        "kullanim": "Araçlar › Prompt › **Araştırma** · Tavily kotası bitince devreye giren ikinci arama",
        "link": "https://dashboard.exa.ai/api-keys",
        "adimlar": "dashboard.exa.ai → ücretsiz kayıt ol → **API Keys** → anahtarı kopyala. "
                   "Kredi kartı istemez; kayıtta 20$ ve her ay 10$ ücretsiz kredi verilir.",
        "fields": (("exa_key", "Exa API anahtarı", True),),
    },
    "jina": {
        "label": "Jina Reader (sayfa okuma)",
        "kullanim": "Araçlar › Prompt › **Araştırma** · yerel okuyucunun açamadığı sayfaları okur. "
                    "**Anahtarsız da çalışır** (dakikada 20 sayfa); anahtar sınırı yükseltir.",
        "link": "https://jina.ai/api-dashboard/key-manager",
        "adimlar": "İsteğe bağlıdır. jina.ai → **API** → ücretsiz anahtar al (`jina_` ile başlar, "
                   "10 milyon ücretsiz token). Anahtar yoksa okuma anahtarsız sınırla sürer.",
        "fields": (("jina_key", "Jina API anahtarı (isteğe bağlı)", True),),
    },
    # ── Video konusu bul · viral Shorts / TikTok verisi ──
    "youtube": {
        "label": "YouTube Data API",
        "kullanim": "Araçlar › Prompt › **Video konusu bul** · YouTube Shorts araması (tarihli ve "
                    "isabetli). **Anahtarsız da çalışır** (yt-dlp); anahtar sonuçları iyileştirir.",
        "link": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "adimlar": "Google Cloud Console → yeni proje → **YouTube Data API v3**'ü etkinleştir → "
                   "**Kimlik bilgileri → API anahtarı oluştur**. Ücretsiz; günde 10.000 birim "
                   "(bir arama 100 birim). Her Google projesi ayrı kota: birden fazla hesap "
                   "eklersen kotası biten anahtarın yerine sıradaki geçer.",
        "fields": (("youtube_key", "YouTube Data API anahtarı", True),),
    },
    "apify": {
        "label": "Apify (TikTok verisi)",
        "kullanim": "Araçlar › Prompt › **Video konusu bul** · TikTok araması "
                    "(clockworks/tiktok-scraper, ~1,70 $ / 1.000 video)",
        "link": "https://console.apify.com/settings/integrations",
        "adimlar": "apify.com → ücretsiz kayıt ol (kredi kartı istemez) → Settings → "
                   "**API & Integrations** → Personal API token'ı kopyala (`apify_api_` ile "
                   "başlar). Ücretsiz plan **her ay 5 $** kredi verir (~2.900 TikTok videosu); "
                   "kredi bitince çalışma durur, fatura çıkmaz.",
        "fields": (("apify_token", "Apify API token'ı", True),),
    },
}

# Kurulum sayfaları: arayüzde hem seçili hizmetin düğmesi hem de tek listede gösterilir.
KURULUM_SAYFALARI = [(bilgi["label"], bilgi["link"], bilgi["adimlar"])
                     for bilgi in HIZMETLER.values()]

BASLIK = """# Canlandır - bütün API hesapları
#
# Bütün servislerin anahtarları tek yerde, bu dosyada tutulur. Aynı servise birden
# fazla hesap ekleyebilirsin; üretim sekmeleri her servisin "aktif" hesabını kullanır.
#
# Biçim:  hizmet.aktif = hesap_adı
#         hizmet.hesap_adı.alan = değer
#
# Örnek:
#   gemini.aktif = kişisel
#   gemini.kişisel.gemini_key = AIza...
#
# Hesap adlarında nokta kullanılmaz. Arayüzden yönetmek için API hesapları sekmesini
# kullan; elle düzenlersen uygulamayı kapatmana gerek yoktur.
#
# UYARI: anahtarlar burada düz metindir. Dosyayı kimseyle paylaşma.
"""


def bos_veri():
    return {hizmet: {"hesaplar": {}, "aktif": ""} for hizmet in HIZMETLER}


def ad_temizle(ad):
    """Hesap adını dosya biçimine uygun hale getir."""
    ad = re.sub(r"[.\r\n=]+", "_", (ad or "").strip())
    ad = re.sub(r"\s+", " ", ad).strip()
    return ad or VARSAYILAN_HESAP


def maskele(deger):
    deger = (deger or "").strip()
    if not deger:
        return "boş"
    return f"{deger[:6]}…{deger[-4:]}" if len(deger) > 14 else "kayıtlı"


def _eski_oku(yol, alanlar):
    """Eski düz `anahtar = değer` dosyasını oku (taşıma için)."""
    degerler = {}
    try:
        for satir in yol.read_text(encoding="utf-8").splitlines():
            satir = satir.strip()
            if not satir or satir.startswith("#") or "=" not in satir:
                continue
            ad, _, deger = satir.partition("=")
            if ad.strip() in alanlar:
                degerler[ad.strip()] = deger.strip()
    except (FileNotFoundError, OSError):
        pass
    return degerler


class ApiHesaplari(AnahtarDegerDosyasi):
    """`api-hesaplari.txt` dosyasının okuyucusu/yazıcısı ve hesap sorguları."""

    def __init__(self, klasor=AYAR_KLASORU):
        self.klasor = Path(klasor)
        super().__init__(self.klasor / "api-hesaplari.txt", BASLIK)
        self.eski_dosyalar = (self.klasor / "anahtarlar.txt",
                              self.klasor / "gorsel-anahtarlar.txt")
        self._tasindi = False

    # ------------------------------------------------------------------ temel

    def _tasima(self):
        """Eski ayrı dosyaları ilk okumada yeni tek dosyaya taşı (bir kez)."""
        if self._tasindi or self.yol.exists():
            self._tasindi = True
            return
        self._tasindi = True
        veri = bos_veri()
        bulundu = False

        anahtarlar = _eski_oku(self.eski_dosyalar[0],
                               ("hf_token", "gemini_key", "openai_key", "anthropic_key"))
        for hizmet, alan in (("huggingface", "hf_token"), ("gemini", "gemini_key"),
                             ("openai", "openai_key"), ("anthropic", "anthropic_key")):
            if anahtarlar.get(alan):
                veri[hizmet]["hesaplar"].setdefault(VARSAYILAN_HESAP, {})[alan] = anahtarlar[alan]
                veri[hizmet]["aktif"] = VARSAYILAN_HESAP
                bulundu = True

        gorsel = _eski_oku(self.eski_dosyalar[1], ("cf_account_id", "cf_token"))
        if gorsel.get("cf_account_id") or gorsel.get("cf_token"):
            veri["cloudflare"]["hesaplar"][VARSAYILAN_HESAP] = {
                "cf_account_id": gorsel.get("cf_account_id", ""),
                "cf_token": gorsel.get("cf_token", "")}
            veri["cloudflare"]["aktif"] = VARSAYILAN_HESAP
            bulundu = True

        if bulundu:
            self.yaz(veri)

    def oku(self):
        """Bütün hesapları oku. Dosya yoksa/bozuksa boş yapı döner."""
        self._tasima()
        veri = bos_veri()
        satirlar = self.satirlari_oku()
        if satirlar is None:
            return veri
        for satir in satirlar:
            cift = self.veri_satiri(satir)
            if cift is None:
                continue
            sol, deger = cift
            parcalar = sol.split(".")
            if len(parcalar) == 2 and parcalar[1] == "aktif" and parcalar[0] in HIZMETLER:
                veri[parcalar[0]]["aktif"] = deger
            elif len(parcalar) == 3 and parcalar[0] in HIZMETLER:
                hizmet, hesap, alan = parcalar
                gecerli = {a for a, _, _ in HIZMETLER[hizmet]["fields"]}
                if alan in gecerli:
                    veri[hizmet]["hesaplar"].setdefault(hesap, {})[alan] = deger
        return veri

    def yaz(self, veri):
        satirlar = [BASLIK]
        for hizmet, bilgi in HIZMETLER.items():
            bolum = veri.get(hizmet) or {"hesaplar": {}, "aktif": ""}
            adlar = sorted(bolum["hesaplar"])
            if not adlar:
                continue
            satirlar.append("")
            satirlar.append(f"# ── {bilgi['label']} ──")
            aktif = bolum.get("aktif") if bolum.get("aktif") in bolum["hesaplar"] else adlar[0]
            satirlar.append(f"{hizmet}.aktif = {aktif}")
            for ad in adlar:
                for alan, _etiket, _gizli in bilgi["fields"]:
                    satirlar.append(f"{hizmet}.{ad}.{alan} = {bolum['hesaplar'][ad].get(alan, '')}")
        self.satirlari_yaz(satirlar)
        return veri

    def sil(self):
        """Bütün hesapları sil (dosyayı kaldırır)."""
        super().sil()
        return bos_veri()

    # --------------------------------------------------------------- sorgu

    def hesap_adlari(self, hizmet):
        return sorted(self.oku()[hizmet]["hesaplar"])

    def aktif_hesap(self, hizmet):
        """Aktif hesap adı. Aktif geçersizse ilk hesaba düşer, hesap yoksa boş döner."""
        bolum = self.oku()[hizmet]
        if bolum["aktif"] in bolum["hesaplar"]:
            return bolum["aktif"]
        adlar = sorted(bolum["hesaplar"])
        return adlar[0] if adlar else ""

    def hesap_degerleri(self, hizmet, ad):
        if not ad:
            return {}
        return dict(self.oku()[hizmet]["hesaplar"].get(ad) or {})

    def aktif_degerler(self, hizmet):
        return self.hesap_degerleri(hizmet, self.aktif_hesap(hizmet))

    def aktif_deger(self, hizmet, alan, varsayilan=""):
        return (self.aktif_degerler(hizmet).get(alan) or varsayilan).strip()

    # -------------------------------------------------------------- yazma

    def hesap_yaz(self, hizmet, ad, **alanlar):
        """Hesabı oluştur/güncelle ve **aktif** yap."""
        if hizmet not in HIZMETLER:
            raise ValueError("Bilinmeyen hizmet.")
        veri = self.oku()
        ad = ad_temizle(ad)
        gecerli = {a for a, _, _ in HIZMETLER[hizmet]["fields"]}
        kayit = veri[hizmet]["hesaplar"].setdefault(ad, {})
        for alan, deger in alanlar.items():
            if alan in gecerli:
                kayit[alan] = (deger or "").strip()
        veri[hizmet]["aktif"] = ad
        self.yaz(veri)
        return ad

    def hesap_sec(self, hizmet, ad):
        """Mevcut bir hesabı aktif yap."""
        veri = self.oku()
        ad = ad_temizle(ad)
        if ad in veri[hizmet]["hesaplar"]:
            veri[hizmet]["aktif"] = ad
            self.yaz(veri)
        return self.aktif_hesap(hizmet)

    def hesap_sil(self, hizmet, ad):
        """Bir hesabı sil; aktifse kalan ilk hesaba geç."""
        veri = self.oku()
        ad = ad_temizle(ad)
        veri[hizmet]["hesaplar"].pop(ad, None)
        if veri[hizmet]["aktif"] == ad:
            kalan = sorted(veri[hizmet]["hesaplar"])
            veri[hizmet]["aktif"] = kalan[0] if kalan else ""
        return self.yaz(veri)

    # ------------------------------------------------------------- özet

    def ozet(self, veri=None, dis_kimlikler=None):
        """Her hizmette kaç hesap kayıtlı olduğunun kısa özeti (anahtarlar listelenmez).

        `dis_kimlikler`: bu dosyada hesabı olmayıp kimliği başka yerde duran hizmetler
        (`{hizmet: açıklama}`, ör. Kaggle'ın `~/.kaggle/` dosyası); "hesap yok" yerine
        o açıklama yazılır.
        """
        veri = veri if veri is not None else self.oku()
        dis_kimlikler = dis_kimlikler or {}
        satirlar = []
        for hizmet, bilgi in HIZMETLER.items():
            bolum = veri.get(hizmet) or {"hesaplar": {}, "aktif": ""}
            sayi = len(bolum["hesaplar"])
            if sayi:
                satirlar.append(f"{bilgi['label']}: {sayi} hesap")
            else:
                satirlar.append(f"{bilgi['label']}: {dis_kimlikler.get(hizmet) or 'hesap yok'}")
        satirlar.append(f"Dosya: {self.yol}")
        return "\n".join(satirlar)


# Uygulamanın paylaşılan hesap deposu.
VARSAYILAN = ApiHesaplari()
