"""Müzik: kayıt, kırpma, seviye, karışım, videoya ekleme/kaldırma."""
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir, sayi as _sayi
from studioflow.proje.depo import adim_suresi, kayit_adi, proje_adim_saniyesi
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.dosya_yollari import (
    anlatim_suzgeci, muzik_klasoru, muzik_liste_yolu, ses_dosyasi, sure_metni, sure_ozeti)
from studioflow.proje.katmanlar.dublaj import ekli_dublaj_dosyasi
from studioflow.proje.katmanlar.efektler import ekli_efekt
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.ilerleme import arayuz_paketi, bos_ilerleme_html
from studioflow.proje.sabitler import (
    MUZIK_KARARTMA_SINIR, MUZIK_KAYNAK_KLASORU, MUZIK_KLASORU,
    MUZIK_DUCKING_ATAK, MUZIK_DUCKING_BIRAKMA, MUZIK_DUCKING_ESIK, MUZIK_DUCKING_ORAN,
    MUZIK_SEVIYE_SINIR, MUZIK_VARSAYILAN_DUCKING, MUZIK_VARSAYILAN_KARARTMA,
    MUZIK_VARSAYILAN_SEVIYE)
from studioflow.proje.yeniden_deneme import hata_yaz


def muzik_adi(deger):
    """Müzik adını dosya adına çevir: geçersiz karakterler atılır, boşluk `-` olur."""
    return kayit_adi(deger, "muzik")


def _karartma(deger):
    """Karartma süresini doğrula: `MUZIK_KARARTMA_SINIR` aralığına çekilir."""
    sayi = max(MUZIK_KARARTMA_SINIR[0], _sayi(deger, MUZIK_VARSAYILAN_KARARTMA, float))
    return round(min(sayi, MUZIK_KARARTMA_SINIR[1]), 2)


def _muzik_kaydi(kayit):
    """Tek müzik kaydını güvenli değerlere indirge (bozuk alan varsayılana düşer)."""
    return {"ad": muzik_adi(kayit.get("ad")),
            "dosya": str(kayit.get("dosya") or "").replace("\\", "/"),
            "kaynak": str(kayit.get("kaynak") or "").replace("\\", "/"),
            "sure": max(0.0, _sayi(kayit.get("sure"), 0.0, float)),
            "seviye": min(max(_sayi(kayit.get("seviye"), MUZIK_VARSAYILAN_SEVIYE),
                              MUZIK_SEVIYE_SINIR[0]), MUZIK_SEVIYE_SINIR[1]),
            "bas": max(0.0, _sayi(kayit.get("bas"), 0.0, float)),
            "bit": max(0.0, _sayi(kayit.get("bit"), 0.0, float)),
            "giris_karartma": _karartma(kayit.get("giris_karartma")),
            "cikis_karartma": _karartma(kayit.get("cikis_karartma")),
            "tarih": str(kayit.get("tarih") or "")}


def _muzik_durumu(klasor):
    """Kalıcı müzik durumu: `{"parcalar": [...], "tekrarla": bool, "ducking": bool, "secim": [...]}`."""
    try:
        ham = json.loads(muzik_liste_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = {}
    if isinstance(ham, list):        # yalnızca parça listesi tutan eski/yalin biçim
        ham = {"parcalar": ham}
    if not isinstance(ham, dict):
        ham = {}
    parcalar = [_muzik_kaydi(kayit) for kayit in (ham.get("parcalar") or [])
                if isinstance(kayit, dict) and kayit.get("ad")]
    adlar = {kayit["ad"] for kayit in parcalar}
    secim = [str(ad).strip() for ad in (ham.get("secim") or []) if str(ad).strip()]
    return {"parcalar": parcalar, "tekrarla": bool(ham.get("tekrarla")),
            # Ducking anahtarı yazmayan eski kayıtlarda varsayılan açıktır.
            "ducking": MUZIK_VARSAYILAN_DUCKING if ham.get("ducking") is None
            else bool(ham.get("ducking")),
            "secim": [ad for ad in dict.fromkeys(secim) if ad in adlar]}


def _muzik_durumu_yaz(klasor, durum):
    """Müzik durumunu diske yaz (yarım dosya kalmasın diye önce geçiciye)."""
    hedef = muzik_klasoru(klasor)
    hedef.mkdir(parents=True, exist_ok=True)
    gecici = muzik_liste_yolu(klasor).with_suffix(".gecici")
    gecici.write_text(json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, muzik_liste_yolu(klasor))


def _muzik_liste(klasor):
    """Dosyası diskte duran kayıtlar (kayıt sırası korunur)."""
    return [kayit for kayit in _muzik_durumu(klasor)["parcalar"]
            if (klasor / kayit["dosya"]).is_file()]


def _muzik_hedefi(ad):
    """Müzik işlemlerinin ortak ön kontrolü: `(veri, klasör, hata mesajı)`."""
    return proje_hedefi(ad, "müzik ekle",
                        "Müzik için önce bir proje seç ya da proje adını yaz.")


def muzik_durumu(ad):
    """Arayüz için müzik durumu: parçalar (dosyası duranlar), tekrar tercihi, seçim."""
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return {"parcalar": [], "tekrarla": False, "secim": []}
    durum = _muzik_durumu(klasor)
    durum["parcalar"] = _muzik_liste(klasor)
    return durum


def muzik_listesi(ad):
    """Arayüz için kaydedilmiş müzikler (dosyası duran kayıtlar, kayıt sırasıyla)."""
    return muzik_durumu(ad)["parcalar"]


def muzik_ozeti(kayit, sira=0):
    """Liste satırının özeti: sıra · süre · seviye · varsa kırpma ve karartma."""
    parcalar = [f"**{sira}.**" if sira else "", sure_metni(kayit.get("sure")),
                f"%{kayit.get('seviye')}"]
    bas = float(kayit.get("bas") or 0)
    bit = float(kayit.get("bit") or 0)
    if bas > 0 or bit > 0:
        parcalar.append(f"kırpma {sure_metni(bas)}–{sure_metni(bit)} sn")
    giris, cikis = _karartma(kayit.get("giris_karartma")), _karartma(kayit.get("cikis_karartma"))
    if giris > 0 or cikis > 0:
        parcalar.append(f"karartma giriş {_karartma_metni(giris)} · "
                        f"çıkış {_karartma_metni(cikis)}")
    return " · ".join(parca for parca in parcalar if parca)


def _karartma_metni(saniye):
    """Karartma süresini kısa yaz: `0,5 sn` · `3 sn`."""
    return ("—" if not saniye else
            f"{_sayi(saniye, 0.0, float):g} sn".replace(".", ","))


def muzik_suresi(dosya):
    """Yüklenen müziğin süresi ve kırpma notu. Dönüş: `(saniye, not)`.

    Arayüz bu süreyi kırpma kaydırıcılarının sınırı yapar: yüklenen dosyanın
    bittiği yerin ötesini kırpmak anlamsız olurdu.
    """
    if not dosya:
        return 0.0, ("Müzik dosyası yükle: kırpma sınırları dosyanın süresine göre "
                     "ayarlanır.")
    if not Path(dosya).is_file():
        return 0.0, "Dosya okunamadı; yüklemeyi yenile."
    sure = FFMPEG.medya_suresi(dosya)
    if sure <= 0:
        return 0.0, ("Süre okunamadı (ffprobe gerekir); kırpma sınırlarını elle "
                     "ayarlayabilirsin.")
    return sure, (f"Dosya süresi **{sure_metni(sure)}** · kırpma sınırları bu süreye "
                  "göre ayarlandı (bitiş = dosyanın sonu).")


def muzik_secimini_yaz(ad, secim):
    """İşaretleme sırasını projeye yaz (proje henüz kurulmadıysa sessizce atlanır)."""
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return False
    durum = _muzik_durumu(klasor)
    adlar = {kayit["ad"] for kayit in durum["parcalar"]}
    durum["secim"] = [x for x in dict.fromkeys(muzik_adi(x) for x in (secim or []))
                       if x in adlar]
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError:
        return False
    return True


def muzik_tekrarini_yaz(ad, tekrarla):
    """Tekrarlama tercihini projeye yaz (proje yoksa sessizce atlanır)."""
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return False
    durum = _muzik_durumu(klasor)
    durum["tekrarla"] = bool(tekrarla)
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError:
        return False
    return True


def muzik_duckingi_yaz(ad, acik):
    """Ducking tercihini projeye yaz (proje yoksa sessizce atlanır)."""
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return False
    durum = _muzik_durumu(klasor)
    durum["ducking"] = bool(acik)
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError:
        return False
    return True


def _muzik_paketi(veri, mesaj):
    """Müzik panelinin çıktı paketi: panel alanları + proje görünümü."""
    durum = muzik_durumu(veri["slug"])
    return (mesaj, f"{time.time():.6f}", durum["secim"], durum["tekrarla"],
            durum["ducking"]) + arayuz_paketi(veri, mesaj)[1:]


def _muzik_bos(mesaj):
    """Proje seçilmemişse/hata varsa müzik panelinin boş paketi."""
    return (mesaj, "", [], False, MUZIK_VARSAYILAN_DUCKING, "", [], [], None,
            bos_ilerleme_html())


def muzik_kaydet(ad, dosya, isim, seviye, bas, bit, giris_karartma=0, cikis_karartma=0):
    """Yüklenen müziği **kırp**, ses seviyesini uygula ve projeye kaydet.

    Kaydedilen dosya (`muzik/<ad>.m4a`) son hâldir: kırpma ve seviye dosyaya işlenir,
    videoya eklerken yeniden ayar gerekmez. Aynı adla kaydetmek kaydı **günceller**;
    yüklenen kaynak `muzik/kaynak/` altında durduğu için seviye üst üste kısılmaz.

    **Karartma** (`giris_karartma` / `cikis_karartma`) dosyaya işlenmez, müziğin
    kaydına yazılır ve **videoya eklenirken** uygulanır: video müziği kesiyorsa
    karartma tam kesildiği yere oturur (bkz. `_muzik_bed`). Bu yüzden karartma
    süresini değiştirmek için müziği yeniden kaydetmek gerekmez.
    """
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return _muzik_bos(hata)
    if not dosya or not Path(dosya).is_file():
        return _muzik_paketi(veri, "Önce bir müzik dosyası yükle.")
    isim = muzik_adi(isim)
    if not isim:
        return _muzik_paketi(veri, "Müziğe bir ad yaz: liste bu adla görünür.")
    if not FFMPEG.ffmpeg():
        return _muzik_paketi(veri, "ffmpeg bulunamadı; müzik kaydedilemedi.")
    kaynak = Path(dosya)
    seviye = min(max(_sayi(seviye, MUZIK_VARSAYILAN_SEVIYE), MUZIK_SEVIYE_SINIR[0]),
                 MUZIK_SEVIYE_SINIR[1])
    sure_kaynak = FFMPEG.medya_suresi(kaynak)
    bas = max(0.0, _sayi(bas, 0.0, float))
    bit = max(0.0, _sayi(bit, 0.0, float))
    if sure_kaynak > 0:
        # Bitiş verilmemişse dosyanın sonuna kadar alınır (kırpma = yalnızca başlangıç).
        bit = min(bit, sure_kaynak) if bit > 0 else sure_kaynak
        bas = min(bas, max(0.0, bit - 0.1))
    else:
        bas = 0.0
        bit = 0.0
    kirpma = bit > bas + 0.05
    hedef = muzik_klasoru(klasor)
    dosya_hedef = hedef / f"{isim}.m4a"
    kaynak_hedef = hedef / MUZIK_KAYNAK_KLASORU / f"{isim}{kaynak.suffix.lower() or '.wav'}"
    gecici = hedef / f"{isim}.gecici.m4a"
    try:
        hedef.mkdir(parents=True, exist_ok=True)
        gecici.unlink(missing_ok=True)
    except OSError as exc:
        return _muzik_paketi(veri, "Müzik klasörü kurulamadı: " + _ilk_satir(exc, 200))
    # Kırpma girdi tarafında (`-ss`) hızlıdır; süre çıktıda `-t` ile sınırlanır.
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    if kirpma:
        komut += ["-ss", f"{bas:.3f}"]
    komut += ["-i", str(kaynak)]
    if kirpma:
        komut += ["-t", f"{bit - bas:.3f}"]
    # Ses seviyesi burada **uygulanır**: videoya eklerken tekrar ayar gerekmez.
    komut += ["-vn", "-ac", "2", "-ar", "48000",
              "-af", f"volume={seviye / 100:.4f}",
              "-c:a", "aac", "-b:a", "192k", str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut)
    if not ok:
        gecici.unlink(missing_ok=True)
        return _muzik_paketi(veri, "Müzik kaydedilemedi: " + mesaj)
    try:
        os.replace(gecici, dosya_hedef)
        kaynak_hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kaynak, kaynak_hedef)
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return _muzik_paketi(veri, "Müzik dosyası yerine yazılamadı: "
                                  + _ilk_satir(exc, 200))
    sure_hedef = FFMPEG.medya_suresi(dosya_hedef) or max(0.0, bit - bas)
    # Karartmalar müziğin uzunluğuna sığdırılır: ikisi birlikte müzikten uzun olamaz.
    giris = _karartma(giris_karartma)
    cikis = _karartma(cikis_karartma)
    if sure_hedef > 0:
        giris = min(giris, sure_hedef)
        cikis = min(cikis, max(0.0, sure_hedef - giris))
    kayit = {"ad": isim,
             "dosya": f"{MUZIK_KLASORU}/{dosya_hedef.name}",
             "kaynak": f"{MUZIK_KLASORU}/{MUZIK_KAYNAK_KLASORU}/{kaynak_hedef.name}",
             "sure": sure_hedef,
             "seviye": seviye, "bas": round(bas, 2), "bit": round(bit, 2),
             "giris_karartma": giris, "cikis_karartma": cikis,
             "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    durum = _muzik_durumu(klasor)
    adlar = [k["ad"] for k in durum["parcalar"]]
    if isim in adlar:
        durum["parcalar"][adlar.index(isim)] = kayit
    else:
        durum["parcalar"].append(kayit)
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError as exc:
        return _muzik_paketi(veri, "Müzik kaydedildi ama liste yazılamadı: "
                                  + _ilk_satir(exc, 200))
    baslik = (f"'{isim}' müziği kaydedildi ({sure_metni(kayit['sure'])} · %{seviye}"
              + (f" · kırpma {sure_metni(bas)}–{sure_metni(bit)} sn" if kirpma else "")
              + (f" · karartma giriş {_karartma_metni(giris)}"
                 f" / çıkış {_karartma_metni(cikis)}" if giris or cikis else "")
              + ").")
    not_ekle(veri, baslik)
    proje_yaz(veri)
    return _muzik_paketi(
        veri, baslik + " Videoya eklemek için aşağıdaki **Videoya ekle** panelinde "
        "kutuyu işaretle; müzikler işaretlediğin sırayla videoya girer"
        + (" (karartmalar videoya eklenirken uygulanır)." if giris or cikis else "."))


def muzik_sil(ad, isim):
    """Kaydedilmiş müziği listeden ve diskten kaldır.

    Müzik videoda duyuluyorsa karışım da tazelenir: video **kalan** müziklerle (yoksa
    yalnızca anlatım/ekli dille) yeniden kurulur, böylece kayıtla video birbirini tutar.
    """
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return _muzik_bos(hata)
    isim = muzik_adi(isim)
    durum = _muzik_durumu(klasor)
    kayit = next((k for k in durum["parcalar"] if k["ad"] == isim), None)
    if kayit is None:
        return _muzik_paketi(veri, f"'{isim}' listede yok.")
    durum["parcalar"] = [k for k in durum["parcalar"] if k["ad"] != isim]
    durum["secim"] = [x for x in durum["secim"] if x != isim]
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError as exc:
        return _muzik_paketi(veri, "Müzik listesi yazılamadı: " + _ilk_satir(exc, 200))
    for alan in ("dosya", "kaynak"):
        if kayit[alan]:
            try:
                (klasor / kayit[alan]).unlink(missing_ok=True)
            except OSError:
                pass
    not_ekle(veri, f"'{isim}' müziği listeden kaldırıldı.")
    mesaj = f"**{isim}** listeden kaldırıldı; dosyaları proje klasöründen silindi."
    if isim in (veri.get("muzikler") or []):
        veri["muzikler"] = [x for x in veri["muzikler"] if x != isim]
        if veri["muzikler"]:
            ok, ayrinti = _muzigi_uygula(klasor, veri)
            mesaj += (" Müzik videoda duyuluyordu; kalan müziklerle karışım tazelendi."
                      if ok else " Müzik videodan tazelenemedi: " + _ilk_satir(ayrinti, 200))
        else:
            ok, ayrinti = _muzikleri_temizle(klasor, veri)
            mesaj += (" Müzik videoda duyuluyordu; müzik katmanı kaldırıldı."
                      if ok else " Müzik videodan kaldırılamadı: " + _ilk_satir(ayrinti, 200))
    # Silinen müzik sabit müziğe (dışa aktarma ve önizleme) girmişse sabit müzik de
    # güncellenir: kalan müzik varsa aynı konuşmayla yeniden kurulur, yoksa silinir.
    sabit_yol, bilgi = sabit_muzik(klasor)
    if sabit_yol is not None and isim in (bilgi.get("muzikler") or []):
        if veri.get("muzikler"):
            sabit_muzik_kur(klasor, veri, _anlatim_kaynagi(klasor, veri),
                            bilgi.get("konusma") or "seslendirme (ana dil)")
            mesaj += " Sabit müzik kalan müziklerle yeniden kuruldu."
        else:
            sabit_muzigi_sil(klasor)
            mesaj += " Projedeki sabit müzik de kaldırıldı."
    proje_yaz(veri)
    return _muzik_paketi(veri, mesaj)


def _anlatim_kaynagi(klasor, veri):
    """Videoda şu anda duyulan konuşma sesi: ekli dublaj varsa o, yoksa seslendirme."""
    yol = ekli_dublaj_dosyasi(klasor, veri)
    if yol is not None:
        return yol
    if (veri.get("ses_ekleme") or "") == "TAMAM":
        return ses_dosyasi(klasor, veri)
    return None


def _video_suresi(klasor, veri):
    """Videonun süresi (saniye): ffprobe; okunamazsa adım sürelerinin toplamı."""
    sure = FFMPEG.medya_suresi(klasor / "proje.mp4")
    if sure > 0:
        return sure
    return sum(adim_suresi(adim, proje_adim_saniyesi(veri))
               for adim in veri.get("adimlar") or [] if adim.get("video"))


def _muzik_suresi(klasor, kayit):
    """Bir müzik kaydının süresi: kayıtta yazılıysa o, yoksa dosyadan ölçülür."""
    return float(kayit.get("sure") or 0) or FFMPEG.medya_suresi(klasor / kayit["dosya"])


def _karartma_suzgecleri(kayit, sure):
    """Bir müziğin karartma süzgeçleri: başında 0'dan yükselir, sonunda 0'a iner.

    `sure` müziğin kendi uzunluğudur: çıkış karartması bu sürenin **sonuna** oturur.
    Karartma yoksa boş metin döner ve süzgeç zincirine hiç eklenmez.
    """
    giris = _karartma(kayit.get("giris_karartma"))
    cikis = _karartma(kayit.get("cikis_karartma"))
    parcalar = []
    if giris > 0:
        parcalar.append(f"afade=t=in:st=0:d={giris:.3f}")
    if cikis > 0 and sure > 0:
        # Giriş ve çıkış karartması birlikte müzikten uzun olamaz.
        gecerli = min(cikis, max(0.0, sure - giris))
        if gecerli > 0:
            parcalar.append(f"afade=t=out:st={max(0.0, sure - gecerli):.3f}:"
                            f"d={gecerli:.3f}")
    return ",".join(parcalar)


def _muzik_bed(klasor, veri, video_sure=0.0):
    """İşaretlenen müzikleri **sırayla** tek dosyada birleştir (karışımın müzik katmanı).

    Her müziğin **karartması** burada uygulanır: kendi başında 0'dan yükselir, kendi
    sonunda 0'a iner; 1. bitince 2. başlarken geçiş bu yüzden yumuşar. Müzik videodan
    kısa kalırsa ve **tekrarla** işaretliyse katman video süresince tekrarlanır.

    Müzik videodan uzunsa (ya da döngünün son tekrarı tam oturmuyorsa) katman video
    sonunda **kesilir**; bu durumda son müziğin çıkış karartması **tam kesildiği yere**
    oturtulur: ses video sonunda yavaşça sıfıra iner, sert kesilmez.
    """
    kayitlar = {kayit["ad"]: kayit for kayit in _muzik_liste(klasor)}
    secilen = [kayitlar[ad] for ad in (veri.get("muzikler") or []) if ad in kayitlar]
    if not secilen:
        return None, ""
    sures = [_muzik_suresi(klasor, kayit) for kayit in secilen]
    suzgeler = [_karartma_suzgecleri(kayit, sure) for kayit, sure in zip(secilen, sures)]
    bed = muzik_klasoru(klasor) / "karisim.gecici.m4a"
    bed.unlink(missing_ok=True)
    try:
        bed.parent.mkdir(parents=True, exist_ok=True)
        if len(secilen) == 1 and not suzgeler[0]:
            # Tek müzik ve karartma yok: yeniden kodlanmaz, kaydedilen dosya kullanılır.
            shutil.copy2(klasor / secilen[0]["dosya"], bed)
        else:
            birlesik = muzik_klasoru(klasor) / "karisim.gecici-birlesik.m4a"
            birlesik.unlink(missing_ok=True)
            komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
            for kayit in secilen:
                komut += ["-i", str(klasor / kayit["dosya"])]
            # Örnek hızı/kanal düzeni eşitlenir: farklı kaynaklar (mono/stereo, 44,1/48
            # kHz) concat'ta sorun çıkarırdı. Karartmalar da burada, kendi müziğinin
            # üstüne uygulanır.
            zincir = "".join(
                f"[{sira}:a]aresample=48000,aformat=sample_fmts=fltp:"
                f"channel_layouts=stereo" + ("," + suzgec if suzgec else "")
                + f"[a{sira}];" for sira, suzgec in enumerate(suzgeler))
            zincir += "".join(f"[a{sira}]" for sira in range(len(secilen)))
            zincir += f"concat=n={len(secilen)}:v=0:a=1[out]"
            komut += ["-filter_complex", zincir, "-map", "[out]",
                      "-c:a", "aac", "-b:a", "192k", str(birlesik)]
            ok, mesaj = FFMPEG.calistir(komut)
            if not ok:
                birlesik.unlink(missing_ok=True)
                return None, "Müzikler birleştirilemedi: " + mesaj
            os.replace(birlesik, bed)
    except OSError as exc:
        bed.unlink(missing_ok=True)
        return None, "Müzik karışımı hazırlanamadı: " + _ilk_satir(exc, 200)
    cikis = _karartma(secilen[-1].get("cikis_karartma"))
    bed_sure = FFMPEG.medya_suresi(bed)
    kesildi = False
    if (veri.get("muzik_tekrarla") and video_sure > 0 and 0 < bed_sure
            and bed_sure + 0.05 < video_sure):
        # Döngünün son tekrarı tam oturmuyorsa müzik video sonunda kesiliyor demektir
        # (oturuyorsa son müziğin kendi çıkış karartması tam video sonunda biter).
        kalan = video_sure % bed_sure
        kesildi = bool(kalan > 0.05 and bed_sure - kalan > 0.05)
        dongu = muzik_klasoru(klasor) / "dongu.gecici.m4a"
        dongu.unlink(missing_ok=True)
        komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                 "-stream_loop", "-1", "-i", str(bed), "-t", f"{video_sure:.3f}",
                 "-c:a", "aac", "-b:a", "192k", str(dongu)]
        ok, mesaj = FFMPEG.calistir(komut)
        if not ok:
            dongu.unlink(missing_ok=True)
            return None, "Müzik tekrarlanamadı: " + mesaj
        os.replace(dongu, bed)
        bed_sure = FFMPEG.medya_suresi(bed)
    elif video_sure > 0 and bed_sure > video_sure + 0.05:
        kesildi = True
    if kesildi and cikis > 0:
        kadar = min(cikis, video_sure)
        karartilmis = muzik_klasoru(klasor) / "karartma.gecici.m4a"
        karartilmis.unlink(missing_ok=True)
        komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(bed),
                 "-af", f"afade=t=out:st={max(0.0, video_sure - kadar):.3f}:"
                        f"d={kadar:.3f}",
                 "-t", f"{video_sure:.3f}", "-c:a", "aac", "-b:a", "192k",
                 str(karartilmis)]
        ok, mesaj = FFMPEG.calistir(komut)
        if not ok:
            karartilmis.unlink(missing_ok=True)
            return None, "Müzik karartılamadı: " + mesaj
        os.replace(karartilmis, bed)
    return bed, ""


def _ducking_acik(veri):
    """Projede ducking açık mı? Satır yazmayan eski projelerde varsayılan açıktır."""
    deger = (veri or {}).get("muzik_ducking")
    return MUZIK_VARSAYILAN_DUCKING if deger is None else bool(deger)


# Karışımın iki girdisi farklı biçimde gelir: anlatım çoğunlukla mono 24 kHz WAV
# (Gemini PCM), müzik yatağı stereo 48 kHz AAC. `sidechaincompress` iki girdinin
# **aynı** örnekleme hızında ve kanal düzeninde olmasını ister; eşitlemeden filtre
# grafiği hiç kurulmaz. Bu yüzden her iki dal da önce `aresample`+`aformat`'tan geçer.
_ESIT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def _karisim_zinciri(ses_girdi, muzik_girdi, ducking=True, ses_suzgec=""):
    """Anlatım + müzik karışımının `filter_complex` zinciri.

    `ses_suzgec` anlatımın seviye süzgecidir (bkz. `anlatim_suzgeci`); karışımdan
    **önce** uygulanır, böylece ducking de yükseltilmiş anlatıma göre çalışır.

    `ducking` açıkken müzik, anlatımın yan-zincir (sidechain) anahtarıyla kısılır:
    konuşma başlayınca iner, susunca geri yükselir. Anlatım `asplit` ile ikiye ayrılır,
    çünkü hem karışımın bir girdisi hem de sıkıştırıcının anahtarıdır.

    `ducking` kapalıyken zincir eski davranışın **birebir** aynısıdır: düz `amix`.
    """
    if not ducking:
        if ses_suzgec:
            return (f"[{ses_girdi}:a]{ses_suzgec}[voice];"
                    f"[voice][{muzik_girdi}:a]amix=inputs=2:duration=longest:"
                    "normalize=0,alimiter=limit=0.97[aout]")
        return (f"[{ses_girdi}:a][{muzik_girdi}:a]amix=inputs=2:duration=longest:"
                "normalize=0,alimiter=limit=0.97[aout]")
    return (f"[{ses_girdi}:a]{_ESIT}{',' + ses_suzgec if ses_suzgec else ''},"
            "asplit=2[voice][key];"
            f"[{muzik_girdi}:a]{_ESIT}[bed];"
            f"[bed][key]sidechaincompress="
            f"threshold={MUZIK_DUCKING_ESIK}:ratio={MUZIK_DUCKING_ORAN}:"
            f"attack={MUZIK_DUCKING_ATAK}:release={MUZIK_DUCKING_BIRAKMA}:"
            "makeup=1:detection=rms[duck];"
            "[voice][duck]amix=inputs=2:duration=longest:"
            "normalize=0,alimiter=limit=0.97[aout]")


def _mono_mu(yol):
    """Ses dosyası tek kanallı mı? (ffprobe; okunamazsa `False`)."""
    metin = FFMPEG.probe(["-select_streams", "a:0", "-show_entries", "stream=channels",
                          "-of", "default=nw=1:nk=1"], yol).strip()
    return metin.splitlines()[0].strip() == "1" if metin else False


def _efektli_karisim_zinciri(ses_girdi, muzik_girdi, efekt_girdi, efekt_seviye,
                             ducking=True, ses_suzgec="", ses_mono=False):
    """Anlatım + müzik + **ses efekti** karışımının `filter_complex` zinciri.

    Efekt izi yalnızca videoya bir efekt kaydı ekliyken karışıma girer; efekt yoksa
    `_karisim_zinciri` (eski yol) birebir aynen kullanılır. Girdilerden biri yoksa
    (`None`) o dal zincire hiç yazılmaz. Efekt **ducking'e girmez**: sahnedeki ses
    anlatım konuşurken de duyulmalıdır; seviyesi `efekt_seviye` (%) ile ayarlanır.
    Müziğin ducking'i anlatıma göre aynen çalışır.

    `ses_mono`: anlatım tek kanallıysa önce `pan` ile iki kanala **tam seviyede**
    kopyalanır. `aformat`ın kendi dönüşümü merkez kanalı −3 dB kısar (ölçüm: 440 Hz mono
    −21,1 dB → stereo −24,1 dB); efekt eklemek anlatımı kısmamalı.
    """
    dallar, zincir = [], []
    kisma = ducking and ses_girdi is not None and muzik_girdi is not None
    if ses_girdi is not None:
        zincir.append(f"[{ses_girdi}:a]{'pan=stereo|c0=c0|c1=c0,' if ses_mono else ''}"
                      f"{_ESIT}{',' + ses_suzgec if ses_suzgec else ''}"
                      + (",asplit=2[voice][key]" if kisma else "[voice]"))
        dallar.append("[voice]")
    if muzik_girdi is not None:
        if kisma:
            zincir.append(f"[{muzik_girdi}:a]{_ESIT}[bed]")
            zincir.append(f"[bed][key]sidechaincompress="
                          f"threshold={MUZIK_DUCKING_ESIK}:ratio={MUZIK_DUCKING_ORAN}:"
                          f"attack={MUZIK_DUCKING_ATAK}:release={MUZIK_DUCKING_BIRAKMA}:"
                          "makeup=1:detection=rms[duck]")
            dallar.append("[duck]")
        else:
            zincir.append(f"[{muzik_girdi}:a]{_ESIT}[bed]")
            dallar.append("[bed]")
    zincir.append(f"[{efekt_girdi}:a]{_ESIT},volume={efekt_seviye / 100:.4f}[sfx]")
    dallar.append("[sfx]")
    if len(dallar) == 1:
        zincir.append("[sfx]alimiter=limit=0.97[aout]")
    else:
        zincir.append("".join(dallar) + f"amix=inputs={len(dallar)}:duration=longest:"
                      "normalize=0,alimiter=limit=0.97[aout]")
    return ";".join(zincir)


def _muzigi_uygula(klasor, veri):
    """`proje.mp4`ün sesini yeniden kur: anlatım/ekli dublaj + işaretlenen müzikler.

    Görüntü **kopyalanır** (gömülü altyazı korunur), yalnızca ses akışı yazılır: işlem
    hızlıdır ve üst üste eklemek sesleri katlamaz. Ses ne ise o kurulur: ikisi de yoksa
    video sessiz kalır (**Müziği kaldır** ve anlatım yok durumu).
    """
    video = klasor / "proje.mp4"
    if not video.is_file():
        return False, "proje.mp4 yok; önce adımlar birleştirilmeli."
    if not FFMPEG.ffmpeg():
        return False, "ffmpeg bulunamadı; müzik eklenemedi."
    ses = _anlatim_kaynagi(klasor, veri)
    # 21.10.2026 (kullanıcı kararı): müzik eklenirken videoda konuşma yoksa **projenin ana
    # dilindeki seslendirme** eklenir ve ducking ona göre yapılır. Eski arayüzde seslendirme
    # "Sesi videoya ekle" ile ekleniyordu; editörde bu adım olmadığı için proje.mp4
    # yalnızca müzikle kalıyor, müziğin kısılacağı bir konuşma bulunmuyordu.
    ana_dil_eklendi = False
    if ses is None and veri.get("muzikler"):
        ses = ses_dosyasi(klasor, veri)
        ana_dil_eklendi = ses is not None
    sure = _video_suresi(klasor, veri)
    bed, hata = _muzik_bed(klasor, veri, sure)
    if hata:
        return False, hata
    efekt, efekt_seviye = ekli_efekt(klasor)
    gecici = klasor / "proje-muzik.gecici.mp4"
    gecici.unlink(missing_ok=True)
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", "proje.mp4"]
    girdiler = []
    if ses is not None:
        komut += ["-i", str(ses)]
        girdiler.append(1)
    if bed is not None:
        komut += ["-i", str(bed)]
        girdiler.append(len(girdiler) + 1)
    if efekt is not None:
        komut += ["-i", str(efekt)]
    komut += ["-map", "0:v:0"]
    if efekt is not None:
        # Ses efekti ekliyse karışım efekt diliyle kurulur (bkz. `efekt_ekleme`).
        komut += ["-filter_complex",
                  _efektli_karisim_zinciri(1 if ses is not None else None,
                                           girdiler[-1] if bed is not None else None,
                                           len(girdiler) + 1, efekt_seviye,
                                           _ducking_acik(veri), anlatim_suzgeci(veri)
                                           if ses is not None else "",
                                           ses is not None and _mono_mu(ses)),
                  "-map", "[aout]"]
    elif len(girdiler) == 2:
        # Karışım: ikisi de duyulur, seviyeleri kaydedildiği gibi kalır (`normalize=0`).
        # Sınıra dayanırsa kırpılmasın diye yumuşak sınırlayıcı sona eklenir.
        komut += ["-filter_complex",
                  _karisim_zinciri(girdiler[0], girdiler[1], _ducking_acik(veri),
                                   anlatim_suzgeci(veri)),
                  "-map", "[aout]"]
    elif girdiler:
        komut += ["-map", f"{girdiler[0]}:a:0"]
        # Tek girdi anlatımsa seviyesi uygulanır; yalnızca müzikse dokunulmaz.
        if ses is not None and anlatim_suzgeci(veri):
            komut += ["-af", anlatim_suzgeci(veri)]
    else:
        komut += ["-an"]
    komut += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    if sure > 0:
        # Ses video süresine sığdırılır: uzun müzik video sonunda kesilir, boşluk
        # yaratmaz; video akışı kopya olduğu için süre videodan gelir.
        komut += ["-t", f"{sure:.3f}"]
    komut += [str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut, cwd=klasor)
    bed_yolu = muzik_klasoru(klasor) / "karisim.gecici.m4a"
    bed_yolu.unlink(missing_ok=True)
    if not ok:
        gecici.unlink(missing_ok=True)
        return False, mesaj
    try:
        os.replace(gecici, video)
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return False, "Video yerine yazılamadı: " + _ilk_satir(exc, 200)
    if ana_dil_eklendi:
        veri["ses_ekleme"] = "TAMAM"
        veri["ses_ekleme_bitti"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    return True, ""


def _muzikleri_temizle(klasor, veri):
    """Müzik katmanını videodan kaldır: ses yalnızca anlatım/ekli dilden kurulur."""
    eski = {a: veri.get(a) for a in ("muzikler", "muzik_ekleme", "muzik_ekleme_bitti")}
    veri["muzikler"] = []
    veri["muzik_ekleme"] = "BEKLİYOR"
    veri["muzik_ekleme_bitti"] = ""
    ok, mesaj = _muzigi_uygula(klasor, veri)
    if not ok:
        # 21.10.2026: video yazılamazsa (ör. dosya açık) kayıt "müzik yok" derken video
        # müzikli kalıyordu; kayıt videoyla tutarlı kalsın diye eski hâline döner.
        veri.update(eski)
    return ok, mesaj


def ses_katmanini_kur(veri, klasor):
    """`proje.mp4`ün ses akışını baştan kur: anlatım/ekli dublaj + ekli müzik.

    Görüntü kopyalanır (gömülü altyazı korunur); anlatım **dosyasından** yeniden
    okunduğu için seviye değişikliği üst üste binmez. Dönüş: `(tamam mı, mesaj)`.
    """
    return _muzigi_uygula(klasor, veri)


def muzik_geri_uygula(veri, klasor):
    """Video yeniden kurulduysa **ekli müziği ve ses efektini** geri uygula.

    Not döner; `''` = iş yok. Ses efekti müzikle aynı karışımda durduğu için (bkz.
    `_muzigi_uygula`) ikisi tek geçişte geri gelir.
    """
    muzik = ((veri.get("muzik_ekleme") or "") == "TAMAM" and bool(veri.get("muzikler")))
    efekt = ekli_efekt(klasor)[0] is not None
    if not muzik and not efekt:
        return ""
    ok, mesaj = _muzigi_uygula(klasor, veri)
    if not ok:
        return (" Ekli " + ("müzik" if muzik else "ses efekti") + " geri uygulanamadı: "
                + _ilk_satir(mesaj, 200))
    parcalar = []
    if muzik:
        parcalar.append("Ekli müzik (" + ", ".join(veri["muzikler"]) + ")")
    if efekt:
        parcalar.append("ses efektleri")
    return " " + " ve ".join(parcalar) + " yeniden uygulandı."


def muzik_videoya_ekle(ad, secilenler, tekrarla, ducking=MUZIK_VARSAYILAN_DUCKING,
                       konusma=None):
    """İşaretlenen müzikleri **işaretleme sırasıyla** videoya ekle.

    Müzik anlatımın **altına karışır**: video konuşurken de duyulur. Karışım her zaman
    baştan kurulduğu için üst üste eklemek sesleri katlamaz; **Müziği kaldır** da aynı
    yolu kullanır. Seçili müzikler videodan kısaysa ve **tekrarla** işaretliyse müzik
    video sonuna kadar baştan çalar; uzun müzik video sonunda kesilir.

    `konusma` (kullanıcı kararı, 21.10.2026): müzik eklenirken **zaman çizelgesinde işaretli
    konuşma** videoya girer ve ducking ona göre yapılır: `"seslendirme"` → ana dilin
    anlatımı, `"dublaj:<ad>"` → o dublaj. `None` → videodaki konuşma korunur (yoksa ana dil).
    """
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return _muzik_bos(hata)
    if not (klasor / "proje.mp4").is_file():
        return _muzik_paketi(veri, "`proje.mp4` yok; önce adımlar birleştirilmeli.")
    if not FFMPEG.ffmpeg():
        return _muzik_paketi(veri, "ffmpeg bulunamadı; müzik videoya eklenemedi.")
    kayitli = {kayit["ad"] for kayit in _muzik_liste(klasor)}
    secilen = [ad for ad in dict.fromkeys(muzik_adi(x) for x in (secilenler or []))
               if ad in kayitli]
    if not secilen:
        return _muzik_paketi(veri, "Videoya eklemek için yukarıdaki listede en az bir "
                                    "müziğin kutusunu işaretle.")
    veri["muzikler"] = secilen
    veri["muzik_tekrarla"] = bool(tekrarla)
    veri["muzik_ducking"] = bool(ducking)
    if konusma == "seslendirme":
        veri.update(ekli_dublaj="", ekli_dil="", ses_ekleme="TAMAM")
    elif str(konusma or "").startswith("dublaj:"):
        veri.update(ekli_dublaj=konusma.split(":", 1)[1], ekli_dil="", ses_ekleme="BEKLİYOR")
    durum = _muzik_durumu(klasor)
    durum["secim"], durum["tekrarla"] = secilen, bool(tekrarla)
    durum["ducking"] = bool(ducking)
    try:
        _muzik_durumu_yaz(klasor, durum)
    except OSError:
        pass
    ok, mesaj = _muzigi_uygula(klasor, veri)
    if not ok:
        return _muzik_paketi(veri, hata_yaz(veri, None, "Müzik ekleme",
                                             "Müzik videoya eklenemedi: "
                                             + _ilk_satir(mesaj, 200)))
    simdi = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    veri["muzik_ekleme"] = "TAMAM"
    veri["muzik_ekleme_bitti"] = simdi
    veri["durum"] = "tamam"
    # Müzik bu anki konuşmaya göre ducking'li hâliyle sabitlenir (dışa aktarma bunu çalar).
    konusma_yolu = _anlatim_kaynagi(klasor, veri)
    konusma_adi = ("'" + konusma.split(":", 1)[1] + "' dublajı" if str(konusma or "").startswith("dublaj:")
                   else "seslendirme (ana dil)")
    sabit_ok, sabit_hata = sabit_muzik_kur(klasor, veri, konusma_yolu, konusma_adi)
    baslik = ("Müzik videoya eklendi: " + ", ".join(secilen)
              + (" (kısa kalırsa video sonuna kadar tekrar)." if veri["muzik_tekrarla"]
                 else ".")
              + (f" Ducking {konusma_adi} ile sabitlendi." if sabit_ok and _ducking_acik(veri)
                 and konusma_yolu is not None else "")
              + ("" if sabit_ok else f" Sabit müzik yazılamadı: {sabit_hata}"))
    veri["son_not"] = baslik
    not_ekle(veri, baslik + (
        (" Anlatım sesi korundu, müzik altına karıştı."
         + (" Anlatım konuşurken müzik otomatik kısılıyor (ducking)."
            if _ducking_acik(veri) else " Ducking kapalı: seviyeler olduğu gibi karıştı."))
        if _anlatim_kaynagi(klasor, veri) is not None else
        " Videoda konuşma sesi yok; yalnızca müzik duyulur."))
    proje_yaz(veri)
    return _muzik_paketi(veri, baslik + " " + sure_ozeti(veri)
                         + " Anlatım varsa müziğin altında duyulur.")


def muzikleri_kaldir(ad):
    """**Müziği kaldır**: videodaki müzik katmanı çıkar, anlatım sesi kalır.

    Kaydedilmiş müzikler **silinmez**: liste olduğu gibi durur, istediğini yeniden
    ekleyebilirsin.
    """
    veri, klasor, hata = _muzik_hedefi(ad)
    if hata:
        return _muzik_bos(hata)
    if not (klasor / "proje.mp4").is_file():
        return _muzik_paketi(veri, "`proje.mp4` yok; önce adımlar birleştirilmeli.")
    if not FFMPEG.ffmpeg():
        return _muzik_paketi(veri, "ffmpeg bulunamadı; müzik kaldırılamadı.")
    if ((veri.get("muzik_ekleme") or "") != "TAMAM" and not (veri.get("muzikler") or [])
            and sabit_muzik(klasor)[0] is None):
        return _muzik_paketi(veri, "Videoda ekli müzik yok; kaldırılacak bir şey yok.")
    ok, mesaj = _muzikleri_temizle(klasor, veri)
    if ok:
        sabit_muzigi_sil(klasor)
    if not ok:
        return _muzik_paketi(veri, hata_yaz(veri, None, "Müzik kaldırma",
                                             "Müzik videodan kaldırılamadı: "
                                             + _ilk_satir(mesaj, 200)))
    baslik = "Müzik videodan kaldırıldı."
    veri["durum"] = "tamam"
    veri["son_not"] = baslik
    not_ekle(veri, baslik + " Kaydedilmiş müzikler listede durur.")
    proje_yaz(veri)
    return _muzik_paketi(veri, baslik + (" Anlatım sesi videoda kaldı."
                                         if _anlatim_kaynagi(klasor, veri) is not None
                                         else " Videoda başka ses yok; video yine sessiz."))


# Yalnızca ses çıktısı (`ses_ciktisi`) aynı karışımı videoya dokunmadan kurar: müzik
# yatağı, karışım zincirleri ve panel paketleri ortak kalsın diye buradan açılır.
muzik_yatagi = _muzik_bed
karisim_zinciri = _karisim_zinciri
efektli_karisim_zinciri = _efektli_karisim_zinciri
mono_mu = _mono_mu
ducking_acik = _ducking_acik
video_suresi = _video_suresi
muzik_kayitlari = _muzik_liste
muzik_paketi = _muzik_paketi
muzik_bos = _muzik_bos


# ── Sabit müzik (kullanıcı kararı, 21.10.2026) ──────────────────────────────────────
# Müzik projeye eklendiği anda, o an işaretli konuşmaya göre **ducking'i uygulanmış** hâliyle
# projenin tam uzunluğunda tek dosyaya yazılır ve bir daha değişmez. Dışa aktarma ve
# önizleme bu dosyayı olduğu gibi çalar; ducking yeniden hesaplanmaz.
SABIT_MUZIK = "sabit-muzik.m4a"
SABIT_MUZIK_BILGI = "sabit-muzik.json"


# 21.10.2026: önizleme çalarken sabit müzik dosyası açık kalır; Windows açık dosyayı silmeye
# ve üzerine yazmaya izin vermez ("Müziği kaldır" 500 verdi). Bu yüzden her kurulum **yeni
# adlı** dosyaya yazılır (`sabit-muzik-<zaman>.m4a`), geçerli dosya bilgi dosyasında durur;
# kaldırmada önce bilgi "silindi" yapılır, eski dosyalar silinebildiği zaman silinir.
def _sabit_bilgi(klasor):
    try:
        return json.loads((muzik_klasoru(klasor) / SABIT_MUZIK_BILGI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sabit_bilgi_yaz(klasor, bilgi):
    yol = muzik_klasoru(klasor) / SABIT_MUZIK_BILGI
    gecici = yol.with_suffix(".gecici")
    gecici.write_text(json.dumps(bilgi, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, yol)


def _eski_sabitleri_temizle(klasor, gecerli=None):
    """Geçerli olmayan sabit müzik dosyalarını sil; kullanımda olan kalır, sonra silinir."""
    for yol in muzik_klasoru(klasor).glob("sabit-muzik*.m4a"):
        if gecerli is not None and yol.resolve() == gecerli.resolve():
            continue
        try:
            yol.unlink()
        except OSError:
            pass


def sabit_muzik(klasor):
    """Projenin sabit müziği: `(dosya yolu, bilgi sözlüğü)`; yoksa `(None, {})`."""
    bilgi = _sabit_bilgi(klasor)
    if bilgi.get("silindi"):
        return None, {}
    yol = klasor / bilgi["dosya"] if bilgi.get("dosya") else muzik_klasoru(klasor) / SABIT_MUZIK
    if not yol.is_file():
        return None, {}
    return yol, bilgi


def sabit_muzigi_sil(klasor):
    """Sabit müziği projeden kaldır. Dosya o an kullanımdaysa (önizleme) bilgi "silindi"
    yapılır; dosya bir sonraki temizlikte silinir. Hata vermez."""
    try:
        _sabit_bilgi_yaz(klasor, {"silindi": True,
                                  "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"})
    except OSError:
        pass
    _eski_sabitleri_temizle(klasor)


def sabit_muzik_kur(klasor, veri, konusma_yolu, konusma_adi):
    """Ducking'i uygulanmış müziği tek dosyaya yaz. Dönüş: `(tamam_mı, mesaj)`."""
    sure = _video_suresi(klasor, veri)
    bed, hata = _muzik_bed(klasor, veri, sure)
    if hata or bed is None:
        return False, hata or "Seçili müzik yok."
    hedef = muzik_klasoru(klasor) / f"sabit-muzik-{datetime.now():%Y%m%d-%H%M%S}.m4a"
    gecici = hedef.with_name("yaziliyor-sabit.m4a")   # uzantı .m4a olmalı (ffmpeg biçimi buradan seçer)
    gecici.unlink(missing_ok=True)
    ducking = _ducking_acik(veri) and konusma_yolu is not None
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    if ducking:
        suzgec = anlatim_suzgeci(veri)
        zincir = (f"[0:a]{_ESIT}{',' + suzgec if suzgec else ''}[key];"
                  f"[1:a]{_ESIT}[bed];"
                  f"[bed][key]sidechaincompress=threshold={MUZIK_DUCKING_ESIK}:"
                  f"ratio={MUZIK_DUCKING_ORAN}:attack={MUZIK_DUCKING_ATAK}:"
                  f"release={MUZIK_DUCKING_BIRAKMA}:makeup=1:detection=rms[out]")
        komut += ["-i", str(konusma_yolu), "-i", str(bed), "-filter_complex", zincir,
                  "-map", "[out]"]
    else:
        komut += ["-i", str(bed), "-af", _ESIT]
    if sure > 0:
        komut += ["-t", f"{sure:.3f}"]
    komut += ["-c:a", "aac", "-b:a", "192k", str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut, cwd=klasor)
    bed.unlink(missing_ok=True)
    if not ok:
        gecici.unlink(missing_ok=True)
        return False, "Sabit müzik yazılamadı: " + _ilk_satir(mesaj, 200)
    os.replace(gecici, hedef)
    bilgi = {"dosya": f"{MUZIK_KLASORU}/{hedef.name}", "muzikler": list(veri.get("muzikler") or []),
             "konusma": konusma_adi if ducking else "", "ducking": ducking,
             "tekrarla": bool(veri.get("muzik_tekrarla")), "sure": round(sure, 3),
             "tarih": f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    _sabit_bilgi_yaz(klasor, bilgi)
    _eski_sabitleri_temizle(klasor, gecerli=hedef)
    return True, ""
