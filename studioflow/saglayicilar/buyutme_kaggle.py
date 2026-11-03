"""Kaggle'ın ücretsiz GPU'sunda video büyütme (SeedVR2 ya da Real-ESRGAN).

Yerel GPU/RAM hiç kullanılmaz; bütün iş Kaggle API'siyle uzakta yürür:

1. Kimlik Kaggle'ın kendi dosyalarından okunur: yeni tip token `~/.kaggle/access_token`,
   eski tip anahtar `~/.kaggle/kaggle.json` (ikisini de API hesapları sekmesi yazar;
   yoksa açık bir hata verilir).
2. Girdi videoları **özel** bir veri setine yüklenir: ilk seferde oluşturulur, sonra
   yeni sürüm eklenir. Kaggle sürümü işleyip `ready` diyene dek beklenir.
3. Tek hücreli bir notebook ve `kernel-metadata.json` yazılır (özel, GPU ve internet
   açık, veri seti `dataset_sources`'ta) ve hızlandırıcı `NvidiaTeslaT4` ile gönderilir.
4. Notebook depoyu `/tmp`'ye klonlar (çıktıya karışmasın; `/kaggle/working` altındaki
   her şey çıktı sayılır), bağımlılıkları kurar ve sonucu `/kaggle/working/out/`a yazar.
5. Kernel durumu birkaç saniyede bir sorgulanır; bitince yalnızca `out/` indirilir.
   Hata olursa Kaggle günlüğü indirilip okunur hâle getirilir.

Kimlik bilgisi bu iki dosya dışında hiçbir dosyaya ya da günlüğe yazılmaz: notebook'a girmez, hata
metinlerinden anahtar ayıklanır. Çıktı videoda ses olmayabilir; bu beklenen durumdur
(ses projede sonradan eklenir).
"""
import json
import re
import shutil
import time
from pathlib import Path

KAGGLE_JSON = Path.home() / ".kaggle" / "kaggle.json"       # eski tip: username + key
ACCESS_TOKEN = Path.home() / ".kaggle" / "access_token"     # yeni tip token (KGAT_…)
TOKEN_URL = "https://www.kaggle.com/settings/api"

SEEDVR2_DEPO = "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler"
REALESRGAN_DEPO = "https://github.com/xinntao/Real-ESRGAN"

YONTEM_SEEDVR2 = "seedvr2"
YONTEM_REALESRGAN = "realesrgan"
HIZLANDIRICI = "NvidiaTeslaT4"

# Kernel ve veri seti her çalıştırmada aynı adla kalır; Kaggle yeni sürüm ekler.
# Başlık, `slug`a birebir çözülmeli (Kaggle aksi hâlde uyarır).
KERNEL_SLUG = "studioflow-video-buyutme"
KERNEL_BASLIK = "StudioFlow Video Buyutme"
VERI_SLUG = "studioflow-buyutme-girdi"
VERI_BASLIK = "StudioFlow Buyutme Girdi"

VIDEO_UZANTILARI = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")

MODELLER = ["seedvr2_ema_3b-Q8_0.gguf", "seedvr2_ema_3b-Q4_K_M.gguf",
            "seedvr2_ema_3b_fp8_e4m3fn.safetensors", "seedvr2_ema_3b_fp16.safetensors"]
MODEL_VARSAYILAN = MODELLER[0]
COZUNURLUK_VARSAYILAN = 1108
MAX_COZUNURLUK_VARSAYILAN = 1920
BATCH_VARSAYILAN = 21
GURULTU_SINIRI = (0.0, 0.3)
REALESRGAN_MODEL = "RealESRGAN_x4plus"
REALESRGAN_OLCEK = 2

# SeedVR2'nin her çalıştırmada aynı kalan parametreleri (T4'ün 16 GB belleğine göre).
SABIT_PARAMETRELER = [
    "--temporal_overlap", "3", "--prepend_frames", "4", "--color_correction", "lab",
    "--dit_offload_device", "cpu", "--vae_offload_device", "cpu", "--blocks_to_swap", "16",
    "--vae_encode_tiled", "--vae_decode_tiled", "--cache_dit", "--cache_vae",
    "--uniform_batch_size", "--video_backend", "ffmpeg", "--debug"]

SORGU_ARALIGI = 10          # kernel durumu sorgu aralığı (sn)
VERI_BEKLEME = 900          # veri setinin işlenmesi için en uzun bekleme (sn)
# Gönderimden hemen sonra Kaggle bir süre **önceki** çalıştırmanın durumunu döndürebilir;
# kuyruk/çalışma görülmeden gelen bitiş durumu bu süre dolana dek yok sayılır.
ESKI_DURUM_PAYI = 90

DURUM_ADLARI = {"queued": "sırada", "running": "çalışıyor", "complete": "tamamlandı",
                "error": "hata", "cancel_requested": "iptal isteniyor",
                "cancel_acknowledged": "iptal edildi", "new_script": "hazırlanıyor"}


class KaggleHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilebilen Kaggle hatası (anahtar içermez)."""


# ── Doğrulama ─────────────────────────────────────────────────────────────────────

def batch_dogrula(deger):
    """`batch_size` yalnızca 4n+1 olabilir (5, 9, 13, …): en yakın geçerli değere çekilir."""
    try:
        sayi = int(round(float(deger)))
    except (TypeError, ValueError):
        return BATCH_VARSAYILAN
    return max(5, 4 * round((sayi - 1) / 4) + 1)


def gurultu_dogrula(deger):
    """`latent_noise_scale`: 0–0,3 aralığına çekilir."""
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return GURULTU_SINIRI[0]
    return min(max(sayi, GURULTU_SINIRI[0]), GURULTU_SINIRI[1])


def cozunurluk_dogrula(deger, varsayilan):
    try:
        sayi = int(deger)
    except (TypeError, ValueError):
        return varsayilan
    return sayi if 64 <= sayi <= 4096 else varsayilan


def girdi_videolari(girdi):
    """Seçilen dosyalar (tek yol ya da liste) → video listesi; video olmayanlar atlanır.

    Bir klasör verilirse içindeki videolar alınır (alt klasöre inilmez). Sıra seçim
    sırası değil ad sırasıdır: sahne klipleri `adim-01`, `adim-02`… diye sıralanır.
    """
    yollar = girdi if isinstance(girdi, (list, tuple)) else [girdi]
    videolar = []
    for yol in yollar:
        yol = Path(str(yol or "").strip().strip('"'))
        if not str(yol).strip() or str(yol) == ".":
            continue
        if yol.is_dir():
            videolar += [p for p in yol.iterdir()
                         if p.is_file() and p.suffix.lower() in VIDEO_UZANTILARI]
        elif yol.is_file() and yol.suffix.lower() in VIDEO_UZANTILARI:
            videolar.append(yol)
    if not videolar:
        raise KaggleHatasi("Büyütülecek video seç (mp4, mov, mkv, webm, avi, m4v).")
    return sorted(videolar, key=lambda p: p.name.lower())


def veri_adlari(videolar):
    """Veri setindeki dosya adları: aynı adlı iki video çakışmasın diye sonuna `-2`… eklenir."""
    adlar, kullanilan = [], set()
    for video in videolar:
        ad, sayi = video.name, 2
        while ad.lower() in kullanilan:
            ad, sayi = f"{video.stem}-{sayi}{video.suffix}", sayi + 1
        kullanilan.add(ad.lower())
        adlar.append(ad)
    return adlar


# ── Kimlik ────────────────────────────────────────────────────────────────────────

def eski_tip_anahtar_mi(anahtar):
    """Eski tip (legacy) anahtar 32 haneli onaltılık bir değerdir ve kullanıcı adıyla
    `kaggle.json`a yazılır. Yeni tip token (`KGAT_…`) tek başına `access_token`a yazılır."""
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", (anahtar or "").strip()))


def _json_oku(dosya):
    try:
        veri = json.loads(Path(dosya).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return veri if isinstance(veri, dict) else None


def _token_oku(dosya=None):
    try:
        return Path(dosya or ACCESS_TOKEN).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _yeni_tokeni_tasi():
    """`kaggle.json`un `key` alanında yeni tip token (`KGAT_…`) varsa `access_token`a taşı.

    Kaggle, `kaggle.json`daki değeri kullanıcı adı/şifre gibi gönderir; yeni tip token bu
    yolla **401** alır. Uygulamanın eski sürümü token'ı oraya yazıyordu; elle indirilen
    dosyada da aynı karışıklık olabilir. Eski tip (32 haneli) anahtara dokunulmaz.
    """
    if _token_oku():
        return
    anahtar = str((_json_oku(KAGGLE_JSON) or {}).get("key") or "").strip()
    if anahtar and not eski_tip_anahtar_mi(anahtar):
        ACCESS_TOKEN.write_text(anahtar, encoding="utf-8")
        KAGGLE_JSON.unlink(missing_ok=True)


def kimlik_oku():
    """Kayıtlı kimliği denetle; kullanıcı adını döndür (yeni tip token'da boş olabilir,
    Kaggle onu doğrulamada kendisi bildirir). Kimlik yoksa açık bir hata verir.

    Anahtar döndürülmez: Kaggle kütüphanesi onu kendi dosyasından okur.
    """
    _yeni_tokeni_tasi()
    if _token_oku():
        veri = _json_oku(KAGGLE_JSON) or {}
        return str(veri.get("username") or "").strip()
    if not KAGGLE_JSON.is_file():
        raise KaggleHatasi(
            "Kaggle kimliği bulunamadı.\n"
            "API hesapları sekmesinde Kaggle hizmetine anahtarını kaydet "
            f"({TOKEN_URL} › API › 'Generate New Token'); kimlik dosyası kendiliğinden yazılır.")
    veri = _json_oku(KAGGLE_JSON)
    if veri is None:
        raise KaggleHatasi(f"Kaggle kimlik dosyası okunamadı (geçerli JSON değil): {KAGGLE_JSON}")
    kullanici = str(veri.get("username") or "").strip()
    if not kullanici or not str(veri.get("key") or "").strip():
        raise KaggleHatasi(f"Kaggle kimlik dosyasında 'username' ya da 'key' eksik: {KAGGLE_JSON}")
    return kullanici


def kullanici_adi(api):
    """Doğrulanmış hesabın kullanıcı adı: Kaggle'ın bildirdiği ad, yoksa dosyadaki ad."""
    try:
        ad = str(api.get_config_value("username") or "").strip()
    except Exception:
        ad = ""
    ad = ad or kimlik_oku()
    if not ad:
        raise KaggleHatasi("Kaggle kullanıcı adı alınamadı; API hesapları sekmesinde "
                           "kullanıcı adını da yaz.")
    return ad


def baglanti_testi(api=None):
    """Kimliği Kaggle'a gerçekten sor: yalnızca okuyan tek bir çağrı (kendi notebook
    listesinin ilk satırı). Hiçbir şey oluşturmaz, GPU kotası harcamaz."""
    try:
        kimlik_oku()
        api = api or api_baglan()
        api.kernels_list(mine=True, page_size=1)
        kullanici = kullanici_adi(api)
    except KaggleHatasi as exc:
        return f"❌ {exc}"
    except Exception as exc:
        return "❌ Kaggle bağlantısı kurulamadı: " + hata_metni(exc)
    return (f"✅ Kaggle bağlantısı çalışıyor · hesap: {kullanici}\n"
            "Not: GPU ve internet izni (telefon doğrulaması) ancak ilk büyütmede sınanır; "
            "eksikse Kaggle gönderimde açık bir hata verir.")


def kimlik_yaz(kullanici, anahtar):
    """API hesapları sekmesindeki aktif Kaggle hesabını Kaggle'ın okuduğu dosyaya yaz.

    Yeni tip token `~/.kaggle/access_token`a, eski tip anahtar kullanıcı adıyla
    `~/.kaggle/kaggle.json`a yazılır. Kaggle token dosyasını öncelikli okuduğu için hesap
    değişince **diğer türün dosyası kaldırılır**; yoksa eski hesap kullanılmaya devam ederdi.
    """
    kullanici, anahtar = (kullanici or "").strip(), (anahtar or "").strip()
    if not anahtar:
        raise KaggleHatasi("Kaggle API anahtarı boş.")
    ACCESS_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    if eski_tip_anahtar_mi(anahtar):
        if not kullanici:
            raise KaggleHatasi("Eski tip (32 haneli) Kaggle anahtarı kullanıcı adıyla birlikte gerekli.")
        KAGGLE_JSON.write_text(json.dumps({"username": kullanici, "key": anahtar}), encoding="utf-8")
        ACCESS_TOKEN.unlink(missing_ok=True)
        return KAGGLE_JSON
    ACCESS_TOKEN.write_text(anahtar, encoding="utf-8")
    KAGGLE_JSON.unlink(missing_ok=True)
    return ACCESS_TOKEN


def kimlik_sil_eslesirse(kullanici, anahtar):
    """Kimlik dosyası verilen hesaba aitse sil (silinen hesabın bilgisi diskte kalmasın).
    Başka bir hesaba ait dosyaya dokunulmaz."""
    anahtar = (anahtar or "").strip()
    if anahtar and _token_oku() == anahtar:
        ACCESS_TOKEN.unlink(missing_ok=True)
        return True
    veri = _json_oku(KAGGLE_JSON) or {}
    if (anahtar and str(veri.get("key") or "").strip() == anahtar
            and str(veri.get("username") or "").strip() == (kullanici or "").strip()):
        KAGGLE_JSON.unlink(missing_ok=True)
        return True
    return False


def _anahtar():
    """Yalnızca hata metinlerinden ayıklamak için; hiçbir yere yazılmaz."""
    return [a for a in (_token_oku(), str((_json_oku(KAGGLE_JSON) or {}).get("key") or "")) if a]


def hata_metni(exc):
    """İstisnayı kullanıcıya gösterilecek metne çevir; Kaggle anahtarı ayıklanır."""
    mesaj = str(exc) or type(exc).__name__
    for anahtar in _anahtar():
        mesaj = mesaj.replace(anahtar, "[gizli]")
    mesaj = re.sub(r"KGAT_[A-Za-z0-9_-]+", "[gizli]", mesaj)
    dusuk = mesaj.lower()
    if "401" in dusuk or "unauthorized" in dusuk:
        mesaj = ("Kaggle anahtarı reddedildi (geçersiz, silinmiş ya da süresi dolmuş). "
                 "API hesapları sekmesinde yeni bir token kaydet. Ayrıntı: " + mesaj)
    elif "403" in dusuk or "forbidden" in dusuk:
        mesaj = ("Kaggle bu işleme izin vermedi: GPU ve internet için hesapta telefon "
                 "doğrulaması gerekir (kaggle.com › Settings › Phone verification). "
                 "Ayrıntı: " + mesaj)
    return mesaj[:1500]


def api_baglan():
    """Kimliği doğrulanmış bir `KaggleApi` döndür.

    `kaggle` paketi içe aktarılırken de kimlik arar; bu yüzden önce dosya denetlenir,
    sonra içe aktarılır. `authenticate()` başarısızlıkta `exit(1)` çağırır; uygulamayı
    kapatmasın diye `SystemExit` yakalanır.
    """
    kimlik_oku()
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        raise KaggleHatasi("`kaggle` paketi kurulu değil: "
                           "uv pip install --python .venv\\Scripts\\python.exe kaggle") from None
    api = KaggleApi()
    try:
        api.authenticate()
    except SystemExit:
        raise KaggleHatasi("Kaggle kimliği doğrulanamadı: anahtar geçersiz ya da süresi dolmuş. "
                           "API hesapları sekmesinde yeni bir anahtar kaydet.") from None
    return api


# ── Notebook ──────────────────────────────────────────────────────────────────────

_ORTAK_KOD = '''\
import glob, os, shutil, subprocess, sys

UZANTILAR = {uzantilar!r}
CIKTI = "/kaggle/working/out"
GIRDI = "/tmp/girdi"


def calistir(komut, cwd=None):
    print("$", " ".join(komut), flush=True)
    subprocess.run(komut, cwd=cwd, check=True)


# Veri setinin bağlandığı yol Kaggle sürümüne göre değişebilir: /kaggle/input altı taranır.
videolar = sorted(p for p in glob.glob("/kaggle/input/**/*", recursive=True)
                  if p.lower().endswith(UZANTILAR))
if not videolar:
    raise SystemExit("Girdi videosu bulunamadı: /kaggle/input")
os.makedirs(GIRDI, exist_ok=True)
os.makedirs(CIKTI, exist_ok=True)
for yol in videolar:
    shutil.copy(yol, GIRDI)
print(f"{{len(videolar)}} video:", [os.path.basename(v) for v in videolar], flush=True)
'''

_SEEDVR2_KOD = '''
DEPO = "/tmp/seedvr2"
calistir(["git", "clone", "--depth", "1", {depo!r}, DEPO])
calistir([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(DEPO, "requirements.txt")])
calistir([sys.executable, "inference_cli.py", GIRDI, "--output", CIKTI,
          "--dit_model", {model!r},
          "--resolution", {cozunurluk!r}, "--max_resolution", {max_cozunurluk!r},
          "--batch_size", {batch!r}, "--latent_noise_scale", {gurultu!r},
          *{sabit!r}], cwd=DEPO)
# Klasör girdisinde CLI her videoyu aynı adla --output klasörüne yazar (out/adim-01.mp4).
'''

_REALESRGAN_KOD = '''
import importlib.util
DEPO = "/tmp/realesrgan"
calistir(["git", "clone", "--depth", "1", {depo!r}, DEPO])
calistir([sys.executable, "-m", "pip", "install", "-q", "basicsr", "facexlib", "gfpgan", "ffmpeg-python"])
calistir([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=DEPO)
# basicsr yeni torchvision'da kaldırılan modülü içe aktarır; tek satırlık düzeltme.
kok = os.path.dirname(importlib.util.find_spec("basicsr").origin)
yol = os.path.join(kok, "data", "degradations.py")
metin = open(yol, encoding="utf-8").read()
open(yol, "w", encoding="utf-8").write(metin.replace(
    "torchvision.transforms.functional_tensor", "torchvision.transforms.functional"))
calistir([sys.executable, "setup.py", "develop"], cwd=DEPO)
for video in sorted(os.listdir(GIRDI)):
    calistir([sys.executable, "inference_realesrgan_video.py", "-i", os.path.join(GIRDI, video),
              "-n", {model!r}, "-s", {olcek!r}, "-o", CIKTI, "--suffix", "buyuk"], cwd=DEPO)
'''

_KAPANIS_KOD = '''
ciktilar = sorted(f for f in os.listdir(CIKTI) if f.lower().endswith(UZANTILAR))
print("Çıktı:", ciktilar, flush=True)
if not ciktilar:
    raise SystemExit("Büyütme bitti ama out/ klasöründe video yok.")
'''


def notebook_kodu(yontem, model=MODEL_VARSAYILAN, cozunurluk=COZUNURLUK_VARSAYILAN,
                  max_cozunurluk=MAX_COZUNURLUK_VARSAYILAN, batch=BATCH_VARSAYILAN, gurultu=0.0):
    """Notebook'un tek hücresindeki Python kodu. Kimlik bilgisi içermez."""
    kod = _ORTAK_KOD.format(uzantilar=VIDEO_UZANTILARI)
    if yontem == YONTEM_REALESRGAN:
        kod += _REALESRGAN_KOD.format(depo=REALESRGAN_DEPO, model=REALESRGAN_MODEL,
                                      olcek=str(REALESRGAN_OLCEK))
    else:
        kod += _SEEDVR2_KOD.format(
            depo=SEEDVR2_DEPO, model=(model or MODEL_VARSAYILAN).strip(),
            cozunurluk=str(cozunurluk_dogrula(cozunurluk, COZUNURLUK_VARSAYILAN)),
            max_cozunurluk=str(cozunurluk_dogrula(max_cozunurluk, MAX_COZUNURLUK_VARSAYILAN)),
            batch=str(batch_dogrula(batch)), gurultu=f"{gurultu_dogrula(gurultu):g}",
            sabit=SABIT_PARAMETRELER)
    return kod + _KAPANIS_KOD


def notebook(kod):
    """Tek kod hücreli `.ipynb` içeriği (sözlük)."""
    return {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                       "outputs": [], "source": kod}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                        "name": "python3"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 4}


def kernel_metadata(kullanici, kod_dosyasi="buyutme.ipynb"):
    return {"id": f"{kullanici}/{KERNEL_SLUG}", "title": KERNEL_BASLIK,
            "code_file": kod_dosyasi, "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": True, "enable_tpu": False,
            "enable_internet": True, "dataset_sources": [f"{kullanici}/{VERI_SLUG}"],
            "competition_sources": [], "kernel_sources": [], "model_sources": []}


def veri_metadata(kullanici):
    return {"title": VERI_BASLIK, "id": f"{kullanici}/{VERI_SLUG}",
            "licenses": [{"name": "CC0-1.0"}]}


# ── Kaggle adımları ───────────────────────────────────────────────────────────────

def _yanit_hatasi(yanit, ne):
    hata = str(getattr(yanit, "error", "") or "").strip()
    if hata:
        raise KaggleHatasi(f"{ne} başarısız: {hata}")


def _durum_adi(durum):
    """Kaggle SDK enum'u (`KernelWorkerStatus.RUNNING`) ya da metin → `running`."""
    ad = getattr(durum, "name", None) or str(durum or "")
    return ad.rsplit(".", 1)[-1].lower()


def veri_seti_yukle(api, kullanici, videolar, calisma, bildir=print, uyu=time.sleep):
    """Videoları özel veri setine yükle (yoksa oluştur, varsa yeni sürüm) ve hazır olmasını bekle."""
    klasor = Path(calisma) / "veri"
    if klasor.exists():
        shutil.rmtree(klasor, ignore_errors=True)
    klasor.mkdir(parents=True, exist_ok=True)
    for video, ad in zip(videolar, veri_adlari(videolar)):
        shutil.copy2(video, klasor / ad)
    (klasor / "dataset-metadata.json").write_text(
        json.dumps(veri_metadata(kullanici), ensure_ascii=False, indent=1), encoding="utf-8")

    ref = f"{kullanici}/{VERI_SLUG}"
    try:
        api.dataset_status(ref)
        var = True
    except Exception as exc:
        kod = getattr(getattr(exc, "response", None), "status_code", None)
        if kod != 404:
            raise
        var = False
    boyut = sum(v.stat().st_size for v in videolar) / 1e6
    if var:
        bildir(f"Veri setine yeni sürüm yükleniyor ({len(videolar)} video, {boyut:.1f} MB)…")
        yanit = api.dataset_create_version(str(klasor), "StudioFlow büyütme girdisi",
                                           quiet=True, convert_to_csv=False)
    else:
        bildir(f"Özel veri seti oluşturuluyor ({len(videolar)} video, {boyut:.1f} MB)…")
        yanit = api.dataset_create_new(str(klasor), public=False, quiet=True,
                                       convert_to_csv=False)
    _yanit_hatasi(yanit, "Veri seti yüklemesi")
    shutil.rmtree(klasor, ignore_errors=True)

    bildir("Kaggle veri setini işliyor…")
    baslangic = time.monotonic()
    while True:
        durum = str(api.dataset_status(ref) or "").lower()
        if durum == "ready":
            return ref
        if durum in ("failed", "deleted"):
            raise KaggleHatasi(f"Kaggle veri setini işleyemedi (durum: {durum}).")
        if time.monotonic() - baslangic > VERI_BEKLEME:
            raise KaggleHatasi("Veri seti zamanında hazır olmadı; biraz sonra yeniden dene.")
        uyu(5)


def kernel_gonder(api, kullanici, kod, calisma):
    """Notebook'u ve `kernel-metadata.json`u yaz, T4 hızlandırıcıyla gönder; kernel ref'i döndür."""
    klasor = Path(calisma) / "kernel"
    klasor.mkdir(parents=True, exist_ok=True)
    meta = kernel_metadata(kullanici)
    (klasor / meta["code_file"]).write_text(json.dumps(notebook(kod), ensure_ascii=False),
                                            encoding="utf-8")
    (klasor / "kernel-metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    yanit = api.kernels_push(str(klasor), acc=HIZLANDIRICI)
    _yanit_hatasi(yanit, "Notebook gönderimi")
    gecersiz = list(getattr(yanit, "invalid_dataset_sources", None) or [])
    if gecersiz:
        raise KaggleHatasi(f"Veri seti notebook'a bağlanamadı: {', '.join(gecersiz)}")
    return meta["id"], str(getattr(yanit, "url", "") or "")


def gunluk_metni(ham, son_satir=120):
    """Kaggle günlüğü (JSON satır listesi) → okunur metin; yalnızca son satırlar."""
    ham = ham or ""
    try:
        kayitlar = json.loads(ham)
        metin = "".join(str(k.get("data", "")) for k in kayitlar if isinstance(k, dict))
    except (ValueError, TypeError, AttributeError):
        metin = ham
    satirlar = metin.splitlines()
    return "\n".join(satirlar[-son_satir:])


def ciktiyi_indir(api, kernel, hedef, calisma):
    """`out/` klasöründeki videoları `hedef`e indir; (videolar, günlük metni) döndür."""
    gecici = Path(calisma) / "indirilen"
    shutil.rmtree(gecici, ignore_errors=True)
    dosyalar, _ = api.kernels_output(kernel, str(gecici), file_pattern=r"(^|/)out/",
                                     force=True, quiet=True)
    hedef = Path(hedef)
    hedef.mkdir(parents=True, exist_ok=True)
    videolar, gunluk = [], ""
    for dosya in map(Path, dosyalar):
        if dosya.suffix == ".log":
            try:
                gunluk = dosya.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        elif dosya.suffix.lower() in VIDEO_UZANTILARI and dosya.is_file():
            yer = hedef / dosya.name
            shutil.move(str(dosya), yer)
            videolar.append(yer)
    shutil.rmtree(gecici, ignore_errors=True)
    return sorted(videolar), gunluk_metni(gunluk)


def gunlugu_indir(api, kernel, calisma):
    """Yalnızca günlüğü indir (hata durumunda); okunur metin döndür."""
    gecici = Path(calisma) / "gunluk"
    shutil.rmtree(gecici, ignore_errors=True)
    # Hiçbir dosyaya uymayan desen `(?!)`: yalnızca günlük dosyası yazılır.
    dosyalar, _ = api.kernels_output(kernel, str(gecici), file_pattern=r"(?!)", quiet=True)
    metin = ""
    for dosya in map(Path, dosyalar):
        if dosya.suffix == ".log" and dosya.is_file():
            metin = dosya.read_text(encoding="utf-8", errors="replace")
    shutil.rmtree(gecici, ignore_errors=True)
    return gunluk_metni(metin)


def buyut(girdi, hedef, calisma, yontem=YONTEM_SEEDVR2, model=MODEL_VARSAYILAN,
          cozunurluk=COZUNURLUK_VARSAYILAN, max_cozunurluk=MAX_COZUNURLUK_VARSAYILAN,
          batch=BATCH_VARSAYILAN, gurultu=0.0, aralik=SORGU_ARALIGI, api=None,
          uyu=time.sleep, saat=time.monotonic):
    """Bütün akış; olay üretir: `("durum", metin)`, `("bitti", [videolar], günlük)`,
    `("hata", metin, günlük)`. Arayüz her olayı canlı gösterir."""
    try:
        videolar = girdi_videolari(girdi)
        kimlik_oku()
        api = api or api_baglan()
        kullanici = kullanici_adi(api)
        yield "durum", f"Kaggle hesabı: {kullanici} · {len(videolar)} video."
        kod = notebook_kodu(yontem, model, cozunurluk, max_cozunurluk, batch, gurultu)

        notlar = []
        ref = veri_seti_yukle(api, kullanici, videolar, calisma, bildir=notlar.append, uyu=uyu)
        for not_ in notlar:
            yield "durum", not_
        yield "durum", f"Veri seti hazır: {ref}. Notebook gönderiliyor (GPU: T4)…"
        kernel, adres = kernel_gonder(api, kullanici, kod, calisma)
        yield "durum", f"Notebook gönderildi: {adres or kernel}"
    except KaggleHatasi as exc:
        yield "hata", str(exc), ""
        return
    except Exception as exc:
        yield "hata", "Kaggle'a gönderilemedi: " + hata_metni(exc), ""
        return

    baslangic = saat()
    goruldu = False     # bu çalıştırmanın kuyruk/çalışma durumu görüldü mü
    son = None
    while True:
        gecen = int(saat() - baslangic)
        try:
            yanit = api.kernels_status(kernel)
            durum = _durum_adi(getattr(yanit, "status", ""))
            ariza = str(getattr(yanit, "failure_message", "") or "")
        except Exception as exc:
            # Tek bir başarısız sorgu akışı bozmasın; bir sonraki turda yeniden denenir.
            yield "durum", f"[{gecen // 60:02d}:{gecen % 60:02d}] Durum alınamadı: {hata_metni(exc)}"
            uyu(aralik)
            continue
        if durum in ("queued", "running", "new_script"):
            goruldu = True
        bitis = durum in ("complete", "error", "cancel_acknowledged")
        if bitis and not goruldu and gecen < ESKI_DURUM_PAYI:
            durum = "queued"     # büyük olasılıkla önceki çalıştırmanın durumu
            bitis = False
        if durum != son or not bitis:
            yield "durum", (f"[{gecen // 60:02d}:{gecen % 60:02d}] Kaggle: "
                            f"{DURUM_ADLARI.get(durum, durum)}")
            son = durum
        if bitis:
            break
        uyu(aralik)

    try:
        if durum == "complete":
            yield "durum", "Çıktı indiriliyor…"
            ciktilar, gunluk = ciktiyi_indir(api, kernel, hedef, calisma)
            if not ciktilar:
                yield "hata", "Kernel tamamlandı ama indirilecek video çıkmadı.", gunluk
                return
            yield "bitti", ciktilar, gunluk
            return
        gunluk = gunlugu_indir(api, kernel, calisma)
    except Exception as exc:
        yield "hata", "Kaggle çıktısı indirilemedi: " + hata_metni(exc), ""
        return
    neden = DURUM_ADLARI.get(durum, durum)
    yield "hata", f"Kaggle çalıştırması bitmedi ({neden}). {ariza}".strip(), gunluk
