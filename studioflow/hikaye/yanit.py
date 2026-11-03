"""Hikâye hattındaki yapay zekâ işlerinin ortak tabanı: JSON isteği, durdurma, günlük notları.

Araştırma (`arastirma.Arastirma`) ve seslendirme metni (`seslendirme.SeslendirmeYazari`)
aynı kurallarla yapay zekâya JSON sorar:

- okunamayan yanıt bir kez daha istenir;
- `kurtar` verilirse **yarıda kesilmiş** yanıtın tamamlanmış kısmı kurtarılır ve istek
  yinelenmez (çıktı sınırında yinelemek hem kota harcıyor hem çoğu zaman yine kesiliyordu);
- yapay zekâ hiç yazamazsa `None` döner ve sebep günlüğe düşer: o ana kadar yapılan iş kaybolmaz;
- durdurma bayrağı her istekten önce ve hesap beklemelerinde denetlenir.
"""
import time

from studioflow.proje.json_yardim import json_nesnesi
from studioflow.saglayicilar.metin_ortak import kisa


class Durduruldu(Exception):
    """Kullanıcı işi durdurdu."""


class YapayZekaIsi:
    """`self.ai` (HesapliMetin benzeri), `self.iptal` (Event ya da None) ve `self._notlar` bekler."""

    def _dur_mu(self):
        if self.iptal is not None and self.iptal.is_set():
            raise Durduruldu()

    def _bekle(self, saniye):
        """Hesap beklemesi; durdurma düğmesi beklemeyi hemen keser."""
        if self.iptal is None:
            time.sleep(saniye)
        elif self.iptal.wait(saniye):
            raise Durduruldu()

    def _json(self, sistem, kullanici, kurtar=None):
        """Yapay zekâdan JSON nesnesi (bkz. modül açıklaması); olmazsa `None`."""
        for _deneme in range(2):
            self._dur_mu()
            try:
                cevap = self.ai.metin(sistem, kullanici, json_modu=True,
                                      bildir=self._notlar.append)
            except Durduruldu:
                raise
            except Exception as exc:
                self._notlar.append(f"⚠ {self.ai.label} yanıt veremedi: {kisa(exc, 220)}")
                return None
            veri = json_nesnesi(cevap)
            if isinstance(veri, dict):
                return veri
            kurtarilan = kurtar(cevap) if kurtar else None
            if kurtarilan:
                self._notlar.append("Yanıt yarıda kesilmiş (çıktı sınırı); tamamlanmış kısmı "
                                    "kurtarıldı, istek yinelenmedi.")
                return kurtarilan
            self._notlar.append("Yapay zekâ yanıtı JSON olarak okunamadı; yeniden isteniyor. "
                                f"Yanıtın başı: {(cevap or '')[:100]!r}")
        return None

    def _notlari_bosalt(self):
        notlar, self._notlar = self._notlar, []
        return notlar
