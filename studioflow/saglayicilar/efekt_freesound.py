"""Freesound API ile ses efekti araması ve indirme (yalnızca **CC0** sesler).

Freesound yapay zekâ değil, gerçek kayıtlardan oluşan ücretsiz bir ses kütüphanesidir;
GPU ya da kota harcayan bir üretim yoktur. Arama `license:"Creative Commons 0"`
süzgeciyle yapılır: dönen her ses atıfsız ve ticari kullanıma açıktır. İndirilen
dosya sesin **yüksek kaliteli önizlemesidir** (`preview-hq-mp3`); özgün dosya OAuth2
ister, önizleme ise yalnızca API anahtarıyla alınır ve efekt katmanı için yeterlidir.

Hesaplar aktif olandan başlayarak denenir: yetki (401/403) ya da hız sınırı (429)
alan hesap bu nesne yaşadığı sürece elenir ve **aynı servisin sıradaki hesabı** geçer.
Kimlik bilgisi hata metinlerine yazılmaz.
"""
import re
import time
from pathlib import Path

import requests

from studioflow.ayarlar import api_hesaplari

API = "https://freesound.org/apiv2"
HIZMET = "freesound"
ALAN = "freesound_key"
CC0 = 'license:"Creative Commons 0"'
ALANLAR = "id,name,tags,description,duration,username,license,url,previews,avg_rating,num_ratings"
ZAMAN_ASIMI = 30
# Freesound sınırı dakikada 60 istek: istekler arasında en az bu kadar beklenir.
ISTEK_ARALIGI = 1.05
HIZ_BEKLEMESI = 60           # 429 alınınca aynı hesapla yeniden denemeden önce (sn)


class FreesoundHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilebilen Freesound hatası (anahtar içermez)."""


def _cc0_mu(lisans):
    lisans = str(lisans or "")
    return "publicdomain/zero" in lisans or "Creative Commons 0" in lisans


def _kisa(metin, sinir):
    metin = re.sub(r"\s+", " ", str(metin or "")).strip()
    return metin if len(metin) <= sinir else metin[: sinir - 1].rstrip() + "…"


def aday_kaydi(ham):
    """API sonucunu sade bir sözlüğe indir; CC0 değilse ya da önizlemesi yoksa `None`."""
    if not isinstance(ham, dict) or not _cc0_mu(ham.get("license")):
        return None
    onizleme = (ham.get("previews") or {}).get("preview-hq-mp3") or ""
    if not onizleme:
        return None
    return {"id": int(ham.get("id") or 0), "ad": _kisa(ham.get("name"), 90),
            "etiketler": [str(t) for t in (ham.get("tags") or [])][:10],
            "aciklama": _kisa(ham.get("description"), 180),
            "sure": round(float(ham.get("duration") or 0), 2),
            "sahip": str(ham.get("username") or ""), "url": str(ham.get("url") or ""),
            "onizleme": onizleme,
            "puan": round(float(ham.get("avg_rating") or 0), 2),
            "oy": int(ham.get("num_ratings") or 0)}


class FreesoundEfekt:
    """Freesound araması; hesap havuzu `api_hesaplari` dosyasından okunur."""

    def __init__(self, hesaplar=None, oturum=None, uyu=None, aralik=ISTEK_ARALIGI):
        self.hesaplar = hesaplar or api_hesaplari.VARSAYILAN
        self.oturum = oturum or requests
        self.uyu = uyu or time.sleep
        self.aralik = aralik
        self.elenen = set()
        self.onbellek = {}           # (sorgu, adet, süre) → adaylar; bir iş boyunca
        self._son_istek = 0.0

    def _bekle(self):
        kalan = self._son_istek + self.aralik - time.monotonic()
        if kalan > 0:
            self.uyu(kalan)
        self._son_istek = time.monotonic()

    def _anahtarlar(self):
        adlar = self.hesaplar.hesap_adlari(HIZMET)
        aktif = self.hesaplar.aktif_hesap(HIZMET)
        sira = ([aktif] if aktif in adlar else []) + [ad for ad in adlar if ad != aktif]
        for ad in sira:
            if ad in self.elenen:
                continue
            anahtar = (self.hesaplar.hesap_degerleri(HIZMET, ad).get(ALAN) or "").strip()
            if anahtar:
                yield ad, anahtar

    def anahtar_var_mi(self):
        return any(True for _ in self._anahtarlar())

    def _istek(self, yol, parametreler):
        """Hesapları sırayla dene; ilk başarılı JSON yanıtı döndür."""
        son = "API hesapları sekmesinde Freesound anahtarı yok."
        for ad, anahtar in list(self._anahtarlar()):
            yanit = None
            for deneme in range(2):
                self._bekle()
                try:
                    yanit = self.oturum.get(f"{API}{yol}",
                                            params={**parametreler, "token": anahtar},
                                            timeout=ZAMAN_ASIMI)
                except requests.RequestException as exc:
                    son = f"bağlantı hatası ({type(exc).__name__})"
                    yanit = None
                    break
                # Dakikalık sınır: hesap elenmeden önce bir kez beklenir.
                if yanit.status_code == 429 and deneme == 0:
                    self.uyu(HIZ_BEKLEMESI)
                    continue
                break
            if yanit is None:
                continue
            if yanit.status_code in (401, 403, 429):
                self.elenen.add(ad)
                son = (f"'{ad}' hesabı " + ("hız sınırına takıldı" if yanit.status_code == 429
                                            else "anahtarı geçersiz") + f" (HTTP {yanit.status_code})")
                continue
            if yanit.status_code != 200:
                son = f"HTTP {yanit.status_code}"
                continue
            try:
                return yanit.json()
            except ValueError:
                son = "yanıt okunamadı"
        raise FreesoundHatasi("Freesound'a ulaşılamadı: " + son)

    def ara(self, sorgu, adet=8, sure_alt=0.5, sure_ust=180):
        """CC0 adaylar (puanı yüksek olan önce). Sonuç yoksa boş liste."""
        sorgu = _kisa(sorgu, 80)
        if not sorgu:
            return []
        anahtar = (sorgu.lower(), adet, sure_alt, sure_ust)
        if anahtar in self.onbellek:
            return list(self.onbellek[anahtar])
        veri = self._istek("/search/", {
            "query": sorgu, "filter": f"{CC0} duration:[{sure_alt} TO {sure_ust}]",
            "fields": ALANLAR, "page_size": max(1, min(int(adet), 30)), "sort": "score"})
        adaylar = [aday for aday in (aday_kaydi(ham) for ham in (veri.get("results") or []))
                   if aday]
        self.onbellek[anahtar] = adaylar
        return list(adaylar)

    def bilgi(self, kimlik):
        """Tek sesin aday kaydı (önizleme adresi için); CC0 değilse `None`."""
        return aday_kaydi(self._istek(f"/sounds/{int(kimlik)}/", {"fields": ALANLAR}))

    def indir(self, aday, hedef):
        """Önizlemeyi `hedef`e indir (zaten varsa dokunma); yolu döndür."""
        hedef = Path(hedef)
        if hedef.is_file() and hedef.stat().st_size > 0:
            return hedef
        hedef.parent.mkdir(parents=True, exist_ok=True)
        son = None
        for deneme in range(3):
            try:
                yanit = self.oturum.get(aday["onizleme"], timeout=ZAMAN_ASIMI * 2)
                if yanit.status_code == 200 and yanit.content:
                    gecici = hedef.with_suffix(hedef.suffix + ".gecici")
                    gecici.write_bytes(yanit.content)
                    gecici.replace(hedef)
                    return hedef
                son = f"HTTP {yanit.status_code}"
            except requests.RequestException as exc:
                son = type(exc).__name__
            time.sleep(1 + deneme)
        raise FreesoundHatasi(f"#{aday.get('id')} sesi indirilemedi ({son}).")


VARSAYILAN = FreesoundEfekt()
