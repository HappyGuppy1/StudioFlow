"""StudioFlow projesini editörün zaman çizelgesi modeline çevirir (yalnızca okur).

Model:
    proje  → ad, durum, süre, tuval, sahneler, izler (seslendirme · dublaj · müzik ·
             altyazı · efekt), birleşik video varsa adresi
    sahne  → numara, başlangıç/bitiş saniyesi, durum, anlatım, kare ve klip adresi
             (ayrıntıda prompt'lar ve kontrol listesi)

Medya adresleri `/medya/<proje>/<projeye göreli yol>` biçimindedir; dosyayı sunan uç
yolun proje klasöründen çıkmadığını ayrıca denetler (bkz. `proje_dosyasi`).
"""
import re
from pathlib import Path
from urllib.parse import quote

from sunucu import ayar  # noqa: F401  (studioflow paketini bağlar)
from studioflow.ayarlar import bicimler
from studioflow.ayarlar.bicimler import DURUM_ADI
from studioflow.proje import depo
from studioflow.proje.dosya import proje_oku
from studioflow.proje.katmanlar import diller, efekt_ekleme, muzik

DURUMLAR = ("TAMAM", "YARIM", "HATA", "BEKLİYOR")


class ProjeYok(LookupError):
    """İstenen proje `projects/` içinde yok ya da okunamıyor."""


def _klasor(ad):
    klasor = depo.guvenli_klasor(ad)
    if klasor is None:
        raise ProjeYok(ad)
    return klasor


def _taslak():
    from sunucu import taslak   # döngüsel içe aktarma olmasın
    return taslak


def _oku(ad):
    klasor = _klasor(ad)
    veri = proje_oku(klasor)
    if veri is None:
        raise ProjeYok(ad)
    return klasor, veri


def medya_adresi(ad, goreli):
    """Projeye göreli dosyanın adresi; dosya yoksa `None`."""
    if not goreli:
        return None
    klasor = depo.guvenli_klasor(ad)
    yol = klasor / goreli if klasor is not None else None
    if yol is None or not yol.is_file():
        return None
    # Sürüm eki: kare/klip yenilenince adı aynı kalır; değişiklik zamanı adrese girer ki
    # tarayıcı eski dosyayı önbellekten göstermesin.
    return (f"/medya/{quote(klasor.name)}/{quote(str(goreli).replace(chr(92), '/'))}"
            f"?v={int(yol.stat().st_mtime)}")


def proje_dosyasi(ad, goreli):
    """`/medya` ucunun dosyası: proje klasörünün içindeki gerçek bir dosya, yoksa `None`."""
    klasor = depo.guvenli_klasor(ad)
    if klasor is None:
        return None
    try:
        yol = (klasor / goreli).resolve()
        yol.relative_to(klasor.resolve())
    except (ValueError, OSError):
        return None
    return yol if yol.is_file() else None


def diskteki_durum(klasor):
    """`proje.txt` başlığındaki çalışma durumu (`calisiyor`, `bekliyor`…); okunamazsa boş."""
    try:
        with open(klasor / "proje.txt", encoding="utf-8") as dosya:
            for _ in range(15):
                satir = dosya.readline()
                if satir.startswith("Durum"):
                    metin = satir.split(":", 1)[1].split("·")[0].strip()
                    return next((k for k, v in DURUM_ADI.items() if v == metin), metin)
    except OSError:
        pass
    return ""


def _saniye(deger, varsayilan=0.0):
    try:
        return round(float(deger), 3)
    except (TypeError, ValueError):
        return varsayilan


def _durum(klasor, adim):
    """Adımın görünen durumu: TAMAM ama klibi diskte yoksa YARIM (ilerleme çubuğuyla aynı)."""
    durum = (adim.get("durum") or "BEKLİYOR").upper()
    if durum == "TAMAM" and not (adim.get("video") and (klasor / adim["video"]).is_file()):
        return "YARIM"
    return durum if durum in DURUMLAR else "BEKLİYOR"


def _sahne(ad, klasor, adim):
    bas, bit = _saniye(adim.get("start")), _saniye(adim.get("end"))
    return {
        "index": int(adim["index"]),
        "bas": bas, "bit": bit, "sure": round(max(bit - bas, 0.0), 3),
        "durum": _durum(klasor, adim),
        "metin": (adim.get("text") or "").strip(),
        "kare": medya_adresi(ad, adim.get("gorsel")),
        "klip": medya_adresi(ad, adim.get("video")),
        "hata": (adim.get("hata") or "").strip(),
    }


def _tuval(veri):
    """Çıktı tuvali (genişlik × yükseklik): projenin biçiminden, yoksa görsel ölçüsünden."""
    ayarlar = veri.get("ayarlar") or {}
    bicim = bicimler.CIKTI_BICIMLERI.get((ayarlar.get("video") or {}).get("bicim") or "")
    if bicim:
        return {"genislik": bicim["genislik"], "yukseklik": bicim["yukseklik"],
                "ad": bicim["ad"]}
    gorsel = ayarlar.get("gorsel") or {}
    return {"genislik": int(gorsel.get("width") or 1920),
            "yukseklik": int(gorsel.get("height") or 1080), "ad": "özel"}


def srt_oku(yol):
    """SRT dosyasını bloklara çevir: `[{bas, bit, metin}]` (saniye). Bozuk blok atlanır."""
    try:
        metin = Path(yol).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    zaman = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    bloklar = []
    for parca in re.split(r"\r?\n\s*\r?\n", metin.strip()):
        satirlar = [s for s in parca.splitlines() if s.strip()]
        for sira, satir in enumerate(satirlar):
            eslesme = zaman.search(satir)
            if not eslesme:
                continue
            s = [int(x) for x in eslesme.groups()]
            bas = s[0] * 3600 + s[1] * 60 + s[2] + s[3] / 1000
            bit = s[4] * 3600 + s[5] * 60 + s[6] + s[7] / 1000
            yazi = " ".join(satirlar[sira + 1:]).strip()
            if yazi and bit > bas:
                bloklar.append({"bas": round(bas, 3), "bit": round(bit, 3), "metin": yazi})
            break
    return bloklar


def _izler(ad, klasor, veri):
    """Ses ve altyazı izleri: kayıtlar, dosya adresleri ve videoya ekli olanlar."""
    ses = veri.get("ses") or {}
    dublaj_ekli = (veri.get("ekli_dublaj") or veri.get("ekli_dil") or "").strip()
    muzik_ekli = (set(veri.get("muzikler") or [])
                  if veri.get("muzik_ekleme") == "TAMAM" else set())
    efekt_ekli = efekt_ekleme.ekli_efekt_adi(ad)
    altyazi_ekli = diller.ekli_altyazi_adi(ad)
    return {
        "seslendirme": [{
            "ad": "anlatım", "dil": "", "ses": medya_adresi(ad, ses.get("dosya")),
            "sure": _saniye(ses.get("sure")),
            "ekli": veri.get("ses_ekleme") == "TAMAM" and not dublaj_ekli,
        }] if ses.get("durum") == "TAMAM" else [],
        "dublaj": [{
            "ad": k["ad"], "dil": k.get("dil", ""), "ses": medya_adresi(ad, k.get("dosya")),
            "altyazi": medya_adresi(ad, k.get("altyazi")), "sure": _saniye(k.get("sure")),
            "ekli": k["ad"] == dublaj_ekli,
        } for k in diller.dublaj_listesi(ad)],
        "muzik": [{
            "ad": k["ad"], "ses": medya_adresi(ad, k.get("dosya")),
            "sure": _saniye(k.get("sure")), "ekli": k["ad"] in muzik_ekli,
        } for k in muzik.muzik_listesi(ad)],
        "altyazi": [{
            "ad": k["ad"], "dil": k.get("dil", ""), "srt": medya_adresi(ad, k.get("dosya")),
            "blok": k.get("blok"), "ekli": k["ad"] == altyazi_ekli,
        } for k in diller.altyazi_listesi(ad)],
        "efekt": [{
            "ad": k["ad"], "ses": medya_adresi(ad, k.get("dosya")),
            "sure": _saniye(k.get("sure")), "ekli": k["ad"] == efekt_ekli,
        } for k in efekt_ekleme.efekt_listesi(ad)],
    }


def _taslak_ozeti(kayit):
    return {"ad": kayit["ad"], "taslak": True, "sahne": 0, "tamam": 0, "sure": 0.0,
            "kapak": None, "tuval": _tuval(kayit), "guncellendi": kayit.get("guncellendi") or ""}


def projeler():
    """Kütüphane: taslaklar (başlatılmamış projeler) ve projelerin özeti."""
    sonuc = [_taslak_ozeti(k) for k in _taslak().liste()]
    for ad in depo.liste():
        try:
            klasor, veri = _oku(ad)
        except ProjeYok:
            continue
        adimlar = veri.get("adimlar") or []
        tamam = sum(1 for adim in adimlar if _durum(klasor, adim) == "TAMAM")
        kapak = next((adim.get("gorsel") for adim in adimlar
                      if adim.get("gorsel") and (klasor / adim["gorsel"]).is_file()), None)
        sonuc.append({
            "ad": ad, "taslak": False, "sahne": len(adimlar), "tamam": tamam,
            "sure": _saniye((veri.get("ses") or {}).get("sure"))
            or (_saniye(adimlar[-1].get("end")) if adimlar else 0.0),
            "kapak": medya_adresi(ad, kapak), "tuval": _tuval(veri),
            "guncellendi": veri.get("guncellendi") or "",
        })
    return sonuc


def _taslak_modeli(kayit):
    """Başlatılmamış proje: sahne ve iz yok; ayarlar ve metin taslakta."""
    return {"ad": kayit["ad"], "taslak": True, "durum": "taslak",
            "durum_adi": "taslak · başlatılmadı", "sure": 0.0, "tuval": _tuval(kayit),
            "sahneler": [], "sayim": {d: 0 for d in DURUMLAR},
            "izler": {"seslendirme": [], "dublaj": [], "muzik": [], "altyazi": [], "efekt": []},
            "video": None, "gorsel_onay": "", "video_servisi": "",
            "sahne_plani": bool(kayit.get("sahne_on_plan"))}


def _muzik_tercihi(ad):
    """Müzik bölümündeki tekrar ve ducking tercihi (önizleme ve dışa aktarma uygular)."""
    try:
        durum = muzik.muzik_durumu(ad) or {}
    except Exception:
        durum = {}
    return {"tekrarla": bool(durum.get("tekrarla")), "ducking": durum.get("ducking") is not False}


def proje(ad):
    """Editörün açtığı projenin tamamı: sahneler, izler, tuval ve süre."""
    taslak = _taslak()
    if taslak.var_mi(ad) and not taslak.basladi_mi(ad):
        return _taslak_modeli(taslak.oku(ad))
    klasor, veri = _oku(ad)
    sahneler = [_sahne(ad, klasor, adim) for adim in veri.get("adimlar") or []]
    sure = max([_saniye((veri.get("ses") or {}).get("sure"))]
               + [sahne["bit"] for sahne in sahneler] + [0.0])
    sayim = {durum: sum(1 for s in sahneler if s["durum"] == durum) for durum in DURUMLAR}
    return {
        "ad": klasor.name, "taslak": False,
        "durum": diskteki_durum(klasor) or veri.get("durum") or "",
        "durum_adi": DURUM_ADI.get(diskteki_durum(klasor), diskteki_durum(klasor)),
        "sure": round(sure, 3),
        "tuval": _tuval(veri), "sahneler": sahneler, "sayim": sayim,
        "izler": _izler(ad, klasor, veri),
        "video": medya_adresi(ad, "proje.mp4"),
        "gorsel_onay": veri.get("gorsel_onay") or "",
        "video_servisi": veri.get("video_servisi") or "",
        "muzik_tercih": _muzik_tercihi(ad),
        "muzik_sabit": _muzik_sabit(ad, klasor),
    }


def _muzik_sabit(ad, klasor):
    """Projeye eklenmiş, ducking'i uygulanmış sabit müzik (önizleme bunu çalar); yoksa None."""
    try:
        yol, bilgi = muzik.sabit_muzik(klasor)
    except Exception:
        return None
    if yol is None:
        return None
    return {"ses": medya_adresi(ad, f"{yol.parent.name}/{yol.name}"), "sure": bilgi.get("sure"),
            "konusma": bilgi.get("konusma") or "", "muzikler": bilgi.get("muzikler") or [],
            "tarih": bilgi.get("tarih") or ""}


def sahne(ad, index):
    """Sağ panel: sahnenin prompt'ları, kontrol listesi ve karakterleri."""
    klasor, veri = _oku(ad)
    adim = next((a for a in veri.get("adimlar") or [] if str(a.get("index")) == str(index)),
                None)
    if adim is None:
        raise ProjeYok(f"{ad} · sahne {index}")
    ayrinti = _sahne(ad, klasor, adim)
    ayrinti.update({
        "gorsel_prompt": adim.get("image_prompt") or "",
        "negatif_prompt": adim.get("negative_prompt") or "",
        "video_prompt": adim.get("video_prompt") or "",
        "kontrol": adim.get("kontrol") or "",
        "karakterler": adim.get("karakterler") or "",
        "bitti": adim.get("bitti") or "",
    })
    return ayrinti


def altyazi_bloklari(ad, kayit_adi):
    """Kayıtlı altyazının blokları (zaman çizelgesi izi ve önizleme yazısı için)."""
    klasor = _klasor(ad)
    kayit = next((k for k in diller.altyazi_listesi(ad) if k["ad"] == kayit_adi), None)
    if kayit is None:
        raise ProjeYok(f"{ad} · altyazı {kayit_adi}")
    return srt_oku(klasor / kayit["dosya"])


def proje_kaydi(ad):
    """`proje.txt`'in metni (StudioFlow › Ayarlar › proje.txt)."""
    klasor = _klasor(ad)
    try:
        return (klasor / "proje.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise ProjeYok(ad) from None


def proje_dosyalari(ad):
    """Proje klasöründeki dosyalar (ara dosyalar hariç), adresleriyle."""
    klasor = _klasor(ad)
    sonuc = []
    for yol in sorted(klasor.rglob("*")):
        goreli = yol.relative_to(klasor)
        if not yol.is_file() or goreli.parts[0] in (depo.CALISMA_KLASORU, "disa-aktarim"):
            continue
        sonuc.append({"yol": goreli.as_posix(), "boyut": yol.stat().st_size,
                      "adres": medya_adresi(ad, goreli.as_posix())})
    return sonuc
