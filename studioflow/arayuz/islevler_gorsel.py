"""Araçlar › Görsel üret sekmesi. — geri çağrı işlevleri."""
import gradio as gr

from studioflow.arayuz.sabitler import GORSEL_IPTAL
from studioflow.ayarlar import api_hesaplari, bicimler
from studioflow.cekirdek import hatalar
from studioflow.saglayicilar import gorsel_cloudflare


def gorsel_servis_kontrol():
    """Görsel servisinin erişilebilirliğini ve aktif anahtarını doğrula."""
    cf_account = api_hesaplari.VARSAYILAN.aktif_deger("cloudflare", "cf_account_id")
    cf_token = api_hesaplari.VARSAYILAN.aktif_deger("cloudflare", "cf_token")
    try:
        return gorsel_cloudflare.VARSAYILAN.durum(cf_account, cf_token)
    except Exception as exc:
        return "Kontrol başarısız: " + hatalar.gorsel_hatasi_temizle(exc, cf_token)


def gorsel_modeller():
    """Model listesini Cloudflare'in sabit tablosundan yeniden yükle."""
    secenekler = gorsel_cloudflare.cf_model_choices()
    return gr.update(choices=secenekler, value=secenekler[0][1] if secenekler else None)


def gorsel_on_ayar_degisti(ad):
    """Görsel ön ayarını model, boyut, adım ve guidance'a uygula."""
    not_metni = gorsel_cloudflare.on_ayar_notu(ad)
    ayar = gorsel_cloudflare.on_ayar_uygula(ad)
    if not ayar:
        return [gr.update()] * 6 + [gr.update(value=not_metni)]
    aralik = gorsel_cloudflare.cf_size_range(ayar["model"])
    hedef = gorsel_cloudflare.size_clamp(ayar["model"], ayar["width"], ayar["height"])
    if aralik and hedef[0]:
        genislik = gr.update(minimum=aralik[0], maximum=aralik[1], step=aralik[2], value=hedef[0])
        yukseklik = gr.update(minimum=aralik[0], maximum=aralik[1], step=aralik[2], value=hedef[1])
    else:
        # Boyutu model sabitliyor (FLUX 1024×1024): slider'ın aralığına dokunulmaz.
        genislik, yukseklik = gr.update(value=ayar["width"]), gr.update(value=ayar["height"])
    adim_alt, adim_ust, _adim_varsayilan = gorsel_cloudflare.cf_steps_range(ayar["model"])
    guidance_alt, guidance_ust, _g = gorsel_cloudflare.cf_guidance_range(ayar["model"])
    return [gr.update(choices=gorsel_cloudflare.cf_model_choices(), value=ayar["model"]),
            gr.update(value=gorsel_cloudflare.cf_note(ayar["model"])),
            genislik, yukseklik,
            gr.update(minimum=adim_alt, maximum=adim_ust, value=ayar["steps"]),
            gr.update(minimum=guidance_alt, maximum=guidance_ust, value=ayar["guidance"]),
            gr.update(value=not_metni)]


def _bicim_boyutlari(model, bicim):
    """Biçimin görsel boyutunu **modelin izin verdiği** değerlere yuvarla.

    Video Space'i klibin ölçüsünü yüklediğimiz karenin oranından türettiği için karenin
    oranı hedef biçimle aynı olmalıdır; ama CF modelleri yalnızca belli boyutları kabul
    eder (64'ün katı, 256–2048), FLUX ise 1024×1024'e sabittir. Model boyutu sabitliyorsa
    `(None, None)` döner.
    """
    genislik, yukseklik = bicimler.bicim_gorsel_boyutu(bicim)
    secenekler = gorsel_cloudflare.cf_size_options(model)
    if not secenekler:
        return None, None

    def en_yakin(deger):
        return min(secenekler, key=lambda secenek: abs(secenek - deger))

    return en_yakin(genislik), en_yakin(yukseklik)


def gorsel_boyut_ayari(model, bicim=None):
    """Cloudflare modelinin adım, guidance ve boyut değerlerini hazırla.

    `bicim` verilirse boyut, modelin sınırları içinde o biçimin oranına uydurulur
    (proje sekmesinde çıktı biçimi belirleyicidir); verilmezse model varsayılanı kalır.
    """
    alt, ust, varsayilan = gorsel_cloudflare.cf_steps_range(model)
    g_alt, g_ust, g_varsayilan = gorsel_cloudflare.cf_guidance_range(model)
    boyut = gorsel_cloudflare.cf_size_default(model)
    aralik = gorsel_cloudflare.cf_size_range(model)
    not_metni = gorsel_cloudflare.cf_note(model)
    if boyut is None:
        spec = gorsel_cloudflare.cf_model_spec(model) or {}
        not_metni += " Çözünürlüğü model sabitler: " + str(spec.get("size_label") or "")
        if bicim:
            not_metni += (f" Bu model kare kare üretir; "
                          f"**{bicimler.bicim_etiketi(bicim)}** için karenin oranı "
                          "değişmez: SDXL Lightning seçersen oran tutar.")
        genislik = yukseklik = gr.update()
    else:
        genislik, yukseklik = _bicim_boyutlari(model, bicim) if bicim else (None, None)
        if not genislik:
            genislik = yukseklik = boyut
        alt_b, ust_b, adim_b = aralik
        genislik = gr.update(minimum=alt_b, maximum=ust_b, step=adim_b, value=genislik)
        yukseklik = gr.update(minimum=alt_b, maximum=ust_b, step=adim_b, value=yukseklik)
    return (gr.update(minimum=alt, maximum=ust, value=varsayilan),
            gr.update(minimum=g_alt, maximum=g_ust, value=g_varsayilan),
            genislik, yukseklik, gr.update(value=not_metni))


def seed_alan_gorunumu(model):
    """Seed kutusunu modelin desteğine göre aç ya da kilitle.

    FLUX.1 schnell'in şeması yalnızca `prompt` ve `steps` alır; fazladan alan gelirse
    Cloudflare isteğin **tamamını** reddeder. Bu yüzden desteklemeyen modelde kutu
    kilitlenir ve sebebi yazar (gönderilmediği için üretim yine çalışır).
    """
    if gorsel_cloudflare.supports_seed(model):
        return gr.update(interactive=True,
                         label="Seed · boş bırakırsan rastgele")
    return gr.update(value="", interactive=False,
                     label="Seed · bu model seed desteklemiyor (yok sayılır)")


def gorsel_model_degisti(model):
    """Model değişince adım/guidance aralıklarını, boyutu ve seed kutusunu uydur.

    Sınırlar tahmin değil, modelin kendi değerleridir: FLUX 1–8, SDXL 1–20, Lucid 1–40.
    """
    adim, guidance, genislik, yukseklik, not_metni = gorsel_boyut_ayari(model)
    return (not_metni, adim, guidance, genislik, yukseklik, seed_alan_gorunumu(model))


def gorsel_hesap_bul(token, mevcut=""):
    """Token'ın eriştiği hesabı Cloudflare'den sorup Account ID alanına yaz."""
    try:
        hesaplar, hata = gorsel_cloudflare.VARSAYILAN.hesaplari_listele(token)
        if hata:
            return mevcut, "Account ID bulunamadı: " + hata
        if not hesaplar:
            return mevcut, gorsel_cloudflare.CF_NO_ACCOUNT_MESSAGE
        liste = "\n".join(f"• {hesap['name'] or 'isimsiz'} — {hesap['id']}" for hesap in hesaplar)
        if len(hesaplar) == 1:
            return hesaplar[0]["id"], f"Account ID bulundu ve alana yazıldı:\n{liste}"
        return hesaplar[0]["id"], (f"Token {len(hesaplar)} hesaba erişiyor; ilki alana yazıldı. "
                                   f"Kullanmak istediğin kimliği kopyala:\n{liste}")
    except Exception as exc:
        return mevcut, "Account ID bulunamadı: " + hatalar.gorsel_hatasi_temizle(exc, token)


def gorsel_cf_test(account, token):
    """Cloudflare bilgilerini gerçekten küçük bir görsel üreterek doğrula."""
    try:
        kayitli = api_hesaplari.VARSAYILAN.aktif_degerler("cloudflare")
        account = (account or "").strip() or kayitli.get("cf_account_id", "")
        token = (token or "").strip() or kayitli.get("cf_token", "")
        if not token:
            return "Önce Cloudflare API token'ını gir ya da kaydet."
        if not account:
            hesaplar, hata = gorsel_cloudflare.VARSAYILAN.hesaplari_listele(token)
            if hata:
                return "Account ID bulunamadı: " + hata
            if not hesaplar:
                return gorsel_cloudflare.CF_NO_ACCOUNT_MESSAGE
            account = hesaplar[0]["id"]
        ok, mesaj = gorsel_cloudflare.VARSAYILAN.dogrula(account, token)
        if ok:
            return "Bağlantı çalışıyor. " + mesaj
        ipucu = "\nSorunun sebebini görmek için 'Sorunu teşhis et' düğmesine bas." if any(
            kod in mesaj for kod in ("401", "403", "tanımıyor", "yetki")) else ""
        return "Doğrulama başarısız: " + mesaj + ipucu
    except Exception as exc:
        return "Doğrulama başarısız: " + hatalar.gorsel_hatasi_temizle(exc, token)


def gorsel_cf_teshis(token, account):
    """401 gibi hataların sebebini madde madde yaz. Hiçbir şeyi değiştirmez."""
    kayitli = api_hesaplari.VARSAYILAN.aktif_degerler("cloudflare")
    token = (token or "").strip() or kayitli.get("cf_token", "")
    account = (account or "").strip() or kayitli.get("cf_account_id", "")
    try:
        sonuc = gorsel_cloudflare.VARSAYILAN.teshis(token, account)
    except Exception as exc:
        return "Teşhis yapılamadı: " + hatalar.gorsel_hatasi_temizle(exc, token)
    etiket = {"ok": "TAMAM", "info": "BİLGİ", "warn": "UYARI", "error": "HATA"}
    baslik = {"ok": "Sorun yok: kontrollerin hepsi geçti.",
              "warn": "Dikkat: çalışabilir ama uyarılar var.",
              "error": "Sorun var: aşağıdaki HATA maddelerini düzeltip tekrar dene."}
    satirlar = [baslik.get(sonuc["verdict"], "Teşhis sonucu:"), ""]
    for bulgu in sonuc["findings"]:
        satirlar.append(f"- **[{etiket.get(bulgu['level'], 'BİLGİ')}] {bulgu['title']}** "
                        f"{bulgu['detail']}".strip())
    return "\n".join(satirlar)


def gorsel_iptal_et():
    """Kuyruktaki isteği iptal et (kuyruk dışında, anında çalışır)."""
    GORSEL_IPTAL.set()
    return "İptal istendi. Devam eden istek kuyruktan çekilir; birkaç saniye sürebilir."


def gorsel_uret(prompt, negative, model, width, height, steps, guidance, count, seed):
    """Tek istek gönder; görselleri hedef klasöre yaz. Otomatik tekrar yapılmaz."""
    cf_account = api_hesaplari.VARSAYILAN.aktif_deger("cloudflare", "cf_account_id")
    cf_token = api_hesaplari.VARSAYILAN.aktif_deger("cloudflare", "cf_token")
    GORSEL_IPTAL.clear()
    try:
        for durum, images, dosyalar in gorsel_cloudflare.VARSAYILAN.uret(
                prompt=prompt, negative=negative, model=model, width=width, height=height,
                steps=steps, guidance=guidance, count=int(count), seed=seed,
                cf_account=cf_account, cf_token=cf_token, iptal=GORSEL_IPTAL):
            yield images, dosyalar, durum
    except Exception as exc:
        yield [], [], hatalar.gorsel_hatasi_temizle(exc, cf_token)
