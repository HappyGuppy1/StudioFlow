"""Katmanlı web araması: **Tavily → Exa → DDGS**; anahtarlı servislerde hesap hesap.

- Anahtarlı serviste hesaplar aktif olandan başlayarak denenir. Kota/yetki hatası alan
  hesap bu araştırma boyunca elenir ve sıradaki hesaba geçilir; bütün hesaplar bitince
  sıradaki **servise** geçilir.
- Başka bir hata (sunucu hatası, kopan bağlantı) hesabı yakmaz: o sorgu için doğrudan
  sıradaki servise geçilir.
- Hiç sonuç döndürmeyen servis de başarısız sayılır; sorgu sıradaki serviste denenir.
- DDGS anahtarsızdır; hız sınırına takılırsa bu araştırma boyunca kapatılır.

Havuz **araştırma başına** kurulur: elenen hesaplar bir sonraki araştırmada yeniden denenir.
"""
from studioflow.ayarlar import api_hesaplari
from studioflow.saglayicilar import arama_ddgs, arama_exa, arama_tavily
from studioflow.saglayicilar.arama_ortak import AramaHatasi
from studioflow.saglayicilar.metin_ortak import kisa

ARAMA_SIRA = ("tavily", "exa", "ddgs")

ETIKETLER = {"tavily": "Tavily", "exa": "Exa", "ddgs": "DDGS (anahtarsız)"}


class AramaHavuzu:
    def __init__(self, saglayicilar=None, hesaplar=None):
        self.saglayicilar = saglayicilar or {"tavily": arama_tavily.VARSAYILAN,
                                             "exa": arama_exa.VARSAYILAN,
                                             "ddgs": arama_ddgs.VARSAYILAN}
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.elenen = set()          # {(servis, hesap adı)} bu araştırmada tükenenler
        self.kapali = set()          # hız sınırına takılan anahtarsız servisler
        self.sayac = {}              # servis → başarılı arama sayısı

    def anahtarli_hesaplar(self, servis):
        """`[(hesap adı, anahtar)]`, aktif hesap önce; anahtarı boş hesaplar atlanır."""
        try:
            adlar = self.hesaplar.hesap_adlari(servis)
            aktif = self.hesaplar.aktif_hesap(servis)
        except Exception:
            return []
        sirali = ([aktif] if aktif in adlar else []) + [ad for ad in adlar if ad != aktif]
        alan = f"{servis}_key"
        cift = [(ad, (self.hesaplar.hesap_degerleri(servis, ad).get(alan) or "").strip())
                for ad in sirali]
        return [(ad, anahtar) for ad, anahtar in cift if anahtar]

    def ozet(self):
        """Hangi katmanlar kullanılabilir? Kısa, tek satırlık açıklama."""
        parcalar = []
        for servis in ARAMA_SIRA:
            saglayici = self.saglayicilar.get(servis)
            if saglayici is None:
                continue
            if saglayici.hizmet:
                adet = len(self.anahtarli_hesaplar(servis))
                parcalar.append(f"{ETIKETLER[servis]}: {adet} hesap" if adet
                                else f"{ETIKETLER[servis]}: anahtar yok")
            else:
                hazir = servis != "ddgs" or arama_ddgs.DDGS is not None
                parcalar.append(f"{ETIKETLER[servis]}: {'hazır' if hazir else 'paket kurulu değil'}")
        return " · ".join(parcalar)

    def _aktif_yap(self, servis, ad):
        try:
            if ad != self.hesaplar.aktif_hesap(servis):
                self.hesaplar.hesap_sec(servis, ad)
        except Exception:
            pass

    def ara(self, sorgu, adet=5, dil="tr", bildir=None):
        """`(sonuçlar, servis)`; hiçbir katman sonuç veremezse `([], "")`."""
        def haber(mesaj):
            if bildir:
                bildir(mesaj)

        for servis in ARAMA_SIRA:
            saglayici = self.saglayicilar.get(servis)
            if saglayici is None or servis in self.kapali:
                continue
            etiket = ETIKETLER.get(servis, servis)
            denemeler = ([(ad, anahtar) for ad, anahtar in self.anahtarli_hesaplar(servis)
                          if (servis, ad) not in self.elenen]
                         if saglayici.hizmet else [("", "")])
            for ad, anahtar in denemeler:
                try:
                    sonuclar = saglayici.ara(sorgu, adet, anahtar, dil)
                except AramaHatasi as exc:
                    if saglayici.hizmet and exc.tur in ("KOTA", "YETKİ"):
                        self.elenen.add((servis, ad))
                        haber(f"{etiket} · '{ad}' hesabı kullanılamıyor ({kisa(exc)}); "
                              "sıradaki hesap deneniyor.")
                        continue
                    if not saglayici.hizmet and exc.tur == "KOTA":
                        self.kapali.add(servis)
                    haber(f"{etiket} arayamadı ({kisa(exc)}); sıradaki arama servisine geçiliyor.")
                    break
                if not sonuclar:
                    break
                if ad:
                    self._aktif_yap(servis, ad)
                self.sayac[servis] = self.sayac.get(servis, 0) + 1
                return sonuclar, servis
        return [], ""
