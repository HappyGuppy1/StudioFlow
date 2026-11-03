"""Proje oluştur sekmesi — geri çağrı işlevleri."""
import time
from html import escape
from pathlib import Path

import gradio as gr

from studioflow.arayuz import editor, islevler_karakter
from studioflow.arayuz.islevler_gorsel import gorsel_boyut_ayari
from studioflow.arayuz.islevler_ses import ses_testi_akisi
from studioflow.arayuz.sabitler import (
    NEGATIF_DESTEK_YOK_NOT, PJ_ALTYAZI_HAZIR, PJ_COK_HAZIR, PJ_MUZIK_HAZIR,
    PJ_UR_ALTYAZI_HAZIR, PJ_UR_DUBLAJ_HAZIR, PJ_UR_MUZIK_HAZIR, SUB_PRESET_AYAR)
from studioflow.altyazi import gorunum
from studioflow.ayarlar import api_hesaplari, bicimler, proje_ayarlari
from studioflow.proje import (
    akis, akis_servis, calisma_kilidi, depo, on_ayarlar, sabitler, sahneleme, yonetim)
from studioflow.proje import karakterler as kadro
from studioflow.proje.dosya import proje_oku
from studioflow.proje.katmanlar import (
    diller, efektler, muzik as proje_muzik, ses_ciktisi, ses_ekleme)
from studioflow.saglayicilar import gorsel_cloudflare, metin_ortak, ses_edge
from studioflow.altyazi.kural import sub_rules
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.cekirdek.hatalar import ses_hatasi_temizle as clean_error
from studioflow.saglayicilar.ses_ortak import test_cumlesi
from studioflow.proje.sahne_stratejileri import (
    STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT, STRATEJI_TARIH, VARSAYILAN_STRATEJI,
    strateji_etiketi, strateji_normallestir)


def pj_altyazi_preset_degisti(ad):
    """Hazır altyazı ayarının **seviyesini** proje panelindeki kaydırıcıya yaz.

    Seviye hazır ayarın parçasıdır (bkz. `SUB_PRESET_AYAR`); şu an bütün hazır ayarlar
    aynı varsayılanı getirir (`gorunum.ALTYAZI_SEVIYE`), yani şablon seçmek yazıyı
    oynatmaz ama şablonun değeri kaydırıcıya her zaman yazılır. Kullanıcı kaydırıcıyı
    sonradan elle değiştirebilir; ayar `proje.txt`'e böyle yazılır.
    """
    _karakter, _satir, seviye = SUB_PRESET_AYAR.get(ad, SUB_PRESET_AYAR["yatay"])
    return seviye


def pj_ses_testi(provider, dil, edge_ses, gemini_ses, gemini_model, stil, hiz, ton, ref, exag,
                 cfg):
    """Proje sekmesindeki ses testi: proje ayarlarıyla dili ve sesi dener (kaydedilmez)."""
    ses = edge_ses if provider == "edge" else (gemini_ses if provider == "gemini" else "")
    for ses_yolu, _dosyalar, durum in ses_testi_akisi(
            provider, dil, test_cumlesi(dil), [ses], gemini_model, stil, hiz, ton, ref, exag, cfg):
        yield ses_yolu, durum


def pj_on_ayar_degisti(ad):
    """Proje ön ayarını alanlara uygula: tuval, altyazı, görsel ve video ayarları."""
    not_metni = on_ayarlar.proje_on_ayar_notu(ad)
    on_ayar = on_ayarlar.proje_on_ayari(ad)
    if not on_ayar:
        # Ön ayar temizlendi: görsel modeli değişmediği için negatif prompt alanı da
        # olduğu gibi kalır.
        return ([gr.update()] * 9 + [gr.update(value=not_metni)] + [gr.update(), gr.update()])
    gorsel = on_ayar["gorsel"]
    aralik = gorsel_cloudflare.cf_size_range(gorsel["model"])
    adim_alt, adim_ust, _adim_varsayilan = gorsel_cloudflare.cf_steps_range(gorsel["model"])
    guidance_alt, guidance_ust, _g = gorsel_cloudflare.cf_guidance_range(gorsel["model"])
    if aralik:
        genislik = gr.update(minimum=aralik[0], maximum=aralik[1], step=aralik[2],
                             value=gorsel["width"])
        yukseklik = gr.update(minimum=aralik[0], maximum=aralik[1], step=aralik[2],
                              value=gorsel["height"])
    else:
        genislik, yukseklik = gr.update(value=gorsel["width"]), gr.update(value=gorsel["height"])
    return [gr.update(value=on_ayar["bicim"]), gr.update(value=on_ayar["altyazi"]),
            gr.update(choices=gorsel_cloudflare.cf_model_choices(), value=gorsel["model"]),
            gr.update(minimum=adim_alt, maximum=adim_ust, value=gorsel["steps"]),
            gr.update(minimum=guidance_alt, maximum=guidance_ust, value=gorsel["guidance"]),
            genislik, yukseklik,
            gr.update(value=on_ayar["video_adim"]), gr.update(value=on_ayar["adim_saniye"]),
            gr.update(value=not_metni),
            *negatif_alan_gorunumu(gorsel["model"])]


def pj_bicim_degisti(bicim):
    """Çıktı biçimi değişince görsel boyutunu ve altyazı önerisini biçime uydur.

    Biçim üç şeyi birlikte belirler: **karenin oranı** (video Space'i klibin ölçüsünü
    karenin oranından türetir), **altyazı satır genişliği** ve **birleştirme tuvali**.
    Burada ilk ikisi uygulanır; tuval birleştirmede kullanılır.
    """
    genislik, yukseklik = bicimler.bicim_gorsel_boyutu(bicim)
    return (gr.update(value=genislik), gr.update(value=yukseklik),
            gr.update(value=bicimler.bicim_bilgisi(bicim)["preset"]))


def negatif_alan_gorunumu(model):
    """Negatif prompt alanını seçili görsel modelinin desteğine göre aç ya da kilitle."""
    if gorsel_cloudflare.supports_negative(model):
        return gr.update(interactive=True), gr.update(value="")
    return gr.update(interactive=False), gr.update(value=NEGATIF_DESTEK_YOK_NOT)


def ilk_negatif_gorunumu(model):
    """İlk sahne negatif alanı da negatif almayan modelde kilitlenir.

    İçerik silinmez: destekleyen modele dönülünce aynen kullanılır. Kilitli değilken
    FLUX'ta buraya yazılan "hands, fingers, visible face…" hiçbir işe yaramıyordu.
    """
    if gorsel_cloudflare.supports_negative(model):
        return gr.update(interactive=True, info="Projenin genel negatif prompt'uyla birleşir; "
                                                "tekrarlar atılır.")
    return gr.update(interactive=False, info="Bu görsel modeli negatif prompt desteklemiyor; "
                                             "alan kilitli. İstenmeyeni yazmak yerine ilk sahne "
                                             "içeriğinde doğrusunu tarif et.")


def pj_gorsel_model_degisti(model, bicim=None):
    """Model değişince adım, guidance ve boyutu modele (ve biçime) uydur."""
    if not model:
        return (gr.update(), gr.update(), gr.update(), gr.update(),
                *negatif_alan_gorunumu(model))
    adim, guidance, genislik, yukseklik, _not = gorsel_boyut_ayari(model, bicim)
    return (adim, guidance, genislik, yukseklik, *negatif_alan_gorunumu(model))


def pj_ses_servis_degisti(provider):
    """Ses servisi değişince yalnızca o servisin alanlarını göster."""
    return [gr.Group(visible=provider == ad) for ad in ("edge", "gemini", "chatterbox")]


def pj_dil_degisti(dil):
    sesler = ses_edge.VARSAYILAN.guvenli_sesler(dil)
    return gr.update(choices=sesler, value=sesler[0] if sesler else None)


def pj_ai_degisti(ai):
    modeller = metin_ortak.AI_SAGLAYICILAR.get(ai, {}).get("models") or []
    return gr.update(choices=modeller, value=modeller[0] if modeller else None)


def _ai_aciklama(ai):
    """"Seçili prompt yapay zekâsı: **<etiket>**" satırı (iki düğme takımı da aynısını yazar)."""
    bilgi = metin_ortak.AI_SAGLAYICILAR.get(ai, {})
    return f"Seçili prompt yapay zekâsı: **{bilgi.get('label', ai)}**"


def _ai_dugme_gorunumleri(ai):
    """Sağlayıcı sayısı kadar `gr.update`: seçili düğme vurgulu, diğerleri ikincil."""
    return tuple(gr.update(variant="primary" if ad == ai else "secondary")
                 for ad in metin_ortak.AI_SAGLAYICILAR)


def pj_prompt_ai_sec(ai):
    """Prompt yapay zekâsı düğmelerinin ortak seçili görünümünü güncelle.

    Strateji düğmeleriyle **aynı desen** (bkz. `pj_sahne_stratejisi_sec`): düğme
    yalnızca görünümü değil durumu da yazar, seçim başlatırken projeye uygulanır
    (`akis._hazirla`). Model listesi de seçilen servise göre tazelenir; model adları
    servisler arasında taşınamaz.

    Seçim **iki yerde** durur (içerik kartı ve üretim/durum kartı); ikisi de tek
    `pj_ai` durumunu besler, bu yüzden dönüş hem içerik hem üretim takımının
    görünümünü tazeler.

    Dönüş sırası: durum · model listesi · açıklama · görünümler · açıklama · görünümler.
    """
    ai = ai if ai in metin_ortak.AI_SAGLAYICILAR else metin_ortak.AI_VARSAYILAN
    # Düğme görünümleri **düz** döndürülür: Gradio'nun çıktı listesi sırayla
    # eşleşir, iç içe liste tek bir çıktı sayılır.
    return (
        ai,
        pj_ai_degisti(ai),
        _ai_aciklama(ai),
        *_ai_dugme_gorunumleri(ai),
        _ai_aciklama(ai),
        *_ai_dugme_gorunumleri(ai),
    )


def pj_sahne_stratejisi_sec(strateji):
    """Strateji düğmelerinin ortak seçili görünümünü güncelle."""
    strateji = strateji_normallestir(strateji)
    return (gr.update(value=strateji), *_strateji_dugmeleri(strateji),
            f"Seçili sahne planlama stratejisi: **{strateji_etiketi(strateji)}**")


def _strateji_dugmeleri(strateji):
    """Default · Tarih · Birinci kişi düğmelerinin görünümü: yalnızca seçili olan vurgulu."""
    return tuple(gr.update(variant="primary" if strateji == secenek else "secondary")
                 for secenek in (STRATEJI_DEFAULT, STRATEJI_TARIH, STRATEJI_BIRINCI_KISI))


def pj_sahne_planla(metin, ai_provider, ai_model, dil, hiz, tavan,
                    strateji=VARSAYILAN_STRATEJI, ad=""):
    """**🎬 Video sürelerini yapay zekâ ayarlasın**: sahne planını önizle.

    Anlatım cümlelere bölünür; yapay zekâ ardışık cümleleri sahnelere gruplar ve her
    sahneye **içeriğine/temposuna göre ayrı süre** verir (ör. 2 sn, 3,5 sn, 5 sn).

    Tavanı **kullanıcı seçer**: `tavan` kaydırıcıdan okunur ve yapay zekâya sınır
    olarak verilir. Düğme kaydırıcıya dokunmaz — eskiden plandaki en uzun sahneyi
    oraya yazıyordu ve kullanıcının seçtiği değeri (ör. 7 sn) eziyordu.

    Üreteçtir: düğmeye basıldığı **anda** durum satırı *çalışıyor*a döner, plan hazır
    olunca aynı alana rapor yazılır (bkz. `pj_sahne_not`). Ayrıca üretilen plan bir
    `State`e (`pj_sahne_on_plan`) **kaydedilir**: akış sahneyi ikinci bir istekle
    yeniden planlamaz, bu planı **aynen** kullanır. Böylece ana sayfada görünen sahne
    sayısı ile üretilen sahne sayısı aynı kalır.

    Her paket `(rapor, plan_kaydı)` çiftidir; plan yalnızca başarılı son pakette dolu
    olur (bkz. `sahneleme.plan_kaydi`).

    `ad` açık projeyse plan her basışta **projeye de yazılır** (bkz.
    `yonetim.sahne_planini_uygula`): eskiden yalnızca `State`te kalıyor, sahneleri kurulmuş
    projede hiç kullanılmıyordu.
    """
    metin = (metin or "").strip()
    strateji = strateji_normallestir(strateji)
    if not metin:
        yield "Önce videonun anlatım metnini yaz.", None
        return
    # İlk paket hemen gönderilir: Gradio üretecin ilk çıktısını beklemeden iletir,
    # böylece düğmeye basıldığı anda "çalışıyor" görünür.
    yield (f"⏳ **Çalışıyor…** {ai_model or ai_provider} anlatımı "
           f"**{strateji_etiketi(strateji)}** stratejisiyle sahnelere "
           "bölüp her sahneye kendi süresini veriyor; bitince rapor burada olacak.", None)
    alt, tavan_ust = sabitler.SAHNE_TAVAN_ARALIGI
    try:
        tavan = float(tavan)
    except (TypeError, ValueError):
        tavan = sabitler.ADIM_SANIYE
    tavan = max(alt, min(tavan_ust, tavan))
    sinirlar = (sabitler.SURE_SINIRLARI[0], tavan)
    anahtar = metin_ortak.ai_anahtari(ai_provider, api_hesaplari.VARSAYILAN.aktif_degerler(ai_provider))
    tahmin = sahneleme.tahmini_sure(metin, hiz)
    # Seçili servis kota/yetki hatası verirse yedek servis planı yazar; geçişler
    # aşağıda "Yapay zekâ geçişi" satırı olarak gösterilir.
    notlar = []
    try:
        plan = sahneleme.sahne_plani_detayli(
            ai_provider, anahtar, ai_model, metin, LANGUAGES.get(dil, dil),
            sinirlar, toplam_sure=tahmin, hiz=hiz, bildir=notlar.append,
            strateji=strateji)
    except Exception as exc:
        yield "Sahne planı çıkarılamadı: " + clean_error(exc, anahtar), None
        return
    adimlar = plan.get("adimlar") or []
    if not adimlar:
        yield "Sahne planı çıkarılamadı: anlatım sahnelere bölünemedi.", None
        return
    sureler = [float(a.get("saniye") or 0) for a in adimlar]
    kaynak = "yapay zekâ" if plan.get("kaynak") == "ai" else "içerik yedeği"
    satirlar = [
        f"✅ 🎬 **{len(adimlar)} sahne** · süreler **{min(sureler):g}–{max(sureler):g} sn** "
        f"(ortalama {sum(sureler) / len(sureler):g} sn) · anlatım tahmini {tahmin:g} sn "
        f"· kaynak: {kaynak}.",
        f"**{strateji_etiketi(strateji)}** stratejisi ve seçtiğin **{tavan:g} sn** tavanına uyuldu; "
        "kaydırıcı değişmedi. Sahne "
        f"süreleri anlatıma göre {sinirlar[0]:g} sn ile {tavan:g} sn arasında değişir.",
    ]
    for adim in adimlar[:10]:
        satirlar.append(f"- {float(adim.get('saniye') or 0):g} sn · "
                        f"{(adim.get('text') or '').strip()}")
    if len(adimlar) > 10:
        satirlar.append(f"- … ve {len(adimlar) - 10} sahne daha")
    if notlar:
        satirlar.append("Yapay zekâ geçişi: " + " · ".join(notlar))
    if plan.get("gerekce"):
        satirlar.append("Not: " + plan["gerekce"])
    # Süreler burada **tahmindir**; gerçek ses gelince tavanı aşan sahne ikiye bölünür
    # (claudetest4: sayfada 12, projede 14 sahne). Sınıra yakın sahneler önceden söylenir.
    sinirda = [i + 1 for i, s in enumerate(sureler) if s >= tavan * 0.85]
    if sinirda:
        satirlar.append(f"⚠️ Sahne {', '.join(map(str, sinirda))} tavana yakın; gerçek ses "
                        f"{tavan:g} sn'yi aşarsa o sahne virgül ya da cümle sınırından ikiye "
                        "bölünür ve projedeki sahne sayısı buradakinden fazla olur.")
    satirlar.append("Bu plan **kaydedildi**: proje başlarken yapay zekâya yeniden "
                    "sorulmaz, sahne sayısı ve gruplaması aynen bununla üretilir. Süreler "
                    "gerçek sesin kelime zamanlarına birebir hizalanır: her sahne kendi ilk "
                    "kelimesinin söylenmeye başladığı anda başlar ve sonraki sahneye kadar "
                    "sürer. Zamanlar ses dinlenerek (Cloudflare anahtarı varsa) ya da metinden "
                    "tahmin edilerek bulunur.")
    # Plan akışa bu kayıtla taşınır (bkz. `pj_sahne_on_plan`, `akis_sahne.sahne_plani_uret`).
    kayit = sahneleme.plan_kaydi(metin, strateji, adimlar, tavan)
    # Açık projeye de yazılır: her basış projenin sahnelerini yeniler.
    try:
        proje_notu = yonetim.sahne_planini_uygula(ad, kayit)
    except Exception as exc:
        proje_notu = "Plan projeye yazılamadı: " + clean_error(exc, anahtar)
    if proje_notu:
        satirlar.append("📁 " + proje_notu)
    yield "\n\n".join(satirlar), kayit


def _icerik_sayisi(deger):
    """Dosya/görsel listesinin eleman sayısı; tek değer geldiyse 1, boşsa 0."""
    if deger is None:
        return 0
    return len(deger) if isinstance(deger, (list, tuple)) else 1


def pj_panel_sayilari(dosyalar, gorseller):
    """Kapalı panellerin başlığını içerik sayısıyla güncelle.

    Panel kapalıyken de dolup dolmadığı anlaşılsın: başlıkta kaç dosya ve kaç
    görsel olduğu yazar. Paneller kendiliğinden açılmaz (sayfayı şişirmesinler).
    """
    return (gr.update(label=f"Proje dosyaları · {_icerik_sayisi(dosyalar)} dosya"),
            gr.update(label=f"Parça görselleri · {_icerik_sayisi(gorseller)} görsel"))


def pj_panel_doldur(liste, acik):
    """Dosya/görsel listesi değişince görünür bileşeni yalnızca panel açıksa doldur.

    Kapalı panelde bileşene dokunulmaz (`gr.skip`): dosyalar tarayıcıya gönderilmez,
    panel açılınca güncel liste yüklenir.
    """
    return liste if acik else gr.skip()


def _sn(deger):
    """Saniyeyi Türkçe ondalık ayraçla yaz: `12.5` → `12,5`."""
    return f"{float(deger):g}".replace(".", ",")


def sahne_etiketi(adim, toplam):
    """Sahne düğmesinin yazısı: `Adım 3/8 · TAMAM · 10–15 sn`."""
    return (f"Adım {adim['index']}/{toplam} · {adim['durum']} · "
            f"{_sn(adim['baslangic'])}–{_sn(adim['bitis'])} sn")


def pj_sahne_ac():
    """**Sahneleri incele**: listeyi tazele.

    Zaman damgası her basışta değişir; `gr.render` bloğu böylece listeyi yeniden
    çizer. Seçili adım da temizlenir: yeni liste geldiğinde silme onayı kapalı kalır.
    """
    return f"{time.strftime('%H:%M:%S')}", None


def pj_ilk_prompt_olcusu(metin):
    """İlk sahne prompt'unun uzunluk uyarısı: kaç kelimesi modele ulaşıyor?"""
    kelime = len([k for k in str(metin or "").split() if k.strip()])
    if not kelime:
        return ""
    sinir = sabitler.PROMPT_KELIME_SINIRI
    if kelime <= sinir:
        return f"≈{kelime} kelime · tamamı modele ulaşır."
    return (f"⚠️ ≈{kelime} kelime · görsel modeli yalnızca ilk **~{sinir} kelimeyi** "
            "okur, sonrası **yok sayılır**. En önemli öğeyi (özne, dönem, stil) "
            "**başa** yaz.")


def pj_gorsel_ac():
    """**Kareleri göster**: görsel listesini tazele (damga her basışta değişir)."""
    return f"{time.strftime('%H:%M:%S')}·{time.time():.3f}"


def calisirken_engelle(islem):
    """Bir proje çalışırken sahne/kare değişikliğini **hata uyarısıyla** reddet.

    Değişiklik yalnızca proje durdurulmuş ya da bitmişken yapılır: çalışan akış aynı
    `proje.txt`'e yazdığı için araya giren bir silme kaydı bozar. `gr.Error` açılır
    pencere olarak gösterilir ve hiçbir çıktıya yazılmaz; böylece çalışan projenin
    durum kutusu ve ilerleme paneli olduğu gibi kalır.
    """
    calisan = calisma_kilidi.calisan()
    if calisan:
        raise gr.Error(f"'{calisan}' projesi şu anda çalışıyor. {islem} yalnızca proje "
                       "durdurulduğunda ya da bittiğinde yapılabilir. Önce **⏹ Durdur**'a "
                       "bas; geçerli adım bitip proje durunca yeniden dene.",
                       title="Proje çalışıyor", print_exception=False)


def pj_ham_video_goster(ad):
    """Sonuç videosu değişince dublaj panelindeki özeti tazele.

    Ham video (`proje-ham.mp4`) birleştirmeden hemen sonra arka planda kurulur (bkz.
    `akis._ham_videoyu_kur`) ama ayrı bir panelde **gösterilmez**: ekrandaki tek video
    sonuç videosudur. Proje çalışırken özet yazılmaz: panel işlemleri o sırada
    reddedildiği için özet yerine "çalışıyor" uyarısı çıkardı; akış bitince yeniden
    tazelenir.
    """
    ad = (ad or "").strip()
    klasor = depo.guvenli_klasor(ad) if ad else None
    if klasor is None or calisma_kilidi.calisan():
        return gr.update()
    return diller.dil_listesi(ad)


def pj_gorsel_yenile(ad, index):
    """Adımın karesini kaldır ve yenisini üret; video onayı yeniden sorulur.

    `yonetim.gorsel_sil_yenile` üreteci arayüz çıktılarını (`pj_ciktilar`)
    olduğu gibi üretir; burada yalnızca bağlanır (bkz. `pj_sahne_yenile`).
    """
    calisirken_engelle("Kare yenileme")
    yield from yonetim.gorsel_sil_yenile(ad, index)


def _sahne_secilmedi():
    """Sağ paneldeki düğmeye sahne seçilmeden basıldı: uyar, çıktılara dokunma."""
    gr.Warning("Önce alttaki şeritten bir sahne seç.")
    return tuple(gr.skip() for _ in range(6))


def pj_secili_kare_yenile(ad, index):
    """Sağ panel · **Kareyi kaldır ve yenile**: seçili sahnenin karesi (`pj_gorsel_yenile`)."""
    if index in (None, ""):
        yield _sahne_secilmedi()
        return
    yield from pj_gorsel_yenile(ad, index)


def pj_secili_klip_yenile(ad, index):
    """Sağ panel · **Sil ve yeniden üret**: seçili sahnenin klibi (`pj_sahne_yenile`)."""
    if index in (None, ""):
        yield _sahne_secilmedi()
        return
    yield from pj_sahne_yenile(ad, index)


def pj_editor_sahne_sec(ad, index):
    """Şeritte sahneye tıklandı: sağ paneli o sahneyle doldur.

    Çıktılar: seçili sahne, kare, bilgi satırı, prompt düzenleyicinin sahne listesi
    (değeri seçili sahne; değişince prompt alanları `pj_prompt_secildi` ile dolar),
    düzenleyicinin görünürlüğü ve seçimi işaretlenmiş şerit.
    """
    index = str(index or "").strip() or None
    gorsel, bilgi = editor.sahne_detayi(ad, index)
    kayitlar = yonetim.sahne_prompt_listesi(ad) if index else []
    secenekler = [(f"Adım {k['index']} · {k['metin'] or 'Anlatım metni yok'}", str(k["index"]))
                  for k in kayitlar]
    deger = index if any(deger == index for _etiket, deger in secenekler) else None
    return (index, gorsel, bilgi, gr.update(choices=secenekler, value=deger),
            gr.update(visible=bool(secenekler)), editor.sahne_seridi_html(ad, index))


def pj_editor_proje_degisti(ad):
    """Başka proje açıldı: sahne seçimi sıfırlanır (eski projenin sahne numarası yeni
    projede yanlış sahneye uygulanmasın), sağ panel boşalır, şerit yeni projeyle çizilir."""
    gorsel, bilgi = editor.sahne_detayi(ad, None)
    return None, gorsel, bilgi, gr.update(visible=False), editor.sahne_seridi_html(ad, None)


def pj_editor_sahne_tazele(ad, index):
    """Sağ paneldeki kare ve bilgi satırını tazele (kare/klip yenilendikten sonra)."""
    return editor.sahne_detayi(ad, index)


def pj_serit_tazele(ad, index):
    """Alttaki sahne şeridini tazele (proje açılınca ve üretim ilerledikçe)."""
    return editor.sahne_seridi_html(ad, index)


def pj_izler_tazele(ad):
    """Alttaki ses/altyazı izlerini tazele (kayıt ya da video değişince)."""
    return editor.izler_html(ad)


def pj_sahne_yenile(ad, index):
    """Adımı sil, **yalnızca o adımı** yeniden üret ve videoyu yeniden birleştir.

    `yonetim.sahne_sil_yenile` üretecidir; paketleri arayüz çıktılarına
    aktarır. Bu işlev bilinçli olarak gerçek bir üreteçtir (`yield from`): Gradio
    `lambda` ile dönen üreteç nesnesini üreteç saymaz, tek çıktı sanır. Silme bitince
    liste `.then` ile tazelenir (bkz. `_pj_sahne_satirlari`).
    """
    calisirken_engelle("Sahne silme ve yeniden üretme")
    yield from yonetim.sahne_sil_yenile(ad, index)


def pj_prompt_listele(ad):
    """Prompt paneline sahne seçeneklerini ve ilk promptu yükle."""
    kayitlar = yonetim.sahne_prompt_listesi(ad)
    secenekler = [(f"Adım {k['index']} · {k['metin'] or 'Anlatım metni yok'}", str(k["index"]))
                  for k in kayitlar]
    if not kayitlar:
        return (gr.update(choices=[], value=None), "", "", "Listelenecek sahne promptu yok.",
                gr.update(visible=True))
    ilk = kayitlar[0]
    return (gr.update(choices=secenekler, value=str(ilk["index"])),
            ilk["image_prompt"], ilk["negative_prompt"],
            f"**{len(kayitlar)} sahne** yüklendi. Düzenlemek istediğin sahneyi seç.",
            gr.update(visible=True))


def pj_prompt_secildi(ad, index):
    """Seçilen sahnenin prompt alanlarını doldur."""
    kayitlar = yonetim.sahne_prompt_listesi(ad)
    secilen = next((k for k in kayitlar if str(k["index"]) == str(index)), None)
    if secilen is None:
        return "", "", "Sahne seçilmedi."
    return (secilen["image_prompt"], secilen["negative_prompt"],
            f"**Adım {secilen['index']}** · prompt düzenlenebilir.")


def pj_sahne_prompt_onayla(ad, index, image_prompt, negative_prompt):
    """Seçilen promptu kaydet ve yalnızca o sahnenin karesini yenile."""
    calisirken_engelle("Sahne promptu değiştirme")
    yield from yonetim.sahne_prompt_uygula(ad, index, image_prompt, negative_prompt)


def pj_muzik_dosya_degisti(dosya):
    """Müzik yüklendi: kırpma kaydırıcılarını dosyanın **gerçek süresine** göre kur.

    Sınır dosyanın süresidir (bittiği yerin ötesini kırpmak anlamsız olurdu). Süre
    okunamazsa varsayılan sınıra dönülür; `muzik_kaydet` kırpmayı yine de güvenle
    uygular (kırpma süresi bilinmiyorsa baştan sona alınır).
    """
    sure, not_metni = proje_muzik.muzik_suresi(dosya)
    varsayilan = sabitler.MUZIK_VARSAYILAN_SINIR
    if sure <= 0:
        return (gr.update(maximum=varsayilan, value=0),
                gr.update(maximum=varsayilan, value=0), not_metni)
    ust = max(1.0, round(sure + 0.5, 1))
    return (gr.update(maximum=ust, value=0), gr.update(maximum=ust, value=ust), not_metni)


def pj_muzik_isaret(ad, isim):
    """Bir müziğin kutusu değişti: **işaretleme sırasını** güncelle ve projeye yaz.

    Sıra, videoya ekleme sırasıdır: işaretlenen müzik listenin sonuna eklenir, işaret
    kaldırılırsa çıkar. Sıra projeye yazılır (`muzik/parcalar.json`), böylece başka
    bir projeye geçip dönmek işaretleri kaybettirmez.
    """
    def uygula(isaretli, secili):
        siralar = [str(ad_gecen) for ad_gecen in (secili or []) if str(ad_gecen) != isim]
        if isaretli:
            siralar.append(isim)
        proje_muzik.muzik_secimini_yaz(ad, siralar)
        return siralar
    return uygula


def pj_panel_bos(dil_listesi="", muzik=None, dublaj_secim="", altyazi_secim=""):
    """Projeye özel panel alanlarının boş hâli (sıra: `pj_panel_alanlari`).

    Sıra: sahne planı notu, ses testi (ses + durum), dublaj bölümü (ses, dosyalar,
    durum, kayıt özeti), müzik paneli (durum, tekrarla, ducking, liste damgası,
    işaretleme sırası), dublaj listesi (damga, seçim), altyazı paneli (durum,
    dosyalar, damga, seçim), üretim sayfasındaki üç ekleme panelinin durumu ve
    görsel düzenleme listesinin damgası.
    `dil_listesi`, `muzik` ve seçimler bir proje açılırken o projenin kaydından
    doldurulur; proje yokken hepsi boş kalır.
    """
    muzik = muzik or {}
    return ("", None, "Hazır.", None, [], PJ_COK_HAZIR, dil_listesi,
            PJ_MUZIK_HAZIR, bool(muzik.get("tekrarla")),
            # Ducking yazmayan kayıtta (ve proje yokken) varsayılan açıktır.
            sabitler.MUZIK_VARSAYILAN_DUCKING if muzik.get("ducking") is None
            else bool(muzik.get("ducking")), "",
            [str(x) for x in (muzik.get("secim") or [])],
            # Dublaj ve altyazı listeleri: damga boş (liste projeden tazelenir),
            # seçim kayıttan gelir.
            "", str(dublaj_secim or ""),
            PJ_ALTYAZI_HAZIR, [], "", str(altyazi_secim or ""),
            PJ_UR_DUBLAJ_HAZIR, PJ_UR_MUZIK_HAZIR, PJ_UR_ALTYAZI_HAZIR,
            # Görsel düzenleme listesi kapalı başlar: yeni projede eski kareler durmasın.
            "")


def pj_panel_projeden(ad):
    """Bir proje açılınca panel alanlarına yazılacak değerler.

    Müzik, dublaj ve altyazı panelleri projeden gelir: müziklerin **işaretleme
    sırası**, **tekrarla** ve **ducking** tercihi ile dublaj/altyazı **seçimleri**
    projenin kendi kayıtlarında durur (bkz. `muzik.muzik_durumu`,
    `dublaj_secimi`, `altyazi_secimi`).
    """
    def _dene(islev, varsayilan=""):
        try:
            return islev(ad)
        except Exception:
            return varsayilan

    muzik = _dene(proje_muzik.muzik_durumu, None)
    return pj_panel_bos(_dene(diller.dil_listesi), muzik,
                        _dene(diller.dublaj_secimi),
                        _dene(diller.altyazi_secimi))


def pj_yeni_panel_ac():
    """**＋ Yeni proje oluştur**: küçük ad panelini aç ve alanı temizle."""
    return gr.update(visible=True), gr.update(value=""), ""


def pj_yeni_panel_kapat():
    """Ad panelindeki **İptal**: paneli kapat, alanı temizle."""
    return gr.update(visible=False), gr.update(value=""), ""


def katman_rozeti_html(katmanlar):
    """Önizlemenin üstündeki katman satırı: `[(etiket, videoda mı), ...]`.

    `None` → video henüz yok. Videoda olan katman işaretli, olmayan soluk yazılır.
    """
    if not katmanlar:
        return ('<div class="sf-katmanlar"><span class="sf-katman bos">'
                "Video henüz üretilmedi</span></div>")
    rozetler = "".join(
        f'<span class="sf-katman{" var" if var else ""}">{"✓" if var else "–"} '
        f"{escape(etiket)}</span>" for etiket, var in katmanlar)
    return f'<div class="sf-katmanlar">{rozetler}</div>'


def pj_katmanlar(ad, video, mod=None):
    """Sonuç videosunda hangi katmanların olduğunu `proje.txt`'ten oku.

    Yalnızca okur; proje çalışırken de güvenlidir (ekleme işlemleri engellenir, bu
    değil). Video yoksa ya da proje okunamazsa "henüz yok" satırı döner. **Ses**
    modunda videonun değil ses modunun katmanları gösterilir (bkz. `ses_ciktisi`).
    """
    if mod == CIKTI_SES:
        return katman_rozeti_html(ses_ciktisi.ses_katmanlari(ad)
                                  if (ad or "").strip() else None)
    klasor = depo.guvenli_klasor(ad) if (ad or "").strip() and video else None
    veri = proje_oku(klasor) if klasor else None
    if veri is None:
        return katman_rozeti_html(None)
    dublaj = (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()
    return katman_rozeti_html([
        ("Seslendirme", veri.get("ses_ekleme") == "TAMAM" and not dublaj),
        ("Dublaj" + (f" · {dublaj}" if dublaj else ""), bool(dublaj)),
        ("Altyazı", veri.get("altyazi_ekleme") == "TAMAM"),
        ("Müzik", veri.get("muzik_ekleme") == "TAMAM" and bool(veri.get("muzikler"))),
        ("Ses efekti", efektler.ekli_efekt(klasor)[0] is not None),
    ])


# Önizlemenin üstündeki **Video | Ses** anahtarının değerleri.
CIKTI_VIDEO, CIKTI_SES = "video", "ses"
CIKTI_MODLARI = [("🎬 Video", CIKTI_VIDEO), ("♪ Ses", CIKTI_SES)]


def pj_modlu(video_islevi, ses_islevi):
    """Bir ekleme düğmesini anahtara bağla: **Video**'da videoya ekler, **Ses**'te
    katmanı ses moduna yazar (bkz. `ses_ciktisi`). Çıktı = düğmenin eski paketi +
    ses önizlemesi + katman rozetleri; Video modunda ikisine dokunulmaz (rozetler
    video değişince zaten tazelenir). İlk girdi her zaman proje adıdır.
    """
    def islev(mod, *girdiler):
        if mod == CIKTI_SES:
            paket, dosya = ses_islevi(*girdiler)
            return (*paket, dosya, pj_katmanlar(girdiler[0], None, CIKTI_SES))
        return (*video_islevi(*girdiler), gr.update(), gr.update())
    return islev


def pj_ses_dosyasi_indir(ad):
    """**Sesi indir**: ses modunun güncel dosyası; indirmeyi tarayıcı başlatır."""
    dosya = ses_ciktisi.son_ses_dosyasi(ad)
    if not dosya:
        gr.Warning("Henüz ses dosyası yok: önce seslendirmeyi ya da bir dublajı ekle.")
    return dosya


def pj_cikti_modu_degisti(mod, ad, video):
    """Anahtar değişince önizleme, düğmeler ve katman rozetleri moda göre değişir.

    Sıra: video · ses önizlemesi · altyazı düğmesi · ham videoya dön (Ses'te sesi
    sıfırla) · sesi ekle · dublaj ekle · müzik ekle · müzik kaldır · sesi indir ·
    katman rozetleri.
    """
    ses = mod == CIKTI_SES
    return (gr.update(visible=not ses),
            gr.update(visible=ses, value=ses_ciktisi.son_ses_dosyasi(ad) if ses else None),
            gr.update(visible=not ses),
            gr.update(value="↺ Sesi sıfırla" if ses else "↺ Ham videoya geri dön"),
            gr.update(value="Seslendirmeyi ekle" if ses else "Sesi videoya ekle"),
            gr.update(value="Seçili dublajı ekle" if ses else "Seçili dublajı videoya ekle"),
            gr.update(value="Müziği ekle" if ses else "Videoya ekle"),
            gr.update(value="Müziği kaldır"),
            gr.update(visible=ses),
            pj_katmanlar(ad, video, mod))


def pj_sesi_indir(ad, video):
    """Video araç çubuğundaki ♪ düğmesi: sonuç videosunun sesini görüntüsüz MP3 yap.

    Anlatım/dublaj, müzik ve ses efektleri videoya tek iz olarak karıştırılır; o iz
    olduğu gibi alınır. Dosya `.calisma/ses-indir/<proje>-ses.mp3` olarak yazılır,
    indirmeyi tarayıcı başlatır (bkz. `sayfa_proje`). Döner: dosya yolu ya da None.
    """
    klasor = depo.guvenli_klasor(ad) if (ad or "").strip() else None
    if klasor is None or not video or not Path(video).is_file():
        gr.Warning("Önce sonuç videosu olan bir proje aç.")
        return None
    if not FFMPEG.ffmpeg():
        gr.Warning("ffmpeg bulunamadı; ses çıkarılamadı.")
        return None
    hedef = klasor / depo.CALISMA_KLASORU / "ses-indir" / f"{klasor.name}-ses.mp3"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    ok, mesaj = FFMPEG.calistir([
        FFMPEG.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(hedef)])
    if not ok:
        gr.Warning("Ses çıkarılamadı (videoda ses izi olmayabilir): " + mesaj)
        return None
    return str(hedef)


def pj_sil_uyarisi(ad):
    """**Sil** düğmesi: onay kutusu yerine küçük uyarı panelini aç.

    Hedef proje `pj_sil_hedef` durumunda tutulur; silme yalnızca **Onayla**'ya
    basılınca yapılır (`pj_sil_onayla`), **İptal** paneli kapatır.
    """
    if not (ad or "").strip():
        return "", "", gr.update(visible=False)
    return (ad, f"### Projeyi sil\n**{ad}** kalıcı olarak silinecek.",
            gr.update(visible=True))


def pj_sil_onayla(ad):
    """Uyarı panelindeki **Onayla**: projeyi sil ve listeyi tazele."""
    mesaj = yonetim.sil(ad) if (ad or "").strip() else "Silinecek proje yok."
    return mesaj, gr.update(visible=False), depo.liste(), "", ""


def pj_sil_iptal():
    """Uyarı panelindeki **İptal**: paneli kapat, hedefi temizle."""
    return gr.update(visible=False), "", ""


def pj_secime_don():
    """Çalışma panelini gizle, proje listesine dön.

    Liste diskten tazelenir: akış sırasında kurulan yeni proje (ya da dışarıdan
    eklenen klasör) böylece panelde görünür.
    """
    return (gr.update(visible=True), gr.update(visible=False), gr.update(value=""),
            gr.update(value=""), depo.liste())


# Ayarların tek kaynağı: hem projeyi çalıştıran akış hem "Ayarları kaydet" bu sözlüğü
# kullanır, böylece arayüz ile kaydedilen dosya asla ayrışmaz.
def _altyazi_sozlugu(acik, preset, font, renk, kalin, seviye=None):
    """Altyazı ayarlarını tek sözlükte topla (tek kaynak).

    Hazır ayar blok ölçülerini (karakter/satır) ve **seviyeyi** (yazının alttan
    yüksekliği, tuval yüksekliğinin yüzdesi) belirler; görünüm (yazı tipi, renk,
    kalınlık) ayrıca taşınır. `seviye` verilmezse hazır ayarın kendi seviyesi kullanılır.
    Proje akışı **ve** arayüzdeki önizleme bu sözlüğü kullanır, böylece önizleme ile
    videoya gömülen altyazı ayrışmaz.
    """
    karakter, satir, hazir_seviye = SUB_PRESET_AYAR.get(preset, SUB_PRESET_AYAR["yatay"])
    return {"acik": bool(acik), "preset": preset, "font": font, "renk": renk,
            "kalin": bool(kalin),
            "seviye": gorunum.altyazi_seviye(seviye, hazir_seviye),
            "ayar": sub_rules(line_chars=karakter, max_lines=satir)}


def pj_altyazi_yeniden(ad, altyazi, preset, font, renk, kalin, seviye):
    """Videodaki altyazıyı paneldeki güncel ayarlarla baştan oluştur.

    Ayarlar önce projeye yazılır (gömme `proje.txt`'ten okunur), sonra eski gömme
    kaldırılıp altyazı yeniden gömülür (bkz. `videoya_altyazi_yeniden`).
    """
    return ses_ekleme.videoya_altyazi_yeniden(
        ad, _altyazi_sozlugu(altyazi, preset, font, renk, kalin, seviye))


def pj_altyazi_onizleme(bicim, font, renk, kalin, seviye, preset, zemin):
    """Altyazı görünümünü küçük bir karede göster.

    Kare, seçili **Hedef biçim**in tuvalinde, hazır ayarın satır sınırlarıyla ve
    **seviyeyle** üretilir; gömme yoluyla aynı stil kullanıldığı için yazı tipi, renk,
    kalınlık ve konum videoya gömülecek hâliyle aynı görünür (bkz. `altyazi_onizleme`).
    `zemin` yalnızca önizlemenin arka planını seçer, gömülen videoya karışmaz.
    """
    return gorunum.altyazi_onizleme(
        bicim, _altyazi_sozlugu(True, preset, font, renk, kalin, seviye), zemin)


def pj_ayar_sozlugu(ses_provider, dil, edge_ses, hiz, ton, gemini_model, gemini_ses, stil,
                    ref, exag, cfg, altyazi, altyazi_preset, altyazi_font, altyazi_renk,
                    altyazi_kalin, altyazi_seviye, gorsel_model,
                    genislik, yukseklik, adim, guidance, negatif,
                    video_adim, adim_saniye, ai, ai_model, gorsel_stil, genel_prompt,
                    cikti_bicim, on_ayar, sahne_stratejisi=VARSAYILAN_STRATEJI,
                    ilk_prompt="", ilk_negatif="",
                    ses_seviye=sabitler.SES_VARSAYILAN_SEVIYE, karakterler=None):
    """Proje sekmesinin ayar sözlüğünü kur (proje.txt AYARLAR bölümüyle aynı yapı).

    `karakterler`: 👥 Karakterler panelinde kaydedilen kadro (`pj_kadro` listesi).
    """
    return {
        "ses": {"provider": ses_provider, "dil": dil, "edge_ses": edge_ses, "hiz": hiz,
                "ton": ton, "seviye": ses_seviye, "gemini_model": gemini_model,
                "gemini_ses": gemini_ses, "stil": stil, "ref": ref, "exag": exag, "cfg": cfg},
        "altyazi": _altyazi_sozlugu(altyazi, altyazi_preset, altyazi_font, altyazi_renk,
                                    altyazi_kalin, altyazi_seviye),
        "gorsel": {"provider": gorsel_cloudflare.VARSAYILAN_SAGLAYICI, "model": gorsel_model,
                   "width": genislik, "height": yukseklik, "steps": adim,
                   "guidance": guidance, "negatif": negatif},
        "video": {"adim": video_adim, "adim_saniye": adim_saniye, "ai": ai,
                  "model": ai_model, "stil": gorsel_stil,
                  "genel": genel_prompt,
                  "sahne_stratejisi": strateji_normallestir(sahne_stratejisi),
                  # Hedef platform + tuval: görsel oranını, altyazı önerisini ve
                  # birleştirme tuvalini birlikte belirler (proje.txt'e yazılır).
                  "bicim": cikti_bicim,
                  # Seçili ön ayar: alanların kendisi ayrıca kaydedildiği için bu değer
                  # yalnızca listenin hangi kurulumu gösterdiğidir (açılışta geri gelir).
                  "on_ayar": on_ayar,
                  # İlk sahne (kanca karesi) için kullanıcının yazdığı içerik ve
                  # negatif; ikisi de boşsa 1. sahneyi tamamen yapay zekâ yazar.
                  # Görsel stil burada yoktur: 1. sahne de `stil` alanını kullanır.
                  "ilk_prompt": ilk_prompt, "ilk_negatif": ilk_negatif,
                  # Karakter kadrosu: proje içeriğidir, genel ayar dosyasına yazılmaz.
                  "karakterler": kadro.normalize(karakterler or [])},
    }


def pj_baslat(ad, metin, ses_provider, dil, edge_ses, hiz, ton, gemini_model, gemini_ses, stil,
              ref, exag, cfg, altyazi, altyazi_preset, altyazi_font, altyazi_renk,
              altyazi_kalin, altyazi_seviye, gorsel_model, genislik,
              yukseklik, adim, guidance, negatif, video_adim, adim_saniye,
              ai, ai_model, gorsel_stil, genel_prompt, cikti_bicim, on_ayar,
              sahne_stratejisi=VARSAYILAN_STRATEJI, ilk_prompt="", ilk_negatif="",
              ses_seviye=sabitler.SES_VARSAYILAN_SEVIYE, karakterler=None, sahne_on_plan=None):
    """Proje sekmesinin ayarlarını topla ve proje akışını çalıştır.

    `karakterler`: kaydedilen kadro (`pj_kadro`). `sahne_on_plan` ana sayfada (🎬
    düğmesiyle) üretilen plandır; akış onu **aynen** kullanır, sahneyi yeniden
    planlamaz (bkz. `sahneleme.plan_sahneleri`).
    """
    ayarlar = pj_ayar_sozlugu(
        ses_provider, dil, edge_ses, hiz, ton, gemini_model, gemini_ses, stil, ref, exag, cfg,
        altyazi, altyazi_preset, altyazi_font, altyazi_renk, altyazi_kalin, altyazi_seviye,
        gorsel_model, genislik, yukseklik, adim,
        guidance, negatif, video_adim, adim_saniye, ai, ai_model,
        gorsel_stil, genel_prompt, cikti_bicim, on_ayar,
        sahne_stratejisi, ilk_prompt, ilk_negatif, ses_seviye, karakterler)
    yield from akis.proje_calistir(ad, metin, ayarlar, sahne_on_plan)


def pj_gorsel_onay_ltx(ad):
    """**Onayla · LTX-2.3 ile videoları üret**: seçim projeye yazılır (`Video servisi`),
    **Kaldığı yerden devam** da LTX ile sürer. Hazır sahne videoları korunur.
    """
    yield from yonetim.gorsel_onayi_ver(ad, akis_servis.VIDEO_LTX)


def pj_gorsel_onay_agnes(ad):
    """**Onayla · Agnes AI 2.5 Flash ile videoları üret**: seçim projeye yazılır
    (`Video servisi`), **Kaldığı yerden devam** da Agnes ile sürer. Hazır sahne videoları
    korunur; üretim ilk eksik sahneden sürer.
    """
    yield from yonetim.gorsel_onayi_ver(ad, akis_servis.VIDEO_AGNES)


def _secili(deger, secenekler, varsayilan=None):
    """(etiket, değer) listesinde varsa değeri, yoksa ilkini döndür."""
    for _etiket, anahtar in secenekler:
        if anahtar == deger:
            return deger
    return secenekler[0][1] if secenekler else varsayilan


def _secili_metin(deger, secenekler):
    return deger if deger in secenekler else (secenekler[0] if secenekler else None)


def pj_karakter_kaydet(kadro_, ad, tarif, gorsel):
    """**Karakteri kaydet**: düzenleme kartındaki karakteri kadroya yaz, kartı boşalt.

    Dönüş: kadro, ad, tarif, görsel ve not. Aynı adlı karakter varsa güncellenir; hata
    olursa kadro ve kart olduğu gibi kalır, not sebebi yazar.
    """
    yeni, hata = kadro.kadroya_ekle(kadro_, ad, tarif, gorsel)
    if hata:
        return yeni, gr.update(), gr.update(), gr.update(), hata
    ad = " ".join(str(ad).split())
    guncellendi = len(yeni) == len(kadro.normalize(kadro_))
    return (yeni, "", "", None,
            f"**{ad}** {'güncellendi' if guncellendi else 'kaydedildi'} · kadroda "
            f"{len(yeni)} karakter. Düzenlemek için listede adına tıkla.")


def pj_karakter_duzenle(kadro_, ad):
    """Listede karaktere tıklandı: karakteri düzenleme kartına getir."""
    karakter = next((k for k in kadro.normalize(kadro_) if k["ad"] == ad), None)
    if karakter is None:
        return gr.update(), gr.update(), gr.update(), f"**{ad}** kadroda bulunamadı."
    # Görsel alanına boş metin verilmez (Gradio onu yol sanar); dosya yoksa None.
    gorsel = karakter["gorsel"]
    return (karakter["ad"], karakter["tarif"],
            gorsel if gorsel and Path(gorsel).is_file() else None,
            f"**{ad}** düzenleniyor: değiştirip **Karakteri kaydet**'e bas.")


def pj_karakter_sil(kadro_, ad):
    """Listedeki 🗑 düğmesi: karakteri kadrodan çıkar."""
    yeni = kadro.kadrodan_sil(kadro_, ad)
    return yeni, f"**{ad}** kadrodan çıkarıldı · kadroda {len(yeni)} karakter."


# Karakter panelinin başlık çubuğu: kapalıyken ▾, açıkken ▴.
KARAKTER_DUGMESI = {False: "👥  Karakterler · tek ya da çok karakterli senaryo   ▾",
                    True: "👥  Karakterler · tek ya da çok karakterli senaryo   ▴"}


def pj_karakter_paneli(acik):
    """👥 Karakterler düğmesi: paneli aç ya da kapat; düğmenin oku durumu gösterir."""
    acik = not bool(acik)
    return acik, gr.update(visible=acik), gr.update(value=KARAKTER_DUGMESI[acik])


def pj_karakter_referans_uret(ad, tarif, gorsel_stil, model):
    """Düzenleme kartındaki karakterin referans görselini tariften üret (projenin stili ve modeliyle).

    Referans almayan model seçiliyse FLUX.2 klein 4B ile üretilir: karakterli proje
    zaten o modelle çalışır, referans da aynı modelin elinden çıksın.
    """
    ad, tarif = (ad or "").strip(), (tarif or "").strip()
    if not ad or not tarif:
        return gr.update(), "Önce karakterin **adını** ve **tarifini** yaz."
    model = model if gorsel_cloudflare.referans_siniri(model) else islevler_karakter.MODEL_VARSAYILAN
    stil = " ".join(str(gorsel_stil or "").split())
    prompt = (f"Full-body front view character reference of {ad}, {tarif}. Standing, arms "
              "relaxed at sides, neutral expression, centered, the whole body visible from "
              "head to feet, plain pure white background, no other objects, no text."
              + (f" Style: {stil}." if stil else ""))
    islevler_karakter.KARAKTER_IPTAL.clear()
    yol, durum = islevler_karakter.tek_gorsel(prompt, model, *islevler_karakter.REFERANS_BOYUT)
    if not yol:
        return gr.update(), f"**{ad}** için referans üretilemedi: {durum}"
    return yol, (f"**{ad}** için referans hazır. Beğenmediysen yeniden üret ya da kendi "
                 "görselini bırak.")


def pj_ayar_uygula(ayarlar, kadroyu_yaz=True):
    """Ayar sözlüğünü `pj_ayar_alanlari` sırasına göre arayüz güncellemelerine çevir.

    `kadroyu_yaz=False`: kadroya dokunulmaz (genel ayar dosyası yüklenirken; kadro proje
    içeriğidir).
    """
    ses, altyazi = ayarlar["ses"], ayarlar["altyazi"]
    gorsel, video = ayarlar["gorsel"], ayarlar["video"]
    dil = ses["dil"] if ses["dil"] in LANGUAGES else "tr"
    preset = altyazi["preset"] if altyazi["preset"] in SUB_PRESET_AYAR else "yatay"
    ai = (video["ai"] if video["ai"] in metin_ortak.AI_SAGLAYICILAR
          else metin_ortak.AI_VARSAYILAN)
    ai_modeller = metin_ortak.AI_SAGLAYICILAR[ai]["models"]
    sesler = ses_edge.VARSAYILAN.guvenli_sesler(dil)
    # Cloudflare model listesi sabittir (ağ çağrısı yapmaz), yükleme bu yüzden hızlıdır.
    modeller = gorsel_cloudflare.cf_model_choices()
    return [
        gr.update(value=ses["provider"]),
        gr.update(value=dil),
        gr.update(choices=sesler, value=_secili_metin(ses["edge_ses"], sesler)),
        gr.update(value=ses["hiz"]),
        gr.update(value=ses["ton"]),
        gr.update(value=ses["gemini_model"]),
        gr.update(value=ses["gemini_ses"]),
        gr.update(value=ses["stil"]),
        # Audio alanına **boş metin verilmez**: Gradio boş yolu çalışma klasörü sayar,
        # onu cache'e kopyalamaya çalışır ve `PermissionError` verir (boş `value` yol
        # gibi işleniyor). Referans ses yoksa alan `None` ile boşaltılır.
        gr.update(value=ses["ref"] or None),
        gr.update(value=ses["exag"]),
        gr.update(value=ses["cfg"]),
        gr.update(value=altyazi["acik"]),
        gr.update(value=preset),
        gr.update(value=altyazi["font"]),
        gr.update(value=altyazi["renk"]),
        gr.update(value=altyazi["kalin"]),
        gr.update(value=altyazi["seviye"]),
        gr.update(choices=modeller, value=_secili(gorsel["model"], modeller)),
        gr.update(value=gorsel["width"]),
        gr.update(value=gorsel["height"]),
        gr.update(value=gorsel["steps"]),
        gr.update(value=gorsel["guidance"]),
        # Negatif prompt alanı yalnızca destekleyen modelde açık kalır.
        gr.update(value=gorsel["negatif"],
                  interactive=gorsel_cloudflare.supports_negative(gorsel["model"])),
        gr.update(value=video["adim"]),
        gr.update(value=video["adim_saniye"]),
        # Prompt yapay zekâsı bir `gr.State`tir: State çıktısı `gr.update` ile değil
        # **değerin kendisiyle** yazılır.
        ai,
        gr.update(choices=ai_modeller,
                  value=video["model"] or (ai_modeller[0] if ai_modeller else None)),
        gr.update(value=video["stil"]),
        gr.update(value=video["genel"]),
        gr.update(value=video.get("bicim") or bicimler.VARSAYILAN_BICIM),
        # Ön ayar seçimi de kayıttan gelir; satır yoksa (eski kayıt ya da `proje.txt`)
        # liste "— elle ayarla —" gösterir: yanlış bir kurulum seçili görünmez.
        gr.update(value=video.get("on_ayar") or ""),
        # Sahne planlama stratejisi: eski projelerde tarih varsayılanı gösterilir.
        gr.update(value=strateji_normallestir(video.get("sahne_stratejisi"))),
        # İlk sahne alanları: `pj_ayar_alanlari` sırasında ön ayardan hemen sonra.
        gr.update(value=video.get("ilk_prompt") or ""),
        gr.update(value=video.get("ilk_negatif") or ""),
        # Seslendirme seviyesi: `pj_ayar_alanlari` sırasının sonunda.
        gr.update(value=ses.get("seviye", sabitler.SES_VARSAYILAN_SEVIYE)),
        # Kadro (`pj_kadro` State'i): `pj_ayar_alanlari` sırasının en sonunda. State
        # değerin kendisiyle yazılır; boş `gr.update()` State'e dokunmaz.
        (kadro.normalize(video.get("karakterler")) if kadroyu_yaz else gr.update()),
        # Strateji düğmeleri ve açıklaması.
        *_strateji_dugmeleri(strateji_normallestir(video.get("sahne_stratejisi"))),
        gr.update(value=f"Seçili sahne planlama stratejisi: **{strateji_etiketi(video.get('sahne_stratejisi'))}**"),
        gr.Group(visible=ses["provider"] == "edge"),
        gr.Group(visible=ses["provider"] == "gemini"),
        gr.Group(visible=ses["provider"] == "chatterbox"),
        gr.update(value="" if gorsel_cloudflare.supports_negative(gorsel["model"])
                  else NEGATIF_DESTEK_YOK_NOT),
        # Prompt yapay zekâsı düğmeleri: seçili olan vurgulu gelir (strateji düğmeleri
        # gibi). İki takım da (içerik + üretim/durum kartı) aynı seçimi gösterir.
        gr.update(value=_ai_aciklama(ai)),
        *_ai_dugme_gorunumleri(ai),
        gr.update(value=_ai_aciklama(ai)),
        *_ai_dugme_gorunumleri(ai),
    ]


def pj_ayarlari_kaydet(*degerler):
    """Proje sekmesinin geçerli ayarlarını genel ayar dosyasına kaydet."""
    try:
        yazilan = proje_ayarlari.VARSAYILAN.kaydet(pj_ayar_sozlugu(*degerler))
    except Exception as exc:
        return "Ayarlar kaydedilemedi: " + str(exc)[:300]
    return "Ayarlar kaydedildi ve bundan sonra açılışta kendiliğinden yüklenecek.\n" \
           + proje_ayarlari.VARSAYILAN.ozet(yazilan)


def pj_ayarlari_sil():
    """Kayıtlı ayarları sil; arayüzdeki değerler olduğu gibi kalır."""
    proje_ayarlari.VARSAYILAN.sil()
    return ("Kayıtlı ayarlar silindi; ekrandaki değerler değişmedi.\n" + proje_ayarlari.VARSAYILAN.ozet())
