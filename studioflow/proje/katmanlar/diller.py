"""Dublaj ve altyazı kayıtları: ham video, dil sesi üretimi, videoya ekleme.

Akış ikiye ayrılmıştır: **kaydetmek** (dublajı üret ve listeye yaz, altyazıyı dile
göre kaydet) ile **videoya eklemek**. Kaydetme proje sayfasının müzik/dublaj/altyazı
sekmesinde, ekleme ise üretim sayfasındaki video altı panellerindedir; ikisi de
aynı kayıtlara bakar (`studioflow.proje.katmanlar.dublaj`, `studioflow.proje.katmanlar.altyazilar`).
"""
import hashlib
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import soundfile as sf

from studioflow.altyazi.bloklar import build_subtitles
from studioflow.altyazi.gorunum import altyazi_ayari, altyazi_olcu
from studioflow.altyazi.hizalama import cf_listen
from studioflow.ayarlar.bicimler import bicim_bilgisi
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.hatalar import dakikalik_bekleme, hata_etiketle, ses_hatasi_temizle
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.katmanlar.altyazilar import (
    altyazi_bul, altyazi_kayit_adi, altyazi_kayit_ozeti, altyazi_kayitlari,
    altyazi_kaydini_sil, altyazi_secimi_yaz, altyazi_yolu, altyazilari_tazele,
    dosyadan_kaydet, metinden_kaydet)
from studioflow.proje.birlestirme import birlestir
from studioflow.proje.depo import (
    calisma_klasoru, calismayi_temizle, dosya_kopyala, dosya_suresi, proje_adim_saniyesi,
    proje_klasoru)
from studioflow.proje.dosya import gorsel_kaynak_bicim, not_ekle, proje_yaz
from studioflow.proje.dosya_yollari import (
    altyazi_dosyasi, dil_dosya_listesi, dil_dosyasi, dil_klasoru, dil_kodu,
    anlatim_suzgeci, ham_video, ses_seviyesi, sure_ozeti)
from studioflow.proje.katmanlar.dublaj import (
    dublaj_adi, dublaj_bul, dublaj_kaydini_sil, dublaj_kayitlari, dublaj_ozeti,
    dublaj_secimi_yaz, dublaj_yaz, dublaj_yolu, dublajlari_tazele, ekli_dublaj_dosyasi)
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.ilerleme import arayuz_paketi, bos_ilerleme_html
from studioflow.proje.katmanlar import sahne_dublaji
from studioflow.proje.katmanlar.efektler import ekli_efekt, ekli_efekti_yaz
from studioflow.proje.katmanlar.muzik import muzik_geri_uygula
from studioflow.proje.sabitler import (
    COK_DIL_CEVIRI_SISTEM, HAM_VIDEO_ADI, VARSAYILAN_STIL)
from studioflow.proje.yeniden_deneme import hata_yaz
from studioflow.saglayicilar import ses_gecis, ses_uretim
from studioflow.saglayicilar.hesap_havuzu import (
    SES_HIZMET, aktif_anahtar, hesap_aktif_yap, hesap_ele, hesap_elendi, hesap_kimligi,
    hesap_listesi, kota_bekliyor)
from studioflow.saglayicilar.hesap_havuzu import VARSAYILAN as HAVUZ
from studioflow.saglayicilar.kota_listesi import VARSAYILAN as KOTA_LISTESI, saat_metni
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR


def ham_videoyu_hazirla(klasor, veri):
    """Ham videoyu getir; yoksa **adım kliplerinden** kur. `(yol, hata mesajı)` döner.

    Ham video her zaman adım kliplerinden üretilir; böylece `proje.mp4`e daha önce
    eklenmiş ses ya da altyazı ham videoya hiçbir zaman karışmaz. Adım klipleri yoksa
    (tek dosya hâlinde kalmış eski proje) mevcut `proje.mp4` ham sayılır.
    """
    if ham_video(klasor):
        return ham_video(klasor), ""
    klipler = [adim for adim in veri.get("adimlar") or []
               if adim.get("video") and (klasor / adim["video"]).is_file()]
    if klipler:
        ok, mesaj = birlestir(klasor, veri["adimlar"], klasor / HAM_VIDEO_ADI,
                              gorsel_kaynak_bicim(veri), adim_saniye=proje_adim_saniyesi(veri))
        if not ok:
            return None, "Ham video üretilemedi: " + mesaj
        return klasor / HAM_VIDEO_ADI, ""
    kaynak = klasor / "proje.mp4"
    if kaynak.is_file():
        try:
            shutil.copy2(kaynak, klasor / HAM_VIDEO_ADI)
        except OSError as hata:
            return None, "Ham video oluşturulamadı: " + _ilk_satir(hata, 200)
        return klasor / HAM_VIDEO_ADI, ""
    return None, ("Ham video yok: önce projeyi çalıştırıp adımların birleşmiş hâlini "
                  "(`proje.mp4`) oluştur.")


def _cok_dil_hedefi(ad):
    """Dil işlemlerinin ortak ön kontrolü. `(veri, klasör, hata mesajı)` döner."""
    return proje_hedefi(ad, "dublaj ya da altyazı ekle")


def _cok_dil_paketi(veri, mesaj, ses=None, dosyalar=None):
    """Panelin çıktı paketi: panel alanları + proje görünümü (çubuk, video, dosyalar)."""
    _mesaj, log, pj_dosyalar, gorseller, video, cubuk = arayuz_paketi(veri, mesaj)
    return (mesaj, ses, list(dosyalar or []), dil_listesi_metni(veri),
            mesaj, log, pj_dosyalar, gorseller, video, cubuk)


def _cok_dil_bos(mesaj):
    """Proje seçilmemişse/hata varsa panel paketi."""
    return (mesaj, None, [], "", mesaj, "", [], [], None, bos_ilerleme_html())


def _dublaj_paketi(veri, klasor, mesaj, ses=None, dosyalar=None):
    """Dublaj panellerinin çıktı paketi (kaydetme ve videoya ekleme aynı sırayı kullanır).

    Sıra: durum · liste damgası · seçim · dinleme sesi · dosyalar · dil özeti +
    proje görünümü (`arayuz_paketi`nin durum satırı dışındaki beşlisi). Liste damgası
    her işlemde değişir: arayüzdeki `gr.render` blokları kayıtları diskten tazeler.
    """
    durum = dublajlari_tazele(klasor) if klasor is not None else {"secim": ""}
    return ((mesaj, f"{time.time():.6f}", durum["secim"], ses, list(dosyalar or []),
             dil_listesi_metni(veri, klasor)) + arayuz_paketi(veri, mesaj)[1:])


def _dublaj_bos(mesaj):
    """Proje seçilmemişse/hata varsa dublaj paneli paketi."""
    return (mesaj, "", "", None, [], "", "", [], [], None, bos_ilerleme_html())


# `ses_ciktisi` dublaj panelini aynı paketle yanıtlar.
dublaj_paketi = _dublaj_paketi
dublaj_bos = _dublaj_bos


def _altyazi_paketi(veri, klasor, mesaj, dosyalar=None):
    """Altyazı panellerinin çıktı paketi: durum · liste damgası · seçim · dosyalar + görünüm."""
    durum = altyazilari_tazele(klasor) if klasor is not None else {"secim": ""}
    return ((mesaj, f"{time.time():.6f}", durum["secim"], list(dosyalar or []))
            + arayuz_paketi(veri, mesaj)[1:])


def _altyazi_bos(mesaj):
    """Proje seçilmemişse/hata varsa altyazı paneli paketi."""
    return (mesaj, "", "", [], "", [], [], None, bos_ilerleme_html())


def dil_listesi_metni(veri, klasor=None):
    """Panelde gösterilen özet: ham video durumu, videoya ekli dublaj/altyazı ve kayıtlar."""
    klasor = klasor or proje_klasoru(veri["slug"])
    ham = ham_video(klasor)
    ekli = (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()
    ekli_alt = (veri.get("ekli_altyazi") or "").strip()
    satirlar = ["Ham video: " + (f"hazır ({HAM_VIDEO_ADI})" if ham else
                                 "henüz yok · bir dublaj eklediğinde kliplerden kurulur"),
                "Videoya ekli dublaj: " + (ekli if ekli else "— (video ham hâlinde)"),
                "Videoya gömülü altyazı: " + (ekli_alt if ekli_alt else "—")]
    kayitlar = dublaj_kayitlari(klasor)
    if not kayitlar:
        satirlar.append("Kayıtlı dublaj yok: dil seçip **Dublajı kaydet**'e bas.")
    for kayit in kayitlar:
        satirlar.append(f"• {kayit['ad']} · " + dublaj_ozeti(kayit, kayit["ad"] == ekli))
    altyazilar = altyazi_kayitlari(klasor)
    if not altyazilar:
        satirlar.append("Kayıtlı altyazı yok: altyazı panelinden dile göre kaydet.")
    for kayit in altyazilar:
        satirlar.append(f"• altyazı: {kayit['ad']} · "
                        + altyazi_kayit_ozeti(kayit, kayit["ad"] == ekli_alt))
    return "\n".join(satirlar)


def dil_listesi(ad):
    """Arayüz için dil özeti: seçili projenin ham video durumu ve hazır diller."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return hata
    return dil_listesi_metni(veri, klasor)


def _metni_cevir(veri, kod, metin, ceviri_ai=""):
    """Anlatım metnini hedef dile çevir (bkz. `_ceviri_ai`)."""
    return _ceviri_ai(veri, ceviri_ai).metin(
        COK_DIL_CEVIRI_SISTEM,
        f"Target language: {LANGUAGES[kod]}\n\n"
        f"Narration to translate:\n<<<\n{metin}\n>>>", json_modu=False).strip()


def _ceviri_ai(veri, servis=""):
    """Çeviri yapay zekâsı: dublaj panelinde seçilen servis (boşsa projenin prompt
    servisi). Servis projeninkiyle aynıysa projenin modeli, değilse servisin en iyi
    modeli kullanılır; kota/yetki hatasında aynı servisin **sıradaki hesabına** geçer
    (bkz. `HesapliMetin`)."""
    video = veri["ayarlar"]["video"]
    proje_ai = video.get("ai") or "gemini"
    servis = servis if servis in AI_SAGLAYICILAR else proje_ai
    return HesapliMetin(servis, (video.get("model") or "") if servis == proje_ai else "")


# Bütün hesaplar kota (429) verdiğinde turlar arası beklemeler (sn). Gemini TTS'in 429'u
# çoğunlukla **dakikalık** sınırdır: 07.10.2026'da 10 hesabın hepsi 33. blokta 429 verdi,
# 2,5 dk sonra aynı hesaplar aynı metni sorunsuz seslendirdi. Bu yüzden kota hatası
# hesabı elemez; tur biter, beklenir, yeniden denenir.
SES_BEKLEMELERI = (60, 120, 180)   # yalnızca dakikalık sınırda (bkz. `dakikalik_bekleme`)
_bekle = time.sleep
# Geçici hata (yarım kalan ses akışı, 5xx, kopan bağlantı) bir seslendirmede en fazla
# kaç kez yeniden denenir; denemeler sıradaki hesapla yapılır.
SES_GECICI_TEKRAR = 2


def _gecici_mi(mesaj):
    """Hesap ya da kotayla ilgisiz, yeniden denemekle geçebilecek hata mı?"""
    dusuk = str(mesaj).lower()
    return (hata_etiketle(mesaj) == "BAĞLANTI"
            or any(k in dusuk for k in ("please retry", "could not be completed", "http 500",
                                        "http 502", "http 503", "http 504", "overloaded",
                                        "unavailable", "internal error")))


def _hesapli_ses(veri, provider, uret):
    """Sesi, seslendirme servisinin hesaplarını **sırayla deneyerek** üret.

    `uret(kimlik)` bir `ses_uretim` üreteci döndürür; paketleri aynen aktarılır.
    Yetki hatası veren hesap bu çalışma boyunca elenir; kota hatası verende sıradaki
    hesaba geçilir. Bütün hesaplar kota verirse `SES_BEKLEMELERI` kadar beklenip tur
    yinelenir. Başka bir hata (hesap değiştirmenin çözmeyeceği) doğrudan döner.
    Edge anahtarsızdır; tek geçişte çalışır.
    """
    hizmet = SES_HIZMET.get(provider)
    if not hizmet:
        yield from uret(hesap_kimligi(veri))
        return
    gecici = 0
    for tur in range(len(SES_BEKLEMELERI) + 1):
        # Hepsi elendiyse ilki yine denenir (bu çalışmadaki eleme geçici olabilir); kalıcı
        # kota listesindeki hesap ise kotası yenilenmeden **hiç** seçilmez.
        hesaplar = ([h for h in hesap_listesi(hizmet) if not hesap_elendi(hizmet, h)]
                    or [h for h in hesap_listesi(hizmet)
                        if kota_bekliyor(hizmet, h) is None][:1])
        if not hesaplar:
            bekleyen = KOTA_LISTESI.liste(hizmet)
            ilk = (f" En erken açılan hesap: '{bekleyen[0]['ad']}' "
                   f"{saat_metni(bekleyen[0]['acilis'])}." if bekleyen else "")
            yield (f"Bütün hesapların kotası dolu (kota bekleme listesinde).{ilk}",
                   None, [], [])
            return
        kotali = False
        for hesap in hesaplar:
            son = None
            for paket in uret(hesap_kimligi(veri, hizmet, hesap)):
                son = paket
                yield paket
            if son and son[1]:
                hesap_aktif_yap(hizmet, hesap)
                return
            etiket = hata_etiketle(son[0]) if son else "HATA"
            if etiket == "YETKİ" or (etiket == "KOTA" and dakikalik_bekleme(son[0]) is None):
                # Yetki ya da **günlük** kota (ör. "10 requests per day"): beklemek çözmez.
                hesap_ele(hizmet, hesap, son[0])
            elif etiket == "KOTA":
                kotali = True
                # Dakikalık sınır da kota uyarısıdır: hesap listede görünür (süresi kadar).
                HAVUZ.kota_uyarisi(hizmet, hesap, son[0])
            elif son and gecici < SES_GECICI_TEKRAR and _gecici_mi(son[0]):
                # Gemini uzun okumada ara sıra "The audio stream could not be
                # completed. Please retry" diyor (İspanyolca, 09.10.2026): yeniden denenir.
                gecici += 1
            else:
                return
            yield (f"'{hesap['ad']}' hesabı kullanılamadı ({_ilk_satir(son[0], 120)}); "
                   "sıradaki hesap deneniyor…", None, [], [])
        if not kotali or tur == len(SES_BEKLEMELERI):
            return
        sure = SES_BEKLEMELERI[tur]
        yield (f"Bütün hesaplar hız/kota sınırında; {sure} sn beklenip yeniden denenecek…",
               None, [], [])
        _bekle(sure)


def dublaj_dosya_listesi(klasor, kayit):
    """Bir dublaj kaydının indirilebilir dosyaları: ses · altyazı · çevrilmiş metin."""
    kok = dil_klasoru(klasor)
    adaylar = [kok / f"seslendirme-{kayit['ad']}{uzanti}" for uzanti in (".wav", ".srt", ".vtt")]
    adaylar.append(kok / f"metin-{kayit['ad']}.txt")
    return [str(yol) for yol in adaylar if yol.is_file()]


def dil_sesi_uret(ad, dil, cevir, provider, edge_ses, gemini_model, gemini_ses, hiz, ton,
                  isim="", sahneye_gore=False, ceviri_ai=""):
    """Seçili dil için dublaj üret ve **listeye kaydet**; gerekirse metni önce çevir.

    Dosyalar `ses/diller/seslendirme-<ad>.wav` (yanında `.srt` ve `metin-<ad>.txt`)
    olarak yazılır; `isim` boşsa ad **dil kodudur**, yani tek dilli eski projelerin
    dosya adları değişmez. Aynı adla yeniden üretmek kaydı günceller, başka bir adla
    üretmek aynı dile **ikinci bir dublaj** ekler (ör. farklı ses denemesi).

    Üretilen altyazı da (proje ayarlarında **Altyazı üret** açıksa) kendi başına
    kaydedilir: artık dublaja iliştirilmiş bir kutucuk değil, listede duran ayrı bir
    parçadır ve videoya üretim sayfasından gömülür.

    Ses parçaları projenin `.calisma/dublaj` klasöründe üretilir ve iş bitince silinir.

    `sahneye_gore=True` dublajı **sahne sahne** kurar: çeviri ve ses adım zamanlarına
    oturtulur, bloklar üst üste binmez (bkz. `sahne_dublaji`). Kapalıyken (varsayılan)
    düz dublaj eskisi gibi çalışır.

    `ceviri_ai` çeviriyi yapan yapay zekâ servisidir (boşsa projenin prompt servisi).
    """
    try:
        yield from _dil_sesi_uret(ad, dil, cevir, provider, edge_ses, gemini_model,
                                  gemini_ses, hiz, ton, isim, sahneye_gore, ceviri_ai)
    finally:
        if (ad or "").strip():
            calismayi_temizle(proje_klasoru(ad), "dublaj")


def _dil_sesi_uret(ad, dil, cevir, provider, edge_ses, gemini_model, gemini_ses, hiz, ton,
                   isim, sahneye_gore=False, ceviri_ai=""):
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        yield _dublaj_bos(hata)
        return
    kod = dil_kodu(dil)
    if not kod:
        yield _dublaj_paketi(veri, klasor, "Geçerli bir hedef dil seç.")
        return
    kayit_ad = dublaj_adi(isim, kod)
    metin = (veri.get("metin") or "").strip()
    if not metin:
        yield _dublaj_paketi(veri, klasor, "Projenin anlatım metni boş; önce projeyi oluştur.")
        return

    ayar = veri["ayarlar"]["ses"]
    if sahneye_gore and veri.get("adimlar"):
        sonuc = yield from _sahneli_dublaj(veri, klasor, kod, kayit_ad, cevir, provider,
                                           edge_ses, gemini_model, gemini_ses, hiz, ton,
                                           ceviri_ai)
        if sonuc is None:
            return
        son_ses, altyazilar, hedef_metin, notlar = sonuc
    else:
        hedef_metin, notlar = metin, []
        if cevir and kod != (ayar.get("dil") or ""):
            yield _dublaj_paketi(veri, klasor, f"Anlatım {LANGUAGES[kod]} diline çevriliyor…")
            try:
                hedef_metin = _metni_cevir(veri, kod, metin, ceviri_ai)
            except Exception as exc:
                yield _dublaj_paketi(
                    veri, klasor,
                    "Metin çevrilemedi: " + ses_hatasi_temizle(exc, aktif_anahtar("gemini", "gemini_key"))
                    + "\nÇeviri kutusunu kapatıp hedef dildeki metinle üretebilirsin.")
                return
            if not hedef_metin:
                yield _dublaj_paketi(veri, klasor, "Çeviri boş döndü; tekrar dene.")
                return
            notlar.append(f"metin çevrildi ({len(hedef_metin)} karakter)")

        kimlik = hesap_kimligi(veri)
        son_ses, altyazilar = None, []
        yield _dublaj_paketi(veri, klasor, f"{LANGUAGES[kod]} dublajı üretiliyor…")
        try:
            for durum, ses_yolu, proje_dosyalari, alt_dosyalar in _hesapli_ses(
                    veri, provider, lambda kimlik: ses_uretim.VARSAYILAN.uret(
                    provider, hedef_metin, kod, key=kimlik["gemini_key"],
                    model=gemini_model, voice=gemini_ses, style=ayar.get("stil") or VARSAYILAN_STIL,
                    token=kimlik["hf_token"], reference=None, exaggeration=0.5, cfg=0.5,
                    edge_voice=edge_ses, rate=hiz, pitch=ton,
                    cf_account=kimlik["cf_account_id"], cf_token=kimlik["cf_token"],
                    subtitles=bool(veri["ayarlar"]["altyazi"]["acik"]),
                    subtitle_ayar=veri["ayarlar"]["altyazi"]["ayar"],
                    hedef_klasor=calisma_klasoru(veri, "dublaj"))):
                if ses_yolu:
                    son_ses = Path(ses_yolu)
                if alt_dosyalar:
                    altyazilar = [Path(yol) for yol in alt_dosyalar]
                yield _dublaj_paketi(
                    veri, klasor, durum, str(son_ses) if son_ses and son_ses.exists() else None,
                    [str(yol) for yol in altyazilar])
        except Exception as exc:
            yield _dublaj_paketi(veri, klasor, "Dublaj üretilemedi: "
                                 + ses_hatasi_temizle(exc, kimlik["gemini_key"],
                                                      kimlik["hf_token"]))
            return
        if not son_ses or not son_ses.exists():
            yield _dublaj_paketi(veri, klasor, "Ses dosyası oluşmadı; yukarıdaki durum notunu oku.")
            return

    hedef = dil_klasoru(klasor)
    try:
        hedef.mkdir(parents=True, exist_ok=True)
        yazilan = [dosya_kopyala(son_ses, hedef / f"seslendirme-{kayit_ad}.wav")]
        for yol in altyazilar:
            if yol.suffix.lower() in (".srt", ".vtt"):
                yazilan.append(dosya_kopyala(
                    yol, hedef / f"seslendirme-{kayit_ad}{yol.suffix.lower()}"))
        # Çevrilmiş metin de saklanır: sonradan düzeltip yeniden seslendirebilirsin.
        (hedef / f"metin-{kayit_ad}.txt").write_text(hedef_metin, encoding="utf-8")
    except OSError as exc:
        yield _dublaj_paketi(veri, klasor, "Dublaj üretildi ama proje klasörüne yazılamadı: "
                             + _ilk_satir(exc, 200))
        return

    ses_hedef = hedef / f"seslendirme-{kayit_ad}.wav"
    srt = hedef / f"seslendirme-{kayit_ad}.srt"
    kayit = {"ad": kayit_ad, "dil": kod,
             "dosya": ses_hedef.relative_to(klasor).as_posix(),
             "altyazi": srt.relative_to(klasor).as_posix() if srt.is_file() else "",
             "metin": (hedef / f"metin-{kayit_ad}.txt").relative_to(klasor).as_posix(),
             "provider": provider, "ses": gemini_ses if provider == "gemini" else edge_ses,
             "sure": dosya_suresi(ses_hedef), "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    dublaj_yaz(klasor, kayit)
    # Altyazı da kendi listesine girer: dublajın kutucuğu değil, ayrı bir kayıttır.
    alt_notu = ""
    if srt.is_file():
        alt_kayit, alt_hata = dosyadan_kaydet(klasor, srt, kayit_ad, kod, "dublaj")
        alt_notu = (f" Altyazı da **{alt_kayit['ad']}** adıyla kaydedildi."
                    if alt_kayit else f" Altyazı kaydedilemedi: {alt_hata}")
    dosyalar = dublaj_dosya_listesi(klasor, kayit)
    not_ekle(veri, f"'{kayit_ad}' dublajı kaydedildi ({LANGUAGES.get(kod, kod)} · "
                   f"{dosya_suresi(ses_hedef):.1f} sn)"
                   + (", altyazı yazıldı" if srt.is_file() else "")
                   + (", " + ", ".join(notlar) if notlar else "") + ".")
    proje_yaz(veri)
    mesaj = (f"**{kayit_ad}** dublajı kaydedildi · {LANGUAGES.get(kod, kod)} · "
             f"{dosya_suresi(ses_hedef):.1f} sn.\n"
             + ((" · ".join(notlar) + "\n") if notlar else "") + alt_notu
             + " Videoya eklemek için aşağıdaki **Videoya ekle** panelinden seç.")
    yield _dublaj_paketi(veri, klasor, mesaj, str(ses_hedef), dosyalar)


# Sahneli dublajın blok sesleri burada birikir; iş **başarıyla** bitince silinir. Kota
# yarıda biterse üretilmiş bloklar kalır, yeniden denemede yalnızca eksikler üretilir.
SAHNE_DUBLAJ_KLASORU = "dublaj-sahne"


# Tek istekte çevrilen blok sayısı. 121 blok tek istekte gidince akıl yürüten model
# (Cloudflare nemotron) düşünme + çeviriyle token sınırına dayanıyor, JSON yarıda
# kalıyordu ("Çeviri yanıtı JSON dizisi değil"). Gruplar küçük tutulur.
CEVIRI_GRUBU = 15
# Bozuk/eksik JSON dönen grubun **eksik blokları** en fazla bu kadar istekte tamamlanır.
# Gemini 15 bloğun bazen yalnızca ilk 10'unu döndürüyor (İspanyolca, 17.10.2026); eskiden
# grup iki denemede tamamlanamazsa bütün dublaj düşüyordu.
CEVIRI_TEKRAR = 4
# Geçici hatada (yoğun model 503'ü, kopan bağlantı) bütün çeviri boyunca yapılan beklemeler (sn).
CEVIRI_YOGUN_BEKLEMELERI = (30, 60, 120, 180, 300, 300)


def _blok_cevir(veri, kod, bloklar, butceler, ceviri_ai=""):
    """Blokları `CEVIRI_GRUBU`'luk gruplar hâlinde çevir; `(metinler, hata)` döner.

    Yanıtta eksik kalan bloklar atılmaz: gelenler saklanır, sonraki istekte yalnızca
    eksikler gönderilir.
    """
    ai, metinler, yogun_bekleme = _ceviri_ai(veri, ceviri_ai), [], 0
    for bas in range(0, len(bloklar), CEVIRI_GRUBU):
        grup, butce = bloklar[bas:bas + CEVIRI_GRUBU], butceler[bas:bas + CEVIRI_GRUBU]
        bulunan, son_hata, deneme = {}, "", 0
        while deneme < CEVIRI_TEKRAR:
            deneme += 1
            eksik = [sira for sira in range(len(grup)) if sira not in bulunan]
            try:
                cevap = ai.metin(
                    sahne_dublaji.CEVIRI_SISTEM,
                    sahne_dublaji.ceviri_istegi([grup[s] for s in eksik], [butce[s] for s in eksik],
                                                LANGUAGES[kod]), json_modu=True)
                parcalar = sahne_dublaji.ceviri_parcalari(cevap, len(eksik))
            except ValueError as exc:
                son_hata = str(exc)       # yanıt geldi ama çözülemedi: yeniden istenir
                continue
            except Exception as exc:
                if not _gecici_mi(exc) or yogun_bekleme >= len(CEVIRI_YOGUN_BEKLEMELERI):
                    return None, ses_hatasi_temizle(exc, aktif_anahtar("gemini", "gemini_key"))
                # Model yoğun (503) ya da bağlantı koptu: çevrilmiş gruplar korunur,
                # beklenip aynı grup yeniden istenir (Hintçe dublaj, 22.10.2026).
                _bekle(CEVIRI_YOGUN_BEKLEMELERI[yogun_bekleme])
                yogun_bekleme += 1
                son_hata, deneme = str(exc), deneme - 1    # bekleme deneme sayılmaz
                continue
            for yerel, metin in parcalar.items():
                bulunan[eksik[yerel]] = metin
            if len(bulunan) == len(grup):
                break
            son_hata = (f"Çeviride {len(grup) - len(bulunan)} blok eksik "
                        f"(yanıtın sonu: {_ilk_satir(cevap[-150:], 150)})")
        eksik = [sira for sira in range(len(grup)) if sira not in bulunan]
        if eksik:
            return None, (f"{bas + 1}–{bas + len(grup)}. bloklar ({CEVIRI_TEKRAR} istekte "
                          f"{len(eksik)} blok tamamlanamadı): "
                          + ses_hatasi_temizle(son_hata, aktif_anahtar("gemini", "gemini_key")))
        metinler += [bulunan[sira] for sira in range(len(grup))]
    return metinler, ""


# Cloudflare whisper'ın tanımadığı diller ("'ga' is not a valid language code").
WHISPER_DESTEKSIZ = {"ga"}
# Bu dillerde parça okunurken yönetmen notuna eklenir: bloklar arası belirgin sessizlik.
BLOK_ARASI_SESSIZLIK = (" Between paragraphs, leave a clear silence of about two seconds;"
                        " within a paragraph, keep pauses short.")


def _dinle(veri, ses_yolu, kod):
    """Sesi Cloudflare whisper ile dinle; kotası/yetkisi biten hesaptan sıradakine geç.

    Whisper görselle **aynı** günlük nöron hakkını harcar; görsel üretimi bir hesabın
    hakkını bitirmiş olabilir (Yunanca dublaj, 09.10.2026: aktif hesap bitikti, beş
    parçanın hiçbiri dinlenemedi). Hiçbir hesap dinleyemezse son hata yükseltilir.
    """
    son_hata = None
    for hesap in hesap_listesi("cloudflare"):
        if hesap_elendi("cloudflare", hesap):
            continue
        kimlik = hesap_kimligi(veri, "cloudflare", hesap)
        if not (kimlik["cf_account_id"] and kimlik["cf_token"]):
            continue
        try:
            return cf_listen(str(ses_yolu), kimlik["cf_account_id"], kimlik["cf_token"],
                             language=kod)
        except Exception as exc:
            son_hata = exc
            if hata_etiketle(str(exc)) not in ("KOTA", "YETKİ"):
                raise
            hesap_ele("cloudflare", hesap, str(exc))
    if son_hata is not None:
        raise son_hata
    raise RuntimeError("Cloudflare hesabı kayıtlı değil.")


def _sahneli_dublaj(veri, klasor, kod, kayit_ad, cevir, provider, edge_ses, gemini_model,
                    gemini_ses, hiz, ton, ceviri_ai=""):
    """Dublajı sahne sahne kur (bkz. `sahne_dublaji`).

    Üreteçtir: arayüz paketleri verir, sonunda `(ses, altyazı dosyaları, metin, notlar)`
    döndürür; başarısızsa mesajı vermiş olarak `None` döndürür.
    """
    ayar = veri["ayarlar"]["ses"]
    bloklar = sahne_dublaji.bloklari_kur(veri["adimlar"])
    if not bloklar:
        yield _dublaj_paketi(veri, klasor, "Adımların metni yok; sahneli dublaj kurulamadı.")
        return None
    toplam = max([float(a.get("end") or 0.0) for a in veri["adimlar"]]
                 + [float((veri.get("ses") or {}).get("sure") or 0.0)])
    pencereler = sahne_dublaji.pencereler(bloklar, toplam)
    butceler = [sahne_dublaji.kelime_butcesi(sure) for sure in pencereler]
    cevrilecek = bool(cevir) and kod != (ayar.get("dil") or "")
    metinler, notlar = [blok["text"] for blok in bloklar], []
    if cevrilecek:
        yield _dublaj_paketi(veri, klasor, f"{len(bloklar)} sahne bloğu {LANGUAGES[kod]} "
                                           "diline, sahne sürelerine sığacak şekilde çevriliyor…")
        metinler, hata = _blok_cevir(veri, kod, bloklar, butceler, ceviri_ai)
        if metinler is None:
            yield _dublaj_paketi(veri, klasor, "Metin çevrilemedi: " + hata)
            return None
        notlar.append(f"{len(bloklar)} blok sahne süresine göre çevrildi")

    kimlik = hesap_kimligi(veri)
    onbellek = calisma_klasoru(veri, SAHNE_DUBLAJ_KLASORU) / kayit_ad
    onbellek.mkdir(parents=True, exist_ok=True)
    ses_adi = gemini_ses if provider == "gemini" else edge_ses

    def seslendir(sira, metin, stil_ek=""):
        """Bloğu seslendir (önbellekte varsa yeniden üretme); WAV yolunu verir."""
        iz = hashlib.sha1("|".join([provider, str(ses_adi), str(gemini_model), str(hiz),
                                    str(ton), metin, stil_ek]).encode("utf-8")).hexdigest()[:10]
        hedef = onbellek / (f"blok-{sira:03d}-{iz}.wav" if sira >= 0
                            else f"parca-{-sira:03d}-{iz}.wav")
        if hedef.is_file():
            return hedef
        son, son_durum = None, ""
        for son_durum, ses_yolu, _d, _a in _hesapli_ses(
                veri, provider, lambda kimlik: ses_uretim.VARSAYILAN.uret(
                provider, metin, kod, key=kimlik["gemini_key"], model=gemini_model,
                voice=gemini_ses, style=(ayar.get("stil") or VARSAYILAN_STIL) + stil_ek,
                token=kimlik["hf_token"], reference=None, exaggeration=0.5, cfg=0.5,
                edge_voice=edge_ses, rate=hiz, pitch=ton, subtitles=False,
                hedef_klasor=calisma_klasoru(veri, "dublaj"))):
            if ses_yolu:
                son = Path(ses_yolu)
        if not son or not son.is_file():
            raise RuntimeError((f"{sira + 1}. blok" if sira >= 0 else f"{-sira}. parça")
                               + " için ses dosyası oluşmadı: "
                               + _ilk_satir(son_durum, 200))
        return dosya_kopyala(son, hedef)

    def hepsini_seslendir(siralar):
        for adim_no, sira in enumerate(siralar, 1):
            yield _dublaj_paketi(veri, klasor, f"Blok {adim_no}/{len(siralar)} seslendiriliyor…")
            dosyalar[sira] = seslendir(sira, metinler[sira])
            # Tek başına okunan blok: hem kendisi hem ardından gelen blok bir okuma başıdır.
            okuma_baslari.update(s for s in (sira, sira + 1) if s < len(bloklar))

    def blok_yolu(sira):
        iz = hashlib.sha1("|".join([provider, str(ses_adi), str(gemini_model), str(hiz),
                                    str(ton), metinler[sira]]).encode("utf-8")).hexdigest()[:10]
        return onbellek / f"blok-{sira:03d}-{iz}.wav"

    def parcali_seslendir():
        """Blokları büyük parçalar hâlinde seslendirip blok sınırlarından kes.

        Bkz. `sahne_dublaji.ses_parcalari`: ses kesintisiz okunduğu için blok
        sınırlarında konuşmacı kaymaz. Önbellekte duran bloklar yeniden üretilmez.
        """
        parcalar = sahne_dublaji.ses_parcalari(metinler)
        kuyruk = list(enumerate(parcalar, 1))
        # Whisper bu dili tanımıyorsa blok sınırı dinlenerek bulunamaz: Gemini bloklar
        # arasında belirgin bir sessizlik bırakır, kesim o sessizliklere oturur.
        duyulmaz = kod in WHISPER_DESTEKSIZ
        if duyulmaz:
            notlar.append("whisper bu dili tanımıyor; bloklar arasına sessizlik bırakılıp "
                          "sessizliklerden kesildi")
        while kuyruk:
            no, siralar = kuyruk.pop(0)
            okuma_baslari.add(siralar[0])     # önbellekteki parça da ayrı bir okumadır
            if all(blok_yolu(sira).is_file() for sira in siralar):
                for sira in siralar:
                    dosyalar[sira] = blok_yolu(sira)
                continue
            yield _dublaj_paketi(veri, klasor, f"Parça {no}/{len(parcalar)} seslendiriliyor "
                                               f"({len(siralar)} blok, tek okuma)…")
            parca_metinleri = [metinler[sira] for sira in siralar]
            try:
                if duyulmaz:
                    parca = seslendir(-no, "\n\n".join(parca_metinleri), BLOK_ARASI_SESSIZLIK)
                else:
                    parca = seslendir(-no, " ".join(parca_metinleri))
            except Exception as exc:
                if len(siralar) < 2 or not _gecici_mi(str(exc)):
                    raise
                # Gemini bazı uzun okumaları tekrar tekrar yarıda kesiyor ("audio stream
                # could not be completed", Japonca, 09.10.2026): parça ikiye bölünür.
                yari = len(siralar) // 2
                kuyruk[:0] = [(no * 10 + 1, siralar[:yari]), (no * 10 + 2, siralar[yari:])]
                notlar.append(f"parça {no} okunamadı, ikiye bölündü")
                continue
            ses, oran = sf.read(str(parca), dtype="float32", always_2d=True)
            ses = ses.mean(axis=1)
            kelimeler = []
            if len(siralar) > 1 and not duyulmaz:
                yield _dublaj_paketi(veri, klasor, f"Parça {no}/{len(parcalar)} dinleniyor "
                                                   "(blok sınırları bulunuyor)…")
                try:
                    kelimeler = _dinle(veri, parca, kod)
                except Exception as exc:
                    notlar.append(f"parça {no} dinlenemedi, sınırlar sesteki duraklamalardan "
                                  f"bulundu ({_ilk_satir(exc, 80)})")
            if len(siralar) > 1 and len(sahne_dublaji.belirtec_zamanlari(kelimeler)) < sum(
                    len(sahne_dublaji.belirtecler(m)) for m in parca_metinleri) * 0.5:
                kelimeler = []          # whisper yanlış çözdü: kesim metinden tahmin edilir
            kesimler = sahne_dublaji.kesim_noktalari(parca_metinleri, kelimeler, ses, oran)
            for sira, blok_sesi in zip(siralar, sahne_dublaji.parcayi_kes(ses, oran, kesimler)):
                sf.write(str(blok_yolu(sira)), blok_sesi, oran, subtype="PCM_16")
                dosyalar[sira] = blok_yolu(sira)

    dosyalar = [None] * len(bloklar)
    okuma_baslari = set()      # ayrı bir Gemini okumasıyla başlayan blokların sıraları
    try:
        yield from parcali_seslendir()
        sureler = [dosya_suresi(d) for d in dosyalar]
        yerlesim = sahne_dublaji.yerlestir(bloklar, sureler, toplam)
        kisa = sahne_dublaji.kisaltilacaklar(yerlesim) if cevrilecek else []
        if kisa:
            yield _dublaj_paketi(veri, klasor, f"{len(kisa)} blok sahnesine sığmadı; daha kısa "
                                               "çevrilip yeniden seslendiriliyor…")
            yeni_butce = [sahne_dublaji.kisa_butce(len(metinler[sira].split()), sureler[sira],
                                                   pencereler[sira]) for sira in kisa]
            kisalar, _hata = _blok_cevir(veri, kod, [bloklar[sira] for sira in kisa], yeni_butce,
                                         ceviri_ai)
            if kisalar:
                for sira, metin in zip(kisa, kisalar):
                    metinler[sira] = metin
                yield from hepsini_seslendir(kisa)
                sureler = [dosya_suresi(d) for d in dosyalar]
                yerlesim = sahne_dublaji.yerlestir(bloklar, sureler, toplam)
                notlar.append(f"{len(kisa)} blok kısaltıldı")
    except Exception as exc:
        yield _dublaj_paketi(veri, klasor, "Dublaj üretilemedi: "
                             + ses_hatasi_temizle(exc, kimlik["gemini_key"], kimlik["hf_token"])
                             + " Üretilen bloklar saklandı; yeniden denediğinde kalanlar üretilir.")
        return None

    # Hızlandırma: penceresine sığmayan blok `atempo` ile (perdesi değişmeden) sıkıştırılır.
    calisma = calisma_klasoru(veri, "dublaj")
    calisma.mkdir(parents=True, exist_ok=True)
    son_dosyalar = []
    for sira, (dosya, yer) in enumerate(zip(dosyalar, yerlesim)):
        if yer["hiz"] > 1.001 and FFMPEG.ffmpeg():
            hizli = calisma / f"blok-{sira:03d}-hizli.wav"
            ok, _hata = FFMPEG.calistir([FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel",
                                         "error", "-i", str(dosya), "-filter:a",
                                         f"atempo={yer['hiz']:.3f}", str(hizli)])
            son_dosyalar.append(hizli if ok and hizli.is_file() else dosya)
        else:
            son_dosyalar.append(dosya)
    yerlesim = [dict(yer, sure=dosya_suresi(d)) for yer, d in zip(yerlesim, son_dosyalar)]
    cikti = calisma / "seslendirme.wav"
    try:
        sahne_dublaji.karistir(son_dosyalar, yerlesim, toplam, cikti)
    except (OSError, ValueError) as exc:
        yield _dublaj_paketi(veri, klasor, "Bloklar birleştirilemedi: " + _ilk_satir(exc, 200))
        return None
    # Okuma sınırlarında yüksek başlayan okumayı yumuşat (bkz. ses_gecis); yalnız kazanç
    # değişir, yerleşim ve altyazı zamanları aynı kalır. Hata olursa ses olduğu gibi kalır.
    if provider == "gemini" and len(okuma_baslari) > 1:
        try:
            rapor = ses_gecis.dosyada_yumusat(
                cikti, [yerlesim[sira]["bas"] for sira in sorted(okuma_baslari) if sira > 0])
            if ses_gecis.rapor_ozeti(rapor):
                notlar.append(ses_gecis.rapor_ozeti(rapor))
        except Exception as exc:
            notlar.append("geçiş yumuşatma atlandı (" + _ilk_satir(exc, 100) + ")")
    altyazilar = []
    if veri["ayarlar"]["altyazi"]["acik"]:
        altyazilar, _adet, _uzun = build_subtitles(
            sahne_dublaji.altyazi_kelimeleri(metinler, yerlesim), calisma,
            veri["ayarlar"]["altyazi"]["ayar"])
    hizlanan = sum(1 for yer in yerlesim if yer["hiz"] > 1.001)
    tasan = sum(1 for yer in yerlesim if yer["tasma"] > 0.05)
    notlar.append(f"sahneye göre hizalandı: {len(bloklar)} blok, {hizlanan} hızlandırıldı, "
                  f"{tasan} sonraki sahneye taştı (üst üste binme yok)")
    calismayi_temizle(klasor, SAHNE_DUBLAJ_KLASORU)
    return cikti, [Path(yol) for yol in altyazilar], "\n".join(metinler), notlar


def dil_dosya_goster(ad, dil):
    """Seçili dilin hazır dosyalarını indirme kutusuna koy (hiçbir şey üretmez)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return [], hata
    kod = dil_kodu(dil)
    if not kod:
        return [], "Geçerli bir dil seç."
    dosyalar = dil_dosya_listesi(klasor, kod)
    if not dosyalar:
        return [], f"'{kod}' için hazır dosya yok: **Dublajı kaydet**'e bas."
    return dosyalar, f"'{kod}' için hazır {len(dosyalar)} dosya indirme kutusunda."


# ── dublaj kayıtları · arayüz (proje adıyla çağrılır) ─────────────────────────
def dublaj_listesi(ad):
    """Arayüz için kaydedilmiş dublajlar (dosyası diskte duranlar, kayıt sırasıyla)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return []
    return dublaj_kayitlari(klasor)


def dublaj_sec(ad, isim):
    """Üretim sayfasında seçilen dublajı projeye yaz; geçerli seçimi döndürür."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return dublaj_secimi_yaz(klasor, isim)


def dublaj_secimi(ad):
    """Listede **seçili** dublajın adı (proje açılırken panele yazılır)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return dublajlari_tazele(klasor)["secim"]


def ekli_dublaj_adi(ad):
    """Videoya **eklenmiş** dublajın adı (yoksa boş metin): listedeki işaret için."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()


def dublaj_sil(ad, isim):
    """Kayıtlı dublajı listeden ve diskten kaldır (videoya ekliyse video değişmez)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _dublaj_bos(hata)
    silindi, kayit = dublaj_kaydini_sil(klasor, isim)
    if not silindi:
        return _dublaj_paketi(veri, klasor, f"'{isim}' adlı dublaj listede yok.")
    baslik = f"'{kayit['ad']}' dublajı silindi (ses, altyazı ve metin dosyaları)."
    not_ekle(veri, baslik)
    proje_yaz(veri)
    ek = (" Bu dublaj videoya eklenmişti: video değişmedi, başka bir dublaj ekleyerek "
          "ya da **Ham videoya geri dön** ile değiştirebilirsin."
          if (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "") == kayit["ad"] else "")
    return _dublaj_paketi(veri, klasor, baslik + ek)


def dublaj_videoya_ekle(ad, isim, seviye=None):
    """Kayıtlı bir dublajı videoya ekle (altyazı **ayrı** bir işlemdir).

    `proje.mp4` her zaman **ham videodan** yeniden kurulur: üst üste dublaj eklemek
    sesleri karıştırmaz, videoda yalnızca son eklenen dublaj duyulur. Kayıtlar
    silinmez; başka bir dublajı seçip yeniden eklemek yeter. Video baştan kurulduğu
    için gömülü altyazı kalkar ve müzik katmanı (ekliyse) geri uygulanır.

    `seviye` dublaj panelindeki ses seviyesidir (%); verilirse önce projeye yazılır.
    Dublaj ile seslendirme **aynı** seviyeyi (`ses.seviye`) paylaşır: videoda tek
    konuşma sesi olduğu için iki ayrı değer tutulmaz.
    """
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _dublaj_bos(hata)
    if seviye is not None:
        ses_ayar = veri["ayarlar"].setdefault("ses", {})
        if ses_seviyesi(ses_ayar.get("seviye")) != ses_seviyesi(seviye):
            ses_ayar["seviye"] = ses_seviyesi(seviye)
            not_ekle(veri, f"Dublaj seviyesi panelden güncellendi: %{ses_ayar['seviye']:g}.")
    if not FFMPEG.ffmpeg():
        return _dublaj_paketi(veri, klasor, "ffmpeg bulunamadı; videoya dublaj eklenemedi.")
    kayit = dublaj_bul(klasor, isim)
    ses = dublaj_yolu(klasor, kayit) if kayit else None
    if ses is None:
        return _dublaj_paketi(
            veri, klasor, f"'{isim or '—'}' adlı kayıtlı dublaj yok. Listeden bir dublaj "
                          "seç ya da yukarıdaki panelde yeni bir dublaj "
                          "kaydet.")
    ham, mesaj = ham_videoyu_hazirla(klasor, veri)
    if ham is None:
        return _dublaj_paketi(veri, klasor, mesaj)

    gecici = klasor / "proje-dil.gecici.mp4"
    gecici.unlink(missing_ok=True)
    # Görüntü ham videodan **kopyalanır** (yeniden kodlanmaz): işlem hızlıdır ve
    # görüntü kalitesi her eklemede yeniden sıkıştırılarak düşmez.
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(ham), "-i", str(ses), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy"]
    # Seslendirme seviyesi dublaja da uygulanır (bkz. `anlatim_suzgeci`).
    if anlatim_suzgeci(veri):
        komut += ["-af", anlatim_suzgeci(veri)]
    komut += ["-c:a", "aac", "-b:a", "192k", str(gecici)]
    ok, hata_mesaji = FFMPEG.calistir(komut, cwd=klasor)
    if not ok:
        gecici.unlink(missing_ok=True)
        return _dublaj_paketi(
            veri, klasor, hata_yaz(veri, None, f"{kayit['ad']} dublajı ekleme",
                                   f"'{kayit['ad']}' dublajı videoya eklenemedi: {hata_mesaji}"))
    try:
        os.replace(gecici, klasor / "proje.mp4")
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return _dublaj_paketi(veri, klasor, "Dublaj eklendi ama dosya yerine yazılamadı: "
                              + _ilk_satir(exc, 200))

    simdi = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    veri["ham_video"] = HAM_VIDEO_ADI
    veri["ekli_dublaj"] = kayit["ad"]
    veri["ekli_dil"] = kayit["dil"]
    # `proje.mp4` ham videodan yeniden kurulduğu için alanlar baştan yazılır: gömülü
    # altyazı kalkmıştır, "TAMAM" kalsaydı video yanlış anlatılmış olurdu.
    veri["ses_ekleme"] = "TAMAM"
    veri["ses_ekleme_bitti"] = simdi
    veri["altyazi_ekleme"] = "BEKLİYOR"
    veri["altyazi_ekleme_bitti"] = ""
    veri["ekli_altyazi"] = ""
    veri["durum"] = "tamam"
    dublaj_secimi_yaz(klasor, kayit["ad"])
    baslik = (f"'{kayit['ad']}' dublajı videoya eklendi: proje.mp4 = ham video + "
              f"{LANGUAGES.get(kayit['dil'], kayit['dil'])} sesi · seviye "
              f"%{ses_seviyesi(veri['ayarlar']['ses'].get('seviye')):g}.")
    veri["son_not"] = baslik
    not_ekle(veri, baslik)
    # Video ham videodan kurulduğu için müzik katmanı kaybolurdu; ekliyse geri uygulanır.
    ek = muzik_geri_uygula(veri, klasor)
    proje_yaz(veri)
    return _dublaj_paketi(
        veri, klasor, baslik + " " + sure_ozeti(veri) + ek +
        " Altyazı istiyorsan alttaki **Altyazı** panelinden bir kayıt seçip göm.",
        str(ses), dublaj_dosya_listesi(klasor, kayit))


def dil_videoya_ekle(ad, dil, altyazi_gom=False):
    """Eski ad: bir dili videoya ekler (kayıt adı = dil kodu olan dublaj).

    `altyazi_gom` açıksa o dilin **kayıtlı altyazısı** da gömülür; artık ikisi ayrı
    işlemdir, bu yüzden varsayılan kapalıdır (bkz. `dublaj_videoya_ekle`,
    `altyazi_videoya_ekle`).
    """
    paket = dublaj_videoya_ekle(ad, dil)
    if not altyazi_gom:
        return paket
    alt = altyazi_videoya_ekle(ad, dil)
    return (paket[0] + " " + alt[0],) + tuple(paket[1:])


# ── altyazı kayıtları · dile göre kaydet, listele, videoya göm ────────────────
def altyazi_listesi(ad):
    """Arayüz için kaydedilmiş altyazılar (dosyası diskte duranlar).

    21.10.2026: listede yalnızca dublajlarla üretilen altyazılar vardı; **ana dilin**
    altyazısı (seslendirmeyle üretilen `ses/seslendirme.srt`) hiç kaydedilmediği için
    bütün projelerde ana dil (ör. İngilizce) listede görünmüyordu. Dosya varsa ve ana dil
    kayıtlı değilse burada kendiliğinden kaydedilir.
    """
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return []
    _ana_dil_altyazisini_kaydet(klasor, veri)
    return altyazi_kayitlari(klasor)


def _ana_dil_altyazisini_kaydet(klasor, veri):
    kod = dil_kodu(((veri.get("ayarlar") or {}).get("ses") or {}).get("dil")) or ""
    srt = altyazi_dosyasi(klasor)
    if not kod or srt is None:
        return
    if any(k.get("ad") == kod or k.get("dil") == kod for k in altyazi_kayitlari(klasor)):
        return
    try:
        dosyadan_kaydet(klasor, srt, kod, kod, "anlatim")
    except Exception:       # liste okunurken kayıt hatası arayüzü düşürmesin
        pass


def altyazi_sec(ad, isim):
    """Üretim sayfasında seçilen altyazıyı projeye yaz; geçerli seçimi döndürür."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return altyazi_secimi_yaz(klasor, isim)


def _altyazi_kaynagi(klasor, veri, kod, isim):
    """Bir altyazı kaydının kaynağı: `(srt yolu, metin, süre, etiket)`.

    Sıra: **kaydın dublajının** altyazısı → aynı adlı dil dosyası → projenin kendi
    altyazısı (anlatım dili). Hiçbiri yoksa `srt` `None` döner ve çağıran altyazıyı
    metinden yazar (dublajın metni ve süresi buradan gelir).
    """
    kayit = dublaj_bul(klasor, isim)
    if kayit is not None:
        srt = dublaj_yolu(klasor, kayit, "altyazi") or dil_dosyasi(klasor, kayit["ad"], ".srt")
        metin_yolu = dublaj_yolu(klasor, kayit, "metin")
        metin = ""
        if metin_yolu is not None:
            try:
                metin = metin_yolu.read_text(encoding="utf-8", errors="replace")
            except OSError:
                metin = ""
        ses = dublaj_yolu(klasor, kayit)
        sure = float(kayit.get("sure") or 0) or (dosya_suresi(ses) if ses else 0.0)
        return srt, metin or (veri.get("metin") or ""), sure, "dublaj"
    # Dublaj kaydı yok: proje kendi dilinde altyazı istiyor demektir.
    sure = float((veri.get("ses") or {}).get("sure") or 0)
    return altyazi_dosyasi(klasor), (veri.get("metin") or ""), sure, "anlatim"


def altyazi_kaydet(ad, dil, isim=""):
    """Bir dilin altyazısını **kendi başına kaydet** (dublaja iliştirilmez).

    Kaynak sırayla aranır: o adın dublajıyla birlikte üretilmiş `.srt`, yoksa
    projenin kendi altyazısı; ikisi de yoksa altyazı **metinden** yazılır (kelime
    zamanları uzunluğa göre tahmin edilir, hiçbir servise istek gitmez). Kaydedilen
    dosya `altyazi/<ad>.srt`tir ve videoya üretim sayfasından gömülür.
    """
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _altyazi_bos(hata)
    kod = dil_kodu(dil)
    if not kod:
        return _altyazi_paketi(veri, klasor, "Altyazı için geçerli bir dil seç.")
    kayit_ad = altyazi_kayit_adi(isim, kod)
    srt, metin, sure, etiket = _altyazi_kaynagi(klasor, veri, kod, kayit_ad)
    if srt is not None:
        kayit, sorun = dosyadan_kaydet(klasor, srt, kayit_ad, kod, etiket)
    else:
        kayit, sorun = metinden_kaydet(klasor, metin, sure, kayit_ad, kod,
                                       (veri["ayarlar"]["altyazi"] or {}).get("ayar"))
    if kayit is None:
        return _altyazi_paketi(veri, klasor, sorun)
    baslik = (f"'{kayit['ad']}' altyazısı kaydedildi · "
              + altyazi_kayit_ozeti(kayit) + ".")
    not_ekle(veri, baslik)
    proje_yaz(veri)
    dosyalar = [str(yol) for yol in (altyazi_yolu(klasor, kayit),
                                     altyazi_yolu(klasor, kayit, "vtt")) if yol is not None]
    return _altyazi_paketi(
        veri, klasor, baslik + " Videoya gömmek için aşağıdaki **Videoya göm** panelinden "
        "seç.", dosyalar)


def altyazi_secimi(ad):
    """Listede **seçili** altyazının adı (proje açılırken panele yazılır)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return altyazilari_tazele(klasor)["secim"]


def ekli_altyazi_adi(ad):
    """Videoya **gömülmüş** altyazının adı (yoksa boş metin): listedeki işaret için."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return ""
    return (veri.get("ekli_altyazi") or "").strip() if veri.get("altyazi_ekleme") == "TAMAM" else ""


def altyazi_sil(ad, isim):
    """Kayıtlı altyazıyı listeden ve diskten kaldır (videodaki gömme değişmez)."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _altyazi_bos(hata)
    silindi, kayit = altyazi_kaydini_sil(klasor, isim)
    if not silindi:
        return _altyazi_paketi(veri, klasor, f"'{isim}' adlı altyazı listede yok.")
    baslik = f"'{kayit['ad']}' altyazısı silindi."
    not_ekle(veri, baslik)
    proje_yaz(veri)
    return _altyazi_paketi(veri, klasor, baslik)


def altyazi_videoya_ekle(ad, isim):
    """Kayıtlı bir altyazıyı `proje.mp4`e göm (hard sub); ses akışı korunur.

    Videoda zaten gömülü bir altyazı varsa önce **ham videodan yeniden kurmak**
    gerekir (üst üste gömme iki altyazı yazardı): ekli dublaj ve müzik geri uygulanır,
    sonra yeni altyazı gömülür.
    """
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _altyazi_bos(hata)
    if not FFMPEG.ffmpeg():
        return _altyazi_paketi(veri, klasor, "ffmpeg bulunamadı; altyazı gömülemedi.")
    kayit = altyazi_bul(klasor, isim)
    altyazi = altyazi_yolu(klasor, kayit) if kayit else None
    if altyazi is None:
        return _altyazi_paketi(
            veri, klasor, f"'{isim or '—'}' adlı kayıtlı altyazı yok. Listeden birini seç "
                          "ya da yukarıdaki panelde kaydet.")
    video = klasor / "proje.mp4"
    if not video.is_file():
        return _altyazi_paketi(veri, klasor, "`proje.mp4` yok; önce adımlar birleştirilmeli.")
    onceki = ""
    if veri.get("altyazi_ekleme") == "TAMAM":
        # Eski gömmeyi kaldır: video ham videodan kurulur, ses ve müzik geri gelir.
        onceki = (veri.get("ekli_altyazi") or "").strip()
        geri = _gomuyu_kaldir(klasor, veri)
        if geri:
            return _altyazi_paketi(veri, klasor, geri)

    gecici = klasor / "proje-altyazi.gecici.mp4"
    gecici.unlink(missing_ok=True)
    genislik, yukseklik = FFMPEG.video_olcusu(video)
    if not yukseklik:
        olcu = bicim_bilgisi(gorsel_kaynak_bicim(veri))
        genislik, yukseklik = olcu["genislik"], olcu["yukseklik"]
    try:
        satirlar = altyazi.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        satirlar = None
    stil, yazi, alt = altyazi_olcu(genislik, yukseklik, altyazi_ayari(veri), satirlar)
    # Altyazı, ffmpeg **altyazı klasöründe** çalıştırılarak göreli adla verilir;
    # böylece Windows'ta `C:` iki noktası ve ters bölü kaçış sorunu oluşmaz.
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(video), "-vf", f"subtitles={altyazi.name}:force_style='{stil}'",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "copy", str(gecici)]
    ok, hata_mesaji = FFMPEG.calistir(komut, cwd=altyazi.parent)
    if not ok:
        gecici.unlink(missing_ok=True)
        return _altyazi_paketi(
            veri, klasor, hata_yaz(veri, None, "Altyazı gömme",
                                   f"'{kayit['ad']}' altyazısı gömülemedi: {hata_mesaji}"
                                   " (ffmpeg derlemesinde `subtitles`/libass gerekir)."))
    try:
        os.replace(gecici, video)
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return _altyazi_paketi(veri, klasor, "Altyazı gömüldü ama dosya yerine yazılamadı: "
                               + _ilk_satir(exc, 200))
    veri["altyazi_ekleme"] = "TAMAM"
    veri["altyazi_ekleme_bitti"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    veri["ekli_altyazi"] = kayit["ad"]
    veri["durum"] = "tamam"
    altyazi_secimi_yaz(klasor, kayit["ad"])
    baslik = (f"'{kayit['ad']}' altyazısı videoya gömüldü ({genislik}×{yukseklik} tuvalde "
              f"yazı {yazi} px, alt boşluk {alt} px).")
    veri["son_not"] = baslik
    not_ekle(veri, baslik + (f" Önceki gömme ('{onceki}') kaldırılmıştı." if onceki else ""))
    proje_yaz(veri)
    dosyalar = [str(yol) for yol in (altyazi, altyazi_yolu(klasor, kayit, "vtt"))
                if yol is not None]
    return _altyazi_paketi(veri, klasor, baslik + " " + sure_ozeti(veri), dosyalar)


def _gomuyu_kaldir(klasor, veri):
    """Videodaki gömülü altyazıyı kaldır: ham videodan kur, dublaj ve müziği geri ver.

    Dönüş boş metin ise iş tamamdır; doluysa hata mesajıdır.
    """
    ham, mesaj = ham_videoyu_hazirla(klasor, veri)
    if ham is None:
        return mesaj
    gecici = klasor / "proje-yenile.gecici.mp4"
    gecici.unlink(missing_ok=True)
    ses = ekli_dublaj_dosyasi(klasor, veri)
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(ham)]
    if ses is not None:
        komut += ["-i", str(ses), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
        if anlatim_suzgeci(veri):
            komut += ["-af", anlatim_suzgeci(veri)]
        komut += ["-c:a", "aac", "-b:a", "192k"]
    else:
        komut += ["-c:v", "copy", "-an"]
    ok, hata_mesaji = FFMPEG.calistir(komut + [str(gecici)], cwd=klasor)
    if not ok:
        gecici.unlink(missing_ok=True)
        return "Eski gömülü altyazı kaldırılamadı: " + _ilk_satir(hata_mesaji, 200)
    try:
        os.replace(gecici, klasor / "proje.mp4")
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return "Video yerine yazılamadı: " + _ilk_satir(exc, 200)
    veri["altyazi_ekleme"] = "BEKLİYOR"
    veri["altyazi_ekleme_bitti"] = ""
    veri["ekli_altyazi"] = ""
    muzik_geri_uygula(veri, klasor)
    return ""


def ham_videoya_geri_don(ad):
    """Videoyu ham hâline döndür: ekli dublaj, altyazı ve müzik kalkar, kayıtlar durur."""
    veri, klasor, hata = _cok_dil_hedefi(ad)
    if hata:
        return _cok_dil_bos(hata)
    ham, mesaj = ham_videoyu_hazirla(klasor, veri)
    if ham is None:
        return _cok_dil_paketi(veri, mesaj)
    gecici = klasor / "proje-ham.gecici.mp4"
    gecici.unlink(missing_ok=True)
    try:
        shutil.copy2(ham, gecici)
        os.replace(gecici, klasor / "proje.mp4")
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return _cok_dil_paketi(veri, "Ham video geri getirilemedi: " + _ilk_satir(exc, 200))
    onceki = (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()
    veri["ses_ekleme"] = "BEKLİYOR"
    veri["ses_ekleme_bitti"] = ""
    veri["altyazi_ekleme"] = "BEKLİYOR"
    veri["altyazi_ekleme_bitti"] = ""
    veri["ekli_dil"] = ""
    veri["ekli_dublaj"] = ""
    veri["ekli_altyazi"] = ""
    # Müzik katmanı da kalkar: video ham (sessiz) hâline döndüğü için müzik duyulmaz.
    # Kaydedilmiş müzik dosyaları silinmez, listeden yeniden eklenir.
    veri["muzik_ekleme"] = "BEKLİYOR"
    veri["muzik_ekleme_bitti"] = ""
    veri["muzikler"] = []
    # Ses efekti de kalkar (kayıt silinmez; yalnızca "videoda" işareti kaldırılır).
    efekt_vardi = ekli_efekt(klasor)[0] is not None
    if efekt_vardi:
        try:
            ekli_efekti_yaz(klasor, "")
        except OSError:
            pass
    veri["ham_video"] = HAM_VIDEO_ADI
    veri["durum"] = "tamam"
    baslik = ("proje.mp4 ham videoya döndürüldü"
              + (f": '{onceki}' dublajının sesi ve gömülü altyazı kaldırıldı." if onceki
                 else "."))
    veri["son_not"] = baslik
    not_ekle(veri, baslik + " Ekli müzik" + (" ve ses efektleri" if efekt_vardi else "")
             + " de kaldırıldı.")
    proje_yaz(veri)
    return _cok_dil_paketi(
        veri, baslik + " Video yeniden sessiz ve altyazısız. Kaydedilmiş dublaj, altyazı, "
        "müzik ve ses efektleri silinmedi: istediğini alttaki panellerden yeniden "
        "ekleyebilirsin.")
