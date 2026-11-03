"""Kota bekleme listesi: günlük kotası biten hesaplar, kota yenilenene kadar **kullanılmaz**.

Neden (kullanıcı kararı, 14.10.2026): hesap havuzu tükenen hesapları yalnızca bellekte
tutuyordu (`hesap_havuzu.elenen`) ve her çalışma başında listeyi boşaltıyordu. Uygulama
yeniden başlatılınca ya da **Kaldığı yerden devam** edilince kotası saatler önce biten
hesaplar yeniden asıl hesap yapıldı; Guppy'de üç grup 0 adımda kaldı, her çalışma
başında 10–20 istek boşa gitti.

Bu liste diske yazılır ve uygulama kapansa da kalır. Bir hesap ancak servisin **kesin**
günlük kota mesajıyla girer (bkz. `acilis_zamani`); açılış zamanı geçince kendiliğinden
çıkar. Arka planda çalışan bir zamanlayıcı yoktur: her okumada süresi dolan kayıtlar
silinir, bu yüzden uygulama kapalıyken ya da bilgisayar uyurken de doğru çalışır.

Kapsam yalnızca Hugging Face ve Cloudflare'dir:
* **Hugging Face (ZeroGPU):** açılış, mesajdaki "Try again in H:M:S" süresidir. Sabit
  24 saat yanlış olurdu: 54 sn'si kalan hesap 22 dakika sonra yeniden kullanılabildi.
* **Cloudflare Workers AI:** günlük 10.000 nöron her gün 00:00 UTC'de sıfırlanır; 4006
  mesajı saat vermez.

Dakikalık hız sınırı, geçici hata, içerik filtresi ve yetki hatası listeye **girmez**:
yanlış sınıflandırma sağlam bir hesabı bir gün kilitlerdi (14.10.2026'da istek
kimliğindeki "403"/"429" hesapları yanlışlıkla eletmişti).

Dosyada anahtar saklanmaz; yalnızca hesap adı ve anahtarın parmak izi durur. Anahtar
değişirse (ör. token yenilendi) parmak izi tutmaz ve kayıt düşer.
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from studioflow.cekirdek.hatalar import dakikalik_bekleme, hata_etiketle
from studioflow.cekirdek.yollar import AYAR_KLASORU

# Kural (kullanıcı kararı, 21.10.2026): **kota uyarısı veren her hesap listeye girer**,
# hangi servis olursa olsun. Eskiden yalnızca Hugging Face ve Cloudflare tutuluyor, onlarda
# da yalnızca belli kalıptaki mesajlar kabul ediliyordu; kota uyarısı alan hesaplar listede
# görünmüyordu. `None` = bütün servisler.
TAKIPLI = None

# Servis mesajı açılış saati vermezse günlük kotanın sıfırlanma saati (UTC). Gemini'nin
# günlük kotası Pasifik gece yarısı sıfırlanır (yaz saatinde 07:00, kışın 08:00 UTC).
GUNLUK_SIFIRLANMA_UTC = {"cloudflare": 0, "gemini": 8}

# Açılışa eklenen pay: servisin saati ile bizimkinin farkı yüzünden açılır açılmaz
# yeniden kotaya çarpılmasın.
PAY = timedelta(minutes=2)

# Kota mesajı süre vermezse ve servisin sıfırlanma saati bilinmiyorsa: 24 saat. Kotası
# erken açılan hesap API hesapları sekmesinden "listeden çıkar" ile elle geri alınır.
HF_VARSAYILAN = timedelta(hours=24)

# Testler gerçek dosyaya yazmasın diye yol ortam değişkeniyle değiştirilebilir;
# "kapali" listeyi tamamen devre dışı bırakır (eski davranış).
ORTAM_DEGISKENI = "STUDIOFLOW_KOTA_DOSYASI"
KAPALI = "kapali"

_HF_KOTA = re.compile(r"exceeded your [a-z ]*gpu quota")
_HF_SURE = re.compile(r"try again in (?:(\d+) days?,\s*)?(\d+):(\d{1,2}):(\d{1,2})")
_CF_KOTA = re.compile(r"daily free allocation")

# Dosya başka bir program (antivirüs, editör) tarafından o an açıksa Windows yerine
# koymayı reddeder; `proje.dosya` ile aynı kısa yeniden denemeler.
_YAZIM_BEKLEMELERI = (0.05, 0.1, 0.2, 0.3, 0.5)


def _utc(simdi=None):
    return (simdi or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _takipli(hizmet):
    return bool(hizmet) and (TAKIPLI is None or hizmet in TAKIPLI)


def _gunluk_sifirlanma(hizmet, simdi):
    """Servisin günlük kotasının bir sonraki sıfırlanma anı; bilinmiyorsa 24 saat sonra."""
    saat = GUNLUK_SIFIRLANMA_UTC.get(hizmet)
    if saat is None:
        return simdi + HF_VARSAYILAN
    an = simdi.replace(hour=saat, minute=0, second=0, microsecond=0)
    if an <= simdi:
        an += timedelta(days=1)
    return an + PAY


def acilis_zamani(hizmet, mesaj, simdi=None):
    """Mesaj **kota uyarısı** ise hesabın yeniden açılacağı an (UTC), değilse None.

    Önce servisin verdiği süre kullanılır (Hugging Face "Try again in H:M:S", Gemini
    "retry in 6s"); süre yoksa servisin günlük sıfırlanma saati. Yetki, bağlantı ve içerik
    filtresi hataları kota değildir, listeye girmez.
    """
    dusuk = str(mesaj or "").lower()
    simdi = _utc(simdi)
    if hizmet == "huggingface" and _HF_KOTA.search(dusuk):
        sure = _HF_SURE.search(dusuk)
        if sure:
            gun, saat, dakika, saniye = (int(sure.group(i) or 0) for i in range(1, 5))
            return simdi + timedelta(days=gun, hours=saat, minutes=dakika, seconds=saniye) + PAY
        return simdi + HF_VARSAYILAN
    if hizmet == "cloudflare" and _CF_KOTA.search(dusuk):
        return _gunluk_sifirlanma("cloudflare", simdi)
    if hata_etiketle(mesaj) != "KOTA":
        return None
    # Dakikalık hız sınırı yalnızca mesaj bunu **açıkça** söylüyorsa sayılır; tek başına
    # "429" günlük kota da olabilir (Cloudflare'in kesilmiş nöron mesajı, OpenAI
    # "insufficient_quota"). Dakikalık sınır: yalnızca bekleme süresi kadar listede kalır.
    acik_dakikalik = any(k in dusuk for k in ("retry in", "per minute", "perminute",
                                              "rate limit", "requests per min", "rpm"))
    bekleme = dakikalik_bekleme(mesaj) if acik_dakikalik else None
    if bekleme is not None:
        return simdi + timedelta(seconds=bekleme)
    return _gunluk_sifirlanma(hizmet, simdi)


def parmak_izi(degerler):
    """Hesap anahtarlarının kısa özeti: anahtar değişince kayıt düşsün, anahtar yazılmasın."""
    ham = json.dumps(sorted((str(k), str(v or "").strip()) for k, v in (degerler or {}).items()))
    return hashlib.sha256(ham.encode("utf-8")).hexdigest()[:16]


def saat_metni(an, simdi=None):
    """Açılış anını yerel saatle kısa yaz: bugünse `15:23`, değilse `15.10 15:00`."""
    yerel = an.astimezone()
    bugun = _utc(simdi).astimezone().date()
    return f"{yerel:%H:%M}" if yerel.date() == bugun else f"{yerel:%d.%m %H:%M}"


class KotaListesi:
    """Diske yazılan kota bekleme listesi (iş parçacığı güvenli)."""

    def __init__(self, yol=None, saat=None):
        self._yol = yol                 # None → ortam değişkeni ya da varsayılan dosya
        self._saat = saat               # testler için sabit saat: () → UTC datetime
        self._kilit = threading.RLock()
        self._kayitlar = {}             # (hizmet, ad) → kayıt sözlüğü
        self._okunan = None             # dosyanın son okunan değişiklik zamanı

    # ------------------------------------------------------------------ dosya
    @property
    def yol(self):
        if self._yol is not None:
            return self._yol
        ortam = os.environ.get(ORTAM_DEGISKENI)
        if ortam == KAPALI:
            return None
        return Path(ortam) if ortam else AYAR_KLASORU / "kota-bekleme.json"

    def acik(self):
        return self.yol is not None

    def _simdi(self):
        return _utc(self._saat() if self._saat else None)

    def _oku(self):
        """Dosya değiştiyse yeniden oku. Bozuk ya da okunamayan dosya boş liste sayılır."""
        yol = self.yol
        try:
            zaman = yol.stat().st_mtime_ns
        except OSError:
            # Okunmuş dosya silindiyse liste elle temizlenmiştir. Hiç yazılamadıysa
            # (izin yok) bellekteki liste bu çalışma boyunca korunur.
            if self._okunan is not None:
                self._kayitlar, self._okunan = {}, None
            return
        if zaman == self._okunan:
            return
        try:
            ham = json.loads(yol.read_text(encoding="utf-8"))
            kayitlar = {}
            for kayit in ham.get("hesaplar") or []:
                kayit["acilis"] = datetime.fromisoformat(kayit["acilis"]).astimezone(timezone.utc)
                kayitlar[(kayit["hizmet"], kayit["ad"])] = kayit
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            kayitlar = {}
        self._kayitlar, self._okunan = kayitlar, zaman

    def _yaz(self):
        yol = self.yol
        icerik = {"aciklama": "StudioFlow kota bekleme listesi: kotası yenilenene kadar "
                              "kullanılmayan hesaplar. Silinirse liste boşalır.",
                  "hesaplar": [{**k, "acilis": k["acilis"].isoformat()}
                               for k in sorted(self._kayitlar.values(),
                                               key=lambda k: (k["hizmet"], k["acilis"]))]}
        try:
            yol.parent.mkdir(parents=True, exist_ok=True)
            gecici = yol.with_suffix(".gecici")
            gecici.write_text(json.dumps(icerik, ensure_ascii=False, indent=1), encoding="utf-8")
            for bekleme in (*_YAZIM_BEKLEMELERI, None):
                try:
                    os.replace(gecici, yol)
                    break
                except PermissionError:
                    if bekleme is None:
                        raise
                    time.sleep(bekleme)
            self._okunan = yol.stat().st_mtime_ns
        except OSError:
            # Yazılamazsa liste bu çalışma boyunca bellekte sürer; üretim durmaz.
            pass

    def _suresi_dolanlari_at(self):
        simdi = self._simdi()
        dolan = [anahtar for anahtar, k in self._kayitlar.items() if k["acilis"] <= simdi]
        for anahtar in dolan:
            del self._kayitlar[anahtar]
        return bool(dolan)

    # ------------------------------------------------------------------ işlemler
    def kaydet(self, hizmet, kayit, mesaj):
        """Mesaj kesin günlük kotaysa hesabı listeye al; açılış anını döndür (yoksa None)."""
        if not self.acik() or not _takipli(hizmet) or not kayit.get("degerler"):
            return None
        acilis = acilis_zamani(hizmet, mesaj, self._simdi())
        if acilis is None:
            return None
        with self._kilit:
            self._oku()
            self._suresi_dolanlari_at()
            eski = self._kayitlar.get((hizmet, kayit["ad"]))
            if eski and eski["iz"] == parmak_izi(kayit["degerler"]) and eski["acilis"] > acilis:
                acilis = eski["acilis"]
            self._kayitlar[(hizmet, kayit["ad"])] = {
                "hizmet": hizmet, "ad": kayit["ad"], "iz": parmak_izi(kayit["degerler"]),
                "acilis": acilis, "eklendi": self._simdi().isoformat(timespec="seconds"),
                "sebep": " ".join(str(mesaj).split())[:200]}
            self._yaz()
        return acilis

    def bekliyor(self, hizmet, kayit):
        """Hesap kota bekliyorsa açılış anı (UTC), değilse None.

        Anahtarı değişen hesabın kaydı düşer. `degerler` verilmezse (yalnızca ad) kayıt
        ada göre okunur ve dokunulmaz.
        """
        if not self.acik() or not _takipli(hizmet):
            return None
        with self._kilit:
            self._oku()
            degisti = self._suresi_dolanlari_at()
            k = self._kayitlar.get((hizmet, kayit.get("ad")))
            if k and "degerler" in kayit and k["iz"] != parmak_izi(kayit["degerler"]):
                del self._kayitlar[(hizmet, kayit["ad"])]
                k, degisti = None, True
            if degisti:
                self._yaz()
            return k["acilis"] if k else None

    def liste(self, hizmet=None):
        """Bekleyen kayıtlar, açılışı en yakın olan önce."""
        if not self.acik():
            return []
        with self._kilit:
            self._oku()
            if self._suresi_dolanlari_at():
                self._yaz()
            return sorted((dict(k) for k in self._kayitlar.values()
                           if hizmet is None or k["hizmet"] == hizmet),
                          key=lambda k: k["acilis"])

    def cikar(self, hizmet=None, ad=None):
        """Kaydı elle çıkar (`ad` yoksa hizmetin, `hizmet` de yoksa hepsini). Çıkan sayısı."""
        if not self.acik():
            return 0
        with self._kilit:
            self._oku()
            silinecek = [a for a in self._kayitlar
                         if (hizmet is None or a[0] == hizmet) and (ad is None or a[1] == ad)]
            for anahtar in silinecek:
                del self._kayitlar[anahtar]
            if silinecek:
                self._yaz()
            return len(silinecek)


VARSAYILAN = KotaListesi()
