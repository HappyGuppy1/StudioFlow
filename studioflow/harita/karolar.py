"""Harita karoları (Web Mercator, 256 px): kaynak listesi, disk önbelleği, paralel indirme.

Tüm kaynaklar **yazısız** altlıktır: modern şehir/ülke adları tarihi sahnelere uymaz,
etiketleri animasyon kendisi çizer. Her kaynağın kullanım şartı **atıf** ister; atıf
metni videonun sağ alt köşesine küçük yazılır (`atif`).
"""
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

from studioflow.cekirdek.yollar import GECICI

KARO = 256
ZAMAN_ASIMI = 20
PARALEL = 8
BELLEK_SINIRI = 900                 # bellekte tutulan en fazla karo
_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
_CARTO = "https://{{s}}.basemaps.cartocdn.com/{}/{{z}}/{{x}}/{{y}}.png"

# ad → (görünen ad, adres kalıbı, en büyük yakınlık, atıf, boş karo rengi)
STILLER = {
    "uydu": ("Uydu (Esri)", _ESRI.format("World_Imagery"), 18,
             "Harita: Esri, Maxar, Earthstar Geographics", (12, 22, 40)),
    "arazi": ("Arazi · yumuşak tonlar (Esri)", _ESRI.format("World_Terrain_Base"), 9,
              "Harita: Esri, USGS, NOAA", (200, 215, 225)),
    "fiziki": ("Fiziki · belgesel (Esri)", _ESRI.format("World_Physical_Map"), 8,
               "Harita: Esri, US National Park Service", (165, 190, 215)),
    "kabartma": ("Gölgeli kabartma (Esri)", _ESRI.format("World_Shaded_Relief"), 13,
                 "Harita: Esri", (220, 220, 220)),
    "koyu": ("Koyu (CARTO)", _CARTO.format("dark_nolabels"), 18,
             "Harita: © OpenStreetMap katkıcıları © CARTO", (14, 14, 16)),
    "acik": ("Açık (CARTO)", _CARTO.format("light_nolabels"), 18,
             "Harita: © OpenStreetMap katkıcıları © CARTO", (240, 240, 238)),
}
VARSAYILAN_STIL = "fiziki"
_BASLIK = {"User-Agent": "StudioFlow/1.0 (harita animasyonu)"}


def stil_secenekleri():
    """Açılır liste için `(görünen ad, değer)` çiftleri."""
    return [(v[0], k) for k, v in STILLER.items()]


class KaroDeposu:
    """Bir stilin karolarını diskten / ağdan getirir; son kullanılanları bellekte tutar."""

    def __init__(self, stil=VARSAYILAN_STIL, klasor=None):
        self.stil = stil if stil in STILLER else VARSAYILAN_STIL
        _ad, self.kalip, self.en_buyuk_zoom, self.atif, self.zemin = STILLER[self.stil]
        self.klasor = Path(klasor or GECICI / "harita_karolari") / self.stil
        self._bellek = {}
        self._kilit = threading.Lock()
        self._oturum = requests.Session()
        self._oturum.headers.update(_BASLIK)
        self.hatali = 0

    def _yol(self, z, x, y):
        return self.klasor / str(z) / str(x) / f"{y}.img"

    def _adres(self, z, x, y):
        return self.kalip.format(z=z, x=x, y=y, s="abcd"[(x + y) % 4])

    def indir(self, z, x, y):
        """Karo diskte yoksa indir. Başarılıysa True; ağ hatası sayılır, yükseltilmez."""
        yol = self._yol(z, x, y)
        if yol.is_file():
            return True
        try:
            yanit = self._oturum.get(self._adres(z, x, y), timeout=ZAMAN_ASIMI)
            if yanit.status_code != 200 or not yanit.content:
                raise ValueError(yanit.status_code)
            Image.open(io.BytesIO(yanit.content)).verify()
        except Exception:
            self.hatali += 1
            return False
        yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = yol.with_suffix(".part")
        gecici.write_bytes(yanit.content)
        gecici.replace(yol)
        return True

    def toplu_indir(self, karolar, ilerleme=None):
        """Karo kümesini paralel indir; `ilerleme(biten, toplam)` ara ara çağrılır."""
        eksik = [k for k in karolar if not self._yol(*k).is_file()]
        if not eksik:
            return 0
        biten = 0
        with ThreadPoolExecutor(PARALEL) as havuz:
            for _ in havuz.map(lambda k: self.indir(*k), eksik):
                biten += 1
                if ilerleme and (biten % 25 == 0 or biten == len(eksik)):
                    ilerleme(biten, len(eksik))
        return len(eksik)

    def karo(self, z, x, y):
        """256×256 RGB karo. Dünya dışı ya da indirilemeyen karo düz zemin rengindedir."""
        n = 1 << z
        if y < 0 or y >= n:
            return None
        x %= n
        anahtar = (z, x, y)
        resim = self._bellek.get(anahtar)
        if resim is not None:
            return resim
        yol = self._yol(z, x, y)
        if not yol.is_file():
            self.indir(z, x, y)
        try:
            resim = Image.open(yol).convert("RGB")
            if resim.size != (KARO, KARO):
                resim = resim.resize((KARO, KARO), Image.LANCZOS)
        except Exception:
            resim = None
        with self._kilit:
            if len(self._bellek) >= BELLEK_SINIRI:
                for eski in list(self._bellek)[:BELLEK_SINIRI // 3]:
                    del self._bellek[eski]
            self._bellek[anahtar] = resim
        return resim
