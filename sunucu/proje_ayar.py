"""Proje ayarları: StudioFlow'un proje sayfasındaki **bütün** ayar alanları.

Alanlar, sınırları, seçenekleri ve açıklamaları StudioFlow'un proje sayfasıyla aynıdır
(`studioflow/arayuz/sayfa_proje.py`); editörün formları `FORM` tanımından kurulur. Değerler
`proje.txt`'in AYARLAR yapısındadır (`bolum.alan`):

    Metin        genel prompt, görsel stil, negatif, prompt yapay zekâsı ve modeli, sahne
                 planlama stratejisi (Default · Tarih · Birinci kişi), sahne süresi tavanı,
                 ilk sahne (+ / −)
    Seslendirme  servis (Edge · Gemini · Chatterbox), dil, seviye, Edge sesi/hızı/tonu,
                 Gemini modeli/sesi/üslubu, Chatterbox referans sesi/duygu/bağlılık
    Altyazı      üret, hazır ayar, yazı tipi, renk, kalın, seviye
    Ayarlar      ön ayar, hedef biçim, görsel modeli/boyutu/adımı/guidance, video adımı

Kayıt yeri: başlatılmış projede `proje.txt` (StudioFlow'un kuralı: ayar değişince yalnızca
**kalan adımlar** yeni ayarla üretilir), taslakta `taslaklar/<ad>.json` (bkz. `taslak`).
Biri değişince bağlı alanlar StudioFlow'daki gibi birlikte değişir (bkz. `bagli_degisiklik`):
ön ayar → biçim, altyazı, görsel ve video ayarları; biçim → kare boyutu ve altyazı önerisi;
görsel modeli → adım, guidance, boyut ve negatif desteği; altyazı hazır ayarı → seviye;
yapay zekâ → model listesi; dil → Edge sesi.
"""
import copy
from pathlib import Path

from sunucu import ayar  # noqa: F401  (studioflow paketini bağlar)
from sunucu import katman, taslak, uretim, veri
from studioflow.altyazi import gorunum
from studioflow.arayuz.sabitler import NEGATIF_DESTEK_YOK_NOT, SUB_PRESET_AYAR, SUB_PRESETLER
from studioflow.ayarlar import bicimler, proje_ayarlari
from studioflow.cekirdek import depolama
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.proje import akis, ayar_normalize, depo, on_ayarlar, sabitler
from studioflow.proje.dosya import proje_oku, proje_yaz
from studioflow.proje.sahneleme import KELIME_HIZI
from studioflow.proje.sahne_stratejileri import (STRATEJI_SECENEKLERI, strateji_etiketi,
                                                 strateji_normallestir)
from studioflow.saglayicilar import gorsel_cloudflare, metin_ortak, ses_edge, video_huggingface
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS, VOICES

SES_SERVISLERI = [("Edge · anahtarsız, hızlı", "edge"), ("Gemini · en doğal", "gemini"),
                  ("Chatterbox · ses klonu", "chatterbox")]

# Düzenlenebilir alanlar ve türleri (kayıt biçimi).
ALANLAR = {
    "video.genel": "metin", "video.stil": "metin", "gorsel.negatif": "metin",
    "video.ai": "metin", "video.model": "metin", "video.sahne_stratejisi": "metin",
    "video.adim_saniye": "ondalik", "video.ilk_prompt": "metin", "video.ilk_negatif": "metin",
    "ses.provider": "metin", "ses.dil": "metin", "ses.seviye": "sayi", "ses.edge_ses": "metin",
    "ses.hiz": "sayi", "ses.ton": "sayi", "ses.gemini_model": "metin", "ses.gemini_ses": "metin",
    "ses.stil": "metin", "ses.ref": "metin", "ses.exag": "ondalik", "ses.cfg": "ondalik",
    "altyazi.acik": "evet", "altyazi.preset": "metin", "altyazi.font": "metin",
    "altyazi.renk": "metin", "altyazi.kalin": "evet", "altyazi.seviye": "ondalik",
    "altyazi.boyut": "ondalik", "altyazi.golge": "evet",
    "video.on_ayar": "metin", "video.bicim": "metin", "gorsel.model": "metin",
    "gorsel.width": "sayi", "gorsel.height": "sayi", "gorsel.steps": "sayi",
    "gorsel.guidance": "ondalik", "video.adim": "sayi",
}

STRATEJI_ACIKLAMA = (
    "Sahnelerin nasıl kurulacağını seç. **Default** hiçbir stratejiye özgü kural eklemez "
    "(kamera ve kurgu serbest), **Tarih** olayın neden-sonuç akışını, **Birinci kişi "
    "anlatım** ise kamerayı anlatıcının gözleri olarak planlar. Başlatırken bu seçim "
    "uygulanır. Mevcut projede stratejiyi değiştirirsen eski üretim yedeklenir; sahneler ve "
    "görseller yeniden hazırlanır, üretim kotası kullanılır.")

ILK_SAHNE_ACIKLAMA = (
    "Short'ta **ilk kare** videonun kancasıdır; izleyici ilk saniyede kalır ya da kaydırır. "
    "Boş bırakırsan 1. sahneyi yapay zekâ anlatımın ilk cümlesinden kurar. Doldurursan 1. "
    "sahnenin ne göstereceğine sen karar verirsin: içerik prompt'u yazan yapay zekâya verilir, "
    "kare diğer sahnelerle aynı görsel stil ve kamera diliyle kurulur. İngilizce yaz.")


def _f(anahtar, tur, etiket, **ek):
    return {"anahtar": anahtar, "tur": tur, "etiket": etiket, **ek}


def form():
    """Panellerin alan tanımı (arayüz bunu çizer). `kosul`: alan yalnızca o değerde görünür."""
    sinir = sabitler.SAHNE_TAVAN_ARALIGI
    ses_alt, ses_ust = sabitler.SES_SEVIYE_SINIR
    alt_seviye = gorunum.ALTYAZI_SEVIYE_SINIR
    return {
        "metin": [
            {"grup": "Prompt · genel brief, görsel stil ve negatif prompt", "alanlar": [
                _f("video.genel", "uzun", "Genel video prompt'u (İngilizce)", satir=4,
                   yer="A lone astronaut drifting through a decaying orbital station; cold cyan "
                       "light, slow dolly moves, 35mm anamorphic, quiet awe; no text, no logos",
                   bilgi="Videonun tamamına hâkim çerçeve: konu, karakterler, mekân, atmosfer ve "
                         "kamera dili. Boş bırakırsan anlatımdan türetilir."),
                _f("video.stil", "uzun", "Görsel stil katmanı (İngilizce)", satir=2,
                   bilgi="Her karenin başına eklenir; fotoğraf/tablo farkını belirler. Boş "
                         "bırakırsan varsayılana döner."),
                _f("gorsel.negatif", "uzun", "Negatif prompt (opsiyonel)", satir=2,
                   bilgi="Yapay zekâ her parça için kendi negatif prompt'unu yazar; yazamazsa bu "
                         "değer kullanılır."),
            ]},
            {"grup": "Prompt yapay zekâsı", "aciklama":
                "Anlatımı sahnelere bölen ve sahne prompt'larını yazan servis. Seçim "
                "başlatırken mevcut projeye de uygulanır.", "alanlar": [
                _f("video.ai", "dugmeler", "Servis"),
                _f("video.model", "secim", "Prompt modeli", bagli="video.ai", serbest=True),
            ]},
            {"grup": "Sahne planlama stratejisi", "aciklama": STRATEJI_ACIKLAMA, "alanlar": [
                _f("video.sahne_stratejisi", "dugmeler", "Strateji"),
            ]},
            {"grup": "Sahne süresi", "ozel": "plan", "alanlar": [
                _f("video.adim_saniye", "aralik", "Sahne süresi · üst sınır (saniye)",
                   min=sinir[0], max=sinir[1], adim=0.5,
                   bilgi="Bir sahnenin alabileceği en uzun süre. Sahne süreleri anlatıma göre "
                         "bu tavanın altında değişir (en kısa sahne 1 sn). 6 sn üstü kesitlerde "
                         "tek görselden üretilen klipte hareket tükenip kare donuklaşabilir."),
            ]},
            {"grup": "İlk sahne prompt'u · kanca karesi (opsiyonel)",
             "aciklama": ILK_SAHNE_ACIKLAMA, "kapali": True, "alanlar": [
                _f("video.ilk_prompt", "uzun", "İlk sahne · ne görünsün (+)", satir=3,
                   yer="ör. Extreme close-up of a cracked clay tablet filling the frame, harsh "
                       "noon sunlight, photorealistic historical cinema", sayac=True,
                   bilgi="Yazdığın içerik önceliklidir. En önemli öğeyi başa yaz: model "
                         "yalnızca ilk ~55 kelimeyi okur."),
                _f("video.ilk_negatif", "uzun", "İlk sahne · negatif prompt (−)", satir=2,
                   yer="ör. modern objects, text, watermark",
                   bilgi="Projenin genel negatif prompt'uyla birleşir; tekrarlar atılır."),
            ]},
        ],
        "seslendirme": [
            {"grup": "Ses servisi ve ayarları", "alanlar": [
                _f("ses.provider", "dugmeler", "Ses servisi"),
                _f("ses.dil", "secim", "Dil"),
                _f("ses.edge_ses", "secim", "Edge sesi", kosul={"ses.provider": "edge"},
                   bagli="ses.dil"),
                _f("ses.hiz", "aralik", "Konuşma hızı (%)", min=-50, max=50, adim=5,
                   kosul={"ses.provider": "edge"}),
                _f("ses.ton", "aralik", "Ton (Hz)", min=-50, max=50, adim=5,
                   kosul={"ses.provider": "edge"}),
                _f("ses.gemini_model", "secim", "Gemini modeli", kosul={"ses.provider": "gemini"}),
                _f("ses.gemini_ses", "secim", "Gemini sesi", kosul={"ses.provider": "gemini"}),
                _f("ses.stil", "uzun", "Anlatım üslubu (İngilizce yaz)", satir=2,
                   kosul={"ses.provider": "gemini"}),
                _f("ses.ref", "dosya", "Referans ses · 3–30 saniye temiz kayıt", kabul="audio/*",
                   kosul={"ses.provider": "chatterbox"}),
                _f("ses.exag", "aralik", "Duygu yoğunluğu", min=0, max=2, adim=0.05,
                   kosul={"ses.provider": "chatterbox"}),
                _f("ses.cfg", "aralik", "Referansa bağlılık", min=0, max=1, adim=0.05,
                   kosul={"ses.provider": "chatterbox"}),
                _f("ses.seviye", "aralik", "Ses seviyesi · videodaki seslendirme (%)",
                   min=ses_alt, max=ses_ust, adim=5,
                   bilgi="100 = sesin kendi seviyesi. Kısık geliyorsa 150–200 dene; ses videoya "
                         "eklenirken uygulanır."),
            ]},
        ],
        "altyazi": [
            {"grup": "Görünüm ve üretim · yazı tipi, renk, seviye", "ozel": "altyazi_onizleme",
             "alanlar": [
                _f("altyazi.acik", "evet", "Altyazı üret (SRT + VTT)"),
                _f("altyazi.preset", "secim", "Hazır ayar",
                   bilgi="Çıktı biçimi değişince biçime uygun öneriye geçer."),
                _f("altyazi.font", "secim", "Yazı tipi · videoya gömülürken", serbest=True),
                _f("altyazi.renk", "renk", "Yazı rengi"),
                _f("altyazi.kalin", "evet", "Kalın"),
                _f("altyazi.seviye", "aralik", "Seviye · yazının alttan yüksekliği (%)",
                   min=alt_seviye[0], max=alt_seviye[1], adim=1,
                   bilgi="Yazı arayüz çubuğunun arkasında kalıyorsa yükselt; değer hazır ayarla "
                         "birlikte gelir."),
                _f("altyazi.boyut", "aralik", "Boyut · yazı yüksekliği (tuvalin %'si)",
                   min=2, max=8, adim=0.5, bilgi="Varsayılan 4.5; küçük altyazı için düşür."),
                _f("altyazi.golge", "evet", "Arka gölge"),
            ]},
        ],
        "ayarlar": [
            {"grup": "Çıktı biçimi · platform ve tuval ölçüsü", "alanlar": [
                _f("video.on_ayar", "secim", "Ön ayar · tek seçimle hazır kurulum",
                   bilgi="Görsel modelini ve adımını, video adımını, adım süresini, hedef tuvali "
                         "ve altyazı önerisini birlikte ayarlar."),
                _f("video.bicim", "secim", "Hedef biçim"),
            ]},
            {"grup": "Görsel ayarları", "alanlar": [
                _f("gorsel.model", "secim", "Model"),
                _f("gorsel.width", "aralik", "Genişlik (px)", min=256, max=2048, adim=64),
                _f("gorsel.height", "aralik", "Yükseklik (px)", min=256, max=2048, adim=64),
                _f("gorsel.steps", "aralik", "Adım (steps)", min=1, max=20, adim=1),
                _f("gorsel.guidance", "aralik", "Guidance (CFG)", min=1, max=15, adim=0.5),
            ]},
            {"grup": "Video ayarları", "alanlar": [
                _f("video.adim", "aralik", "Video adımı", min=video_huggingface.ADIM_ALT,
                   max=video_huggingface.ADIM_UST, adim=1, bilgi="4–8 adım önerilir."),
            ]},
        ],
    }


def secenekler():
    """Seçim listeleri `(etiket, değer)` ve bağlı listeler."""
    return {
        "video.ai": metin_ortak.ai_secenekleri(),
        "video.model": {ai: s["models"] for ai, s in metin_ortak.AI_SAGLAYICILAR.items()},
        "video.sahne_stratejisi": list(STRATEJI_SECENEKLERI),
        "ses.provider": SES_SERVISLERI,
        "ses.dil": [(ad, kod) for kod, ad in LANGUAGES.items() if kod != "auto"],
        "ses.gemini_model": [(m, m) for m in GEMINI_MODELS],
        "ses.gemini_ses": [(v, v) for v in VOICES],
        "altyazi.preset": list(SUB_PRESETLER),
        "altyazi.font": [(f, f) for f in gorunum.ALTYAZI_FONTLARI],
        "altyazi.zemin": gorunum.onizleme_zemin_secenekleri(),
        "video.on_ayar": on_ayarlar.proje_on_ayar_secenekleri(),
        "video.bicim": [(b["ad"], k) for k, b in bicimler.CIKTI_BICIMLERI.items()],
        "gorsel.model": [(e, d) for e, d in gorsel_cloudflare.cf_model_choices()],
        # Tek seferlik işlemlerin seçimleri (dublaj, altyazı kaydı, çeviri)
        "dil": [(ad, kod) for kod, ad in LANGUAGES.items() if kod != "auto"],
    }


def edge_sesleri(dil):
    return ses_edge.VARSAYILAN.guvenli_sesler(dil or "en") or []


# ── Okuma / yazma ──────────────────────────────────────────────────────────────
def _kayit(ad):
    """`("proje", proje verisi)` ya da `("taslak", taslak verisi)`."""
    klasor = depo.guvenli_klasor(ad)
    durum = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if durum is not None:
        return "proje", durum
    try:
        return "taslak", taslak.oku(ad)
    except taslak.TaslakYok:
        raise veri.ProjeYok(ad) from None


_edge_sesini_tamamla = uretim.edge_sesini_tamamla


def _degerler(ayarlar):
    a = _edge_sesini_tamamla(ayar_normalize.ayarlari_normalize(copy.deepcopy(ayarlar)))
    return {anahtar: (a.get(anahtar.split(".")[0]) or {}).get(anahtar.split(".")[1])
            for anahtar in ALANLAR}


def calisiyor_mu(ad):
    is_ = uretim.is_durumu()
    return uretim.baska_yerde_calisiyor(ad) or bool(
        is_ and is_["durum"] == "calisiyor" and is_["ad"] == depo.slug(ad))


def model_bilgisi(model):
    """Görsel modelinin sınırları ve negatif desteği (alanlar buna göre kurulur)."""
    adim = gorsel_cloudflare.cf_steps_range(model)
    rehber = gorsel_cloudflare.cf_guidance_range(model)
    boyut = gorsel_cloudflare.cf_size_range(model)
    return {"steps": {"min": adim[0], "max": adim[1], "varsayilan": adim[2]},
            "guidance": {"min": rehber[0], "max": rehber[1], "varsayilan": rehber[2]},
            "boyut": ({"min": boyut[0], "max": boyut[1], "adim": boyut[2]} if boyut else None),
            "negatif": gorsel_cloudflare.supports_negative(model),
            "referans": bool(gorsel_cloudflare.referans_siniri(model)),
            "not": gorsel_cloudflare.cf_note(model)}


def notlar(degerler):
    """Alanların altındaki açıklamalar (StudioFlow'daki notlar)."""
    model = degerler.get("gorsel.model") or ""
    return {
        "gorsel.negatif": "" if gorsel_cloudflare.supports_negative(model) else NEGATIF_DESTEK_YOK_NOT,
        "video.on_ayar": on_ayarlar.proje_on_ayar_notu(degerler.get("video.on_ayar") or ""),
        "gorsel.model": gorsel_cloudflare.cf_note(model),
        "video.sahne_stratejisi": "Seçili sahne planlama stratejisi: "
                                  + strateji_etiketi(degerler.get("video.sahne_stratejisi")),
        "video.ai": "Seçili prompt yapay zekâsı: " + metin_ortak.AI_SAGLAYICILAR.get(
            degerler.get("video.ai") or "", {}).get("label", degerler.get("video.ai") or ""),
    }


def _dosya_adresi(ad, yol):
    """Referans ses gibi yerel dosyanın dinleme adresi."""
    if not yol or not Path(yol).is_file():
        return None
    try:
        goreli = Path(yol).resolve().relative_to((taslak.DOSYALAR / depo.slug(ad)).resolve())
        return f"/dosyalar/{depo.slug(ad)}/{goreli.as_posix()}"
    except ValueError:
        return katman.gecici_adresi(yol)


def ayarlari_oku(ad):
    tur, kayit = _kayit(ad)
    degerler = _degerler(kayit["ayarlar"])
    ses_hazir = tur == "proje" and (kayit.get("ses") or {}).get("durum") == "TAMAM"
    return {"degerler": degerler, "secenekler": secenekler(), "form": form(),
            "edge_sesleri": edge_sesleri(degerler.get("ses.dil")),
            "model": model_bilgisi(degerler.get("gorsel.model") or ""),
            "notlar": notlar(degerler),
            "taslak": tur == "taslak", "ses_hazir": ses_hazir,
            "ref_adres": _dosya_adresi(ad, degerler.get("ses.ref")),
            "kelime_hizi": KELIME_HIZI, "kelime_siniri": sabitler.PROMPT_KELIME_SINIRI,
            "sahne_plani": tur == "taslak" and bool(kayit.get("sahne_on_plan")),
            "metin": kayit.get("metin") or "",
            # Seslendirme bitince anlatım değişmez (StudioFlow da kayıtlı metni kullanır).
            "metin_kilitli": ses_hazir,
            "calisiyor": tur == "proje" and calisiyor_mu(ad)}


def _cevir(tur, deger):
    if tur == "evet":
        return bool(deger)
    if tur in ("sayi", "ondalik"):
        try:
            sayi = float(deger)
        except (TypeError, ValueError):
            return None
        return int(round(sayi)) if tur == "sayi" else sayi
    return str(deger if deger is not None else "")


def _uygula(ayarlar, gelen):
    """Gelen `{"bolum.alan": deger}` değişikliklerini ayar sözlüğüne işle (izinli alanlar)."""
    for anahtar, deger in (gelen or {}).items():
        tur = ALANLAR.get(anahtar)
        if tur is None:
            continue
        deger = _cevir(tur, deger)
        if deger is None:
            continue
        bolum, _, alan = anahtar.partition(".")
        ayarlar.setdefault(bolum, {})[alan] = deger
    if "video.sahne_stratejisi" in (gelen or {}):
        ayarlar["video"]["sahne_stratejisi"] = strateji_normallestir(
            ayarlar["video"].get("sahne_stratejisi"))
    # Altyazı hazır ayarı satır kuralını da getirir (StudioFlow arayüzü gibi).
    preset = (ayarlar.get("altyazi") or {}).get("preset")
    if "altyazi.preset" in (gelen or {}) and preset in SUB_PRESET_AYAR:
        karakter, satir, _seviye = SUB_PRESET_AYAR[preset]
        kural = dict(ayarlar["altyazi"].get("ayar") or {})
        kural.update(line_chars=karakter, max_lines=satir)
        ayarlar["altyazi"]["ayar"] = kural
    return ayarlar


def ayarlari_yaz(ad, gelen):
    """Değişiklikleri kaydet: projede `proje.txt` (çalışırken yazılmaz), taslakta taslak
    dosyası. `metin` anahtarı anlatım metnidir (seslendirme bitmeden değiştirilebilir)."""
    gelen = dict(gelen or {})
    tur, kayit = _kayit(ad)
    if tur == "proje" and calisiyor_mu(ad):
        raise uretim.UretimHatasi("Proje çalışırken ayar değiştirilmez; önce durdur.")
    kayit["ayarlar"] = _edge_sesini_tamamla(ayar_normalize.ayarlari_normalize(
        _uygula(copy.deepcopy(kayit["ayarlar"]), gelen)))
    if "metin" in gelen:
        metin = str(gelen["metin"] or "").strip()
        if tur == "proje" and (kayit.get("ses") or {}).get("durum") == "TAMAM":
            if metin != (kayit.get("metin") or "").strip():
                raise uretim.UretimHatasi("Bu projede anlatım zaten seslendirildi; metin "
                                          "değiştirilemez. Yeni metin için yeni proje başlat.")
        kayit["metin"] = metin
    if tur == "proje":
        proje_yaz(kayit)
    else:
        if gelen.get("sahne_on_plan_sil"):
            kayit["sahne_on_plan"] = None
        taslak.yaz(kayit)
    return ayarlari_oku(ad)


# ── Bağlı alanlar (StudioFlow'un .change zincirleri) ───────────────────────────
def _bicim_boyutu(model, bicim):
    genislik, yukseklik = bicimler.bicim_gorsel_boyutu(bicim)
    secenek = gorsel_cloudflare.cf_size_options(model)
    if not secenek:
        return None, None
    en_yakin = lambda d: min(secenek, key=lambda s: abs(s - d))  # noqa: E731
    return en_yakin(genislik), en_yakin(yukseklik)


def bagli_degisiklik(alan, degerler):
    """Bir alan değişince StudioFlow'un birlikte değiştirdiği alanlar: `{"bolum.alan": değer}`."""
    d = dict(degerler or {})
    yeni = {}
    deger = d.get(alan)
    if alan == "video.on_ayar":
        hazir = on_ayarlar.proje_on_ayari(deger or "")
        if hazir:
            g = hazir["gorsel"]
            yeni.update({"video.bicim": hazir["bicim"], "altyazi.preset": hazir["altyazi"],
                         "altyazi.seviye": SUB_PRESET_AYAR.get(hazir["altyazi"], SUB_PRESET_AYAR["yatay"])[2],
                         "gorsel.model": g["model"], "gorsel.steps": g["steps"],
                         "gorsel.guidance": g["guidance"], "gorsel.width": g["width"],
                         "gorsel.height": g["height"], "video.adim": hazir["video_adim"]})
        # Sahne süresi tavanı ön ayarla değişmez: kullanıcının seçtiği kalır (en fazla 8 sn).
    elif alan == "video.bicim":
        model = d.get("gorsel.model") or ""
        genislik, yukseklik = _bicim_boyutu(model, deger)
        if genislik:
            yeni.update({"gorsel.width": genislik, "gorsel.height": yukseklik})
        elif gorsel_cloudflare.cf_size_default(model) is not None:
            genislik, yukseklik = bicimler.bicim_gorsel_boyutu(deger)
            yeni.update({"gorsel.width": genislik, "gorsel.height": yukseklik})
        preset = bicimler.bicim_bilgisi(deger)["preset"]
        yeni.update({"altyazi.preset": preset,
                     "altyazi.seviye": SUB_PRESET_AYAR.get(preset, SUB_PRESET_AYAR["yatay"])[2]})
    elif alan == "gorsel.model":
        bilgi = model_bilgisi(deger or "")
        yeni.update({"gorsel.steps": bilgi["steps"]["varsayilan"],
                     "gorsel.guidance": bilgi["guidance"]["varsayilan"]})
        boyut = gorsel_cloudflare.cf_size_default(deger or "")
        if boyut is not None:
            genislik, yukseklik = _bicim_boyutu(deger, d.get("video.bicim") or bicimler.VARSAYILAN_BICIM)
            yeni.update({"gorsel.width": genislik or boyut, "gorsel.height": yukseklik or boyut})
    elif alan == "altyazi.preset":
        yeni["altyazi.seviye"] = SUB_PRESET_AYAR.get(deger, SUB_PRESET_AYAR["yatay"])[2]
    elif alan == "video.ai":
        modeller = metin_ortak.AI_SAGLAYICILAR.get(deger, {}).get("models") or []
        yeni["video.model"] = modeller[0] if modeller else ""
    elif alan in ("ses.dil", "ses.provider"):
        sesler = edge_sesleri(d.get("ses.dil"))
        if sesler and d.get("ses.edge_ses") not in sesler:
            yeni["ses.edge_ses"] = sesler[0]
    return yeni


# ── Genel ayar dosyası (StudioFlow › Ayarlar › Ayarları kaydet) ────────────────
def genel_ayar_ozeti():
    return proje_ayarlari.VARSAYILAN.ozet()


def genel_ayarlari_kaydet(ad):
    """Projenin/taslağın ayarlarını StudioFlow'un genel ayar dosyasına yaz (kadro hariç)."""
    _tur, kayit = _kayit(ad)
    ayarlar = copy.deepcopy(kayit["ayarlar"])
    ayarlar["video"]["karakterler"] = []
    try:
        yazilan = proje_ayarlari.VARSAYILAN.kaydet(ayarlar)
    except Exception as hata:
        raise uretim.UretimHatasi(f"Ayarlar kaydedilemedi: {str(hata)[:300]}") from None
    return {"mesaj": "Ayarlar kaydedildi; StudioFlow açılışta ve editörde her yeni projede "
                     "kendiliğinden yüklenecek.", "ozet": proje_ayarlari.VARSAYILAN.ozet(yazilan)}


def genel_ayarlari_yukle(ad):
    """Genel ayar dosyasını projeye/taslağa uygula (kadroya dokunulmaz)."""
    ham = proje_ayarlari.VARSAYILAN.oku()
    if not ham:
        raise uretim.UretimHatasi("Kayıtlı genel ayar yok; önce **Ayarları kaydet**'e bas.")
    yuklenen = _degerler(ayar_normalize.ayarlari_normalize(ham))
    return ayarlari_yaz(ad, yuklenen)


def genel_ayarlari_sil():
    proje_ayarlari.VARSAYILAN.sil()
    return {"mesaj": "Kayıtlı genel ayarlar silindi; projedeki değerler değişmedi.",
            "ozet": proje_ayarlari.VARSAYILAN.ozet()}


def otomatik_kaydet(acik=None):
    """Üretilen dosyaları `outputs` klasörüne otomatik kaydet (bu süreçteki tercih)."""
    if acik is not None:
        depolama.VARSAYILAN.otomatik(bool(acik))
    return {"acik": depolama.VARSAYILAN.otomatik(),
            "mesaj": depolama.VARSAYILAN.durum_metni().replace("**", "").replace("`", "")}


# ── Yeni proje ─────────────────────────────────────────────────────────────────
def yeni_taslak(ad):
    try:
        kayit = taslak.olustur(ad)
    except ValueError as hata:
        raise uretim.UretimHatasi(str(hata)) from None
    return {"ad": kayit["ad"]}


def baslat(ad):
    """Taslağı başlat: StudioFlow'un **Projeye başlat**'ı (klasör kurulur, akış başlar)."""
    try:
        kayit = taslak.oku(ad)
    except taslak.TaslakYok:
        raise veri.ProjeYok(ad) from None
    metin = (kayit.get("metin") or "").strip()
    if not metin:
        raise uretim.UretimHatasi("Önce anlatım metnini yaz (Metin bölümü).")
    ad = kayit["ad"]
    if ad in depo.liste():
        raise uretim.UretimHatasi(f"'{ad}' adında bir proje zaten var.")
    ayarlar = _edge_sesini_tamamla(ayar_normalize.ayarlari_normalize(copy.deepcopy(kayit["ayarlar"])))
    ayarlar["video"]["karakterler"] = list(kayit["ayarlar"]["video"].get("karakterler") or [])
    plan = kayit.get("sahne_on_plan")
    return uretim.baslat_ozel(ad, "yeni", "Projeye başlat · seslendirme ve sahneler",
                              lambda: akis.proje_calistir(ad, metin, ayarlar, plan))

