"""`# açıklama` satırlı, elle düzenlenebilir metin ayar dosyaları için ortak taban.

API hesapları ve genel proje ayarları aynı kalıbı kullanır: bir başlık yorumu,
`anahtar = değer` satırları, dosya yoksa boş sonuç, yazarken klasörü oluşturma ve
izin hatasını anlaşılır bir mesaja çevirme. Satırların **anlamı** alt sınıflara aittir;
dosya biçimleri bu sınıf yüzünden değişmez.
"""
from pathlib import Path


class AnahtarDegerDosyasi:
    def __init__(self, yol, baslik=""):
        self.yol = Path(yol)
        self.baslik = baslik

    def var_mi(self):
        """Dosya var ve boş değil mi?"""
        try:
            return self.yol.is_file() and self.yol.stat().st_size > 0
        except OSError:
            return False

    def satirlari_oku(self):
        """Bütün satırlar; dosya yoksa/okunamıyorsa None."""
        try:
            return self.yol.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return None

    @staticmethod
    def veri_satiri(satir):
        """`anahtar = değer` satırını `(anahtar, değer)` olarak ver; yorum/boşsa None."""
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            return None
        sol, _, deger = satir.partition("=")
        return sol.strip(), deger.strip()

    def satirlari_yaz(self, satirlar):
        """Satırları (başlık dâhil) dosyaya yaz; klasör yoksa oluştur."""
        try:
            self.yol.parent.mkdir(parents=True, exist_ok=True)
            self.yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
        except OSError as hata:
            raise RuntimeError(f"{self.yol} yazılamadı. Klasör izinlerini kontrol et. "
                               f"Ayrıntı: {hata}") from None

    def sil(self):
        self.yol.unlink(missing_ok=True)
