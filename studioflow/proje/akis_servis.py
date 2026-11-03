"""Projenin üretim servisleri: ses, görsel ve video üreticilerinin proje ayarlarıyla
çağrılması ve sonuçlarının denetimi. Akış (`akis`) bu işlevleri adım adım kullanır.
"""
from studioflow.cekirdek.metin import negatif_birlestir, negatif_celiski_ayikla, negatif_duzenle
from studioflow.proje.calisma_kilidi import IPTAL
from studioflow.proje import karakterler as kadro
from studioflow.proje.depo import adim_suresi, calisma_klasoru, proje_adim_saniyesi, proje_klasoru
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.sabitler import NEGATIF_ONCELIK
from studioflow.saglayicilar import (gorsel_cloudflare, ses_uretim, video_agnes,
                                     video_huggingface, video_ltx)
from studioflow.saglayicilar.hesap_havuzu import aktif_anahtar


def ses_uretici(veri, kimlik):
    ses = veri["ayarlar"]["ses"]
    return ses_uretim.VARSAYILAN.uret(
        ses["provider"], veri["metin"], ses["dil"],
        key=kimlik["gemini_key"], model=ses["gemini_model"], voice=ses["gemini_ses"],
        style=ses["stil"], token=kimlik["hf_token"], reference=ses["ref"] or None,
        exaggeration=ses["exag"], cfg=ses["cfg"], edge_voice=ses["edge_ses"],
        rate=ses["hiz"], pitch=ses["ton"],
        cf_account=kimlik["cf_account_id"], cf_token=kimlik["cf_token"],
        subtitles=veri["ayarlar"]["altyazi"]["acik"],
        subtitle_ayar=veri["ayarlar"]["altyazi"]["ayar"],
        hedef_klasor=calisma_klasoru(veri, "ses"))


def gorsel_uretici(veri, adim, kimlik):
    ayar = veri["ayarlar"]["gorsel"]
    # Negatif prompt yalnızca destekleyen modele gönderilir: desteklemeyen modelde alan
    # arayüzde de kilitlidir, burada da boş gönderilir. Gönderilen liste önceliğe göre
    # sıralanır ve metin penceresine sığdırılır: SDXL'in 77 tokenlık penceresinde
    # listenin sonu modele ulaşmaz, o yüzden kareyi kurtaran terimler (bozuk el, fazla
    # parmak, yazı/filigran) başa alınır (bkz. `negatif_duzenle`, `NEGATIF_ONCELIK`).
    # Sahne negatifi genel negatifin **yerine geçmez, üstüne eklenir**. Eskiden
    # "veya" vardı: yapay zekâ genel öğeleri yanıtında tekrarlamazsa kullanıcının
    # yazdığı negatif sessizce düşüyordu. Birleştirme yinelenenleri ayıklar.
    negatif = ""
    if gorsel_cloudflare.supports_negative(ayar["model"]):
        # Pozitifte istenen şeyi bastıracak öğeler **gönderim anında** da ayıklanır:
        # prompt denetimde düzeltilmiş olabilir, genel negatif sonradan elle
        # değiştirilmiş olabilir (bkz. `negatif_celiski_ayikla`).
        birlesik, _atilan = negatif_celiski_ayikla(
            adim["image_prompt"],
            negatif_birlestir(adim.get("negative_prompt"), ayar["negatif"]))
        negatif = negatif_duzenle(birlesik, NEGATIF_ONCELIK)
    prompt, referanslar = karakterli_prompt(veri, adim)
    return gorsel_cloudflare.VARSAYILAN.uret(
        prompt=prompt,
        model=ayar["model"], width=ayar["width"], height=ayar["height"],
        steps=ayar["steps"], guidance=ayar["guidance"], count=1,
        negative=negatif,
        cf_account=kimlik["cf_account_id"],
        cf_token=kimlik["cf_token"], iptal=IPTAL,
        hedef_klasor=calisma_klasoru(veri, "gorsel"), referanslar=referanslar)


def karakterli_prompt(veri, adim):
    """Karenin gönderilecek prompt'u ve referans görselleri.

    Kadro varsa sahnede görünen karakterlerin referans görselleri sırayla
    `input_image_0..3` olur; prompt'un başına "image 0 is …" eşlemesi eklenir. Eşleme
    kayıttaki prompt'a yazılmaz (gönderim anında eklenir): kullanıcı prompt'u
    düzenlerken onu görmez, karakter değişirse eşleme kendiliğinden tazelenir.
    """
    prompt = adim["image_prompt"] or adim.get("text") or "frame"
    gorunen = kadro.sahne_karakterleri(adim, veri["ayarlar"]["video"].get("karakterler") or [])
    if not gorunen:
        return prompt, []
    klasor = proje_klasoru(veri["slug"])
    referanslar = [str(kadro.mutlak_yol(karakter, klasor)) for karakter in gorunen]
    return kadro.referans_oneki([karakter["ad"] for karakter in gorunen]) + " " + prompt, referanslar


def video_uretici(veri, adim, klasor, kimlik):
    """Video üretimini Space'ler arasında kontrollü geçişle çalıştır.

    `video_hazirla` ile hazırlanan sıra (çalışan Space'ler önce) ve zorlanan
    `video.space` ayarı buraya aktarılır; istemci sırayla dener.
    """
    ayar = veri["ayarlar"]["video"]
    # Negatif prompt video modeline de gider: görsel tarafında yasaklanan öğeler
    # (anakronik nesneler, fantastik zırh vb.) hareket üretilirken geri gelmesin.
    return video_huggingface.VARSAYILAN.uret(
        str(klasor / adim["gorsel"]), adim["video_prompt"],
        adim_suresi(adim, proje_adim_saniyesi(veri)), ayar["adim"],
        kimlik["hf_token"], space=ayar.get("space") or None,
        saglayicilar=veri.get("video_sirada") or None, iptal=IPTAL,
        negatif=veri["ayarlar"]["gorsel"]["negatif"],
        hedef_klasor=calisma_klasoru(veri, "video"))


# Proje videolarını üreten servisler. Varsayılan Hugging Face'tir (Wan2.2 Space'leri).
# Servis görsel onayındaki düğmeyle seçilir (bkz. `yonetim.gorsel_onayi_ver`) ve projeye
# yazılır (`Video servisi`); **Kaldığı yerden devam** da kayıtlı servisi kullanır.
VIDEO_HF, VIDEO_AGNES, VIDEO_LTX = "huggingface", "agnes", "ltx"
VIDEO_SERVIS_ADI = {VIDEO_HF: "Hugging Face", VIDEO_AGNES: "Agnes AI (2.5 Flash · 1248×704)",
                    VIDEO_LTX: "LTX-2.3 (Hugging Face · 1280×704)"}


def video_uretici_ltx(veri, adim, klasor, kimlik):
    """Adımın videosunu LTX-2.3 Space'iyle üret (Hugging Face hesap sırasıyla)."""
    return video_ltx.VARSAYILAN.uret(
        str(klasor / adim["gorsel"]), adim["video_prompt"],
        adim_suresi(adim, proje_adim_saniyesi(veri)), kimlik["hf_token"], iptal=IPTAL,
        hedef_klasor=calisma_klasoru(veri, "video"))


def video_uretici_agnes(veri, adim, klasor):
    """Adımın videosunu Agnes AI 2.5 Flash ile üret (görsel onayındaki Agnes düğmesi).

    Kare, adımın görselidir ve **yalnızca ilk kare** olarak gider (keyframe modu); süre
    adımın kendi süresidir (Flash 4–12 sn tam sayı ister, yukarı yuvarlanır; birleştirme
    fazlasını keser). En-boy oranı görsel ayarından gelir. Flash negatif prompt almaz;
    negatif yalnızca eski V2.0 gövdesinde kullanılır. Üreteç, `video_kontrol`'ün beklediği
    biçimde biter: `(durum, dosya)`.
    """
    anahtar = aktif_anahtar("agnes", "agnes_key")
    gorsel = veri["ayarlar"]["gorsel"]
    oran = video_agnes.oran_bul(gorsel.get("width"), gorsel.get("height"))
    # Sahneye özel negatif de eklenir (A/B denemesinde süreklilik bununla birlikte arttı).
    negatif = negatif_birlestir(
        negatif_birlestir(video_huggingface.NEGATIVE, gorsel.get("negatif")),
        adim.get("negative_prompt"))
    son = None
    try:
        for durum, dosya in video_agnes.VARSAYILAN.uret(
                str(klasor / adim["gorsel"]), adim["video_prompt"], video_agnes.MODEL_VARSAYILAN,
                adim_suresi(adim, proje_adim_saniyesi(veri)), oran, anahtar, iptal=IPTAL,
                negatif=negatif, hedef_klasor=calisma_klasoru(veri, "video")):
            if dosya:
                son = (durum, dosya)
            else:
                yield f"Agnes AI · {durum}"
    except Exception as hata:
        if IPTAL.is_set():
            raise
        raise RuntimeError(video_agnes.hata_metni(hata, anahtar)) from None
    yield son or ("Agnes AI video döndürmedi.", None)


def video_hazirla(veri):
    """Video Space'lerini önceden kontrol et ve deneme sırasını hazırla.

    Çalışan Space'ler sıranın önüne alınır; hazır görünmeyenler metne ve kullanıcıya
    yazılır, yine de sıranın sonunda tutulur (birazdan ayağa kalkabilir). Böylece
    üretim, tek bir Space'in dalgalanmasına bağlı kalmaz.

    Dönüş: `(özet metni, en az bir Space hazır mı)`.
    """
    ayar = veri["ayarlar"]["video"]
    token = aktif_anahtar("huggingface", "hf_token")
    adaylar = video_huggingface.VARSAYILAN.aday_spaceler(ayar.get("space") or None)
    hazir, kapali = [], []
    for aday in adaylar:
        ok, mesaj = video_huggingface.VARSAYILAN.space_kontrol(aday, token)
        (hazir if ok else kapali).append((aday, mesaj))
    veri["video_sirada"] = [ad for ad, _m in hazir] + [ad for ad, _m in kapali]
    parcalar = [f"✔ {ad}" for ad, _m in hazir] + [f"✖ {ad} ({m})" for ad, m in kapali]
    ozet = (f"Video Space kontrolü · {len(hazir)}/{len(adaylar)} hazır · "
            + " · ".join(parcalar))
    not_ekle(veri, ozet)
    proje_yaz(veri)
    return ozet, bool(hazir)


def ses_kontrol(deger):
    """Seslendirme boş döndüyse sebebini döndür."""
    if not deger or not deger[1]:
        return (deger[0] if deger else "Seslendirme yanıt vermedi.")


def gorsel_kontrol(deger):
    """Görsel dönmediyse sebebini döndür (istemci hatayı yutup boş liste döndürür)."""
    if not deger or not deger[1]:
        return (deger[0] if deger else "Görsel dönmedi.")


def video_kontrol(deger):
    """Video dönmediyse sebebini döndür."""
    if not deger or not deger[1]:
        return (deger[0] if deger else "Video dönmedi.")


def prompt_kontrol(deger):
    """Prompt listesi boş döndüyse sebebini döndür."""
    if not deger:
        return "Prompt dönmedi (boş yanıt)."


def video_kontrollu(uretec):
    """`adim_calistir` kontrol almaz: boş video dönerse sebebi hata olarak yükselt."""
    son = None
    for deger in uretec:
        son = deger
        yield deger
    sorun = video_kontrol(son)
    if sorun:
        raise RuntimeError(sorun)
