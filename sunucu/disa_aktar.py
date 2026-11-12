"""Dışa aktarma: işaretli izlerden tek video (`projects/<ad>/disa-aktarim/*.mp4`).

İzler ve anlamları:
    video        her sahne kendi süresinde: klibi varsa klip, yoksa karesi, o da yoksa
                 siyah. İşaretsizse bütün video siyah (yalnızca ses ve altyazı).
    seslendirme  anlatım sesi (`ses/seslendirme.wav`)
    dublaj       seçili dublaj kaydı
    muzik        seçili müzikler sırayla (kaydedilirken seviye dosyaya işlenmiştir)
    altyazi      seçili altyazı, StudioFlow'un gömme görünümüyle (yazı tipi, renk, seviye)
    efekt        seçili ses efekti izi

İşaretsiz iz videoya girmez. Önizlemedeki göz yalnızca önizlemeyi etkiler; dışa
aktarmaya yalnızca işaretler bakar. Ayarlar `disa-aktarim/ayar.json`'da durur;
`proje.txt`'e ve StudioFlow'un üretim dosyalarına dokunulmaz.

Sahne parçaları `disa-aktarim/.parca/` altında saklanır: aynı tuvalde ve aynı kaynakla
ikinci dışa aktarma yeniden kodlama yapmaz.
"""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from sunucu import ayar  # noqa: F401  (studioflow paketini bağlar)
from sunucu import veri
from studioflow.altyazi import gorunum
from studioflow.ayarlar.bicimler import CIKTI_FPS
from studioflow.cekirdek.ffmpeg import VARSAYILAN as FFMPEG
from studioflow.proje import depo
from studioflow.proje.birlestirme import sure_doldurma
from studioflow.proje.dosya import proje_oku
from studioflow.proje.dosya_yollari import anlatim_suzgeci
from studioflow.proje.katmanlar import diller, efekt_ekleme, muzik
from studioflow.proje.sabitler import (MUZIK_DUCKING_ATAK, MUZIK_DUCKING_BIRAKMA,
                                       MUZIK_DUCKING_ESIK, MUZIK_DUCKING_ORAN)

# Karışımdaki her ses aynı biçime getirilir (sidechaincompress aynı hız ve kanal ister).
_ESIT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

IZLER = ("video", "seslendirme", "dublaj", "muzik", "altyazi", "efekt")
SES_IZLERI = ("seslendirme", "dublaj", "muzik", "efekt")
KLASOR = "disa-aktarim"
_PENCERESIZ = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DisaAktarimHatasi(RuntimeError):
    """Dışa aktarma yapılamadı; mesaj kullanıcıya gösterilir."""


# ── Ayarlar (işaretler ve seçimler) ─────────────────────────────────────────────
def _ayar_yolu(klasor):
    return klasor / KLASOR / "ayar.json"


def varsayilan_ayar(ad):
    """İlk açılışta işaretler StudioFlow'daki videonun hâlini izler: videoya eklenmiş
    katmanlar işaretli gelir, eklenmemiş dublaj/altyazı/efekt işaretsiz."""
    klasor = depo.guvenli_klasor(ad)
    durum = proje_oku(klasor) if klasor else None
    if durum is None:
        raise veri.ProjeYok(ad)
    dublajlar = [k["ad"] for k in diller.dublaj_listesi(ad)]
    altyazilar = [k["ad"] for k in diller.altyazi_listesi(ad)]
    efektler = [k["ad"] for k in efekt_ekleme.efekt_listesi(ad)]
    # Ekli sayılan kayıt listede de olmalı: eski projelerde `Ekli dil` kaydı olmayan bir dili
    # gösterebilir; o zaman seslendirme işaretli kalsın.
    dublaj_ekli = diller.ekli_dublaj_adi(ad)
    dublaj_ekli = dublaj_ekli if dublaj_ekli in dublajlar else ""
    altyazi_ekli = diller.ekli_altyazi_adi(ad)
    altyazi_ekli = altyazi_ekli if altyazi_ekli in altyazilar else ""
    efekt_ekli = efekt_ekleme.ekli_efekt_adi(ad) or ""
    efekt_ekli = efekt_ekli if efekt_ekli in efektler else ""
    muzikler = [k["ad"] for k in muzik.muzik_listesi(ad)]
    ekli_muzik = [m for m in (durum.get("muzikler") or []) if m in muzikler]
    return {
        "isaret": {
            "video": True,
            "seslendirme": (durum.get("ses") or {}).get("durum") == "TAMAM" and not dublaj_ekli,
            "dublaj": bool(dublaj_ekli),
            "muzik": durum.get("muzik_ekleme") == "TAMAM" and bool(ekli_muzik),
            "altyazi": bool(altyazi_ekli),
            "efekt": bool(efekt_ekli),
        },
        "dublaj": dublaj_ekli or (dublajlar[0] if dublajlar else ""),
        "altyazi": altyazi_ekli or (altyazilar[0] if altyazilar else ""),
        "efekt": efekt_ekli or (efektler[0] if efektler else ""),
        "muzik": ekli_muzik,          # yalnızca projeye eklenmiş müzikler ("Videoya ekle")
        # v0.5 · ses: iz başına seviye (%, 100 = dosyanın kendi seviyesi), müzik karartması
        "seviye": {iz: 100 for iz in SES_IZLERI},
        "muzik_karartma": {"giris": 0.0, "cikis": 0.0},
        # v0.6 · kurgu: çıkarılan sahneler (süreleri bütün izlerden kesilir) ve aralık
        "cikarilan": [],
        "aralik": {"bas": None, "bit": None},
    }


def ayar_oku(ad):
    """Kayıtlı ayar; yoksa ya da bozuksa varsayılan. Silinmiş kayıtlar ayıklanır."""
    temel = varsayilan_ayar(ad)
    klasor = depo.guvenli_klasor(ad)
    try:
        kayitli = json.loads(_ayar_yolu(klasor).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return temel
    return ayar_dogrula(ad, kayitli, temel)


def ayar_dogrula(ad, gelen, temel=None):
    """Gelen ayarı güvenli biçime getir: bilinmeyen iz yok sayılır, olmayan kayıt seçilmez."""
    temel = temel or varsayilan_ayar(ad)
    gelen = gelen if isinstance(gelen, dict) else {}
    isaret = dict(temel["isaret"])
    for iz, deger in (gelen.get("isaret") or {}).items():
        if iz in IZLER:
            isaret[iz] = bool(deger)
    adlar = {
        "dublaj": [k["ad"] for k in diller.dublaj_listesi(ad)],
        "altyazi": [k["ad"] for k in diller.altyazi_listesi(ad)],
        "efekt": [k["ad"] for k in efekt_ekleme.efekt_listesi(ad)],
    }
    sonuc = {"isaret": isaret}
    for alan, gecerli in adlar.items():
        secim = gelen.get(alan, temel[alan])
        sonuc[alan] = secim if secim in gecerli else temel[alan]
    muzikler = [k["ad"] for k in muzik.muzik_listesi(ad)]
    secilen = gelen.get("muzik", temel["muzik"])
    sonuc["muzik"] = ([m for m in dict.fromkeys(secilen) if m in muzikler]
                      if isinstance(secilen, list) else temel["muzik"])
    seviye = dict(temel["seviye"])
    for iz, deger in (gelen.get("seviye") or {}).items():
        if iz in SES_IZLERI:
            seviye[iz] = int(_sinirla(deger, 0, 200, 100))
    sonuc["seviye"] = seviye
    karartma = gelen.get("muzik_karartma") or {}
    sonuc["muzik_karartma"] = {k: _sinirla(karartma.get(k), 0, 10, 0.0) for k in ("giris", "cikis")}
    sahneler = {int(a["index"]) for a in (proje_oku(depo.guvenli_klasor(ad)) or {}).get("adimlar") or []}
    cikarilan = gelen.get("cikarilan") or []
    sonuc["cikarilan"] = sorted({int(i) for i in cikarilan
                                 if str(i).lstrip("-").isdigit() and int(i) in sahneler})
    aralik = gelen.get("aralik") or {}
    bas = _sinirla(aralik.get("bas"), 0, 1e7, None)
    bit = _sinirla(aralik.get("bit"), 0, 1e7, None)
    if bas is not None and bit is not None and bit <= bas:
        bas = bit = None
    sonuc["aralik"] = {"bas": bas, "bit": bit}
    return sonuc


def _sinirla(deger, alt, ust, varsayilan):
    try:
        return round(min(max(float(deger), alt), ust), 3)
    except (TypeError, ValueError):
        return varsayilan


def ayar_yaz(ad, gelen):
    """Gelen **değişikliği** kayıtlı ayarın üzerine işle ve kaydet.

    20.10.2026: editör her değişiklikte elindeki ayarın tamamını gönderiyordu; bir katman
    işi (ör. "Videoya ekle" müziği) ayarı sunucuda değiştirdikten sonra editörün eski
    kopyası müziği geri siliyordu. Artık yalnızca gelen alanlar değişir; sözlük alanları
    (işaret, seviye, karartma) anahtar anahtar birleştirilir.
    """
    klasor = depo.guvenli_klasor(ad)
    if klasor is None:
        raise veri.ProjeYok(ad)
    gelen = gelen if isinstance(gelen, dict) else {}
    birlesik = ayar_oku(ad)
    for alan, deger in gelen.items():
        if alan in ("isaret", "seviye", "muzik_karartma") and isinstance(deger, dict):
            birlesik[alan] = {**birlesik.get(alan, {}), **deger}
        else:
            birlesik[alan] = deger
    sonuc = ayar_dogrula(ad, birlesik)
    yol = _ayar_yolu(klasor)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")
    return sonuc


# ── ffmpeg yardımcıları ─────────────────────────────────────────────────────────
def _ffmpeg():
    yol = shutil.which("ffmpeg")
    if yol:
        return yol
    # Açılıştaki indirme sürüyorsa biter, hiç başlamadıysa şimdi indirilir (~110 MB).
    from sunucu import ffmpeg_indir
    try:
        return ffmpeg_indir.hazirla()
    except RuntimeError as hata:
        raise DisaAktarimHatasi(f"{str(hata).rstrip('.')}. İnternet bağlantını kontrol edip uygulamayı yeniden "
                                "aç; ffmpeg otomatik indirilir.") from hata


def _calistir(komut, cwd=None, is_=None):
    """ffmpeg'i çalıştır; iptal edilirse süreci durdur. Hata metninin son satırını döndür."""
    surec = subprocess.Popen(komut, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=_PENCERESIZ)
    if is_ is not None:
        is_.surec = surec
    _, hata = surec.communicate()
    if is_ is not None:
        is_.surec = None
        if is_.iptal:
            raise DisaAktarimHatasi("Dışa aktarma iptal edildi.")
    if surec.returncode != 0:
        satirlar = [s for s in (hata or "").strip().splitlines() if s.strip()]
        raise DisaAktarimHatasi("ffmpeg hatası: " + (satirlar[-1] if satirlar else "bilinmiyor"))


def _tuval_zinciri(g, y):
    # Renk aralığı her parçada aynı (tv) olmalı: kareden (JPEG, tam aralık) üretilen parça
    # yuvj420p, klipten üretilen yuv420p olunca birleşik videoda parça sınırında biçim
    # değişiyor; ffmpeg filtre zincirini yeniden kurup kesme (select/trim) sayacını
    # sıfırlıyor ve kareler kayboluyordu.
    return (f"scale={g}:{y}:force_original_aspect_ratio=increase:out_range=tv,crop={g}:{y},"
            f"fps={CIKTI_FPS},setsar=1,format=yuv420p")


_KODLAYICI = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
              "-color_range", "tv", "-r", str(CIKTI_FPS)]
PARCA_SURUMU = "v2"   # parça üretimi değişince eski önbellek parçaları kullanılmasın


def _parca(ffmpeg, klasor, sahne_adim, sure, g, y, parca_klasoru, is_):
    """Sahnenin tuval parçası (tam `sure` saniye): klip > kare > siyah. Önbellekten gelir."""
    klip = sahne_adim.get("video") and klasor / sahne_adim["video"]
    kare = sahne_adim.get("gorsel") and klasor / sahne_adim["gorsel"]
    index = int(sahne_adim["index"])
    if klip and klip.is_file():
        kaynak, tur = klip, "klip"
    elif kare and kare.is_file():
        kaynak, tur = kare, "kare"
    else:
        kaynak, tur = None, "siyah"
    once = sonra = ""
    if tur == "klip":
        # Kısa klip yavaşlatılarak doldurulur (bkz. `birlestirme.sure_doldurma`).
        once, sonra = sure_doldurma(FFMPEG.medya_suresi(kaynak), sure)
    if tur == "siyah":   # siyah parça sahneye bağlı değildir: süre ve tuvale göre paylaşılır
        hedef = parca_klasoru / f"siyah-{g}x{y}-{sure:.3f}-{PARCA_SURUMU}.mp4"
    else:
        ek = "-yav" if once else ""      # eski (donan kareli) önbellek parçası kullanılmasın
        hedef = parca_klasoru / f"sahne-{index:03d}-{g}x{y}-{tur}-{sure:.3f}-{PARCA_SURUMU}{ek}.mp4"
    if hedef.is_file() and (kaynak is None or hedef.stat().st_mtime >= kaynak.stat().st_mtime):
        return hedef
    if tur != "siyah":
        for eski in parca_klasoru.glob(f"sahne-{index:03d}-*.mp4"):
            eski.unlink(missing_ok=True)
    taban = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if tur == "klip":
        # Klip sahneden kısaysa önce yavaşlatılır, kalan fark son kareyle kapanır; tpad
        # her durumda güvenlik payıdır (ses kaymasın).
        komut = taban + ["-i", str(kaynak), "-an", "-vf",
                         once + _tuval_zinciri(g, y) + (sonra or
                         f",tpad=stop_mode=clone:stop_duration={sure:.3f}"),
                         "-t", f"{sure:.3f}"]
    elif tur == "kare":
        komut = taban + ["-loop", "1", "-framerate", str(CIKTI_FPS), "-i", str(kaynak),
                         "-vf", _tuval_zinciri(g, y), "-t", f"{sure:.3f}"]
    else:
        komut = taban + ["-f", "lavfi", "-i", f"color=c=black:s={g}x{y}:r={CIKTI_FPS}",
                         "-vf", "format=yuv420p", "-t", f"{sure:.3f}"]
    gecici = hedef.with_suffix(".yaziliyor.mp4")
    _calistir(komut + _KODLAYICI + [str(gecici)], is_=is_)
    gecici.replace(hedef)
    return hedef


def altyazi_stili(srt, g, y, durum):
    """Altyazının gömme stili: StudioFlow'un videoya gömerken kullandığıyla aynı.

    `altyazi_olcu` SRT dosyasının **ham satırlarını** bekler (boş satır bloğu bitirir);
    bloklar birleştirilip verilirse bütün dosya tek blok sayılır ve yazı en küçük
    boyuta iner. StudioFlow da dosyayı satır satır okuyarak verir (`diller`).
    """
    try:
        satirlar = Path(srt).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        satirlar = None
    stil, _px, _alt = gorunum.altyazi_olcu(g, y, gorunum.altyazi_ayari(durum), satirlar)
    return stil


# ── İş (arka plan) ──────────────────────────────────────────────────────────────
class Is:
    """Bir projenin dışa aktarma işi: durum, yüzde, mesaj ve çıktı dosyası."""

    def __init__(self, ad):
        self.ad = ad
        self.durum = "bekliyor"      # bekliyor · calisiyor · bitti · hata · iptal
        self.yuzde = 0
        self.mesaj = ""
        self.dosya = None
        self.hedef = None            # kullanıcının seçtiği konum (yoksa disa-aktarim/)
        self.baslangic = time.time()
        self.iptal = False
        self.surec = None

    def ozet(self):
        adres = None
        if self.dosya:
            # `/medya` yalnızca proje klasörünün içini sunar; dışarıdaki dosyanın adresi yok.
            klasor = depo.guvenli_klasor(self.ad)
            try:
                adres = veri.medya_adresi(self.ad, Path(self.dosya).relative_to(klasor))
            except (TypeError, ValueError):
                adres = None
        return {"durum": self.durum, "yuzde": self.yuzde, "mesaj": self.mesaj,
                "dosya": adres, "yol": self.dosya or self.hedef,
                "dosya_adi": Path(self.dosya).name if self.dosya else None,
                "sure": round(time.time() - self.baslangic)}


_ISLER = {}
_KILIT = threading.Lock()


def is_durumu(ad):
    is_ = _ISLER.get(ad)
    return is_.ozet() if is_ else None


def varsayilan_hedef(ad):
    """Konum seçilmezse videonun yazılacağı yer: `<proje>/disa-aktarim/<ad>-<zaman>.mp4`."""
    klasor = depo.guvenli_klasor(ad)
    if klasor is None:
        raise veri.ProjeYok(ad)
    return str(klasor / KLASOR / f"{klasor.name}-{time.strftime('%Y%m%d-%H%M%S')}.mp4")


def hedef_dogrula(hedef):
    """Kullanıcının seçtiği kayıt yolu: tam yol, `.mp4` uzantılı, klasörü var."""
    hedef = str(hedef or "").strip().strip('"')
    if not hedef:
        return None
    yol = Path(hedef)
    if not yol.is_absolute():
        raise DisaAktarimHatasi("Kayıt konumu tam bir yol olmalı (ör. C:\\Videolar\\film.mp4).")
    if yol.suffix.lower() != ".mp4":
        yol = yol.with_name(yol.name + ".mp4")
    if not yol.parent.is_dir():
        raise DisaAktarimHatasi(f"Klasör bulunamadı: {yol.parent}")
    return str(yol)


def baslat(ad, hedef=None):
    """İşi arka planda başlat; aynı anda tek dışa aktarma çalışır."""
    hedef = hedef_dogrula(hedef)
    with _KILIT:
        if any(i.durum == "calisiyor" for i in _ISLER.values()):
            raise DisaAktarimHatasi("Başka bir dışa aktarma sürüyor; bitmesini bekle ya da iptal et.")
        is_ = Is(ad)
        is_.hedef = hedef
        is_.durum = "calisiyor"
        _ISLER[ad] = is_
    threading.Thread(target=_calis, args=(is_,), name=f"disa-aktar-{ad}", daemon=True).start()
    return is_.ozet()


def iptal_et(ad):
    is_ = _ISLER.get(ad)
    if is_ and is_.durum == "calisiyor":
        is_.iptal = True
        if is_.surec is not None:
            is_.surec.kill()
    return is_durumu(ad)


def _calis(is_):
    try:
        uretilen = Path(disa_aktar(is_.ad, is_))
        if is_.hedef and Path(is_.hedef) != uretilen:
            # Video önce disa-aktarim/ altında yazılır (parçalar orada), sonra seçilen
            # konuma taşınır; aynı adlı dosya varsa "Farklı kaydet"te onaylanmıştır.
            _ilerle(is_, 98, f"Seçilen konuma taşınıyor: {is_.hedef}")
            try:
                shutil.move(str(uretilen), is_.hedef)
            except OSError as hata:
                raise DisaAktarimHatasi(f"Video seçilen konuma taşınamadı ({hata}); "
                                        f"dosya burada kaldı: {uretilen}") from None
            uretilen = Path(is_.hedef)
        is_.dosya = str(uretilen)
        is_.durum, is_.yuzde = "bitti", 100
        sure = veri._saniye(subprocess.run(
            [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", is_.dosya], capture_output=True, text=True).stdout.strip())
        dk, sn = divmod(int(round(sure)), 60)
        is_.mesaj = (f"Hazır: {Path(is_.dosya).name} · video {dk}:{sn:02d} · "
                     f"{round(time.time() - is_.baslangic)} sn'de hazırlandı")
    except DisaAktarimHatasi as hata:
        is_.durum = "iptal" if is_.iptal else "hata"
        is_.mesaj = str(hata)
    except Exception as hata:  # beklenmeyen hata da kullanıcıya yazılsın, sunucu düşmesin
        is_.durum, is_.mesaj = "hata", f"Beklenmeyen hata: {hata}"


def _ilerle(is_, yuzde, mesaj):
    if is_ is not None:
        if is_.iptal:
            raise DisaAktarimHatasi("Dışa aktarma iptal edildi.")
        is_.yuzde, is_.mesaj = int(yuzde), mesaj


def korunan_araliklar(sahneler, toplam, cikarilan=(), aralik=None):
    """Videoda kalacak zaman aralıkları (özgün zaman çizelgesinde, saniye).

    Önce dışa aktarma aralığı (`aralik.bas`–`aralik.bit`, verilmeyen uç projenin başı/sonu)
    alınır, sonra çıkarılan sahnelerin süreleri bunun içinden kesilir. Bitişik aralıklar
    birleştirilir; çok kısa (< 40 ms) artıklar atılır.
    """
    aralik = aralik or {}
    bas = max(0.0, aralik.get("bas") or 0.0)
    bit = min(toplam, aralik.get("bit") or toplam)
    parcalar = [(bas, bit)] if bit > bas else []
    for sahne in sahneler:
        if sahne["index"] not in set(cikarilan):
            continue
        yeni = []
        for a, b in parcalar:
            if sahne["bit"] <= a or sahne["bas"] >= b:
                yeni.append((a, b))
                continue
            if sahne["bas"] > a:
                yeni.append((a, sahne["bas"]))
            if sahne["bit"] < b:
                yeni.append((sahne["bit"], b))
        parcalar = yeni
    sonuc = []
    for a, b in sorted(parcalar):
        if b - a < 0.04:
            continue
        if sonuc and a - sonuc[-1][1] < 0.001:
            sonuc[-1] = (sonuc[-1][0], b)
        else:
            sonuc.append((round(a, 3), round(b, 3)))
    return sonuc


def altyaziyi_kaydir(bloklar, araliklar):
    """Altyazı bloklarını kesilmiş zaman çizelgesine taşı: korunan kısımları kalır,
    kesilen kısımlar düşer, sonraki bloklar kesilen süre kadar öne kayar."""
    sonuc, kayma = [], []
    gecen = 0.0
    for a, b in araliklar:
        kayma.append((a, b, gecen))
        gecen += b - a
    for blok in bloklar:
        for a, b, once in kayma:
            ust_bas, ust_bit = max(blok["bas"], a), min(blok["bit"], b)
            if ust_bit - ust_bas >= 0.05:
                sonuc.append({"bas": round(once + ust_bas - a, 3),
                              "bit": round(once + ust_bit - a, 3), "metin": blok["metin"]})
    return sonuc


def _srt_yaz(bloklar, yol):
    def zaman(sn):
        ms = int(round(sn * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    Path(yol).write_text("".join(f"{i}\n{zaman(b['bas'])} --> {zaman(b['bit'])}\n{b['metin']}\n\n"
                                 for i, b in enumerate(bloklar, 1)), encoding="utf-8")


def _secim_ifadesi(araliklar):
    return "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in araliklar)


def disa_aktar(ad, is_=None):
    """İşaretli izlerden videoyu kur ve yolunu döndür."""
    ffmpeg = _ffmpeg()
    klasor = depo.guvenli_klasor(ad)
    durum = proje_oku(klasor) if klasor else None
    if durum is None:
        raise DisaAktarimHatasi(f"Proje bulunamadı: {ad}")
    secim = ayar_oku(ad)
    isaret = secim["isaret"]
    model = veri.proje(ad)
    g, y = model["tuval"]["genislik"], model["tuval"]["yukseklik"]
    adimlar = durum.get("adimlar") or []
    toplam = max(model["sure"], 0.1)
    araliklar = korunan_araliklar(model["sahneler"], toplam, secim["cikarilan"], secim["aralik"])
    if not araliklar:
        raise DisaAktarimHatasi("Dışa aktarılacak süre kalmadı: bütün sahneler çıkarılmış ya da "
                                "aralık boş.")
    kesik = araliklar != [(0.0, round(toplam, 3))]
    cikti_suresi = sum(b - a for a, b in araliklar)
    cikti_klasoru = klasor / KLASOR
    parca_klasoru = cikti_klasoru / ".parca"
    calisma = cikti_klasoru / ".calisma"
    for yol in (parca_klasoru, calisma):
        yol.mkdir(parents=True, exist_ok=True)
    for eski in calisma.iterdir():
        if eski.is_file():
            eski.unlink(missing_ok=True)

    # 1 · Görüntü: sahne parçaları (ya da tek siyah parça) → özgün zaman çizelgesinde video.
    # Yalnızca korunan aralıklara değen sahneler hazırlanır; ötekiler siyah parçayla geçilir
    # (nasılsa kesilecekler, kodlamaya gerek yok).
    liste = []
    if isaret["video"] and adimlar:
        for sira, adim in enumerate(adimlar, 1):
            bas, bit = veri._saniye(adim.get("start")), veri._saniye(adim.get("end"))
            sure = max(bit - bas, 0.04)
            gerekli = any(bas < b and bit > a for a, b in araliklar)
            _ilerle(is_, 70 * sira / len(adimlar), f"Sahne {sira}/{len(adimlar)} hazırlanıyor")
            kaynak = adim if gerekli else {"index": 0}   # kesilecek: siyah yeter
            liste.append(_parca(ffmpeg, klasor, kaynak, sure, g, y, parca_klasoru, is_))
        sahne_toplami = sum(max(veri._saniye(a.get("end")) - veri._saniye(a.get("start")), 0.04)
                            for a in adimlar)
        if toplam - sahne_toplami > 0.05:   # ses son sahneden uzunsa sonu siyahla dolsun
            liste.append(_parca(ffmpeg, klasor, {"index": 999}, toplam - sahne_toplami, g, y,
                                parca_klasoru, is_))
    else:
        _ilerle(is_, 35, "Siyah görüntü hazırlanıyor (video izi işaretsiz)")
        liste.append(_parca(ffmpeg, klasor, {"index": 0}, toplam, g, y, parca_klasoru, is_))
    (calisma / "liste.txt").write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in liste), encoding="utf-8")
    _ilerle(is_, 74, "Sahneler birleştiriliyor")
    _calistir([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
               "-i", "liste.txt", "-c", "copy", "goruntu.mp4"], cwd=calisma, is_=is_)

    # 2 · Ses: işaretli ses izleri; her biri kendi seviyesinde, kendi başlangıcında
    seviye = secim["seviye"]
    sesler = []   # (dosya, başlangıç sn, süzgeç, grup: konusma · muzik · efekt)
    muzik_tercihi = muzik.muzik_durumu(ad) or {}
    def ekle(dosya, bas, iz, ek=""):
        oran = seviye.get(iz, 100) / 100
        suzgec = ",".join(x for x in (ek, f"volume={oran:.2f}" if oran != 1 else "") if x)
        grup = "konusma" if iz in ("seslendirme", "dublaj") else iz
        sesler.append((dosya, bas, suzgec, grup))
    # Konuşma (seslendirme/dublaj) projenin **konuşma seviyesiyle** (`ses.seviye`, ör. %400,
    # sınırlayıcıyla) yükseltilir; StudioFlow'un ses ekleme ve ses modu da aynısını yapar.
    # 21.10.2026: dışa aktarma bunu uygulamıyordu, konuşma %100'de kalıp kısık geliyordu.
    konusma_suzgeci = anlatim_suzgeci(durum)
    # İşaretli bir ses izinin dosyası yoksa video o iz olmadan **sessizce** çıkıyordu
    # (21.10.2026: seçili müzik silinince müziksiz). Artık açıkça hata verilir.
    if isaret["seslendirme"]:
        dosya = (durum.get("ses") or {}).get("dosya")
        if not (dosya and (klasor / dosya).is_file()):
            raise DisaAktarimHatasi("Seslendirme izi işaretli ama seslendirme dosyası bulunamadı. "
                                    "İzin işaretini kaldır ya da seslendirmeyi yeniden üret.")
        ekle(klasor / dosya, 0.0, "seslendirme", konusma_suzgeci)
    if isaret["dublaj"]:
        kayit = next((k for k in diller.dublaj_listesi(ad) if k["ad"] == secim["dublaj"]), None)
        if not (kayit and (klasor / kayit["dosya"]).is_file()):
            raise DisaAktarimHatasi("Dublaj izi işaretli ama seçili dublaj bulunamadı. Zaman "
                                    "çizelgesinde dublajı seç ya da izin işaretini kaldır.")
        ekle(klasor / kayit["dosya"], 0.0, "dublaj", konusma_suzgeci)
    sabit_muzik = muzik.sabit_muzik(klasor)[0] if isaret["muzik"] else None
    if sabit_muzik is not None:
        # Kullanıcı kararı (21.10.2026): projeye eklenen müzik **sabittir**; ducking'i müzik
        # eklenirken o anki konuşmaya göre uygulandı. Dışa aktarma yalnızca müziğin olup
        # olmadığına bakar, dosyayı olduğu gibi koyar, ducking'i yeniden hesaplamaz.
        ekle(sabit_muzik, 0.0, "muzik")
        dosya_, bas_, suzgec_, _grup = sesler.pop()
        sesler.append((dosya_, bas_, suzgec_, "sabit"))
    elif isaret["muzik"]:
        kayitlar = {k["ad"]: k for k in muzik.muzik_listesi(ad)}
        secilenler = [kayitlar[m] for m in secim["muzik"]
                      if m in kayitlar and (klasor / kayitlar[m]["dosya"]).is_file()]
        if not secilenler:
            raise DisaAktarimHatasi("Müzik izi işaretli ama videoya girecek müzik bulunamadı "
                                    "(seçili müzik silinmiş ya da yeniden adlandırılmış olabilir). "
                                    "Müzik bölümünde müziği işaretleyip Videoya ekle'ye bas ya da "
                                    "müzik izinin işaretini kaldır.")
        giris, cikis = secim["muzik_karartma"]["giris"], secim["muzik_karartma"]["cikis"]
        # StudioFlow'un Müzik bölümündeki "kısa kalırsa video sonuna kadar tekrarla"
        # tercihi: seçili müzikler sırayla, video bitene dek baştan çalar.
        tekrarla = bool(muzik_tercihi.get("tekrarla"))
        sira_listesi = []
        bas = 0.0
        while secilenler and bas < toplam and len(sira_listesi) < 500:
            for kayit in secilenler:
                if bas >= toplam:
                    break
                uzunluk = float(kayit.get("sure") or 0) or toplam
                sira_listesi.append((kayit, bas, uzunluk))
                bas += uzunluk
            if not tekrarla:
                break
        for sira, (kayit, bas, uzunluk) in enumerate(sira_listesi):
            karartma = []
            if sira == 0 and giris > 0:
                karartma.append(f"afade=t=in:st=0:d={giris:.2f}")
            if sira == len(sira_listesi) - 1 and cikis > 0:
                son = min(uzunluk, toplam - bas)
                karartma.append(f"afade=t=out:st={max(0.0, son - cikis):.2f}:d={cikis:.2f}")
            ekle(klasor / kayit["dosya"], bas, "muzik", ",".join(karartma))
    if isaret["efekt"] and secim["efekt"]:
        kayit = next((k for k in efekt_ekleme.efekt_listesi(ad) if k["ad"] == secim["efekt"]), None)
        if kayit and kayit.get("dosya") and (klasor / kayit["dosya"]).is_file():
            ekle(klasor / kayit["dosya"], 0.0, "efekt")

    # 3 · Altyazı: kesilmiş zamana kaydırılır, StudioFlow'un gömme görünümüyle yazılır
    altyazi_filtresi = None
    if isaret["altyazi"] and secim["altyazi"]:
        kayit = next((k for k in diller.altyazi_listesi(ad) if k["ad"] == secim["altyazi"]), None)
        if kayit and (klasor / kayit["dosya"]).is_file():
            if kesik:
                _srt_yaz(altyaziyi_kaydir(veri.srt_oku(klasor / kayit["dosya"]), araliklar),
                         calisma / "altyazi.srt")
            else:
                shutil.copyfile(klasor / kayit["dosya"], calisma / "altyazi.srt")
            altyazi_filtresi = ("subtitles=altyazi.srt:force_style='"
                                + altyazi_stili(calisma / "altyazi.srt", g, y, durum) + "'")

    # 4 · Son video: seçim (kesme) → altyazı → kodlama
    zaman = time.strftime("%Y%m%d-%H%M%S")
    hedef = cikti_klasoru / f"{klasor.name}-{zaman}.mp4"
    # -reinit_filter 0: parça sınırında akış özelliği değişse bile filtre zinciri yeniden
    # kurulmasın (kesme sayacı sıfırlanmasın; bkz. `_tuval_zinciri`).
    komut = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-reinit_filter", "0",
             "-i", "goruntu.mp4"]
    for dosya, _bas, _s, _g in sesler:
        komut += ["-i", str(dosya)]
    filtre, harita = [], []
    secim_ifadesi = _secim_ifadesi(araliklar)
    goruntu = "[0:v]"
    if kesik:
        filtre.append(f"{goruntu}select='{secim_ifadesi}',setpts=N/FRAME_RATE/TB[vk]")
        goruntu = "[vk]"
    if altyazi_filtresi:
        filtre.append(f"{goruntu}{altyazi_filtresi}[va]")
        goruntu = "[va]"
    if sesler:
        gruplar = {"konusma": [], "muzik": [], "efekt": []}
        for sira, (_dosya, bas, suzgec, grup) in enumerate(sesler, 1):
            gecikme = int(round(bas * 1000))
            zincir = ",".join(x for x in (_ESIT, suzgec, f"adelay=delays={gecikme}:all=1") if x)
            filtre.append(f"[{sira}:a]{zincir}[s{sira}]")
            gruplar.setdefault(grup, []).append(f"[s{sira}]")

        def birlestir(etiketler, ad_):
            if len(etiketler) == 1:
                return etiketler[0]
            filtre.append(f"{''.join(etiketler)}amix=inputs={len(etiketler)}:normalize=0:"
                          f"duration=longest[{ad_}]")
            return f"[{ad_}]"
        etiketler = []
        konusma = birlestir(gruplar["konusma"], "kon") if gruplar["konusma"] else None
        muzik_izi = birlestir(gruplar["muzik"], "muz") if gruplar["muzik"] else None
        # StudioFlow'un ducking tercihi: anlatım konuşurken müzik kendiliğinden kısılır
        # (StudioFlow'daki sidechaincompress değerleriyle aynı).
        if konusma and muzik_izi and muzik_tercihi.get("ducking", True) is not False:
            filtre.append(f"{konusma}asplit=2[konk][anahtar]")
            filtre.append(f"{muzik_izi}[anahtar]sidechaincompress=threshold={MUZIK_DUCKING_ESIK}:"
                          f"ratio={MUZIK_DUCKING_ORAN}:attack={MUZIK_DUCKING_ATAK}:"
                          f"release={MUZIK_DUCKING_BIRAKMA}:makeup=1:detection=rms[duck]")
            etiketler += ["[konk]", "[duck]"]
        else:
            etiketler += [x for x in (konusma, muzik_izi) if x]
        etiketler += gruplar["efekt"] + gruplar.get("sabit", [])   # sabit müzik: ducking yok
        karisim = ("anull" if len(etiketler) == 1 else
                   f"amix=inputs={len(etiketler)}:normalize=0:duration=longest,alimiter=limit=0.97")
        kesme = (f",atrim=0:{toplam:.3f},aselect='{secim_ifadesi}',asetpts=N/SR/TB"
                 if kesik else "")
        filtre.append(f"{''.join(etiketler)}{karisim}{kesme}[ses]")
        harita += ["-map", "[ses]", "-c:a", "aac", "-b:a", "192k"]
    yeniden_kodla = kesik or bool(altyazi_filtresi)
    harita = ["-map", goruntu if goruntu != "[0:v]" else "0:v"] + harita
    if filtre:
        komut += ["-filter_complex", ";".join(filtre)]
    komut += harita + (_KODLAYICI if yeniden_kodla else ["-c:v", "copy"])
    komut += ["-t", f"{cikti_suresi:.3f}", "-movflags", "+faststart",
              str(hedef.with_suffix(".yaziliyor.mp4"))]
    izler = [iz for iz in IZLER if isaret[iz]]
    _ilerle(is_, 80, "Video yazılıyor (" + ", ".join(izler or ["boş"]) + ")"
            + (f" · {len(secim['cikarilan'])} sahne çıkarıldı" if secim["cikarilan"] else "")
            + (" · aralık" if secim["aralik"]["bas"] is not None or secim["aralik"]["bit"] is not None else "")
            + (" · yeniden kodlandığı için birkaç dakika sürebilir" if yeniden_kodla else ""))
    _calistir(komut, cwd=calisma, is_=is_)
    hedef.with_suffix(".yaziliyor.mp4").replace(hedef)
    return hedef
