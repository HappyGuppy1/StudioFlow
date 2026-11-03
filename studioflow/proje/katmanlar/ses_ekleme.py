"""Videoya seslendirme ve gömülü altyazı ekleme / yeniden oluşturma."""
import difflib
import os
import re
import shutil
from datetime import datetime

from studioflow.altyazi.bloklar import build_cues, tahmini_kelimeler, write_srt, write_vtt
from studioflow.altyazi.gorunum import altyazi_ayari, altyazi_olcu, altyazi_seviye
from studioflow.altyazi.hizalama import align_parts
from studioflow.altyazi.kural import sub_rules
from studioflow.ayarlar.bicimler import bicim_bilgisi
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.hatalar import gorsel_hatasi_temizle, hata_etiketle
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.calisma_kilidi import calisan
from studioflow.proje.depo import guvenli_klasor, slug
from studioflow.proje.katmanlar.diller import dil_videoya_ekle, ham_videoyu_hazirla
from studioflow.proje.dosya import gorsel_kaynak_bicim, not_ekle, proje_oku, proje_yaz
from studioflow.proje.dosya_yollari import (
    altyazi_dosyasi, anlatim_suzgeci, ses_dosyasi, ses_seviyesi, sure_ozeti)
from studioflow.proje.ilerleme import arayuz_paketi, bos_paket
from studioflow.proje.katmanlar.muzik import muzik_geri_uygula, ses_katmanini_kur
from studioflow.proje.sabitler import DOSYA_ADI, HAM_VIDEO_ADI
from studioflow.proje.yeniden_deneme import hata_yaz
from studioflow.saglayicilar import hesap_havuzu
from studioflow.saglayicilar.hesap_havuzu import hesap_kimligi


def altyazi_metinden_yaz(klasor, veri, sure=0.0):
    """Altyazı dosyası yoksa **anlatım metninden** SRT + VTT üret.

    Seslendirme üretilirken `Altyazı üret` kapalıysa (ya da dosya elle silindiyse)
    ortada gömülecek bir altyazı kalmaz. Eskiden kullanıcı yalnızca görünümü
    değiştirmek için projeyi baştan çalıştırmak, yani sesi yeniden üretip kotayı
    tekrar harcamak zorundaydı. Bu yardımcı altyazıyı sıfırdan yazar:

    * metin: projenin anlatımı (`veri["metin"]`),
    * kelime zamanları: **önce gerçek ses** (`altyazi_kelimeleri` — ses varsa
      whisper ile dinlenir ve zamanlar anlatımın kelimelerine eşlenir), ses yoksa
      **metinden tahmin**,
    * bloklar: `veri["ayarlar"]["altyazi"]["ayar"]` (paneldeki satır/süre sınırları),
    * süre: ölçülen ses süresi (`veri["ses"]["sure"]`), yoksa son adımın bitişi.

    Dönüş: `(yazılan SRT yolu, zamanların kaynağı, sese geçilemediyse sebebi)`;
    üretilemediyse (anlatım ya da süre yok) `None`. Kaynak `"ses"` ya da `"metin"`.
    """
    metin = (veri.get("metin") or "").strip()
    if not metin:
        return None
    sure = float(sure or (veri.get("ses") or {}).get("sure") or 0)
    if sure <= 0:
        sure = max((float(adim.get("end") or 0) for adim in veri.get("adimlar") or []),
                   default=0.0)
    if sure <= 0:
        return None
    kelimeler, kaynak, sebep = altyazi_kelimeleri(klasor, veri, metin, sure)
    if not kelimeler:
        return None
    ham = dict((veri.get("ayarlar", {}).get("altyazi") or {}).get("ayar") or {})
    kural = sub_rules(**{ad: ham.get(ad) for ad in ("line_chars", "max_lines",
                                                              "min_seconds", "max_seconds")})
    cues = build_cues(kelimeler, kural)
    if not cues:
        return None
    hedef = klasor / "ses"
    hedef.mkdir(parents=True, exist_ok=True)
    srt = write_srt(cues, hedef / "seslendirme.srt")
    write_vtt(cues, hedef / "seslendirme.vtt")
    return srt, kaynak, sebep


def _zamanlari_esle(metin, kelimeler):
    """ASR'nin bulduğu **zamanları** anlatım metninin kelimelerine eşle.

    Ses tanıma kendi yazımıyla döner (büyük harf, yanlış duyulan ya da birleştirilmiş
    kelime), oysa altyazıda projenin kendi anlatımı görünmelidir. İki kelime listesi
    `difflib` ile hizalanır: eşleşen kelimeler ASR'nin **gerçek** zamanını alır,
    eşleşmeyenler iki komşusunun arasına uzunluklarına göre dağıtılır. Böylece metin
    anlatımdan, zamanlar gerçek konuşmadan gelir.

    Dönüş: `(başlangıç, bitiş, kelime)` listesi; eşleşme kelimelerin yarısından
    azsa `None` (o durumda çağıran metinden tahmine düşer).
    """
    hedef = [k for k in re.split(r"\s+", (metin or "").strip()) if k]
    kaynak = [(float(k[0]), float(k[1]), str(k[2])) for k in kelimeler or []]
    if not hedef or not kaynak:
        return None
    # Karşılaştırma yalnızca kelime karakterleriyle yapılır: noktalama ve büyük/küçük
    # harf farkı eşleşmeyi bozmasın (Türkçe harfler `\w` içindedir).
    eslesme = difflib.SequenceMatcher(
        a=[re.sub(r"[^\w]+", "", k[2].lower()) for k in kaynak],
        b=[re.sub(r"[^\w]+", "", k.lower()) for k in hedef],
        autojunk=False).get_matching_blocks()
    bulunan = {blok.b + sira: (kaynak[blok.a + sira][0], kaynak[blok.a + sira][1])
               for blok in eslesme for sira in range(blok.size)}
    if len(bulunan) < len(hedef) * 0.5:
        return None
    citler = sorted(bulunan)

    def doldur(siralar, bas, son):
        """Eşleşmeyen kelimeleri `[bas, son]` aralığına uzunluklarına göre dağıt."""
        if not siralar:
            return
        if son <= bas:
            son = bas + 0.01 * len(siralar)
        agirlik = [len(hedef[sira]) + 1 for sira in siralar]
        toplam, gecen = sum(agirlik), bas
        for sira, pay in zip(siralar, agirlik):
            sure = (son - bas) * pay / toplam
            bulunan[sira] = (gecen, gecen + sure)
            gecen += sure

    # Baştaki, aradaki ve sondaki eşleşmeyen kelimeler komşularının arasına girer.
    doldur(list(range(0, citler[0])), 0.0, bulunan[citler[0]][0])
    for onceki, sonraki in zip(citler, citler[1:]):
        doldur(list(range(onceki + 1, sonraki)), bulunan[onceki][1], bulunan[sonraki][0])
    doldur(list(range(citler[-1] + 1, len(hedef))), bulunan[citler[-1]][1],
           max(kaynak[-1][1], bulunan[citler[-1]][1] + 0.01))
    # ASR nadiren sırasız zaman döndürür; geriye giden damga altyazıyı bozar.
    sonuc, onceki_son = [], 0.0
    for sira, kelime in enumerate(hedef):
        bas, son = bulunan.get(sira) or (onceki_son, onceki_son + 0.01)
        bas = max(bas, onceki_son)
        son = max(son, bas + 0.01)
        sonuc.append((bas, son, kelime))
        onceki_son = son
    return sonuc


def altyazi_kelimeleri(klasor, veri, metin, sure):
    """Altyazı kelime zamanları: önce **gerçek ses**, olmazsa metinden tahmin.

    Ses dosyası varsa ses whisper ile dinlenir (`hizalama.align_parts`) ve zamanlar
    anlatımın kelimelerine eşlenir; böylece altyazı gerçek konuşmayla hizalanır.
    Cloudflare hesapları aktif olandan başlayarak sırayla denenir: kotası dolan ya da
    yetkisi olmayan hesap elenir, çalışan hesap aktif yapılır. Ses yoksa, hiçbir hesap
    dinleyemezse ya da çözüm güvenilmezse kelimeler metinden tahmin edilir.

    Dönüş: `(kelimeler, kaynak, sebep)` · `kaynak` `"ses"` ya da `"metin"`;
    `sebep` yalnızca sese geçilemediğinde nedenini açıklar.
    """
    ses = ses_dosyasi(klasor, veri)
    if ses is None:
        return tahmini_kelimeler(metin, sure), "metin", "seslendirme dosyası yok"
    dil = (veri.get("ayarlar", {}).get("ses") or {}).get("dil") or "tr"
    # Whisper da görsel üretimi gibi **hesap havuzunu** dolaşır: eskiden yalnızca aktif
    # hesap deneniyordu; aktif hesabın kotası dolunca (13.10.2026: 'apple' dolu, 20 hesap
    # boştu) zamanlar sessizce metinden tahmin ediliyor ve sahneler sesle kayıyordu.
    hatali = []
    for kayit in hesap_havuzu.hesap_listesi("cloudflare"):
        if hesap_havuzu.hesap_elendi("cloudflare", kayit):
            continue
        kimlik = hesap_kimligi(veri, "cloudflare", kayit)
        if not (kimlik["cf_account_id"] and kimlik["cf_token"]):
            continue
        try:
            ham, guvenilmez = align_parts(
                [ses], [metin], kimlik["cf_account_id"], kimlik["cf_token"], dil)
        except Exception as exc:
            durum = gorsel_hatasi_temizle(exc, kimlik["cf_token"])
            hatali.append(f"{hesap_havuzu.hesap_adi(kayit)}: {_ilk_satir(durum, 120)}")
            if hata_etiketle(durum) not in ("KOTA", "YETKİ"):
                # Kota/yetki dışı hata isteğin sorunudur; başka hesap aynısını alır.
                break
            hesap_havuzu.hesap_ele("cloudflare", kayit, durum)
            continue
        hesap_havuzu.hesap_basarisi("cloudflare", kayit)
        hesap_havuzu.hesap_aktif_yap("cloudflare", kayit)
        kelimeler = _zamanlari_esle(metin, ham)
        if kelimeler and not guvenilmez:
            return kelimeler, "ses", ""
        # Çözüm kötüyse hesap değil ses sorunludur: başka hesap aynı sonucu verir.
        sebep = ("ses çözümü güvenilir değildi" if guvenilmez else
                 "ses çözümü anlatımla eşleşmedi")
        return tahmini_kelimeler(metin, sure), "metin", sebep
    sebep = ("ses dinlenemedi: " + " · ".join(hatali) if hatali else
             "Cloudflare Account ID/token kayıtlı değil, ses dinlenemedi")
    return tahmini_kelimeler(metin, sure), "metin", sebep


def ekleme_sifirla(veri):
    """`proje.mp4` yeniden üretildiyse ses/altyazı/müzik eklemeleri geçersizdir."""
    if (veri.get("ses_ekleme") == "BEKLİYOR" and veri.get("altyazi_ekleme") == "BEKLİYOR"
            and veri.get("muzik_ekleme") == "BEKLİYOR" and not veri.get("ekli_dil")
            and not veri.get("ekli_dublaj") and not veri.get("muzikler")):
        return False
    veri["ses_ekleme"] = "BEKLİYOR"
    veri["ses_ekleme_bitti"] = ""
    veri["altyazi_ekleme"] = "BEKLİYOR"
    veri["altyazi_ekleme_bitti"] = ""
    # Ekli dublaj da kalkar: video artık ham hâline döndüğü için hiçbir dublaj duyulmaz.
    veri["ekli_dil"] = ""
    veri["ekli_dublaj"] = ""
    veri["ekli_altyazi"] = ""
    # Müzik katmanı da kalkar: birleştirme videoyu sessiz üretti. Kaydedilmiş müzik
    # dosyaları silinmez, listeden yeniden eklenir.
    veri["muzik_ekleme"] = "BEKLİYOR"
    veri["muzik_ekleme_bitti"] = ""
    veri["muzikler"] = []
    not_ekle(veri, "proje.mp4 yeniden birleştirildi; ses, altyazı, ekli dublaj ve müzik "
                    "sıfırlandı.")
    return True


def ekleme_hedefi(ad, etiket):
    """Düğmelerin ortak ön kontrolü: `(klasör, veri, proje.mp4)` ya da hata paketi."""
    ad = (ad or "").strip()
    if not ad:
        return None, None, None, bos_paket(f"Videoya {etiket} eklemek için önce bir proje seç.")
    if calisan() == slug(ad):
        return None, None, None, bos_paket(
            f"'{ad}' şu anda çalışıyor. Önce **Durdur**'a bas, sonra {etiket} ekle.")
    klasor = guvenli_klasor(ad)
    veri = proje_oku(klasor) if klasor else None
    if veri is None or klasor is None:
        return None, None, None, bos_paket(
            f"'{ad}' okunamadı: klasöründe okunabilir bir {DOSYA_ADI} yok.")
    # Yazma hedefi seçilen klasör olmalı: `proje.txt` içindeki ad klasör adından
    # farklıysa (elle yeniden adlandırma) metne değil seçilen klasöre yazılır.
    veri["slug"] = slug(ad)
    video = klasor / "proje.mp4"
    if not video.is_file():
        return klasor, veri, None, arayuz_paketi(
            veri, f"`proje.mp4` yok; önce adımlar birleştirilmeli. "
                  "**Kaldığı yerden devam et**'e bas.")
    if not FFMPEG.ffmpeg():
        return klasor, veri, None, arayuz_paketi(
            veri, "ffmpeg bulunamadı; videoya ekleme yapılamadı. ffmpeg'i kurup tekrar dene.")
    return klasor, veri, video, None


def ekleme_yaz(veri, baslik, gecici, video, alan, bitti_alani):
    """Başarılı eklemeyi metne işle (geçici dosya `proje.mp4`ün yerine geçer)."""
    try:
        os.replace(gecici, video)
    except OSError as hata:
        return "Videoya ekleme tamamlandı ama dosya yerine yazılamadı: " + _ilk_satir(hata, 200)
    veri[alan] = "TAMAM"
    veri[bitti_alani] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    veri["durum"] = "tamam"
    veri["son_not"] = baslik
    not_ekle(veri, baslik)
    proje_yaz(veri)
    return None


def _seviye_panelden(veri, seviye):
    """Paneldeki seslendirme seviyesini projeye işle; gerçekten değiştiyse `True` döner."""
    if seviye is None:
        return False
    ses_ayar = veri["ayarlar"].setdefault("ses", {})
    yeni = ses_seviyesi(seviye)
    if ses_seviyesi(ses_ayar.get("seviye")) == yeni:
        return False
    ses_ayar["seviye"] = yeni
    not_ekle(veri, f"Seslendirme seviyesi panelden güncellendi: %{yeni:g}.")
    proje_yaz(veri)
    return True


def videoya_ses_ekle(ad, seviye=None):
    """Seslendirmeyi `proje.mp4`e ekle. Sonuç tek dosyadır: `proje.mp4`.

    Düğmeye basılmazsa hiçbir şey değişmez; basılırsa ses eklenir. Altyazı eklemek
    ayrı bir düğmedir ve sesi korur, yani ikisi aynı videoda birleşir.

    `seviye` paneldeki **Seslendirme ses seviyesi**dir (%); verilirse önce projeye
    yazılır. Ses zaten ekliyse ve seviye değiştiyse ses akışı yeni seviyeyle baştan
    kurulur (görüntü ve gömülü altyazı kopyalanır, ekli dublaj ve müzik korunur).
    """
    klasor, veri, video, hata = ekleme_hedefi(ad, "ses")
    if hata is not None:
        return hata
    degisti = _seviye_panelden(veri, seviye)
    yuzde = ses_seviyesi(veri["ayarlar"]["ses"].get("seviye"))
    if veri.get("ses_ekleme") == "TAMAM":
        if not degisti:
            return arayuz_paketi(
                veri, f"Ses bu videoya zaten eklenmiş (seviye %{yuzde:g}); yeniden eklenmedi. "
                      "Sesi yükseltmek/kısmak için **Seslendirme ayarları** panelindeki "
                      "**ses seviyesini** değiştirip bu düğmeye yeniden bas.")
        ok, mesaj = ses_katmanini_kur(veri, klasor)
        if not ok:
            return arayuz_paketi(veri, hata_yaz(veri, None, "Ses seviyesi",
                                          "Ses seviyesi uygulanamadı: " + mesaj))
        baslik = f"Seslendirme seviyesi videoda %{yuzde:g} olarak güncellendi (proje.mp4)."
        veri["son_not"] = baslik
        not_ekle(veri, baslik)
        proje_yaz(veri)
        return arayuz_paketi(veri, baslik + " " + sure_ozeti(veri))
    ses = ses_dosyasi(klasor, veri)
    if ses is None:
        return arayuz_paketi(veri, "Seslendirme dosyası bulunamadı. Önce projeyi çalıştırıp sesi üret.")
    baslik = f"Ses videoya eklendi (proje.mp4 · seviye %{yuzde:g})."
    gecici = klasor / "proje-ses.gecici.mp4"
    gecici.unlink(missing_ok=True)
    # `-shortest` **kullanılmaz**: ses, videodan kısa olsa bile video sonuna kadar
    # sürer. Video süresi adım sayısı × adım süresidir; ses kendi süresinde kalır
    # (ör. 16,3 sn ses + 4 adım → 20 sn video, son 3,7 sn sessiz).
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-i", "proje.mp4", "-i", ses.relative_to(klasor).as_posix(),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy"]
    if anlatim_suzgeci(veri):
        komut += ["-af", anlatim_suzgeci(veri)]
    komut += ["-c:a", "aac", "-b:a", "192k", str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut, cwd=klasor)
    if not ok:
        gecici.unlink(missing_ok=True)
        return arayuz_paketi(veri, hata_yaz(veri, None, "Ses ekleme",
                                      "Ses videoya eklenemedi: " + mesaj))
    sorun = ekleme_yaz(veri, baslik, gecici, video, "ses_ekleme", "ses_ekleme_bitti")
    if sorun:
        return arayuz_paketi(veri, sorun)
    # Ses eklenirken video yeniden yazıldı: müzik katmanı varsa geri uygulanır, yoksa
    # müzik sessizce kaybolurdu.
    ek = muzik_geri_uygula(veri, klasor)
    return arayuz_paketi(veri, baslik + " " + sure_ozeti(veri) + ek +
                  " Altyazıyı da eklemek için **Altyazıyı videoya ekle**'ye bas.")


def altyazi_panelden(veri, altyazi):
    """Paneldeki altyazı ayarlarını projeye işle; gerçekten değiştiyse `True` döner.

    Gömme işlemleri ayarları **`proje.txt`'ten** okur; var olan bir projede arayüz
    seçimleri kendiliğinden kullanılmaz (bilerek: kalan adımlar başka bir görünümle
    karışmasın). Bu yüzden **Video altyazısını tekrar oluştur** düğmesi seçimleri önce
    projeye yazar, sonra gömmeyi yeniler.
    """
    if not isinstance(altyazi, dict) or not altyazi:
        return False
    onceki = veri["ayarlar"].get("altyazi") or {}
    if dict(onceki) == dict(altyazi):
        return False
    veri["ayarlar"]["altyazi"] = dict(altyazi)
    not_ekle(veri, "Altyazı ayarları panelden güncellendi: "
                    f"{altyazi.get('font')} · {altyazi.get('renk')}"
                    f"{' · kalın' if altyazi.get('kalin') else ''}"
                    f" · seviye %{altyazi_seviye(altyazi.get('seviye')):g}"
                    f" · preset {altyazi.get('preset')}.")
    proje_yaz(veri)
    return True


def videoya_altyazi_yeniden(ad, altyazi=None):
    """Videodaki altyazıyı panelin **güncel ayarlarıyla baştan** oluştur.

    **Altyazıyı videoya ekle** bir kez çalıştıktan sonra kendini tekrarlamaz (üst üste
    gömme altyazıyı iki kez yazardı); ayrıca gömme ayarları `proje.txt`'ten okunur. Bu
    yüzden yazı tipi/rengi/kalınlığı değiştiren kullanıcı videoyu elle düzeltmek zorunda
    kalıyordu. Bu düğme o işi tek adıma indirir:

    1. Paneldeki altyazı ayarları projeye işlenir,
    2. videodaki **eski gömme kaldırılır** (`proje.mp4` ham videodan yeniden kurulur;
       böylece altyazı üst üste binmez), varsa seslendirme ve ekli dil geri uygulanır,
    3. altyazı **güncel ayarlarla** yeniden gömülür.

    **Altyazı üret** kapalıysa yenisi gömülmez; yalnızca eski altyazı videodan kaldırılır.
    Altyazı dosyası (`ses/seslendirme.srt`) yoksa **anlatım metninden sıfırdan üretilir**
    (`altyazi_metinden_yaz`): kelime zamanları metinden tahmin edilir, ses yeniden
    üretilmez ve hiçbir servise istek gitmez. Anlatım metni de yoksa (proje hiç
    çalışmamış) hiçbir şey değişmez ve önce projenin çalıştırılması gerektiği söylenir.
    """
    klasor, veri, video, hata = ekleme_hedefi(ad, "altyazı")
    if hata is not None:
        return hata
    altyazi_panelden(veri, altyazi)
    acik = True if not isinstance(altyazi, dict) else bool(altyazi.get("acik", True))
    # Altyazı dosyası yoksa anlatım metninden sıfırdan üretilir: yeniden ses
    # üretmek (kota harcamak) gerekmez (bkz. `altyazi_metinden_yaz`).
    yenilendi = ""
    if acik and altyazi_dosyasi(klasor) is None:
        yazilan = altyazi_metinden_yaz(klasor, veri)
        if yazilan is not None:
            _, kaynak, sebep = yazilan
            esas = ("kelime zamanları **gerçek sesle hizalandı** (ses dinlendi)" if kaynak == "ses"
                    else "kelime zamanları **metinden tahmin edildi**")
            not_ekle(veri, f"Altyazı dosyası yoktu; anlatım metninden yeniden üretildi "
                            f"(zamanlar: {kaynak})." + (f" Sesle hizalanamadı: {sebep}" if sebep else ""))
            proje_yaz(veri)
            yenilendi = ("Altyazı dosyası yoktu (`ses/seslendirme.srt`); **anlatım "
                         f"metninden** yeniden üretildi · {esas}"
                         + (f" · sese geçilemedi: {sebep}" if sebep else "") + ". Ses yeniden "
                         "üretilmedi.")
    # Ekli dublaj varsa video zaten ham videodan kurulur: altyazısını yenile (aynı yol).
    ekli = (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()
    if ekli and veri.get("altyazi_ekleme") == "TAMAM":
        cikti = dil_videoya_ekle(ad, ekli, altyazi_gom=acik)
        taze = proje_oku(klasor) or veri
        taze["slug"] = veri["slug"]
        return arayuz_paketi(taze, cikti[0] + " Altyazı paneldeki güncel ayarlarla yenilendi.")
    if not acik and veri.get("altyazi_ekleme") != "TAMAM":
        # Kapatma istenmiş ama videoda gömülü altyazı da yok: eksik dosyayı söyleyip
        # kullanıcıyı yanıltmak yerine durumu açıkça söyle.
        return arayuz_paketi(veri, "**Altyazı üret** kapalı ve videoda gömülü altyazı yok; "
                            "yapılacak bir şey yok.")
    if veri.get("altyazi_ekleme") != "TAMAM":
        # Videoda gömülü altyazı yok: yapılacak iş zaten normal eklemedir.
        sonuc = videoya_altyazi_ekle(ad)
        return (sonuc[0] + " " + yenilendi, ) + sonuc[1:] if yenilendi else sonuc
    # ── Eski gömmeyi kaldır: proje.mp4 ham videodan yeniden kurulur ──
    ses_vardi = veri.get("ses_ekleme") == "TAMAM"
    ham, mesaj = ham_videoyu_hazirla(klasor, veri)
    if ham is None:
        return arayuz_paketi(veri, mesaj)
    gecici = klasor / "proje-yenile.gecici.mp4"
    gecici.unlink(missing_ok=True)
    try:
        shutil.copy2(ham, gecici)
        os.replace(gecici, klasor / "proje.mp4")
    except OSError as exc:
        gecici.unlink(missing_ok=True)
        return arayuz_paketi(veri, "Video ham videodan kurulamadı: " + _ilk_satir(exc, 200))
    veri["ham_video"] = HAM_VIDEO_ADI
    veri["ses_ekleme"] = "BEKLİYOR"
    veri["ses_ekleme_bitti"] = ""
    veri["altyazi_ekleme"] = "BEKLİYOR"
    veri["altyazi_ekleme_bitti"] = ""
    veri["ekli_dil"] = ""
    veri["ekli_dublaj"] = ""
    veri["ekli_altyazi"] = ""
    not_ekle(veri, "Altyazıyı yeniden oluşturmak için eski gömme kaldırıldı.")
    proje_yaz(veri)
    notlar = ["Eski gömülü altyazı kaldırıldı."]
    ses_geri = False
    if ses_vardi:
        ses_cikti = videoya_ses_ekle(ad)
        ses_geri = "videoya eklendi" in ses_cikti[0]
        if ses_geri:
            notlar.append("Seslendirme geri eklendi.")
        else:
            notlar.append("Seslendirme geri eklenemedi: " + _ilk_satir(ses_cikti[0], 200))
    if not acik:
        taze = proje_oku(klasor) or veri
        taze["slug"] = veri["slug"]
        # Kapanış, gerçek durumu söyler: ses geri eklendiyse "sessiz" demek yanlış olurdu.
        kapanis = ("**Altyazı üret** kapalı olduğu için yenisi gömülmedi; video sesli "
                   "ve altyazısız hâlde kaldı." if ses_geri else
                   "**Altyazı üret** kapalı olduğu için yenisi gömülmedi; yalnızca eski "
                   "gömülü altyazı videodan kaldırıldı.")
        ek = muzik_geri_uygula(taze, klasor)
        return arayuz_paketi(taze, " ".join(notlar + [kapanis]) + ek)
    sonuc = videoya_altyazi_ekle(ad)
    ek = muzik_geri_uygula(proje_oku(klasor) or veri, klasor)
    return (sonuc[0] + " " + " ".join(notlar + [yenilendi]).strip() + ek,) + sonuc[1:]


def videoya_altyazi_ekle(ad):
    """Altyazıyı `proje.mp4`e göm (hard sub). Sonuç tek dosyadır: `proje.mp4`.

    Altyazı dosyası projede üretilmiş olmalıdır (`ses/seslendirme.srt`); üretmek
    seslendirme ayarlarındaki **Altyazı üret** kutusuna bağlıdır ve eklemek için
    bu düğmeye ayrıca basmak gerekir. Varsa ses akışı korunur.
    """
    klasor, veri, video, hata = ekleme_hedefi(ad, "altyazı")
    if hata is not None:
        return hata
    if veri.get("altyazi_ekleme") == "TAMAM":
        return arayuz_paketi(veri, "Altyazı bu videoya zaten eklenmiş; yeniden eklenmedi.")
    altyazi = altyazi_dosyasi(klasor)
    if altyazi is None:
        return arayuz_paketi(
            veri, "Altyazı dosyası yok (ses/seslendirme.srt). Seslendirme ayarlarında "
                  "**Altyazı üret** işaretliyken projeyi çalıştır; sonra bu düğmeye bas.")
    baslik = "Altyazı videoya gömüldü (proje.mp4)."
    gecici = klasor / "proje-altyazi.gecici.mp4"
    gecici.unlink(missing_ok=True)
    genislik, yukseklik = FFMPEG.video_olcusu(video)
    if not yukseklik:
        olcu = bicim_bilgisi(gorsel_kaynak_bicim(veri))
        genislik, yukseklik = olcu["genislik"], olcu["yukseklik"]
    try:
        altyazi_satirlari = altyazi.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        altyazi_satirlari = None
    stil, yazi, alt = altyazi_olcu(genislik, yukseklik, altyazi_ayari(veri),
                                    altyazi_satirlari)
    # Altyazı, ffmpeg `ses/` klasöründe çalıştırılarak **göreli** adla verilir; böylece
    # Windows'ta `C:` iki noktası ve ters bölü kaçış sorunu oluşmaz.
    komut = [FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(video),
             "-vf", f"subtitles={altyazi.name}:force_style='{stil}'",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "copy",
             str(gecici)]
    ok, mesaj = FFMPEG.calistir(komut, cwd=altyazi.parent)
    if not ok:
        gecici.unlink(missing_ok=True)
        return arayuz_paketi(veri, hata_yaz(veri, None, "Altyazı ekleme",
                                      "Altyazı videoya gömülemedi: " + mesaj +
                                      " (ffmpeg derlemesinde `subtitles`/libass gerekir)."))
    sorun = ekleme_yaz(veri, baslik, gecici, video, "altyazi_ekleme", "altyazi_ekleme_bitti")
    if sorun:
        return arayuz_paketi(veri, sorun)
    return arayuz_paketi(veri, baslik + f" {genislik}×{yukseklik} tuvalde yazı {yazi} px, "
                  f"alt boşluk {alt} px. " + sure_ozeti(veri) +
                  " Ses de eklendiyse tek dosyada birleşti.")
