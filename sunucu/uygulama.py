"""HTTP katmanı: JSON uçları, proje medyası ve editörün sayfası.

Okuma ve dışa aktarma uçları kota harcamaz; dışa aktarma yalnızca `projects/<ad>/disa-aktarim/`
klasörüne yazar. Üretim ve katman uçları StudioFlow'un kendi işlevlerini arka plan işi
olarak çalıştırır (kota harcayabilir, `proje.txt`'e yazar); iş `GET /api/uretim` ile izlenir.

    Kütüphane     GET /api/projeler · POST /api/yeni-proje (taslak) · DELETE /api/proje/{ad}
    Proje         GET /api/proje/{ad} · /sahne/{i} · /altyazi/{kayit} · /kayit · /dosyalar
    Ayarlar       GET|PUT /api/proje/{ad}/ayarlar · POST /api/ayar/bagli
                  GET|DELETE /api/ayar/genel · POST /api/proje/{ad}/ayar/genel-{kaydet|yukle}
                  GET|POST /api/ayar/otomatik
    İçerik        GET /api/belgeler · /api/belge/{seslendirme|prompt}/{ad}
                  POST /api/proje/{ad}/plan · /ses-testi · /yukle
                  GET|POST /api/proje/{ad}/kadro · DELETE /kadro/{karakter} · POST /kadro/referans
                  GET /api/kutuphane?ara=&yz= (hazır karakterler) · /kutuphane/{yol}
    Üretim        GET /api/uretim · POST /api/uretim/mod · /api/uretim/durdur
                  POST /api/proje/{ad}/baslat · /uretim/{devam|prompt|onay|deneme}
                  POST /api/proje/{ad}/sahne/{index}/{prompt|kare|klip}
    Katmanlar     /api/proje/{ad}/dublaj · /muzik · /altyazilar · /efekt · /sonuc (bkz. `katman`)
    Dışa aktarma  GET /api/proje/{ad}/disa-aktar · PUT /ayar · POST · POST /iptal
    Dosyalar      GET /medya/{ad}/{yol} · /dosyalar/{ad}/{yol} · /gecici/{ad} · / (web/)
"""
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from sunucu import ayar, disa_aktar, icerik, katman, kopru, kutuphane, proje_ayar, taslak, uretim, veri
from studioflow.arayuz.islevler_proje import _altyazi_sozlugu
from studioflow.proje import depo

app = FastAPI(title="StudioFlow", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _arayuz_onbelleksiz(istek: Request, sonraki):
    """Editörün kendi dosyaları her açılışta doğrulansın: güncellemeden sonra pencere eski
    `paneller.js`'i önbellekten yükleyip yeni `index.html`'le uyumsuz kalmasın."""
    yanit = await sonraki(istek)
    if istek.url.path == "/" or istek.url.path.endswith((".html", ".js", ".css")):
        yanit.headers["Cache-Control"] = "no-cache"
    return yanit


def _uret(islev, *argumanlar, **ad):
    try:
        return islev(*argumanlar, **ad)
    except (veri.ProjeYok, taslak.TaslakYok) as hata:
        raise HTTPException(status_code=404, detail=f"Bulunamadı: {hata}") from None
    except uretim.UretimHatasi as hata:
        raise HTTPException(status_code=409, detail=str(hata)) from None


_bul = _uret


# ── Kütüphane ve proje ─────────────────────────────────────────────────────────
@app.get("/api/projeler")
def projeler():
    return veri.projeler()


@app.get("/api/proje/{ad}")
def proje(ad: str):
    return _bul(veri.proje, ad)


@app.delete("/api/proje/{ad}")
def proje_sil(ad: str):
    """Projeyi (ya da taslağı) kalıcı olarak sil; süren üretim ve dışa aktarma durdurulur."""
    if taslak.var_mi(ad) and not (depo.PROJELER / depo.slug(ad) / "proje.txt").is_file():
        taslak.sil(ad)
        return {"mesaj": f"'{depo.slug(ad)}' taslağı silindi."}
    is_ = disa_aktar.is_durumu(ad)
    if is_ and is_.get("durum") == "calisiyor":
        disa_aktar.iptal_et(ad)         # ffmpeg süreci kapatılır, klasördeki dosyalar serbest kalır
        bitis = time.monotonic() + 5
        while (disa_aktar.is_durumu(ad) or {}).get("durum") == "calisiyor" \
                and time.monotonic() < bitis:
            time.sleep(0.2)
    return _uret(uretim.sil, ad)


@app.get("/api/proje/{ad}/sahne/{index}")
def sahne(ad: str, index: int):
    return _bul(veri.sahne, ad, index)


@app.get("/api/proje/{ad}/altyazi/{kayit}")
def altyazi(ad: str, kayit: str):
    return _bul(veri.altyazi_bloklari, ad, kayit)


@app.get("/api/proje/{ad}/kayit", response_class=PlainTextResponse)
def proje_kaydi(ad: str):
    return _bul(veri.proje_kaydi, ad)


@app.get("/api/proje/{ad}/dosyalar")
def proje_dosyalari(ad: str):
    return _bul(veri.proje_dosyalari, ad)


@app.post("/api/yeni-proje")
def yeni_proje(govde: dict = Body(...)):
    """StudioFlow gibi: önce ad; içerik ve ayarlar taslakta doldurulur, sonra başlatılır."""
    return _uret(proje_ayar.yeni_taslak, govde.get("ad"))


# ── Ayarlar ────────────────────────────────────────────────────────────────────
@app.get("/api/proje/{ad}/ayarlar")
def ayarlar_oku(ad: str):
    return _uret(proje_ayar.ayarlari_oku, ad)


@app.put("/api/proje/{ad}/ayarlar")
def ayarlar_yaz(ad: str, govde: dict = Body(...)):
    return _uret(proje_ayar.ayarlari_yaz, ad, govde)


@app.post("/api/ayar/bagli")
def ayar_bagli(govde: dict = Body(...)):
    """Bir alan değişince birlikte değişen alanlar + yeni değerlerle notlar ve model sınırları."""
    alan, degerler = govde.get("alan") or "", dict(govde.get("degerler") or {})
    yeni = proje_ayar.bagli_degisiklik(alan, degerler)
    son = {**degerler, **yeni}
    return {"degisen": yeni, "notlar": proje_ayar.notlar(son),
            "model": proje_ayar.model_bilgisi(son.get("gorsel.model") or ""),
            "edge_sesleri": proje_ayar.edge_sesleri(son.get("ses.dil"))}


@app.get("/api/ayar/genel")
def genel_ayar():
    return {"ozet": proje_ayar.genel_ayar_ozeti()}


@app.delete("/api/ayar/genel")
def genel_ayar_sil():
    return proje_ayar.genel_ayarlari_sil()


@app.post("/api/proje/{ad}/ayar/genel-kaydet")
def genel_ayar_kaydet(ad: str):
    return _uret(proje_ayar.genel_ayarlari_kaydet, ad)


@app.post("/api/proje/{ad}/ayar/genel-yukle")
def genel_ayar_yukle(ad: str):
    return _uret(proje_ayar.genel_ayarlari_yukle, ad)


@app.get("/api/ayar/otomatik")
def otomatik_oku():
    return proje_ayar.otomatik_kaydet()


@app.post("/api/ayar/otomatik")
def otomatik_yaz(govde: dict = Body(...)):
    return proje_ayar.otomatik_kaydet(bool(govde.get("acik")))


# ── İçerik ─────────────────────────────────────────────────────────────────────
@app.get("/api/belgeler")
def belgeler():
    return icerik.belgeler()


@app.get("/api/belge/seslendirme/{ad}")
def seslendirme_belgesi(ad: str):
    return _uret(icerik.seslendirme_belgesi, ad)


@app.get("/api/belge/prompt/{ad}")
def prompt_belgesi(ad: str):
    return _uret(icerik.prompt_belgesi, ad)


@app.post("/api/proje/{ad}/plan")
def sahne_plani(ad: str):
    return _uret(icerik.sahne_plani, ad)


@app.post("/api/proje/{ad}/ses-testi")
def ses_testi(ad: str):
    return _uret(icerik.ses_testi, ad)


@app.get("/api/proje/{ad}/kadro")
def kadro(ad: str):
    return _uret(icerik.kadro_listesi, ad)


@app.post("/api/proje/{ad}/kadro")
def kadro_kaydet(ad: str, govde: dict = Body(...)):
    return _uret(icerik.kadro_kaydet, ad, govde.get("ad"), govde.get("tarif"), govde.get("gorsel"))


@app.delete("/api/proje/{ad}/kadro/{karakter}")
def kadro_sil(ad: str, karakter: str):
    return _uret(icerik.kadro_sil, ad, karakter)


@app.get("/api/kutuphane")
def karakter_kutuphanesi(ara: str = "", yz: int = 1):
    """Hazır karakterler: boş aramada örnekler, `yz=0` yalnızca yerel eşleşme (anında)."""
    return kutuphane.ara(ara, yapay_zeka=bool(yz))


@app.post("/api/proje/{ad}/kadro/referans")
def kadro_referans(ad: str, govde: dict = Body(...)):
    return _uret(icerik.karakter_referansi, ad, govde.get("ad") or "", govde.get("tarif") or "")


@app.post("/api/proje/{ad}/yukle")
async def yukle(ad: str, istek: Request, tur: str, dosya: str = "dosya"):
    """Ham gövdeyle dosya yükleme (karakter görseli, referans ses, müzik)."""
    if tur not in ("karakter", "referans", "muzik"):
        raise HTTPException(status_code=400, detail="Bilinmeyen yükleme türü")
    icerik_ = await istek.body()
    return _uret(icerik.yukle, ad, tur, unquote(dosya), icerik_)


# ── Üretim ─────────────────────────────────────────────────────────────────────
@app.get("/api/uretim")
def uretim_durumu():
    return {"is": uretim.is_durumu(), "mod": uretim.uretim_modu(),
            "servisler": [{"anahtar": k, "ad": v} for k, v in uretim.SERVISLER.items()]}


@app.post("/api/uretim/mod")
def uretim_modu(govde: dict = Body(...)):
    return {"mod": uretim.uretim_modu(str(govde.get("mod") or ""))}


@app.post("/api/uretim/durdur")
def uretim_durdur():
    return {"is": uretim.durdur()}


@app.post("/api/proje/{ad}/baslat")
def proje_baslat(ad: str):
    return _uret(proje_ayar.baslat, ad)


@app.post("/api/proje/{ad}/uretim/{islem}")
def uretim_baslat(ad: str, islem: str, govde: dict = Body(default={})):
    if islem == "devam":
        return _uret(uretim.devam, ad)
    if islem == "prompt":
        return _uret(uretim.prompt_baslat, ad, govde.get("ai"), govde.get("model"))
    if islem == "onay":
        return _uret(uretim.onay, ad, govde.get("servis") or "")
    if islem == "deneme":
        return {"mesaj": _uret(uretim.deneme_sifirla, ad)}
    raise HTTPException(status_code=404, detail="Bilinmeyen işlem")


@app.post("/api/proje/{ad}/sahne/{index}/{islem}")
def sahne_islemi(ad: str, index: int, islem: str, govde: dict = Body(default={})):
    _bul(veri.sahne, ad, index)
    if islem == "prompt":
        return _uret(uretim.sahne_prompt, ad, index, govde.get("gorsel"), govde.get("negatif"))
    if islem == "kare":
        return _uret(uretim.kare_yenile, ad, index)
    if islem == "klip":
        return _uret(uretim.klip_yenile, ad, index)
    raise HTTPException(status_code=404, detail="Bilinmeyen işlem")


# ── Katmanlar: dublaj ──────────────────────────────────────────────────────────
@app.get("/api/proje/{ad}/dublaj")
def dublajlar(ad: str):
    return _uret(katman.dublajlar, ad)


@app.post("/api/proje/{ad}/dublaj")
def dublaj_uret(ad: str, govde: dict = Body(...)):
    return _uret(katman.dublaj_uret, ad, govde)


@app.delete("/api/proje/{ad}/dublaj/{isim}")
def dublaj_sil(ad: str, isim: str):
    return _uret(katman.dublaj_sil, ad, isim)


@app.post("/api/proje/{ad}/dublaj/{isim}/sec")
def dublaj_sec(ad: str, isim: str):
    return _uret(katman.dublaj_sec, ad, isim)


@app.post("/api/proje/{ad}/dublaj/{isim}/ekle")
def dublaj_ekle(ad: str, isim: str, govde: dict = Body(default={})):
    return _uret(katman.dublaj_ekle, ad, isim, govde.get("seviye"), govde.get("mod") or "video")


# ── Katmanlar: müzik ───────────────────────────────────────────────────────────
@app.get("/api/proje/{ad}/muzik")
def muzikler(ad: str):
    return _uret(katman.muzikler, ad)


@app.post("/api/proje/{ad}/muzik/uret")
def muzik_uret(ad: str, govde: dict = Body(default={})):
    return _uret(katman.muzik_yz_uret, ad, govde.get("tarif") or "", govde.get("sure") or 60,
                 govde.get("bpm") or 0)


@app.post("/api/proje/{ad}/muzik")
def muzik_kaydet(ad: str, govde: dict = Body(...)):
    return _uret(katman.muzik_kaydet, ad, govde)


@app.delete("/api/proje/{ad}/muzik/{isim}")
def muzik_sil(ad: str, isim: str):
    return _uret(katman.muzik_sil, ad, isim)


@app.put("/api/proje/{ad}/muzik/secim")
def muzik_secim(ad: str, govde: dict = Body(...)):
    return _uret(katman.muzik_secim, ad, govde.get("secim") or [])


@app.put("/api/proje/{ad}/muzik/tercih")
def muzik_tercih(ad: str, govde: dict = Body(...)):
    return _uret(katman.muzik_tercih, ad, govde.get("tekrarla"), govde.get("ducking"))


@app.post("/api/proje/{ad}/muzik/ekle")
def muzik_ekle(ad: str, govde: dict = Body(default={})):
    return _uret(katman.muzik_ekle, ad, govde.get("mod") or "video")


@app.post("/api/proje/{ad}/muzik/kaldir")
def muzik_kaldir(ad: str, govde: dict = Body(default={})):
    return _uret(katman.muzik_kaldir, ad, govde.get("mod") or "video")


# ── Katmanlar: altyazı ─────────────────────────────────────────────────────────
@app.get("/api/proje/{ad}/altyazilar")
def altyazilar(ad: str):
    return _uret(katman.altyazilar_, ad)


@app.post("/api/proje/{ad}/altyazilar")
def altyazi_kaydet(ad: str, govde: dict = Body(...)):
    return _uret(katman.altyazi_kaydet, ad, govde.get("dil") or "en", govde.get("isim") or "")


@app.delete("/api/proje/{ad}/altyazilar/{isim}")
def altyazi_sil(ad: str, isim: str):
    return _uret(katman.altyazi_sil, ad, isim)


@app.post("/api/proje/{ad}/altyazilar/{isim}/sec")
def altyazi_sec(ad: str, isim: str):
    return _uret(katman.altyazi_sec, ad, isim)


@app.post("/api/proje/{ad}/altyazilar/{isim}/gom")
def altyazi_gom(ad: str, isim: str):
    return _uret(katman.altyazi_gom, ad, isim)


@app.post("/api/proje/{ad}/altyazi-yeniden")
def altyazi_yeniden(ad: str):
    return _uret(katman.altyazi_yeniden, ad)


@app.post("/api/altyazi-onizleme")
def altyazi_onizleme(govde: dict = Body(...)):
    d = govde.get("degerler") or {}
    sozluk = _altyazi_sozlugu(True, d.get("altyazi.preset") or "yatay", d.get("altyazi.font") or "Arial",
                              d.get("altyazi.renk") or "#FFFFFF", bool(d.get("altyazi.kalin")),
                              d.get("altyazi.seviye"))
    return katman.altyazi_onizleme(d.get("video.bicim") or "", sozluk, govde.get("zemin"))


# ── Katmanlar: ses efektleri ───────────────────────────────────────────────────
@app.get("/api/proje/{ad}/efekt")
def efektler(ad: str):
    return _uret(katman.efektler_, ad)


@app.get("/api/proje/{ad}/efekt-sahneleri")
def efekt_sahneleri(ad: str):
    return _uret(katman.efekt_sahneleri, ad)


@app.post("/api/proje/{ad}/efekt/hazirla")
def efekt_hazirla(ad: str, govde: dict = Body(...)):
    istekler = {int(k): v for k, v in (govde.get("istekler") or {}).items()}
    return _uret(katman.efekt_hazirla_, ad, govde.get("yontem") or "yapay_zeka",
                 govde.get("isim") or "", istekler or None)


@app.post("/api/proje/{ad}/efekt/bul")
def efekt_bul(ad: str, govde: dict = Body(...)):
    return _uret(katman.efekt_bul, ad, govde.get("sorgu") or "", int(govde.get("index") or 0),
                 govde.get("tur") or "eylem")


@app.post("/api/proje/{ad}/efekt/kaldir")
def efekt_kaldir(ad: str):
    return _uret(katman.efekt_kaldir, ad)


@app.delete("/api/proje/{ad}/efekt/{isim}")
def efekt_sil(ad: str, isim: str):
    return _uret(katman.efekt_sil, ad, isim)


@app.post("/api/proje/{ad}/efekt/{isim}/sec")
def efekt_sec(ad: str, isim: str):
    return _uret(katman.efekt_sec, ad, isim)


@app.post("/api/proje/{ad}/efekt/{isim}/gom")
def efekt_gom(ad: str, isim: str, govde: dict = Body(default={})):
    return _uret(katman.efekt_gom, ad, isim, govde.get("seviye") or 100)


@app.get("/api/proje/{ad}/efekt/{isim}/duzenle")
def efekt_duzenle(ad: str, isim: str):
    return _uret(katman.efekt_duzenleme_listesi, ad, isim)


@app.post("/api/proje/{ad}/efekt/{isim}/onayla")
def efekt_onayla(ad: str, isim: str, govde: dict = Body(...)):
    return _uret(katman.efekt_onayla, ad, isim, govde.get("index"), govde.get("sira"),
                 govde.get("aday"), govde.get("tur"), govde.get("bas"), govde.get("etiket"))


# ── Sonuç videosu (StudioFlow'un proje.mp4'ü) ──────────────────────────────────
@app.get("/api/proje/{ad}/sonuc")
def sonuc(ad: str):
    return _uret(katman.sonuc, ad)


@app.post("/api/proje/{ad}/sonuc/ses")
def sonuc_ses(ad: str, govde: dict = Body(default={})):
    return _uret(katman.ses_ekle, ad, govde.get("seviye"), govde.get("mod") or "video")


@app.post("/api/proje/{ad}/sonuc/altyazi")
def sonuc_altyazi(ad: str):
    return _uret(katman.altyazi_ekle, ad)


@app.post("/api/proje/{ad}/sonuc/geri")
def sonuc_geri(ad: str, govde: dict = Body(default={})):
    return _uret(katman.geri_don, ad, govde.get("mod") or "video")


@app.post("/api/proje/{ad}/sonuc/mp3")
def sonuc_mp3(ad: str):
    return _uret(katman.video_sesi_mp3, ad)


# ── Dışa aktarma ───────────────────────────────────────────────────────────────
@app.get("/api/proje/{ad}/disa-aktar")
def disa_aktar_durumu(ad: str):
    """İz işaretleri/seçimleri ve (varsa) son dışa aktarma işinin durumu."""
    return {"ayar": _bul(disa_aktar.ayar_oku, ad), "is": disa_aktar.is_durumu(ad),
            "varsayilan_hedef": _bul(disa_aktar.varsayilan_hedef, ad)}


@app.put("/api/proje/{ad}/disa-aktar/ayar")
def disa_aktar_ayari(ad: str, govde: dict = Body(...)):
    return _bul(disa_aktar.ayar_yaz, ad, govde)


@app.post("/api/proje/{ad}/disa-aktar")
def disa_aktar_baslat(ad: str, govde: dict = Body(default={})):
    """Dışa aktarmayı başlat; `hedef` verilirse video bitince o konuma kaydedilir."""
    _bul(veri.proje, ad)
    try:
        return disa_aktar.baslat(ad, (govde or {}).get("hedef"))
    except disa_aktar.DisaAktarimHatasi as hata:
        raise HTTPException(status_code=409, detail=str(hata)) from None


@app.post("/api/proje/{ad}/disa-aktar/konum")
def disa_aktar_konum(ad: str, govde: dict = Body(default={})):
    """Windows'un "Farklı kaydet" penceresini aç; seçilen yolu döndür (vazgeçilirse `null`).

    Pencere yalnızca uygulama penceresinde (pywebview) açılır; tarayıcıyla çalışırken
    `pencere: false` döner ve editör yolu elle yazdırır.
    """
    baslangic = str((govde or {}).get("hedef") or "") or _bul(disa_aktar.varsayilan_hedef, ad)
    try:
        import webview
    except ImportError:
        return {"pencere": False, "hedef": None}
    if not webview.windows:
        return {"pencere": False, "hedef": None}
    yol = Path(baslangic)
    secim = webview.windows[0].create_file_dialog(
        webview.FileDialog.SAVE, directory=str(yol.parent) if yol.parent.is_dir() else "",
        save_filename=yol.name, file_types=("MP4 video (*.mp4)",))
    secilen = (secim[0] if isinstance(secim, (list, tuple)) else secim) if secim else None
    if secilen:
        try:
            secilen = disa_aktar.hedef_dogrula(secilen)
        except disa_aktar.DisaAktarimHatasi as hata:
            raise HTTPException(status_code=400, detail=str(hata)) from None
    return {"pencere": True, "hedef": secilen}


@app.post("/api/proje/{ad}/disa-aktar/goster")
def disa_aktar_goster(ad: str):
    """Son dışa aktarılan videoyu Dosya Gezgini'nde seçili göster."""
    is_ = disa_aktar.is_durumu(ad) or {}
    yol = is_.get("yol") if is_.get("durum") == "bitti" else None
    if not yol or not Path(yol).is_file():
        raise HTTPException(status_code=404, detail="Dışa aktarılmış video bulunamadı.")
    import subprocess
    subprocess.Popen(["explorer", f"/select,{Path(yol)}"])
    return {"yol": yol}


@app.post("/api/proje/{ad}/disa-aktar/iptal")
def disa_aktar_iptal(ad: str):
    return disa_aktar.iptal_et(ad) or {}


# ── Araçlar ve API hesapları (StudioFlow'un sayfaları, Gradio köprüsüyle) ────────
def _kopru(islev, *argumanlar):
    try:
        return islev(*argumanlar)
    except kopru.KopruHatasi as hata:
        raise HTTPException(status_code=404, detail=str(hata)) from None


@app.get("/api/araclar")
def araclar():
    return _kopru(kopru.KOPRU.liste)


@app.get("/api/arac/{anahtar}")
def arac(anahtar: str):
    """Aracın bileşen ağacı; açılış işlevleri (listeler, özetler) arka planda başlar."""
    agac = _kopru(kopru.KOPRU.agac, anahtar)
    agac["is"] = kopru.KOPRU.acilis_olaylari(anahtar)
    return agac


@app.post("/api/arac-olay")
def arac_olay(govde: dict = Body(...)):
    """Bileşen olayı (click, change…): bağlı StudioFlow işlevi arka planda çalışır."""
    return {"is": _kopru(kopru.KOPRU.olay, int(govde.get("bilesen") or 0), govde.get("olay") or "",
                         govde.get("degerler") or {})}


@app.post("/api/arac-deger")
def arac_deger(govde: dict = Body(...)):
    kopru.KOPRU.degerleri_yaz(govde.get("degerler") or {})
    return {}


@app.get("/api/arac-is/{no}")
def arac_is(no: int, son: int = 0):
    return _kopru(kopru.KOPRU.is_durumu, no, son)


@app.post("/api/arac-yukle")
async def arac_yukle(istek: Request, dosya: str = "dosya"):
    return kopru.KOPRU.yukle(unquote(dosya), await istek.body())


@app.post("/api/arac-ef-indir")
def arac_ef_indir(govde: dict = Body(...)):
    return {"is": kopru.KOPRU.ef_indir(govde.get("aday") or {})}


@app.get("/arac-dosya/{anahtar}/{ad}")
def arac_dosyasi(anahtar: str, ad: str):
    dosya = kopru.KOPRU.dosya(anahtar)
    if dosya is None or not Path(dosya).is_file():
        raise HTTPException(status_code=404, detail="Dosya yok")
    return FileResponse(dosya, filename=Path(dosya).name, content_disposition_type="inline",
                        headers=_ONBELLEKSIZ)


# ── Dosyalar ───────────────────────────────────────────────────────────────────
_ONBELLEKSIZ = {"Cache-Control": "no-cache"}


@app.get("/medya/{ad}/{yol:path}")
def medya(ad: str, yol: str):
    dosya = veri.proje_dosyasi(ad, yol)
    if dosya is None:
        raise HTTPException(status_code=404, detail="Dosya yok")
    # Kare ve klipler üretim sırasında değişebilir: tarayıcı her seferinde doğrulasın.
    return FileResponse(dosya, headers=_ONBELLEKSIZ)


def _icinde(kok, yol):
    try:
        hedef = (kok / yol).resolve()
        hedef.relative_to(kok.resolve())
    except (ValueError, OSError):
        return None
    return hedef if hedef.is_file() else None


@app.get("/dosyalar/{ad}/{yol:path}")
def editor_dosyasi(ad: str, yol: str):
    """Editöre yüklenen/üretilen dosyalar (karakter görseli, referans ses, müzik)."""
    dosya = _icinde(taslak.DOSYALAR / depo.slug(ad), yol) if depo.slug(ad) else None
    if dosya is None:
        raise HTTPException(status_code=404, detail="Dosya yok")
    return FileResponse(dosya, headers=_ONBELLEKSIZ)


@app.get("/kutuphane/{yol:path}")
def kutuphane_gorseli(yol: str):
    dosya = kutuphane.dosya(yol)
    if dosya is None:
        raise HTTPException(status_code=404, detail="Dosya yok")
    return FileResponse(dosya)


@app.get("/gecici/{ad}")
def gecici(ad: str):
    """Geçici önizlemeler (ses testi, altyazı önizlemesi, karakter referansı)."""
    dosya = _icinde(katman.GECICI, ad)
    if dosya is None:
        raise HTTPException(status_code=404, detail="Dosya yok")
    return FileResponse(dosya, headers=_ONBELLEKSIZ)


app.mount("/", StaticFiles(directory=ayar.WEB, html=True), name="web")
