"""Ad verilerek saklanan kayıtlar: araştırmalar ve seslendirme metinleri.

Her iş bittiğinde zaman damgalı bir yedek zaten yazılır (`outputs/arastirma/`,
`outputs/seslendirme/`). Kullanıcı sonucu gözden geçirip **bir ad vererek** kaydettiğinde
kayıt ilgili kütüphaneye girer ve sonraki aşamalar oradan seçer:

    outputs/arastirma/kayitli/<ad>.txt     düzenlenmiş araştırma raporu
    outputs/arastirma/kayitli/<ad>.json    araştırmanın ham verisi + kayıt bilgisi
    outputs/seslendirme/kayitli/<ad>.txt   seslendirilecek metin (ses aşamasının girdisi)
    outputs/seslendirme/kayitli/<ad>.json  plan, bölümler, çeviri + kayıt bilgisi

Aynı adla yeniden kaydetmek kaydı günceller. Modül düzeyindeki işlevler (`kaydet`,
`listele`, …) araştırma kütüphanesinindir; seslendirme kütüphanesi
`seslendirme.SESLENDIRMELER`dir.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from studioflow.hikaye import rapor

# Windows dosya adında geçmeyen karakterler ve ayrılmış adlar.
_YASAK = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_AYRILMIS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
AD_SINIRI = 80


def ad_temizle(ad):
    """Kullanıcının yazdığı adı dosya adına uygun hale getir (Türkçe harfler korunur)."""
    ad = _YASAK.sub(" ", str(ad or ""))
    ad = re.sub(r"\s+", " ", ad).strip(" .")[:AD_SINIRI].strip(" .")
    return "" if ad.lower() in _AYRILMIS else ad


def _json_oku(yol):
    try:
        veri = json.loads(Path(yol).read_text(encoding="utf-8"))
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


class Kutuphane:
    """Tek klasörde `<ad>.txt` + `<ad>.json` çiftleri.

    `klasor_bul` her çağrıda klasörü döndüren bir işlevdir: testler kök klasörü
    (`rapor.KLASOR`, `seslendirme.KLASOR`) değiştirebilsin diye yol önceden sabitlenmez.
    """

    def __init__(self, klasor_bul, etiket):
        self.klasor_bul = klasor_bul
        self.etiket = etiket                  # hata metinleri için: "araştırma", "seslendirme"

    def klasor(self):
        return self.klasor_bul()

    def listele(self):
        """Kayıt adları, en son kaydedilen önce."""
        yer = self.klasor()
        if not yer.is_dir():
            return []
        dosyalar = sorted(yer.glob("*.txt"), key=lambda yol: yol.stat().st_mtime, reverse=True)
        return [yol.stem for yol in dosyalar]

    def yollar(self, ad):
        temiz = ad_temizle(ad)
        return self.klasor() / f"{temiz}.txt", self.klasor() / f"{temiz}.json"

    def var_mi(self, ad):
        return bool(ad_temizle(ad)) and self.yollar(ad)[0].is_file()

    def kaydet(self, ad, metin, ham_json=None, ek=None):
        """Metni `ad` ile kaydet; `(ad, txt yolu, json yolu, güncellendi mi)` döndürür.

        `ham_json`: işin zaman damgalı ham verisi (varsa kayda kopyalanır; yoksa kaydın
        mevcut verisi korunur). `ek`: JSON'a yazılacak ek alanlar (ör. çeviri).
        """
        temiz = ad_temizle(ad)
        if not temiz:
            raise ValueError(f"{self.etiket.capitalize()} kaydına bir ad ver.")
        if not (metin or "").strip():
            raise ValueError(f"Kaydedilecek {self.etiket} metni boş.")
        txt, jsn = self.yollar(temiz)
        guncellendi = txt.is_file()
        if ham_json and Path(ham_json).is_file() and Path(ham_json) != jsn:
            veri = _json_oku(ham_json)
        else:
            veri = _json_oku(jsn) if jsn.is_file() else {}
        veri.update(ek or {})
        onceki = veri.get("kayit") or {}
        veri["kayit"] = {"ad": temiz, "kaydedildi": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
                         "ham_veri": str(ham_json) if ham_json and Path(ham_json) != jsn
                         else onceki.get("ham_veri", "")}
        self.klasor().mkdir(parents=True, exist_ok=True)
        txt.write_text(metin.strip() + "\n", encoding="utf-8")
        jsn.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        return temiz, txt, jsn, guncellendi

    def oku(self, ad):
        """`(metin, txt yolu, json yolu)`; kayıt yoksa `FileNotFoundError`."""
        txt, jsn = self.yollar(ad)
        if not txt.is_file():
            raise FileNotFoundError(f"Kayıtlı {self.etiket} bulunamadı: {ad}")
        return txt.read_text(encoding="utf-8"), txt, jsn

    def veri(self, ad):
        """Kaydın JSON verisi (yoksa boş sözlük)."""
        return _json_oku(self.yollar(ad)[1])

    def sil(self, ad):
        txt, jsn = self.yollar(ad)
        if not txt.is_file():
            raise FileNotFoundError(f"Kayıtlı {self.etiket} bulunamadı: {ad}")
        for yol in (txt, jsn):
            yol.unlink(missing_ok=True)


# Araştırma kütüphanesi ve eski modül düzeyi adları (arayüz ve testler bunları kullanır).
ARASTIRMALAR = Kutuphane(lambda: rapor.KLASOR / "kayitli", "araştırma")
klasor = ARASTIRMALAR.klasor
listele = ARASTIRMALAR.listele
yollar = ARASTIRMALAR.yollar
var_mi = ARASTIRMALAR.var_mi
kaydet = ARASTIRMALAR.kaydet
oku = ARASTIRMALAR.oku
sil = ARASTIRMALAR.sil
