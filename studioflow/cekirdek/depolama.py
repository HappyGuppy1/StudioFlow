"""Üretilen dosyaların nereye yazılacağını belirler.

**Varsayılan davranış:** hiçbir dosya `outputs` klasörüne otomatik kaydedilmez.
Görseller, sesler ve videolar `.cache/studioflow` altındaki geçici çalışma klasörüne
yazılır; arayüzdeki indirme kutularından **yalnızca kullanıcı istediğinde** alınır.

**Proje oluştur** sekmesindeki *Ayarları kaydet* panelinin altındaki açılır bölümde
yer alan **Otomatik kaydetmeyi aç** kutusu işaretlenirse üretim doğrudan `outputs`
klasörüne yazılır. Seçim yalnızca bu oturum için geçerlidir; uygulama kapanınca
varsayılan (kapalı) duruma döner, böylece disk kendiliğinden dolmaz.

Geçici klasördeki dosyalar bir hafta durur; daha eskileri uygulama açılırken silinir
(bkz. `cekirdek.temizlik`). Proje üretimi bu klasörü kullanmaz: sağlayıcılara projenin
kendi `.calisma` klasörü verilir, üretilen her şey proje klasöründe kalır.
"""
from studioflow.cekirdek.yollar import GECICI, OUTPUTS, ROOT


class Depolama:
    """Oturum boyunca tek örnek: otomatik kaydetme açık mı ve hedef klasör nerede."""

    def __init__(self, outputs=OUTPUTS, gecici=GECICI):
        self.outputs = outputs
        self.gecici = gecici
        self._acik = False

    def otomatik(self, acik=None):
        """Otomatik kaydetme açık mı? Değer verilirse ayarı değiştirir."""
        if acik is not None:
            self._acik = bool(acik)
        return self._acik

    def hedef_klasoru(self, ad=""):
        """Kategori klasörünü döndür (ve oluştur).

        Otomatik kaydetme açıkken `outputs[/ad]`, kapalıyken `.cache/studioflow[/ad]`.
        """
        temel = self.outputs if self._acik else self.gecici
        yol = temel / ad if ad else temel
        yol.mkdir(parents=True, exist_ok=True)
        return yol

    def hedef_metni(self, ad=""):
        """Durum mesajlarında gösterilecek klasör yolu."""
        return str(self.hedef_klasoru(ad))

    def durum_metni(self):
        if self._acik:
            return ("Otomatik kaydetme **açık**: üretilen dosyalar doğrudan "
                    f"`{self.outputs}` klasörüne yazılır.")
        return ("Otomatik kaydetme **kapalı**: üretilen dosyalar geçici klasöre yazılır ve "
                "yalnızca indirme kutusundan alınır. Kalıcı olmasını istersen yukarıdaki "
                "kutuyu işaretle.")


# Uygulamanın paylaşılan depolama örneği: sağlayıcılar ve arayüz aynı ayarı görür.
VARSAYILAN = Depolama()

__all__ = ["Depolama", "VARSAYILAN", "ROOT", "OUTPUTS", "GECICI"]
