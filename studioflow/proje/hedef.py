"""Panel işlemlerinin ortak ön kontrolü: proje adı → `(veri, klasör, hata mesajı)`.

Müzik, dublaj, altyazı ve dil panellerinin hepsi aynı üç soruyu sorar: ad yazılı mı,
proje şu anda çalışıyor mu, klasöründe okunabilir bir `proje.txt` var mı? Cevap tek
yerde durur; panele özgü tek fark hata metnindeki **işlem adıdır**.
"""
from studioflow.proje.calisma_kilidi import calisan
from studioflow.proje.depo import guvenli_klasor, slug
from studioflow.proje.dosya import proje_oku
from studioflow.proje.sabitler import DOSYA_ADI


def proje_hedefi(ad, islem="işlem yap", secim_notu="Önce bir proje seç ya da proje adını yaz."):
    """Ön kontrol. Dönüş: `(veri, klasör, hata mesajı)`; hata varsa ilk ikisi `None`.

    `islem` yalnızca "proje çalışıyor" uyarısında görünür ("… sonra müzik ekle").
    Dönen `veri["slug"]` **seçilen klasörün** adıdır: yazma hedefi hep o klasördür.
    """
    ad = (ad or "").strip()
    if not ad:
        return None, None, secim_notu
    if calisan() == slug(ad):
        return None, None, (f"'{ad}' şu anda çalışıyor. Önce **Durdur**'a bas, "
                            f"sonra {islem}.")
    klasor = guvenli_klasor(ad)
    veri = proje_oku(klasor) if klasor else None
    if veri is None:
        return None, None, f"'{ad}' okunamadı: klasöründe okunabilir bir {DOSYA_ADI} yok."
    veri["slug"] = slug(ad)
    return veri, klasor, ""
