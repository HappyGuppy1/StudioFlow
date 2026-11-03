"""Araçlar › Sabit karakter — geri çağrı işlevleri.

Karakter bir **referans görselle** sabitlenir; her sahne o görsel `input_image_0` olarak
verilerek FLUX.2 klein ile üretilir. Referans ya prompt'tan üretilir ya da kullanıcı
kendi görselini yükler.

Neden: karakter yalnızca metinle tarif edildiğinde model her sahnede "tarife uyan"
başka bir yüz seçiyordu. Deneme (02.10.2026, aynı 3 sahne, klein 4B): referanslı
karelerde yüz, saç ve kıyafet portredekiyle aynı kaldı; referanssız karelerde gerçekçi
karakter her sahnede başka biri oldu. Referansın pozu da kopyalanabildiği için sahne
prompt'u pozu ayrıca ister (bkz. `sahne_promptu`).
"""
import gradio as gr

from studioflow.arayuz.sabitler import KARAKTER_IPTAL
from studioflow.cekirdek import hatalar
from studioflow.cekirdek.metin import ilk_satir
from studioflow.saglayicilar import gorsel_cloudflare, hesap_havuzu

# Stil seçenekleri: (etiket, prompt'a eklenen İngilizce stil cümlesi).
STILLER = (
    ("Çizgi film (2D)", "2D cartoon animation style, clean bold outlines, flat colors"),
    ("3D animasyon", "3D animated feature film style, soft studio lighting, stylized character"),
    ("Anime", "anime style, cel shading, clean line art"),
    ("Gerçekçi", "photorealistic, cinematic film still, natural lighting"),
    ("Stil yok · prompt'ta yazacağım", ""),
)
STIL_VARSAYILAN = STILLER[0][0]
STIL_METNI = dict(STILLER)

MODEL_VARSAYILAN = "@cf/black-forest-labs/flux-2-klein-4b"
# Referans portre dikey: tam boy karakter kareye sığsın.
REFERANS_BOYUT = (768, 1024)


def _stil(stil):
    return STIL_METNI.get(stil, "")


def referans_promptu(tarif, stil):
    """Karakterin tek referans görseli: önden, tam boy, düz beyaz zemin.

    Referans her sahneye `input_image_0` olarak girer: göğsü açık bir referans (Zeus,
    14.10.2026) sahnelerde de çıplak ten üretip Cloudflare'in içerik filtresine takıldı.
    Kıyafetin üst bedeni örtmesi bu yüzden referansta istenir.
    """
    stil_metni = _stil(stil)
    return (f"Full-body front view character reference of {tarif.strip()}. Fully clothed, "
            "the outfit covering chest, shoulders and hips. Standing, arms "
            "relaxed at sides, neutral expression, centered, the whole body visible from head "
            "to feet, plain pure white background, no other objects."
            + (f" {stil_metni}." if stil_metni else ""))


def sahne_promptu(sahne, stil):
    """Sahne prompt'u: kimlik referanstan, poz ve eylem sahne metninden gelir.

    Denemede model referansın dimdik duruşunu sahneye de taşıdı ("yürürken" istenen
    karakter ayakta dikildi); bu yüzden pozun referanstan alınmaması açıkça yazılır.
    """
    stil_metni = _stil(stil)
    return (f"The exact same character from image 0, with identical face, hair, colors and "
            f"outfit, {sahne.strip()}. Show the pose and action of this scene; do not copy "
            "the standing pose of image 0."
            + (f" {stil_metni}." if stil_metni else ""))


def sahne_listesi(metin):
    """Her dolu satır bir sahne."""
    return [satir.strip(" -•\t") for satir in (metin or "").splitlines() if satir.strip(" -•\t")]


def tek_gorsel(prompt, model, genislik, yukseklik, referanslar=()):
    """Tek kare üret; kota ya da yetki hatasında **aynı servisin sıradaki hesabına** geç.

    Dönüş: `(dosya yolu ya da None, durum metni)`. Çalışan hesap uygulamanın aktif hesabı
    yapılır; tükenen hesap bu çalışma boyunca elenir (bkz. `hesap_havuzu`).
    """
    hatali = []
    for kayit in hesap_havuzu.hesap_listesi("cloudflare"):
        if hesap_havuzu.hesap_elendi("cloudflare", kayit):
            continue
        if KARAKTER_IPTAL.is_set():
            return None, "İptal edildi."
        degerler = kayit["degerler"]
        cf_token = degerler.get("cf_token", "")
        kayitlar, durum = [], "Görsel dönmedi."
        try:
            for durum, kayitlar, _dosyalar in gorsel_cloudflare.VARSAYILAN.uret(
                    prompt=prompt, model=model or MODEL_VARSAYILAN, width=genislik,
                    height=yukseklik, count=1, referanslar=referanslar,
                    cf_account=degerler.get("cf_account_id", ""), cf_token=cf_token,
                    iptal=KARAKTER_IPTAL):
                pass
        except Exception as exc:
            durum = hatalar.gorsel_hatasi_temizle(exc, cf_token)
        if kayitlar:
            hesap_havuzu.hesap_basarisi("cloudflare", kayit)
            if hesap_havuzu.hesap_aktif_yap("cloudflare", kayit):
                durum += f"\nAktif Cloudflare hesabı: {hesap_havuzu.hesap_adi(kayit)}"
            return str(kayitlar[0][0]), durum
        hatali.append(f"{hesap_havuzu.hesap_adi(kayit)}: {ilk_satir(durum)}")
        if hatalar.hata_etiketle(durum) not in ("KOTA", "YETKİ"):
            # Kota/yetki dışı hata hesabın değil isteğin sorunudur; başka hesap aynısını alır.
            break
        hesap_havuzu.hesap_ele("cloudflare", kayit, durum)
    return None, "\n".join(hatali) or "Kullanılabilir Cloudflare hesabı yok; API hesaplarından ekle."


def karakter_kaynak_degisti(kaynak):
    """Referans kaynağı: prompt'tan üretilecekse tarif alanı görünür."""
    return gr.update(visible=kaynak == "Prompt ile üret")


def karakter_iptal_et():
    KARAKTER_IPTAL.set()
    return "İptal istendi. Sıradaki sahne başlamadan durur."


def karakter_referans_uret(tarif, stil, model):
    """Tariften karakterin referans görselini üret. Çıkışlar: (referans görsel, durum)."""
    if not (tarif or "").strip():
        return None, "Önce karakteri tarif et (ör. a cute orange fox with a blue scarf)."
    KARAKTER_IPTAL.clear()
    yol, durum = tek_gorsel(referans_promptu(tarif, stil), model, *REFERANS_BOYUT)
    if not yol:
        return None, durum
    return yol, ("Referans hazır. Beğenmediysen yeniden üret; beğendiysen sahneleri yaz ve "
                 "**Sahneleri üret**e bas.\n" + durum)


def karakter_sahneleri_uret(referans, sahneler, stil, model, genislik, yukseklik):
    """Her sahneyi referans görselle üret. Çıkışlar: (galeri, dosyalar, durum)."""
    if not referans:
        yield [], [], "Önce bir referans görsel üret ya da kendi görselini yükle."
        return
    liste = sahne_listesi(sahneler)
    if not liste:
        yield [], [], "Her satıra bir sahne yaz (ör. walking through a busy market at sunset)."
        return
    KARAKTER_IPTAL.clear()
    galeri, dosyalar, hatali = [], [], []
    for sira, sahne in enumerate(liste, 1):
        if KARAKTER_IPTAL.is_set():
            yield galeri, dosyalar, f"İptal edildi · {len(galeri)}/{len(liste)} sahne üretildi."
            return
        yield galeri, dosyalar, f"Sahne {sira}/{len(liste)} üretiliyor… ({sahne[:60]})"
        yol, durum = tek_gorsel(sahne_promptu(sahne, stil), model, genislik, yukseklik,
                                [referans])
        if not yol:
            hatali.append(f"Sahne {sira}: {durum}")
            continue
        galeri.append((yol, f"Sahne {sira} · {sahne[:50]}"))
        dosyalar.append(yol)
    ozet = f"Tamamlandı · {len(galeri)}/{len(liste)} sahne üretildi."
    if hatali:
        ozet += "\n" + "\n".join(hatali)
    yield galeri, dosyalar, ozet
