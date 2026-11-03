"""Proje akışı: seslendirme → sahneleme → prompt → **kareler** → görsel onayı → videolar.

Akış sahne klipleriyle biter; genel video (`proje.mp4`) birleştirilmez, son video
editörde **Dışa aktar** ile kliplerden kurulur (kullanıcı kararı, 23.10.2026).

Sıra bilinçlidir: bütün kareler videolardan **önce** üretilir ve akış orada durur.
Kullanıcı kareleri topluca görüp onaylayana kadar tek bir klip bile üretilmez; pahalı
olan video üretimidir, beğenilmeyen bir kare için harcanmamalıdır. Onay `proje.txt`e
yazılır (`Görsel onayı`), yani uygulama kapansa da kalır. Aşama mantığı metinde aynen
korunur: kare hazır olan adım `YARIM`, klibi de biten adım `TAMAM`dır.
"""
from datetime import datetime
from pathlib import Path

from studioflow.proje.adim_promptlari import ILK_SAHNE_INDEX
from studioflow.proje.akis_kanca import (
    ilk_sahneyi_tazele, kanca_geri_al, kanca_izini_yaz, kanca_yedegi)
from studioflow.proje.akis_kare import adim_gorsel, gorsel_hazir
from studioflow.proje.akis_sahne import (
    adim_prompt, adimlari_kur, eksik_prompt_adimlari, prompt_isi_var, sahne_plani_uret)
from studioflow.proje.akis_servis import (
    VIDEO_AGNES, VIDEO_HF, VIDEO_LTX, VIDEO_SERVIS_ADI, ses_kontrol, ses_uretici, video_hazirla,
    video_kontrol, video_kontrollu, video_uretici, video_uretici_agnes, video_uretici_ltx)
from studioflow.proje import coklu_uretim, karakterler as kadro
from studioflow.proje.ayar_normalize import ayarlari_normalize
from studioflow.proje.on_ayarlar import on_ayar_video_servisi
from studioflow.proje.birlestirme import adim_sifirla, klibi_sahneye_uzat
from studioflow.proje.calisma_kilidi import CALISAN, IPTAL
from studioflow.proje.depo import (
    adim_dosya_adi, adim_suresi, adim_tamam, calismayi_temizle, dosya_kopyala, dosya_suresi,
    proje_klasoru, slug)
from studioflow.proje.dosya import not_ekle, proje_oku, proje_yaz
from studioflow.proje.ilerleme import arayuz_paketi, bos_paket, paket_ozeti
from studioflow.proje.katmanlar.ses_ekleme import ekleme_sifirla
from studioflow.proje.sabitler import (
    ADIM_DENEMELERI, DOSYA_ADI, MUZIK_VARSAYILAN_DUCKING, SES_HIZ_ALT_SINIRI, YENIDEN_SINIR)
from studioflow.proje.sahne_kalitesi import kare_izi
from studioflow.proje.sahne_stratejileri import strateji_etiketi
from studioflow.proje.strateji_gecisi import stratejiyi_uygula
from studioflow.proje.yeniden_deneme import (
    adim_calistir, adim_hesapli, denemeler_tukendi, denemeli, dur_turu, hata_yaz)
from studioflow.saglayicilar import gorsel_cloudflare, video_huggingface, video_ltx
from studioflow.saglayicilar.hesap_havuzu import ELENEN, SES_HIZMET, aktif_anahtar, hesap_kimligi
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR


def _yeni_durum(ad, metin, ayarlar):
    return {
        "ad": ad.strip(),
        "slug": slug(ad),
        "olusturuldu": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "guncellendi": "",
        "durum": "hazir",
        "deneme": {},
        "metin": metin,
        "ayarlar": ayarlar,
        "adimlar": [],
        "ses": {"durum": "BEKLİYOR", "dosya": "", "sure": 0.0, "bitti": ""},
        # Görsel onayı: kareler üretildikten sonra kullanıcı onaylayana dek videolar
        # başlamaz (bkz. `akis_calistir` 5. adım).
        "gorsel_onay": "BEKLİYOR",
        # Yeni projenin video servisi ön ayardan gelir (Animasyon → LTX-2.3); sonradan
        # görsel onayındaki düğmeyle değiştirilebilir.
        "video_servisi": on_ayar_video_servisi(ayarlar["video"].get("on_ayar")),
        # Kanca izi: 1. sahnenin prompt'u hangi ilk sahne metniyle yazıldı.
        "kanca_izi": "",
        "birlestirme": "BEKLİYOR",
        "birlestirme_bicim": "",
        "birlestirme_dosya": "",
        "birlestirme_bitti": "",
        # Çok dilli ses: ham video (ses ve altyazısı olmayan temel dosya) ve videoya ekli dil.
        "ham_video": "",
        "ekli_dil": "",
        # proje.mp4'e sonradan eklenenler: ses (mux) ve gömülü altyazı.
        "ses_ekleme": "BEKLİYOR",
        "ses_ekleme_bitti": "",
        "altyazi_ekleme": "BEKLİYOR",
        "altyazi_ekleme_bitti": "",
        # Müzik katmanı: videoya eklenen müziklerin sıralı listesi ve tekrar tercihi.
        "muzik_ekleme": "BEKLİYOR",
        "muzik_ekleme_bitti": "",
        "muzikler": [],
        "muzik_tekrarla": False,
        "muzik_ducking": MUZIK_VARSAYILAN_DUCKING,
        "gunluk": [],
        "son_not": "",
    }


def _ekran_ai(ayarlar):
    """Ekranda seçili prompt yapay zekâsı; geçersizse boş metin (kayıt korunur).

    Arayüz dört servisten birini gönderir (`ai_secenekleri`). Tanınmayan/eski bir
    değer geldiğinde projede kayıtlı seçim **ezilmez**: yarım kimlikle istek atılmaz.
    """
    secili = ((ayarlar or {}).get("video") or {}).get("ai")
    return secili if secili in AI_SAGLAYICILAR else ""


def _hazirla(ad, metin, ayarlar):
    """(durum sözlüğü, klasör, hata mesajı) döndür.

    Var olan projede model ve ses ayarları metinden okunur. **Sahne stratejisi ve
    prompt yapay zekâsı** (`video.ai`, `video.model`) ekrandaki seçimden alınır;
    strateji değişmişse eski çıktılar arşivlenir ve sahneler yeniden planlanır,
    yapay zekâ değişmişse yalnızca kalan sahneleri o servis yazar. Diğer ayarlar
    için metnin AYARLAR bölümü düzenlenir. Var olan projede kayıtlı metin korunur,
    ekrandaki metin yalnızca proje yeniyken kullanılır. Böylece bir projenin metni
    ya da prompt'u başka bir projeye geçmez.
    """
    ad, metin = (ad or "").strip(), (metin or "").strip()
    if not ad:
        return None, None, "Proje adı gerekli."
    klasor = proje_klasoru(ad)
    veri = proje_oku(klasor) if klasor.is_dir() else None
    if veri is None:
        if klasor.is_dir() and any(klasor.iterdir()):
            return None, None, (f"'{ad}' klasöründe okunabilir bir {DOSYA_ADI} yok. "
                                "İlerleme yalnızca bu dosyadan okunur; dosyayı düzelt ya da "
                                "projeyi silip yeniden oluştur.")
        if not metin:
            return None, None, "Anlatım metnini yaz."
        veri = _yeni_durum(ad, metin, ayarlari_normalize(ayarlar))
        hata = _kadroyu_kur(veri, klasor, veri["ayarlar"]["video"]["karakterler"])
        if hata:
            return None, None, hata
        not_ekle(veri, "Proje oluşturuldu.")
        return veri, klasor, ""
    # Yazma hedefi **seçilen klasör** olmalı. `proje_oku` slug'ı dosyanın içindeki
    # `Proje` satırından türetir; klasör elle yeniden adlandırılmış ya da kopyalanmışsa
    # bu ad başka bir projeyi gösterir ve akış yanlışlıkla **onun** kaydının üzerine
    # yazardı. Aynı koruma sahne/görsel yenilemede de var (bkz. `yonetim`).
    veri["slug"] = slug(ad)
    try:
        arsiv = stratejiyi_uygula(veri, klasor, ayarlar)
    except (OSError, ValueError) as exc:
        return None, None, f"Strateji değişimi uygulanamadı: {exc}"
    if arsiv:
        not_ekle(veri, "Seçili strateji uygulandı: " +
                 strateji_etiketi(veri["ayarlar"]["video"]["sahne_stratejisi"]) +
                 f". Sahne planı ve promptlar yenilenecek; eski üretim: {arsiv}")
    # Prompt'ları yazan yapay zekâ da **ekrandaki seçimden** uygulanır (strateji gibi).
    # Eskiden mevcut projede `video.ai` yalnızca proje dosyasından okunuyordu: ekranda
    # Cloudflare seçilse bile kayıtlı Gemini (proje.txt) kalan sahnelerin prompt'larını
    # yazmaya devam ediyordu ve seçim hiçbir işe yaramıyordu.
    hata = _kadroyu_uygula(veri, klasor, ayarlar)
    if hata:
        return None, None, hata
    secili_ai = _ekran_ai(ayarlar)
    eski_ai = veri["ayarlar"]["video"].get("ai") or ""
    if secili_ai and secili_ai != eski_ai:
        veri["ayarlar"]["video"]["ai"] = secili_ai
        # Model adları servisler arasında taşınamaz: seçimle birlikte yenilenir.
        veri["ayarlar"]["video"]["model"] = str(
            (((ayarlar or {}).get("video") or {}).get("model") or ""))
        not_ekle(veri, "Prompt yapay zekâsı ekrandaki seçimden uygulandı: "
                       + AI_SAGLAYICILAR[secili_ai]["label"]
                       + (f" (kayıtlı: {AI_SAGLAYICILAR[eski_ai]['label']})"
                          if eski_ai in AI_SAGLAYICILAR else "")
                       + ". Yazılmış prompt'lar korunur; kalan sahneleri bu servis yazar.")
    kayitli = (veri.get("metin") or "").strip()
    if veri["ses"]["durum"] == "TAMAM":
        if metin and metin != veri.get("metin"):
            not_ekle(veri, "Anlatım metni bu projede zaten seslendirilmiş; yeni metin yok "
                            "sayıldı. Baştan başlamak için projeyi silip aynı adla yeniden "
                            "başlat ya da farklı bir proje adı kullan.")
        not_ekle(veri, "Sahne stratejisi ekrandaki seçimden uygulandı; diğer üretim "
                        "ayarları ve seslendirme proje kaydından korundu.")
        if not arsiv:
            not_ekle(veri, "Mevcut projeye devam ediliyor; TAMAM olan adımlar atlanacak.")
    elif kayitli:
        # Var olan projede anlatım metni de **kendi kaydından** okunur (ayarlar gibi):
        # arayüzde başka bir projeden kalmış metin bu projeye yazılmaz, çünkü içerik
        # projeye özeldir. Metni değiştirmek için proje.txt düzenlenir.
        if metin and metin.strip() != kayitli:
            not_ekle(veri, "Bu projede kayıtlı bir anlatım metni var; ekrandaki metin yok "
                            "sayıldı (içerik her projenin kendi kaydında kalır). Metni "
                            f"değiştirmek için {DOSYA_ADI} içindeki ANLATIM METNİ bölümünü "
                            "düzenle ya da projeyi silip yeniden oluştur.")
    elif metin:
        veri["metin"] = metin
    return veri, klasor, ""


def _kadroyu_kur(veri, klasor, karakterler):
    """Kadroyu projeye yerleştir: model denetimi + referans görsellerin kopyası.

    Hata metni döner (boşsa sorun yok). Referans almayan modelde (SDXL, FLUX.1)
    karakterli proje **başlatılmaz**: kareler referanssız üretilir ve karakter her
    sahnede değişirdi; başka modele sessizce geçilmez, sebebi yazılır.
    """
    if not karakterler:
        return ""
    model = veri["ayarlar"]["gorsel"]["model"]
    if not gorsel_cloudflare.referans_siniri(model):
        etiket = (gorsel_cloudflare.cf_model_spec(model) or {}).get("label", model)
        return (f"Karakterli proje referans görsel alan bir görsel modeli ister; seçili "
                f"model ({etiket}) referans almaz. Görsel modelini FLUX.2 klein 4B yap.")
    try:
        veri["ayarlar"]["video"]["karakterler"] = kadro.projeye_kopyala(karakterler, klasor)
    except (OSError, ValueError) as exc:
        return str(exc)
    not_ekle(veri, "Karakter kadrosu: " + ", ".join(k["ad"] for k in karakterler)
             + ". Her kare sahnede görünen karakterlerin referans görselleriyle üretilir.")
    return ""


def _kadroyu_uygula(veri, klasor, ayarlar):
    """Var olan projede kadro: kayıt kazanır; kayıtta kadro yoksa ve henüz kare
    üretilmediyse ekrandaki kadro projeye eklenir (sonradan karakter eklemek için)."""
    kayitli = veri["ayarlar"]["video"].get("karakterler") or []
    ekrandaki = kadro.normalize((((ayarlar or {}).get("video") or {}).get("karakterler")))
    if kayitli:
        if not gorsel_cloudflare.referans_siniri(veri["ayarlar"]["gorsel"]["model"]):
            return _kadroyu_kur(veri, klasor, kayitli)
        if ekrandaki and [k["ad"] for k in ekrandaki] != [k["ad"] for k in kayitli]:
            not_ekle(veri, "Bu projenin kayıtlı bir karakter kadrosu var; ekrandaki kadro "
                           "yok sayıldı (kadro projenin kendi kaydında kalır).")
        return ""
    if not ekrandaki:
        return ""
    if any(adim.get("gorsel") for adim in veri["adimlar"]):
        not_ekle(veri, "Ekrandaki karakter kadrosu uygulanmadı: bu projede kareler zaten "
                       "üretildi. Karakterli üretim için yeni bir proje başlat.")
        return ""
    hata = _kadroyu_kur(veri, klasor, ekrandaki)
    if hata:
        return hata
    # Kadrosuz yazılmış prompt'lar karakter adlarını taşımaz; referans hiç devreye
    # girmezdi. Henüz kare yokken prompt'lar silinir ve kadroyla yeniden yazılır.
    yazilmis = [adim for adim in veri["adimlar"] if adim.get("image_prompt")]
    for adim in yazilmis:
        for alan in ("image_prompt", "video_prompt", "negative_prompt", "kontrol"):
            adim[alan] = ""
        for alan in ("sahne_plani", "karakterler"):
            adim.pop(alan, None)
    if yazilmis:
        not_ekle(veri, f"Kadro eklendi; {len(yazilmis)} sahnenin prompt'u karakterlerle "
                       "yeniden yazılacak.")
    return ""


def _ses_tamam(klasor, veri):
    """Seslendirme bitmiş ve dosya yerinde mi?"""
    yol = veri["ses"].get("dosya")
    return veri["ses"].get("durum") == "TAMAM" and bool(yol) and (klasor / yol).exists()


def _adim_video(veri, klasor, adim, deneme=1, servis=VIDEO_HF):
    """Adımın videosunu üret ve projeye yaz. Dönüş: `"ok"` · `"hata"` · `"durdu"`.

    Yeniden denemelerde video Space'lerinin önbelleği sıfırlanır: uykudan kalkan ya da
    kotası yenilenen Space sıranın önüne geçebilsin. `servis=VIDEO_AGNES` ise video
    Hugging Face yerine Agnes AI ile üretilir (tek anahtar; hesap sırası yoktur);
    `servis=VIDEO_LTX` ise LTX-2.3 Space'iyle, Hugging Face hesap sırasıyla üretilir.
    """
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])} video"
    if not _video_serbest(veri, klasor, adim):
        yield hata_yaz(veri, adim, baslik, "Kare kalite kontrolünü geçmedi; video üretilmedi.")
        return "hata"
    agnes, ltx = servis == VIDEO_AGNES, servis == VIDEO_LTX
    if deneme > 1 and servis == VIDEO_HF:
        video_huggingface.VARSAYILAN.sorunlulari_sifirla()
        yield f"{baslik} · {deneme}. deneme: video Space'leri yeniden kontrol ediliyor…"
    hedef = klasor / adim_dosya_adi(adim, ".mp4")
    uretim = (adim_calistir(veri, adim, baslik + " (Agnes AI)",
                            video_kontrollu(video_uretici_agnes(veri, adim, klasor)))
              if agnes else
              adim_hesapli(veri, adim, baslik + " (LTX-2.3)", "huggingface",
                           lambda hesap, kimlik: video_uretici_ltx(veri, adim, klasor, kimlik),
                           video_kontrol)
              if ltx else
              adim_hesapli(veri, adim, baslik, "huggingface",
                           lambda hesap, kimlik: video_uretici(veri, adim, klasor, kimlik),
                           video_kontrol))
    for tur, deger in uretim:
        if tur == "bildir":
            yield deger
            continue
        if tur == "dur":
            yield deger
            return dur_turu(veri)
        video = deger[1] if deger else None
        if not video:
            yield hata_yaz(veri, adim, baslik, deger[0] if deger else "Video dönmedi.")
            return "hata"
        dosya_kopyala(video, hedef)
        # LTX en fazla 8 sn üretir; sahne daha uzunsa klip burada sahneye uzatılır ki
        # son saniyeler hiçbir yerde (önizleme, birleştirme, dışa aktarma) donmasın.
        uzatildi, uzatma_notu = klibi_sahneye_uzat(hedef, adim_suresi(adim))
        if uzatildi:
            not_ekle(veri, f"{baslik} · {uzatma_notu}.")
        adim["video"] = adim_dosya_adi(adim, ".mp4")
        adim["durum"] = "TAMAM"
        adim["bitti"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        adim["hata"] = ""
        not_ekle(veri, f"{baslik} tamamlandı: {adim['gorsel']} + {adim['video']}"
                        + (" (Agnes AI)" if agnes else " (LTX-2.3)" if ltx else ""))
        proje_yaz(veri)
        yield f"{baslik} tamam · görsel + video yazıldı, metne işlendi."
        return "ok"
    yield hata_yaz(veri, adim, baslik, "Video üretilemedi.")
    return "hata"


def _deneme_dolu(adim, islem):
    """O işlemin deneme hakkı bitti mi? (`gorsel` · `video`)"""
    return int((adim.get("deneme") or {}).get(islem) or 0) >= YENIDEN_SINIR


def _adim_uret(veri, klasor, adim):
    """Tek adımı baştan üret: görsel, sonra video (eski tek adımlık yol).

    Akışın kendisi artık **önce bütün kareleri, sonra bütün videoları** üretir
    (bkz. `_gorsel_asamasi`, `_video_asamasi`); bu işlev tek bir adımı uçtan uca
    yenilemek isteyen çağrılar için durur. Görsel ve video ayrı ayrı korunur: video
    hata verdiğinde hazır görsel yeniden üretilmez, yalnızca video yeniden denenir.

    Dönüş: `True` ise akış kesilmelidir (hata, durdurma ya da dolmuş deneme hakkı).
    """
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])}"
    # Deneme hakkı dolmuş bir işlem varsa adım baştan silinmez: hazır dosyalar korunur,
    # akış hemen durur; kullanıcı **Deneme hakkını yenile** ile devam eder.
    dolu = [islem for islem in ADIM_DENEMELERI if _deneme_dolu(adim, islem)]
    if dolu:
        yield arayuz_paketi(veri, denemeler_tukendi(veri, baslik, dolu[0], adim))
        return True
    adim_sifirla(klasor, adim)
    adim["durum"] = "YARIM"
    not_ekle(veri, f"{baslik} baştan üretiliyor (görsel + video).")
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"{baslik} · görsel üretiliyor…")
    if (yield from denemeli(veri, f"{baslik} görsel", "gorsel", adim,
                             lambda deneme: adim_gorsel(veri, klasor, adim))):
        return True
    yield arayuz_paketi(veri, f"{baslik} · görsel tamam, video üretiliyor…")
    return (yield from denemeli(veri, f"{baslik} video", "video", adim,
                                 lambda deneme: _adim_video(veri, klasor, adim, deneme)))


def _durdurulduysa(veri, klasor):
    """Kullanıcı **Durdur**'a bastıysa projeyi durdurulmuş olarak kapat.

    Dönüş: `True` ise akış kesilmelidir. Görsel ve video aşamalarının ikisi de aynı
    davranışı kullanır, böylece durdurma hangi aşamada olursa olsun metne aynı
    şekilde yazılır.
    """
    if not IPTAL.is_set():
        return False
    veri["durum"] = "durduruldu"
    veri["son_not"] = "Kullanıcı durdurdu."
    not_ekle(veri, veri["son_not"])
    proje_yaz(veri)
    yield arayuz_paketi(veri, "Durduruldu. **Kaldığı yerden devam et** ile sürdürebilirsin.")
    return True


def _gorsel_asamasi(veri, klasor):
    """**Bütün adımların karelerini** üret; videolara hiç dokunulmaz.

    Kullanıcı kareleri videolardan önce topluca görür ve onaylar. Yeni bir kare
    üretildiğinde görsel onayı **sıfırlanır**: görülmemiş bir kare için video
    üretilmesin. Adım durumu kare hazır olunca `YARIM`dır — yani metindeki aşama
    mantığı aynen korunur ("görsel var, video yok").

    **Çoklu üretim** seçiliyse eksik kareler önce hesaplara bölünüp paralel üretilir
    (bkz. `coklu_uretim`); kurulamazsa aynı adımlar aşağıdaki tekli döngüyle üretilir.

    Dönüş: `True` ise akış kesilmelidir.
    """
    if coklu_uretim.coklu_mu():
        bekleyen = [adim for adim in veri["adimlar"] if not gorsel_hazir(klasor, adim)]
        dolu = next((adim for adim in bekleyen if _deneme_dolu(adim, "gorsel")), None)
        if dolu:
            yield arayuz_paketi(veri, denemeler_tukendi(
                veri, f"Adım {dolu['index']}/{len(veri['adimlar'])}", "gorsel", dolu))
            return True
        if bekleyen:
            sonuc = yield from coklu_uretim.calistir(
                veri, "görsel", veri["ayarlar"]["gorsel"]["provider"], bekleyen,
                lambda adim: _kare_adimi(veri, klasor, adim))
            if sonuc is not None:
                return sonuc
    for adim in veri["adimlar"]:
        if IPTAL.is_set():
            return False          # durdurma akışın kendi kontrolünde ele alınır
        if gorsel_hazir(klasor, adim):
            # ANA KURAL (29.09.2026): bir kare değişirse yalnızca o kare değişir. Var
            # olan kareye hiç dokunulmaz, denetlenmez de; yalnızca karesi olmayan adım
            # üretilir (ve yalnızca o denetlenir, bkz. `adim_gorsel`).
            continue
        if (yield from _kare_adimi(veri, klasor, adim)):
            return True
    return False


def _kare_adimi(veri, klasor, adim):
    """Karesi olmayan **tek** adımın karesini üret (tekli ve çoklu üretim ortak gövdesi).

    Dönüş: `True` ise akış kesilmelidir.
    """
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])}"
    if _deneme_dolu(adim, "gorsel"):
        yield arayuz_paketi(veri, denemeler_tukendi(veri, baslik, "gorsel", adim))
        return True
    if adim.get("durum") == "TAMAM":
        not_ekle(veri, f"Adım {adim['index']} metinde TAMAM görünüyordu ama karesi "
                        "diskte yok; adım baştan üretilecek.")
    # Karesi olmayan adımın eski klibi de geçersizdir: ikisi birlikte silinir.
    adim_sifirla(klasor, adim)
    adim["durum"] = "BEKLİYOR"
    # Yeni kare üretiliyor: onay sıfırlanır, videolar yeniden onay bekler.
    veri["gorsel_onay"] = "BEKLİYOR"
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"{baslik} · görsel üretiliyor…")
    if (yield from denemeli(veri, f"{baslik} görsel", "gorsel", adim,
                             lambda deneme: adim_gorsel(veri, klasor, adim))):
        return True
    adim["durum"] = "YARIM"
    proje_yaz(veri)
    return False


def _video_serbest(veri, klasor, adim):
    """Adımın klibi üretilebilir mi: kalite kontrolü geçti **ya da** kullanıcı onayladı.

    Kullanıcı kareleri görüp **Görselleri onayla**'ya bastıysa karar onundur; hakemin
    "kaldı" kararı videoyu engellemez (29.09.2026: onay verildiği hâlde kapı onayı
    sıfırlıyor, hiçbir video üretilmiyordu).
    """
    return veri.get("gorsel_onay") == "VERİLDİ" or _kalite_hazir(klasor, adim)


def _kalite_hazir(klasor, adim):
    if "sahne_plani" not in adim:
        return True  # Eski projeler, strateji değişene kadar mevcut akışı sürdürür.
    if adim.get("kalite_durumu") != "gecti" or not adim.get("hareket_izi"):
        return False
    # Önceki karenin değişmesi bu karenin onayını **bozmaz** (ANA KURAL, 29.09.2026):
    # eskiden süreklilik izi tutmayınca komşu kare yeniden denetleniyor ya da
    # üretiliyordu. Onay yalnızca bu karenin kendisi/planı/hareketi değişince düşer.
    try:
        return adim["hareket_izi"] == kare_izi(klasor / adim["gorsel"], adim)
    except (OSError, KeyError):
        return False


def _video_asamasi(veri, klasor, servis=VIDEO_HF):
    """**Bütün adımların videolarını** üret (kareler hazır ve onaylanmış olmalı).

    `servis` videoları üreten servistir (bkz. `VIDEO_SERVIS_ADI`). **Çoklu üretim**
    seçiliyse bekleyen klipler Hugging Face hesaplarına bölünüp paralel üretilir (Agnes
    tek anahtarlı olduğu için tekli kalır). Dönüş: `True` ise akış kesilmelidir.
    """
    if coklu_uretim.coklu_mu():
        bekleyen = [adim for adim in veri["adimlar"] if not adim_tamam(klasor, adim)]
        for adim in bekleyen:
            if (yield from _klip_engeli(veri, klasor, adim)):
                return True
        if bekleyen and servis == VIDEO_AGNES:
            mesaj = "Agnes AI tek anahtarla çalışır; videolar tekli üretimle üretilecek."
            not_ekle(veri, mesaj)
            yield arayuz_paketi(veri, mesaj)
        elif bekleyen:
            # LTX: grup sayısı kendi Space'imizin kuyruksuz kaldığı sınırda tutulur; her grup
            # kendi Space'ine gider (grup 1 → 1. Space, grup 2 → 2. Space …).
            ltx = servis == VIDEO_LTX
            sonuc = yield from coklu_uretim.calistir(
                veri, "video", "huggingface", bekleyen,
                lambda adim: _klip_adimi(veri, klasor, adim, servis),
                azami=video_ltx.ESZAMANLI if ltx else coklu_uretim.AZAMI_GRUP,
                grup_baglami=video_ltx.VARSAYILAN.space_sabitle if ltx else None)
            if sonuc is not None:
                return sonuc
    for adim in veri["adimlar"]:
        if IPTAL.is_set():
            return False
        if adim_tamam(klasor, adim):
            continue
        if (yield from _klip_engeli(veri, klasor, adim)):
            return True
        if (yield from _klip_adimi(veri, klasor, adim, servis)):
            return True
    return False


def _klip_engeli(veri, klasor, adim):
    """Adımın klibi üretilemiyorsa hatayı yaz. Dönüş: `True` ise akış kesilmelidir."""
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])}"
    if not _video_serbest(veri, klasor, adim):
        yield arayuz_paketi(veri, hata_yaz(veri, adim, "Sahne kalitesi",
            "Kare ve hareket kalite denetiminden geçmedi; video üretilmedi."))
        return True
    if not gorsel_hazir(klasor, adim):
        # Buraya normalde düşülmez: görsel aşaması her adımı karelemiş olmalı.
        yield arayuz_paketi(veri, hata_yaz(veri, adim, baslik,
                                    "Karesi olmayan adım için video üretilemez."))
        return True
    if _deneme_dolu(adim, "video"):
        yield arayuz_paketi(veri, denemeler_tukendi(veri, baslik, "video", adim))
        return True
    return False


def _klip_adimi(veri, klasor, adim, servis):
    """Tek adımın klibini üret (tekli ve çoklu üretim ortak gövdesi).

    Dönüş: `True` ise akış kesilmelidir.
    """
    baslik = f"Adım {adim['index']}/{len(veri['adimlar'])}"
    yield arayuz_paketi(veri, f"{baslik} · video üretiliyor"
                        + (f" ({VIDEO_SERVIS_ADI[servis]})…" if servis != VIDEO_HF else "…"))
    return (yield from denemeli(veri, f"{baslik} video", "video", adim,
                                lambda deneme: _adim_video(veri, klasor, adim, deneme,
                                                           servis)))


def _servis_hazirla(veri, klasor, servis):
    """Başka bir video servisine elle geçildi: bekleyen adımların **video** deneme
    sayaçlarını aç.

    Önceki serviste o adımın video hakkı çoğunlukla 3/3 dolmuştur; servis değiştiği için
    bu sayaç yeni servise temiz bir başlangıç verir (hazır kareler korunur).
    """
    acilan = 0
    for adim in veri["adimlar"]:
        if adim_tamam(klasor, adim):
            continue
        sayac = adim.setdefault("deneme", {})
        if int(sayac.get("video") or 0):
            sayac["video"] = 0
            acilan += 1
        if adim.get("durum") == "HATA":
            adim["durum"] = "YARIM" if gorsel_hazir(klasor, adim) else "BEKLİYOR"
            adim["hata"] = ""
    mesaj = (f"Videolar bu çalışmada **{VIDEO_SERVIS_ADI[servis]}** ile üretilecek (elle seçildi)."
             + (f" {acilan} adımın video deneme hakkı yenilendi." if acilan else ""))
    not_ekle(veri, mesaj)
    proje_yaz(veri)
    return mesaj


def _ses_asamasi(veri, klasor):
    """Seslendirmeyi üret, süresini ölç ve projeye yaz.

    Üreteç; iletileri sade metin olarak üretir ve bittiğinde durumu döndürür:
    `"ok"` · `"hata"` · `"durdu"`.
    """
    veri["ses"]["durum"] = "BEKLİYOR"
    not_ekle(veri, "Seslendirme başladı.")
    proje_yaz(veri)
    yield "Seslendirme üretiliyor…"
    son = None
    # Seslendirme yalnızca hesap kullanan sağlayıcılarda döner; Edge anahtarsız çalışır.
    hizmet = SES_HIZMET.get(veri["ayarlar"]["ses"]["provider"])
    akis = (adim_hesapli(veri, None, "Seslendirme", hizmet,
                          lambda hesap, kimlik: ses_uretici(veri, kimlik), ses_kontrol)
            if hizmet else
            adim_calistir(veri, None, "Seslendirme", ses_uretici(veri, hesap_kimligi(veri))))
    for tur, deger in akis:
        if tur == "sonuc":
            son = deger
        else:
            yield deger
            if tur == "dur":
                return dur_turu(veri)
    if not son or not son[1]:
        yield hata_yaz(veri, None, "Seslendirme",
                        son[0] if son else "Seslendirme yanıt vermedi.")
        return "hata"
    hedef = dosya_kopyala(son[1], klasor / "ses" / "seslendirme.wav")
    for ek in son[3] or []:
        dosya_kopyala(ek, klasor / "ses" / Path(ek).name)
    yeni_sure = round(dosya_suresi(hedef), 2)
    eski_sure = float(veri["ses"].get("sure") or 0)
    veri["ses"].update(durum="TAMAM", dosya="ses/seslendirme.wav", sure=yeni_sure,
                       bitti=f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    not_ekle(veri, f"Seslendirme tamam · {yeni_sure:.2f} saniye.")
    # Anlatım hızı olağan aralığın çok altındaysa ses fazladan bir şey okumuştur.
    # claudetest3 (29.09.2026): Gemini seslendirme stilini sesli okudu; 151 kelime 114 sn
    # sürdü (dakikada 79 kelime; olağanı 130–160) ve sahne zamanları kaydı.
    kelime = len((veri.get("metin") or "").split())
    if kelime >= 20 and yeni_sure > 0 and kelime / yeni_sure * 60 < SES_HIZ_ALT_SINIRI:
        not_ekle(veri, f"Seslendirme · UYARI: {kelime} kelime {yeni_sure:.0f} saniye sürdü "
                       f"(dakikada {kelime / yeni_sure * 60:.0f} kelime). Ses metin dışında bir "
                       "şey okumuş ya da uzun duraklamalar yapmış olabilir (ör. seslendirme "
                       "stilini sesli okuma). Sesi dinleyip gerekirse yeniden üret.")
    # Ses yeniden üretildiyse ve süre değiştiyse adım sınırları kayar: planı
    # eskisiyle sürdürmek yanlış olur, adımlar baştan kurulur.
    if veri["adimlar"] and abs(yeni_sure - eski_sure) > 0.05:
        not_ekle(veri, "Ses süresi değişti; adımlar baştan hesaplandı ve "
                        "hepsi BEKLİYOR'a çevrildi.")
        veri["adimlar"] = []
        for eski in (klasor / "gorseller").glob("adim-*"):
            eski.unlink(missing_ok=True)
        for eski in (klasor / "videolar").glob("adim-*"):
            eski.unlink(missing_ok=True)
        (klasor / "proje.mp4").unlink(missing_ok=True)
        ekleme_sifirla(veri)
    proje_yaz(veri)
    return "ok"


def proje_calistir(ad, metin, ayarlar, sahne_on_plan=None):
    """Projeyi baştan sona çalıştır; var olan projede metinden kaldığı yeri bulur.

    Aynı anda yalnızca bir proje çalışır (bkz. `CALISAN`). Videolar projenin kayıtlı
    servisiyle (`Video servisi`: Hugging Face, Agnes ya da LTX-2.3) üretilir; servis
    görsel onayındaki düğmeyle seçilir.
    `sahne_on_plan` ana sayfada üretilen plandır; sahneleme onu **aynen** kullanır.
    """
    IPTAL.clear()
    ad = (ad or "").strip()
    if CALISAN["slug"]:
        yield bos_paket(f"Şu anda '{CALISAN['slug']}' projesi çalışıyor. Önce **Durdur**'a bas "
                   "ya da bitmesini bekle.")
        return
    if not ad:
        yield bos_paket("Proje adı gerekli.")
        return
    CALISAN["slug"] = slug(ad)
    try:
        yield from akis_calistir(ad, metin, ayarlar, sahne_on_plan=sahne_on_plan)
    finally:
        CALISAN["slug"] = ""


# Proje akışının ara dosyalarını yazdığı `.calisma` alt klasörleri (bkz. `calisma_klasoru`).
URETIM_CALISMA = ("ses", "gorsel", "video")


def akis_calistir(ad, metin, ayarlar, video_servisi=None, prompt_onayli=False,
                  sahne_on_plan=None):
    """Proje akışı; bitince (hata ya da durdurmada da) ara dosyalar projeden silinir.

    Üretilen her dosya projenin kendi klasörüne yazılır: sağlayıcılar ara dosyaları
    `<proje>/.calisma` altına koyar, son dosyalar oradan projeye kopyalanır.
    """
    try:
        yield from _akis(ad, metin, ayarlar, video_servisi, prompt_onayli, sahne_on_plan)
    finally:
        if (ad or "").strip():
            klasor = proje_klasoru(ad)
            adlar = URETIM_CALISMA
            # Seslendirme bitmediyse okunmuş parçalar silinmez: **Kaldığı yerden devam**
            # yalnızca eksik parçaları okur (bkz. `ses_uretim.onceki_parcalar`).
            try:
                if (proje_oku(klasor).get("ses") or {}).get("durum") != "TAMAM":
                    adlar = tuple(a for a in URETIM_CALISMA if a != "ses")
            except Exception:
                pass
            calismayi_temizle(klasor, *adlar)


def _akis(ad, metin, ayarlar, video_servisi=None, prompt_onayli=False,
          sahne_on_plan=None):
    """Proje akışının kendisi; kilidi `proje_calistir` yönetir.

    `prompt_onayli=True` **prompt onayı kapısını atlar**: seslendirme bittikten sonra
    hangi yapay zekânın sahne planını/prompt'ları yazacağını kullanıcı seçip **Prompt
    üretimine başla**'ya bastığında gelir (bkz. `yonetim.prompt_uretimi_baslat`).
    Panel işlemleri (kare/prompt yenileme, görsel onayı) de kapıyı atlar: kullanıcı
    seçimini zaten panelden yapmıştır.

    `video_servisi` verilmezse projenin kayıtlı servisi (`Video servisi` satırı) kullanılır:
    bir servis (Agnes, LTX-2.3, Hugging Face) görsel onayında bir kez seçildiyse **Kaldığı
    yerden devam** da onunla sürer.
    """
    # Her çalışma temiz bir hesapla başlar: önceki çalışmada kotası dolan hesaplar
    # yeniden denenir (kota arada yenilenmiş olabilir).
    ELENEN.clear()
    veri, klasor, hata = _hazirla(ad, metin, ayarlar)
    if hata:
        yield bos_paket(hata)
        return
    if video_servisi in VIDEO_SERVIS_ADI:
        veri["video_servisi"] = video_servisi
    if video_servisi not in VIDEO_SERVIS_ADI:
        video_servisi = veri.get("video_servisi") or VIDEO_HF
    if video_servisi not in VIDEO_SERVIS_ADI:
        video_servisi = VIDEO_HF
    veri["durum"] = "calisiyor"
    not_ekle(veri, "Etkin sahne stratejisi: " +
             strateji_etiketi(veri["ayarlar"]["video"].get("sahne_stratejisi")))
    proje_yaz(veri)
    yield arayuz_paketi(veri, "Etkin sahne stratejisi: **" +
                       strateji_etiketi(veri["ayarlar"]["video"].get("sahne_stratejisi")) +
                       "**\n" + paket_ozeti(veri))

    # ── 1) seslendirme ───────────────────────────────────────────────
    # Her aşama `denemeli` ile sarılır: hata olursa akış durmaz, aynı işlem en fazla
    # `YENIDEN_SINIR` kez kendiliğinden yeniden başlatılır.
    if not _ses_tamam(klasor, veri):
        if (yield from denemeli(veri, "Seslendirme", "ses", None,
                                 lambda deneme: _ses_asamasi(veri, klasor))):
            return

    # ── 1.5) prompt onayı ────────────────────────────────────────────
    # Seslendirme hazır; sıra sahne planı ve prompt'larda. Akış **burada durur**:
    # hangi yapay zekânın yazacağını kullanıcı seçer ve **Prompt üretimine başla**'ya
    # basar. Yazacak iş yoksa (plan ve prompt'lar hazır) kapı devreye girmez.
    if not prompt_onayli and prompt_isi_var(veri):
        veri["durum"] = "prompt_onay"
        veri["son_not"] = ("Seslendirme hazır. Sahne planını ve prompt'ları yazacak "
                           "yapay zekâyı seçip **Prompt üretimine başla**'ya bas.")
        not_ekle(veri, "Prompt üretimi bekleniyor: seçilecek yapay zekâ ekrandan alınacak.")
        proje_yaz(veri)
        yield arayuz_paketi(veri, veri["son_not"])
        return

    # ── 2) adımlama ──────────────────────────────────────────────────
    if not veri["adimlar"]:
        sure = float(veri["ses"].get("sure") or 0)
        if sure <= 0:
            yield arayuz_paketi(veri, hata_yaz(veri, None, "Adımlama",
                                         "Ses dosyasının süresi okunamadı."))
            return
        yield arayuz_paketi(veri, "Sahne planı çıkarılıyor; süreler anlatımın içeriğine göre "
                           "belirlenecek…")
        sahneler, kaynak, gerekce = sahne_plani_uret(veri, klasor, sure,
                                                      on_plan=sahne_on_plan)
        adimlari_kur(veri, sure, sahneler)
        not_ekle(veri, f"Sahne planı kaynağı: {kaynak}" + (f" · {gerekce}" if gerekce else ""))
        proje_yaz(veri)
    yield arayuz_paketi(veri, f"Ses {float(veri['ses']['sure']):.2f} sn → "
                       f"{len(veri['adimlar'])} sahne · toplam "
                       + f"{sum(adim_suresi(a) for a in veri['adimlar']):g} sn video "
                       f"(süreler içeriğe göre değişken).")

    # ── 3) prompt'lar (görsel/video üretiminden önce hepsi hazır olur) ─
    # Kanca sahnesi: ilk sahne metni **değiştiyse** o sahnenin prompt'u boşaltılır ve
    # aşağıdaki aşama onu yapay zekâya diğer sahnelerle aynı biçimde yeniden yazdırır.
    # Metin aynıysa prompt olduğu gibi kalır (bkz. `ilk_sahneyi_tazele`).
    # Yedek **silinmeden önce** alınır: yeniden yazdırma başarısız olursa geri konur.
    kanca_yedek = kanca_yedegi(veri)
    if ilk_sahneyi_tazele(veri, klasor):
        yield arayuz_paketi(veri, f"Adım {ILK_SAHNE_INDEX} (kanca) prompt'u yeniden "
                            "yazdırılıyor: yazdığın içerik, diğer sahnelerle aynı "
                            "stil ve kamera diliyle kurulacak.")
    else:
        kanca_yedek = None          # tazeleme olmadı: geri alınacak bir şey yok
    if eksik_prompt_adimlari(veri):
        if (yield from denemeli(veri, "Prompt", "prompt", None,
                                 lambda deneme: adim_prompt(veri))):
            # Yeniden yazma başarısızsa eski kanca prompt'u geri konur: proje
            # başladığından kötü duruma düşmesin.
            if kanca_geri_al(veri, kanca_yedek):
                yield arayuz_paketi(veri, "Kanca prompt'u yeniden yazdırılamadı; "
                                    "önceki prompt geri kondu.")
            return
    # Prompt'lar yazıldı: kanca izini kaydet ki aynı metinle bir daha yazılmasın.
    if kanca_izini_yaz(veri):
        proje_yaz(veri)
    yield arayuz_paketi(veri, f"Bütün adımların prompt'ları hazır · "
                       f"{len(veri['adimlar'])} adım sırada.")

    # ── 4) bütün kareler (videolardan **önce**) ──────────────────────
    # Akışın sırası bilinçli: önce her adımın karesi üretilir, kullanıcı hepsini bir
    # arada görüp onaylar, videolar ancak ondan sonra başlar. Pahalı olan video
    # üretimidir; beğenilmeyen bir kare için klip harcanmasın.
    if (yield from _gorsel_asamasi(veri, klasor)):
        return
    if (yield from _durdurulduysa(veri, klasor)):
        return

    # ── 5) görsel onayı ──────────────────────────────────────────────
    # Onay `proje.txt`e yazılır (`Görsel onayı`), yani uygulama kapansa da kalır.
    # Videosu eksik adım yoksa (her şey TAMAM) kapı hiç devreye girmez.
    video_bekleyen = [adim for adim in veri["adimlar"] if not adim_tamam(klasor, adim)]
    sorunlu = [str(a["index"]) for a in video_bekleyen if not _video_serbest(veri, klasor, a)]
    if sorunlu:
        veri["gorsel_onay"] = "BEKLİYOR"
        veri["durum"] = "gorsel_onay"
        veri["son_not"] = ("Kalite kontrolü bekleyen sahneler: " + ", ".join(sorunlu) +
            ". Video üretimi başlamadı. Denetim notlarını incele; hatalı kareleri yenile. "
            "Denetim servisi çalışmadıysa yeniden devam et.")
        proje_yaz(veri)
        yield arayuz_paketi(veri, veri["son_not"])
        return
    if video_bekleyen and veri.get("gorsel_onay") != "VERİLDİ":
        veri["durum"] = "gorsel_onay"
        veri["son_not"] = (f"Bütün kareler hazır ({len(veri['adimlar'])} adım) · videolar "
                           "**görsel onayı** bekliyor. Kareleri **Görsel sahnelerini düzenle** "
                           "panelinden incele; beğenmediğin kareyi kaldır (yerine yenisi "
                           "üretilir), sonra **Görselleri onayla**'ya bas.")
        not_ekle(veri, "Kareler hazır; görsel onayı bekleniyor (videolar başlamadı).")
        # Denetimden tam geçemeyen kareler onaydan önce **adıyla** söylenir.
        suphe = [str(adim["index"]) for adim in veri["adimlar"]
                 if adim.get("denetim") and "geçti" not in adim["denetim"]]
        if suphe:
            veri["son_not"] += (" Denetimden tam geçemeyen kareler: adım " + ", ".join(suphe)
                                + " (her adımın `Denetim` satırı eksiği yazar).")
        proje_yaz(veri)
        yield arayuz_paketi(veri, veri["son_not"])
        return

    # ── 6) video Space'leri: kontrol et ve geçiş sırasını hazırla ────
    # Agnes elle seçildiyse Space kontrolü atlanır; bekleyen adımların video hakkı açılır.
    if video_bekleyen and video_servisi == VIDEO_AGNES:
        if not aktif_anahtar("agnes", "agnes_key"):
            yield arayuz_paketi(veri, hata_yaz(
                veri, None, "Agnes AI video",
                "Agnes AI anahtarı kayıtlı değil. **API hesapları** sekmesinde Agnes AI "
                "hizmetine anahtarını kaydet, sonra Agnes düğmesine yeniden bas."))
            return
        yield arayuz_paketi(veri, _servis_hazirla(veri, klasor, VIDEO_AGNES))
    elif video_bekleyen and video_servisi == VIDEO_LTX:
        hazir, sebep = video_ltx.VARSAYILAN.space_kontrol(aktif_anahtar("huggingface", "hf_token"))
        not_ekle(veri, f"LTX-2.3 Space kontrolü · {'✔' if hazir else '✖'} {sebep}")
        yield arayuz_paketi(veri, _servis_hazirla(veri, klasor, VIDEO_LTX)
                            + ("" if hazir else f" · Space şu an hazır görünmüyor ({sebep}); "
                               "üretim yine denenecek."))
    elif video_bekleyen:
        ozet, hazir = video_hazirla(veri)
        yield arayuz_paketi(veri, ozet if hazir else
                     ozet + " · hiçbiri şu an hazır görünmüyor; üretim yine denenecek.")

    # ── 7) bütün videolar ────────────────────────────────────────────
    if (yield from _video_asamasi(veri, klasor, video_servisi)):
        return
    if (yield from _durdurulduysa(veri, klasor)):
        return

    # ── 8) bitiş ─────────────────────────────────────────────────────
    # Kullanıcı kararı (23.10.2026): sahne klipleri bitince akış biter; genel video
    # (`proje.mp4`) artık burada birleştirilmez. Son video editörde **Dışa aktar** ile
    # sahne kliplerinden kurulur; birleştirme her çalışmada dakikalar sürüyor ve
    # sonucu kullanılmıyordu.
    tamam = all(adim_tamam(klasor, adim) for adim in veri["adimlar"])
    veri["durum"] = "tamam" if tamam else "bekliyor"
    if tamam:
        veri["son_not"] = (f"Proje tamamlandı · {len(veri['adimlar'])} sahne klibi hazır. "
                           "Son videoyu editörde **Dışa aktar** ile oluştur.")
    else:
        veri["son_not"] = "Bazı adımlar eksik; **Kaldığı yerden devam et** ile sürdür."
    not_ekle(veri, veri["son_not"])
    proje_yaz(veri)
    yield arayuz_paketi(veri, veri["son_not"] + f"\nKlasör: {klasor}")
