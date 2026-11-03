"""Araçlar › Sesten yazıya — geri çağrılar.

Video ya da ses dosyası Gemini ile metne (ve istenirse zamanlı SRT altyazıya) dökülür;
akış `altyazi.sesten_yazi` modülündedir. Büyük videolar tarayıcıdan yüklenemediği için
(yükleme sınırı 20 MB) bilgisayardaki dosyanın yolu da verilebilir: uygulama yerelde
çalıştığı için dosya kopyalanmadan okunur.
"""
from pathlib import Path

from studioflow.altyazi import sesten_yazi
from studioflow.cekirdek import depolama
from studioflow.cekirdek.metin import ilk_satir as _ilk_satir

YA_HAZIR = ("Hazır. Bir video ya da ses dosyası yükle (20 MB'a kadar) veya bilgisayardaki "
            "dosyanın yolunu yapıştır, sonra **Yazıya dök**'e bas. Gemini anahtarları "
            "**API hesapları** sekmesindedir.")


def _kaynak(dosya, yol):
    """Önce yazılan yol (büyük dosyalar), yoksa yüklenen dosya."""
    yol = (yol or "").strip().strip('"').strip("'")
    if yol:
        return Path(yol)
    if dosya:
        return Path(getattr(dosya, "name", dosya))
    return None


def _terimler(metin):
    return [t.strip() for t in (metin or "").replace("\n", ",").split(",") if t.strip()][:1000]


def yazi_dok(dosya, yol, dil, zamanli, terimler):
    """Çıkışlar: (durum, metin, indirilecek dosyalar)."""
    kaynak = _kaynak(dosya, yol)
    if kaynak is None:
        yield "Önce bir dosya yükle ya da bilgisayardaki dosyanın yolunu yaz.", "", None
        return
    zamanli = bool(zamanli)
    liste = _terimler(terimler)
    satirlar = []
    if zamanli and liste:
        satirlar.append("Not: özel kelimeler yalnızca altyazısız kipte kullanılır "
                        "(Gemini ikisini birlikte kabul etmiyor); bu dökümde yok sayıldı.")
        liste = []
    hedef = sesten_yazi.cikti_klasoru(depolama.VARSAYILAN.hedef_klasoru("yazi"), kaynak)
    akis = sesten_yazi.yaziya_dok(kaynak, hedef, dil or "", zamanli, liste)
    try:
        while True:
            satirlar.append(next(akis))
            yield "\n".join(satirlar[-8:]), "", None
    except StopIteration as bitis:
        sonuc = bitis.value
    except sesten_yazi.SestenYaziHatasi as exc:
        yield "\n".join(satirlar[-6:] + [f"❌ {exc}"]), "", None
        return
    except Exception as exc:
        yield "\n".join(satirlar[-6:] + [f"❌ Beklenmeyen hata: {_ilk_satir(exc, 300)}"]), "", None
        return
    ozet = (f"✅ Tamam · {sonuc['sure'] / 60:.1f} dk · {sonuc['parca']} parça · "
            f"{len(sonuc['metin'].split())} kelime\n"
            + "".join(f"· {n}\n" for n in sonuc["notlar"])
            + f"Kaydedildi: {hedef}")
    yield ozet, sonuc["metin"], [str(y) for y in sonuc["dosyalar"]]

