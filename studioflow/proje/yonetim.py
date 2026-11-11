"""Proje yönetimi: sahne listesi, adım sil/yenile, gösterme, sıfırlama, silme."""
import shutil
import time

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.akis import akis_calistir
from studioflow.proje.akis_kanca import kanca_izini_yaz
from studioflow.proje.akis_kare import gorsel_hazir
from studioflow.proje.akis_sahne import adimlari_kur, sahne_plani_uret
from studioflow.proje.akis_servis import VIDEO_HF, VIDEO_SERVIS_ADI
from studioflow.proje.ayar_normalize import ayarlari_normalize
from studioflow.proje.birlestirme import adim_sifirla, adim_videosunu_sifirla
from studioflow.proje.calisma_kilidi import CALISAN, IPTAL, birak, calisan
from studioflow.proje.depo import (
    SILINENLER, adim_tamam, guvenli_klasor, proje_dosyalari, proje_klasoru, silineni_temizle,
    slug, zorla_sil)
from studioflow.proje.dosya import not_ekle, proje_oku, proje_yaz
from studioflow.proje.ilerleme import arayuz_paketi, bos_ilerleme_html, bos_paket, paket_ozeti
from studioflow.proje.sabitler import DOSYA_ADI, HAM_VIDEO_ADI, VARSAYILAN_NEGATIF
from studioflow.proje.sahneleme import plan_sahneleri
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR, AI_VARSAYILAN


def sahne_listesi(ad):
    """Projenin adımlarını arayüzde düğme olarak listelemek için sade özetler.

    Dönen her öge JSON'a yazılabilir değerler taşır (`index`, `durum`, `baslangic`,
    `bitis`, `metin`), böylece Gradio `State` içinde saklanabilir; arayüz `gr.render`
    bloğunda bunları sırayla düğme yapar. Proje okunamıyorsa ya da henüz adım yoksa
    boş liste döner.
    """
    ad = (ad or "").strip()
    klasor = proje_klasoru(ad) if ad else None
    veri = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if veri is None:
        return []
    return [{
        "index": int(adim["index"]),
        "durum": adim.get("durum") or "BEKLİYOR",
        "baslangic": round(float(adim.get("start") or 0), 2),
        "bitis": round(float(adim.get("end") or 0), 2),
        "metin": _ilk_satir(adim.get("text") or "", 90),
    } for adim in veri["adimlar"]]


def sahne_prompt_listesi(ad):
    """Sahne seçimi paneli için promptları tam metin olarak döndür."""
    ad = (ad or "").strip()
    klasor = proje_klasoru(ad) if ad else None
    veri = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if veri is None:
        return []
    return [{
        "index": int(adim["index"]),
        "durum": adim.get("durum") or "BEKLİYOR",
        "metin": _ilk_satir(adim.get("text") or "", 110),
        "image_prompt": adim.get("image_prompt") or "",
        "negative_prompt": adim.get("negative_prompt") or "",
        "video_prompt": adim.get("video_prompt") or "",
    } for adim in veri["adimlar"]]


def sahne_prompt_uygula(ad, index, image_prompt, negative_prompt):
    """Seçilen sahnenin görsel promptunu kaydet ve karesini baştan üret."""
    veri, klasor, hata = _proje_hedefi(ad, "Sahne promptu")
    if hata is not None:
        yield hata
        return
    try:
        hedef = int(index)
    except (TypeError, ValueError):
        yield arayuz_paketi(veri, "Prompt uygulanacak sahne seçilemedi.")
        return
    adim = next((oge for oge in veri["adimlar"] if int(oge["index"]) == hedef), None)
    if adim is None:
        yield arayuz_paketi(veri, f"Adım {hedef} bu projede yok; prompt listesi güncel değil.")
        return
    image_prompt = " ".join(str(image_prompt or "").split())
    negative_prompt = " ".join(str(negative_prompt or "").split())
    if not image_prompt:
        yield arayuz_paketi(veri, "Görsel promptu boş bırakılamaz.")
        return
    if len(image_prompt) > 3000 or len(negative_prompt) > 3000:
        yield arayuz_paketi(veri, "Promptlar 3000 karakteri geçemez.")
        return
    # Eski hareket, kontrol listesi ve plan eski kareyi tarif eder. Görsel metni
    # korunarak bunlar prompt aşamasında yeniden türetilmelidir (eski projeler de).
    adim["image_prompt"] = image_prompt
    adim["negative_prompt"] = negative_prompt
    adim["video_prompt"] = ""
    adim.pop("kontrol", None)
    adim.pop("sahne_plani", None)
    if hedef == 1:
        veri["ayarlar"]["video"]["ilk_prompt"] = image_prompt
        veri["ayarlar"]["video"]["ilk_negatif"] = negative_prompt
        kanca_izini_yaz(veri)
    adim_sifirla(klasor, adim)
    adim["deneme"] = {}
    veri.setdefault("deneme", {}).pop("prompt", None)
    veri["birlestirme"] = "BEKLİYOR"
    veri["gorsel_onay"] = "BEKLİYOR"
    not_ekle(veri, f"Adım {hedef} promptu panelden güncellendi; yalnızca bu adımın karesi "
             "yeniden üretilecek. Klibi, görsel onayından sonra üretilecek.")
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"Adım {hedef} promptu kaydedildi · görsel baştan üretiliyor…")
    CALISAN["slug"] = slug(ad)
    SILINENLER.discard(slug(ad))
    try:
        IPTAL.clear()
        # Kullanıcı prompt'u panelden kendisi düzenledi: prompt onayı kapısı atlanır.
        yield from akis_calistir(ad, veri.get("metin") or "", veri["ayarlar"],
                                 prompt_onayli=True)
    finally:
        birak(slug(ad))
        silineni_temizle(ad)


def prompt_uretimi_baslat(ad, ai="", model="", sahne_on_plan=None):
    """**Prompt üretimine başla**: seçilen yapay zekâyı projeye işle ve akışı sürdür.

    Seslendirme bittiğinde akış bu düğmeyi bekler (bkz. `akis.akis_calistir`):
    hangi servisin sahne planını ve prompt'ları yazacağına kullanıcı burada karar verir.
    Seçim `proje.txt`e yazılır (kalan sahneleri de bu servis yazar; yazılmış prompt'lar
    korunur) ve akış **kapıyı atlayarak** devam eder. Seslendirme henüz bitmemişse akış
    önce sesi üretir, sonra prompt'lara geçer.

    `sahne_on_plan` ana sayfada (🎬 düğmesiyle) üretilen plandır; verilirse sahneleme
    onu **aynen** kullanır (yapay zekâya yeniden sorulmaz).

    Üreteç; arayüz çıktılarıyla birebir aynı sırayı üretir.
    """
    veri, klasor, hata = _proje_hedefi(ad, "Prompt üretimi")
    if hata is not None:
        yield hata
        return
    video = veri["ayarlar"]["video"]
    secili = ai if ai in AI_SAGLAYICILAR else ""
    if secili:
        eski = video.get("ai") or ""
        video["ai"] = secili
        # Model adları servisler arasında taşınamaz: seçimle birlikte yenilenir.
        video["model"] = str(model or "")
        not_ekle(veri, "Prompt yapay zekâsı seçildi: " + AI_SAGLAYICILAR[secili]["label"]
                 + (f" (önceki: {AI_SAGLAYICILAR[eski]['label']})" if eski in AI_SAGLAYICILAR
                    else "")
                 + f" · model: {video['model'] or AI_SAGLAYICILAR[secili]['models'][0]}.")
    etiket = (AI_SAGLAYICILAR.get(secili) or AI_SAGLAYICILAR.get(video.get("ai"))
              or AI_SAGLAYICILAR[AI_VARSAYILAN])
    if not veri["adimlar"] and veri["ses"].get("durum") != "TAMAM":
        not_ekle(veri, "Prompt üretimi başlatıldı; önce seslendirme üretilecek.")
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"Sahne planı ve prompt'lar **{etiket['label']}** ile "
                        "yazılıyor…")
    CALISAN["slug"] = slug(ad)
    SILINENLER.discard(slug(ad))
    try:
        IPTAL.clear()
        yield from akis_calistir(ad, veri.get("metin") or "", veri["ayarlar"],
                                 prompt_onayli=True, sahne_on_plan=sahne_on_plan)
    finally:
        birak(slug(ad))
        silineni_temizle(ad)


def sahne_sil_yenile(ad, index):
    """Bir adımın **videosunu** sil, yalnızca onu yeniden üret ve videoyu yeniden birleştir.

    Adımın **karesi korunur**: yalnızca klibi ve tuval klibi diskten kaldırılır,
    video deneme sayaçları temizlenir (bkz. `adim_videosunu_sifirla`). Prompt'lar da
    korunur. Kare zaten görülüp onaylandığı için görsel onayı kapısı bu adım için
    yeniden sorulmaz: akış doğrudan 1. aynı kareden yeni klibi üretir, 2. `proje.mp4`i
    yeniden birleştirir. Kareyi değiştirmek isteyen **Görsel sahnelerini düzenle**
    panelini kullanır (bkz. `gorsel_sil_yenile`). Karesi diskte yoksa (elle silinmiş)
    adım eski yoldan baştan üretilir: önce kare, sonra onay, sonra video.

    Üreteç; her adımda `arayuz_paketi` üretir (arayüz çıktılarıyla birebir aynı sıra).
    """
    ad = (ad or "").strip()
    if not ad:
        yield bos_paket("Sahneyi yeniden üretmek için önce bir proje aç.")
        return
    if CALISAN["slug"]:
        yield bos_paket(f"Şu anda '{CALISAN['slug']}' projesi çalışıyor. Önce **Durdur**'a bas; "
                   "sahne yenileme çalışan akış bitince yapılabilir.")
        return
    try:
        hedef = int(index)
    except (TypeError, ValueError):
        yield bos_paket("Silinecek adım belirlenemedi; **Sahneleri incele**'ye yeniden bas.")
        return
    klasor = guvenli_klasor(ad)
    veri = proje_oku(klasor) if klasor is not None else None
    if veri is None or klasor is None:
        yield bos_paket(f"'{ad}' okunamadı: klasöründe okunabilir bir {DOSYA_ADI} yok.")
        return
    # Yazma hedefi **seçilen klasör** olmalı: `proje.txt` içindeki ad klasör adından
    # farklıysa (elle yeniden adlandırma) metne değil seçilen klasöre yazılır.
    veri["slug"] = slug(ad)
    adim = next((oge for oge in veri["adimlar"] if int(oge["index"]) == hedef), None)
    if adim is None:
        yield arayuz_paketi(veri, f"Adım {hedef} bu projede yok; liste güncel olmayabilir. "
                           "**Sahneleri incele**'ye yeniden bas.")
        return
    CALISAN["slug"] = slug(ad)
    try:
        # Kare ve prompt'lar **korunur**: yalnızca klip yeniden üretilir. Akış prompt
        # ve görsel aşamalarını atlar, o adım için yalnızca video harcanır.
        if gorsel_hazir(klasor, adim):
            adim_videosunu_sifirla(klasor, adim)
            sayac = adim.get("deneme") or {}
            sayac.pop("video", None)
            adim["deneme"] = sayac
            # Kare değişmedi: yeni klip onay beklemeden başlar. Onay yalnızca başka
            # videosu eksik adım yoksa verilir; yoksa onaylanmamış kareler de videoya
            # giderdi.
            if all(adim_tamam(klasor, oge) for oge in veri["adimlar"] if oge is not adim):
                veri["gorsel_onay"] = "VERİLDİ"
            not_ekle(veri, f"Adım {adim['index']} videosu panelden silindi: kare ve "
                            "prompt'lar korundu; yalnızca video yeniden üretilecek.")
            mesaj = (f"Adım {adim['index']} videosu silindi (kare korundu). Aynı kareden "
                     "yeni video üretiliyor, en son video birleştirilecek…")
        else:
            adim_sifirla(klasor, adim)
            adim.update(deneme={})
            not_ekle(veri, f"Adım {adim['index']} panelden silindi: karesi diskte yoktu, "
                            "kare ve video baştan üretilecek (prompt'lar korundu).")
            mesaj = (f"Adım {adim['index']} silindi. Karesi diskte olmadığı için önce kare "
                     "üretilecek; görsel onayından sonra video üretilir.")
        proje_yaz(veri)
        yield arayuz_paketi(veri, mesaj)
        IPTAL.clear()
        # Kalan akış yalnızca eksik adımı üretir: diğerleri TAMAM olduğu için atlanır.
        # Kullanıcı seçimini panelden yaptı; prompt onayı kapısı atlanır.
        yield from akis_calistir(ad, veri.get("metin") or "", veri["ayarlar"],
                                 prompt_onayli=True)
    finally:
        birak(slug(ad))
        silineni_temizle(ad)


def _proje_hedefi(ad, islem):
    """Panel işlemlerinin ortak ön kontrolü: `(veri, klasör, hata paketi)`.

    Hata paketi `None` değilse çağıran onu yield edip durur. `sahne_sil_yenile` ile
    aynı kurallar: ad yazılı olmalı, başka bir proje çalışıyor olmamalı, klasörde
    okunabilir bir `proje.txt` bulunmalı.
    """
    ad = (ad or "").strip()
    if not ad:
        return None, None, bos_paket(f"{islem} için önce bir proje aç.")
    if CALISAN["slug"]:
        return None, None, bos_paket(
            f"Şu anda '{CALISAN['slug']}' projesi çalışıyor. Önce **Durdur**'a bas; "
            f"{islem.lower()} çalışan akış bitince yapılabilir.")
    klasor = guvenli_klasor(ad)
    veri = proje_oku(klasor) if klasor is not None else None
    if veri is None or klasor is None:
        return None, None, bos_paket(f"'{ad}' okunamadı: klasöründe okunabilir bir "
                                     f"{DOSYA_ADI} yok.")
    # Yazma hedefi **seçilen klasör** olmalı (bkz. `sahne_sil_yenile`).
    veri["slug"] = slug(ad)
    return veri, klasor, None


def sahne_planini_uygula(ad, plan_kaydi):
    """🎬 ile üretilen planı **açık projenin** `proje.txt`'sine işle; sonuç metnini döndür.

    Eskiden plan yalnızca arayüzdeki `State`te kalıyordu ve akış onu yalnızca projede hiç
    sahne yokken kullanıyordu (`akis` 2. adım: `if not veri["adimlar"]`). Sahneleri bir
    kez kurulmuş projede 🎬'ye her basış yeni plan üretse de proje eski sahnelerle devam
    ediyordu (Greek Mythology 8 Monsters, 05.10.2026). Artık her basışta plan projeye
    yazılır: sahneler gerçek sesin kelime zamanlarına hizalanıp baştan kurulur, eski
    sahnelerin prompt'ları silinir (yeni sahnelere yeniden yazılır).

    Kare ya da video üretilmiş projede sahneler **değiştirilmez**: yeni sınırlar mevcut
    kareleri ve klipleri geçersiz bırakırdı; kullanıcıya söylenir.
    """
    ad = (ad or "").strip()
    if not ad or not plan_kaydi:
        return ""
    klasor = guvenli_klasor(ad)
    veri = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if veri is None:
        return "Bu ad henüz bir proje değil: plan, proje başlatılınca aynen kullanılacak."
    if CALISAN["slug"] == slug(ad):
        return ("Bu proje şu anda çalışıyor; sahne planı projeye yazılmadı. Durdurup 🎬'ye "
                "yeniden bas.")
    if any(adim.get("gorsel") or adim.get("video") for adim in veri["adimlar"]):
        return ("Bu projede kare/video üretilmiş; sahneler **değiştirilmedi** (yeni sınırlar "
                "mevcut kareleri geçersiz bırakır). Sahneleri yeniden kurmak için kareleri "
                "kaldır ya da yeni proje başlat.")
    strateji = veri["ayarlar"]["video"].get("sahne_stratejisi")
    if plan_sahneleri(plan_kaydi, veri.get("metin") or "", strateji) is None:
        return ("Plan bu projenin kayıtlı anlatımına ya da stratejisine ait değil; projeye "
                "yazılmadı (metin ya da strateji ekrandakinden farklı).")
    if veri["ses"].get("durum") != "TAMAM" or not float(veri["ses"].get("sure") or 0):
        return "Seslendirme henüz hazır değil: plan, sahneleme aşamasında aynen kullanılacak."
    veri["slug"] = slug(ad)
    # 🎬'de seçilen tavan projeye de yazılır: eskiden plan 10 sn ile çıkarılıyor, gerçek
    # sese hizalama ise projenin kayıtlı 8 sn'sini kullanıyordu ve 8–10 sn'lik cümleler
    # gereksiz yere bölünüyordu (Greek Mythology, 05.10.2026).
    tavan = float(plan_kaydi.get("tavan") or 0)
    if tavan > 0:
        veri["ayarlar"]["video"]["adim_saniye"] = tavan
    sure = float(veri["ses"]["sure"])
    eski = len(veri["adimlar"])
    sahneler, kaynak, gerekce = sahne_plani_uret(veri, klasor, sure, on_plan=plan_kaydi)
    adimlari_kur(veri, sure, sahneler)
    not_ekle(veri, f"🎬 sahne planı projeye işlendi ({eski} → {len(veri['adimlar'])} sahne) · "
                   f"kaynak: {kaynak}" + (f" · {gerekce}" if gerekce else "")
                   + ". Prompt'lar yeni sahnelere yeniden yazılacak.")
    proje_yaz(veri)
    return (f"Plan **{ad}** projesine işlendi: {eski} → **{len(veri['adimlar'])} sahne** "
            "(gerçek sesin kelime zamanlarına hizalandı). Prompt'lar yeni sahnelere "
            "yeniden yazılacak.")


def gorsel_listesi(ad):
    """Adımların **kareleri**: görsel düzenleme panelinin listesi.

    Her öge `index`, `gorsel` (tam yol ya da `None`), `durum`, `metin` ve `sure`
    taşır; kare henüz üretilmemişse `gorsel` boştur. Video durumu ayrıca `videolu`
    alanında verilir: kaldırma düğmesi bunu uyarı metninde kullanır.
    """
    ad = (ad or "").strip()
    klasor = proje_klasoru(ad) if ad else None
    veri = proje_oku(klasor) if klasor is not None and klasor.is_dir() else None
    if veri is None:
        return []
    liste = []
    for adim in veri["adimlar"]:
        kare = klasor / adim["gorsel"] if gorsel_hazir(klasor, adim) else None
        liste.append({
            "index": int(adim["index"]),
            "gorsel": str(kare) if kare is not None else "",
            "durum": adim.get("durum") or "BEKLİYOR",
            "videolu": bool(adim.get("video") and (klasor / adim["video"]).exists()),
            "sure": round(float(adim.get("end") or 0) - float(adim.get("start") or 0), 1),
            "metin": _ilk_satir(adim.get("text") or "", 110),
        })
    return liste


def gorsel_onayi_ver(ad, video_servisi=VIDEO_HF):
    """**Görselleri onayla**: kareler kabul edilir ve video üretimi başlar.

    Onay `proje.txt`e yazılır (`Görsel onayı : VERİLDİ`), yani uygulama kapansa da
    kalır. Eksik kare varsa akış önce onları üretir ve onayı **yeniden** sorar:
    görülmemiş bir kare için video harcanmaz (bkz. `akis._gorsel_asamasi`).

    `video_servisi` videoları üreten servistir: üç onay düğmesinden hangisine
    basıldığını taşır (Agnes AI · LTX-2.3 · Hugging Face). Seçim projeye yazılır
    (`Video servisi`); **Kaldığı yerden devam** da o servisle sürer. Daha önce üretilmiş sahne videoları
    **silinmez**: akış tamamlanmış adımları atlar ve ilk eksik sahneden sürer.

    Üreteç; arayüz çıktılarıyla birebir aynı sırayı üretir.
    """
    veri, klasor, hata = _proje_hedefi(ad, "Görsel onayı")
    if hata is not None:
        yield hata
        return
    if not veri["adimlar"]:
        yield arayuz_paketi(veri, "Bu projede henüz adım yok: önce **Projeye başlat**'a bas, "
                            "seslendirme ve kareler üretilsin.")
        return
    eksik = [adim["index"] for adim in veri["adimlar"] if not gorsel_hazir(klasor, adim)]
    if video_servisi not in VIDEO_SERVIS_ADI:
        video_servisi = VIDEO_HF
    servis = VIDEO_SERVIS_ADI[video_servisi]
    hazir = sum(1 for adim in veri["adimlar"] if adim_tamam(klasor, adim))
    veri["gorsel_onay"] = "VERİLDİ"
    not_ekle(veri, f"Görseller onaylandı; video üretimi {servis} ile başlatıldı."
             + (f" {hazir} sahnenin videosu hazır, korunuyor." if hazir else "")
             + (f" Karesi eksik adımlar önce üretilecek: {eksik}." if eksik else ""))
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"Görseller onaylandı · videolar **{servis}** ile üretiliyor…"
                        + (f"\nHazır {hazir} sahne videosu korunuyor; üretim ilk eksik "
                           "sahneden sürüyor." if hazir else "")
                        + (f"\nKaresi olmayan {len(eksik)} adım önce üretilecek; yeni kare "
                           "çıkarsa onay yeniden sorulur." if eksik else ""))
    CALISAN["slug"] = slug(ad)
    SILINENLER.discard(slug(ad))
    try:
        IPTAL.clear()
        yield from akis_calistir(ad, veri.get("metin") or "", veri["ayarlar"], video_servisi,
                                 prompt_onayli=True)
    finally:
        birak(slug(ad))
        silineni_temizle(ad)


def gorsel_sil_yenile(ad, index):
    """Bir adımın **karesini** kaldır ve yerine yenisini üret (video başlamaz).

    Beğenilmeyen kare panelden kaldırılınca sistem aynı prompt'la yeni bir kare
    üretir. Adımın klibi varsa o da geçersizdir (klip kareden türer), bu yüzden
    birlikte silinir; prompt'lar korunur. Kare yenilendiği için **görsel onayı da
    sıfırlanır**: akış yeni kareyi gösterip yeniden onay ister, videolar kendiliğinden
    başlamaz.
    """
    veri, klasor, hata = _proje_hedefi(ad, "Görsel yenileme")
    if hata is not None:
        yield hata
        return
    try:
        hedef = int(index)
    except (TypeError, ValueError):
        yield arayuz_paketi(veri, "Yenilenecek kare belirlenemedi; listeyi tazele.")
        return
    adim = next((oge for oge in veri["adimlar"] if int(oge["index"]) == hedef), None)
    if adim is None:
        yield arayuz_paketi(veri, f"Adım {hedef} bu projede yok; listeyi tazele.")
        return
    videolu = bool(adim.get("video"))
    # Kare ve (varsa) klip silinir, deneme sayaçları temizlenir; prompt'lar kalır.
    adim_sifirla(klasor, adim)
    adim.update(deneme={}, durum="BEKLİYOR")
    veri["gorsel_onay"] = "BEKLİYOR"
    not_ekle(veri, f"Adım {adim['index']} karesi panelden kaldırıldı; yenisi üretilecek"
             + (" (klibi de silindi)." if videolu else ".") + " Prompt'lar korundu.")
    proje_yaz(veri)
    yield arayuz_paketi(veri, f"Adım {adim['index']} karesi kaldırıldı · yenisi üretiliyor…")
    CALISAN["slug"] = slug(ad)
    SILINENLER.discard(slug(ad))
    try:
        IPTAL.clear()
        # Akış yalnızca eksik kareyi üretir ve görsel onayı kapısında durur; prompt'lar
        # hazır olduğu için prompt onayı kapısı zaten devreye girmez.
        yield from akis_calistir(ad, veri.get("metin") or "", veri["ayarlar"],
                                 prompt_onayli=True)
    finally:
        birak(slug(ad))
        silineni_temizle(ad)


def proje_goster(ad):
    """Kayıtlı bir projenin metnini ve dosyalarını oku."""
    klasor = proje_klasoru(ad)
    veri = proje_oku(klasor) if klasor.is_dir() else None
    if veri is None:
        return (f"'{ad}' okunamadı: klasöründe okunabilir bir {DOSYA_ADI} yok.", "", [], [],
                None, bos_ilerleme_html())
    return arayuz_paketi(veri, f"{paket_ozeti(veri)}\nKlasör: {klasor}")


def proje_ayarlari(ad):
    """Kayıtlı projenin **anlatım metnini** ve **ayarlarını** döndür (okunamazsa `None`).

    Proje seçildiğinde arayüz alanlarını doldurmak için kullanılır: anlatım metni,
    genel prompt, görsel stil, negatif prompt ve bütün ses/görsel/video ayarları
    yalnızca `proje.txt` metninde kalmaz, kendi alanlarında da görünür. Dönen sözlük
    `{"metin": ..., "ayarlar": ...}` biçimindedir ve ayarlar `proje.txt` yazılırken
    kullanılan yapıyla aynıdır.
    """
    klasor = proje_klasoru(ad)
    veri = proje_oku(klasor) if klasor.is_dir() else None
    if veri is None:
        return None
    return {"metin": veri.get("metin") or "", "ayarlar": veri["ayarlar"]}


def icerik_varsayilanlari():
    """Yeni projenin **içerik** katmanları: kayıtlı genel ayarlardan, yoksa boş.

    Anlatım metni, genel video prompt'u, görsel stil ve negatif prompt **proje
    içeriğidir**: bir projeden diğerine kendiliğinden taşınmaz, her proje kendi
    `proje.txt`'inden okunur. Yeni bir proje açılırken başlangıç değeri yalnızca
    kullanıcının **Ayarları kaydet** ile genel ayar dosyasına yazdığı prompt'lardır
    (bkz. `ayarlar.proje_ayarlari`); dosya yoksa metin ve prompt'lar boş, negatif prompt
    varsayılan değerle başlar. Seslendirme · altyazı · görsel · video ayarları bu
    sözlükte yoktur: onlar genel ayardır ve ekranda olduğu gibi kullanılır.
    """
    try:
        ham = proje_ayarlari.VARSAYILAN.oku()
    except Exception:
        ham = None
    ayar = ayarlari_normalize(ham or {})
    return {"metin": "",
            "genel": (ayar["video"].get("genel") or "").strip(),
            "stil": (ayar["video"].get("stil") or "").strip(),
            "negatif": (ayar["gorsel"].get("negatif") or "").strip() or VARSAYILAN_NEGATIF,
            # İlk sahne (kanca) prompt'u da projeye özel içeriktir: ad değişince
            # panelden boşalır, yeni projede genel ayar dosyasındaki değerle başlar.
            "ilk_prompt": (ayar["video"].get("ilk_prompt") or "").strip(),
            "ilk_negatif": (ayar["video"].get("ilk_negatif") or "").strip()}


def sifirla(ad):
    """Projenin üretilmiş dosyalarını ve kaydını sil; klasör ve ad kalsın.

    Silinenler: `proje.txt`, `proje.mp4`, `ses/`, `gorseller/`, `videolar/`.
    Bir sonraki çalıştırma sesi ve bütün adımları baştan üretir.
    """
    ad = (ad or "").strip()
    if not ad:
        return "Listeden bir proje seç."
    if calisan() == slug(ad):
        return f"'{ad}' şu anda çalışıyor. Önce **Durdur**'a bas, sonra sıfırla."
    klasor = guvenli_klasor(ad)
    if klasor is None:
        return f"'{ad}' klasörü bulunamadı."
    dosya = len(proje_dosyalari(klasor))
    hedefler = [klasor / DOSYA_ADI, klasor / "proje.mp4", klasor / HAM_VIDEO_ADI,
                klasor / "ses", klasor / "gorseller", klasor / "videolar"]
    for yol in hedefler:
        try:
            if yol.is_dir():
                shutil.rmtree(yol)
            elif yol.exists():
                yol.unlink()
        except OSError as hata:
            return f"Sıfırlama yarıda kaldı ({yol.name}): {_ilk_satir(hata, 200)}"
    return (f"'{ad}' sıfırlandı · {dosya} dosya silindi. Klasör ve proje adı duruyor; "
            "**Projeye başlat** sesi ve bütün adımları baştan üretir.")


def sil(ad, bekle=5.0):
    """Projenin klasörünü ve içindeki her şeyi sil; çalışıyorsa önce durdurur.

    Silme hiçbir durumda reddedilmez: çalışan akışa durdurma işareti verilir ve en çok
    `bekle` saniye beklenir. Hata ya da takılan bir adım yüzünden akış durmazsa kaydı
    zorla boşaltılır; akış sonradan bittiğinde klasörü yeniden yazmışsa o da silinir
    (`silineni_temizle`). Kilitli dosyalar için bkz. `zorla_sil`.
    """
    ad = (ad or "").strip()
    if not ad:
        return "Listeden bir proje seç."
    klasor = guvenli_klasor(ad)
    if klasor is None:
        return f"'{ad}' klasörü bulunamadı."
    durduruldu = calisan() == klasor.name
    if durduruldu:
        SILINENLER.add(klasor.name)
        IPTAL.set()
        bitis = time.monotonic() + bekle
        while calisan() == klasor.name and time.monotonic() < bitis:
            time.sleep(0.2)
        birak(klasor.name)
    dosya = len(proje_dosyalari(klasor))
    on_ek = "Çalışma durduruldu · " if durduruldu else ""
    if not zorla_sil(klasor):
        return (f"{on_ek}'{ad}' silindi; açık kalan birkaç dosya, serbest kalınca "
                "kendiliğinden temizlenecek.")
    return (f"{on_ek}'{ad}' silindi · {dosya} dosya ve klasörün tamamı kaldırıldı. "
            "Aynı adı yeniden kullanırsan proje sıfırdan başlar.")
