"""Katmanlar: dublaj, müzik, altyazı, ses efekti ve StudioFlow'un sonuç videosu.

StudioFlow'un proje sayfasındaki **Dublaj · Müzik · Altyazı · Efekt** bölümlerinin ve
önizleme altındaki **Sesi videoya ekle · Altyazıyı videoya ekle · Ham videoya geri dön**
düğmelerinin karşılığı. Her işlem StudioFlow'un kendi işlevini çağırır
(`studioflow.proje.katmanlar`); kayıtlar ve `proje.txt` StudioFlow'daki gibi yazılır.

Uzun süren ya da videoyu yeniden kuran işlemler arka plan işidir (`uretim.islem`): editörde
aynı anda tek iş çalışır, ilerleme üst çubukta görünür. Yalnızca seçim yazan işlemler
(müziğin işaret sırası, tekrar/ducking tercihi, seçili dublaj/altyazı/efekt) eşzamanlıdır.

**Video | Ses** anahtarı (`mod`): Video'da katman `proje.mp4`'e eklenir; Ses'te video
değişmez, katman yalnızca `youtube/<dil>/ses.mp3`'e yazılır (YouTube'un çok dilli ses
izleri için; bkz. `ses_ciktisi`).
"""
import hashlib
import re
import shutil
from pathlib import Path

from sunucu import ayar
from sunucu import disa_aktar, uretim, veri
from studioflow.altyazi import gorunum
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.proje import depo
from studioflow.proje.dosya import proje_oku
from studioflow.proje.katmanlar import (altyazilar, diller, dublaj, efekt_duzenleme,
                                        efekt_ekleme, efektler, muzik, ses_ciktisi, ses_ekleme)
from studioflow.proje.katmanlar.efekt_hazirlama import efekt_hazirla
from studioflow.proje.katmanlar.muzik_uretimi import URETIM_KLASORU, muzik_uret, proje_baglami

GECICI = ayar.GECICI
VIDEO, SES = "video", "ses"


def _temiz(metin):
    return re.sub(r"\*\*|`", "", str(metin or "")).strip()


def _klasor(ad):
    klasor = depo.guvenli_klasor(ad)
    if klasor is None or not klasor.is_dir():
        raise veri.ProjeYok(ad)
    return klasor


def _servis(ad):
    """"Sahne prompt'larının yapay zekâsı" (StudioFlow çeviri/efekt/müzik için de bunu kullanır)."""
    durum = proje_oku(_klasor(ad)) or {}
    return ((durum.get("ayarlar") or {}).get("video") or {}).get("ai") or ""


def dosya_adresi(ad, yol):
    """Proje klasöründeki (mutlak ya da göreli) dosyanın `/medya` adresi; `http` aynen döner."""
    if not yol:
        return None
    yol = str(yol)
    if yol.startswith("http"):
        return yol
    klasor = _klasor(ad)
    try:
        goreli = Path(yol).resolve().relative_to(klasor.resolve()) if Path(yol).is_absolute() else Path(yol)
    except ValueError:
        return gecici_adresi(yol)
    return veri.medya_adresi(ad, goreli.as_posix())


def gecici_adresi(yol):
    """Proje dışındaki bir dosyayı (önizleme, test sesi) `.gecici/`e kopyala; adresini ver."""
    kaynak = Path(yol)
    if not kaynak.is_file():
        return None
    GECICI.mkdir(parents=True, exist_ok=True)
    ad = hashlib.sha1(f"{kaynak.resolve()}{kaynak.stat().st_mtime}".encode()).hexdigest()[:16]
    hedef = GECICI / f"{ad}{kaynak.suffix.lower()}"
    if not hedef.is_file():
        shutil.copyfile(kaynak, hedef)
    return f"/gecici/{hedef.name}"


def _is(ad, tur, baslik, fonk, sonuc_al=None):
    _klasor(ad)
    return uretim.islem(ad, tur, baslik, fonk, sonuc_al=sonuc_al)


def _modlu(mod, video_fonk, ses_fonk):
    return ses_fonk if mod == SES else video_fonk


def _disa_aktarima_yansit(ad, **degisiklik):
    """"Videoya ekle / göm": katman projenin videosuna (zaman çizelgesi ve Dışa aktar)
    girer. Hazır seslendirme ve toplam süreyle çalışır; bitmiş video (proje.mp4) gerekmez.
    Boş değer katmanı çıkarır."""
    ayar_ = disa_aktar.ayar_oku(ad)
    isaret = dict(ayar_["isaret"])
    for iz, deger in degisiklik.items():
        ayar_[iz] = deger
        isaret[iz] = bool(deger)
    ayar_["isaret"] = isaret
    disa_aktar.ayar_yaz(ad, ayar_)


def _video_var(ad):
    return (_klasor(ad) / "proje.mp4").is_file()


def _video_gerekli(ad, mod):
    """Yalnızca StudioFlow videosunun kendisini değiştiren işlemler (sesi ekle, ham videoya
    dön, altyazıyı yeniden kur) proje.mp4 ister."""
    if mod != SES and not _video_var(ad):
        raise uretim.UretimHatasi(
            "StudioFlow videosu (proje.mp4) henüz yok; bu işlem proje bitince yapılabilir.")


def _ekle_isi(ad, tur, baslik, mesaj, studioflow_fonk=None):
    """Katmanı projeye ekleyen iş: önce zaman çizelgesi/Dışa aktar (anında), StudioFlow
    videosu varsa ardından ona da StudioFlow'un kendi işleviyle."""
    def akis():
        yield (mesaj,)
        if studioflow_fonk is not None and _video_var(ad):
            yield ("StudioFlow videosuna (proje.mp4) da ekleniyor…",)
            yield studioflow_fonk()
    return _is(ad, tur, baslik, akis)


# ── Dublaj ─────────────────────────────────────────────────────────────────────
def dublajlar(ad):
    _klasor(ad)
    ekli = diller.ekli_dublaj_adi(ad)
    secili = diller.dublaj_secimi(ad)
    return [{"ad": k["ad"], "dil": k.get("dil", ""), "ozet": _temiz(dublaj.dublaj_ozeti(k, k["ad"] == ekli)),
             "ses": veri.medya_adresi(ad, k.get("dosya")), "altyazi": veri.medya_adresi(ad, k.get("altyazi")),
             "ekli": k["ad"] == ekli, "secili": k["ad"] == (secili or ekli)}
            for k in diller.dublaj_listesi(ad)]


def dublaj_uret(ad, g):
    edge_ses = g.get("edge_ses") or ""
    return _is(ad, "dublaj", f"Dublaj · {g.get('dil') or 'en'}", lambda: diller.dil_sesi_uret(
        ad, g.get("dil") or "en", bool(g.get("cevir", True)), g.get("provider") or "gemini",
        edge_ses, g.get("gemini_model") or "", g.get("gemini_ses") or "Charon",
        int(g.get("hiz") or 0), int(g.get("ton") or 0), (g.get("isim") or "").strip(),
        bool(g.get("sahneye_gore")), g.get("ceviri_ai") or "gemini"))


def dublaj_sil(ad, isim):
    return _is(ad, "dublaj_sil", f"Dublaj sil · {isim}", lambda: diller.dublaj_sil(ad, isim))


def dublaj_sec(ad, isim):
    _klasor(ad)
    diller.dublaj_sec(ad, isim)
    return {"secili": isim}


def dublaj_ekle(ad, isim, seviye, mod=VIDEO):
    if not isim:
        raise uretim.UretimHatasi("Önce listeden bir dublaj seç.")
    if mod == SES:
        return _is(ad, "dublaj_ekle", f"Dublajı sese ekle · {isim}",
                   lambda: ses_ciktisi.dublaj_sesi(ad, isim, seviye))
    _disa_aktarima_yansit(ad, dublaj=isim)
    return _ekle_isi(ad, "dublaj_ekle", f"Dublajı videoya ekle · {isim}",
                     f"✅ '{isim}' dublajı projeye eklendi: zaman çizelgesinde duyulur, Dışa aktar'la videoya girer.",
                     lambda: diller.dublaj_videoya_ekle(ad, isim, seviye))


# ── Müzik ──────────────────────────────────────────────────────────────────────
def muzikler(ad):
    klasor = _klasor(ad)
    durum = muzik.muzik_durumu(ad) or {}
    secim = [str(x) for x in durum.get("secim") or []]
    return {"kayitlar": [{"ad": k["ad"], "ozet": _temiz(muzik.muzik_ozeti(k)),
                          "ses": veri.medya_adresi(ad, k.get("dosya")), "sure": k.get("sure"),
                          "sira": secim.index(k["ad"]) + 1 if k["ad"] in secim else 0}
                         for k in muzik.muzik_listesi(ad)],
            "secim": secim, "tekrarla": bool(durum.get("tekrarla")),
            "ducking": True if durum.get("ducking") is None else bool(durum.get("ducking")),
            # Projeye eklenmiş müzik var mı (kayıtlı müzik silinmiş olsa da): "Müziği kaldır"
            # düğmesi buna göre gösterilir (21.10.2026: liste boşalınca düğme kayboluyordu).
            "ekli": _muzik_ekli_mi(ad, klasor)}


def _muzik_ekli_mi(ad, klasor):
    if muzik.sabit_muzik(klasor)[0] is not None:
        return True
    kayit = proje_oku(klasor) or {}
    if (kayit.get("muzik_ekleme") or "") == "TAMAM" or kayit.get("muzikler"):
        return True
    ayar_ = disa_aktar.ayar_oku(ad)
    return bool(ayar_.get("isaret", {}).get("muzik") and ayar_.get("muzik"))


def muzik_suresi(yol):
    sure, not_metni = muzik.muzik_suresi(yol)
    return {"sure": sure, "not": _temiz(not_metni)}


def muzik_yz_uret(ad, tarif, sure, bpm):
    klasor = _klasor(ad)
    baglam = proje_baglami(ad)
    if not (tarif or "").strip() and not baglam:
        raise uretim.UretimHatasi("Projenin anlatımı okunamadı; müziği kendin tarif et.")
    hedef = klasor / depo.CALISMA_KLASORU / URETIM_KLASORU
    servis = _servis(ad)

    def akis():
        depo.calismayi_temizle(klasor, URETIM_KLASORU)
        for olay in muzik_uret(tarif, sure, bpm, hedef, baglam, servis):
            if olay[0] == "durum":
                yield ("⏳ " + olay[1], None)
            elif olay[0] == "hata":
                yield ("❌ " + olay[1], None)
            else:
                _tur, yol, isim, ozet = olay
                yield (f"✅ Müzik üretildi. {ozet} Dinle, gerekirse kırp, sonra Müziği kaydet.",
                       {"yol": str(yol), "ad": isim})

    def sonuc(paket):
        if paket[1]:
            yol = paket[1]["yol"]
            return {**paket[1], "adres": dosya_adresi(ad, yol), **muzik_suresi(yol)}
        return None
    return _is(ad, "muzik_yz", "Müzik üret · Lyria", akis, sonuc)


def muzik_kaydet(ad, g):
    yol = g.get("yol") or ""
    if not yol or not Path(yol).is_file():
        raise uretim.UretimHatasi("Önce bir müzik dosyası yükle ya da üret.")

    # Kaydetmek yalnızca kaydeder: müzik Müzik panelinin listesinde durur; videoya
    # "Videoya ekle" ile girer.
    return _is(ad, "muzik_kaydet", f"Müziği kaydet · {g.get('isim') or ''}".strip(" ·"),
               lambda: muzik.muzik_kaydet(ad, yol, g.get("isim") or "", g.get("seviye", 10),
                                          g.get("bas") or 0, g.get("bit") or 0,
                                          g.get("giris") or 0, g.get("cikis") or 0))


def muzik_sil(ad, isim):
    return _is(ad, "muzik_sil", f"Müzik sil · {isim}", lambda: muzik.muzik_sil(ad, isim))


def muzik_secim(ad, secim):
    _klasor(ad)
    muzik.muzik_secimini_yaz(ad, [str(x) for x in secim or []])
    return muzikler(ad)


def muzik_tercih(ad, tekrarla=None, ducking=None):
    _klasor(ad)
    if tekrarla is not None:
        muzik.muzik_tekrarini_yaz(ad, bool(tekrarla))
    if ducking is not None:
        muzik.muzik_duckingi_yaz(ad, bool(ducking))
    return muzikler(ad)


def muzik_ekle(ad, mod=VIDEO):
    m = muzikler(ad)
    if not m["secim"]:
        raise uretim.UretimHatasi("Önce videoya girecek müzikleri işaretle.")
    if mod == SES:
        return _is(ad, "muzik_ekle", "Müziği sese ekle",
                   lambda: ses_ciktisi.muzik_sesi(ad, m["secim"], m["tekrarla"], m["ducking"]))
    # Müzik hazır seslendirmeye ve toplam süreye göre ayarlanır: tekrarla açıksa video
    # sonuna kadar baştan çalar, ducking açıksa anlatım konuşurken kısılır.
    konusma, konusma_adi = _isaretli_konusma(ad)
    _disa_aktarima_yansit(ad, muzik=m["secim"])
    ayar_metni = (("tekrar açık · " if m["tekrarla"] else "tekrar kapalı · ")
                  + (f"ducking: {konusma_adi}" if m["ducking"] else "ducking kapalı"))
    return _ekle_isi(ad, "muzik_ekle", "Müziği videoya ekle",
                     f"✅ Müzik projeye eklendi ({', '.join(m['secim'])} · {ayar_metni}): zaman "
                     "çizelgesinde çalar, Dışa aktar'la videoya girer.",
                     lambda: muzik.muzik_videoya_ekle(ad, m["secim"], m["tekrarla"], m["ducking"],
                                                      konusma))


def _isaretli_konusma(ad):
    """Müzik eklenirken zaman çizelgesinde işaretli konuşma (kullanıcı kararı, 21.10.2026).

    Dönüş: `(muzik_videoya_ekle'nin konusma değeri, mesajdaki ad)`. Dublaj işaretliyse ve
    seçili dublaj kayıtlıysa o dublaj; değilse (seslendirme işaretli, ikisi birden işaretli
    ya da hiçbiri) projenin ana dilindeki seslendirme. İki konuşma izi birden videoya
    girmez: iki dil üst üste konuşurdu.
    """
    ayar_ = disa_aktar.ayar_oku(ad)
    isaret = ayar_.get("isaret") or {}
    dublaj_ad = ayar_.get("dublaj") or ""
    dublaj_var = any(k["ad"] == dublaj_ad for k in diller.dublaj_listesi(ad))
    if isaret.get("dublaj") and dublaj_ad and dublaj_var and not isaret.get("seslendirme"):
        return f"dublaj:{dublaj_ad}", f"'{dublaj_ad}' dublajı"
    return "seslendirme", "seslendirme (ana dil)"


def muzik_kaldir(ad, mod=VIDEO):
    _klasor(ad)
    if mod == SES:
        return _is(ad, "muzik_kaldir", "Müziği sesten kaldır", lambda: ses_ciktisi.muzik_sesi_kaldir(ad))
    _disa_aktarima_yansit(ad, muzik=[])
    # Sabit müzik (dışa aktarma ve önizleme bunu çalar) her durumda kalkar; proje.mp4 yoksa
    # ya da müzik kaydı silinmişse de müzik projeden çıkmış olur.
    muzik.sabit_muzigi_sil(_klasor(ad))
    return _ekle_isi(ad, "muzik_kaldir", "Müziği kaldır", "✅ Müzik projeden çıkarıldı.",
                     lambda: muzik.muzikleri_kaldir(ad))


# ── Altyazı ────────────────────────────────────────────────────────────────────
def altyazilar_(ad):
    _klasor(ad)
    ekli = diller.ekli_altyazi_adi(ad)
    secili = diller.altyazi_secimi(ad)
    return [{"ad": k["ad"], "dil": k.get("dil", ""),
             "ozet": _temiz(altyazilar.altyazi_kayit_ozeti(k, k["ad"] == ekli)),
             "srt": veri.medya_adresi(ad, k.get("dosya")), "vtt": veri.medya_adresi(ad, k.get("vtt")),
             "ekli": k["ad"] == ekli, "secili": k["ad"] == (secili or ekli)}
            for k in diller.altyazi_listesi(ad)]


def altyazi_kaydet(ad, dil, isim=""):
    return _is(ad, "altyazi_kaydet", f"Altyazı kaydet · {dil}",
               lambda: diller.altyazi_kaydet(ad, dil or "en", (isim or "").strip()))


def altyazi_sil(ad, isim):
    return _is(ad, "altyazi_sil", f"Altyazı sil · {isim}", lambda: diller.altyazi_sil(ad, isim))


def altyazi_sec(ad, isim):
    _klasor(ad)
    diller.altyazi_sec(ad, isim)
    return {"secili": isim}


def altyazi_gom(ad, isim):
    if not isim:
        raise uretim.UretimHatasi("Önce listeden bir altyazı seç.")
    _disa_aktarima_yansit(ad, altyazi=isim)
    return _ekle_isi(ad, "altyazi_gom", f"Altyazıyı videoya göm · {isim}",
                     f"✅ '{isim}' altyazısı projeye eklendi: önizlemede görünür, Dışa aktar'la videoya yazılır.",
                     lambda: diller.altyazi_videoya_ekle(ad, isim))


def altyazi_yeniden(ad):
    """Videodaki altyazıyı projenin güncel görünüm ayarlarıyla baştan kur."""
    _video_gerekli(ad, VIDEO)
    durum = proje_oku(_klasor(ad)) or {}
    altyazi = (durum.get("ayarlar") or {}).get("altyazi") or None
    return _is(ad, "altyazi_yeniden", "Video altyazısını tekrar oluştur",
               lambda: ses_ekleme.videoya_altyazi_yeniden(ad, altyazi))


def altyazi_onizleme(bicim, altyazi, zemin=None):
    """Altyazı görünümünün tek karelik önizlemesi (videoya gömülecek hâlin küçüğü)."""
    yol, not_metni = gorunum.altyazi_onizleme(bicim, altyazi, zemin)
    return {"adres": gecici_adresi(yol) if yol else None, "not": _temiz(not_metni)}


# ── Ses efektleri ──────────────────────────────────────────────────────────────
def efektler_(ad):
    _klasor(ad)
    ekli = efekt_ekleme.ekli_efekt_adi(ad)
    secili = efekt_ekleme.efekt_secimi(ad)
    return [{"ad": k["ad"], "ozet": _temiz(efektler.efekt_ozeti(k, k["ad"] == ekli)),
             "ses": veri.medya_adresi(ad, k.get("dosya")), "ekli": k["ad"] == ekli,
             "secili": k["ad"] == (secili or ekli)}
            for k in efekt_ekleme.efekt_listesi(ad)]


def efekt_sahneleri(ad):
    """Manuel hazırlama için videosu üretilmiş sahneler."""
    _klasor(ad)
    return [{"index": s["index"], "bas": s["bas"], "sure": s["sure"], "metin": s.get("metin") or ""}
            for s in efekt_ekleme.efekt_sahne_listesi(ad)]


def efekt_hazirla_(ad, yontem, isim="", istekler=None):
    servis = _servis(ad)

    def akis():
        satirlar = []
        for olay in efekt_hazirla(ad, yontem, istekler, isim, servis):
            if olay[0] == "durum":
                satirlar.append(olay[1])
                yield ("⏳ " + olay[1],)
            elif olay[0] == "hata":
                yield ("❌ " + olay[1],)
                return
            else:
                yield ("✅ " + olay[2],)
                return
    baslik = "Ses efektleri · " + ("yapay zekâ" if yontem == "yapay_zeka" else "manuel")
    return _is(ad, "efekt", baslik, akis)


def efekt_sil(ad, isim):
    return _is(ad, "efekt_sil", f"Efekt sil · {isim}", lambda: efekt_ekleme.efekt_sil(ad, isim))


def efekt_sec(ad, isim):
    _klasor(ad)
    efekt_ekleme.efekt_sec(ad, isim)
    return {"secili": isim}


def efekt_gom(ad, isim, seviye):
    if not isim:
        raise uretim.UretimHatasi("Önce listeden bir efekt kaydı seç.")
    _disa_aktarima_yansit(ad, efekt=isim)
    return _ekle_isi(ad, "efekt_gom", f"Ses efektlerini göm · {isim}",
                     f"✅ '{isim}' ses efektleri projeye eklendi: zaman çizelgesinde duyulur, Dışa aktar'la videoya girer.",
                     lambda: efekt_ekleme.efekt_videoya_ekle(ad, isim, seviye))


def efekt_kaldir(ad):
    _klasor(ad)
    _disa_aktarima_yansit(ad, efekt="")
    return _ekle_isi(ad, "efekt_kaldir", "Ses efektlerini kaldır", "✅ Ses efektleri projeden çıkarıldı.",
                     lambda: efekt_ekleme.efektleri_kaldir(ad))


def efekt_duzenleme_listesi(ad, kayit):
    """✏️ Sesleri düzenle: sahne sırasıyla her ses (dinleme adresiyle)."""
    _klasor(ad)
    sahneler, mesaj = efekt_duzenleme.duzenleme_sahneleri(ad, kayit)
    sonuc = []
    for s in sorted(sahneler, key=lambda x: x["index"]):
        sonuc.append({"index": s["index"], "bas": s["bas"], "metin": s.get("metin") or "",
                      "katmanlar": [{"sira": k["sira"], "ad": k.get("ad") or "",
                                     "etiket": k.get("etiket") or "", "tur": k.get("tur") or "eylem",
                                     "bas": k.get("bas") or 0.0, "adres": dosya_adresi(ad, k.get("dosya"))}
                                    for k in s["katmanlar"]]})
    return {"sahneler": sonuc, "mesaj": _temiz(mesaj)}


def efekt_bul(ad, sorgu, index, tur="eylem"):
    """🤖 Bul: isteğe uyan CC0 sesler (en iyisi başta). Eşzamanlıdır (birkaç saniye)."""
    _klasor(ad)
    adaylar, mesaj = efekt_duzenleme.yz_ses_bul(ad, sorgu, index, tur, _servis(ad))
    return {"adaylar": adaylar, "mesaj": _temiz(mesaj)}


def efekt_onayla(ad, kayit, index, sira, aday, tur="eylem", bas=0.0, etiket=""):
    return _is(ad, "efekt_onay", f"Sahne {index} · sesi değiştir",
               lambda: efekt_duzenleme.katman_koy(ad, kayit, int(index), int(sira or 0), aday,
                                                  tur or "eylem", float(bas or 0), etiket or ""))


# ── Sonuç videosu (StudioFlow'un proje.mp4'ü) ──────────────────────────────────
def sonuc(ad):
    klasor = _klasor(ad)
    durum = proje_oku(klasor) or {}
    dublaj_ekli = (durum.get("ekli_dublaj") or durum.get("ekli_dil") or "").strip()
    video = veri.medya_adresi(ad, "proje.mp4")
    katmanlar = [
        ("Seslendirme", durum.get("ses_ekleme") == "TAMAM" and not dublaj_ekli),
        ("Dublaj" + (f" · {dublaj_ekli}" if dublaj_ekli else ""), bool(dublaj_ekli)),
        ("Altyazı", durum.get("altyazi_ekleme") == "TAMAM"),
        ("Müzik", durum.get("muzik_ekleme") == "TAMAM" and bool(durum.get("muzikler"))),
        ("Ses efekti", efektler.ekli_efekt(klasor)[0] is not None),
    ] if video else []
    ses_dosyasi = ses_ciktisi.son_ses_dosyasi(ad)
    return {"video": video,
            "katmanlar": [{"ad": a, "var": v} for a, v in katmanlar],
            "ses_katmanlari": [{"ad": a, "var": v} for a, v in (ses_ciktisi.ses_katmanlari(ad) or [])],
            "ses": dosya_adresi(ad, ses_dosyasi) if ses_dosyasi else None,
            "ses_seviye": ((durum.get("ayarlar") or {}).get("ses") or {}).get("seviye", 100)}


def ses_ekle(ad, seviye, mod=VIDEO):
    _video_gerekli(ad, mod)
    fonk = _modlu(mod, ses_ekleme.videoya_ses_ekle, ses_ciktisi.seslendirme_sesi)
    return _is(ad, "ses_ekle", "Seslendirmeyi " + ("sese" if mod == SES else "videoya") + " ekle",
               lambda: fonk(ad, seviye))


def altyazi_ekle(ad):
    _video_gerekli(ad, VIDEO)
    return _is(ad, "altyazi_ekle", "Altyazıyı videoya ekle", lambda: ses_ekleme.videoya_altyazi_ekle(ad))


def geri_don(ad, mod=VIDEO):
    _video_gerekli(ad, mod)
    fonk = _modlu(mod, diller.ham_videoya_geri_don, ses_ciktisi.sesi_sifirla)
    return _is(ad, "geri_don", "Sesi sıfırla" if mod == SES else "Ham videoya geri dön", lambda: fonk(ad))


def video_sesi_mp3(ad):
    """Sonuç videosunun sesi (anlatım/dublaj + müzik + efekt) tek MP3 olarak."""
    klasor = _klasor(ad)
    video = klasor / "proje.mp4"
    if not video.is_file():
        raise uretim.UretimHatasi("Bu projenin sonuç videosu (proje.mp4) henüz yok.")
    if not FFMPEG.ffmpeg():
        raise uretim.UretimHatasi("ffmpeg bulunamadı; ses çıkarılamadı.")
    hedef = klasor / depo.CALISMA_KLASORU / "ses-indir" / f"{klasor.name}-ses.mp3"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    ok, mesaj = FFMPEG.calistir([FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                                 "-i", str(video), "-map", "0:a:0", "-vn", "-c:a", "libmp3lame",
                                 "-b:a", "192k", str(hedef)])
    if not ok:
        raise uretim.UretimHatasi("Ses çıkarılamadı (videoda ses izi olmayabilir): " + str(mesaj))
    return {"adres": dosya_adresi(ad, hedef)}
