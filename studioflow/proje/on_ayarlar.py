"""Proje ön ayarları: tuval, altyazı, görsel modeli/boyutu, video adımı tek seçimle."""

from studioflow.ayarlar.bicimler import bicim_gorsel_boyutu
from studioflow.saglayicilar import gorsel_cloudflare

# ------------------------------------------------- proje ön ayarları
# Proje sekmesinde tek seçimle kurulan hazır kurulumlar: görsel modeli + adım, çıktı
# biçimi, video adımı, adım süresi ve altyazı önerisi. Görsel **boyutu** burada
# yazılmaz: biçimden gelir ve modelin izin verdiği aralığa oturtulur, böylece ön ayar
# ile birleştirme tuvalinin oranı hiç ayrışmaz.
#
# Guidance (prompt bağlılığı) modele göre yazılır; modelin kendi varsayılanı ve
# neden o değer olduğu `gorsel_cloudflare.CF_MODELS` tablosundadır. Özet: SDXL base'te
# 6,0, çünkü 5–7 aralığı 32 karelik ölçümde eşdeğer çıktı ve 6,0 en az renk yanması
# veren değer; 5'in altında fotogerçekçilik bozuluyor. Damıtılmış modellerde
# (Lightning, LCM) guidance'ı 1'e çekmek negatif prompt'u tamamen devre dışı bırakır
# (CFG 1 = negatif dal yok), bu yüzden oradaki değerler olduğu gibi bırakıldı.
PROJE_ON_AYARLARI = {
    "": {"ad": "— elle ayarla —", "not": "Bütün alanları kendin seç."},
    # Sahneye sadakat ön ayarları: FLUX.2 klein 4B. Aynı 14 sahnelik prompt setinde
    # SDXL base sahnelerin çoğunu kuramadı (kar, kum tepesi, kolaj, eksik özne), klein
    # 4B 13'ünü doğru kurdu (bkz. `gorsel_cloudflare.CF_MODELS`). Model adım/guidance
    # almaz; alanlar yalnızca uyumluluk için yazılır.
    "shorts-sahne": {
        "ad": "Shorts / Reels dikey · sahneye sadık (FLUX.2 klein 4B)",
        "not": "Prompt'taki sahneyi en iyi kuran ücretsiz model: iki özneli, eylemli "
               "sahneler doğru çıkar. Her kare görsel hakemle denetlenir. Kare başına ~105 "
               "nöron (günlük ücretsiz kotayla ~95 kare).",
        "bicim": "shorts-1080", "altyazi": "dikey", "video_adim": 8, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["flux-2-klein-4b"],
                   "steps": 4, "guidance": 6.0}},
    "yt-sahne": {
        "ad": "YouTube yatay · sahneye sadık (FLUX.2 klein 4B)",
        "not": "1920×1080 tuval · 1344×768 kare · sahneyi en iyi kuran ücretsiz model; her "
               "kare görsel hakemle denetlenir.",
        "bicim": "yt-1080", "altyazi": "yatay", "video_adim": 8, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["flux-2-klein-4b"],
                   "steps": 4, "guidance": 6.0}},
    # Animasyon: boyalı/çizgi anlatım videoları (efsane, belgesel) için en kaliteli
    # kurulum. Kare FLUX.2 klein 9B ile üretilir: 4B tek gözlü dev, ölçek ve alışılmadık
    # anatomide sahneyi kaçırıyordu (Turkic-Mythology-8-Monsters, 04.10.2026). Video
    # 8 adım; sahne tavanı 6 sn, çünkü daha uzun kesitte tek kareden üretilen klipte
    # hareket tükenip görüntü donuklaşıyor (bkz. `pj_adim_saniye` açıklaması). Videolar
    # LTX-2.3 ile üretilir (1280×704 · 24 fps; Wan2.2 832×480): kareye sadık kaldı, Agnes
    # ise kareden koptu (bkz. `saglayicilar.video_ltx`). `video_servisi` yalnızca bu ön
    # ayarla **yeni kurulan** projenin `Video servisi` satırını belirler.
    "yt-animasyon": {
        "ad": "Animasyon · YouTube yatay · en kaliteli (FLUX.2 klein 9B + LTX-2.3)",
        "not": "Boyalı/çizgi anlatım videoları için: en iyi kare modeli (FLUX.2 klein 9B), "
               "videolar LTX-2.3 ile 1280×704 · 24 fps, 6 sn sahne tavanı; her kare görsel "
               "hakemle denetlenir. Kare başına ~1370 nöron: hesap başına günlük ücretsiz "
               "kota ~7 kareye yeter, kalan kareler sıradaki Cloudflare hesabıyla üretilir.",
        "bicim": "yt-1080", "altyazi": "yatay", "video_adim": 8, "adim_saniye": 6.0,
        "video_servisi": "ltx",
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["flux-2-klein-9b"],
                   "steps": 4, "guidance": 6.0}},
    "yt-hizli": {
        "ad": "YouTube yatay · hızlı (SDXL Lightning · 4 adım)",
        "not": "1920×1080 tuval · 1344×768 kare · 4 adım görsel · 4 adım video · 5 sn adım.",
        "bicim": "yt-1080", "altyazi": "yatay", "video_adim": 4, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-lightning"],
                   "steps": 4, "guidance": 7.5}},
    "yt-kalite": {
        "ad": "YouTube yatay · kaliteli (SDXL base · 20 adım)",
        "not": "Aynı tuval, daha detaylı kare; video da 8 adımda üretilir, bu yüzden "
               "daha yavaştır. Prompt bağlılığı (guidance) 6.",
        "bicim": "yt-1080", "altyazi": "yatay", "video_adim": 8, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-base-1.0"],
                   "steps": 20, "guidance": 6.0}},
    "yt-gercekci": {
        "ad": "YouTube yatay · gerçekçi (DreamShaper · 8 adım)",
        "not": "Fotoğraf gerçekçi yüzler; kare 1024×576 üretilir (SD 1.5 tabanlı model "
               "büyük ölçüde bozulur).",
        "bicim": "yt-1080", "altyazi": "yatay", "video_adim": 4, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["dreamshaper-8-lcm"],
                   "steps": 8, "guidance": 7.5}},
    "shorts-hizli": {
        "ad": "Shorts / Reels dikey · hızlı (SDXL Lightning · 4 adım)",
        "not": "1080×1920 tuval · 768×1344 kare · altyazı 25 karakter/1 satır (Shorts "
               "arayüzü altyazıyı kapatmaz).",
        "bicim": "shorts-1080", "altyazi": "dikey", "video_adim": 4, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-lightning"],
                   "steps": 4, "guidance": 7.5}},
    "shorts-kalite": {
        "ad": "Shorts / Reels dikey · kaliteli (SDXL base · 20 adım)",
        "not": "Dikey tuval, detaylı kare ve 8 adımlık video: en yavaş ama en temiz sonuç. "
               "Prompt bağlılığı (guidance) 6: 5–7 arası pratikte eşdeğer, 6 en az renk "
               "yanması veren orta değer.",
        "bicim": "shorts-1080", "altyazi": "dikey", "video_adim": 8, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-base-1.0"],
                   "steps": 20, "guidance": 6.0}},
    "shorts-uzun": {
        "ad": "Shorts dikey · uzun adım (8 sn · daha az klip)",
        "not": "Her klip 8 saniye (en uzun sahne süresi): daha az video isteği, daha uzun "
               "kesintisiz sahne; klip başına GPU süresi artar.",
        "bicim": "shorts-1080", "altyazi": "dikey", "video_adim": 4, "adim_saniye": 8.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-lightning"],
                   "steps": 4, "guidance": 7.5}},
    "kare-hizli": {
        "ad": "Kare 1:1 · hızlı (1080×1080)",
        "not": "Kare yayınlar (Instagram akışı, kapak) için 1080×1080 tuval.",
        "bicim": "kare-1080", "altyazi": "dikey", "video_adim": 4, "adim_saniye": 5.0,
        "gorsel": {"provider": "cloudflare",
                   "model": gorsel_cloudflare.CF_MODEL_ID["stable-diffusion-xl-lightning"],
                   "steps": 4, "guidance": 7.5}},
}


# Varsayılan proje ön ayarı ve anlatım dili **tek kaynaktır**: uygulama kayıtlı ayar
# olmadan açıldığında bütün alanlar bu ön ayarın şartıyla dolar — görsel modeli ve
# adımı, hedef tuval, altyazı önerisi, video adımı ve adım süresi (bkz.
# `ayarlari_normalize`), anlatım dili İngilizce olur. "Varsayılan" ile "ön ayar"
# ayrışmasın diye değerler tek yerden, ön ayarın kendisinden okunur.
VARSAYILAN_ON_AYAR = "shorts-sahne"


VARSAYILAN_DIL = "en"


def proje_on_ayar_secenekleri():
    """Gradio Dropdown için proje ön ayarı listesi: `(etiket, değer)`."""
    return [(bilgi["ad"], anahtar) for anahtar, bilgi in PROJE_ON_AYARLARI.items()]


def proje_on_ayari(ad):
    """Ön ayarı uygulanabilir hâle getir; "elle" ya da bilinmeyen adda `None`.

    Dönen sözlük: `bicim`, `altyazi` (hazır altyazı adı), `video_adim`, `adim_saniye` ve
    `gorsel` (provider, model, width, height, steps, guidance). Görsel boyutu biçimin
    oranından gelir ve modelin kendi aralığına oturtulur.
    """
    on_ayar = PROJE_ON_AYARLARI.get((ad or "").strip())
    if not on_ayar or "bicim" not in on_ayar:
        return None
    gorsel = dict(on_ayar["gorsel"])
    genislik, yukseklik = bicim_gorsel_boyutu(on_ayar["bicim"])
    oturmus = gorsel_cloudflare.size_clamp(gorsel["model"], genislik, yukseklik)
    gorsel["width"], gorsel["height"] = oturmus if oturmus[0] else (genislik, yukseklik)
    return {**on_ayar, "gorsel": gorsel}


def on_ayar_video_servisi(ad):
    """Ön ayarın yeni projeye yazacağı video servisi; belirtmeyen ön ayarda Hugging Face."""
    return (PROJE_ON_AYARLARI.get((ad or "").strip()) or {}).get("video_servisi") or "huggingface"


def proje_on_ayar_notu(ad):
    """Ön ayarın kısa açıklaması (seçilince gösterilir)."""
    return (PROJE_ON_AYARLARI.get((ad or "").strip()) or {}).get("not", "")
