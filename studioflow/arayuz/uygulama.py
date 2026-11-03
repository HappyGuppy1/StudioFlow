"""Uygulama: sayfaları sırayla kurar, olayları bağlar ve sunucuyu başlatır.

Bileşen oluşturma sırası eski `app.py` ile aynıdır (Gradio bileşen kimlikleri korunur):
başlık → üst çubuk ve ayar çekmecesi → Proje oluştur → Araçlar (video, görsel, sabit karakter, ses, prompt [araştırma · seslendirme · tasarım · sahne planla],
müzik üret, ses efekti üret, büyütme, harita animasyonu)
→ API hesapları. Olaylar sayfa sayfa bağlanır.
"""
import gradio as gr

from studioflow.arayuz import render_kilidi, tema
from studioflow.arayuz.sayfa import Bilesenler
from studioflow.arayuz.sayfa_arastirma import ArastirmaAraciSayfasi
from studioflow.arayuz.sayfa_ayarlar import AyarCekmecesi
from studioflow.arayuz.sayfa_buyutme import BuyutmeAraciSayfasi
from studioflow.arayuz.sayfa_efekt_araci import EfektAraciSayfasi
from studioflow.arayuz.sayfa_gorsel import GorselAraciSayfasi
from studioflow.arayuz.sayfa_harita import HaritaAraciSayfasi
from studioflow.arayuz.sayfa_hesaplar import HesaplarSayfasi
from studioflow.arayuz.sayfa_karakter import KarakterAraciSayfasi
from studioflow.arayuz.sayfa_konu_bul import KonuBulSayfasi
from studioflow.arayuz.sayfa_muzik_araci import MuzikAraciSayfasi
from studioflow.arayuz.sayfa_proje import ProjeSayfasi
from studioflow.arayuz.sayfa_prompt import PromptAraciSayfasi
from studioflow.arayuz.sayfa_ses import SesAraciSayfasi
from studioflow.arayuz.sayfa_seslendirme_promptu import SeslendirmePromptuSayfasi
from studioflow.arayuz.sayfa_tasarim_promptu import TasarimPromptuSayfasi
from studioflow.arayuz.sayfa_video import VideoAraciSayfasi
from studioflow.arayuz.sayfa_yazi_araci import YaziAraciSayfasi
from studioflow.cekirdek import depolama, temizlik
from studioflow.cekirdek.yollar import ASSETS, OUTPUTS, ROOT
from studioflow.proje import depo


class Uygulama:
    def __init__(self):
        self.b = Bilesenler()
        # `app.py` arayüzü kurmadan önce Gradio önbelleğini temizlediyse True olur;
        # açılış temizliği o klasörü yeniden ele almaz.
        self.gradio_onbellegi_temiz = False
        self.ayarlar = AyarCekmecesi()
        self.proje = ProjeSayfasi()
        self.video = VideoAraciSayfasi()
        self.gorsel = GorselAraciSayfasi()
        self.karakter = KarakterAraciSayfasi()
        self.ses = SesAraciSayfasi()
        self.muzik = MuzikAraciSayfasi()
        self.efekt = EfektAraciSayfasi()
        self.yazi = YaziAraciSayfasi()
        self.buyutme = BuyutmeAraciSayfasi()
        self.harita = HaritaAraciSayfasi()
        self.arastirma = ArastirmaAraciSayfasi()
        self.konu_bul = KonuBulSayfasi()
        self.seslendirme_promptu = SeslendirmePromptuSayfasi()
        self.tasarim_promptu = TasarimPromptuSayfasi()
        # Araştırma, Video konusu bul, Seslendirme ve Tasarım promptu, Prompt sayfasının alt
        # sekmeleridir; bileşenlerini Prompt kurar, olaylarını kendileri bağlar.
        self.prompt = PromptAraciSayfasi(self.arastirma, self.konu_bul,
                                         self.seslendirme_promptu, self.tasarim_promptu)
        self.hesaplar = HesaplarSayfasi()
        # Olay bağlama sırası: eski app.py'deki bağlantı sırasına en yakın düzen.
        self.sayfalar = [self.hesaplar, self.ayarlar, self.video, self.ses, self.gorsel,
                         self.karakter,
                         self.prompt, self.muzik, self.efekt, self.yazi, self.buyutme, self.arastirma, self.konu_bul,
                         self.seslendirme_promptu, self.tasarim_promptu, self.proje, self.harita]

    def kur(self):
        """Gradio arayüzünü kur ve `gr.Blocks` nesnesini döndür (başlatmaz)."""
        b = self.b
        # Eşzamanlı render'lar birbirini bozmasın (bkz. `render_kilidi`).
        render_kilidi.kur()
        b.demo = gr.Blocks(title="StudioFlow · Fotoğraftan video ve seslendirme")
        with b.demo:
            # Logo üst çubuğun içinde kurulur (bkz. `AyarCekmecesi.kur`).
            # Ses testi düğmeleri biraz daha kalın dursun: Gradio'nun varsayılan düğme boyutu
            # en büyüğü olduğu için kalınlık burada biçimle verilir.
            gr.HTML("<style>\n"
                    ".sf-test-btn, .sf-test-btn button { min-height: 44px; font-weight: 600; }\n"
                    # Üst çubuk: durum yazısı solda kalır, ☰ ve ✕ en sağa yapışır.
                    ".sf-ust-cubuk { align-items: center; }\n"
                    ".sf-kapat-btn { margin-left: auto; }\n"
                    # ☰ düğmesi sağdaki ayar çekmecesini açar; üç çizgi "panel" anlamında.
                    ".sf-menu-btn button { min-width: 46px; font-size: 19px; line-height: 1; "
                    "font-weight: 700; padding: 4px 10px; }\n"
                    ".sf-menu-btn button:hover { filter: brightness(1.08); }\n"
                    # Proje paneli sabit yüksekliktedir: liste uzarsa sayfa itilmez, panel
                    # kendi içinde yukarı-aşağı kaydırılır.
                    ".sf-proje-paneli { max-height: 340px; overflow-y: auto; padding: 4px 8px; "
                    "border: 1px solid var(--border-color-primary); border-radius: 8px; }\n"
                    ".sf-proje-paneli .sf-proje-adi p { margin: 0; font-weight: 600; }\n"
                    ".sf-kapat-btn button { min-width: 46px; font-size: 19px; line-height: 1; "
                    "font-weight: 700; padding: 4px 10px; }\n"
                    ".sf-kapat-btn button:hover { filter: brightness(1.08); }\n"
                    # ── Gradio'nun kendi ayar katmanı: sayfanın altındaki dişli düğmesi yerine
                    # sağ çekmece olarak görünür. Katmanın sınıfları Gradio sürümüne bağlıdır;
                    # `:has(.theme-buttons)` yalnızca ayar panelini hedefler ("View API" katmanında
                    # tema düğmeleri yoktur).
                    "footer[aria-label='Gradio footer navigation'] .settings { display: none; }\n"
                    ".api-docs:has(.theme-buttons) { background: transparent !important; "
                    "left: auto !important; width: min(420px, 100vw) !important; }\n"
                    ".api-docs:has(.theme-buttons) .backdrop { display: none; }\n"
                    ".api-docs:has(.theme-buttons) .api-docs-wrap { width: min(420px, 100vw) "
                    "!important; border-radius: 0; }\n"
                    # Yalnızca stil taşıyan bloklar ekranda yer kaplamasın (stil yine uygulanır).
                    ".sf-stil { display: none !important; }\n"
                    "</style>", elem_classes=["sf-stil"])

            gr.HTML("<style>" + tema.CSS + "</style>", elem_classes=["sf-stil"])
            self.ayarlar.kur(b)
            self.proje.kur(b)
            # ── Araçlar: on aracı tek sekme altında toplar ───────────────────────────
            # Üst çubukta **Araçlar** durur; basınca hemen altında ikinci sekme çubuğu
            # açılır: Fotoğraftan video · Görsel üret · Sabit karakter · Seslendirme · Prompt · Müzik üret ·
            # Ses efekti üret · Sesten yazıya · Video büyütme · Harita animasyonu.
            # Prompt'un kendi alt düğmeleri vardır (Araştırma → … → Sahne planla). Sarmalayıcı
            # bağlamlar girinti yerine elle açılıp kapatılır: `__enter__` yalnızca geçerli
            # bağlamı değiştirir, satır girintisinin bir etkisi yoktur; böylece araçların
            # yüzlerce satırı yeniden girintilenmez.
            b.arac_tab = gr.Tab("Araçlar", elem_id="sf-tools", elem_classes=["sf-secondary"])
            b.arac_tab.__enter__()
            gr.HTML(tema.TOOLS_HEADING)
            b.arac_tabs = gr.Tabs(elem_classes=["sf-tool-tabs"])
            b.arac_tabs.__enter__()
            self.video.kur(b)
            self.gorsel.kur(b)
            self.karakter.kur(b)
            self.ses.kur(b)
            self.prompt.kur(b)
            self.muzik.kur(b)
            self.efekt.kur(b)
            self.yazi.kur(b)
            self.buyutme.kur(b)
            self.harita.kur(b)
            # Araçlar sekmesinin sarmalayıcılarını kapat (açılış sırasının tersi).
            b.arac_tabs.__exit__()
            b.arac_tab.__exit__()
            self.hesaplar.kur(b)
            for sayfa in self.sayfalar:
                sayfa.bagla(b)
        return b.demo

    def favicon_ayarlari(self):
        """Tarayıcı sekmesi simgesi: **klasördeki `StudioFlow_logo.ico`** + önbellek kıran bağlantı.

        Gradio dosyayı `/favicon.ico` ucundan servis eder; tarayıcılar bu simgeyi günlerce
        önbellekte tutar (Chrome yeniden istemez), bu yüzden logo dosyası değişse bile
        sekmede **eski** simge görünmeye devam eder. Sayfa başlığına dosyanın **değişim
        zamanı** damgasıyla bir bağlantı eklenir: damga her logo değişiminde değiştiği için
        tarayıcı simgeyi yeniden çeker, sekme ile klasördeki dosya ayrışmaz.

        Dönen ikili `launch(...)`a doğrudan verilir: `(favicon_path, head_html)`.
        """
        yol = ROOT / "StudioFlow_logo.ico"
        damga = int(yol.stat().st_mtime) if yol.is_file() else 0
        return str(yol), f'<link rel="icon" type="image/x-icon" href="favicon.ico?v={damga}">'

    def baslat(self):
        """Sunucuyu 127.0.0.1:7860 üzerinde başlat (tarayıcıyı açmaz; başlatıcı açar)."""
        favicon_path, favicon_head = self.favicon_ayarlari()
        # Gradio önbelleği burada değil, arayüz kurulmadan önce temizlenir (`app.py`):
        # kurulumda kopyalanan örnek dosyalar silinmesin.
        temizlik.arka_planda_temizle(gradio=not self.gradio_onbellegi_temiz)
        # Sayfa açılışında onlarca `demo.load`/`.change` olayı aynı anda kuyruğa girer;
        # küçük sınır (eski 4) bunları "This application is currently busy" ile reddediyordu.
        # Ağır işler zaten `concurrency_limit=1` ile sıraya konuyor, sınır yalnızca taşmaya karşı.
        self.b.demo.queue(max_size=64).launch(
            server_name="127.0.0.1", server_port=7860, share=False,
            allowed_paths=[str(OUTPUTS), str(ASSETS), str(depo.klasoru_hazirla()),
                           str(depolama.GECICI)],
            max_file_size="20mb", inbrowser=False,
            favicon_path=favicon_path, head=favicon_head + tema.HEAD_JS,
            theme=tema.GRADIO_TEMASI)
