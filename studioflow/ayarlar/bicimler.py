"""Çıktı biçimleri (platform tuvalleri) ve proje durum sabitleri.

Video Space'i **en/boy almaz**; klip ölçüsünü yüklediğimiz karenin oranından türetir
ve 480–832 aralığına indirir (space'in kendi `resize_image` işlevi: MAX_DIM 832,
MIN_DIM 480, kare girdi 640, FIXED_FPS 16). Bu yüzden platform ölçüsü üç yerde
birlikte ayarlanmalıdır: **görsel üretim boyutu** (karenin oranı), **altyazı önerisi**
(satır genişliği) ve **birleştirme tuvali** (proje.mp4 ölçüsü).

Tek seçim (`video.bicim`) üçünü birlikte yönetir ve `proje.txt`'e yazılır: kaldığı
yerden devam eden proje biçim değiştirmez. Biçim değiştirilirse `proje.mp4` bir
sonraki çalıştırmada yeni tuvalde yeniden birleştirilir.
"""

CIKTI_BICIMLERI = {
    "yt-1080": {"ad": "YouTube · yatay 16:9 · 1920×1080",
                "genislik": 1920, "yukseklik": 1080,
                "gorsel": (1344, 768), "preset": "yatay", "dikey": False},
    "shorts-1080": {"ad": "Shorts / Reels / TikTok · dikey 9:16 · 1080×1920",
                    "genislik": 1080, "yukseklik": 1920,
                    "gorsel": (768, 1344), "preset": "dikey", "dikey": True},
    "kare-1080": {"ad": "Kare 1:1 · 1080×1080",
                  "genislik": 1080, "yukseklik": 1080,
                  "gorsel": (1024, 1024), "preset": "dikey", "dikey": False},
}
# Varsayılan çıktı biçimi **dikeydir**: uygulama kayıtlı ayar olmadan açıldığında
# Shorts / Reels kurulumu gelir. Ön ayarın kendisi `VARSAYILAN_ON_AYAR`dır; bu değer
# onunla aynı olmalıdır (biçim, ön ayarın `bicim` alanından da okunur).
VARSAYILAN_BICIM = "shorts-1080"
# Bütün klipler bu kare hızına eşitlenir: Space 16 fps üretir, platformlar ve kesme
# programları 30 fps bekler.
CIKTI_FPS = 30
TUVAL_KLASORU = "tuval"      # videolar/ altında, tuval ölçüsüne çevrilmiş klipler

DURUMLAR = ("BEKLİYOR", "YARIM", "TAMAM", "HATA", "ATLANDI")
DURUM_ACIKLAMA = {
    "BEKLİYOR": "henüz üretilmedi",
    "YARIM": "görsel var, video yok → adım baştan üretilir",
    "TAMAM": "görsel ve video hazır; dosyaları alanlarında yazar",
    "HATA": "hata satırında sebebi yazar; adım baştan üretilir",
    "ATLANDI": "atlandı",
}
DURUM_ADI = {"hazir": "hazır", "calisiyor": "çalışıyor", "bekliyor": "bekliyor (devam edilecek)",
             # Seslendirme hazır; sahne planı/prompt'ları yazacak yapay zekâ seçimi bekleniyor.
             "prompt_onay": "prompt üretimi bekleniyor",
             # Görseller hazır, videolar kullanıcının onayını bekliyor.
             "gorsel_onay": "görsel onayı bekleniyor",
             "tamam": "tamamlandı", "durduruldu": "durduruldu", "hata": "hata"}

# Windows'ta dosya adı olamayacak adlar.
YASAK_ADLAR = {"CON", "PRN", "AUX", "NUL",
               *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

SES_ADI = {"edge": "Edge (anahtarsız)", "gemini": "Gemini", "chatterbox": "Chatterbox (ses klonu)"}
GORSEL_ADI = {"cloudflare": "Cloudflare Workers AI"}
ETIKET_IPUCU = {
    "KOTA": "Kota doldu ya da hız sınırına gelindi. Prompt üretiminde anahtarı kayıtlı "
            "yedek servise otomatik geçilir; yine olmadıysa üç otomatik denemede de "
            "geçmemiştir. Kota yenilendikten sonra **Deneme hakkını yenile** ve "
            "**Kaldığı yerden devam et**'e bas.",
    "YETKİ": "Anahtar ya da yetki reddedildi. Prompt üretiminde yedek servise otomatik "
             "geçilir; geçmediyse **API hesapları** sekmesinden anahtarı kontrol edip "
             "**Deneme hakkını yenile** ve **Kaldığı yerden devam et**'e bas.",
    "BAĞLANTI": "Sunucuya bağlanılamadı (internet?). Üç otomatik denemede de geçmedi; "
                "bağlantı düzelince **Deneme hakkını yenile** ve "
                "**Kaldığı yerden devam et**'e bas.",
    "HATA": "Üç otomatik denemede de geçmedi. Sorunu giderdikten sonra **Deneme hakkını "
            "yenile** ve **Kaldığı yerden devam et**'e bas.",
}


def bicim_bilgisi(bicim):
    """Biçim kütüğünü döndür; bilinmeyen/boş değerde varsayılana düşer."""
    return CIKTI_BICIMLERI.get((bicim or "").strip(), CIKTI_BICIMLERI[VARSAYILAN_BICIM])


def bicim_etiketi(bicim):
    """Arayüzde ve hata metinlerinde görünen biçim adı."""
    return bicim_bilgisi(bicim)["ad"]


def bicim_gorsel_boyutu(bicim):
    """Biçimin görsel üretim boyutu: `(genişlik, yükseklik)`.

    Karenin oranı klibin ölçüsünü belirler: 16:9 kare → 832×480, 9:16 kare → 480×832,
    kare → 640×640 klip. Yani görsel, videonun oranını gerçekten belirler.
    """
    return bicim_bilgisi(bicim)["gorsel"]


def bicim_kunye(bicim):
    """VİDEO bölümüne yazılan biçim imzası.

    `proje.txt`'te bu satır değişmişse `proje.mp4` yeni tuvalde yeniden birleştirilir;
    böylece biçim değişikliği yok sayılmaz.
    """
    anahtar = (bicim or "").strip()
    bilgi = bicim_bilgisi(anahtar)
    return (f"{anahtar if anahtar in CIKTI_BICIMLERI else VARSAYILAN_BICIM} · "
            f"{bilgi['genislik']}x{bilgi['yukseklik']} · {CIKTI_FPS} fps")
