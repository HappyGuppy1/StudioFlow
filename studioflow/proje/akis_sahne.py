"""Adımların kurulması, sahnelerin gerçek konuşmaya hizalanması ve sahne prompt'larının
yapay zekâya yazdırılması (akışın sahneleme ve prompt aşamaları).
"""
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir, sayi as _sayi
from studioflow.proje.adim_promptlari import ilk_sahne_kaydi, prompt_grubu_uret
from studioflow.proje.akis_servis import prompt_kontrol
from studioflow.proje.depo import proje_adim_saniyesi
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.katmanlar.ses_ekleme import altyazi_kelimeleri
from studioflow.proje.kiyafet import analiz_hazirla, filtre_acik
from studioflow.proje.prompt_uretimi import GRUP_BOYU
from studioflow.proje.sabitler import ADIM_SANIYE, PROMPT_KELIME_SINIRI, SURE_SINIRLARI
from studioflow.proje.sahneleme import (
    bolme_puani, bolum_basligi_mi, icerik_sahneleri, parcalara_bol, plan_sahneleri,
    sahne_plani_detayli, sahne_tavani, sahneleri_sureye_uydur)
from studioflow.proje.sahne_stratejileri import VARSAYILAN_STRATEJI
from studioflow.proje.yeniden_deneme import adim_yedekli_hesapli, dur_turu, hata_yaz
from studioflow.saglayicilar import gorsel_cloudflare
from studioflow.saglayicilar.hesap_havuzu import aktif_kimlik
from studioflow.saglayicilar.metin_ortak import ai_anahtari


def adimlari_kur(veri, sure, sahneler=None):
    """Sahne planını adımlara dönüştür ve projeye yaz.

    Her sahne bir adımdır ve **kendi süresini** taşır (`start`/`end`); süreler anlatımın
    içeriğine göre değişir (bkz. `sahneleme.sahne_plani_detayli`). `sahneler`
    verilmezse eski davranışa (eşit `video.adim_saniye`lik parçalar) düşülür.
    """
    if not sahneler:
        saniye = proje_adim_saniyesi(veri)
        sahneler = [{"text": parca["text"], "saniye": saniye}
                    for parca in parcalara_bol(veri["metin"], sure, saniye)]
    adimlar, bas = [], 0.0
    # Son ağ: hizalamadaki iki uç durum (kısa sahneleri birleştirme, son sahnenin sesin
    # sonuna kadar uzaması) projenin tavanını aşabiliyor. Tavan **projeden** okunur,
    # sabitten değil: kullanıcı kaydırıcıyla kendi videosuna göre seçiyor.
    tavan = proje_adim_saniyesi(veri)
    for sira, sahne in enumerate(sahneler, 1):
        saniye = max(SURE_SINIRLARI[0],
                     min(tavan,
                         _sayi(sahne.get("saniye"), ADIM_SANIYE, float)))
        adimlar.append({"index": sira, "start": round(bas, 2), "end": round(bas + saniye, 2),
                        "text": (sahne.get("text") or "").strip(), "durum": "BEKLİYOR",
                        "bitti": "", "image_prompt": "", "negative_prompt": "",
                        "video_prompt": "", "gorsel": "", "video": "", "hata": "",
                        "deneme": {}})
        bas += saniye
    veri["adimlar"] = adimlar
    not_ekle(veri, f"{sure:.2f} saniye anlatım {len(adimlar)} sahneye bölündü · "
                    f"toplam video {bas:.2f} sn. Sahne süreleri anlatımın içeriğine göre "
                    "değişken (" + f"{SURE_SINIRLARI[0]:g}".replace(".", ",")
                    + "–" + f"{proje_adim_saniyesi(veri):g} sn).")


def sahneleri_zamanla(klasor, veri, sahneler, sure, alt, ust, azami_sahne=60):
    """Sahne sürelerini **gerçek konuşmanın kelime zamanlarına** birebir hizala.

    Altyazının (SRT) da üretildiği kelime zamanları (`altyazi_kelimeleri`) kullanılır:
    ses varsa ve Cloudflare anahtarları kayıtlıysa ses dinlenir (whisper) ve zamanlar
    anlatımın kelimelerine eşlenir; aksi hâlde zamanlar metinden tahmin edilir. Her sahne
    kendi **ilk kelimesinin söylenmeye başladığı an** başlar ve sonraki sahnenin ilk
    kelimesine kadar sürer; böylece sahne değişimi tam o cümlenin başında olur ve süreler
    toplamı sesin süresini birebir kapsar. `üst` saniyeyi aşan sahne (video Space'i daha
    uzun klip üretemez) kelime sınırlarından parçalara bölünür; yapay zekânın cümle
    gruplaması korunur. Zamanlar çıkarılamazsa plan olduğu gibi bırakılır.

    Dönüş: `(sahneler, zaman_kaynağı)` · kaynak `"ses"` · `"metin"` · `"yok"`.
    """
    metin = (veri.get("metin") or "").strip()
    if not sahneler or not metin or sure <= 0:
        return sahneler, "yok"
    kelimeler, zaman_kaynak, sebep = altyazi_kelimeleri(klasor, veri, metin, sure)
    if zaman_kaynak == "metin" and sebep:
        # Tahmini zamanlar sahneleri sesten birkaç saniye kaydırabilir; bu eskiden
        # yalnızca planın gerekçesinde geçiyordu ve fark edilmiyordu (12.10.2026).
        not_ekle(veri, "Sahne planı · UYARI: ses dinlenemedi, sahne zamanları metinden "
                       f"tahmin edildi; sahneler sesle kayabilir ({_ilk_satir(sebep, 200)}). "
                       "Kotası olan bir Cloudflare hesabıyla sahne planını yenile.")
    if not kelimeler:
        return sahneler, "yok"
    baslar = [float(k[0]) for k in kelimeler]
    bitisler = [float(k[1]) for k in kelimeler]
    sozcuk = [str(k[2]) for k in kelimeler]
    adetler = [len((s.get("text") or "").split()) for s in sahneler]
    # Sahne metinleri anlatımı eksiksiz ve sırayla kapsamalı; yoksa hizalama güvenilmez.
    if not all(adetler) or sum(adetler) != len(kelimeler):
        return sahneler, "yok"
    # 1) Yapay zekânın cümle gruplamasını kelime aralıklarına çevir.
    araliklar, konum = [], 0
    for adet in adetler:
        araliklar.append((konum, konum + adet))
        konum += adet
    # 2) Tavanı aşan aralık **dengeli ve dilbilgisine uygun** bölünür. Adaylar puanlanır
    # (bkz. `sahneleme.bolme_puani`): cümle sonu < virgül/noktalı virgül < bağlacın önü <
    # sıradan kelime sınırı; parça asılı kalan bir işlev kelimesiyle ("and", "the", "to",
    # "his"…) **bitemez**. En iyi puan grubunda iki parçanın süresini en eşit yapan nokta
    # seçilir; parça hâlâ uzunsa aynı kural tekrarlanır. Eskiden yalnızca cümle sonu ve
    # virgül biliniyordu, sonra ortaya en yakın kelimeye düşülüyordu (Greek Mythology,
    # 05.10.2026: "…from the cliff, and" / "six sailors…", "gave birth to" / "a monster",
    # "in the" / "dark"). Kırıntı (claudetest, 29.09.2026: "…its ramps like" + "ants.")
    # `alt` sınırıyla önlenir.
    asil_sozcukler = metin.split()

    def sinir(k):
        return 0.0 if k == 0 else (float(sure) if k == len(baslar) else baslar[k])

    def bol(i, son):
        if son - i <= 1 or sinir(son) - sinir(i) <= ust + 1e-6:
            return [[i, son]]
        orta = (sinir(i) + sinir(son)) / 2
        adaylar = []
        for k in range(i + 1, son):
            puan = bolme_puani(asil_sozcukler[k - 1], asil_sozcukler[k])
            if puan is None:
                continue
            yeterli = sinir(k) - sinir(i) >= alt and sinir(son) - sinir(k) >= alt
            adaylar.append((not yeterli, puan, abs(sinir(k) - orta), k))
        if not adaylar:     # her sınır yasak (çok kısa aralık): ortadan kes
            adaylar = [(False, 9, abs(sinir(k) - orta), k) for k in range(i + 1, son)]
        k = min(adaylar)[3]
        return bol(i, k) + bol(k, son)

    gruplar = []
    for bas, son in araliklar:
        gruplar += bol(bas, son)

    def baslik(g):
        return bolum_basligi_mi(" ".join(asil_sozcukler[g[0]:g[1]]))

    # 3) `alt` saniyeden kısa grupları komşusuyla birleştir. Bölüm başlığı ("Number four.")
    # önceki bölümün sahnesine eklenmez: kısa başlık **sonraki** sahneye katılır.
    i = 0
    while i < len(gruplar):
        kisa = (bitisler[gruplar[i][1] - 1] - baslar[gruplar[i][0]]) < alt
        if kisa and baslik(gruplar[i]) and i + 1 < len(gruplar) \
                and sinir(gruplar[i + 1][1]) - sinir(gruplar[i][0]) <= ust:
            gruplar[i][1] = gruplar[i + 1][1]
            del gruplar[i + 1]
            continue
        if kisa and i > 0 and not baslik(gruplar[i]) \
                and sinir(gruplar[i][1]) - sinir(gruplar[i - 1][0]) <= ust:
            gruplar[i - 1][1] = gruplar[i][1]
            del gruplar[i]
            continue
        i += 1
    # Fazla grup eritilirken de bölüm sınırı geçilmez (başlıkla başlayan grup öncekine
    # eklenmez). Tavanı çağıran verir: planın sahne sayısı korunur, yalnızca bölmenin
    # ürettiği fazlalık geri birleşir.
    while len(gruplar) > max(1, int(azami_sahne)) and len(gruplar) > 1:
        adaylar = [k for k in range(1, len(gruplar))
                   if not baslik(gruplar[k])
                   and sinir(gruplar[k][1]) - sinir(gruplar[k - 1][0]) <= ust]
        if not adaylar:
            break
        k = min(adaylar,
                key=lambda t: bitisler[gruplar[t][1] - 1] - baslar[gruplar[t][0]])
        gruplar[k - 1][1] = gruplar[k][1]
        del gruplar[k]
    # 4) Sınırlar: ilk sahne 0'dan, son sahne sesin sonuna kadar sürer.
    sinirlar = [0.0]
    for bas, _son in gruplar[1:]:
        sinirlar.append(baslar[bas])
    sinirlar.append(float(sure))
    for k in range(1, len(sinirlar)):
        sinirlar[k] = max(sinirlar[k], sinirlar[k - 1])
    hizali = [{"text": " ".join(sozcuk[bas:son]),
               "saniye": round(max(sinirlar[k + 1] - sinirlar[k], alt), 2)}
              for k, (bas, son) in enumerate(gruplar)]
    return hizali, ("ses" if zaman_kaynak == "ses" else "metin")


def sahne_plani_uret(veri, klasor, sure, on_plan=None):
    """Anlatımı sahnelere ayır: **ana sayfadaki plan** ya da yapay zekâ/içerik yedeği.

    `on_plan` verilmişse (ana sayfada 🎬 düğmesiyle üretilip kaydedilen plan) ve bu
    anlatıma/stratejiye aitse sahne listesi **aynen** kullanılır: akış sahneyi ikinci
    bir yapay zekâ isteğiyle yeniden planlamaz, böylece ana sayfada görünen sahne
    sayısı ile üretilen sahne sayısı aynı kalır (bkz. `sahneleme.plan_sahneleri`).
    Plan yoksa/eskiyse yapay zekâdan detaylı plan istenir; alınamazsa `sahneleme`
    içindeki içerik yedeğine düşülür. Ardından sahne süreleri **gerçek konuşmanın
    kelime zamanlarına** birebir hizalanır (`sahneleri_zamanla`); zamanlar
    çıkarılamazsa süreler ses süresine göre dengelenir.

    Dönüş: `(sahneler, kaynak, gerekçe)`.
    """
    ayar = veri["ayarlar"]["video"]
    ses = veri["ayarlar"]["ses"]
    alt = SURE_SINIRLARI[0]
    ust = max(alt, proje_adim_saniyesi(veri))
    dil = LANGUAGES.get(ses.get("dil"), ses.get("dil") or "tr")
    strateji = ayar.get("sahne_stratejisi", VARSAYILAN_STRATEJI)
    # Servis geçişleri günlüğe yazılır: plan yazılırken Gemini bırakıp ChatGPT'ye
    # geçildiyse bu, planın kaynağıyla birlikte `proje.txt`'te görünür.
    notlar = []
    sahneler = plan_sahneleri(on_plan, veri["metin"], strateji)
    if sahneler:
        kaynak = "ana sayfa"
        gerekce = "ana sayfadaki yapay zekâ planı kullanıldı"
    else:
        try:
            plan = sahne_plani_detayli(
                ayar["ai"], ai_anahtari(ayar["ai"], aktif_kimlik(ayar["ai"])), ayar.get("model"),
                veri["metin"], dil, (alt, ust), toplam_sure=sure, hiz=ses.get("hiz") or 0,
                bildir=notlar.append, strateji=strateji)
            sahneler = plan["adimlar"]
            kaynak = plan.get("kaynak", "icerik")
            gerekce = plan.get("gerekce", "")
        except Exception as exc:
            sahneler = icerik_sahneleri(veri["metin"], sure, alt, ust,
                                        hiz=ses.get("hiz") or 0)
            kaynak, gerekce = "icerik", f"plan alınamadı ({_ilk_satir(exc, 160)}); içerik yedeği"
    for not_ in notlar:
        not_ekle(veri, "Sahne planı · " + not_)
    if notlar:
        gerekce = (gerekce + " · " if gerekce else "") + " · ".join(notlar)
    # Planın sahne sayısı korunur: hizalama yalnızca bölmenin ürettiği fazlalığı eritir
    # (eskiden sabit 60'a indiriyordu; 🎬'nin 156 sahnelik planı 90'a birleşti).
    hizali, zaman_kaynak = sahneleri_zamanla(
        klasor, veri, sahneler, sure, alt, ust,
        azami_sahne=max(sahne_tavani(60, sure, ust), len(sahneler)))
    if zaman_kaynak != "yok":
        # Sayfadaki plan tahmini süreyle yapılır; gerçek seste tavanı aşan sahne ikiye
        # bölünür. Bu sessiz kalınca iki ekranda "farklı sahneler" görülüyordu
        # (claudetest4, 29.09.2026: sayfada 12, projede 14 sahne).
        if len(hizali) != len(sahneler):
            # Mesaj gerçekte olanı söyler: eskiden sahneler birleştirildiğinde de
            # "bölündü" yazıyordu (156 → 90 sahne "123 sahne bölündü" diye geçti).
            degisen = [str(s.get("text") or "")[:40] for s in sahneler
                       if not any(h["text"] == str(s.get("text") or "").strip() for h in hizali)]
            islem = ("tavanını aşan sahneler cümle/virgül sınırından bölündü"
                     if len(hizali) > len(sahneler) else
                     "altındaki kısa sahneler komşularıyla birleştirildi")
            not_ekle(veri, f"Sahne planı · plan {len(sahneler)} sahneydi; gerçek seste {ust:g} sn "
                           f"{islem} → {len(hizali)} sahne ({len(degisen)} sahne değişti"
                           + (": " + " · ".join(f"“{b}…”" for b in degisen[:8]) if degisen else "")
                           + ").")
        sahneler = hizali
        etiket = ("gerçek sesin kelime zamanlarına birebir hizalandı"
                  if zaman_kaynak == "ses" else
                  "kelime zamanları metinden tahmin edilerek hizalandı")
        gerekce = (gerekce + " · " if gerekce else "") + etiket
    elif kaynak == "ana sayfa":
        # Hizalama yapılamadı: ana sayfa planının süreleri **tahmini** ses süresine
        # göreydi; gerçek sesle videonun kısa kalmaması için süreler dengelenir.
        sahneler = sahneleri_sureye_uydur(sahneler, sure, alt, ust)
        gerekce += " · hizalama yok, süreler ses süresine göre dengelendi"
    return sahneler, kaynak, gerekce


def eksik_prompt_adimlari(veri):
    return [adim for adim in veri["adimlar"]
            if not (adim.get("image_prompt") and adim.get("video_prompt"))]


def prompt_isi_var(veri):
    """Sahne planını/prompt'ları yazacak **yapay zekâ işi** kaldı mı?

    Seslendirme bittikten sonra akış, yapacak iş varsa (sahne planı yok ya da prompt'ı
    eksik sahneler var) durur ve kullanıcıdan yapay zekâ seçimini bekler (bkz.
    `akis_calistir`). Her şey yazılmışsa kapı devreye girmez: devam eden bir akış
    gereksiz yere beklemez.
    """
    return (not veri.get("adimlar")) or bool(eksik_prompt_adimlari(veri))


def adim_prompt(veri):
    """Bütün adımların prompt'larını, görsel/video üretimine geçmeden önce yaz.

    Seçili prompt yapay zekâsı (ör. Gemini) kota/yetki/model hatası verirse akış
    durmaz: anahtarı kayıtlı yedek servis (ChatGPT, Claude) otomatik denenir
    (`adim_yedekli_hesapli`).

    Üreteç; iletileri sade metin olarak üretir ve bittiğinde durumu döndürür:
    `"ok"` · `"hata"` · `"durdu"` (otomatik yeniden başlatmayı çağıran yönetir).
    """
    ayar = veri["ayarlar"]["video"]
    eksik = eksik_prompt_adimlari(veri)
    if eksik:
        not_ekle(veri, f"{len(eksik)} adım için prompt yazılıyor ({ayar['ai']}).")
        proje_yaz(veri)
        yield f"{len(eksik)} adım için görsel ve video prompt'ları yazılıyor…"
    for baslangic in range(0, len(veri["adimlar"]), GRUP_BOYU):
        grup = [adim for adim in veri["adimlar"][baslangic:baslangic + GRUP_BOYU]
                if not (adim.get("image_prompt") and adim.get("video_prompt"))]
        if not grup:
            continue
        baslik = f"Prompt {grup[0]['index']}–{grup[-1]['index']}"
        # Gruplar arası süreklilik: bir önceki gruptaki **son iki sahnenin** yazılmış
        # prompt'ları isteğe eklenir, böylece 6.→7. sahne geçişinde karakter, kıyafet
        # ve palet kaymaz.
        onceki = [adim for adim in veri["adimlar"][max(0, baslangic - 2):baslangic]
                  if adim.get("image_prompt")]
        if not onceki:
            # Grup en baştaysa (ör. yalnızca kanca sahnesi yeniden yazılıyor) öncesi
            # yoktur; bu durumda **sonraki** yazılmış sahneler bağlam olur. Yoksa tek
            # başına yazılan sahne diğerlerinden kopuk çıkardı: karakter, kıyafet ve
            # palet kayardı.
            grup_indexleri = {oge["index"] for oge in grup}
            onceki = [oge for oge in veri["adimlar"]
                      if oge["index"] not in grup_indexleri and oge.get("image_prompt")][:2]
        sonuc, kullanilan = None, {}
        for tur, deger in adim_yedekli_hesapli(
                veri, grup[0], baslik, ayar["ai"],
                lambda hizmet, hesap, kimlik: prompt_uretici(
                    ayar, hizmet, ai_anahtari(hizmet, kimlik), grup, veri, kullanilan,
                    onceki),
                prompt_kontrol):
            if tur == "sonuc":
                sonuc = deger
            else:
                yield deger
                if tur == "dur":
                    return dur_turu(veri)
        if not sonuc:
            continue
        for adim, kayit in zip(grup, sonuc):
            adim.update(kayit)
        # Yedek servis yazdıysa metne de işlenir: proje kaydı hangi yapay zekânın
        # prompt'ları yazdığını kendiliğinden söyler.
        servis_ek = (f" ({kullanilan.get('label')} ile)"
                     if kullanilan and kullanilan.get("provider") != ayar["ai"] else "")
        not_ekle(veri, f"Prompt yazıldı{servis_ek} · adım {grup[0]['index']}–{grup[-1]['index']}.")
        proje_yaz(veri)
        yield f"Prompt'lar hazır · adım {grup[0]['index']}–{grup[-1]['index']}."
    kalan = eksik_prompt_adimlari(veri)
    if kalan:
        yield hata_yaz(veri, kalan[0], "Prompt",
                        f"Adım {kalan[0]['index']} için prompt yazılamadı; "
                        "görsel/video üretimine geçilmedi.")
        return "hata"
    not_ekle(veri, "Bütün adımların prompt'ları hazır.")
    proje_yaz(veri)
    return "ok"


def prompt_uretici(ayar, hizmet, anahtar, grup, veri, kullanilan=None, onceki=None):
    """`prompt_grubu_uret` çağrısını tek adımlık bir üreteç gibi sun.

    Yedek servis zincirini `adim_yedekli_hesapli` yürütür; bu yüzden istek
    `yedek=False` ile **yalnızca kendi servisine** yapılır (geçişler tek yerde yönetilir).
    Yedek servis yazdıysa bunu durum satırı olarak üretir ki kullanıcı hangi yapay zekânın
    prompt'ları yazdığını görsün. `kullanilan` verilirse yanıtı yazan servis oraya yazılır.

    Anlatımın tamamı ve `onceki` (bir önceki gruptaki son sahneler) bağlam olarak
    geçirilir; eşleştirme uyarıları proje günlüğüne yazılır.
    """
    yield "yanıt bekleniyor…"
    kullanilan = {} if kullanilan is None else kullanilan
    uyarilar = []
    # Dönem/kıyafet filtresi yalnızca Tarih ve Birinci kişide çalışır; Default filtresizdir
    # (bkz. `kiyafet.filtre_acik`): analiz isteği hiç gitmez, prompt'lar süzülmez.
    if filtre_acik(ayar.get("sahne_stratejisi")):
        yield "Prompt öncesi dönem ve kıyafet kontrolü yapılıyor…"
        kiyafet = analiz_hazirla(
            veri, hizmet, anahtar, ayar["model"] if hizmet == ayar["ai"] else "",
            yedek=False, kullanilan=kullanilan)
        not_ekle(veri, "Kıyafet ön kontrolü · " + (kiyafet.get("donem") or "tarihsel değil")
                 + " · " + (kiyafet.get("kilit") or "dönem kıyafeti gerekmiyor")
                 + (" · mimari: " + kiyafet["mimari"] if kiyafet.get("mimari") else ""))
    else:
        kiyafet = {}
        not_ekle(veri, "Kıyafet ön kontrolü atlandı · Default strateji filtresizdir "
                       "(dönem/kıyafet analizi yalnızca Tarih ve Birinci kişide çalışır).")
    proje_yaz(veri)
    sonuc = prompt_grubu_uret(
        hizmet, anahtar, ayar["model"] if hizmet == ayar["ai"] else "", grup,
        LANGUAGES.get(veri["ayarlar"]["ses"]["dil"], veri["ayarlar"]["ses"]["dil"]),
        ayar["stil"], veri["ayarlar"]["gorsel"]["negatif"],
        genel=ayar.get("genel", ""), kullanilan=kullanilan, yedek=False,
        tam_metin=veri.get("metin", ""), onceki=onceki, uyar=uyarilar.append,
        strateji=ayar.get("sahne_stratejisi", VARSAYILAN_STRATEJI), kalite=True, kiyafet=kiyafet,
        # İlk sahne kullanıcının elindeyse hem isteğe bağlam olarak girer hem de o
        # karenin prompt'u birebir kullanıcının yazdığı olur.
        ilk_sahne=ilk_sahne_kaydi(ayar),
        # Prompt'un biçimi **görsel modeline** göre kurulur: kelime bütçesi ve negatif
        # prompt desteği modelden okunur (SDXL ~55 kelime + negatif, FLUX.2 uzun metin,
        # negatif yok).
        kelime_siniri=gorsel_cloudflare.prompt_kelime_siniri(
            veri["ayarlar"]["gorsel"]["model"], PROMPT_KELIME_SINIRI),
        negatif_destekli=gorsel_cloudflare.supports_negative(
            veri["ayarlar"]["gorsel"]["model"]),
        stil_ayri=gorsel_cloudflare.stil_butce_disi(veri["ayarlar"]["gorsel"]["model"]),
        # Karakter kadrosu: yapay zekâ görünen karakteri adıyla anar; kare onların
        # referans görselleriyle üretilir (bkz. `karakterler`).
        karakterler=ayar.get("karakterler") or None)
    for uyari in uyarilar:
        not_ekle(veri, "Prompt · UYARI: " + uyari)
        yield "UYARI: " + uyari
    if kullanilan and kullanilan.get("provider") != ayar["ai"]:
        not_ = (f"Yedek servis devrede: {kullanilan.get('label')} · "
                f"model: {kullanilan.get('model')}.")
        not_ekle(veri, f"Prompt · {not_}")
        yield not_
    yield sonuc
