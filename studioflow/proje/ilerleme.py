"""Arayüz için ilerleme çubuğu ve özet HTML'leri; işlev dönüş paketleri."""
import html
import math
import re

from studioflow.ayarlar import api_hesaplari
from studioflow.cekirdek.metin import numara as _numara
from studioflow.proje.depo import (
    adim_suresi, adim_tamam, proje_adim_saniyesi, proje_dosyalari,
    proje_gorselleri, proje_klasoru)
from studioflow.proje.dosya import deneme_satiri, log_metni
from studioflow.proje.sabitler import (
    ADIM_DENEMELERI, DENEME_ADI, PROJE_DENEMELERI, YENIDEN_SINIR)
from studioflow.saglayicilar.hesap_havuzu import ELENEN, KAYITSIZ, SES_HIZMET, hesap_listesi
from studioflow.saglayicilar.kota_listesi import VARSAYILAN as KOTA_LISTESI, saat_metni

# İlerleme paneli tek bir kart gibi görünür: büyük başlık, kalın çubuk, sayı çipleri
# ve **hata kutusu**. Yazı boyutları bilinçli olarak büyüktür: panel ekranın en çok
# bakılan yeridir, uzaktan okunabilmelidir.
ILERLEME_STIL = """<style>
.sf-il { font-size: 14px; line-height: 1.55; text-align: left;
  background: var(--block-background-fill, rgba(127,127,127,.05));
  border: 1px solid var(--border-color-primary, rgba(127,127,127,.28));
  border-radius: 12px; padding: 14px 16px; }
.sf-il-baslik { font-size: 17px; font-weight: 700; }
.sf-il-ust { display: flex; align-items: center; justify-content: space-between;
  gap: 10px; flex-wrap: wrap; }
.sf-il-rozet { font-size: 14px; font-weight: 600; padding: 2px 12px; border-radius: 999px;
  background: rgba(128,128,128,.16); }
.sf-il-cubuk { display: flex; gap: 3px; height: 30px; margin: 12px 0 10px; }
.sf-il-parca { flex: 1 1 0; min-width: 0; border-radius: 6px;
  background: rgba(128,128,128,.22); }
.sf-il-cubuk-yogun { flex-wrap: wrap; height: auto; }
.sf-il-cubuk-yogun .sf-il-parca { flex: 0 0 calc((100% - 29 * 3px) / 30); height: 14px;
  border-radius: 4px; }
.sf-il-tamam { background: linear-gradient(180deg, #34d399, #16a34a); }
.sf-il-yarim { background: linear-gradient(180deg, #fbbf24, #d97706); }
.sf-il-hata { background: linear-gradient(180deg, #f87171, #dc2626); }
.sf-il-sirada { box-shadow: 0 0 0 3px #2563eb, 0 0 10px rgba(37,99,235,.55); }
.sf-il-sayilar { display: flex; flex-wrap: wrap; gap: 6px; margin: 4px 0 2px; }
.sf-il-cip { font-size: 13px; font-weight: 600; padding: 2px 10px; border-radius: 999px;
  background: rgba(128,128,128,.16); }
.sf-il-cip-tamam { background: rgba(34,197,94,.18); }
.sf-il-cip-yarim { background: rgba(245,158,11,.20); }
.sf-il-cip-hata { background: rgba(239,68,68,.20); }
.sf-il-cip-sira { background: rgba(37,99,235,.18); }
.sf-il-not { color: var(--body-text-color-subdued, #6b7280); font-size: 13px;
  margin-top: 4px; }
.sf-il-sayi { font-weight: 700; font-size: 16px; }
.sf-il-uyari { color: #b45309; }
.sf-il-alarm { color: #b91c1c; font-weight: 600; }
.sf-il-etiket { display: inline-block; border-radius: 999px; padding: 1px 9px;
  font-size: 12px; font-weight: 700; background: rgba(128,128,128,.18); }
.sf-il-hata-kutu { margin-top: 12px; border: 1px solid rgba(239,68,68,.55);
  background: rgba(239,68,68,.10); border-radius: 10px; padding: 10px 12px; }
.sf-il-hata-baslik { font-size: 14px; font-weight: 700; margin-bottom: 6px;
  display: flex; align-items: center; gap: 8px; }
.sf-il-etiket-hata { background: #dc2626; color: #fff; }
.sf-il-hata-liste { margin: 0; padding: 0 6px 0 20px; font-size: 13.5px; line-height: 1.5;
  max-height: 240px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
.sf-il-hata-liste li { margin-bottom: 4px; }
</style>"""


# Hata satırlarını tanıyan etiketler: günlükten okurken kullanılır (bkz. `hata_ozeti_html`).
HATA_ETIKETLERI = ("[KOTA]", "[YETKİ]", "[BAĞLANTI]", "[HATA]")


# Durum sırası: kalabalık projede bir küme en kötü durumuyla gösterilir.
_ONCELIK = ("HATA", "YARIM", "BEKLİYOR", "TAMAM")


_RENK = {"TAMAM": "sf-il-tamam", "YARIM": "sf-il-yarim", "HATA": "sf-il-hata"}


def _gosterim_durumu(klasor, adim):
    """Çubukta gösterilecek durum.

    Metin TAMAM dese bile dosyalar diskte yoksa adım tamam sayılmaz; çubuk
    gerçek durumu gösterir.
    """
    durum = adim.get("durum") or "BEKLİYOR"
    if durum == "TAMAM" and not adim_tamam(klasor, adim):
        return "YARIM"
    return durum


def _cubuk_dilimleri(adimlar, klasor, azami=60):
    """Her adım için (durum, ilk adım numarası) üret.

    Adım sayısı `azami`yi aşarsa dilimler kümelenir: her küme içindeki en kötü
    durumu taşır, böylece çubuk okunur kalır.
    """
    durumlar = [(a["index"], _gosterim_durumu(klasor, a)) for a in adimlar]
    if len(durumlar) <= azami:
        return list(durumlar)
    boy = math.ceil(len(durumlar) / azami)
    dilimler = []
    for bas in range(0, len(durumlar), boy):
        kume = durumlar[bas:bas + boy]
        durum = next(d for d in _ONCELIK if any(d == durum for _i, durum in kume))
        dilimler.append((kume[0][0], durum))
    return dilimler


def _html_metni(metin):
    """Metni HTML'e güvenle koy ve `**kalın**` işaretini gerçek kalına çevir."""
    guvenli = html.escape(str(metin or ""), quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", guvenli)


def bos_ilerleme_html(mesaj="Proje seçilmedi. Soldan ayarları yapıp **Projeye başlat**'a bas; "
                            "başka bir projeye geçmek için **‹ Projelere dön**."):
    """Proje yokken gösterilen boş ilerleme paneli."""
    return (ILERLEME_STIL + '<div class="sf-il"><div class="sf-il-ust">'
            '<span class="sf-il-baslik">İlerleme</span></div>'
            f'<div class="sf-il-not">{_html_metni(mesaj)}</div></div>')


def _kullanilan_hizmetler(veri):
    """Bu projede hangi hizmetler kullanılıyor: [(etiket, hizmet), …]."""
    ayar = (veri or {}).get("ayarlar") or {}
    adaylar = [("Video", "huggingface"),
               ("Görsel", (ayar.get("gorsel") or {}).get("provider")),
               ("Prompt", (ayar.get("video") or {}).get("ai")),
               ("Ses", SES_HIZMET.get((ayar.get("ses") or {}).get("provider")))]
    gorulen, sonuc = set(), []
    for etiket, hizmet in adaylar:
        if hizmet and hizmet not in gorulen:
            gorulen.add(hizmet)
            sonuc.append((etiket, hizmet))
    return sonuc


def hata_ozeti_html(veri):
    """Paneldeki **hata kutusu**: sorun varsa ilerlemenin hemen altında görünür.

    Önce hata veren adımlar yazılır (`Adım 3 · [KOTA] …`). Adımlarda güncel hata yoksa
    günlük ve son not taranır; böylece seslendirme, prompt ya da birleştirme hatası da
    burada görünür. Projede hiçbir sorun kalmadıysa kutu hiç çizilmez: eski hatalar
    biten bir projede ekranda kalmaz.
    """
    adimlar = veri.get("adimlar") or []
    kayitlar = [f"Adım {adim['index']} · {adim['hata']}" for adim in adimlar
                if adim.get("hata")]
    if kayitlar:
        # Kutu dört satır gösterir; kaç adımın hatalı olduğu başlıkta yazmazsa 16
        # hatalı adımlık projede yalnızca 4 sorun var sanılıyordu (14.10.2026).
        hatali = sum(1 for adim in adimlar if adim.get("durum") == "HATA")
        return _hata_kutusu(kayitlar[-4:], hatali)
    # Proje düzeyinde bir sorun kaldı mı? Kalmadıysa günlükteki eski hatalar gösterilmez.
    sorunlu = (veri.get("durum") in ("hata", "durduruldu")
               or veri.get("birlestirme") == "HATA"
               or any(adim.get("durum") != "TAMAM" for adim in adimlar))
    if not sorunlu:
        return ""
    adaylar = list(veri.get("gunluk") or []) + (veri.get("son_not") or "").splitlines()
    satirlar = [satir.strip() for satir in adaylar
                if any(etiket in satir for etiket in HATA_ETIKETLERI)]
    return _hata_kutusu(satirlar[-4:]) if satirlar else ""


def _hata_kutusu(satirlar, toplam=0):
    """Hata satırlarını kırmızı çerçeveli kutuya çevir."""
    ogeler = "".join(f'<li>{_html_metni(satir)}</li>' for satir in satirlar)
    baslik = (f"Son hatalar · {toplam} adımda hata (son {len(satirlar)} gösteriliyor)"
              if toplam > len(satirlar) else "Son hatalar")
    return (f'<div class="sf-il-hata-kutu"><div class="sf-il-hata-baslik">'
            f'<span class="sf-il-etiket sf-il-etiket-hata">HATA</span>'
            f'{baslik}</div><ul class="sf-il-hata-liste">{ogeler}</ul></div>')


def hesap_ozeti_html(veri=None):
    """Kullanılan hizmetlerin aktif hesabını ve yedek sayısını göster.

    Yedek hesap varsa kota dolduğunda proje durmadan sıradakine geçilir; yoksa o
    hizmette kota bitince proje durur. Kullanıcı bunu önceden görsün.
    """
    parcalar = []
    for etiket, hizmet in _kullanilan_hizmetler(veri):
        adlar = [k["ad"] for k in hesap_listesi(hizmet) if k["ad"] != KAYITSIZ]
        if not adlar:
            continue
        aktif = api_hesaplari.VARSAYILAN.aktif_hesap(hizmet)
        ek = f"+{len(adlar) - 1} yedek" if len(adlar) > 1 else "yedek yok"
        # Kalıcı kota listesi ile bu çalışmadaki eleme ayrı yazılır: biri saatlerce
        # sürer (açılış saati yazar), diğeri bir sonraki çalışmada kalkar.
        bekleyen = [k for k in KOTA_LISTESI.liste(hizmet) if k["ad"] in adlar]
        elenen = sum(1 for ad in adlar if (hizmet, ad) in ELENEN
                     and not any(k["ad"] == ad for k in bekleyen))
        if elenen:
            ek += f", bu çalışmada elenen: {elenen}"
        if bekleyen:
            ek += (f", kota bekleyen: {len(bekleyen)} (ilki '{bekleyen[0]['ad']}' "
                   f"{saat_metni(bekleyen[0]['acilis'])})")
        parcalar.append(f"{etiket}: {aktif} ({ek})")
    if not parcalar:
        return ""
    return f'<div class="sf-il-not">Hesaplar · {" · ".join(parcalar)}</div>'


def deneme_ozeti_html(veri):
    """Otomatik yeniden başlatmanın paneldeki satırı.

    Yalnızca hak harcanmışsa çizilir (boşken panel kalabalıklaşmaz): hangi işlemde kaç
    deneme kullanıldığı, yeniden başlatmanın sürüp sürmediği ve hak dolduysa ne
    yapılması gerektiği burada yazar. Hak dolmuşsa proje durmuş demektir.
    """
    kayitlar = []
    proje = veri.get("deneme") or {}
    for islem in PROJE_DENEMELERI:
        sayi = int(proje.get(islem) or 0)
        if sayi:
            kayitlar.append((DENEME_ADI[islem].capitalize(), sayi))
    for adim in veri.get("adimlar") or []:
        for islem in ADIM_DENEMELERI:
            sayi = int((adim.get("deneme") or {}).get(islem) or 0)
            if sayi:
                kayitlar.append((f"Adım {adim['index']} {DENEME_ADI[islem]}", sayi))
    if not kayitlar:
        return ""
    liste = " · ".join(f'{ad} <span class="sf-il-sayi">{sayi}/{YENIDEN_SINIR}</span>'
                       for ad, sayi in kayitlar)
    dolu = [ad for ad, sayi in kayitlar if sayi >= YENIDEN_SINIR]
    if dolu:
        return (f'<div class="sf-il-not sf-il-alarm"><span class="sf-il-etiket">DENEME '
                f'DOLDU</span> {liste} — {", ".join(dolu)} için {YENIDEN_SINIR} otomatik '
                'deneme hakkı doldu, proje durdu. <b>Deneme hakkını yenile</b>\'ye basıp '
                '<b>Kaldığı yerden devam et</b>.</div>')
    if veri.get("durum") == "calisiyor":
        return (f'<div class="sf-il-not sf-il-uyari"><span class="sf-il-etiket">YENİDEN '
                f'BAŞLATILIYOR</span> {liste} — hata sürerse aynı işlem tekrar denenir.</div>')
    return (f'<div class="sf-il-not sf-il-uyari"><span class="sf-il-etiket">YENİDEN '
            f'BAŞLATMA</span> {liste} — kalan hak, devam edildiğinde kullanılır.</div>')


def ilerleme_html(veri):
    """Adım adım ilerleme çubuğu: her adım bir kutu."""
    klasor = proje_klasoru(veri["slug"])
    adimlar = veri.get("adimlar") or []
    if not adimlar:
        # Seslendirme hazırsa akış prompt onayı kapısındadır: kullanıcı yapay zekâyı
        # seçip **Prompt üretimine başla**'ya basınca sahne planı çıkarılır.
        if (veri.get("ses") or {}).get("durum") == "TAMAM":
            return bos_ilerleme_html(
                "Seslendirme hazır. Sahne planını ve prompt'ları yazacak yapay zekâyı "
                "seçip **Prompt üretimine başla**'ya bas.")
        return bos_ilerleme_html("Henüz adım yok: önce seslendirme üretilmeli.")

    durumlar = {adim["index"]: _gosterim_durumu(klasor, adim) for adim in adimlar}
    tamam = sum(1 for durum in durumlar.values() if durum == "TAMAM")
    # Yüzde iki aşamayı birlikte sayar: hazır kare yarım, hazır video yarım adım.
    # Yalnızca TAMAM sayılsaydı bütün kareler bitip videolar beklerken %0 görünürdü.
    kareli = sum(1 for adim in adimlar
                 if adim.get("gorsel") and (klasor / adim["gorsel"]).exists())
    yuzde = math.floor((tamam + kareli) / (2 * len(adimlar)) * 100)
    sirada = next((adim["index"] for adim in adimlar
                   if durumlar[adim["index"]] != "TAMAM"), None)
    # Görsel onayından önce videolar hiç başlamaz: "0/141 adım" yerine hazır kare
    # sayılır ve görseli hazır adımlar "kare hazır" diye gösterilir.
    kare_asamasi = veri.get("gorsel_onay") != "VERİLDİ" and tamam < len(adimlar)

    adim_haritasi = {adim["index"]: adim for adim in adimlar}
    kutular = []
    for index, durum in _cubuk_dilimleri(adimlar, klasor):
        sinif = "sf-il-parca" + (" " + _RENK[durum] if durum in _RENK else "")
        if index == sirada:
            sinif += " sf-il-sirada"
        # Kutu başlığına o adımda harcanan deneme hakkı da yazılır (varsa).
        deneme = deneme_satiri((adim_haritasi.get(index) or {}).get("deneme") or {},
                                ADIM_DENEMELERI)
        ipucu = f"Adım {index}: {durum}" + (f" · {deneme}" if deneme else "")
        kutular.append(f'<span class="{sinif}" title="{ipucu}"></span>')

    # Sayılar çip olarak gösterilir: bir bakışta kaç adım bittiği, kaçının kaldığı
    # ve sıradaki adımın hangisi olduğu okunur.
    cipler = [f'<span class="sf-il-cip sf-il-cip-tamam">{tamam} tamam</span>']
    # `str.lower()` Türkçe değildir ("YARIM" → "yarim"): etiketler elle yazılır.
    for durum, sinif, ad in (("YARIM", "sf-il-cip-yarim", "kare hazır" if kare_asamasi else "yarım"),
                             ("HATA", "sf-il-cip-hata", "hata")):
        adet = sum(1 for d in durumlar.values() if d == durum)
        if adet:
            cipler.append(f'<span class="sf-il-cip {sinif}">{adet} {ad}</span>')
    kalan = sum(1 for d in durumlar.values() if d == "BEKLİYOR")
    if kalan:
        cipler.append(f'<span class="sf-il-cip">{kalan} bekliyor</span>')
    if sirada is not None:
        cipler.append(f'<span class="sf-il-cip sf-il-cip-sira">sıradaki: {sirada}. adım</span>')

    sure = float(veri.get("ses", {}).get("sure") or 0)
    satirlar = [
        '<div class="sf-il">',
        ('<div class="sf-il-ust"><span class="sf-il-baslik">İlerleme</span>'
         f'<span class="sf-il-rozet"><span class="sf-il-sayi">'
         f'{kareli if kare_asamasi else tamam}/{len(adimlar)}</span> '
         f'{"kare" if kare_asamasi else "adım"} · %{yuzde}</span></div>'),
        # Dar panelde 30'dan çok dilim tek sıraya sığmaz: sıra başına 30 dilim, alt alta.
        ('<div class="sf-il-cubuk' + (" sf-il-cubuk-yogun" if len(kutular) > 30 else "")
         + '">' + "".join(kutular) + "</div>"),
        '<div class="sf-il-sayilar">' + "".join(cipler) + "</div>",
        # Hatalar ilerlemenin hemen altında, en görünür yerde durur.
        hata_ozeti_html(veri),
    ]
    if sure:
        toplam_video = sum(adim_suresi(a, proje_adim_saniyesi(veri)) for a in adimlar)
        satirlar.append(f'<div class="sf-il-not">Ses {_numara(sure)} sn → '
                        f'{len(adimlar)} sahne · toplam {toplam_video:g} sn video '
                        f'(süreler içeriğe göre değişken)</div>')
    # Prompt onayı kapısı: seslendirme hazır ama yazacak iş kaldıysa (plan yok ya da
    # prompt'ı eksik sahneler var) akış kullanıcıdan yapay zekâ seçimini bekler.
    if any(not (adim.get("image_prompt") and adim.get("video_prompt")) for adim in adimlar):
        satirlar.append('<div class="sf-il-not"><b>Prompt üretimi bekleniyor</b> · '
                        'Sahne planını ve prompt\'ları yazacak yapay zekâyı seçip '
                        '<b>Prompt üretimine başla</b>ya bas.</div>')
    # Görsel onayı kapısı: kareler hazır ama videolar bekliyorsa en görünür yerde söyle.
    bekleyen_video = sum(1 for durum in durumlar.values() if durum != "TAMAM")
    if bekleyen_video and veri.get("gorsel_onay") != "VERİLDİ":
        kareli = sum(1 for durum in durumlar.values() if durum in ("YARIM", "TAMAM"))
        satirlar.append('<div class="sf-il-not"><b>Görsel onayı bekleniyor</b> · '
                        f'{kareli}/{len(adimlar)} kare hazır. Kareleri gözden geçirip '
                        '<b>Görselleri onayla</b>ya bas; videolar ondan sonra üretilir.</div>')
    if veri.get("birlestirme") == "TAMAM":
        satirlar.append('<div class="sf-il-not">Birleşik video hazır: <b>proje.mp4</b></div>')
    satirlar.append(deneme_ozeti_html(veri))
    satirlar.append(hesap_ozeti_html(veri))
    satirlar.append("</div>")
    return ILERLEME_STIL + "".join(satirlar)


def proje_videosu(klasor):
    yol = klasor / "proje.mp4"
    return str(yol) if yol.exists() else None


_ADIM_MESAJI = re.compile(r"^Adım (\d+)/\d+")


def hata_sebebi(metin):
    """Uzun hata metninin kısa adı: `kota yetersiz` · `GPU hatası` · …"""
    metin = str(metin or "")
    kucuk = metin.lower()
    if "no gpu" in kucuk:
        return "GPU hatası"
    if "[kota]" in kucuk or "quota" in kucuk or "kota" in kucuk:
        return "kota yetersiz"
    if "[yetki]" in kucuk or "yetkisi yok" in kucuk or "reddedildi" in kucuk:
        return "yetki hatası"
    if "[bağlanti]" in kucuk or "bağlantı" in kucuk or "timeout" in kucuk:
        return "bağlantı hatası"
    return "hata"


def kisa_durum(mesaj):
    """Durum paneli için adım mesajını kısalt: `Adım 26 · video oluştu ✔`.

    Yalnızca `Adım N/M …` ile başlayan üretim mesajları kısalır; onay, prompt ve klasör
    gibi yönlendiren mesajlar olduğu gibi kalır. proje.txt günlüğü ayrıntılı kalır
    (kullanıcı kararı, 12.10.2026).
    """
    metin = str(mesaj or "")
    eslesme = _ADIM_MESAJI.match(metin)
    if not eslesme:
        return metin
    tur = "video" if re.match(r"[\s·]*video", metin[eslesme.end():]) else "görsel"
    k = metin.lower()
    # Hak yakmadan duran/bekleyen adımlar (14.10.2026): bunlar eşleşmeyince panelde
    # "video işleniyor…" görünüyor, durmuş grup çalışıyor sanılıyordu.
    if "deneme hakkı harcanmadı" in k:
        kisa = "GPU bulunamadı ✖" if "boş gpu" in k else "kota bitti ✖"
    elif "deneme hakkı doldu" in k:
        kisa = "deneme hakkı doldu ✖"
    elif "denemede hata" in k:
        tekrar = re.search(r"\((\d+)/(\d+)\);", metin)
        kisa = hata_sebebi(metin) + (f" · tekrar {tekrar.group(1)}/{tekrar.group(2)}"
                                     if tekrar else " · tekrar")
    elif "tamamlanamadı" in k:
        kisa = hata_sebebi(metin) + " ✖"
    elif "durduruldu" in k:
        kisa = "durduruldu"
    elif "dakikalık hız sınırında" in k:
        kisa = "hız sınırı, bekleniyor"
    elif "hesabı elendi" in k or "kotası doldu" in k or "kullanılamıyor" in k:
        kisa = hata_sebebi(metin) + ", yedek deneniyor"
    elif "hata verdi" in k or "bağlantı hatası verdi" in k:
        kisa = hata_sebebi(metin) + " (geçici)"
    elif "hesabına geçildi" in k:
        kisa = "yedek hesaba geçti"
    elif "otomatik yeniden başlatma başarılı" in k or " tamam" in k or "tamamlandı" in k:
        kisa = f"{tur} oluştu ✔"
    elif "denetle" in k or "denetim" in k:
        kisa = "denetleniyor…"
    elif "üretiliyor" in k:
        kisa = f"{tur} üretiliyor…"
    else:
        kisa = f"{tur} işleniyor…"
    return f"Adım {eslesme.group(1)} · {kisa}"


def arayuz_paketi(veri, mesaj):
    """Arayüze dönecek paket: durum, proje metni, dosyalar, görseller, video, çubuk."""
    klasor = proje_klasoru(veri["slug"])
    return (kisa_durum(mesaj), log_metni(veri), proje_dosyalari(klasor), proje_gorselleri(klasor),
            proje_videosu(klasor), ilerleme_html(veri))


def bos_paket(mesaj):
    return (mesaj, "", [], [], None, bos_ilerleme_html())


def paket_ozeti(veri):
    """Kısa durum satırı: kaç adım tamam, hangi adımda kalındı."""
    adimlar = veri["adimlar"]
    tamam = sum(1 for adim in adimlar if adim.get("durum") == "TAMAM")
    satir = f"{veri['ad']} · {tamam}/{len(adimlar)} adım tamam"
    kalan = [adim for adim in adimlar if adim.get("durum") != "TAMAM"]
    if kalan:
        satir += f" · sıradaki adım: {kalan[0]['index']}"
    return satir
