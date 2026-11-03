"""Araçlar › Prompt › Araştırma — geri çağrı işlevleri."""
import gradio as gr

from studioflow.arayuz.sabitler import ARASTIRMA_IPTAL
from studioflow.hikaye import kayitlar
from studioflow.hikaye.arastirma import Arastirma, ArastirmaDurdu
from studioflow.saglayicilar.arama_havuzu import AramaHavuzu
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR, EN_IYI_MODELLER, kisa
from studioflow.ayarlar import api_hesaplari

# Durum kutusunda tutulan en fazla satır: uzun araştırmada kutu sonsuza uzamasın.
GUNLUK_SATIR = 60


def arastirma_model_secenekleri(servis):
    """Servis değişince yalnızca o servisin en iyi modeli önerilir (elle yazılabilir)."""
    model = EN_IYI_MODELLER.get(servis) or (AI_SAGLAYICILAR.get(servis, {}).get("models") or [""])[0]
    return gr.update(choices=[model], value=model)


def arastirma_katmanlari(servis="gemini"):
    """Kullanılabilir yapay zekâ hesapları ve arama katmanları (tek paragraf)."""
    etiket = AI_SAGLAYICILAR.get(servis, {}).get("label", servis)
    hesap = len(api_hesaplari.VARSAYILAN.hesap_adlari(servis)) if servis in api_hesaplari.HIZMETLER else 0
    jina = "anahtarlı" if api_hesaplari.VARSAYILAN.aktif_deger("jina", "jina_key") else "anahtarsız"
    return (f"**Yapay zekâ:** {etiket} · {hesap} hesap  \n"
            f"**Arama sırası:** Wikipedia (TR + EN) → {AramaHavuzu().ozet()}  \n"
            f"**Sayfa okuma:** yerel okuyucu → Jina Reader ({jina})")


def arastirma_baslat(konu, derinlik, servis, model, dil):
    """Araştırmayı yürüt; durum, rapor, dosyalar, ham veri yolu ve önerilen kayıt adı üretir."""
    ARASTIRMA_IPTAL.clear()
    gunluk = []
    bos = (gr.update(),) * 4

    def durum(satir=None):
        if satir:
            gunluk.append(satir)
            del gunluk[:-GUNLUK_SATIR]
        return "\n".join(gunluk)

    konu = (konu or "").strip()
    if not konu:
        yield ("Önce araştırılacak olayı yaz.", *bos)
        return
    try:
        arastirma = Arastirma(konu, derinlik, servis, model, dil, iptal=ARASTIRMA_IPTAL,
                              jina_anahtari=api_hesaplari.VARSAYILAN.aktif_deger("jina", "jina_key"))
        for satir in arastirma.adimlar():
            yield (durum(satir), *bos)
    except ArastirmaDurdu:
        yield (durum("Durduruldu. Yarım kalan araştırma kaydedilmedi."), *bos)
        return
    except Exception as exc:
        yield (durum(f"Araştırma tamamlanamadı: {kisa(exc, 400)}"), *bos)
        return
    sonuc = arastirma.sonuc
    yield (durum("Raporu gözden geçir; bir ad verip **Araştırmayı kaydet**'e bas."),
           sonuc["metin"], [str(sonuc["txt"]), str(sonuc["json"])], str(sonuc["json"]),
           kayitlar.ad_temizle(sonuc["baslik"]))


def arastirma_durdur():
    ARASTIRMA_IPTAL.set()
    return "Durdurma istendi; araştırma sıradaki adımda duracak."


def arastirma_listesi(secili=None):
    """Kayıtlı araştırmalar açılır listesi (seçili ad listede kalıyorsa korunur)."""
    adlar = kayitlar.listele()
    return gr.update(choices=adlar, value=secili if secili in adlar else None)


def arastirma_kaydet(ad, metin, ham_json):
    """Ekrandaki (düzenlenmiş) raporu verilen adla kütüphaneye kaydet."""
    try:
        temiz, txt, jsn, guncellendi = kayitlar.kaydet(ad, metin, ham_json or None)
    except ValueError as exc:
        return str(exc), gr.update(), gr.update(), gr.update()
    except OSError as exc:
        return f"Kaydedilemedi: {exc.strerror or exc}", gr.update(), gr.update(), gr.update()
    fiil = "güncellendi" if guncellendi else "kaydedildi"
    return (f"**{temiz}** {fiil} · `{txt}`", arastirma_listesi(temiz), gr.update(value=temiz),
            [str(txt), str(jsn)])


def arastirma_ac(ad):
    """Kayıtlı bir araştırmayı düzenleyiciye yükle."""
    if not ad:
        return "Listeden bir araştırma seç.", gr.update(), gr.update(), gr.update(), gr.update()
    try:
        metin, txt, jsn = kayitlar.oku(ad)
    except (FileNotFoundError, OSError) as exc:
        return str(exc), gr.update(), gr.update(), gr.update(), gr.update()
    return (f"**{ad}** açıldı. Düzenleyip aynı adla kaydedersen kayıt güncellenir.", metin,
            gr.update(value=ad), str(jsn) if jsn.is_file() else "",
            [str(yol) for yol in (txt, jsn) if yol.is_file()])


def arastirma_sil(ad):
    if not ad:
        return "Listeden silinecek araştırmayı seç.", gr.update()
    try:
        kayitlar.sil(ad)
    except (FileNotFoundError, OSError) as exc:
        return str(exc), gr.update()
    return f"**{ad}** silindi.", arastirma_listesi()
