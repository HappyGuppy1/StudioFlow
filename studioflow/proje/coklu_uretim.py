"""Tekli / çoklu üretim: karelerin ve kliplerin hesaplara bölünüp paralel üretilmesi.

**Tekli üretim** (varsayılan) eski davranıştır: akış adımları baştan tarar, eksik olanı
sırayla, hizmetin hesap sırasıyla üretir.

**Çoklu üretim** (önizleme başlığındaki düğme, kullanıcı kararı 12.10.2026): üretilecek
adımlar en fazla `AZAMI_GRUP` asıl hesaba bölünür, her asıl hesaba bir **yedek** hesap
eşlenir. Her grup kendi iş parçacığında yalnızca kendi adımlarını üretir; asıl hesabın
kotası biterse yalnızca kendi yedeğine geçer, başka grubun hesabına karışmaz (bkz.
`hesap_havuzu.hesaplari_sabitle`). Örnek: 100 kare, 20 Cloudflare hesabı → 10 asıl hesap
10'ar kare, kalan 10 hesap birebir yedek. Bölünmeyen artık (101 kare → biri 11) rastgele
gruplara dağıtılır.
"""
import queue
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.calisma_kilidi import IPTAL
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.ilerleme import arayuz_paketi
from studioflow.saglayicilar.hesap_havuzu import (
    HIZMET_ADI, KAYITSIZ, hesap_elendi, hesap_listesi, hesaplari_sabitle, saglik_kontrol)
from studioflow.saglayicilar.kota_listesi import VARSAYILAN as KOTA_LISTESI, saat_metni

URETIM_TEKLI, URETIM_COKLU = "tekli", "coklu"
URETIM_MODLARI = {URETIM_TEKLI: "Tekli üretim", URETIM_COKLU: "Çoklu üretim"}

# Aynı anda çalışan asıl hesap sınırı (yedekler bu sayıya dahil değildir).
# 21.10.2026: 10'dan 5'e indirildi. Greek'te 10 grup aynı anda LTX'e gidince denemelerin
# %65'i "No GPU" ile döndü; her biri kotadan 75 sn yiyor (HF quota uç noktasıyla ölçüldü).
AZAMI_GRUP = 5


class UretimModu:
    """Arayüzde seçilen üretim modu; görsel ve video aşamaları başlarken okunur."""

    def __init__(self):
        self.deger = URETIM_TEKLI

    def ayarla(self, deger):
        self.deger = deger if deger in URETIM_MODLARI else URETIM_TEKLI
        return self.deger

    def coklu(self):
        return self.deger == URETIM_COKLU


VARSAYILAN = UretimModu()
uretim_modu_ayarla = VARSAYILAN.ayarla
coklu_mu = VARSAYILAN.coklu


def hesap_plani(adimlar, hesaplar, azami=AZAMI_GRUP, rastgele=None):
    """Adımları hesaplara böl: `[{"asil", "yedek", "adimlar"}, ...]`.

    Asıl hesap sayısı `azami`yı, adım sayısını ve hesapların yarısını (yukarı yuvarlanır)
    geçmez; kalan hesaplar sırayla asıllara yedek olur (yedeği olmayan asıl olabilir).
    Yirmiden fazla hesap varsa artanlar gruplara sırayla **ek yedek** olur (`ekler`).
    Her gruba ardışık bir dilim düşer; artık adımlar rastgele seçilen gruplara birer
    birer eklenir.
    """
    adimlar, hesaplar = list(adimlar), list(hesaplar)
    if not adimlar or not hesaplar:
        return []
    sayi = min(azami, len(adimlar), (len(hesaplar) + 1) // 2)
    asillar, yedekler = hesaplar[:sayi], hesaplar[sayi:sayi * 2]
    # 14.10.2026: 22 hesabın 21'i kotadayken kotası olan tek hesap 21. sıradaydı ve
    # hiçbir gruba girmediği için hiç denenmedi. Artık hesap boşta kalmaz.
    artanlar = hesaplar[sayi * 2:]
    taban, artik = divmod(len(adimlar), sayi)
    fazla = set((rastgele or random).sample(range(sayi), artik))
    plan, bas = [], 0
    for sira, asil in enumerate(asillar):
        boy = taban + (1 if sira in fazla else 0)
        plan.append({"asil": asil, "yedek": yedekler[sira] if sira < len(yedekler) else "",
                     "ekler": artanlar[sira::sayi], "adimlar": adimlar[bas:bas + boy]})
        bas += boy
    return plan


def kullanilabilir_hesaplar(hizmet):
    """Hizmetin plana girecek hesapları: elenmemiş ve sağlık kontrolünde bozuk çıkmayan.

    Sağlık kontrolü kotasız, ücretsiz bir sorgudur; hesaplar paralel denetlenir.
    """
    adaylar = [kayit for kayit in hesap_listesi(hizmet)
               if kayit["ad"] != KAYITSIZ and not hesap_elendi(hizmet, kayit)]
    if not adaylar:
        return []
    with ThreadPoolExecutor(max_workers=min(len(adaylar), AZAMI_GRUP)) as havuz:
        sonuclar = list(havuz.map(lambda kayit: saglik_kontrol(hizmet, kayit), adaylar))
    return [kayit["ad"] for kayit, (durum, _m) in zip(adaylar, sonuclar) if durum != "bozuk"]


def _araliklar(adimlar):
    """Adım numaralarını kısa yaz: `1–10, 14, 20–22`."""
    sayilar = sorted(int(adim["index"]) for adim in adimlar)
    parcalar, bas = [], None
    for sira, sayi in enumerate(sayilar):
        if bas is None:
            bas = sayi
        if sira + 1 == len(sayilar) or sayilar[sira + 1] != sayi + 1:
            parcalar.append(str(bas) if bas == sayi else f"{bas}–{sayi}")
            bas = None
    return ", ".join(parcalar)


def plan_ozeti(plan):
    return " · ".join(
        f"'{grup['asil']}' → adım {_araliklar(grup['adimlar'])} ({len(grup['adimlar'])})"
        + (f", yedek '{grup['yedek']}'" if grup["yedek"] else ", yedeksiz")
        + "".join(f" + '{ek}'" for ek in grup.get("ekler") or ())
        for grup in plan)


def _paket_mesaji(paket):
    """Arayüz paketinin durum metni (testlerde paket düz metin olabilir)."""
    return paket[0] if isinstance(paket, tuple) else str(paket)


def grup_tablosu(is_adi, plan, durumlar, biten):
    """Durum paneli: her grubun **sabit satırı** (kullanıcı kararı, 12.10.2026).

    On grup aynı anda çalışırken mesajlar birbirinin üstüne yazılmasın; her satır
    kendi grubunun son kısa durumunu taşır: `ber · 2/7 · Adım 28 · video oluştu ✔`.
    """
    toplam = sum(len(grup["adimlar"]) for grup in plan)
    satirlar = [f"Çoklu {is_adi} · {len(plan)} grup · {sum(biten.values())}/{toplam} adım bitti"]
    for sira, grup in enumerate(plan):
        satirlar.append(f"{grup['asil']} · {biten.get(sira, 0)}/{len(grup['adimlar'])} · "
                        + durumlar.get(sira, "sırada…"))
    return "\n".join(satirlar)


def calistir(veri, is_adi, hizmet, adimlar, is_yap, azami=AZAMI_GRUP, grup_baglami=None):
    """Adımları çoklu üretimle çalıştır (üreteç; arayüz paketleri üretir).

    `azami` aynı anda çalışan grup sınırıdır (ör. kendi LTX Space'imizde `video_ltx.ESZAMANLI`).
    `grup_baglami(sira)` verilirse her grubun iş parçacığı bu bağlamda çalışır (ör. LTX'te
    grubu kendi Space'ine bağlamak: `video_ltx.VARSAYILAN.space_sabitle`).
    `is_yap(adim)` tek adımı üreten üreteçtir ve akış kesilmeliyse `True` döndürür
    (tekli akıştaki adım gövdesinin aynısı). Dönüş: `None` → çoklu üretim kurulamadı,
    çağıran tekli üretime düşer · `True` → en az bir grup durdu, akış kesilmeli ·
    `False` → bütün gruplar bitti ya da kullanıcı durdurdu (durdurmayı akış ele alır).
    """
    ad = HIZMET_ADI.get(hizmet, hizmet)
    yield arayuz_paketi(veri, f"Çoklu {is_adi} üretimi · {ad} hesapları kontrol ediliyor…")
    hesaplar = kullanilabilir_hesaplar(hizmet)
    # Kota bekleme listesindekiler plana hiç girmez (bkz. `kota_listesi`); kaç tanesinin
    # dışarıda kaldığı ve ilkinin ne zaman açılacağı mesajda yazar.
    bekleyen = KOTA_LISTESI.liste(hizmet)
    bekleme = (f"; {len(bekleyen)} hesap kota bekliyor, ilki '{bekleyen[0]['ad']}' "
               f"{saat_metni(bekleyen[0]['acilis'])}" if bekleyen else "")
    if len(hesaplar) < 2 or len(adimlar) < 2:
        sebep = (f"{ad} için kullanılabilir {len(hesaplar)} hesap var{bekleme}"
                 if len(hesaplar) < 2 else "üretilecek tek adım var")
        mesaj = f"Çoklu {is_adi} üretimi kurulamadı ({sebep}); tekli üretimle sürüyor."
        not_ekle(veri, mesaj)
        proje_yaz(veri)
        yield arayuz_paketi(veri, mesaj)
        return None
    plan = hesap_plani(adimlar, hesaplar, azami=azami)
    mesaj = (f"Çoklu {is_adi} üretimi · {len(adimlar)} adım {len(plan)} {ad} hesabına "
             f"bölündü{bekleme}: {plan_ozeti(plan)}")
    not_ekle(veri, mesaj)
    proje_yaz(veri)
    yield arayuz_paketi(veri, mesaj)

    kuyruk, sonuclar = queue.Queue(), {}

    def isci(sira, grup):
        kalan = list(grup["adimlar"])
        try:
            with hesaplari_sabitle(hizmet, [grup["asil"], grup["yedek"],
                                            *(grup.get("ekler") or ())]), \
                    (grup_baglami(sira) if grup_baglami else nullcontext()):
                while kalan and not IPTAL.is_set():
                    akis = is_yap(kalan[0])
                    while True:
                        try:
                            kuyruk.put(("paket", sira, _paket_mesaji(next(akis))))
                        except StopIteration as bitis:
                            durdu = bitis.value
                            break
                    if durdu:
                        sonuclar[sira] = ("durdu", kalan, "")
                        return
                    kalan.pop(0)
                    kuyruk.put(("ilerleme", sira, None))
            sonuclar[sira] = ("tamam" if not kalan else "durdu", kalan, "")
        except Exception as hata:          # grubu çökertmesin, diğerleri sürsün
            sonuclar[sira] = ("durdu", kalan, _ilk_satir(hata, 200))
        finally:
            kuyruk.put(("bitti", sira, None))

    iscilar = [threading.Thread(target=isci, args=(sira, grup), daemon=True,
                                name=f"coklu-{is_adi}-{sira + 1}")
               for sira, grup in enumerate(plan)]
    for isci_ in iscilar:
        isci_.start()
    acik = len(iscilar)
    durumlar, biten = {}, {}
    yield arayuz_paketi(veri, grup_tablosu(is_adi, plan, durumlar, biten))
    try:
        while acik:
            olaylar = [kuyruk.get()]
            while True:
                try:
                    olaylar.append(kuyruk.get_nowait())
                except queue.Empty:
                    break
            for tur, sira, deger in olaylar:
                if tur == "paket":
                    durumlar[sira] = deger.split("\n", 1)[0]
                elif tur == "ilerleme":
                    biten[sira] = biten.get(sira, 0) + 1
                else:
                    acik -= 1
                    son = durumlar.get(sira, "")
                    durumlar[sira] = ("bitti ✔" if biten.get(sira, 0) == len(plan[sira]["adimlar"])
                                      else "durdu ✖" + (f" · {son.removesuffix(' ✖')}"
                                                        if son else ""))
            # Birikenler tek pakette gösterilir: panel her grubun son durumunu taşır.
            yield arayuz_paketi(veri, grup_tablosu(is_adi, plan, durumlar, biten))
    except GeneratorExit:
        # Arayüz akışı bıraktı: gruplar da dursun (tekli akış da ilerletilmeyince durur).
        IPTAL.set()
        raise

    if IPTAL.is_set():
        return False
    duranlar = [(plan[sira], kalan, hata) for sira, (durum, kalan, hata)
                in sorted(sonuclar.items()) if durum != "tamam"]
    if not duranlar:
        mesaj = f"Çoklu {is_adi} üretimi tamam · {len(plan)} grubun hepsi bitti."
        not_ekle(veri, mesaj)
        proje_yaz(veri)
        yield arayuz_paketi(veri, grup_tablosu(is_adi, plan, durumlar, biten) + "\n\n" + mesaj)
        return False
    ayrinti = "; ".join(
        f"'{grup['asil']}'" + (f"+'{grup['yedek']}'" if grup["yedek"] else "")
        + "".join(f"+'{ek}'" for ek in grup.get("ekler") or ())
        + f" grubu durdu, eksik adım {_araliklar(kalan)}" + (f" ({hata})" if hata else "")
        for grup, kalan, hata in duranlar)
    veri["durum"] = "bekliyor"
    veri["son_not"] = (f"Çoklu {is_adi} üretimi: {len(plan) - len(duranlar)}/{len(plan)} grup "
                       f"bitti · {ayrinti}. Hata satırlarına bak; **Kaldığı yerden devam et** "
                       "yalnızca eksik adımları yeniden üretir.")
    not_ekle(veri, veri["son_not"])
    proje_yaz(veri)
    yield arayuz_paketi(veri, grup_tablosu(is_adi, plan, durumlar, biten) + "\n\n"
                        + f"{len(duranlar)} grup durdu · ‘Kaldığı yerden devam et’ yalnızca "
                        "eksik adımları üretir.")
    return True
