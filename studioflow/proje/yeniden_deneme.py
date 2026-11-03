"""Hata sonrası otomatik yeniden deneme ve hesaplı adım çalıştırma çerçevesi."""
import threading
import time

from studioflow.ayarlar.bicimler import ETIKET_IPUCU
from studioflow.cekirdek.hatalar import (Durduruldu as _Durduruldu, dakikalik_bekleme,
                                         gpu_yok_mu, hata_etiketle, icerik_filtresi_mi,
                                         metin_engeli_mi)
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.calisma_kilidi import IPTAL, calisan
from studioflow.proje.depo import proje_klasoru, slug
from studioflow.proje.dosya import hata_notu, not_ekle, proje_oku, proje_yaz
from studioflow.proje.ilerleme import arayuz_paketi, bos_paket
from studioflow.proje.sabitler import (DENEME_ADI, DOSYA_ADI, HIZ_BEKLEMELERI, YENIDEN_BEKLEME,
                                       YENIDEN_SINIR)
from studioflow.saglayicilar.hesap_havuzu import (
    ELENEN, GECICI_HATA_SINIRI, HIZMET_ADI, aktif_anahtar, aktif_kimlik, hesap_adi,
    hesap_aktif_yap,
    hesap_basarisi, hesap_ele, hesap_elendi, hesap_hatasi, hesap_kimligi, hesap_listesi,
    kota_bekliyor, saglik_kontrol)
from studioflow.saglayicilar.hesap_havuzu import VARSAYILAN as _HAVUZ
from studioflow.saglayicilar.kota_listesi import VARSAYILAN as KOTA_LISTESI, saat_metni
from studioflow.saglayicilar.metin_ortak import AI_YEDEK_SIRA, ai_anahtari


def _deneme_sayaci(veri, kayit, islem):
    """Sayaçların tutulduğu sözlüğü döndür.

    Seslendirme ve prompt projede, görsel ve video adımda tutulur; böylece bir adımın
    görselinde harcanan hak o adımın videosunu etkilemez. Sayaç `proje.txt`'e yazıldığı
    için uygulama kapansa da koruma sürer; yalnızca işlem sorunsuz bitince sıfırlanır.
    """
    if isinstance(kayit, dict) and "index" in kayit:
        return kayit.setdefault("deneme", {})
    return veri.setdefault("deneme", {})


# HF video kotası bittiğinde gösterilen yol: Agnes'e **kendiliğinden geçilmez**, kullanıcı
# görsel onayındaki Agnes düğmesiyle seçer (bkz. `yonetim.gorsel_onayi_ver`). Onay zaten
# verilmiş olsa da düğme çalışır: hazır videolar korunur, üretim ilk eksik sahneden sürer.
AGNES_IPUCU = ("Hugging Face kotası bittiyse **✅ Onayla · Agnes AI ile videoları üret** "
               "düğmesiyle videolara bu kez Agnes AI ile, kaldığı sahneden devam edebilirsin.")


# Son hatanın ham sebebi ve hatalı kayıt **iş parçacığı başına** tutulur: çoklu üretimde
# paralel gruplar aynı projeye yazar; ortak alanda bir grubun hatası başka grubun adımına
# işleniyordu (12.10.2026: adım 71'in notunda 26'nın hesabı, "DENEME DOLDU" yanlış adımda).
_YEREL = threading.local()


def _son_hata(veri):
    """Bu iş parçacığının son hatası: `(sebep, kayıt)`."""
    son = getattr(_YEREL, "son", None)
    if son is not None and son[0] is veri:
        return son[1], son[2]
    return veri.get("son_hata") or "", veri.get("son_hata_kayit")


def dur_turu(veri):
    """`"dur"` paketinin sebebi: kullanıcı mı durdurdu, hata mı?"""
    return "durdu" if veri.get("durum") == "durduruldu" else "hata"


def _yeniden_bekle(saniye):
    """İki deneme arasında bekle; **Durdur**'a basılırsa bekleme hemen kesilir."""
    bitis = time.monotonic() + max(0.0, float(saniye))
    while time.monotonic() < bitis and not IPTAL.is_set():
        time.sleep(0.2)


def _deneme_notu(veri, baslik, islem, deneme, kayit=None):
    """Ara denemenin hatasını 'otomatik yeniden başlatılıyor' notuna çevir.

    Ara hata kalıcı sayılmaz: kayıt yeniden üretilecek hâle döner (metinde HATA kalmaz),
    kaçıncı denemede kalındığı ve kaç hak kaldığı günlüğe yazılır. `kayit` verilirse
    not o adıma işlenir; verilmezse bu iş parçacığının son hatalı kaydı kullanılır.
    """
    sebep, son_kayit = _son_hata(veri)
    kayit = kayit if isinstance(kayit, dict) else son_kayit
    not_ = (f"{baslik} · {DENEME_ADI.get(islem, islem)} {deneme}. denemede hata: "
            f"{_ilk_satir(sebep, 200)} — otomatik yeniden başlatılıyor "
            f"({deneme}/{YENIDEN_SINIR}); {YENIDEN_SINIR - deneme} deneme hakkı kaldı.")
    if isinstance(kayit, dict):
        # Hazır dosyası olan adım çubukta YARIM görünsün (kaybolan iş belli olsun).
        kayit["durum"] = ("YARIM" if kayit.get("gorsel") or kayit.get("video")
                          else "BEKLİYOR")
        kayit["hata"] = f"YENİDEN {deneme}/{YENIDEN_SINIR} · {_ilk_satir(sebep, 180)}"
    veri["durum"] = "calisiyor"
    veri["son_not"] = not_
    not_ekle(veri, not_)
    proje_yaz(veri)
    return not_


def kota_bekleniyor(veri, baslik):
    """Bütün hesaplar kotada: deneme hakkı harcanmadan durulur, kota yenilenince sürülür."""
    veri["durum"] = "bekliyor"
    sebep = ("Hugging Face'te boş GPU yok (her yeni deneme hesabın kotasını yer)"
             if gpu_yok_mu(_son_hata(veri)[0])
             else "bütün hesapların kotası dolu")
    # Kota bekleme listesinde en erken açılan hesap: kullanıcı ne zaman devam edeceğini bilsin.
    bekleyen = KOTA_LISTESI.liste(getattr(_YEREL, "kota_hizmet", None) or "-")
    acilis = (f" En erken açılan hesap: '{bekleyen[0]['ad']}' "
              f"{saat_metni(bekleyen[0]['acilis'])}." if bekleyen else "")
    not_ = (f"{baslik} · {sebep}; deneme hakkı harcanmadı, akış durdu.{acilis} "
            "Kota yenilenince ya da **API hesapları** sekmesine hesap ekleyince "
            "**Kaldığı yerden devam et**'e bas.")
    not_ekle(veri, not_)
    veri["son_not"] = f"{veri.get('son_not') or ''}\n{not_}".strip()
    proje_yaz(veri)
    return not_


def denemeler_tukendi(veri, baslik, islem, kayit=None):
    """Deneme hakkı doldu: hata metne yazılır ve proje durur (korumayı kullanıcı açar)."""
    veri["durum"] = "bekliyor"
    not_ = (f"{baslik} · {DENEME_ADI.get(islem, islem)} için {YENIDEN_SINIR} otomatik deneme "
            "hakkı doldu; proje durduruldu. Sorunu giderdikten sonra **Deneme hakkını "
            f"yenile**'ye bas (ya da proje.txt'teki `Deneme` satırını `0/{YENIDEN_SINIR}` "
            "yap), sonra **Kaldığı yerden devam et**."
            + (" " + AGNES_IPUCU if islem == "video" else ""))
    not_ekle(veri, not_)
    veri["son_not"] = f"{veri.get('son_not') or ''}\n{not_}".strip()
    # Adımın Hata satırı kendi kendini açıklasın. Sonek değil **önek** yazılır: metin
    # dosyası bu satırı belli uzunlukta kestiği için asıl bilgi başta durmalı.
    if not isinstance(kayit, dict):
        kayit = _son_hata(veri)[1]
    if isinstance(kayit, dict) and "DENEME DOLDU" not in (kayit.get("hata") or ""):
        kayit["hata"] = (f"[DENEME DOLDU] {YENIDEN_SINIR} otomatik deneme geçmedi; "
                         "**Deneme hakkını yenile** · " + (kayit.get("hata") or ""))
    proje_yaz(veri)
    return not_


def denemeli(veri, baslik, islem, kayit, asama):
    """Bir işlemi çalıştır; hata olursa **otomatik yeniden başlat** (en fazla 3 kez).

    `asama(deneme)` her çağrıda işi baştan yapan yeni bir üreteç döndürür ve bittiğinde
    durumu döndürür: `"ok"` · `"hata"` · `"durdu"`. Arayüze hazır paketler üretilir.

    Koruma (bkz. `YENIDEN_SINIR`): sayaç işlem başına tutulur ve `proje.txt`'e yazılır;
    sorunsuz biten deneme sayacı sıfırlar, kullanıcı durdurması hiç yeniden denenmez,
    hak dolduğunda akış kesilir. Dönüş: akış kesilmeli mi (`True`/`False`).
    """
    sayac = _deneme_sayaci(veri, kayit, islem)
    while True:
        if int(sayac.get(islem) or 0) >= YENIDEN_SINIR:
            yield arayuz_paketi(veri, denemeler_tukendi(veri, baslik, islem, kayit))
            return True
        if IPTAL.is_set():
            return True
        sayac[islem] = int(sayac.get(islem) or 0) + 1
        deneme = sayac[islem]
        _YEREL.kota_tukendi = False
        proje_yaz(veri)          # sayaç hemen diske yazılsın: çalışma koparsa hak kaybolmaz
        akis, sonuc = asama(deneme), "ok"
        while True:
            try:
                mesaj = next(akis)
            except StopIteration as bitis:
                sonuc = bitis.value or "ok"
                break
            except _Durduruldu:
                return True
            except Exception as hata:
                # Beklenmeyen hata akışı çökertmesin: metne yazılır ve deneme hakkı
                # diğer hatalarla aynı kurallarla işler.
                yield arayuz_paketi(veri, hata_yaz(veri, kayit, baslik, _ilk_satir(hata, 400)))
                sonuc = "hata"
                break
            yield arayuz_paketi(veri, mesaj)
        if sonuc == "ok":
            if int(sayac.get(islem) or 0):
                # Başarılı deneme korumayı sıfırlar: bir sonraki hata yine üç hakla başlar.
                sayac[islem] = 0
                if isinstance(kayit, dict):
                    kayit["hata"] = ""
                if deneme > 1:
                    not_ekle(veri, f"{baslik} · otomatik yeniden başlatma başarılı "
                                    f"({deneme}. denemede); deneme sayacı sıfırlandı.")
                proje_yaz(veri)
            return False
        if sonuc == "durdu" or IPTAL.is_set():
            return True
        if getattr(_YEREL, "kota_tukendi", False):
            # 14.10.2026: bütün hesaplar günlük kotadayken kare saniyeler arayla üç kez
            # denendi; kota o arada yenilenmediği için 10 adımın hakkı boşa yandı ve
            # her biri elle açılmak zorunda kaldı. Hak geri verilir, akış durur.
            _YEREL.kota_tukendi = False
            sayac[islem] = max(0, int(sayac.get(islem) or 0) - 1)
            yield arayuz_paketi(veri, kota_bekleniyor(veri, baslik))
            return True
        if gpu_yok_mu(_son_hata(veri)[0]):
            # 22.10.2026: GPU alamayan her deneme hesabın ZeroGPU kotasından ~75 sn yiyor;
            # bekleyip yeniden denemek hesapları boşa tüketiyordu. Hak geri verilir, akış durur.
            sayac[islem] = max(0, int(sayac.get(islem) or 0) - 1)
            if isinstance(kayit, dict):
                kayit["durum"] = "YARIM" if kayit.get("gorsel") or kayit.get("video") else "BEKLİYOR"
                kayit["hata"] = ""
            yield arayuz_paketi(veri, kota_bekleniyor(veri, baslik))
            return True
        if int(sayac.get(islem) or 0) >= YENIDEN_SINIR:
            yield arayuz_paketi(veri, denemeler_tukendi(veri, baslik, islem, kayit))
            return True
        # Yeniden başlatma öncesi hesap elemesi sıfırlanır: kota yenilenmiş olabilir.
        ELENEN.clear()
        yield arayuz_paketi(veri, _deneme_notu(veri, baslik, islem, deneme, kayit))
        _yeniden_bekle(YENIDEN_BEKLEME[min(deneme, len(YENIDEN_BEKLEME)) - 1])


def _adim_dene(veri, baslik, uretec, kontrol=None):
    """Bir istemci üretecini çalıştır ve sonucu yorumla; **metne hata yazmaz**.

    Üretilenler: ("bildir", ara metin) · ("ok", son değer) · ("hata", ham hata) ·
    ("durdu", None). Yazma işini çağıran yapar: böylece bir hesabın kotası dolduğunda
    kalan adıma hata düşmeden sıradaki hesapla yinelenebilir.

    `kontrol(son)` boş/eksik sonuçlar için sebep metni döndürebilir (istemciler hatayı
    yutup boş liste döndüğü için bazı hatalar ancak böyle yakalanır).
    """
    son = None
    try:
        for deger in uretec:
            if IPTAL.is_set():
                raise _Durduruldu()
            son = deger
            if isinstance(deger, str):
                yield "bildir", f"{baslik} · {_ilk_satir(deger)}"
    except Exception as hata:
        if IPTAL.is_set() or isinstance(hata, _Durduruldu):
            yield "durdu", None
        else:
            yield "hata", _ilk_satir(hata, 400)
        return
    sorun = kontrol(son) if kontrol else None
    if sorun:
        yield "hata", _ilk_satir(sorun, 400)
        return
    yield "ok", son


def _durdur_yaz(veri, baslik):
    """Durdurmayı metne işle ve kullanıcıya gösterilecek mesajı döndür."""
    veri["durum"] = "durduruldu"
    veri["son_not"] = f"{baslik} durduruldu."
    not_ekle(veri, veri["son_not"])
    proje_yaz(veri)
    return f"{baslik} durduruldu. **Kaldığı yerden devam et** ile sürdürebilirsin."


def adim_calistir(veri, kayit, baslik, uretec):
    """Hesap seçimi olmayan işlemler için sade çalıştırıcı (ör. anahtarsız Edge sesi).

    Üretilenler: ("bildir", ara metin) · ("sonuc", son değer) · ("dur", mesaj).
    Durdurma ve hata durumu metne yazılır; çağıran taraf akışı keser.
    """
    for tur, deger in _adim_dene(veri, baslik, uretec):
        if tur == "bildir":
            yield tur, deger
        elif tur == "ok":
            yield "sonuc", deger
        elif tur == "durdu":
            yield "dur", _durdur_yaz(veri, baslik)
        else:
            yield "dur", hata_yaz(veri, kayit, baslik, deger)


def _hesaplari_dene(veri, kayit, baslik, hizmet, uretec_yap, kontrol=None, dayanikli=False):
    """Bir hizmetin hesaplarını **aktif olandan başlayarak sırayla dene**.

    - Her işlemden önce hesap sağlık kontrolünden geçirilir (ücretsiz, kotasız sorgu).
    - Kota, yetki ya da bağlantı hatası alan hesap bu çalışma boyunca elenir, aynı işlem
      sıradaki hesapla yinelenir; aynı adım kaldığı yerden sürer.
    - **Dakikalık** hız sınırı (`dakikalik_bekleme`) hesabı elemez: sıradaki hesaba
      geçilir; hiçbir hesap yanıt vermezse `HIZ_BEKLEMELERI` kadar beklenip tur yinelenir.
    - Çalışan hesap uygulamanın da aktif hesabı yapılır (★ API hesapları sekmesinde).
    - Hesap değiştirmek çözmeyen bir hata (ör. yanlış model adı) `dayanikli=False` iken
      doğrudan durdurur; `dayanikli=True` iken hata da bir "tükendi" sebebi sayılır, böylece
      çağıran sıradaki **hizmete** geçebilir (bkz. `adim_yedekli_hesapli`).

    Üreteç: `uretec_yap(hesap, kimlik)` her hesap için istemci üretecini üretir.
    Üretilenler `adim_calistir` ile aynıdır: ("bildir", metin) · ("sonuc", değer) · ("dur", mesaj).
    Hizmetin bütün hesapları elendiğinde hata **yazılmaz**: `("tukendi", [(hesap, sebep)])`
    üretilir; hatayı çağıran yazar.
    """
    for tur in range(len(HIZ_BEKLEMELERI) + 1):
        olu, sinirda = [], []
        for cikti in _hesap_turu(veri, kayit, baslik, hizmet, uretec_yap, kontrol, dayanikli,
                                 olu, sinirda):
            yield cikti
            if cikti[0] in ("sonuc", "dur"):
                return
        if not sinirda or tur == len(HIZ_BEKLEMELERI):
            break
        # Hiçbir hesap yanıt vermedi ama en az biri yalnızca **dakikalık** sınırdaydı:
        # kota bitmedi, beklenip aynı hesaplar yeniden denenir.
        sure = max(HIZ_BEKLEMELERI[tur], *sinirda)
        mesaj = (f"{baslik} · {HIZMET_ADI.get(hizmet, hizmet)} hesapları dakikalık hız "
                 f"sınırında; {sure:.0f} sn beklenip yeniden denenecek.")
        not_ekle(veri, mesaj)
        proje_yaz(veri)
        yield "bildir", mesaj
        _yeniden_bekle(sure)
        if IPTAL.is_set():
            yield "dur", _durdur_yaz(veri, baslik)
            return

    # ── bütün hesaplar tükendi: hatayı çağıran yazar ──
    yield "tukendi", olu


def _hesap_turu(veri, kayit, baslik, hizmet, uretec_yap, kontrol, dayanikli, olu, sinirda):
    """Hesapları bir kez dolaş (bkz. `_hesaplari_dene`).

    Yanıt verilirse `("sonuc", …)`, durdurulursa ya da hesap değiştirmenin çözmeyeceği
    bir hata varsa `("dur", …)` üretir. Yanıt veremeyen hesaplar `olu`ya, dakikalık
    sınırdakilerin bekleme süreleri `sinirda`ya eklenir.
    """
    for hesap in hesap_listesi(hizmet):
        if hesap_elendi(hizmet, hesap):
            # Kalıcı kota listesindeki hesaba **hiç istek atılmaz** (kullanıcı kararı,
            # 14.10.2026); sebep "kota" der ki tükenme kota sayılsın ve hak yanmasın.
            acilis = kota_bekliyor(hizmet, hesap)
            olu.append((hesap, f"kota bekleniyor, {saat_metni(acilis)}'de açılır" if acilis
                        else "bu çalışmada elendi (yukarıdaki sebeple)"))
            continue
        saglik, sebep = saglik_kontrol(hizmet, hesap)
        if saglik == "bozuk":
            hesap_ele(hizmet, hesap, sebep)
            olu.append((hesap, sebep))
            not_ekle(veri, f"{baslik} · {hesap_adi(hesap)} hesabı kullanılamıyor ({sebep}); "
                            "sıradaki hesap denenecek.")
            proje_yaz(veri)
            yield "bildir", (f"{baslik} · {hesap_adi(hesap)} hesabı kullanılamıyor ({sebep}); "
                             "sıradaki hesap deneniyor.")
            continue
        if hesap_aktif_yap(hizmet, hesap):
            # Çalışan hesap uygulamada da aktif olur; kullanıcı hangi hesabın
            # kullanıldığını hem panelde hem API hesapları sekmesinde görür.
            not_ekle(veri, f"{baslik} · {HIZMET_ADI.get(hizmet, hizmet)} "
                            f"{hesap_adi(hesap)} hesabına geçti.")
            yield "bildir", (f"{baslik} · {hesap_adi(hesap)} hesabına geçildi "
                             f"({HIZMET_ADI.get(hizmet, hizmet)}).")
        son_hata = ""
        for tur, deger in _adim_dene(veri, f"{baslik} · {hesap_adi(hesap)}",
                                     uretec_yap(hesap, hesap_kimligi(veri, hizmet, hesap)), kontrol):
            if tur == "bildir":
                yield "bildir", deger
            elif tur == "ok":
                # Hesap yanıt verdi: geçici hata sayacı sıfırlanır, bir sonraki
                # işlemde temiz sayfayla başlar.
                hesap_basarisi(hizmet, hesap)
                yield "sonuc", deger
                return
            elif tur == "durdu":
                yield "dur", _durdur_yaz(veri, baslik)
                return
            else:
                son_hata = deger
        if dayanikli and metin_engeli_mi(son_hata):
            # Servisin içerik politikası **isteği** engelledi: diğer hesaplar da aynı
            # cevabı verir. Hesap elenmez, sayacı artmaz; doğrudan sıradaki servise geçilir.
            mesaj = (f"{baslik} · {HIZMET_ADI.get(hizmet, hizmet)} içerik politikası isteği "
                     "engelledi; aynı istek bu servisin diğer hesaplarında da engelleneceği için "
                     "sıradaki servise geçiliyor. Karakter tariflerindeki yaş/çocuk ifadeleri "
                     "(ör. '8-year-old girl') bu filtreyi tetikleyebilir.")
            olu.append((hesap, f"içerik politikası isteği engelledi: {_ilk_satir(son_hata, 120)}"))
            not_ekle(veri, mesaj)
            proje_yaz(veri)
            yield "bildir", mesaj
            return
        etiket = hata_etiketle(son_hata)
        if icerik_filtresi_mi(son_hata) or gpu_yok_mu(son_hata) or (
                not dayanikli and etiket not in ("KOTA", "YETKİ", "BAĞLANTI")):
            # İçerik filtresi kareyi reddetti: başka hesap aynı kareyi alır, hesap
            # sağlamdır (14.10.2026: filtre reddi geçici hata sayılıp hesap yakılıyordu).
            # Boş GPU yokluğu da hesabın değil Space'in hâlidir; `denemeli` bekleyip dener.
            # Hesap değiştirmek çözmez (ör. model adı yanlış): doğrudan hata yaz.
            yield "dur", hata_yaz(veri, kayit, baslik, son_hata)
            return
        # Kota ve yetki hesabın kendi sorunudur: hesap bu çalışma boyunca elenir.
        # Geçici hatalar (503, boş yanıt, kopan bağlantı) **servisin** o anki hâliyle
        # ilgilidir; tek hatada çalışan bir hesabı yakmak, hepsi bitmiş gibi
        # görünmesine yol açıyordu. Bu yüzden geçici hata sayılır ve hesap ancak üst
        # üste `GECICI_HATA_SINIRI` kez yanıt veremezse elenir.
        # Dakikalık hız sınırı (ör. Gemini seslendirmesinin dakikada 10 isteği) kota
        # **bitmesi** değildir: hesap elenmez, tur bitince beklenip yeniden denenir.
        bekleme = dakikalik_bekleme(son_hata) if etiket == "KOTA" else None
        kalici = etiket in ("KOTA", "YETKİ") and bekleme is None
        sayac = 0 if kalici or bekleme is not None else hesap_hatasi(hizmet, hesap)
        if bekleme is not None:
            sinirda.append(bekleme)
            _HAVUZ.kota_uyarisi(hizmet, hesap, son_hata)   # listede görünsün (süresi kadar)
            durum = "dakikalık hız sınırında (elenmedi)"
            not_ekle(veri, f"{baslik} · {hesap_adi(hesap)} hesabı {durum}: "
                            f"{_ilk_satir(son_hata, 160)}")
        elif kalici or sayac >= GECICI_HATA_SINIRI:
            hesap_ele(hizmet, hesap, son_hata)
            durum = ("kotası doldu" if etiket == "KOTA" else
                     "yetkisi yok" if etiket == "YETKİ" else
                     f"üst üste {sayac} kez yanıt veremedi")
            not_ekle(veri, f"{baslik} · {hesap_adi(hesap)} hesabı elendi ({durum}): "
                            f"{_ilk_satir(son_hata, 160)}")
        else:
            durum = ("bağlantı hatası verdi" if etiket == "BAĞLANTI" else "hata verdi")
            not_ekle(veri, f"{baslik} · {hesap_adi(hesap)} hesabı {durum} "
                            f"({sayac}/{GECICI_HATA_SINIRI} geçici); elenmedi, sonraki "
                            f"adımda yeniden denenir: {_ilk_satir(son_hata, 160)}")
        olu.append((hesap, son_hata))
        proje_yaz(veri)
        yield "bildir", (f"{baslik} · {hesap_adi(hesap)} hesabı {durum}; "
                         "sıradaki hesap otomatik denenecek.")


def _tukendi_mesaji(veri, kayit, baslik, hizmet, olu):
    """Bir hizmetin bütün hesapları tükendiğinde metne yazılacak hatayı üret."""
    nedenler = "; ".join(f"{hesap_adi(h)}: {_ilk_satir(s, 90)}" for h, s in olu) or "sebep yok"
    # Etiket gerçekten ne olduğunu söylesin: hiçbiri kota değilse "KOTA" ya da
    # "YETKİ" demek yanıltıcıydı (geçici hatalar da öyle görünüyordu).
    etiketler = [hata_etiketle(s) for _, s in olu]
    etiket = next((e for e in ("KOTA", "YETKİ", "BAĞLANTI") if e in etiketler), "HATA")
    # Hiçbir hesap geçici bir hata vermediyse (hepsi kotada, yetkisiz ya da bu çalışmada
    # zaten elenmiş) saniyeler sonra yeniden denemek çözmez (bkz. `denemeli`).
    _YEREL.kota_hizmet = hizmet
    _YEREL.kota_tukendi = etiket == "KOTA" and all(
        e in ("KOTA", "YETKİ") or s.startswith("bu çalışmada elendi")
        for e, (_, s) in zip(etiketler, olu))
    mesaj = (f"{HIZMET_ADI.get(hizmet, hizmet)} için kayıtlı {len(olu)} hesabın hiçbiri "
             f"işlem yapamıyor ({nedenler}). **API hesapları** sekmesinden yeni bir hesap ekleyip "
             "**Kaldığı yerden devam et**'e bas; proje bu adımdan sürer.")
    # Video adımında (kayıt bir adımdır) HF tükendiyse Agnes yolu da söylenir.
    if hizmet == "huggingface" and isinstance(kayit, dict) and "index" in kayit:
        mesaj += " " + AGNES_IPUCU
    return hata_yaz(veri, kayit, baslik, mesaj, etiket=etiket)


def adim_hesapli(veri, kayit, baslik, hizmet, uretec_yap, kontrol=None):
    """İşlemi, hizmetin hesaplarını sırayla deneyerek çalıştır (bkz. `_hesaplari_dene`).

    Tek hizmetin hesapları tükenirse işlem `HATA` olarak metne yazılır ve proje durur.
    """
    for tur, deger in _hesaplari_dene(veri, kayit, baslik, hizmet, uretec_yap, kontrol):
        if tur == "tukendi":
            yield "dur", _tukendi_mesaji(veri, kayit, baslik, hizmet, deger)
            return
        yield tur, deger
        if tur in ("sonuc", "dur"):
            return


def _ai_hizmetleri(secilen):
    """Prompt üretimi için denenecek hizmetler: seçili servis **önce**, sonra yedekler.

    Sıra `AI_YEDEK_SIRA` ile aynıdır (Cloudflare → Gemini → EVREN → ChatGPT → Claude);
    anahtarı kayıtlı olmayan servis denemeye alınmaz. Hiçbirinde anahtar yoksa seçili
    servis tek başına döner ki kullanıcı "anahtarı kayıtlı değil" mesajını görsün.
    """
    sirali = [secilen, *[s for s in AI_YEDEK_SIRA if s != secilen]]
    anahtarli = [s for s in sirali if ai_anahtari(s, aktif_kimlik(s))]
    return anahtarli or [secilen]


def adim_yedekli_hesapli(veri, kayit, baslik, secilen, uretec_yap, kontrol=None):
    """Bir yapay zekâ işlemini **yedekli servis zinciriyle** çalıştır.

    Hugging Face Space'lerindeki davranışın aynısı: seçili servis (ör. Gemini) bütün
    hesaplarıyla tükenirse akış **durmaz**; anahtarı kayıtlı sıradaki prompt servisi
    (ChatGPT, Claude) kendiliğinden denenir. Böylece ücretsiz kotası biten Gemini
    yerine yedek servis prompt'ları yazar ve proje kaldığı yerden sürer. Bütün servisler
    başarısız olursa hata metne yazılır ve proje durur.

    Üreteç: `uretec_yap(hizmet, hesap, kimlik)` — kimlik, denen hesabın anahtarlarını taşır.
    """
    hizmetler = _ai_hizmetleri(secilen)
    olu = []
    for sira, hizmet in enumerate(hizmetler):
        # Bu çalışmada tamamen tükenen servis yeniden denenmez: günlüğü aynı satırlarla
        # doldurmadan doğrudan sıradaki servise geçilir.
        if sira + 1 < len(hizmetler) and all(hesap_elendi(hizmet, hesap)
                                            for hesap in hesap_listesi(hizmet)):
            continue
        for tur, deger in _hesaplari_dene(
                veri, kayit, baslik, hizmet,
                lambda hesap, kimlik, h=hizmet: uretec_yap(h, hesap, kimlik),
                kontrol, dayanikli=True):
            if tur == "tukendi":
                olu += [(hizmet, hesap, sebep) for hesap, sebep in deger]
                if sira + 1 < len(hizmetler):
                    sonraki = hizmetler[sira + 1]
                    mesaj = (f"{HIZMET_ADI.get(hizmet, hizmet)} ile yazılamadı; "
                             f"{HIZMET_ADI.get(sonraki, sonraki)} otomatik denenecek.")
                    not_ekle(veri, f"{baslik} · {mesaj}")
                    proje_yaz(veri)
                    yield "bildir", mesaj
                break
            yield tur, deger
            if tur in ("sonuc", "dur"):
                return
    # ── bütün servisler tükendi: proje burada durur ──
    nedenler = "; ".join(
        f"{HIZMET_ADI.get(h, h)} {hesap_adi(hesap)}: {_ilk_satir(sebep, 80)}"
        for h, hesap, sebep in olu) or "sebep yok"
    etiket = "KOTA" if any(hata_etiketle(sebep) == "KOTA" for _, _, sebep in olu) else "HATA"
    mesaj = (f"Prompt yapay zekâlarının hiçbiri yanıt veremedi ({nedenler}). "
             "**API hesapları** sekmesinden bir anahtar ekleyip "
             "**Kaldığı yerden devam et**'e bas; proje bu adımdan sürer.")
    yield "dur", hata_yaz(veri, kayit, baslik, mesaj, etiket=etiket)


def hata_yaz(veri, kayit, baslik, mesaj, etiket=None):
    """Adımı hata gibi metne yaz ve okunur bir rapor döndür.

    `etiket` verilirse tür zorlanır (bütün hesaplar tükendiğinde mesajın kendisi
    KOTA/YETKİ sözcüklerini içermeyebilir).
    """
    not_ = hata_notu(mesaj) if not etiket else \
        f"[{etiket}] {_ilk_satir(mesaj, 400)} — {ETIKET_IPUCU.get(etiket, ETIKET_IPUCU['HATA'])}"
    veri["durum"] = "bekliyor"
    veri["son_not"] = f"{baslik} · {not_}"
    # Ham sebep ve hatalı kayıt saklanır: otomatik yeniden başlatma bunları okur.
    veri["son_hata"] = _ilk_satir(mesaj, 400)
    veri["son_hata_kayit"] = kayit
    _YEREL.son = (veri, veri["son_hata"], kayit)
    if kayit is not None:
        kayit["durum"] = "HATA"
        kayit["hata"] = not_
    not_ekle(veri, veri["son_not"])
    proje_yaz(veri)
    return f"{baslik} tamamlanamadı, proje kaydedildi.\n{not_}"


def denemeleri_sifirla(ad):
    """Otomatik yeniden başlatma sayaçlarını sıfırla ve projeyi göster.

    Deneme hakkı dolduğunda proje durur. Koruma `proje.txt`'te yaşadığı için
    **Kaldığı yerden devam et** sayacı kendiliğinden açmaz (bilerek: kapanıp açılan
    her deneme sınırsız yeniden denemeye dönmesin). Sorun giderildikten sonra bu
    düğme sayacı açar; bir sonraki çalıştırma hata veren işlemi yeniden dener.
    """
    ad = (ad or "").strip()
    if not ad:
        return bos_paket("Listeden bir proje seç ya da yeni bir proje adı yaz.")
    if calisan() == slug(ad):
        return bos_paket(f"'{ad}' şu anda çalışıyor; sayaçlar çalışma sürerken değişmesin. "
                    "Önce **Durdur**'a bas.")
    klasor = proje_klasoru(ad)
    veri = proje_oku(klasor) if klasor.is_dir() else None
    if veri is None:
        return bos_paket(f"'{ad}' okunamadı: klasöründe okunabilir bir {DOSYA_ADI} yok.")
    harcanan = sum(int(sayi or 0) for sayi in (veri.get("deneme") or {}).values())
    harcanan += sum(int(sayi or 0) for adim in veri["adimlar"]
                    for sayi in (adim.get("deneme") or {}).values())
    veri["deneme"] = {}
    for adim in veri["adimlar"]:
        adim["deneme"] = {}
        # Hak açıldı: "[DENEME DOLDU] … yenile ·" öneki artık yanlış; asıl sebep kalır.
        hata = adim.get("hata") or ""
        if hata.startswith("[DENEME DOLDU]") and " · " in hata:
            adim["hata"] = hata.split(" · ", 1)[1]
    not_ekle(veri, f"Otomatik deneme sayaçları sıfırlandı ({harcanan} harcanmış deneme "
                    f"vardı); hata veren işlemler yeniden {YENIDEN_SINIR} deneme hakkıyla "
                    "çalışacak.")
    proje_yaz(veri)
    return arayuz_paketi(veri, f"Deneme sayaçları sıfırlandı ({harcanan} harcanmış deneme vardı). "
                        "**Kaldığı yerden devam et**'e basınca akış kaldığı yerden sürer.\n"
                        f"Klasör: {klasor}")
