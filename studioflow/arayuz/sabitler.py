"""Arayüz sabitleri: varsayılan ön ayar, altyazı hazır ayarları, panel metinleri."""
import threading

from studioflow.altyazi import gorunum
from studioflow.ayarlar import api_hesaplari
from studioflow.proje import on_ayarlar

STYLE = "Warm, natural YouTube narration. Varied emphasis, relaxed pace, clear diction."

# Varsayılan proje ön ayarı: uygulama **kayıtlı ayar olmadan** açıldığında proje
# alanları bu kurulumla gelir. Ön ayarın kendisi `on_ayarlar.VARSAYILAN_ON_AYAR`dır
# (Shorts / Reels dikey kaliteli · dil İngilizce); aşağıdaki alan varsayılanları aynı
# ön ayarın sözlüğünden okunur, böylece ekranda görünen değerler ile ön ayarın şartı
# birbirinden ayrışmaz (görsel modeli ve adımı, tuval, altyazı önerisi, video adımı).
# Kayıtlı bir ayar dosyası varsa (`Ayarları kaydet`) o değerler kazanır.
PJ_VARSAYILAN_ANAHTAR = on_ayarlar.VARSAYILAN_ON_AYAR

PJ_VARSAYILAN = on_ayarlar.proje_on_ayari(PJ_VARSAYILAN_ANAHTAR) or {}

PJ_VARSAYILAN_GORSEL = PJ_VARSAYILAN.get("gorsel") or {}

PJ_VARSAYILAN_DIL = on_ayarlar.VARSAYILAN_DIL

PJ_VARSAYILAN_NOT = on_ayarlar.proje_on_ayar_notu(PJ_VARSAYILAN_ANAHTAR)

# Hazır altyazı ayarları: "karakter, satır, seviye" üçlüsü. CapCut ve dikey videolarda
# metin kutusu dar olduğu için program kelimeyi kendi içinde kırar; satırları kutuya
# sığdırır. Üçüncü değer **seviyedir**: yazının alt kenardan yüksekliği (tuval
# yüksekliğinin yüzdesi; bkz. gorunum.ALTYAZI_SEVIYE). TikTok / Reels / Shorts
# arayüzünün açıklama satırı videonun **alt bölgesini** kapladığı için varsayılan
# yüksektir ve **bütün hazır ayarlarda aynıdır**: şablon seçince seviye oynamaz, tek
# yerden kaydırıcıyla değiştirilir.
SUB_PRESETLER = [("YouTube / yatay video · 42 karakter, 2 satır", "yatay"),
                 ("Shorts, TikTok ve CapCut · 25 karakter, 1 satır", "dikey"),
                 ("Dar kutu / büyük yazı · 18 karakter, 1 satır", "dar")]

SUB_PRESET_AYAR = {"yatay": (42, 2, gorunum.ALTYAZI_SEVIYE),
                   "dikey": (25, 1, gorunum.ALTYAZI_SEVIYE),
                   "dar": (18, 1, gorunum.ALTYAZI_SEVIYE)}

# Proje sekmesindeki dosya listesi sabit yükseklikte kalır ve kendi içinde kaydırılır:
# proje büyüdükçe panel sayfayı aşağı itmez; dosyaları görmek için panel kaydırılır.
DOSYA_PANEL_YUKSEKLIK = 340

# Negatif prompt alanı yalnızca destekleyen görsel modelinde açılır; desteklemeyen modelde
# kutu kilitlenir ve sebebi altındaki notta yazar.
NEGATIF_DESTEK_YOK_NOT = ("Bu görsel modeli **negatif prompt desteklemiyor**; alan kilitli "
                          "ve negatif prompt üretimde kullanılmaz. Negatif prompt için "
                          "SDXL tabanlı bir Cloudflare modeli seç.")

GORSEL_IPTAL = threading.Event()

# Panellerin ilk durum metinleri: hem kutunun kendisi hem de proje değiştiğinde
# temizlenirken bu metinler kullanılır (tek kaynak). Her katmanın kaydı ve videoya
# eklenmesi editörde aynı bölümdedir (şeritte Dublaj, Müzik, Altyazı, Efekt).
PJ_COK_HAZIR = ("Hazır. Dili ve ses servisini seç, **Dublajı kaydet**'e bas; dublaj "
                "listeye eklenir. Videoya eklemek aşağıdaki **Videoya ekle** panelindedir.")

PJ_MUZIK_HAZIR = ("Hazır. Müzik dosyasını yükle, kırp, seviyeyi seç ve **Müziği kaydet**'e "
                  "bas; müzik listeye eklenir. Videoya eklemek aşağıdaki **Videoya ekle** "
                  "panelindedir.")

PJ_ALTYAZI_HAZIR = ("Hazır. Altyazı dilini seç ve **Altyazıyı kaydet**'e bas; altyazı "
                    "listeye eklenir. Videoya gömmek aşağıdaki **Videoya göm** panelindedir.")

# Üretim sayfasındaki üç ekleme panelinin ilk durumu.
PJ_UR_DUBLAJ_HAZIR = ("Hazır. Listeden bir dublaj seç ve **Seçili dublajı videoya ekle**'ye bas.")

PJ_UR_MUZIK_HAZIR = ("Hazır. Kutuları işaretlediğin sırayla müzikler videoya girer; "
                     "sonra **Videoya ekle**'ye bas.")

PJ_UR_ALTYAZI_HAZIR = ("Hazır. Listeden bir altyazı seç ve **Seçili altyazıyı videoya "
                       "göm**'e bas.")

# ── API hesapları · bütün servisler tek dosyada, hizmet başına çok hesap ──
# Arayüzdeki alan kutularının sırası bu listeyle birebir aynı olmalıdır.
API_ALANLAR = [(ad, etiket, gizli)
               for hizmet in api_hesaplari.HIZMETLER.values()
               for ad, etiket, gizli in hizmet["fields"]]

# **Araçlar › Prompt** sekmesinde gösterilen hızlı anahtar sayfası bağlantıları.
PROMPT_AI_LINKLERI = " · ".join(
    f"[{api_hesaplari.HIZMETLER[h]['label']}]({api_hesaplari.HIZMETLER[h]['link']})"
    for h in ("gemini", "evren", "openai", "anthropic"))

# ── Ses testi · her dilde her sesi dene · test sesleri hiçbir zaman kaydedilmez ──
SES_TESTI_IPTAL = threading.Event()

# ── Araçlar › Prompt › Araştırma · durdurma bayrağı ──
ARASTIRMA_IPTAL = threading.Event()

# ── Araçlar › Prompt › Seslendirme promptu · durdurma bayrağı ──
SESLENDIRME_PROMPTU_IPTAL = threading.Event()

# ── Araçlar › Prompt › Tasarım promptu · durdurma bayrağı ──
TASARIM_PROMPTU_IPTAL = threading.Event()

# ── Araçlar › Prompt › Video konusu bul · durdurma bayrağı (arama) ──
KONU_BUL_IPTAL = threading.Event()

# ── Araçlar › Sabit karakter · durdurma bayrağı ──
KARAKTER_IPTAL = threading.Event()
