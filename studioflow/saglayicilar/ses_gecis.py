"""Parça geçişlerinde ses yüksekliği yumuşatma (ducking).

Gemini her parçayı ayrı okur; yeni parça çoğu zaman öncekinin sonundan daha yüksek sesle
başlar (Gambusia: geçişlerde +2,5…+6,9 dB). Her parça sınırında önceki parçanın son
`OLCUM_SN` saniyesiyle yeni parçanın ilk `OLCUM_SN` saniyesinin konuşma seviyesi
karşılaştırılır; yeni parça `ESIK_DB`'den fazla yüksekse sesi fark kadar kısılarak başlar
ve `DONUS_SN` saniyede yumuşak (kosinüs) bir eğriyle normale döner. Alçak başlayan
parçaya dokunulmaz. Kulak testinde (26.10.2026) belirgin biçimde etkili bulundu.

Yalnızca kazanç değişir: süre, örnekleme hızı ve zamanlama aynı kalır (altyazı ve sahne
yerleşimi etkilenmez).
"""
import numpy as np
import soundfile as sf

OLCUM_SN = 8.0        # sınırın iki yanında ölçülen konuşma süresi
DONUS_SN = 12.0       # kısmanın normale dönme süresi
ESIK_DB = 0.5         # bunun altındaki sıçramaya dokunulmaz
AZAMI_DB = 9.0        # en fazla bu kadar kısılır (yanlış ölçüme karşı)
EN_KISA_SN = 2.0      # sınırın bir yanında bundan az ses varsa geçiş atlanır
_KARE = 0.05          # sn: seviye ölçüm karesi


def _mono(ses):
    return ses.mean(axis=1) if ses.ndim == 2 else ses


def konusma_seviyesi(ses, oran, bas, son):
    """[bas, son) saniyeleri arasındaki konuşmanın seviyesi (dB); sessizlik sayılmaz.

    Ölçülecek ses yoksa `None`.
    """
    parca = _mono(ses)[max(0, int(bas * oran)):max(0, int(son * oran))]
    n = max(1, int(_KARE * oran))
    k = len(parca) // n
    if k < 4:
        return None
    enerji = np.sqrt((parca[:k * n].reshape(k, n).astype(np.float64) ** 2).mean(axis=1))
    db = 20 * np.log10(enerji + 1e-9)
    db = db[db > np.percentile(db, 90) - 16]
    if not len(db) or db.max() < -60:
        return None
    return float(10 * np.log10(np.mean(10 ** (db / 10))))


def ilk_konusma(ses, oran, t, en_cok_sn=5.0):
    """t'den sonra konuşmanın başladığı an (parça sessizlikle başlayabilir)."""
    mono = _mono(ses)
    n = max(1, int(0.02 * oran))
    esik = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2))) * 0.1
    i, sinir = int(t * oran), min(len(mono), int((t + en_cok_sn) * oran))
    while i + n < sinir and float(np.sqrt(np.mean(mono[i:i + n] ** 2))) < esik:
        i += n
    return i / oran


def gecisleri_yumusat(ses, oran, sinirlar):
    """`sinirlar` (sn) noktalarında yüksek başlayan parçaları kıs; `(yeni ses, rapor)` döner.

    Rapor: her sınır için `{"sn", "fark_db", "kisilan_db"}` (kısılmadıysa 0).
    """
    sure = len(ses) / oran
    kazanc = np.zeros(len(ses), dtype=np.float32)
    rapor = []
    for t in sorted(s for s in sinirlar if 0 < s < sure):
        bas = ilk_konusma(ses, oran, t)
        once = konusma_seviyesi(ses, oran, max(0.0, t - OLCUM_SN), t)
        sonra = konusma_seviyesi(ses, oran, bas, min(sure, bas + OLCUM_SN))
        yeterli = t >= EN_KISA_SN and sure - bas >= EN_KISA_SN
        fark = (sonra - once) if (once is not None and sonra is not None and yeterli) else None
        kis = min(AZAMI_DB, fark) if fark is not None and fark > ESIK_DB else 0.0
        rapor.append({"sn": round(t, 2), "fark_db": None if fark is None else round(fark, 2),
                      "kisilan_db": round(kis, 2)})
        if not kis:
            continue
        i0, i1 = int(bas * oran), min(len(ses), int((bas + DONUS_SN) * oran))
        egri = -kis * (0.5 + 0.5 * np.cos(np.pi * np.linspace(0, 1, i1 - i0, dtype=np.float32)))
        kazanc[int(t * oran):i0] = np.minimum(kazanc[int(t * oran):i0], -kis)
        kazanc[i0:i1] = np.minimum(kazanc[i0:i1], egri)
    carpan = 10 ** (kazanc / 20)
    yeni = ses * (carpan[:, None] if ses.ndim == 2 else carpan)
    return np.clip(yeni, -1.0, 1.0).astype(np.float32), rapor


def dosyada_yumusat(yol, sinirlar):
    """WAV dosyasını yerinde yumuşat; raporu döndürür. Hiçbir şey kısılmadıysa dosyaya dokunmaz."""
    ses, oran = sf.read(str(yol), dtype="float32")
    yeni, rapor = gecisleri_yumusat(ses, oran, sinirlar)
    if any(r["kisilan_db"] for r in rapor):
        sf.write(str(yol), yeni, oran, subtype="PCM_16")
    return rapor


def rapor_ozeti(rapor):
    """Durum satırı için kısa özet ('' = kısılan geçiş yok)."""
    kisilan = [r for r in rapor if r["kisilan_db"]]
    if not kisilan:
        return ""
    return (f"{len(kisilan)}/{len(rapor)} parça geçişinde ses yumuşatıldı "
            f"(en çok {max(r['kisilan_db'] for r in kisilan):.1f} dB)")
