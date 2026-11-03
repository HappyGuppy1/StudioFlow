"""Proje ayarlarını doğrulayıp sınırlandırma (`ayarlari_normalize`)."""

from studioflow.altyazi.gorunum import (altyazi_boyut, altyazi_font_adi, altyazi_rengi,
                                       altyazi_seviye)
from studioflow.altyazi.kural import sub_rules
from studioflow.ayarlar.bicimler import (
    CIKTI_BICIMLERI, SES_ADI, VARSAYILAN_BICIM, bicim_gorsel_boyutu)
from studioflow.cekirdek.metin import evet as _evet, metin as _metin, sayi as _sayi
from studioflow.proje import karakterler as _karakterler
from studioflow.proje.depo import gorsel_adim_sinirlari
from studioflow.proje.dosya_yollari import ses_seviyesi
from studioflow.proje.on_ayarlar import (
    PROJE_ON_AYARLARI, VARSAYILAN_DIL, VARSAYILAN_ON_AYAR, proje_on_ayari)
from studioflow.proje.sabitler import (
    ADIM_SANIYE, ADIM_SINIRLARI, GORSEL_DENETIM_ARALIGI, GORSEL_DENETIM_DENEME,
    SAHNE_TAVAN_ARALIGI, VARSAYILAN_GORSEL_STIL,
    VARSAYILAN_NEGATIF,
    VARSAYILAN_STIL)
from studioflow.proje.sahne_stratejileri import strateji_normallestir
from studioflow.saglayicilar import gorsel_cloudflare
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR, AI_VARSAYILAN
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS


def _gorsel_oranini_uydur(ayarlar):
    """Görsel boyutu hedef biçimin oranıyla uyuşmuyorsa biçimin boyutunu yaz.

    Video Space'i klibin ölçüsünü (ve oranını) yüklenen kareden türetir: MAX_DIM 832,
    MIN_DIM 480, kare girdi 640, 16 fps. Oran uyuşmazsa klip tuvali doldurabilmek için
    kenarlardan kırpılır ve karenin önemli kısmı boşa gider. Bu yüzden biçim oranı
    **belirleyicidir**: aynı orandaki kullanıcı seçimi korunur (ör. yatay için
    1024×576 ya da 1344×768), uyuşmayan seçim biçimin boyutuna çevrilir.
    """
    gorsel, video = ayarlar["gorsel"], ayarlar["video"]
    genislik, yukseklik = bicim_gorsel_boyutu(video.get("bicim"))
    try:
        simdiki = float(gorsel["width"]) / float(gorsel["height"])
        oran = abs(simdiki / (genislik / yukseklik) - 1)
    except (TypeError, ValueError, ZeroDivisionError):
        oran = 1.0
    if oran > 0.04:
        gorsel["width"], gorsel["height"] = genislik, yukseklik
    # Son adım: boyut, modelin izin verdiği aralığa ve adımına oturtulur (ör. elle
    # yazılan 1300 px, 64'ün katına yuvarlanır). Boyutu model sabitliyorsa
    # (FLUX 1024×1024) `None` döner ve değere dokunulmaz.
    oturmus = gorsel_cloudflare.size_clamp(gorsel.get("model") or "",
                                       gorsel.get("width"), gorsel.get("height"))
    if oturmus[0]:
        gorsel["width"], gorsel["height"] = oturmus
    return ayarlar


def ayarlari_normalize(ayarlar):
    """Ayarları eksiksiz, güvenli bir sözlüğe çevir (metinden okunanlar dahil)."""
    ham = dict(ayarlar or {})
    ses, gorsel, video, altyazi = (dict(ham.get(anahtar) or {})
                                   for anahtar in ("ses", "gorsel", "video", "altyazi"))
    # Dosyada yazmayan alanlar **varsayılan ön ayardan** doldurulur: "varsayılan" demek
    # "bu ön ayarın şartı" demektir (bkz. `VARSAYILAN_ON_AYAR`). Kayıtlı bir değer varsa
    # o kazanır; yalnızca eksik alanlar ön ayara düşer, böylece arayüz ile ön ayar hiç
    # ayrışmaz.
    on_ayar = proje_on_ayari(VARSAYILAN_ON_AYAR) or {}
    on_gorsel = on_ayar.get("gorsel") or {}
    # Görsel boyutu sınırı **modelin kendisinden** gelir: Cloudflare'de modelin izin
    # verdiği aralık (SDXL 256–2048, Lucid 256–2500/16, FLUX boyut almaz).
    gorsel_provider = gorsel_cloudflare.VARSAYILAN_SAGLAYICI
    gorsel_model = _metin(gorsel.get("model"),
                          on_gorsel.get("model") or gorsel_cloudflare.VARSAYILAN_MODEL)
    # Eski bir dosyada artık kullanılmayan bir servis yazıp geçersiz model kalmışsa (ya da
    # model adı bozuksa) geçerli varsayılan Cloudflare modeline düşülür; aksi hâlde üretim
    # reddedilir.
    if gorsel_cloudflare.cf_model_spec(gorsel_model) is None:
        gorsel_model = on_gorsel.get("model") or gorsel_cloudflare.VARSAYILAN_MODEL
    gorsel_genislik, gorsel_yukseklik = gorsel_cloudflare.size_clamp(
        gorsel_model, gorsel.get("width"), gorsel.get("height"))
    gorsel_genislik = gorsel_genislik or _sayi(gorsel.get("width"), 1024)
    gorsel_yukseklik = gorsel_yukseklik or _sayi(gorsel.get("height"), 1024)
    adim_alt, adim_ust, _adim_varsayilan = gorsel_adim_sinirlari(gorsel_model)
    return _gorsel_oranini_uydur({
        "ses": {
            "provider": ses.get("provider") if ses.get("provider") in SES_ADI else "gemini",
            "dil": _metin(ses.get("dil"), VARSAYILAN_DIL),
            "edge_ses": _metin(ses.get("edge_ses")),
            "hiz": max(-50, min(50, _sayi(ses.get("hiz"), 0))),
            "ton": max(-50, min(50, _sayi(ses.get("ton"), 0))),
            # Seslendirme seviyesi (%): videoya eklerken uygulanır; eski projede satır
            # yoksa %100, yani dosyanın kendi seviyesi.
            "seviye": ses_seviyesi(ses.get("seviye")),
            "gemini_model": _metin(ses.get("gemini_model"), GEMINI_MODELS[0]),
            "gemini_ses": _metin(ses.get("gemini_ses"), "Charon"),
            "stil": _metin(ses.get("stil"), VARSAYILAN_STIL),
            "ref": _metin(ses.get("ref")),
            "exag": max(0.0, min(2.0, float(_sayi(ses.get("exag"), 0.5, float)))),
            "cfg": max(0.0, min(1.0, float(_sayi(ses.get("cfg"), 0.5, float)))),
        },
        "altyazi": {
            "acik": altyazi.get("acik", True) if isinstance(altyazi.get("acik"), bool)
            else _evet(altyazi.get("acik"), True),
            "preset": _metin(altyazi.get("preset"), on_ayar.get("altyazi") or "dikey"),
            # Gömme görünümü: yazı tipi, rengi (#RRGGBB) ve kalınlığı.
            "font": altyazi_font_adi(altyazi.get("font")),
            "renk": altyazi_rengi(altyazi.get("renk")),
            "kalin": _evet(altyazi.get("kalin"), False),
            # Altyazı seviyesi: yazının alttan yüksekliği (tuval yüksekliğinin yüzdesi).
            # Eski projelerde satır yoksa varsayılana düşülür (bkz. ALTYAZI_SEVIYE).
            "seviye": altyazi_seviye(altyazi.get("seviye")),
            # Boyut: yazı yüksekliği (tuval %'si); gölge: yazının arkasındaki koyu gölge.
            "boyut": altyazi_boyut(altyazi.get("boyut")),
            "golge": altyazi.get("golge") if isinstance(altyazi.get("golge"), bool)
            else _evet(altyazi.get("golge"), True),
            # `proje.txt`ten gelen değerler metindir ("25"); `sub_rules` yalnızca sayıyı
            # kabul ettiği için çevrilmezse kayıtlı kural sessizce varsayılana düşerdi.
            "ayar": sub_rules(**{ad: _sayi(altyazi.get(ad), None, float)
                                            for ad in ("line_chars", "max_lines",
                                                       "min_seconds", "max_seconds")})
            if any(altyazi.get(ad) is not None for ad in ("line_chars", "max_lines",
                                                          "min_seconds", "max_seconds"))
            else dict(dict(altyazi.get("ayar") or {}) or sub_rules()),
        },
        "gorsel": {
            "provider": gorsel_provider,
            "model": gorsel_model,
            "width": gorsel_genislik,
            "height": gorsel_yukseklik,
            "steps": max(adim_alt, min(adim_ust,
                                       _sayi(gorsel.get("steps"),
                                             on_gorsel.get("steps", _adim_varsayilan)))),
            "guidance": max(0.0, min(30.0,
                                     float(_sayi(gorsel.get("guidance"),
                                                 on_gorsel.get("guidance", 7.5), float)))),
            "negatif": _metin(gorsel.get("negatif"), VARSAYILAN_NEGATIF),
            # Görsel denetimi (bkz. `GORSEL_DENETIM_DENEME`): eski projelerde satır
            # yoktur, açık kabul edilir — denetim hiçbir zaman üretimi durdurmaz.
            "denetim": gorsel.get("denetim") if isinstance(gorsel.get("denetim"), bool)
            else _evet(gorsel.get("denetim"), True),
            # Yazı denetimi (09.10.2026): karede yazı kabul edilmez; varsayılan açık.
            "yazi_denetimi": gorsel.get("yazi_denetimi")
            if isinstance(gorsel.get("yazi_denetimi"), bool)
            else _evet(gorsel.get("yazi_denetimi"), True),
            "denetim_deneme": max(GORSEL_DENETIM_ARALIGI[0],
                                  min(GORSEL_DENETIM_ARALIGI[1],
                                      _sayi(gorsel.get("denetim_deneme"),
                                            GORSEL_DENETIM_DENEME))),
        },
        "video": {
            # Video adımı: Space 1–10 kabul eder (4–8 önerilir).
            "adim": max(ADIM_SINIRLARI[0], min(ADIM_SINIRLARI[1],
                                               _sayi(video.get("adim"),
                                                     on_ayar.get("video_adim", 4)))),
            # Adım süresi kullanıcının seçtiği **tavandır** (sahnenin alabileceği en uzun
            # süre), sahnenin kendi süresi değil: 5–8 sn arası seçilir. Eski projelerde
            # satır olmadığı için ön ayarın süresine düşer.
            "adim_saniye": round(max(SAHNE_TAVAN_ARALIGI[0],
                                     min(SAHNE_TAVAN_ARALIGI[1],
                                         _sayi(video.get("adim_saniye"),
                                               on_ayar.get("adim_saniye", ADIM_SANIYE), float))), 2),
            "ai": video.get("ai") if video.get("ai") in AI_SAGLAYICILAR else AI_VARSAYILAN,
            "model": _metin(video.get("model")),
            # Boş stil = tablo: model kendi eğilimine bırakılırsa yağlı boya üretiyor.
            # Bu yüzden boş bırakılan alan varsayılana düşer; kullanıcı kendi stilini
            # yazarsa ona hiç dokunulmaz.
            "stil": _metin(video.get("stil"), VARSAYILAN_GORSEL_STIL),
            # Hedef biçim: görsel oranını, altyazı önerisini ve birleştirme tuvalini
            # birlikte belirler (bkz. `CIKTI_BICIMLERI`). Bilinmeyen değer varsayılana düşer.
            "bicim": video.get("bicim") if video.get("bicim") in CIKTI_BICIMLERI
            else on_ayar.get("bicim") or VARSAYILAN_BICIM,
            # Kaydedilen **ön ayar** seçimi: yalnızca arayüzde listenin hangi kurulumu
            # gösterdiğidir (alanların kendisi ayrıca kaydedilir). Eski kayıtlarda ve
            # `proje.txt`te bu satır yoktur; o durumda liste "— elle ayarla —" gösterir,
            # yani kullanıcı olmayan bir kurulumu seçili görmez.
            "on_ayar": video.get("on_ayar") if video.get("on_ayar") in PROJE_ON_AYARLARI
            else "",
            # Eski projelerde satır yoksa mevcut tarih davranışı korunur.
            "sahne_stratejisi": strateji_normallestir(video.get("sahne_stratejisi")),
            # Genel video prompt'u (`proje.txt`te ayrı bir bölümde çok satırlı durur):
            # bütün adım prompt'ları bu çerçeveye uydurulur.
            "genel": _metin(video.get("genel")),
            # ── ilk sahne · opsiyonel elle prompt ──────────────────────────────
            # Short'ta ilk kare videonun kancasıdır; rastgele yazılmasın diye kullanıcı
            # 1. sahnenin **içeriğini** kendisi yazabilir. Görsel stili buraya yazılmaz:
            # 1. sahne de projenin genel stilini (`video.stil`) kullanır. İkisi de boşsa
            # davranış eskisiyle birebir aynıdır: prompt'u yapay zekâ yazar
            # (bkz. `adim_promptlari.ilk_sahne_kaydi`).
            "ilk_prompt": _metin(video.get("ilk_prompt")),
            "ilk_negatif": _metin(video.get("ilk_negatif")),
            # Boşsa videolar `video_huggingface.VIDEO_SPACELER` sırasıyla denenir; doldurulursa
            # yalnızca bu Space zorlanır (ör. yalnızca bir Space kullanmak istersen).
            "space": _metin(video.get("space")),
            # Karakter kadrosu (ad · tarif · referans görsel, en fazla 4): proje.txt'te
            # ayrı KARAKTERLER bölümünde durur. Boşsa akış eskisiyle birebir aynıdır.
            "karakterler": _karakterler.normalize(video.get("karakterler")),
        },
    })
