"""Ses efektleri: kayıtlı efekt izini videoya ekle, kaldır, sil (arayüz paketleriyle).

Efekt `proje.mp4`e ayrı bir işlemle **gömülmez**: sesin tamamı (anlatım/dublaj +
müzik + efekt) `muzik._muzigi_uygula` ile her seferinde baştan kurulur. Böylece üst
üste eklemek efekti katlamaz, dublaj/altyazı videoyu yeniden kurduğunda efekt müzikle
birlikte kendiliğinden geri gelir (`muzik_geri_uygula`) ve seviye değişikliği için
efektleri yeniden hazırlamak gerekmez.
"""
import time
from datetime import datetime

from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.katmanlar import efektler
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.dosya_yollari import sure_metni, sure_ozeti
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.ilerleme import arayuz_paketi, bos_ilerleme_html
from studioflow.proje.katmanlar.muzik import ses_katmanini_kur
from studioflow.proje.sabitler import EFEKT_VARSAYILAN_SEVIYE
from studioflow.proje.yeniden_deneme import hata_yaz


def _hedef(ad):
    return proje_hedefi(ad, "ses efekti ekle",
                        "Ses efekti için önce bir proje seç ya da proje adını yaz.")


def efekt_paketi(veri, klasor, mesaj, onizleme=None):
    """Efekt panelinin çıktı paketi: durum, liste damgası, seçim, seviye, önizleme +
    proje görünümü (video, dosyalar, ilerleme)."""
    durum = efektler.efekt_durumu_oku(klasor)
    if onizleme is None:
        kayit = next((k for k in efektler.efekt_kayitlari(klasor)
                      if k["ad"] == (durum["secim"] or durum["ekli"])), None)
        onizleme = str(klasor / kayit["dosya"]) if kayit else None
    return (mesaj, f"{time.time():.6f}", durum["secim"], durum["seviye"],
            onizleme) + arayuz_paketi(veri, mesaj)[1:]


def efekt_bos(mesaj):
    """Proje seçilmemişse/hata varsa efekt panelinin boş paketi."""
    return (mesaj, "", "", EFEKT_VARSAYILAN_SEVIYE, None, "", [], [], None, bos_ilerleme_html())


def efekt_durum_paketi(ad, mesaj, onizleme=None):
    """Yalnızca durum metniyle efekt paketi (hazırlama bitince/hata verince)."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return efekt_bos(mesaj or hata)
    return efekt_paketi(veri, klasor, mesaj, onizleme)


def efekt_listesi(ad):
    """Arayüz için kayıtlı efektler (dosyası duranlar, kayıt sırasıyla)."""
    veri, klasor, hata = _hedef(ad)
    return [] if hata else efektler.efekt_kayitlari(klasor)


def ekli_efekt_adi(ad):
    veri, klasor, hata = _hedef(ad)
    return "" if hata else efektler.efekt_durumu_oku(klasor)["ekli"]


def efekt_secimi(ad):
    veri, klasor, hata = _hedef(ad)
    return "" if hata else efektler.efekt_durumu_oku(klasor)["secim"]


def efekt_sec(ad, isim):
    """Paneldeki seçimi projeye yaz; seçilen adı döndür (arayüz durumuna yazılır)."""
    veri, klasor, hata = _hedef(ad)
    isim = efektler.efekt_adi(isim)
    if hata or not isim:
        return isim
    durum = efektler.efekt_durumu_oku(klasor)
    if isim in {k["ad"] for k in durum["kayitlar"]}:
        durum["secim"] = isim
        try:
            efektler.efekt_durumu_yaz(klasor, durum)
        except OSError:
            pass
    return isim


def efekt_sahne_listesi(ad):
    """Manuel panel için videodaki sahneler: `[{"index", "bas", "sure", "metin"}]`."""
    veri, klasor, hata = _hedef(ad)
    return [] if hata else efektler.efekt_sahneleri(veri, klasor)


def efekt_videoya_ekle(ad, secili, seviye=EFEKT_VARSAYILAN_SEVIYE):
    """Seçili efekt kaydını videoya ekle: ses akışı anlatım + müzik + efektle yeniden kurulur."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return efekt_bos(hata)
    if not (klasor / "proje.mp4").is_file():
        return efekt_paketi(veri, klasor, "`proje.mp4` yok; önce adımlar birleştirilmeli.")
    if not FFMPEG.ffmpeg():
        return efekt_paketi(veri, klasor, "ffmpeg bulunamadı; ses efekti eklenemedi.")
    isim = efektler.efekt_adi(secili)
    kayit = next((k for k in efektler.efekt_kayitlari(klasor) if k["ad"] == isim), None)
    if kayit is None:
        return efekt_paketi(veri, klasor, "Videoya eklemek için listeden bir ses efekti "
                                          "kaydı seç.")
    onceki = efektler.efekt_durumu_oku(klasor)
    try:
        efektler.ekli_efekti_yaz(klasor, isim, seviye)
    except OSError as exc:
        return efekt_paketi(veri, klasor, "Efekt durumu yazılamadı: " + _ilk_satir(exc, 200))
    ok, mesaj = ses_katmanini_kur(veri, klasor)
    if not ok:
        try:
            efektler.ekli_efekti_yaz(klasor, onceki["ekli"], onceki["seviye"])
        except OSError:
            pass
        return efekt_paketi(veri, klasor, hata_yaz(veri, None, "Ses efekti ekleme",
                                                   "Ses efekti videoya eklenemedi: "
                                                   + _ilk_satir(mesaj, 200)))
    seviye = efektler.efekt_durumu_oku(klasor)["seviye"]
    video_sure = FFMPEG.medya_suresi(klasor / "proje.mp4")
    uyari = ""
    if video_sure > 0 and abs(video_sure - kayit["sure"]) > 0.5:
        uyari = (f" ⚠ Efekt izi {sure_metni(kayit['sure'])}, video {sure_metni(video_sure)}: "
                 "sahne süreleri değişmiş olabilir, efektleri yeniden hazırla.")
    baslik = f"'{isim}' ses efektleri videoya eklendi (seviye %{seviye:g})."
    veri["durum"] = "tamam"
    veri["son_not"] = baslik
    not_ekle(veri, baslik + f" [{datetime.now():%H:%M:%S}]")
    proje_yaz(veri)
    return efekt_paketi(veri, klasor, baslik + " " + sure_ozeti(veri) + uyari
                        + " Anlatım ve müzik korunur; efekt onların altına karışır.")


def efektleri_kaldir(ad):
    """Videodaki efekt katmanını kaldır; kayıtlar silinmez."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return efekt_bos(hata)
    if not efektler.efekt_durumu_oku(klasor)["ekli"]:
        return efekt_paketi(veri, klasor, "Videoda ekli ses efekti yok; kaldırılacak bir "
                                          "şey yok.")
    if not (klasor / "proje.mp4").is_file():
        return efekt_paketi(veri, klasor, "`proje.mp4` yok; önce adımlar birleştirilmeli.")
    try:
        efektler.ekli_efekti_yaz(klasor, "")
    except OSError as exc:
        return efekt_paketi(veri, klasor, "Efekt durumu yazılamadı: " + _ilk_satir(exc, 200))
    ok, mesaj = ses_katmanini_kur(veri, klasor)
    if not ok:
        return efekt_paketi(veri, klasor, hata_yaz(veri, None, "Ses efekti kaldırma",
                                                   "Ses efekti videodan kaldırılamadı: "
                                                   + _ilk_satir(mesaj, 200)))
    baslik = "Ses efektleri videodan kaldırıldı."
    veri["son_not"] = baslik
    not_ekle(veri, baslik + " Kayıtlar listede durur.")
    proje_yaz(veri)
    return efekt_paketi(veri, klasor, baslik + " Anlatım ve müzik videoda kaldı; "
                                               "kayıtlı efektler silinmedi.")


def efekt_sil(ad, isim):
    """Kaydı listeden ve diskten kaldır; videoda duyuluyorsa efekt katmanı da çıkar."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return efekt_bos(hata)
    isim = efektler.efekt_adi(isim)
    durum = efektler.efekt_durumu_oku(klasor)
    kayit = next((k for k in durum["kayitlar"] if k["ad"] == isim), None)
    if kayit is None:
        return efekt_paketi(veri, klasor, f"'{isim}' listede yok.")
    videoda = durum["ekli"] == isim
    durum["kayitlar"] = [k for k in durum["kayitlar"] if k["ad"] != isim]
    durum["secim"] = "" if durum["secim"] == isim else durum["secim"]
    durum["ekli"] = "" if videoda else durum["ekli"]
    try:
        efektler.efekt_durumu_yaz(klasor, durum)
    except OSError as exc:
        return efekt_paketi(veri, klasor, "Efekt listesi yazılamadı: " + _ilk_satir(exc, 200))
    for yol in (klasor / kayit["dosya"] if kayit["dosya"] else None,
                efektler.efekt_klasoru(klasor) / f"{isim}-kaynaklar.txt"):
        if yol is not None:
            try:
                yol.unlink(missing_ok=True)
            except OSError:
                pass
    mesaj = f"**{isim}** listeden kaldırıldı; dosyası silindi."
    if videoda and (klasor / "proje.mp4").is_file():
        ok, ayrinti = ses_katmanini_kur(veri, klasor)
        mesaj += (" Efekt videoda duyuluyordu; efekt katmanı videodan kaldırıldı." if ok
                  else " Efekt videodan kaldırılamadı: " + _ilk_satir(ayrinti, 200))
    not_ekle(veri, f"'{isim}' ses efekti kaydı silindi.")
    proje_yaz(veri)
    return efekt_paketi(veri, klasor, mesaj)
