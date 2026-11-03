"""Hata metinleri: anahtar gizleme, kota/yetki ipuçları ve etiketleme.

İki "temizleme" işlevi bilerek ayrı tutulur: ses servisleri ile görsel servisi farklı
kota kelimeleri ve farklı ipucu metinleri kullanır; ikisi de eskisi gibi çalışır.
"""
import re


class Durduruldu(Exception):
    """Kullanıcı durdurma düğmesine bastı."""


# Hata kodları yalnızca **tek başına** geçen sayı olarak tanınır. 14.10.2026: Cloudflare'in
# filtre reddi sonunda bir istek kimliği taşır (`4bb7c056-…-5d1ed0c91403`); "403" ya da
# "429" düz metin olarak arandığı için kimliğe göre bazen YETKİ, bazen KOTA sayıldı ve
# sağlam hesaplar elendi.
def _kod_var(metin, *kodlar):
    return re.search(r"(?<![0-9a-z])(?:" + "|".join(kodlar) + r")(?![0-9a-z])",
                     metin.lower()) is not None


def icerik_filtresi_mi(mesaj):
    """Servis üretilen kareyi içerik filtresine mi taktı? Hesabın değil isteğin sorunudur."""
    dusuk = str(mesaj).lower()
    return "flagged" in dusuk or "içerik filtresi" in dusuk


def metin_engeli_mi(mesaj):
    """Metin yapay zekâsı **isteği** içerik politikasıyla mı engelledi?

    Hesabın sorunu değildir; aynı istek o servisin bütün hesaplarında engellenir.
    Ölçüm (22.10.2026): kadroda "8-year-old girl" tarifi olan masal isteğini Gemini
    "prohibited_content" ile reddetti; tarifsiz aynı istek geçti.
    """
    dusuk = str(mesaj).lower()
    return any(k in dusuk for k in ("prohibited_content", "input blocked",
                                    "prohibited use policy"))


def gpu_yok_mu(mesaj):
    """Hugging Face ZeroGPU havuzunda boş GPU yok mu? Geçicidir; hesabın ya da adımın değil."""
    return "no gpu was available" in str(mesaj).lower()


def _gizle(message, secrets, desen):
    for secret in secrets:
        if secret and secret.strip():
            message = message.replace(secret.strip(), "[gizli]")
    return re.sub(desen, "[gizli]", message)


def ses_hatasi_temizle(exc, *secrets):
    """Seslendirme servislerinin hatası: anahtarlar gizlenir, kota/yetki ipucu eklenir."""
    message = _gizle(str(exc), secrets, r"(?:hf_[A-Za-z0-9]+|AIza[A-Za-z0-9_-]+)")
    if (any(word in message.lower() for word in ("quota", "exceeded", "resource_exhausted"))
            or _kod_var(message, "429")):
        advice = ""
        if "zerogpu" in message.lower():
            advice = ("Bu Chatterbox'ın ZeroGPU kotasıdır. Üstteki 'Hugging Face hesabı' bölümüne ücretsiz tokenını "
                      "girersen kotan artar. Beklemek istemiyorsan Edge servisi kotasız çalışır. ")
        return "Ücretsiz kota / istek sınırına ulaşıldı. Otomatik tekrar yapılmadı. " + advice + message[:500]
    if (any(word in message.lower() for word in ("api_key_invalid", "sign in", "unauthorized"))
            or _kod_var(message, "401", "403")):
        return "Hesap anahtarını ve servis erişimini kontrol et. " + message[:500]
    return message[:900]


def gorsel_hatasi_temizle(exc, *secrets):
    """Görsel (Cloudflare) hatası: anahtarlar gizlenir, kota/yetki ipucu eklenir."""
    message = _gizle(str(exc), secrets,
                     r"(?:hf_[A-Za-z0-9]+|AIza[A-Za-z0-9_-]+|cfut_[A-Za-z0-9_-]+)")
    low = message.lower()
    # Uçtan uca denemede (02.10.2026) gerçek bir insan fotoğrafı karakter referansı
    # olunca Cloudflare bazı kareleri içerik filtresine takıp reddetti; aynı sahne
    # yeniden denenince geçebiliyor.
    if "flagged" in low:
        return ("Cloudflare içerik filtresi bu kareyi reddetti. Karakter referansı gerçek "
                "bir insan fotoğrafıysa çizim ya da üretilmiş bir referans kullan; sahne "
                "yeniden denenince de geçebilir. Ayrıntı: " + message[:500])
    if (any(word in low for word in ("quota", "exceeded", "rate limit", "neurons"))
            or _kod_var(message, "429")):
        return ("Kota ya da hız sınırına ulaşıldı. Otomatik tekrar yapılmadı; kotanın "
                "yenilenmesini bekle. Ayrıntı: " + message[:500])
    if any(word in low for word in ("unauthorized", "forbidden")) or _kod_var(message, "401", "403"):
        return "Hesap bilgilerini ve servis yetkisini kontrol et. Ayrıntı: " + message[:500]
    return message[:900]


def dakikalik_bekleme(hata):
    """Dakikalık hız sınırı mı? Öyleyse beklenecek saniye, günlük/kalıcı kotada `None`.

    Gemini'nin ücretsiz katmanı hesap başına dakikada birkaç istek alır ve 429 ile
    "Please retry in 6s" ya da "Rate limit exceeded … (limit: 10" der (seslendirme
    modeli dakikada 10 istek). Bu kota **bitmesi** değildir: hesabı elemek, on hesabın
    birkaç dakikada "tükenmiş" görünmesine yol açıyordu. Günlük kotalar (Cloudflare'in
    günlük nöron hakkı, Hugging Face ZeroGPU'nun "Try again in 23:43:22"si) `None` döner.
    """
    dusuk = str(hata).lower()
    if any(k in dusuk for k in ("per day", "perday", "daily", "neuron", "zerogpu")):
        return None
    if re.search(r"try again in \d+:\d+", dusuk):
        return None
    eslesme = re.search(r"retry in ([0-9.]+)\s*s", dusuk)
    if eslesme:
        return min(float(eslesme.group(1)) + 1, 90)
    if "per minute" in dusuk or "rate limit" in dusuk or _kod_var(dusuk, "429"):
        return 30
    return None


def hata_etiketle(mesaj):
    """Hatanın türünü tek kelimeyle etiketle: KOTA, YETKİ, BAĞLANTI ya da HATA."""
    dusuk = str(mesaj).lower()
    if icerik_filtresi_mi(dusuk):
        # Filtre ipucu metni "Kota"/"yetki" sözcüğü taşımaz ama ayrıntısı taşıyabilir;
        # kare reddi hesabın sorunu değildir, hesap elenmemelidir.
        return "HATA"
    if (any(k in dusuk for k in ("kota", "quota", "neurons", "gpu limit",
                                 "yetersiz", "rate limit", "exceeded"))
            or _kod_var(dusuk, "429", "402")):
        return "KOTA"
    # Anahtarda ASCII dışı karakter (ör. Türkçe "ı") istek başlığına yazılamaz: hesabın
    # kendi sorunudur, yedeğe geçilmelidir.
    if "codec can't encode" in dusuk:
        return "YETKİ"
    if (any(k in dusuk for k in ("unauthorized", "forbidden", "invalid api",
                                 "authentication", "giriş", "yetki", "anahtar", "api key"))
            or _kod_var(dusuk, "401", "403")):
        return "YETKİ"
    if any(k in dusuk for k in ("bağlan", "connection", "timed out", "timeout", "internet",
                                "dns", "unreachable", "çözümlenemedi")):
        return "BAĞLANTI"
    return "HATA"
