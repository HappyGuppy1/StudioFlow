"""Masaüstü uygulaması: editör kendi penceresinde açılır (WebView2), tarayıcı kullanılmaz.

Pencere hemen açılır ve "açılıyor" ekranı gösterir; sunucu (`sunucu.uygulama`, ağır
içe aktarmalar) arka planda kalkınca pencere editöre geçer. Sunucu yalnızca bu pencere
için çalışır: 7870 doluysa boş bir port seçilir, pencere kapanınca sunucu da kapanır.

- Tek kopya: uygulama açıkken ikinci kez açılırsa yeni kopya başlamaz, açık pencere öne gelir.
- Kapatırken üretim, dışa aktarma ya da araç işi sürüyorsa onay istenir (iş yarıda kalır).
- İndirmeler Windows'un "Farklı kaydet" penceresiyle yapılır; tarayıcı belleği
  (`localStorage`) `.uygulama-verisi/` klasöründe kalıcıdır.
- Sayfadaki tam ekran (önizleme ⛶) pencereyi de tam ekran yapar; sağ tık menüsü açıktır
  (metin alanlarında kopyala/yapıştır).
"""
import ctypes
import os
import socket
import sys
import threading
import time

import uvicorn
import webview

from sunucu import ayar

BASLIK = "StudioFlow"
SIMGE = ayar.STUDIOFLOW_KOK / "StudioFlow_logo.ico"
VERI = ayar.WEBVIEW
GUNLUK = ayar.GUNLUK
UYGULAMA_KIMLIGI = "StudioFlow"       # görev çubuğunda Python'dan ayrı simge
# Kurulum programı da bu adla (Inno Setup `AppMutex`) uygulamanın açık olduğunu anlar.
TEK_KOPYA = "StudioFlow.TekKopya"

ACILIS_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#15171c;color:#e8e9ec;
font:15px system-ui,"Segoe UI",sans-serif;display:grid;place-items:center}
.k{text-align:center}.d{width:34px;height:34px;margin:0 auto 18px;border:3px solid #2c3039;
border-top-color:#7c8cff;border-radius:50%;animation:d 0.9s linear infinite}
@keyframes d{to{transform:rotate(360deg)}}.s{color:#8b909c;font-size:13px;margin-top:6px}
</style></head><body><div class="k"><div class="d"></div><div>StudioFlow açılıyor…</div>
<div class="s" id="s">StudioFlow modülleri yükleniyor</div></div></body></html>"""

HATA_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#15171c;color:#e8e9ec;
font:15px system-ui,"Segoe UI",sans-serif;display:grid;place-items:center}
.k{max-width:640px;padding:24px}pre{white-space:pre-wrap;background:#1d2027;padding:12px;
border-radius:8px;color:#ff9b9b;font-size:12px;max-height:50vh;overflow:auto}
</style></head><body><div class="k"><h3>StudioFlow açılamadı</h3><pre>{hata}</pre>
<p>Ayrıntılar: {gunluk}</p></div></body></html>"""


def _tek_kopya_mi():
    """İlk kopyaysa True; mutex süreç ömrü boyunca tutulur."""
    k32 = ctypes.windll.kernel32
    _tek_kopya_mi.tutamac = k32.CreateMutexW(None, False, TEK_KOPYA)
    return k32.GetLastError() != 183                 # ERROR_ALREADY_EXISTS


def _acik_pencereyi_one_getir():
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, BASLIK)
    if hwnd:
        u32.ShowWindow(hwnd, 9)                      # SW_RESTORE (simge durumundaysa)
        u32.SetForegroundWindow(hwnd)


def bos_port(tercih):
    """Tercih edilen port boşsa onu, doluysa işletim sisteminin verdiği boş portu döndür."""
    for port in (tercih, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((ayar.ADRES, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise RuntimeError("Boş port bulunamadı.")


def suren_isler():
    """Pencere kapanınca yarıda kalacak işlerin başlıkları."""
    isler = []
    try:
        from sunucu import disa_aktar, uretim
        from sunucu.kopru import KOPRU
    except Exception:
        return isler
    is_ = uretim.is_durumu()
    if is_ and is_["durum"] == "calisiyor":
        isler.append(f"{is_['baslik']} ({is_['ad']})")
    isler += [f"Dışa aktarma ({ad})" for ad, i in list(disa_aktar._ISLER.items())
              if i.durum == "calisiyor"]
    isler += [f"Araç: {i.baslik}" for i in list(KOPRU._isler.values()) if i.durum == "calisiyor"]
    return isler


def kapanabilir_mi(soru=None):
    """Süren iş yoksa True; varsa yarıda kalacağını söyleyip onay ister."""
    isler = suren_isler()
    if not isler:
        return True
    return (soru or _soru)("Şu işler sürüyor ve uygulama kapanırsa yarıda kalır:\n\n• "
                           + "\n• ".join(isler) + "\n\nYine de kapatılsın mı?")


def _soru(metin):
    """Evet/Hayır sorusu (Win32 MessageBox: her iş parçacığından güvenle çağrılır)."""
    hwnd = ctypes.windll.user32.FindWindowW(None, BASLIK)
    return ctypes.windll.user32.MessageBoxW(hwnd, metin, BASLIK, 0x4 | 0x30 | 0x100) == 6


class Uygulama:
    def __init__(self):
        self.sunucu = None
        self.adres = ""
        self.tam_ekran = False
        self.pencere = webview.create_window(
            BASLIK, html=ACILIS_HTML, width=1440, height=900, min_size=(1024, 640),
            maximized=True, background_color="#15171c", text_select=True)
        self.pencere.events.closing += self._kapanirken
        self.pencere.events.loaded += self._yuklendi
        self.pencere.events.shown += self._gosterildi
        self._webview_kuruldu = False

    # ── sunucu ─────────────────────────────────────────────────────────────
    def sunucuyu_baslat(self):
        """`webview.start(func=…)` ile arka planda çalışır; hazır olunca editörü yükler."""
        try:
            from sunucu.uygulama import app      # ağır içe aktarma: pencere bu sırada açık
            port = bos_port(ayar.PORT)
            self.adres = f"http://{ayar.ADRES}:{port}/"
            self.sunucu = uvicorn.Server(uvicorn.Config(app, host=ayar.ADRES, port=port,
                                                        log_level="warning"))
            is_parcacigi = threading.Thread(target=self.sunucu.run, name="sunucu", daemon=True)
            is_parcacigi.start()
            for _ in range(600):
                if self.sunucu.started:
                    break
                if not is_parcacigi.is_alive():
                    raise RuntimeError(f"Sunucu {self.adres} adresinde başlatılamadı.")
                time.sleep(0.05)
            else:
                raise RuntimeError("Sunucu 30 saniyede başlamadı.")
            print(f"StudioFlow · {self.adres} · StudioFlow: {ayar.STUDIOFLOW_KOK}")
            self.pencere.load_url(self.adres)
        except Exception as exc:
            import html
            import traceback
            traceback.print_exc()
            self.pencere.load_html(HATA_HTML.replace("{hata}", html.escape(str(exc)))
                                   .replace("{gunluk}", html.escape(str(GUNLUK))))

    # ── pencere olayları ───────────────────────────────────────────────────
    def _kapanirken(self):
        return kapanabilir_mi()

    def _gosterildi(self):
        """Başlık çubuğu da koyu olsun (Windows 10 20H1+ / 11; eski sürümde etkisizdir)."""
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, BASLIK)
            koyu = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(koyu),
                                                       ctypes.sizeof(koyu))
        except Exception:
            pass

    def _yuklendi(self):
        """WebView2 ayarları (bir kez): sağ tık menüsü ve sayfa tam ekranı → pencere tam ekranı."""
        if self._webview_kuruldu:
            return
        self._webview_kuruldu = True
        try:
            from System import Action                # pythonnet (pywebview ile gelir)
            form = self.pencere.native

            def kur():
                core = form.webview.CoreWebView2
                core.Settings.AreDefaultContextMenusEnabled = True
                core.ContainsFullScreenElementChanged += self._sayfa_tam_ekran

            form.Invoke(Action(kur))
        except Exception as exc:                     # süsleme: pencere yine çalışır
            print("WebView2 ayarı yapılamadı:", exc)

    def _sayfa_tam_ekran(self, sender, _args):
        istenen = bool(sender.ContainsFullScreenElement)
        if istenen != self.tam_ekran:
            self.tam_ekran = istenen
            threading.Thread(target=self.pencere.toggle_fullscreen, daemon=True).start()

    def kapat(self):
        if self.sunucu:
            self.sunucu.should_exit = True



def calistir():
    if not _tek_kopya_mi():
        _acik_pencereyi_one_getir()
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(UYGULAMA_KIMLIGI)
    except Exception:
        pass
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # dış bağlantılar tarayıcıda
    # Uçtan uca testler Playwright'ı bu porttan pencereye bağlar (yalnızca değişken verilirse).
    if os.environ.get("STUDIOFLOW_EDITOR_CDP_PORT"):
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["STUDIOFLOW_EDITOR_CDP_PORT"])
    VERI.mkdir(parents=True, exist_ok=True)
    uyg = Uygulama()
    webview.start(uyg.sunucuyu_baslat, gui="edgechromium", private_mode=False,
                  storage_path=str(VERI), icon=str(SIMGE) if SIMGE.is_file() else None)
    uyg.kapat()
    # Yarıda bırakılmayı onaylanan işlerin iş parçacıkları süreci açık tutmasın.
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.flush()
        except Exception:
            pass
    os._exit(0)
