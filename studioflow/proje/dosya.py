"""`proje.txt`: tek gerçek kayıt — yazma (`log_metni`) ve okuma (`proje_oku`)."""
import os
import json
import re
import threading
import time
from datetime import datetime

from studioflow.altyazi.gorunum import altyazi_boyut, altyazi_seviye
from studioflow.ayarlar.bicimler import (
    CIKTI_BICIMLERI, DURUMLAR, DURUM_ADI, ETIKET_IPUCU, VARSAYILAN_BICIM,
    bicim_kunye)
from studioflow.cekirdek.hatalar import gpu_yok_mu, hata_etiketle
from studioflow.cekirdek.metin import (
    evet as _evet, ilk_satir as _ilk_satir, numara as _numara, sayi as _sayi,
    tek_satir as _tek_satir, tek_satir_tam as _tek_satir_tam, temiz as _temiz)
from studioflow.proje.ayar_normalize import ayarlari_normalize
from studioflow.proje.depo import klasoru_hazirla, proje_klasoru, slug
from studioflow.proje.karakterler import normalize as normalize_karakterler
from studioflow.proje.sabitler import (
    ADIM_DENEMELERI, ADIM_SANIYE, DENEME_ADI, DENEME_ISLEM, DOSYA_ADI,
    GUNLUK_SINIR, MUZIK_VARSAYILAN_DUCKING, NASIL_OKUNUR, PROJE_DENEMELERI,
    YENIDEN_SINIR)


def not_ekle(veri, mesaj):
    """Proje günlüğüne zaman damgalı satır ekle (en yenisi sonda)."""
    gunluk = veri.setdefault("gunluk", [])
    gunluk.append(f"{datetime.now():%Y-%m-%d %H:%M:%S} · {mesaj}")
    del gunluk[:-GUNLUK_SINIR]


def hata_notu(hata):
    mesaj = _ilk_satir(hata, 400)
    etiket = hata_etiketle(mesaj)
    if gpu_yok_mu(mesaj):
        # Genel ipucu ("Üç otomatik denemede de geçmedi…") burada yanlıştı: hak harcanmaz.
        return (f"[{etiket}] {mesaj} — deneme hakkı harcanmaz; grup durur, "
                "**Kaldığı yerden devam et** ile sürdür.")
    return f"[{etiket}] {mesaj} — {ETIKET_IPUCU[etiket]}"


def denemeleri_coz(deger, islemler):
    """`Deneme` satırını (`görsel 1/3 · video 2/3`) `{işlem: sayı}` sözlüğüne çevir."""
    sonuc = {islem: 0 for islem in islemler}
    for parca in re.split(r"\s*[·,]\s*", str(deger or "")):
        ad, _, sayi = parca.strip().partition(" ")
        islem = DENEME_ISLEM.get(ad.strip())
        if islem in sonuc and "/" in sayi:
            sonuc[islem] = max(0, _sayi(sayi.split("/")[0].strip(), 0))
    return sonuc


def deneme_satiri(deneme, islemler):
    """Sayaçları tek satıra çevir; hiç deneme harcanmamışsa boş metin döner."""
    parcalar = [f"{DENEME_ADI[islem]} {int(deneme.get(islem) or 0)}/{YENIDEN_SINIR}"
                for islem in islemler if int(deneme.get(islem) or 0) > 0]
    return " · ".join(parcalar)


def _ayar_satirlari(ayar):
    """AYARLAR bölümü: `bölüm.alan : değer` biçiminde okunur ve düzenlenebilir satırlar."""
    ses, gorsel, video, altyazi = ayar["ses"], ayar["gorsel"], ayar["video"], ayar["altyazi"]
    kural = altyazi["ayar"]
    # Seviye yazılmamış bir durum varsa (eski dosya) varsayılana düşülür.
    seviye = altyazi_seviye(altyazi.get("seviye"))
    satirlar = [
        "# aşağıdaki satırlar hem okunur hem düzenlenebilir;",
        "# değiştirdiğin ayar yalnızca henüz üretilmemiş adımları etkiler.",
        f"ses.provider : {ses['provider']}",
        f"ses.dil : {ses['dil']}",
        f"ses.edge_ses : {ses['edge_ses']}",
        f"ses.hiz : {ses['hiz']}",
        f"ses.ton : {ses['ton']}",
        "# ses.seviye · seslendirmenin videodaki seviyesi (%, 25–400; 100 = dosyanın kendisi).",
        f"ses.seviye : {ses.get('seviye', 100)}",
        f"ses.gemini_model : {ses['gemini_model']}",
        f"ses.gemini_ses : {ses['gemini_ses']}",
        f"ses.stil : {ses['stil']}",
        f"ses.ref : {ses['ref']}",
        f"ses.exag : {ses['exag']}",
        f"ses.cfg : {ses['cfg']}",
        f"altyazi.acik : {'açık' if altyazi['acik'] else 'kapalı'}",
        f"altyazi.preset : {altyazi['preset']}",
        "# altyazi.font · videoya gömülürken kullanılan yazı tipi (libass bulamazsa Arial).",
        f"altyazi.font : {altyazi['font']}",
        "# altyazi.renk · yazı rengi #RRGGBB; altyazi.kalin · açık/kapalı.",
        f"altyazi.renk : {altyazi['renk']}",
        f"altyazi.kalin : {'açık' if altyazi['kalin'] else 'kapalı'}",
        "# altyazi.seviye · yazının alttan yüksekliği (tuval yüksekliğinin %'si, 0–40).",
        f"altyazi.seviye : {seviye:g}",
        "# altyazi.boyut · yazı yüksekliği (tuval yüksekliğinin %'si, 2–8; varsayılan 4.5).",
        f"altyazi.boyut : {altyazi_boyut(altyazi.get('boyut')):g}",
        "# altyazi.golge · yazının arkasındaki koyu gölge · açık/kapalı.",
        f"altyazi.golge : {'kapalı' if altyazi.get('golge') is False else 'açık'}",
        f"altyazi.line_chars : {kural.get('line_chars', 42)}",
        f"altyazi.max_lines : {kural.get('max_lines', 2)}",
        f"altyazi.min_seconds : {kural.get('min_seconds', 1.2)}",
        f"altyazi.max_seconds : {kural.get('max_seconds', 7.0)}",
        f"gorsel.provider : {gorsel['provider']}",
        f"gorsel.model : {gorsel['model']}",
        f"gorsel.width : {gorsel['width']}",
        f"gorsel.height : {gorsel['height']}",
        f"gorsel.steps : {gorsel['steps']}",
        f"gorsel.guidance : {gorsel['guidance']}",
        # Negatif prompt ve görsel stil tek satırlık alanlardır: çok satırlı bir değer
        # `anahtar : değer` ayrıştırmasını bozardı, bu yüzden tek satıra indirilir —
        # ama **kısaltılmaz** (uzun negatif listeleri olduğu gibi korunur).
        f"gorsel.negatif : {_tek_satir_tam(gorsel['negatif'])}",
        # Görsel denetimi: her kare sahnenin `Kontrol` listesine göre bir görsel dil
        # modeliyle denetlenir; geçmezse düzeltilmiş prompt'la yeniden üretilir.
        "# gorsel.denetim · açık/kapalı · gorsel.denetim_deneme · kare başına toplam "
        "üretim hakkı (1–5).",
        f"gorsel.denetim : {'açık' if gorsel.get('denetim', True) else 'kapalı'}",
        f"gorsel.denetim_deneme : {gorsel.get('denetim_deneme', 3)}",
        "# gorsel.yazi_denetimi · açık/kapalı · karede yazı (imza, mühür, yazıt) varsa kare "
        "yeniden üretilir; çıkmazsa videosu kilitlenir.",
        f"gorsel.yazi_denetimi : {'açık' if gorsel.get('yazi_denetimi', True) else 'kapalı'}",
        # Çıktı biçimi: hedef platform + tuval. Görsel oranını, altyazı önerisini ve
        # birleştirme tuvalini birlikte belirler; değişirse proje.mp4 yeniden birleşir.
        "# video.bicim · hedef platform ve tuval ölçüsü:",
        *[f"#   {anahtar} = {bilgi['ad']}" for anahtar, bilgi in CIKTI_BICIMLERI.items()],
        f"video.bicim : {video['bicim']}",
        f"video.adim : {video['adim']}",
        "# video.adim_saniye · bir sahnenin alabileceği en uzun süre (üst sınır): 5–8 sn.",
        "#   Sahne süreleri anlatımın içeriğine göre değişir; bu değer yalnızca sınırdır.",
        f"video.adim_saniye : {video['adim_saniye']:g}",
        f"video.ai : {video['ai']}",
        f"video.model : {video['model']}",
        f"video.sahne_stratejisi : {video.get('sahne_stratejisi', 'tarih')}",
        f"video.stil : {_tek_satir_tam(video['stil'])}",
        # İlk sahne (videonun kancası): kullanıcının yazdığı **içerik** ve negatif.
        # Boşsa 1. sahne tamamen yapay zekânın; doluysa içerik isteğe bağlam olarak
        # girer, kare prompt'unu yine yapay zekâ yazar (görsel stil `video.stil`tir).
        f"video.ilk_prompt : {_tek_satir_tam(video.get('ilk_prompt'))}",
        f"video.ilk_negatif : {_tek_satir_tam(video.get('ilk_negatif'))}",
        f"video.space : {video['space']}",
    ]
    return satirlar


def _adim_basligi(adim, toplam):
    """`ADIM 3/8 · 10,0–15,0 sn · TAMAM · 2026-09-19 20:31:07`"""
    return (f"ADIM {adim['index']}/{toplam} · {_numara(adim['start'])}–{_numara(adim['end'])} sn"
            f" · {adim.get('durum') or 'BEKLİYOR'} · {adim.get('bitti') or '-'}")


def _adim_blogu(adim):
    # Anlatım ve prompt alanları **kısaltılmadan** yazılır: bu dosya projenin tek
    # kaydıdır, kaldığı yerden devam eden proje prompt'ları buradan okur.
    blok = [
        f"Anlatım      : {_tek_satir_tam(adim.get('text'))}",
        f"Görsel (+)   : {_tek_satir_tam(adim.get('image_prompt')) or '-'}",
        f"Görsel (−)   : {_tek_satir_tam(adim.get('negative_prompt')) or '-'}",
        f"Video prompt : {_tek_satir_tam(adim.get('video_prompt')) or '-'}",
        f"Görsel dosya : {adim.get('gorsel') or '-'}",
        f"Video dosya  : {adim.get('video') or '-'}",
        f"Hata         : {_tek_satir(adim.get('hata')) or '-'}",
    ]
    # Görsel denetimi: `Kontrol` karede gözle doğrulanacak öğelerdir (prompt'u yazan
    # yapay zekâ yazar, elle de düzenlenebilir; `;` ile ayrılır), `Denetim` görsel
    # hakemin son kararıdır. İkisi de yalnızca doluysa yazılır: eski projelerin
    # dosyası birebir aynı kalır.
    if _tek_satir_tam(adim.get("kontrol")):
        blok.insert(4, f"Kontrol      : {_tek_satir_tam(adim.get('kontrol'))}")
    if _tek_satir_tam(adim.get("denetim")):
        blok.append(f"Denetim      : {_tek_satir_tam(adim.get('denetim'))}")
    # Sahnede görünen karakterler (kadro varsa): kare bu karakterlerin referans
    # görselleriyle üretilir. Kadrosuz projede satır hiç yazılmaz.
    if adim.get("karakterler"):
        blok.append(f"Karakterler  : {', '.join(adim['karakterler'])}")
    if "sahne_plani" in adim:
        blok.append("Sahne planı  : " + json.dumps(adim["sahne_plani"], ensure_ascii=False))
    for anahtar, etiket in (("kalite_durumu", "Kalite"), ("hareket_izi", "Hareket izi"),
                            ("sureklilik_kare", "Süreklilik karesi"),
                            ("sureklilik_izi", "Süreklilik izi")):
        if adim.get(anahtar):
            blok.append(f"{etiket} : {_tek_satir_tam(adim[anahtar])}")
    # Deneme satırı yalnızca hak harcanmışsa yazılır; her adıma boş satır eklenmez.
    deneme = deneme_satiri(adim.get("deneme") or {}, ADIM_DENEMELERI)
    if deneme:
        blok.append(f"Deneme       : {deneme}")
    return blok


def gorsel_kaynak_bicim(veri):
    """Projenin ayarlarındaki hedef biçim (yoksa varsayılan)."""
    return ((veri.get("ayarlar") or {}).get("video") or {}).get("bicim") or VARSAYILAN_BICIM


def log_metni(veri):
    """Projenin metnini (`proje.txt`) üret."""
    adimlar = veri["adimlar"]
    tamam = sum(1 for adim in adimlar if adim.get("durum") == "TAMAM")
    sure = float(veri["ses"].get("sure") or 0)
    satirlar = [
        "StudioFlow · proje dosyası",
        "=" * 72,
        f"Proje      : {veri['ad']}",
        f"Klasör     : {proje_klasoru(veri['slug'])}",
        f"Oluşturulma: {veri['olusturuldu']}",
        f"Güncelleme : {veri['guncellendi']}",
        f"Durum      : {DURUM_ADI.get(veri['durum'], veri['durum'])} · "
        f"{tamam}/{len(adimlar)} adım tamam",
        # Otomatik yeniden başlatma sayaçları: elle `0/3` yapmak hakkı yeniler.
        f"Deneme     : {deneme_satiri(veri.get('deneme') or {}, PROJE_DENEMELERI) or '-'}",
        "",
        "NASIL OKUNUR",
        "-" * 72,
        *NASIL_OKUNUR,
        "",
        "AYARLAR",
        "-" * 72,
        *_ayar_satirlari(veri["ayarlar"]),
        "",
        "SESLENDİRME",
        "-" * 72,
        f"Durum : {veri['ses'].get('durum') or 'BEKLİYOR'}",
        f"Dosya : {veri['ses'].get('dosya') or '-'}",
        f"Süre  : {f'{sure:.2f} saniye' if sure else '-'}",
        f"Bitti : {veri['ses'].get('bitti') or '-'}",
        "",
        "ANLATIM METNİ",
        "-" * 72,
        "<<<",
        veri.get("metin") or "",
        ">>>",
        "",
        "GENEL PROMPT (bütün adımlar bu çerçeveye uydurulur)",
        "-" * 72,
        "<<<",
        (veri.get("ayarlar", {}).get("video", {}).get("genel") or "").strip(),
        ">>>",
        "",
        "ADIMLAR (süreler içeriğe göre değişir; başlıkta başlangıç–bitiş yazar)",
        "-" * 72,
    ]
    karakterler = (veri.get("ayarlar", {}).get("video", {}).get("karakterler") or [])
    if karakterler:
        # Kadro yalnızca varsa yazılır: karaktersiz projelerin dosyası birebir aynı kalır.
        yer = satirlar.index("ADIMLAR (süreler içeriğe göre değişir; başlıkta başlangıç–bitiş yazar)")
        satirlar[yer:yer] = ["KARAKTERLER (her karakterin referans görseli projenin "
                             "karakterler/ klasöründedir)", "-" * 72, "<<<",
                             json.dumps(karakterler, ensure_ascii=False, indent=1), ">>>", ""]
    if veri.get("kiyafet_analizi"):
        yer = satirlar.index("ADIMLAR (süreler içeriğe göre değişir; başlıkta başlangıç–bitiş yazar)")
        satirlar[yer:yer] = ["DÖNEM VE KIYAFET ÖN KONTROLÜ", "-" * 72, "<<<",
            json.dumps(veri["kiyafet_analizi"], ensure_ascii=False), ">>>", ""]
    if not adimlar:
        satirlar.append("(henüz adım yok · önce seslendirme üretilmeli)")
    for adim in adimlar:
        satirlar.append(_adim_basligi(adim, len(adimlar)))
        satirlar += _adim_blogu(adim)
        satirlar.append("")
    satirlar += [
        "VİDEO",
        "-" * 72,
        # Görsel onayı: akış önce **bütün kareleri** üretir ve burada durur; videolar
        # ancak onay verilince üretilir (bkz. `akis.akis_calistir`). Satır yoksa (eski
        # proje) onay beklenir; arayüzdeki **Görselleri onayla** düğmesi VERİLDİ yapar.
        f"Görsel onayı: {veri.get('gorsel_onay') or 'BEKLİYOR'}",
        # Videoları üreten servis (huggingface · agnes · ltx): görsel onayındaki düğme
        # yazar, **Kaldığı yerden devam** bunu kullanır.
        f"Video servisi: {veri.get('video_servisi') or 'huggingface'}",
        f"Birleştirme : {veri.get('birlestirme') or 'BEKLİYOR'}",
        f"Biçim       : {veri.get('birlestirme_bicim') or bicim_kunye(gorsel_kaynak_bicim(veri))}",
        f"Dosya       : {veri.get('birlestirme_dosya') or '-'}",
        f"Bitti       : {veri.get('birlestirme_bitti') or '-'}",
        # Ham video: sesi ve altyazısı olmayan, dillerin üzerine eklendiği temel dosya.
        f"Ham video      : {veri.get('ham_video') or '-'}",
        f"Ekli dil       : {veri.get('ekli_dil') or '-'}",
        # Videoya eklenen **kayıtlı** dublaj ve altyazının adı: paneldeki listeler
        # bu iki satırdan hangi kaydın videoda olduğunu okur (bkz. `dublaj`, `altyazilar`).
        f"Ekli dublaj    : {veri.get('ekli_dublaj') or '-'}",
        f"Ekli altyazı   : {veri.get('ekli_altyazi') or '-'}",
        # Kanca izi: 1. sahnenin prompt'u **hangi** ilk sahne metniyle yazıldı.
        # Metin değişmediyse prompt yeniden yazılmaz (bkz. `akis_kanca.ilk_sahneyi_tazele`);
        # böylece beğenilen kanca prompt'u her devamda değişmez.
        f"Kanca izi      : {veri.get('kanca_izi') or '-'}",
        f"Ses ekleme     : {veri.get('ses_ekleme') or 'BEKLİYOR'}",
        f"Ses bitti      : {veri.get('ses_ekleme_bitti') or '-'}",
        f"Altyazı ekleme : {veri.get('altyazi_ekleme') or 'BEKLİYOR'}",
        f"Altyazı bitti  : {veri.get('altyazi_ekleme_bitti') or '-'}",
        # Müzik katmanı: listeden işaretlenip videoya eklenen müziklerin sırası.
        f"Müzik          : {veri.get('muzik_ekleme') or 'BEKLİYOR'}",
        f"Müzik bitti    : {veri.get('muzik_ekleme_bitti') or '-'}",
        f"Müzikler       : {', '.join(veri.get('muzikler') or []) or '-'}",
        f"Müzik tekrar   : {'evet' if veri.get('muzik_tekrarla') else 'hayır'}",
        # Ducking: anlatım konuşurken müziğin otomatik kısılması. Satır yazmayan eski
        # projelerde varsayılan **açıktır** (bkz. MUZIK_VARSAYILAN_DUCKING).
        f"Müzik ducking  : {'evet' if veri.get('muzik_ducking', True) else 'hayır'}",
        "",
        "GÜNLÜK (en yenisi sonda)",
        "-" * 72,
    ]
    satirlar += veri.get("gunluk") or ["(kayıt yok)"]
    if veri.get("son_not"):
        satirlar += ["", "SON NOT", "-" * 72, veri["son_not"]]
    return "\n".join(satirlar).rstrip() + "\n"


# Çoklu üretimde birden çok iş parçacığı aynı projeyi yazar: geçici dosya ortak olduğu
# için yazımlar sıraya alınır.
_YAZIM_KILIDI = threading.RLock()


# Windows, başka bir program (antivirüs, dosyayı okuyan editör) proje.txt'yi o an açık
# tutuyorsa yerine koymayı "Erişim engellendi" ile reddeder. 12.10.2026: bu hata üretim
# hatası sanıldı ve hazır klip yeniden üretildi (kota boşa gitti). Kısa aralıklarla
# yeniden denenir; ~3 sn sonra hâlâ olmuyorsa hata yükselir.
YAZIM_BEKLEMELERI = (0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0)


def _yerine_koy(gecici, hedef):
    for bekleme in (*YAZIM_BEKLEMELERI, None):
        try:
            os.replace(gecici, hedef)
            return
        except PermissionError:
            if bekleme is None:
                raise
            time.sleep(bekleme)


def proje_yaz(veri):
    """Metni diske yaz. Yarım dosya kalmasın diye önce geçiciye, sonra yerine yazılır."""
    klasoru_hazirla()
    klasor = proje_klasoru(veri["slug"])
    klasor.mkdir(parents=True, exist_ok=True)
    with _YAZIM_KILIDI:
        veri["guncellendi"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        for deneme in range(3):
            try:
                metin = log_metni(veri)
                break
            except RuntimeError:
                # Paralel bir grup sözlüğe tam o an alan ekledi: yeniden okunur.
                if deneme == 2:
                    raise
        gecici = klasor / (DOSYA_ADI + ".gecici")
        gecici.write_text(metin, encoding="utf-8")
        _yerine_koy(gecici, klasor / DOSYA_ADI)
    return klasor


def _bolumler(satirlar):
    """Metni başlıklı bölümlere ayır; başlık, ardından yalnızca tire gelen satırdır.

    Başlığın altındaki çizgi bölüm içeriğine katılmaz.
    """
    bolumler, mevcut, cizgiyi_atla = {"": []}, "", False
    for sira, satir in enumerate(satirlar):
        if cizgiyi_atla:
            cizgiyi_atla = False
            continue
        sonraki = satirlar[sira + 1] if sira + 1 < len(satirlar) else ""
        baslik = satir.strip()
        if baslik and ":" not in baslik and not _cizgi_mi(baslik) and _cizgi_mi(sonraki):
            mevcut = baslik
            bolumler[mevcut] = []
            cizgiyi_atla = True
            continue
        bolumler[mevcut].append(satir)
    return bolumler


def _cizgi_mi(satir):
    """Satır yalnızca tirelerden mi oluşuyor (bölüm başlığı çizgisi)?"""
    satir = satir.strip()
    return bool(satir) and set(satir) == {"-"}


def _bolum(bolumler, onek):
    for ad, satirlar in bolumler.items():
        if ad.startswith(onek):
            return satirlar
    return []


def _alanlar(satirlar):
    """`anahtar : değer` satırlarını sözlüğe çevir (ilk iki noktadan bölünür)."""
    alanlar = {}
    for satir in satirlar:
        anahtar, ayirac, deger = satir.partition(":")
        if ayirac:
            anahtar = anahtar.strip()
            if anahtar and not anahtar.startswith("#"):
                alanlar[anahtar] = deger.strip()
    return alanlar


def _ayarlari_coz(satirlar):
    """`ses.provider : edge` satırlarını iç içe sözlüğe çevir."""
    ayarlar = {}
    for anahtar, deger in _alanlar(satirlar).items():
        if "." not in anahtar:
            continue
        bolum, _, alan = anahtar.partition(".")
        ayarlar.setdefault(bolum, {})[alan] = deger
    return ayarlar


def _metni_coz(satirlar):
    """`<<<` ve `>>>` arasındaki anlatım metnini al (son `>>>` kapanıştır)."""
    baslar = [sira for sira, satir in enumerate(satirlar) if satir.strip() == "<<<"]
    bitisler = [sira for sira, satir in enumerate(satirlar) if satir.strip() == ">>>"]
    if not baslar or not bitisler:
        return ""
    return "\n".join(satirlar[baslar[0] + 1:bitisler[-1]]).strip()


def _adim_basligini_coz(satir, sira, adim_saniye=ADIM_SANIYE):
    """`ADIM 3/8 · 10,0–15,0 sn · TAMAM · <saat>` satırını çöz.

    Zaman aralığı satırın kendisinde yazılıdır; yazılmamışsa (bozuk ya da eski satır)
    projenin kendi adım süresinden türetilir.
    """
    dilimler = [parca.strip() for parca in satir.split(" · ")]
    adim = {"index": sira + 1, "start": 0.0, "end": adim_saniye, "durum": "BEKLİYOR",
            "bitti": "", "alanlar": {}}
    baslik = dilimler[0].split() if dilimler else []
    if len(baslik) > 1 and "/" in baslik[1]:
        try:
            adim["index"] = int(baslik[1].split("/")[0])
        except ValueError:
            pass
    olcum = re.findall(r"[0-9]+[.,][0-9]+", dilimler[1] if len(dilimler) > 1 else "")
    if len(olcum) >= 2:
        adim["start"] = float(olcum[0].replace(",", "."))
        adim["end"] = float(olcum[1].replace(",", "."))
    else:
        adim["start"] = (adim["index"] - 1) * adim_saniye
        adim["end"] = adim["index"] * adim_saniye
    if len(dilimler) > 2 and dilimler[2] in DURUMLAR:
        adim["durum"] = dilimler[2]
    if len(dilimler) > 3:
        adim["bitti"] = "" if dilimler[3] == "-" else dilimler[3]
    return adim


def _adim_kur(baslik, duz_alanlar):
    """Adım başlığını ve `anahtar : değer` satırlarını tek sözlüğe çevir."""
    adim = {anahtar: deger for anahtar, deger in baslik.items() if anahtar != "alanlar"}
    adim["text"] = ""
    adim["image_prompt"] = ""
    adim["negative_prompt"] = ""
    adim["video_prompt"] = ""
    adim["gorsel"] = ""
    adim["video"] = ""
    adim["hata"] = ""
    # `kontrol` / `denetim` yalnızca satırı varsa eklenir (okuyan kod `.get` kullanır).
    for anahtar, deger in duz_alanlar.items():
        if anahtar.startswith("Anlatım"):
            adim["text"] = _temiz(deger)
        elif anahtar.startswith("Görsel ("):
            if "+" in anahtar:
                adim["image_prompt"] = _temiz(deger)
            else:
                adim["negative_prompt"] = _temiz(deger)
        elif anahtar.startswith("Video prompt"):
            adim["video_prompt"] = _temiz(deger)
        elif anahtar.startswith("Görsel dosya"):
            adim["gorsel"] = _temiz(deger)
        elif anahtar.startswith("Video dosya"):
            adim["video"] = _temiz(deger)
        elif anahtar.startswith("Hata"):
            adim["hata"] = _temiz(deger)
        elif anahtar.startswith("Kontrol"):
            adim["kontrol"] = _temiz(deger)
        elif anahtar.startswith("Denetim"):
            adim["denetim"] = _temiz(deger)
        elif anahtar == "Sahne planı":
            try:
                plan = json.loads(deger)
            except (ValueError, TypeError):
                plan = {}
            adim["sahne_plani"] = plan if isinstance(plan, dict) else {}
        elif anahtar == "Karakterler":
            adim["karakterler"] = [ad.strip() for ad in deger.split(",")
                                   if ad.strip() and ad.strip() != "-"]
        elif anahtar == "Kalite":
            adim["kalite_durumu"] = _temiz(deger)
        elif anahtar == "Hareket izi":
            adim["hareket_izi"] = _temiz(deger)
        elif anahtar == "Süreklilik karesi":
            adim["sureklilik_kare"] = _temiz(deger)
        elif anahtar == "Süreklilik izi":
            adim["sureklilik_izi"] = _temiz(deger)
    # Otomatik yeniden başlatma sayaçları (yoksa hepsi 0): elle `0/3` yapılabilir.
    adim["deneme"] = denemeleri_coz(duz_alanlar.get("Deneme", ""), ADIM_DENEMELERI)
    return adim


def _adimlari_coz(satirlar, adim_saniye=ADIM_SANIYE):
    basliklar = []
    for satir in satirlar:
        if satir.startswith("ADIM "):
            basliklar.append((_adim_basligini_coz(satir, len(basliklar), adim_saniye), {}))
        elif basliklar:
            anahtar, ayirac, deger = satir.partition(":")
            if ayirac:
                basliklar[-1][1][anahtar.strip()] = deger.strip()
    return [_adim_kur(baslik, alanlar) for baslik, alanlar in basliklar]


def _kiyafet_coz(metin):
    try:
        veri = json.loads(metin)
    except (ValueError, TypeError):
        return {}
    return veri if isinstance(veri, dict) else {}


def proje_oku(klasor):
    """`proje.txt`'i çöz. Dosya yok ya da biçim bozuksa None döndür."""
    try:
        satirlar = (klasor / DOSYA_ADI).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not satirlar or "StudioFlow" not in satirlar[0]:
        return None
    bolumler = _bolumler(satirlar)
    bas = _alanlar(bolumler.get("", []))
    if not bas.get("Proje"):
        return None
    ses = _alanlar(_bolum(bolumler, "SESLENDİRME"))
    video = _alanlar(_bolum(bolumler, "VİDEO"))
    sure = _sayi(str(ses.get("Süre", "")).split()[0].replace(",", "."), 0.0, float)
    ayarlar = ayarlari_normalize(_ayarlari_coz(_bolum(bolumler, "AYARLAR")))
    # Genel video prompt'u ayrı, çok satırlı bir bölümde tutulur: AYARLAR satırları
    # tek satır olduğu için uzun bir brief oraya sığmaz.
    ayarlar["video"]["genel"] = _metni_coz(_bolum(bolumler, "GENEL PROMPT"))
    ayarlar["video"]["karakterler"] = normalize_karakterler(
        _metni_coz(_bolum(bolumler, "KARAKTERLER")))
    return {
        "ad": bas.get("Proje", ""),
        "slug": slug(bas.get("Proje", "")),
        "olusturuldu": bas.get("Oluşturulma", ""),
        "guncellendi": bas.get("Güncelleme", ""),
        "durum": "bekliyor",
        "deneme": denemeleri_coz(bas.get("Deneme", ""), PROJE_DENEMELERI),
        **({"kiyafet_analizi": _kiyafet_coz(_metni_coz(
            _bolum(bolumler, "DÖNEM VE KIYAFET")))}
           if _bolum(bolumler, "DÖNEM VE KIYAFET") else {}),
        "metin": _metni_coz(_bolum(bolumler, "ANLATIM")),
        "ayarlar": ayarlar,
        "ses": {"durum": (ses.get("Durum") or "BEKLİYOR").upper()
                if (ses.get("Durum") or "").upper() in DURUMLAR else "BEKLİYOR",
                "dosya": _temiz(ses.get("Dosya")),
                "sure": sure,
                "bitti": _temiz(ses.get("Bitti"))},
        "adimlar": _adimlari_coz(_bolum(bolumler, "ADIMLAR"),
                                 ayarlar["video"]["adim_saniye"]),
        # Görsel onayı: yalnızca VERİLDİ onay sayılır; satır yoksa ya da bozuksa
        # akış görselleri gösterip onay bekler (güvenli taraf).
        "gorsel_onay": ("VERİLDİ" if (video.get("Görsel onayı") or "").strip().upper()
                        in ("VERİLDİ", "VERILDI") else "BEKLİYOR"),
        # Satır yoksa (eski proje) ya da tanınmıyorsa Hugging Face (Wan2.2).
        "video_servisi": ((video.get("Video servisi") or "").strip().lower()
                          if (video.get("Video servisi") or "").strip().lower()
                          in ("huggingface", "agnes", "ltx") else "huggingface"),
        "birlestirme": (video.get("Birleştirme") or "BEKLİYOR").upper(),
        # Biçim satırı birleştirilen dosyanın tuvalini yazar; hedef biçimden farklıysa
        # `proje.mp4` yeniden birleştirilir (bkz. `birlestirme_gerekli`).
        "birlestirme_bicim": _temiz(video.get("Biçim")),
        "birlestirme_dosya": _temiz(video.get("Dosya")),
        "birlestirme_bitti": _temiz(video.get("Bitti")),
        # Ham video ve videoya ekli dil: çok dilli ses panelinin kalıcı kaydı.
        "ham_video": _temiz(video.get("Ham video")),
        "ekli_dil": _temiz(video.get("Ekli dil")),
        # Kayıtlı dublaj/altyazı adları: satır yoksa (eski proje) boş kalır ve
        # videoda duyulan ses `Ekli dil`den bulunur.
        "ekli_dublaj": _temiz(video.get("Ekli dublaj")),
        "ekli_altyazi": _temiz(video.get("Ekli altyazı")),
        # Kanca izi: satır yoksa (eski proje) boş kalır; ilk sahne metni de boşsa
        # ikisi eşleşir ve hiçbir şey yeniden yazılmaz.
        "kanca_izi": _temiz(video.get("Kanca izi")),
        "ses_ekleme": (video.get("Ses ekleme") or "BEKLİYOR").upper()
        if (video.get("Ses ekleme") or "").upper() in DURUMLAR else "BEKLİYOR",
        "ses_ekleme_bitti": _temiz(video.get("Ses bitti")),
        "altyazi_ekleme": (video.get("Altyazı ekleme") or "BEKLİYOR").upper()
        if (video.get("Altyazı ekleme") or "").upper() in DURUMLAR else "BEKLİYOR",
        "altyazi_ekleme_bitti": _temiz(video.get("Altyazı bitti")),
        # Müzik katmanı: videoya eklenen müziklerin **sırası** burada durur; video
        # yeniden kurulduğunda karışım bu sırayla yeniden uygulanır.
        "muzik_ekleme": (video.get("Müzik") or "BEKLİYOR").upper()
        if (video.get("Müzik") or "").upper() in DURUMLAR else "BEKLİYOR",
        "muzik_ekleme_bitti": _temiz(video.get("Müzik bitti")),
        "muzikler": [parca.strip() for parca in (video.get("Müzikler") or "").split(",")
                     if parca.strip() and parca.strip() != "-"],
        "muzik_tekrarla": (video.get("Müzik tekrar") or "").strip().lower() in ("evet", "1",
                                                                                "true"),
        # Satır yoksa (eski proje) ducking açık sayılır.
        "muzik_ducking": _evet(video.get("Müzik ducking"), MUZIK_VARSAYILAN_DUCKING),
        # Eski sürümler başlık çizgisini içeriğe katıp her kayıtta bir tane daha
        # yazıyordu; birikmiş çizgiler burada ayıklanır, dosya ilk kayıtta düzelir.
        "gunluk": [satir for satir in _bolum(bolumler, "GÜNLÜK")
                   if satir.strip() and not _cizgi_mi(satir)],
        "son_not": "\n".join(satir for satir in _bolum(bolumler, "SON NOT")
                             if not _cizgi_mi(satir)).strip(),
    }
