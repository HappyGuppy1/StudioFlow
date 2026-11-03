"""Yalnızca ses çıktısı: konuşma (seslendirme ya da dublaj) + müzik + efekt → MP3.

Önizlemenin üstündeki **Video | Ses** anahtarı **Ses**'teyken düğmeler video
modundakiyle aynı işi yapar, tek fark video üretilmez: seslendirme/dublaj ya da müzik
eklendiği anda ses dosyası o katmanlarla yeniden kurulur.

- **Seslendirmeyi ekle** / **Seçili dublajı ekle** konuşmayı seçer (tek konuşma olur),
- **Müziği ekle** / **Müziği kaldır** müzik katmanını değiştirir,
- **Sesi indir** güncel dosyayı indirir,
- **Sesi sıfırla** katmanları boşaltır (önceki dillerin dosyaları kalır).

Ses modu **boş** başlar: videodaki dublaj ya da müzik kendiliğinden gelmez. Amaç
YouTube'un çok dilli ses izleri: dosya video süresine kesilir ve YouTube metinlerinin
yanına yazılır, `youtube/<dil>/ses.mp3` (dublajın adı dil kodundan farklıysa
`ses-<ad>.mp3`). Katman seçimi `youtube/ses-modu.json`da durur.
"""
import json
import os

from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.dosya_yollari import (
    anlatim_suzgeci, dil_kodu, muzik_klasoru, ses_dosyasi, ses_seviyesi)
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.ilerleme import arayuz_paketi, bos_paket
from studioflow.proje.katmanlar import muzik
from studioflow.proje.katmanlar.diller import dil_listesi_metni, dublaj_bos, dublaj_paketi
from studioflow.proje.katmanlar.dublaj import dublaj_bul, dublaj_yolu
from studioflow.proje.katmanlar.efektler import ekli_efekt
from studioflow.proje.sabitler import MUZIK_VARSAYILAN_DUCKING

YOUTUBE_KLASORU = "youtube"
DURUM_ADI = "ses-modu.json"


def _durum_yolu(klasor):
    return klasor / YOUTUBE_KLASORU / DURUM_ADI


def _bos_durum():
    return {"konusma": None, "muzikler": [], "tekrarla": False,
            "ducking": MUZIK_VARSAYILAN_DUCKING}


def _durum(klasor):
    """Ses modunun katmanları; dosya yoksa boş.

    `konusma`: `None` = konuşma yok, `""` = projenin kendi seslendirmesi, diğer
    değerler dublaj kaydının adı.
    """
    try:
        ham = json.loads(_durum_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = None
    if not isinstance(ham, dict):
        return _bos_durum()
    konusma = ham.get("konusma")
    return {"konusma": None if konusma is None else str(konusma),
            "muzikler": [str(x) for x in (ham.get("muzikler") or [])],
            "tekrarla": bool(ham.get("tekrarla")),
            "ducking": bool(ham.get("ducking", MUZIK_VARSAYILAN_DUCKING))}


def _durum_yaz(klasor, durum):
    yol = _durum_yolu(klasor)
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".gecici")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, yol)


def _ana_dil(veri):
    return dil_kodu(((veri.get("ayarlar") or {}).get("ses") or {}).get("dil")) or "en"


def _konusma(klasor, veri, ad):
    """`(ses dosyası ya da None, dil kodu, kayıt adı)`.

    Konuşma seçilmediyse dosya `None`, dil projenin ana dilidir (yalnızca müzikli
    dosya da o klasöre yazılır).
    """
    if ad:
        kayit = dublaj_bul(klasor, ad)
        yol = dublaj_yolu(klasor, kayit) if kayit else None
        if yol is not None:
            return yol, kayit["dil"], kayit["ad"]
        return None, _ana_dil(veri), ""
    if ad is None:
        return None, _ana_dil(veri), ""
    return ses_dosyasi(klasor, veri), _ana_dil(veri), ""


def _hedef_dosya(klasor, dil, ad):
    isim = "ses.mp3" if not ad or ad == dil else f"ses-{ad}.mp3"
    return klasor / YOUTUBE_KLASORU / dil / isim


def _konusma_adi(veri, durum):
    if durum["konusma"] is None:
        return ""
    if durum["konusma"]:
        return f"'{durum['konusma']}' dublajı"
    return LANGUAGES.get(_ana_dil(veri), _ana_dil(veri)) + " seslendirmesi"


def _katman_ozeti(veri, durum):
    parcalar = [ad for ad in [_konusma_adi(veri, durum)] if ad]
    if durum["muzikler"]:
        parcalar.append("müzik (" + ", ".join(durum["muzikler"]) + ")")
    return " + ".join(parcalar) or "boş"


def ses_ciktisi_kur(klasor, veri, durum):
    """Katmanları tek dosyada karıştır. Dönüş: `(dosya ya da None, mesaj)`."""
    if not FFMPEG.ffmpeg():
        return None, "ffmpeg bulunamadı; ses dosyası kurulamadı."
    ses, dil, ad = _konusma(klasor, veri, durum["konusma"])
    if durum["konusma"] is not None and ses is None:
        return None, ("Seçili konuşmanın ses dosyası bulunamadı. Seslendirmeyi ya da bir "
                      "dublajı yeniden ekle.")
    if ses is None and not durum["muzikler"]:
        return None, ("Ses dosyası için katman yok. Önce seslendirmeyi ya da bir dublajı, "
                      "istersen müziği ekle.")
    sure = muzik.video_suresi(klasor, veri)
    # Müzik yatağı seçimi ve tekrarı `veri`den okur; proje kaydı değişmesin diye
    # kopya üzerinde çalışılır.
    kopya = dict(veri, muzikler=durum["muzikler"], muzik_tekrarla=durum["tekrarla"])
    bed, hata = muzik.muzik_yatagi(klasor, kopya, sure)
    if hata:
        return None, hata
    if durum["muzikler"] and bed is None:
        # 21.10.2026: müzik kaydı silinince dosya müziksiz ama "güncellendi" diye yazılıyordu.
        return None, ("Seçili müzik bulunamadı (" + ", ".join(durum["muzikler"]) + "): silinmiş ya "
                      "da yeniden adlandırılmış olabilir. Müzik bölümünden müziği yeniden işaretle.")
    efekt, efekt_seviye = ekli_efekt(klasor)
    suzgec = anlatim_suzgeci(veri) if ses is not None else ""
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    girdiler = [yol for yol in (ses, bed, efekt) if yol is not None]
    for yol in girdiler:
        komut += ["-i", str(yol)]
    ses_i = 0 if ses is not None else None
    bed_i = girdiler.index(bed) if bed is not None else None
    if efekt is not None:
        komut += ["-filter_complex",
                  muzik.efektli_karisim_zinciri(
                      ses_i, bed_i, girdiler.index(efekt), efekt_seviye, durum["ducking"],
                      suzgec, ses is not None and muzik.mono_mu(ses)),
                  "-map", "[aout]"]
    elif ses is not None and bed is not None:
        komut += ["-filter_complex",
                  muzik.karisim_zinciri(0, 1, durum["ducking"], suzgec), "-map", "[aout]"]
    else:
        komut += ["-map", "0:a:0"] + (["-af", suzgec] if suzgec else [])
    if sure > 0:
        # Ses izi videoyla aynı uzunlukta olmalı: uzun müzik video sonunda kesilir.
        komut += ["-t", f"{sure:.3f}"]
    hedef = _hedef_dosya(klasor, dil, ad)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.stem + ".gecici.mp3")
    gecici.unlink(missing_ok=True)
    komut += ["-vn", "-c:a", "libmp3lame", "-b:a", "256k", str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut, cwd=klasor)
    (muzik_klasoru(klasor) / "karisim.gecici.m4a").unlink(missing_ok=True)
    if not ok:
        gecici.unlink(missing_ok=True)
        return None, "Ses dosyası kurulamadı: " + _ilk_satir(mesaj, 200)
    try:
        os.replace(gecici, hedef)
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return None, "Ses dosyası yerine yazılamadı: " + _ilk_satir(exc, 200)
    ozet = _katman_ozeti(veri, durum) + (" + ses efektleri" if efekt is not None else "")
    baslik = (f"Ses dosyası güncellendi: {hedef.relative_to(klasor).as_posix()} = {ozet}"
              + (f" · konuşma seviyesi %{ses_seviyesi(veri['ayarlar']['ses'].get('seviye')):g}"
                 if ses is not None else "") + ". Video değişmedi.")
    veri["son_not"] = baslik
    not_ekle(veri, baslik)
    proje_yaz(veri)
    return hedef, baslik


def _seviye_yaz(veri, seviye):
    if seviye is None:
        return
    ses_ayar = veri["ayarlar"].setdefault("ses", {})
    if ses_seviyesi(ses_ayar.get("seviye")) != ses_seviyesi(seviye):
        ses_ayar["seviye"] = ses_seviyesi(seviye)
        not_ekle(veri, f"Konuşma seviyesi panelden güncellendi: %{ses_ayar['seviye']:g}.")
        proje_yaz(veri)


def seslendirme_sesi(ad, seviye=None):
    """Ses modunda **Sesi ekle**: konuşma katmanı = projenin kendi seslendirmesi.

    Dönüş: `(arayuz_paketi, ses dosyası)`.
    """
    veri, klasor, hata = proje_hedefi(ad, "ses katmanı ekle")
    if hata:
        return bos_paket(hata), None
    if ses_dosyasi(klasor, veri) is None:
        return arayuz_paketi(veri, "Seslendirme dosyası yok. Önce projeyi çalıştırıp "
                                   "sesi üret."), None
    _seviye_yaz(veri, seviye)
    durum = _durum(klasor)
    durum["konusma"] = ""
    _durum_yaz(klasor, durum)
    dosya, mesaj = ses_ciktisi_kur(klasor, veri, durum)
    return arayuz_paketi(veri, mesaj), _yol(dosya)


def dublaj_sesi(ad, isim, seviye=None):
    """Ses modunda **Seçili dublajı ekle**: konuşma katmanı = o dublaj.

    Dönüş: `(dublaj paneli paketi, ses önizlemesi)`.
    """
    veri, klasor, hata = proje_hedefi(ad, "ses katmanı ekle")
    if hata:
        return dublaj_bos(hata), None
    kayit = dublaj_bul(klasor, isim)
    if kayit is None or dublaj_yolu(klasor, kayit) is None:
        return dublaj_paketi(veri, klasor, f"'{isim or '—'}' adlı kayıtlı dublaj yok. "
                                            "Listeden bir dublaj seç."), None
    _seviye_yaz(veri, seviye)
    durum = _durum(klasor)
    durum["konusma"] = kayit["ad"]
    _durum_yaz(klasor, durum)
    dosya, mesaj = ses_ciktisi_kur(klasor, veri, durum)
    return dublaj_paketi(veri, klasor, mesaj), _yol(dosya)


def muzik_sesi(ad, secilenler, tekrarla, ducking=MUZIK_VARSAYILAN_DUCKING):
    """Ses modunda **Müzik ekle**: müzik katmanı = işaretli müzikler (işaret sırasıyla)."""
    veri, klasor, hata = proje_hedefi(ad, "ses katmanı ekle")
    if hata:
        return muzik.muzik_bos(hata), None
    kayitli = {kayit["ad"] for kayit in muzik.muzik_kayitlari(klasor)}
    secilen = [x for x in dict.fromkeys(muzik.muzik_adi(x) for x in (secilenler or []))
               if x in kayitli]
    if not secilen:
        return muzik.muzik_paketi(veri, "Ses katmanına eklemek için listede en az bir "
                                         "müziğin kutusunu işaretle."), None
    durum = _durum(klasor)
    durum.update(muzikler=secilen, tekrarla=bool(tekrarla), ducking=bool(ducking))
    _durum_yaz(klasor, durum)
    if durum["konusma"] is None:
        return muzik.muzik_paketi(veri, "Müzik ses katmanına eklendi: " + ", ".join(secilen)
                                  + ". Şimdi seslendirmeyi ya da bir dublajı ekle; ses "
                                    "dosyası o zaman kurulur."), None
    dosya, mesaj = ses_ciktisi_kur(klasor, veri, durum)
    return muzik.muzik_paketi(veri, mesaj), _yol(dosya)


def muzik_sesi_kaldir(ad):
    """Ses modunda **Müziği kaldır**: müzik katmanı boşalır, konuşma kalır."""
    veri, klasor, hata = proje_hedefi(ad, "ses katmanı kaldır")
    if hata:
        return muzik.muzik_bos(hata), None
    durum = _durum(klasor)
    durum["muzikler"] = []
    _durum_yaz(klasor, durum)
    if durum["konusma"] is None:
        return muzik.muzik_paketi(veri, "Müzik ses katmanından kaldırıldı."), None
    dosya, mesaj = ses_ciktisi_kur(klasor, veri, durum)
    return muzik.muzik_paketi(veri, mesaj), _yol(dosya)


def _yol(dosya):
    return str(dosya) if dosya else None


def sesi_sifirla(ad):
    """Ses modunda **Sesi sıfırla**: konuşma ve müzik katmanları boşalır.

    Kurulmuş dosyalar (`youtube/<dil>/ses*.mp3`) **silinmez**: diller tek tek
    hazırlanırken önceki dillerin dosyaları kaybolmasın. Video değişmez.
    Dönüş: `(Ham videoya geri dön düğmesinin paketi, None)`.
    """
    veri, klasor, hata = proje_hedefi(ad, "sesi sıfırla")
    if hata:
        return (hata, None, [], "") + bos_paket(hata), None
    _durum_yolu(klasor).unlink(missing_ok=True)
    mesaj = ("Ses sıfırlandı: konuşma ve müzik katmanları boşaldı. Önceki ses dosyaları "
             "youtube/ klasöründe duruyor; video değişmedi.")
    return (mesaj, None, [], dil_listesi_metni(veri, klasor)) + arayuz_paketi(veri, mesaj), None


def ses_katmanlari(ad):
    """Ses modunun katman rozetleri: `[(etiket, var mı)]`; proje yoksa None."""
    veri, klasor, hata = proje_hedefi(ad, "ses katmanlarını göster")
    if hata:
        return None
    durum = _durum(klasor)
    dublaj = durum["konusma"] or ""
    return [("Seslendirme", durum["konusma"] == ""),
            ("Dublaj" + (f" · {dublaj}" if dublaj else ""), bool(dublaj)),
            ("Müzik", bool(durum["muzikler"])),
            ("Ses efekti", ekli_efekt(klasor)[0] is not None)]


def son_ses_dosyasi(ad):
    """Seçili konuşmanın ses dosyası (önizleme ve **Sesi indir** için; yoksa None)."""
    veri, klasor, hata = proje_hedefi(ad, "ses dosyası göster")
    if hata:
        return None
    durum = _durum(klasor)
    if durum["konusma"] is None:
        return None
    _ses, dil, kayit_ad = _konusma(klasor, veri, durum["konusma"])
    yol = _hedef_dosya(klasor, dil, kayit_ad)
    return str(yol) if yol.is_file() else None
