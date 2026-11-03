"""Sağlayıcı sözleşmeleri (soyut sınıflar).

Proje akışı ve arayüz yalnızca bu arayüzlere güvenir; somut sınıf değişse de
(yeni Space, yeni ses servisi) çağıran taraf değişmez.
"""
from abc import ABC, abstractmethod


class VideoSaglayici(ABC):
    """Bir kareden kısa video üretir (üreteç: durum metni, dosya yolu)."""

    ad = ""

    @abstractmethod
    def space_kontrol(self, space, token=""):
        """`(hazır mı, açıklama)`; hata yükseltmez."""

    @abstractmethod
    def uret(self, image_path, prompt, duration, steps, token="", **secenekler):
        """`(durum, kaydedilen video yolu ya da None)` çiftleri üretir."""


class GorselSaglayici(ABC):
    """Metinden görsel üretir."""

    ad = ""

    @abstractmethod
    def modeller(self):
        """Arayüz listesi: `(etiket, model kimliği)` çiftleri."""

    @abstractmethod
    def uret(self, *, prompt, model, width, height, steps, guidance, negative, count,
             seed, iptal, **kimlik):
        """`(durum, dosya listesi)` çiftleri üretir."""


class SesSaglayici(ABC):
    """Metni seslendirir; kelime zamanlarını da verebilir."""

    ad = ""

    @abstractmethod
    def kontrol(self, **kimlik):
        """Servis erişilebilir mi? Açıklama metni döner; olmazsa hata yükseltir."""

    @abstractmethod
    def parca_uret(self, text, output, **secenekler):
        """Tek parça metni `output` dosyasına seslendirir; kelime zamanlarını döndürür."""


class MetinAI(ABC):
    """Sistem + kullanıcı mesajından metin (isteğe bağlı JSON) üretir."""

    ad = ""

    @abstractmethod
    def metin(self, anahtar, model, sistem, kullanici, json_modu=True):
        """Yanıt metni; hata yükseltir."""

    def metin_tek_model(self, anahtar, model, sistem, kullanici, json_modu=True):
        """Yalnızca verilen modelle yanıt üret; sağlayıcının kendi model yedeği denenmez.

        Model yedeği olmayan sağlayıcılarda `metin` ile aynıdır.
        """
        return self.metin(anahtar, model, sistem, kullanici, json_modu)


class AramaSaglayici(ABC):
    """Web'de (ya da bir ansiklopedide) arar; her sonuç `arama_ortak.sonuc` sözlüğüdür."""

    ad = ""
    # Anahtar isteyen servisler hesap hesap denenir; istemeyenler bir kez denenir.
    hizmet = ""

    @abstractmethod
    def ara(self, sorgu, adet, anahtar="", dil="tr"):
        """Sonuç listesi; hata durumunda `arama_ortak.AramaHatasi` yükseltir."""
