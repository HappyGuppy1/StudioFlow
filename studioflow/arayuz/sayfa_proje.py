"""Proje oluştur sekmesi: kütüphane ve CapCut tarzı proje editörü (bkz. `editor`)."""
from pathlib import Path

import gradio as gr

from studioflow.arayuz import editor, tema
from studioflow.arayuz.islevler_efekt import (
    PJ_EFEKT_HAZIR, PJ_UR_EFEKT_HAZIR, oynatici as pj_efd_oynatici, pj_efd_bul,
    pj_efd_kayitlari, pj_efd_onayla, pj_efd_onaylaniyor, pj_efd_tekrar,
    pj_efekt_manuel_hazirla,
    pj_efekt_yz_hazirla)
from studioflow.arayuz.islevler_proje import (
    pj_altyazi_onizleme, pj_altyazi_preset_degisti, pj_altyazi_yeniden,
    katman_rozeti_html, pj_gorsel_onay_agnes, pj_gorsel_onay_ltx, pj_ayar_uygula, pj_ayarlari_kaydet, pj_ayarlari_sil, pj_baslat,
    pj_bicim_degisti, CIKTI_MODLARI, CIKTI_VIDEO, pj_cikti_modu_degisti, pj_modlu,
    pj_ses_dosyasi_indir,
    KARAKTER_DUGMESI, pj_dil_degisti, pj_gorsel_ac, pj_karakter_duzenle, pj_karakter_kaydet, pj_karakter_paneli, pj_karakter_referans_uret, pj_karakter_sil, pj_gorsel_model_degisti, pj_gorsel_yenile,
    ilk_negatif_gorunumu, pj_ham_video_goster,
    pj_ilk_prompt_olcusu, pj_katmanlar,
    pj_muzik_dosya_degisti, pj_muzik_isaret,
    pj_on_ayar_degisti, pj_panel_bos, pj_panel_doldur, pj_panel_projeden, pj_panel_sayilari,
    pj_sahne_ac,
    pj_prompt_ai_sec, pj_prompt_listele, pj_prompt_secildi, pj_sahne_planla,
    pj_sahne_prompt_onayla, pj_sahne_stratejisi_sec,
    pj_sahne_yenile, pj_secime_don, pj_editor_proje_degisti, pj_editor_sahne_sec,
    pj_editor_sahne_tazele,
    pj_izler_tazele, pj_secili_kare_yenile, pj_secili_klip_yenile, pj_serit_tazele,
    pj_ses_servis_degisti, pj_sesi_indir, pj_ses_testi,
    pj_sil_iptal, pj_sil_onayla, pj_sil_uyarisi, pj_yeni_panel_ac, pj_yeni_panel_kapat,
    sahne_etiketi)
from studioflow.arayuz.islevler_muzik_uretimi import PJ_MUZIK_YZ_HAZIR, pj_muzik_yz_uret
from studioflow.arayuz.islevler_proje_belgeleri import (
    pj_belge_listeleri, pj_prompt_belgesi_ac, pj_seslendirme_belgesi_ac)
from studioflow.arayuz.islevler_ses import ilk_ses
from studioflow.arayuz.sabitler import (
    DOSYA_PANEL_YUKSEKLIK, PJ_ALTYAZI_HAZIR, PJ_COK_HAZIR, PJ_MUZIK_HAZIR,
    PJ_UR_ALTYAZI_HAZIR, PJ_UR_DUBLAJ_HAZIR, PJ_UR_MUZIK_HAZIR, PJ_VARSAYILAN,
    PJ_VARSAYILAN_ANAHTAR, PJ_VARSAYILAN_DIL, PJ_VARSAYILAN_GORSEL, PJ_VARSAYILAN_NOT,
    STYLE, SUB_PRESETLER)
from studioflow.arayuz.sayfa import Sayfa
from studioflow.altyazi import gorunum
from studioflow.ayarlar import bicimler, proje_ayarlari
from studioflow.cekirdek import depolama
from studioflow.proje import (
    ayar_normalize, calisma_kilidi, coklu_uretim, depo, ilerleme, on_ayarlar, sabitler,
    yeniden_deneme, yonetim)
from studioflow.proje import karakterler as kadro
from studioflow.proje.katmanlar import (
    altyazilar, diller, dublaj, efekt_duzenleme, efekt_ekleme, efektler, muzik, ses_ciktisi,
    ses_ekleme)
from studioflow.saglayicilar import gorsel_cloudflare, metin_ortak, ses_edge, video_huggingface
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.yollar import ASSETS
from studioflow.saglayicilar.ses_ortak import GEMINI_MODELS, VOICES
from studioflow.saglayicilar.muzik_lyria import BPM_SINIRI, SURE_SINIRI
from studioflow.proje.sahne_stratejileri import (
    STRATEJI_BIRINCI_KISI, STRATEJI_DEFAULT, STRATEJI_TARIH, VARSAYILAN_STRATEJI)


class ProjeSayfasi(Sayfa):
    ad = "proje"

    def kur(self, b):
        self.b = b     # geri çağrı yöntemleri bileşen listelerine buradan erişir
        with gr.Tab("Proje oluştur", elem_id="sf-project"):        # ── 1. adım · proje seçimi ────────────────────────────────────────────────
            self._kur_secim_ekrani(b)

            # ── 2. adım · editör ─────────────────────────────────────────────────────
            # Panel bir proje açılınca (ya da yeni proje adı onaylanınca) görünür; **‹
            # Projeler** düğmesi paneli gizleyip seçim ekranına döndürür.
            #
            # Düzen CapCut tarzı tek ekrandır: solda bölüm şeridi ve seçili bölümün paneli,
            # ortada önizleme, sağda seçili sahnenin paneli, altta sahne şeridi ve izler.
            # Eskiden üç sekmeydi ("İçerik ve ayarlar", "Müzik · dublaj · altyazı",
            # "Üretim ve sonuç"); bir sesi kaydetmek bir sekmede, videoya eklemek başka
            # sekmedeydi. Artık her katmanın kaydı ve videoya eklenmesi aynı bölümdedir.
            with gr.Column(visible=False, elem_classes=["sf-workspace"]) as b.pj_calisma:
                self._kur_proje_cubugu(b)
                with gr.Row(elem_classes=["sf-editor"]):
                    with gr.Column(min_width=0, elem_classes=["sf-ray"]):
                        # Bölüm şeridi: seçim yalnızca tarayıcıda hangi panelin görüneceğini
                        # değiştirir (bkz. `editor.BOLUM_JS`); bütün paneller hep kuruludur.
                        b.pj_bolum = gr.Radio(editor.BOLUM_SECENEKLERI,
                                              value=editor.VARSAYILAN_BOLUM, show_label=False,
                                              container=False, elem_classes=["sf-ray-secim"])
                        b.pj_araclar_btn = gr.Button("🧰\nAraçlar", size="sm",
                                                     elem_classes=["sf-ray-arac"])
                    with gr.Column(min_width=0, elem_classes=["sf-bolum-alani"]):
                        # Kurulum sırası bileşen bağımlılıklarını izler: Metin önce kurulur
                        # (proje adı, listelerin girdisi); ekrandaki sıra şerittedir.
                        for anahtar, kurucu in (("metin", self._kur_metin),
                                                ("hazirlik", self._kur_hazirlik),
                                                ("karakter", self._karakter_paneli),
                                                ("sahneler", self._kur_sahneler),
                                                ("uretim", self._kur_uretim_paneli),
                                                ("seslendirme", self._kur_seslendirme),
                                                ("dublaj", self._kur_dublaj),
                                                ("muzik", self._kur_muzik),
                                                ("altyazi", self._kur_altyazi),
                                                ("efekt", self._kur_efekt),
                                                ("ayarlar", self._kur_ayarlar)):
                            with gr.Column(min_width=0,
                                           elem_classes=["sf-bolum", f"sf-bolum-{anahtar}"]):
                                gr.HTML(editor.bolum_basligi(anahtar))
                                kurucu(b)
                    # `sf-studio-stage`: önizleme düğmelerinin mevcut stilleri bu sınıfa bağlı.
                    with gr.Column(min_width=0, elem_classes=["sf-sahne-alani", "sf-studio-stage"]):
                        self._kur_onizleme(b)
                    with gr.Column(min_width=0, elem_classes=["sf-denetci"]):
                        self._kur_denetci(b)
                self._kur_zaman_cizelgesi(b)

    def _kur_proje_cubugu(self, b):
        """Proje çubuğu: geri dönüş, açık proje, üretim modu ve akışı yöneten düğmeler."""
        # Tek satır: eskiden üç ayrı satırdı (geri dönüş, büyük başlık, düğmeler) ve iş
        # alanı ekranın altına itiliyordu.
        with gr.Row(variant="panel", equal_height=True,
                    elem_classes=["sf-actions", "sf-proje-cubugu"]):
            b.pj_geri_btn = gr.Button("‹ Projeler", size="sm", scale=0, min_width=110,
                                      elem_classes=["sf-geri-btn"])
            b.pj_acik_not = gr.Markdown("", elem_classes=["sf-acik-not"])
            # Görsel ve video üretiminin modu: tekli (sırayla, varsayılan) ya da çoklu
            # (hesaplara bölünüp paralel, bkz. `coklu_uretim`). Bütün akışı etkilediği için
            # başlat düğmesinin yanında durur; aşamalar başlarken okunur.
            b.pj_uretim_modu = gr.Radio(
                [(ad, anahtar) for anahtar, ad in coklu_uretim.URETIM_MODLARI.items()],
                value=lambda: coklu_uretim.VARSAYILAN.deger, show_label=False,
                container=False,
                scale=0, min_width=0, elem_classes=["sf-uretim-modu"])
            b.pj_basla = gr.Button("▶ Projeye başlat", variant="primary", scale=0,
                                   min_width=170)
            b.pj_devam = gr.Button("⏵ Kaldığı yerden devam et", scale=0, min_width=210)
            b.pj_durdur = gr.Button("⏹ Durdur", variant="stop", scale=0, min_width=100)
            b.pj_deneme_btn = gr.Button("↻ Deneme hakkını yenile", size="sm", scale=0,
                                        min_width=180)

    def _kur_secim_ekrani(self, b):
        """1. adım · proje seçimi: yeni proje paneli, proje listesi ve silme uyarısı."""
        # Sekme açılınca önce bu ekran gelir: en üstte **＋ Yeni proje oluştur**
        # düğmesi, altında sabit yükseklikli proje paneli. Panelde her proje kendi
        # satırında durur ve yanında **yalnızca** **Aç** ile **Sil** bulunur; proje
        # sayısı paneli taşarsa panel kendi içinde kaydırılır.
        # Silme onay kutusu **yoktur**: **Sil** ekranın ortasında bir onay penceresi
        # açar, silme yalnızca **Evet, sil** ile yapılır. Yeni proje de küçük bir ad paneliyle açılır.
        with gr.Column(elem_classes=["sf-library"]) as b.pj_secim_ekrani:
            gr.HTML(tema.PROJECT_HERO)
            # Panelin çizileceği liste: silme ve yeni proje sonrası bu durum tazelenir.
            b.pj_projeler = gr.State(depo.liste())
            # Çalışma panelinin **hangi projeye ait olduğu** (klasör adı). Proje açılınca
            # ya da yeni proje oluşturulunca yazılır; proje adı elle değiştirilirse içerik
            # alanları boşaltılır ki bir projenin metni/prompt'u diğerine geçmesin.
            b.pj_acik = gr.State("")
            with gr.Row(elem_classes=["sf-library-toolbar"]):
                gr.Markdown("## Projelerin\nTüm hikâyelerin, tek bir yerde.")
                b.pj_yeni_ac_btn = gr.Button("＋ Yeni proje oluştur", variant="primary", scale=0,
                                           min_width=230)
            with gr.Group(visible=False, elem_classes=["sf-confirmation"]) as b.pj_yeni_panel:
                with gr.Row(equal_height=True):
                    b.pj_yeni_ad = gr.Textbox(label="Proje adı", scale=5,
                                            placeholder="ör. kedi-videosu")
                    b.pj_yeni_olustur_btn = gr.Button("Oluştur", variant="primary", scale=0,
                                                    min_width=120)
                    b.pj_yeni_iptal_btn = gr.Button("İptal", size="sm", scale=0, min_width=90)
                b.pj_yeni_durum = gr.Markdown("")
            with gr.Column(elem_classes=["sf-proje-paneli"]):
                @gr.render(inputs=[b.pj_projeler], queue=False)
                def _pj_satirlari(adlar):
                    """Proje panelinin satırları: proje adı + **Aç** + **Sil**.

                    `pj_projeler` her değiştiğinde (silme, yeni proje) liste yeniden
                    çizilir. Düğmeler satırın kendi projesine bağlanır; başka düğme
                    olmadığı için yanlış projeye işlem yapılamaz.
                    """
                    if not adlar:
                        gr.Markdown("Henüz proje yok. **＋ Yeni proje oluştur** ile başla.",
                                    elem_classes=["sf-proje-bos"])
                        return
                    for ad in adlar:
                        with gr.Row(equal_height=True, elem_classes=["sf-project-row"]):
                            gr.Markdown(ad, elem_classes=["sf-proje-adi"])
                            pj_ac = gr.Button("Aç", variant="primary", size="sm", scale=0,
                                              min_width=80)
                            pj_sil = gr.Button("🗑 Sil", variant="stop", size="sm",
                                               scale=0, min_width=90)
                            # Aç: projenin görünümü, içeriği, ayarları ve panel alanları
                            # (dil özeti dahil) tek seferde yüklenir.
                            # Açılınca sahne seçimi sıfırlanır ve şerit çizilir; aynı proje
                            # yeniden açıldığında da (o zaman `pj_acik` değişmez).
                            pj_ac.click(lambda secili=ad: self.pj_projeyi_ac(secili), None,
                                        b.pj_ac_ciktilari, api_name=False
                                        ).then(pj_editor_proje_degisti, [b.pj_ad],
                                               b.pj_editor_sifir_ciktilari, queue=False,
                                               show_progress="hidden", api_name=False)
                            pj_sil.click(lambda secili=ad: pj_sil_uyarisi(secili), None,
                                         [b.pj_sil_hedef, b.pj_sil_uyari, b.pj_sil_panel],
                                         api_name=False)
            # Silme uyarısı: listenin altında değil, ekranın ortasında açılan bir
            # pencere (arkası karartılır). **Vazgeç** kapatır, **Evet, sil** siler.
            with gr.Group(visible=False, elem_classes=["sf-modal", "sf-delete-modal"]) as b.pj_sil_panel:
                b.pj_sil_uyari = gr.Markdown("", elem_classes=["sf-modal-metin"])
                with gr.Row(equal_height=True, elem_classes=["sf-modal-dugmeler"]):
                    b.pj_sil_iptal_btn = gr.Button("Vazgeç", variant="secondary", size="sm",
                                                 scale=1, min_width=0)
                    b.pj_sil_onay_btn = gr.Button("🗑 Evet, sil", variant="stop", size="sm",
                                                scale=1, min_width=0)
            b.pj_secim_durum = gr.Markdown("")
            b.pj_sil_hedef = gr.State("")

    def _kur_metin(self, b):
        """**Metin** bölümü: proje adı, kayıtlı belgeler, anlatım, prompt katmanları, sahne planı ve ilk sahne."""
        b.pj_ad = gr.Textbox(label="Proje adı",
                           placeholder="ör. kedi-videosu · aynı adı yazarsan proje kaldığı yerden sürer")
        # Araçlar › Prompt'ta kaydedilen belgeler, ayrı ayrı: seslendirme
        # belgesi anlatım metnini, prompt belgesi bütün prompt alanlarını
        # doldurur. Proje adının **altında** durur: ad yazılınca içerik
        # boşaltıldığı için (`pj_ad_degisti`) önce ad, sonra belge seçilir.
        # Kapalı başlar: belgeler ara sıra kullanılır, sayfayı kalabalıklaştırmaz.
        with gr.Accordion("📄 Kayıtlı belgeler · seslendirme ve prompt belgesini yükle",
                          open=False, elem_classes=["sf-belge-panel"]):
            with gr.Row(elem_classes=["sf-belge-secimi"]):
                b.pj_ses_belge = gr.Dropdown(
                    choices=[], value=None, scale=3,
                    label="Seslendirme belgesi · anlatım metnini doldurur")
                b.pj_prompt_belge = gr.Dropdown(
                    choices=[], value=None, scale=3,
                    label="Prompt belgesi · genel prompt, stil, negatif ve ilk sahneyi doldurur")
                b.pj_belge_yenile = gr.Button("↻", scale=0, min_width=46)
            b.pj_belge_not = gr.Markdown("")
        b.pj_metin = gr.Textbox(label="Anlatım metni (seslendirilecek yazı)", lines=8,
                              elem_classes=["sf-narration"],
                              placeholder="Videonun anlatım metnini buraya yapıştır…")
        # Prompt paneli: brief, stil ve negatif prompt bir arada; prompt'ları yazan
        # yapay zekâ da burada seçilir.
        with gr.Accordion("Prompt · genel brief, görsel stil ve negatif prompt", open=True,
                          elem_classes=["sf-prompt-panel"]):
            b.pj_genel_prompt = gr.Textbox(
                label="Genel video prompt'u (İngilizce)", lines=4,
                placeholder="A lone astronaut drifting through a decaying orbital "
                            "station; cold cyan light, slow dolly moves, 35mm "
                            "anamorphic, quiet awe; no text, no logos",
                info="Videonun tamamına hâkim çerçeve: konu, karakterler, mekân, "
                     "atmosfer ve kamera dili. Boş bırakırsan anlatımdan türetilir.")
            # Kutu **dolu** açılır: boş stil bırakıldığında SDXL yağlı boya
            # tablo üretiyor (bkz. docs/STIL-PROMPT-KILAVUZU.md). Kullanıcı
            # üstüne yazıp kendi stilini kurabilir.
            b.pj_gorsel_stil = gr.Textbox(
                label="Görsel stil katmanı (İngilizce)", lines=2,
                value=sabitler.VARSAYILAN_GORSEL_STIL,
                info="Her karenin **başına** eklenir; konum fotoğraf/tablo "
                     "farkını belirliyor. Değiştirebilirsin; boş bırakırsan "
                     "varsayılana döner.")
            # Negatif prompt yalnızca destekleyen modellerde açılır; desteklemeyen modelde
            # alan kilitlenir ve altındaki not sebebini yazar.
            b.pj_negatif = gr.Textbox(
                label="Negatif prompt (opsiyonel)", lines=2,
                value="blurry, low quality, watermark, text, deformed hands, extra fingers",
                info="Yapay zekâ her parça için kendi negatif prompt'unu yazar; "
                     "yazamazsa bu değer kullanılır.")
            b.pj_negatif_not = gr.Markdown("")
            # Prompt yapay zekâsı: sahne planlama stratejisi düğmeleriyle
            # **aynı desen**. Varsayılan Cloudflare'dır — görsel üretimiyle
            # aynı hesabı ve aynı ücretsiz nöron bütçesini kullanır; seçim
            # başlatırken mevcut projeye de uygulanır (bkz. `akis._hazirla`).
            gr.Markdown("**Prompt yapay zekâsı** · anlatımı sahnelere bölen "
                        "ve sahne prompt'larını yazan servis.")
            b.pj_ai = gr.State(metin_ortak.AI_VARSAYILAN)
            with gr.Row():
                b.pj_ai_dugmeleri = [
                    gr.Button(etiket,
                              variant=("primary"
                                       if ad == metin_ortak.AI_VARSAYILAN
                                       else "secondary"), size="sm")
                    for etiket, ad in metin_ortak.ai_secenekleri()]
            b.pj_ai_not = gr.Markdown(
                "Seçili prompt yapay zekâsı: **"
                + metin_ortak.AI_SAGLAYICILAR[
                    metin_ortak.AI_VARSAYILAN]["label"] + "**")
            b.pj_ai_model = gr.Dropdown(
                metin_ortak.AI_SAGLAYICILAR[
                    metin_ortak.AI_VARSAYILAN]["models"],
                value=metin_ortak.AI_SAGLAYICILAR[
                    metin_ortak.AI_VARSAYILAN]["models"][0],
                label="Prompt modeli", allow_custom_value=True)
            # Sahne planlama yaklaşımı: panel kapalı başlayabilir; seçim hem
            # önizleme planına hem de proje üretiminin sahne/prompt akışına gider.
            with gr.Accordion("Sahne planlama stratejisi", open=False):
                editor.yardim(
                    "Sahnelerin nasıl kurulacağını seç. **Default** hiçbir stratejiye "
                    "özgü kural eklemez (kamera ve kurgu serbest), **Tarih** olayın "
                    "neden-sonuç akışını, **Birinci kişi anlatım** ise kamerayı "
                    "anlatıcının gözleri olarak planlar. Başlatırken bu seçim uygulanır. Mevcut projede "
                    "stratejiyi değiştirirsen eski üretim yedeklenir; sahneler ve "
                    "görseller yeniden hazırlanır, üretim kotası kullanılır.")
                with gr.Row():
                    b.pj_sahne_default_btn = gr.Button("Default", variant="secondary")
                    b.pj_sahne_tarih_btn = gr.Button("Tarih", variant="primary")
                    b.pj_sahne_pov_btn = gr.Button("Birinci kişi anlatım", variant="secondary")
                b.pj_sahne_stratejisi = gr.State(VARSAYILAN_STRATEJI)
                b.pj_sahne_stratejisi_not = gr.Markdown(
                    "Seçili sahne planlama stratejisi: **Tarih**")
            # Video sürelerini yapay zekâ belirlesin: sahne sayısı ve sahne
            # başına saniye anlatıma göre hesaplanır, **Adım süresi** güncellenir.
            b.pj_sahne_btn = gr.Button("🎬 Video sürelerini yapay zekâ ayarlasın")
            # Tavan, onu yazan düğmenin **hemen altında** durur: eskiden sağdaki
            # kapalı "Video ayarları" panelindeydi ve kimse görmüyordu.
            b.pj_adim_saniye = gr.Slider(
                sabitler.SAHNE_TAVAN_ARALIGI[0],
                sabitler.SAHNE_TAVAN_ARALIGI[1],
                value=sabitler.ADIM_SANIYE, step=0.5,
                label="Sahne süresi · üst sınır (saniye)",
                info="Bir sahnenin alabileceği **en uzun** süre: 5–8 sn arasında "
                     "seç. Sahne süreleri anlatıma göre bu tavanın altında değişir "
                     "(en kısa sahne 1 sn). 6 sn üstü kesitlerde tek görselden "
                     "üretilen klipte hareket tükenip kare donuklaşabilir.")
            b.pj_sahne_not = gr.Markdown("")
            # 🎬 düğmesiyle üretilen plan burada tutulur ve başlatmaya
            # **girdi** olur: akış sahneyi yeniden planlamaz, bu planı
            # aynen kullanır (bkz. `sahneleme.plan_sahneleri`).
            b.pj_sahne_on_plan = gr.State(None)

        # ── İlk sahne · kancayı elle yaz (opsiyonel) ──────────
        # Short'ta ilk kare videonun kancasıdır; yapay zekânın
        # rastgele yazdığı kare yerine kullanıcı bu üç katmanı
        # kendisi verebilir. Üçü de boşsa davranış değişmez
        # (bkz. `adim_promptlari.ilk_sahne_kaydi`).
        with gr.Accordion("İlk sahne prompt'u · kanca karesi (opsiyonel)",
                          open=False):
            editor.yardim(
                "Short'ta **ilk kare** videonun kancasıdır; izleyici ilk "
                "saniyede kalır ya da kaydırır. Burayı boş bırakırsan 1. "
                "sahneyi yapay zekâ anlatımın ilk cümlesinden kurar; hazır "
                "bir açılış (ör. uyanma) dayatılmaz.  \n"
                "Doldurursan **1. sahnenin ne göstereceğine sen karar "
                "verirsin**: yazdığın içerik prompt'u yazan yapay zekâya "
                "verilir ve kare prompt'u **diğer sahnelerle aynı biçimde** "
                "kurulur — aynı görsel stil, aynı kamera dili. Ayrı bir stil "
                "alanı yoktur: 1. sahne de yukarıdaki **görsel stil "
                "katmanını** kullanır.  \n"
                "İçeriği **İngilizce** yaz (görsel modeli İngilizce çalışır). "
                "Sonuç proje başlayınca `proje.txt`'e **ADIM 1** bloğuna "
                "işlenir; oradan da düzenleyebilirsin.")
            b.pj_ilk_prompt = gr.Textbox(
                label="İlk sahne · ne görünsün (+)", lines=3,
                placeholder="ör. Extreme close-up of a cracked clay tablet "
                            "filling the frame, harsh noon sunlight, "
                            "photorealistic historical cinema",
                info="Yazdığın içerik önceliklidir. Boşsa 1. sahne anlatımın ilk cümlesinden kurulur. En önemli öğeyi "
                     "başa yaz: model yalnızca ilk ~55 kelimeyi okur.")
            b.pj_ilk_prompt_not = gr.Markdown("")
            b.pj_ilk_negatif = gr.Textbox(
                label="İlk sahne · negatif prompt (−)", lines=2,
                placeholder="ör. modern objects, text, watermark",
                info="Projenin genel negatif prompt'uyla birleşir; "
                     "tekrarlar atılır.")

    def _kur_hazirlik(self, b):
        """**Hazırlık** bölümü: araştırmadan sahne planına giden Prompt stüdyosu hattı."""
        gr.Markdown(
            "Videonun malzemesi **Araçlar › Prompt** stüdyosunda hazırlanır; adımlar sırayla:\n\n"
            "1. **Video konusu bul** · viral konu ve alt konular\n"
            "2. **Araştırma** · olayın kaynaklı raporu\n"
            "3. **Seslendirme promptu** · rapordan anlatım metni\n"
            "4. **Tasarım promptu** · genel prompt, görsel stil, negatif, ilk sahne\n"
            "5. **Sahne planla** · anlatımı sahnelere bölüp prompt'ları dener\n\n"
            "Kaydettiğin seslendirme ve tasarım belgeleri **Metin** bölümündeki "
            "**Kayıtlı belgeler** listesinden bu projeye yüklenir.")
        b.pj_prompt_studyo_btn = gr.Button("Prompt stüdyosunu aç", variant="primary")

    def _kur_sahneler(self, b):
        """**Sahneler** bölümü: kare ızgarası (kaldır-yenile) ve adım listesi (sil-yeniden üret)."""
        with gr.Accordion("Kareler · kaldır ve yenile", open=True) as b.pj_kare_box:
            editor.yardim(
                "Videolar başlamadan önce kareleri burada incele. Beğenmediğin "
                "karenin altındaki **🗑 Kareyi kaldır ve yenile** düğmesine bas: "
                "kare silinir ve **aynı prompt'la** yenisi üretilir, sonra onay "
                "yeniden sorulur. Adımın klibi varsa o da silinir (klip kareden "
                "türer); anlatım metni, süresi ve prompt'ları korunur.  \n"
                "Kareler hazır olduğunda **Kareleri göster**'e bas: liste "
                "`proje.txt`'ten tazelenir.")
            b.pj_gorsel_goster_btn = gr.Button("Kareleri göster", size="sm")
            # Liste damgası: her gösterme/yenileme işleminde değişir,
            # `gr.render` bloğu kareleri diskten yeniden okur.
            b.pj_gorsel_liste = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_gorsel_liste], queue=False)
            def _pj_gorsel_satirlari(ad, acik):
                """Adım karelerini üçerli satırlarda göster; her birinin altında
                kaldır-yenile düğmesi."""
                if not acik:
                    gr.Markdown("**Kareleri göster**'e bas: adımların kareleri "
                                "burada listelenir.")
                    return
                if not (ad or "").strip():
                    gr.Markdown("Önce bir proje aç.")
                    return
                kayitlar = yonetim.gorsel_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Listelenecek adım yok: önce **Projeye başlat**'a "
                                "bas; seslendirme ve kareler üretilsin.")
                    return
                hazir = sum(1 for kayit in kayitlar if kayit["gorsel"])
                gr.Markdown(f"**{hazir}/{len(kayitlar)}** adımın karesi hazır.")
                for bas in range(0, len(kayitlar), 3):
                    with gr.Row(elem_classes=["sf-scene-row"]):
                        for kayit in kayitlar[bas:bas + 3]:
                            with gr.Column(min_width=0):
                                if kayit["gorsel"]:
                                    gr.Image(value=kayit["gorsel"],
                                             show_label=False, height=220,
                                             interactive=False)
                                else:
                                    gr.Markdown("*(kare yok · üretilecek)*")
                                gr.Markdown(
                                    f"**{kayit['index']}.** {kayit['sure']:g} sn · "
                                    f"{kayit['durum']}"
                                    + (" · klip var" if kayit["videolu"] else "")
                                    + f"  \n{kayit['metin'] or '—'}")
                                if kayit["gorsel"]:
                                    yenile_btn = gr.Button(
                                        "🗑 Kareyi kaldır ve yenile",
                                        variant="stop", size="sm")
                                    # Adım numarası kapanışta taşınır:
                                    # `gr.State` üretmek her çizimde yeni
                                    # bileşen biriktirirdi. Üreteç olmalı
                                    # (akış ilerledikçe panel tazelenir),
                                    # bu yüzden lambda değil `def`.
                                    def _yenile(proje, sira=kayit["index"]):
                                        yield from pj_gorsel_yenile(proje, sira)

                                    yenile_btn.click(
                                        _yenile, [b.pj_ad], b.pj_ciktilar,
                                        concurrency_limit=1, api_name=False
                                    ).then(pj_gorsel_ac, None,
                                           [b.pj_gorsel_liste], api_name=False)
        with gr.Accordion("Sahneleri incele · adım sil · yeniden üret",
                          open=False) as b.pj_sahne_box:
            editor.yardim(
                "Projedeki adımlar burada düğme olarak listelenir. Beğenmediğin "
                "adımın düğmesine bas → **Sil ve yeniden üret**: yalnızca adımın "
                "videosu silinir, **aynı kareden** yeni video üretilir ve "
                "**proje.mp4** yeniden birleştirilir. Kare yeniden üretilmez "
                "(kareyi değiştirmek için **Görsel sahnelerini düzenle**). Diğer "
                "adımlara dokunulmaz; anlatım metni, prompt'lar ve adımın sırası "
                "korunur.\n\n"
                "Üretim sürerken adımların durumunu izlemek için **Sahneleri incele**'ye "
                "yeniden bas: liste `proje.txt`'ten tazelenir. Silme yalnızca proje "
                "çalışmıyorken yapılır.")
            b.pj_sahne_incele_btn = gr.Button("Sahneleri incele", variant="primary")
            # Liste bu iki durumdan çizilir: `pj_sahne_acik` her basışta değişen
            # bir zaman damgasıdır (liste tazeleme), `pj_sahne_sec` seçili adım.
            b.pj_sahne_acik = gr.State("")
            b.pj_sahne_sec = gr.State(None)

            @gr.render(inputs=[b.pj_ad, b.pj_sahne_acik, b.pj_sahne_sec], queue=False)
            def _pj_sahne_satirlari(ad, acik, secili):
                """Sahne düğmelerini ve seçili sahnenin silme onayını çiz.

                Liste her çizimde `proje.txt`'ten **tazelenir**: başka bir proje
                açılırsa eski projenin adımları görünmez ve silme her zaman açık
                projeye uygulanır.
                """
                if not acik:
                    gr.Markdown("**Sahneleri incele**'ye bas: projenin adımları "
                                "burada düğme olarak listelenir.")
                    return
                adimlar = yonetim.sahne_listesi(ad)
                if not adimlar:
                    gr.Markdown("Listelenecek adım yok: proje okunamadı ya da henüz "
                                "adımlara bölünmedi. Önce **Projeye başlat**'a bas "
                                "ve seslendirme tamamlanana kadar bekle.")
                    return
                toplam = len(adimlar)
                for sira in range(0, toplam, 3):
                    with gr.Row(elem_classes=["sf-scene-row"]):
                        for adim in adimlar[sira:sira + 3]:
                            secili_mi = str(secili) == str(adim["index"])
                            tus = gr.Button(
                                sahne_etiketi(adim, toplam), size="sm",
                                variant="primary" if secili_mi else "secondary",
                                elem_classes=["sf-scene-button"])
                            tus.click(lambda i=adim["index"]: i, None, [b.pj_sahne_sec],
                                      api_name=False)
                secilen = next((oge for oge in adimlar
                                if str(oge["index"]) == str(secili)), None)
                if secilen is None:
                    gr.Markdown("Silinecek adımı seçmek için bir düğmeye bas.")
                    return
                gr.Markdown(
                    f"**Adım {secilen['index']}/{toplam} silinsin mi?** "
                    f"Anlatım: {secilen['metin'] or '—'}  \n"
                    "Silme geri alınamaz: adımın videosu diskten kaldırılır; "
                    "kare ve prompt'lar korunur, aynı kareden yeni video "
                    "üretilir ve video yeniden birleştirilir.")
                with gr.Row(equal_height=True):
                    pj_sahne_sil_btn = gr.Button("Sil ve yeniden üret",
                                                 variant="stop", min_width=210)
                    pj_sahne_iptal_btn = gr.Button("İptal", size="sm", scale=0,
                                                   min_width=90)
                # Silme üreteci yalnızca dıştaki çıktılara yazar; bitince `.then`
                # listeyi tazeler ve seçimi temizler (üretim sürerken `gr.render`
                # bloğu yeniden çizilmez). Adım numarası seçili durumdan gelir.
                pj_sahne_sil_btn.click(
                    pj_sahne_yenile, [b.pj_ad, b.pj_sahne_sec], b.pj_ciktilar,
                    concurrency_limit=1, api_name=False
                ).then(pj_sahne_ac, None, [b.pj_sahne_acik, b.pj_sahne_sec],
                       api_name=False)
                pj_sahne_iptal_btn.click(lambda: None, None, [b.pj_sahne_sec],
                                         api_name=False)

    def _kur_uretim_paneli(self, b):
        """**Üretim** bölümü: prompt kapısı, görsel onayı ve ilerleme (hatalarla)."""
        # Adımlar en üstte, iş akışının sırasıyla: önce prompt'lar, sonra görsel
        # onayı. İlerleme çubuğu onların altında; durum önizlemenin üstünde.
        # ── ① Prompt'lar · seslendirmeden sonraki kapı ───────────────
        # Seslendirme biter, akış **burada durur**; yapay zekâ seçilip düğmeye
        # basılınca sahne planı ve prompt'lar o servisle yazılır (bkz.
        # `akis.akis_calistir` 1.5. adım). Düğmeler içerikteki seçimle aynı
        # `pj_ai` durumunu yazar, ikisi **senkron** kalır (bkz. `pj_prompt_ai_sec`).
        with gr.Column(elem_classes=["sf-adim"]):
            gr.HTML(tema.adim_basligi("1", "Prompt'lar",
                                      "Seslendirmeden sonra servisi seç, başlat."))
            with gr.Row(elem_classes=["sf-ai-secim"]):
                b.pj_ur_ai_dugmeleri = [
                    gr.Button(etiket,
                              variant=("primary"
                                       if ad == metin_ortak.AI_VARSAYILAN
                                       else "secondary"), size="sm")
                    for etiket, ad in metin_ortak.ai_secenekleri()]
            # Seçim düğmelerin renginden okunur; yazılı satır gizli kalır ama
            # içerik sekmesindeki eşiyle aynı çıktı listesini paylaşır.
            b.pj_ur_ai_not = gr.Markdown(
                "Seçili prompt yapay zekâsı: **"
                + metin_ortak.AI_SAGLAYICILAR[
                    metin_ortak.AI_VARSAYILAN]["label"] + "**", visible=False)
            b.pj_prompt_basla_btn = gr.Button("▶ Prompt üretimine başla",
                                             variant="primary")

        # ── ② Görsel onayı · videolardan önceki kapı ─────────────────
        # Akış önce **bütün kareleri** üretir ve burada durur; videolar ancak
        # onayla başlar (bkz. `akis_calistir` 5. adım). Onay `proje.txt`e
        # yazılır, uygulama kapansa da kaybolmaz. Üç düğme de onayı verir, farkları
        # videoyu üreten servistir; hazır sahne videoları silinmez, üretim ilk eksik
        # sahneden sürer. Agnes 2.5 Flash en üstte: kareye sadık, 1248×704 ve ücretsiz
        # kotası LTX'ten geniş (LTX hesap başına günde ~1 klip; Wan2.2 832×480).
        with gr.Column(elem_classes=["sf-adim"]):
            gr.HTML(tema.adim_basligi("2", "Görsel onayı",
                                      "Kareleri atölyede incele, videoları başlat."))
            with gr.Column(elem_classes=["sf-onay-dugmeleri"]):
                # LTX-2.3 öne çıkan (mavi) seçenektir; Wan2.2 düğmesi arayüzden
                # kaldırıldı (12.10.2026) ama bağlantısı bozulmasın diye gizli durur.
                b.pj_gorsel_onay_ltx_btn = gr.Button(
                    "✅ Onayla · LTX-2.3 ile videoları üret (1280×704)",
                    variant="primary")
                b.pj_gorsel_onay_agnes_btn = gr.Button(
                    "✅ Onayla · Agnes AI 2.5 Flash ile videoları üret (1248×704)",
                    variant="secondary")
                b.pj_gorsel_onay_btn = gr.Button(
                    "✅ Onayla · Hugging Face (Wan2.2 · 832×480) ile üret",
                    variant="secondary", visible=False)


        # İlerleme paneli: çubuk, adım sayıları, süre bilgisi ve **hatalar**.
        b.pj_cubuk = gr.HTML(ilerleme.bos_ilerleme_html())

    def _kur_seslendirme(self, b):
        """**Seslendirme** bölümü: ses servisi ve ayarları, ses testi ve videodaki seviye."""
        with gr.Accordion("Ses servisi ve ayarları", open=True):
            b.pj_ses_provider = gr.Radio(
                [("Edge · anahtarsız, hızlı", "edge"), ("Gemini · en doğal", "gemini"),
                 ("Chatterbox · ses klonu", "chatterbox")], value="gemini",
                label="Ses servisi")
            b.pj_dil = gr.Dropdown([(ad, kod) for kod, ad in LANGUAGES.items()],
                                 value=PJ_VARSAYILAN_DIL, label="Dil")
            # Seviye bütün ses servislerinde geçerlidir: ses dosyasına işlenmez,
            # **videoya eklenirken** uygulanır (seslendirme, dublaj, müzik
            # karışımı). Ses zaten ekliyse **Sesi videoya ekle** yeni seviyeyle
            # ses akışını baştan kurar (bkz. `videoya_ses_ekle`).
            # Gizli eş: görünen kaydırıcı aşağıdaki **Videoya ekle** panelindedir
            # (`pj_ur_ses_seviye`, iki yönlü senkron); üretim bu değeri okur.
            b.pj_ses_seviye = gr.Slider(
                *sabitler.SES_SEVIYE_SINIR,
                value=sabitler.SES_VARSAYILAN_SEVIYE, step=5, visible=False,
                label="Ses seviyesi · videodaki seslendirme (%)",
                info="100 = sesin kendi seviyesi. Videoda seslendirme kısık "
                     "geliyorsa yükselt (ör. 150–200); ses **videoya eklenirken** "
                     "uygulanır. Ses zaten ekliyse **Sesi videoya ekle**'ye "
                     "yeniden bas.")
            with gr.Group(visible=False) as b.pj_edge_box:
                b.pj_edge_ses = gr.Dropdown(choices=ses_edge.VARSAYILAN.guvenli_sesler(PJ_VARSAYILAN_DIL),
                                          value=ilk_ses(PJ_VARSAYILAN_DIL),
                                          label="Edge sesi")
                with gr.Row():
                    b.pj_hiz = gr.Slider(-50, 50, value=0, step=5, label="Konuşma hızı (%)")
                    b.pj_ton = gr.Slider(-50, 50, value=0, step=5, label="Ton (Hz)")
            with gr.Group(visible=True) as b.pj_gemini_box:
                with gr.Row():
                    b.pj_gemini_model = gr.Dropdown(GEMINI_MODELS, value=GEMINI_MODELS[0],
                                                  label="Gemini modeli")
                    b.pj_gemini_ses = gr.Dropdown(VOICES, value="Charon", label="Gemini sesi")
                b.pj_stil = gr.Textbox(label="Anlatım üslubu (İngilizce yaz)", value=STYLE,
                                     lines=2)
            with gr.Group(visible=False) as b.pj_chatterbox_box:
                b.pj_ref = gr.Audio(label="Referans ses · 3–30 saniye temiz kayıt",
                                  type="filepath", sources=["upload", "microphone"])
                with gr.Row():
                    b.pj_exag = gr.Slider(0, 2, value=0.5, step=0.05, label="Duygu yoğunluğu")
                    b.pj_cfg = gr.Slider(0, 1, value=0.5, step=0.05,
                                       label="Referansa bağlılık")
            # Ses testi: dilin hazır test cümlesiyle dener; test sesi kaydedilmez.
            b.pj_ses_test_btn = gr.Button("Sesi test et · kaydedilmez", variant="primary",
                                        size="lg", elem_classes=["sf-test-btn"])
            b.pj_ses_test_ses = gr.Audio(label="Test sesi · kaydedilmez", type="filepath",
                                       autoplay=True)
            b.pj_ses_test_durum = editor.durum_kutusu("Hazır.", "Test durumu")

        # Seslendirme seviyesi: ayarlar sekmesindeki kaydırıcının üretim
        # sayfasındaki eşi (ikisi senkron). **Uygula** `videoya_ses_ekle`
        # yoludur: ses ekliyse yeni seviyeyle baştan kurulur (görüntü,
        # altyazı, müzik ve ses efekti korunur), değilse o seviyede eklenir.
        with gr.Accordion("Videoya ekle · seslendirme seviyesi",
                          open=True) as b.pj_ur_ses_box:
            editor.yardim(
                "Videodaki seslendirmenin (ya da ekli dublajın) seviyesi. "
                "Kaydırıcıyı ayarla → **Seviyeyi uygula**. Ses videoda yoksa bu "
                "seviyede eklenir. Müzik ve ses efektleri olduğu gibi kalır.")
            b.pj_ur_ses_seviye = gr.Slider(
                *sabitler.SES_SEVIYE_SINIR,
                value=sabitler.SES_VARSAYILAN_SEVIYE, step=5,
                label="Seslendirme ses seviyesi (%)",
                info="100 = sesin kendi seviyesi. Kısık geliyorsa 150–200 dene.")
            b.pj_ur_ses_uygula_btn = gr.Button("Seviyeyi uygula",
                                               variant="primary", size="sm")
            b.pj_ur_ses_durum = editor.durum_kutusu("", "Seslendirme durumu")

    def _kur_dublaj(self, b):
        """**Dublaj** bölümü: dublajı üret ve kaydet, kayıtlı dublajı videoya ekle."""
        # Dublaj paneli de açık başlar (bkz. müzik paneli).
        with gr.Accordion("Dublaj üret ve kaydet · dil · ses servisi · çeviri",
                          open=True):
            editor.yardim(
                "Dublaj burada **üretilip kaydedilir**; videoya aşağıdaki **Videoya ekle** "
                "panelinden eklenir. Dili seç → gerekirse "
                "**çeviriyi** aç → ses servisini seç → **Dublajı kaydet**. Kaydedilen "
                "her dublaj aşağıdaki listede durur; **ad** verirsen aynı dile birden "
                "fazla dublaj (ör. farklı ses denemeleri) kaydedebilirsin, ad boşsa "
                "kayıt dil koduyla saklanır ve aynı dili yeniden üretmek kaydı "
                "günceller.  \n"
                "Dublajla birlikte altyazı da üretilirse (seslendirme ayarlarındaki "
                "**Altyazı üret**) altyazı **ayrı bir kayıt** olur: artık dublaja "
                "iliştirilmiş bir kutucuk değildir, yandaki altyazı listesinde görünür "
                "ve videoya ayrı gömülür.")
            with gr.Accordion("Ses dosyalarının saklandığı yer", open=False):
                gr.Markdown(
                    f"Dublajlar projenin `ses/{sabitler.DIL_KLASORU}` klasöründe "
                    f"(`seslendirme-<ad>.wav`), listesi `{sabitler.DUBLAJ_LISTE_ADI}` "
                    f"dosyasında saklanır; ham video `{sabitler.HAM_VIDEO_ADI}` "
                    "adıyla ayrı durur ve ilk kez gerektiğinde adım kliplerinden kurulur.")
            b.pj_cok_dil = gr.Dropdown(
                [(ad, kod) for kod, ad in LANGUAGES.items() if kod != "auto"],
                value="en", label="Hedef dil")
            b.pj_cok_cevir = gr.Checkbox(
                value=True, label="Anlatımı hedef dile çevir",
                info="Aşağıda seçilen yapay zekâ çevirir. Kapatırsan metin zaten o "
                     "dilde olmalı; projenin dili ile aynı dili seçersen çeviri "
                     "yapılmaz.")
            b.pj_cok_ceviri_ai = gr.Dropdown(
                metin_ortak.ai_secenekleri(), value="gemini",
                label="Çeviriyi yapan yapay zekâ",
                info="Ses servisinden bağımsızdır; kota biterse aynı servisin "
                     "sıradaki hesabına geçilir.")
            b.pj_cok_sahne = gr.Checkbox(
                value=False, label="Sahnelere göre hizala",
                info="Çeviri ve ses sahne sahne kurulur: her cümle kendi sahnesinin "
                     "süresine sığacak şekilde çevrilir, uzun kalan hafifçe "
                     "hızlandırılır, sesler üst üste binmez. Kapalıyken dublaj tek "
                     "parça üretilir (eski davranış).")
            b.pj_cok_provider = gr.Radio(
                [("Edge · anahtarsız, hızlı", "edge"),
                 ("Gemini · en doğal", "gemini"),
                 ("Chatterbox · ses klonu", "chatterbox")], value="gemini",
                label="Ses servisi")
            with gr.Group(visible=False) as b.pj_cok_edge_box:
                b.pj_cok_edge_ses = gr.Dropdown(choices=ses_edge.VARSAYILAN.guvenli_sesler("en"),
                                              value=ilk_ses("en"), label="Edge sesi")
                with gr.Row():
                    b.pj_cok_hiz = gr.Slider(-50, 50, value=0, step=5,
                                           label="Konuşma hızı (%)")
                    b.pj_cok_ton = gr.Slider(-50, 50, value=0, step=5, label="Ton (Hz)")
            with gr.Group(visible=True) as b.pj_cok_gemini_box:
                with gr.Row():
                    b.pj_cok_gemini_model = gr.Dropdown(GEMINI_MODELS,
                                                      value=GEMINI_MODELS[0],
                                                      label="Gemini modeli")
                    b.pj_cok_gemini_ses = gr.Dropdown(VOICES, value="Charon",
                                                    label="Gemini sesi")
            with gr.Group(visible=False) as b.pj_cok_chatterbox_box:
                gr.Markdown(
                    "Chatterbox, **API hesapları** sekmesindeki Hugging Face tokenıyla "
                    "çalışır ve sesi referans kaydı olmadan üretir. Sesi klonlamak için "
                    "**Araçlar › Seslendirme** aracını kullan.")
            b.pj_dublaj_ad = gr.Textbox(
                label="Dublaj adı (opsiyonel)",
                placeholder="ör. en-charon · boş bırakırsan dil kodu kullanılır",
                info="Ad dosya adına çevrilir (boşluk `-` olur). Aynı adla "
                     "kaydetmek kaydı günceller.")
            b.pj_cok_uret_btn = gr.Button("Dublajı kaydet", variant="primary")
            # Dinleme ve indirme alanları kapalı durur: boş bir ses çaları ile dosya
            # listesi sayfada çok yer kaplıyordu. İçerik gelince kendiliğinden açılır
            # (bkz. `pj_cok_ses.change` / `pj_cok_dosyalar.change` bağlantıları).
            with gr.Accordion("Üretilen dublaj · dinle",
                              open=False) as b.pj_cok_ses_box:
                b.pj_cok_ses = gr.Audio(label="Üretilen dublaj", type="filepath")
            with gr.Accordion("Dublaj dosyaları · ses · altyazı · metin",
                              open=False) as b.pj_cok_dosya_box:
                b.pj_cok_dosyalar = gr.File(label="Dublaj dosyaları (ses · altyazı · metin)",
                                          file_count="multiple")
            b.pj_cok_durum = editor.durum_kutusu(PJ_COK_HAZIR, "Dublaj durumu")
            gr.Markdown("**Kaydedilmiş dublajlar** · videoya eklemek için aşağıdaki "
                        "**Videoya ekle** panelinden seç.")
            # Dublaj listesi de müzik listesi gibi çizilir: damga her
            # kayıt/silmede değişir, seçim üretim sayfasında kullanılır.
            b.pj_dublaj_liste = gr.State("")
            b.pj_dublaj_secim = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_dublaj_liste], queue=False)
            def _pj_dublaj_satirlari(ad, _damga):
                """Kaydedilmiş dublajları listeler (kaydet/sil; ekleme burada değil)."""
                if not (ad or "").strip():
                    gr.Markdown("Dublaj listesi için önce bir proje aç.")
                    return
                kayitlar = diller.dublaj_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı dublaj yok: dil seç ve **Dublajı kaydet**'e bas.")
                    return
                for kayit in kayitlar:
                    with gr.Row(equal_height=True, elem_classes=["sf-saved-music-row"]):
                        gr.Markdown(f"**{kayit['ad']}** · "
                                    + dublaj.dublaj_ozeti(kayit), scale=5)
                        sil_btn = gr.Button("🗑 Sil", variant="stop", size="sm",
                                            scale=0, min_width=90)
                    sil_btn.click(
                        lambda proje, isim=kayit["ad"]: diller.dublaj_sil(
                            proje, isim),
                        [b.pj_ad], b.pj_dublaj_ciktilari, api_name=False)

            b.pj_cok_liste = editor.durum_kutusu("", "Kayıtlar · ham video durumu")

        with gr.Accordion("Videoya ekle · kayıtlı dublaj",
                          open=True) as b.pj_ur_dublaj_box:
            editor.yardim(
                "Bir dublaj seç → **Seçili dublajı videoya ekle**. Video ham "
                "videodan yeniden kurulur: videoda tek konuşma sesi olur, "
                "gömülü altyazı kalkar (yeniden gömebilirsin), ekli müzik "
                "kendiliğinden geri uygulanır. Kayıtlar silinmez; istediğin "
                "zaman başka bir dublajı ekleyebilirsin.")

            @gr.render(inputs=[b.pj_ad, b.pj_dublaj_liste, b.pj_dublaj_secim], queue=False)
            def _pj_ur_dublaj(ad, _damga, secili):
                """Kayıtlı dublajlar: seçim düğmesi + videodaki kaydın işareti."""
                if not (ad or "").strip():
                    gr.Markdown("Önce bir proje aç.")
                    return
                kayitlar = diller.dublaj_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı dublaj yok: yukarıdan bir dublaj kaydet.")
                    return
                ekli = diller.ekli_dublaj_adi(ad)
                secenekler = [(f"{kayit['ad']} · "
                               + dublaj.dublaj_ozeti(
                                   kayit, kayit["ad"] == ekli), kayit["ad"])
                              for kayit in kayitlar]
                # Seçili değer listede yoksa (kayıt silinmiş, video eski
                # bir kayda bakıyor) hiçbiri işaretlenmez.
                adlar = [kayit["ad"] for kayit in kayitlar]
                deger = next((x for x in (secili, ekli) if x in adlar), None)
                kutu = gr.Radio(secenekler, value=deger,
                                label="Kayıtlı dublajlar", show_label=False,
                                interactive=True)
                kutu.change(lambda isim, proje=ad: diller.dublaj_sec(
                    proje, isim), [kutu], [b.pj_dublaj_secim], api_name=False)

            # Dublaj seviyesi seslendirme seviyesiyle **aynı** değerdir (videoda
            # tek konuşma sesi var); kaydırıcılar senkron durur.
            b.pj_ur_dublaj_seviye = gr.Slider(
                *sabitler.SES_SEVIYE_SINIR,
                value=sabitler.SES_VARSAYILAN_SEVIYE, step=5,
                label="Dublaj ses seviyesi (%)",
                info="100 = dublajın kendi seviyesi. Dublaj bu seviyeyle eklenir.")
            b.pj_ur_dublaj_ekle_btn = gr.Button("Seçili dublajı videoya ekle",
                                                variant="primary", size="sm")
            b.pj_ur_dublaj_durum = editor.durum_kutusu(PJ_UR_DUBLAJ_HAZIR, "Dublaj ekleme durumu")

    def _kur_muzik(self, b):
        """**Müzik** bölümü: müzik üret/yükle/kırp/kaydet, kayıtlı müzikleri videoya ekle."""
        # Müzik paneli **açık** başlar: müzik, dublaj ve altyazı
        # sonradan eklenen adımlardır, kullanıcı bu sekmeye zaten
        # onlar için gelir.
        with gr.Accordion("Müzik kaydet · yükle · kırp · seviye · karartma",
                          open=True):
            editor.yardim(
                "Birleştirilen video **sessizdir**; müzik burada **kaydedilir**, "
                "videoya aşağıdaki **Videoya ekle** panelinden eklenir. "
                "Dosyayı yükle → **kırp** (başlangıç–bitiş) → **ses seviyesini** "
                "ayarla → **karartmaları** seç → **Müziği kaydet**. Kaydetmek kırpmayı "
                "ve seviyeyi dosyanın içine işler: son hâli saklanır, videoya eklerken "
                "yeniden ayar gerekmez. Böylece **birden fazla** müzik kaydedebilirsin; "
                "hepsi aşağıdaki listede durur ve her projede kendi listesi olur.  \n"
                "**Karartma** ile müziğin başında ses 0'dan yükselir, sonunda yavaş "
                "yavaş 0'a iner; karartma dosyaya işlenmez, **videoya eklenirken** "
                "uygulanır ve müzik video sonunda kesiliyorsa tam kesildiği yere oturur. "
                "Varsayılan seviye **%10**: müzik anlatımın altında fon "
                "olarak kalır; öne çıkmasını istersen kaydırıcıyı yükselt.")
            # Yapay zekâ ile üretim: müzik doğrudan kaydedilmez, aşağıdaki
            # dosya kutusuna konur; kırpma/seviye/kaydetme aynı yoldan gider.
            with gr.Accordion("🎵 Yapay zekâ ile müzik üret · Lyria "
                              "(ücretsiz · telifsiz)", open=True):
                editor.yardim(
                    "Google **Lyria RealTime** enstrümantal müzik üretir "
                    "(Gemini anahtarıyla, şimdilik ücretsiz; seslendirme "
                    "kotasından yemez). Müziği Türkçe tarif et; **boş "
                    "bırakırsan** projenin anlatımından ve stilinden "
                    "çıkarılır. Tarifi projenin yapay zekâsı Lyria "
                    "istemlerine çevirir. Müzik gerçek zamanlı gelir: 60 sn "
                    "müzik yaklaşık 1 dakika sürer. Google hak iddia etmez; "
                    "çıktıda duyulmayan bir SynthID filigranı vardır.")
                b.pj_muzik_yz_tarif = gr.Textbox(
                    label="Müzik tarifi (opsiyonel)", lines=2,
                    placeholder="ör. eski Mısır esintisi, gizemli, ney ve "
                                "darbuka, yavaş · boşsa projeden çıkarılır")
                with gr.Row():
                    b.pj_muzik_yz_sure = gr.Slider(
                        *SURE_SINIRI, value=60, step=5, label="Süre (sn)")
                    b.pj_muzik_yz_bpm = gr.Slider(
                        0, BPM_SINIRI[1], value=0, step=1,
                        label="Tempo (BPM)",
                        info="0 = yapay zekâ tarife göre seçer.")
                b.pj_muzik_yz_btn = gr.Button("🎵 Müzik üret", variant="primary")
                b.pj_muzik_yz_durum = editor.durum_kutusu(PJ_MUZIK_YZ_HAZIR, "Müzik üretimi durumu")
            b.pj_muzik_dosya = gr.Audio(label="Müzik dosyası · yükle", type="filepath",
                                      sources=["upload"])
            b.pj_muzik_sure_not = gr.Markdown("")
            with gr.Row():
                # Sınırlar dosya yüklenince gerçek süreye çekilir; dosyanın
                # bittiği yerin ötesini kırpmak anlamsız olurdu.
                b.pj_muzik_bas = gr.Slider(0, sabitler.MUZIK_VARSAYILAN_SINIR,
                                         value=0, step=0.5,
                                         label="Kırpma · başlangıç (sn)")
                b.pj_muzik_bit = gr.Slider(0, sabitler.MUZIK_VARSAYILAN_SINIR,
                                         value=0, step=0.5,
                                         label="Kırpma · bitiş (sn)")
            with gr.Row():
                # Karartma **dosyaya işlenmez**: videoya eklenirken uygulanır, bu
                # yüzden müzik video sonunda kesiliyorsa karartma tam kesildiği yere
                # oturur. Süreleri değiştirmek için yeniden kaydetmek gerekmez.
                b.pj_muzik_giris_karartma = gr.Slider(
                    *sabitler.MUZIK_KARARTMA_SINIR, value=0, step=0.5,
                    label="Başlangıç karartma (sn)",
                    info="Müzik başlarken ses bu süre boyunca 0'dan yükselir.")
                b.pj_muzik_cikis_karartma = gr.Slider(
                    *sabitler.MUZIK_KARARTMA_SINIR, value=0, step=0.5,
                    label="Bitiş karartma (sn)",
                    info="Müzik biterken ses bu süre boyunca yavaş yavaş 0'a iner. "
                         "Video müziği kesiyorsa tam kesildiği yere uygulanır.")
            with gr.Row():
                b.pj_muzik_seviye = gr.Slider(
                    *sabitler.MUZIK_SEVIYE_SINIR,
                    value=sabitler.MUZIK_VARSAYILAN_SEVIYE, step=5,
                    label="Ses seviyesi (%)",
                    info="100 = dosyanın kendi seviyesi; anlatımın altında "
                         "fon olarak kalması için varsayılan %10'dur. "
                         "Müziğin duyulmasını daha çok istersen %20–40 dene.")
                b.pj_muzik_ad = gr.Textbox(
                    label="Müzik adı",
                    placeholder="ör. yaz-muzigi · aynı adla kaydedersen üzerine yazar",
                    info="Ad dosya adına çevrilir (boşluk `-` olur); proje "
                         "adlarında olduğu gibi.")
            b.pj_muzik_kaydet_btn = gr.Button("Müziği kaydet", variant="primary")
            b.pj_muzik_durum = editor.durum_kutusu(PJ_MUZIK_HAZIR, "Müzik durumu")
            gr.Markdown("**Kaydedilmiş müzikler** · videoya eklemek için aşağıdaki "
                        "**Videoya ekle** panelinde işaretle.")
            # Liste `gr.render` ile `parcalar.json`dan çizilir (bkz. sahne listesi):
            # `pj_muzik_liste` her kayıt/silmede değişen bir zaman damgasıdır
            # (liste tazeleme), `pj_muzik_secim` işaretleme sırasıdır (üretim
            # sayfasındaki panelde kullanılır).
            b.pj_muzik_liste = gr.State("")
            b.pj_muzik_secim = gr.State([])
            b.pj_muzik_sil_hedef = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_muzik_liste], queue=False)
            def _pj_muzik_satirlari(ad, _damga):
                """Kaydedilmiş müzikleri listeler (kaydet/sil; ekleme burada değil).

                Liste her çizimde `muzik/parcalar.json`dan **tazelenir**: başka
                bir proje açılırsa eski projenin müzikleri görünmez.
                """
                if not (ad or "").strip():
                    gr.Markdown("Müzik listesi için önce bir proje aç.")
                    return
                kayitlar = muzik.muzik_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kaydedilmiş müzik yok: yukarıdan yükle, kırp ve "
                                "**Müziği kaydet**'e bas.")
                    return
                for kayit in kayitlar:
                    with gr.Row(equal_height=True, elem_classes=["sf-saved-music-row"]):
                        gr.Markdown(f"**{kayit['ad']}** · "
                                    + muzik.muzik_ozeti(kayit), scale=5)
                        sil_btn = gr.Button("🗑 Sil", variant="stop", size="sm",
                                            scale=0, min_width=90)
                    # Silme müziği listeden ve diskten kaldırır; videoda
                    # duyuluyorsa karışımı da tazeler (bkz. `muzik_sil`).
                    sil_btn.click(
                        lambda proje, isim=kayit["ad"]: muzik.muzik_sil(
                            proje, isim),
                        [b.pj_ad], b.pj_muzik_ciktilari, api_name=False)

        with gr.Accordion("Videoya ekle · kayıtlı müzikler",
                          open=True) as b.pj_ur_muzik_box:
            editor.yardim(
                "Kutuları **işaretlediğin sırayla** müzikler videoya girer "
                "(1. bitince 2. başlar); sıra numarası satırın başında yazar. "
                "**Videoya ekle** müziği **anlatımın/dublajın altına** karıştırır. "
                "**Müziği kaldır** yalnızca müzik katmanını çıkarır, konuşma "
                "sesi videoda kalır.")

            @gr.render(inputs=[b.pj_ad, b.pj_muzik_liste, b.pj_muzik_secim], queue=False)
            def _pj_ur_muzik(ad, _damga, secili):
                """Kayıtlı müzikler: işaretleme kutuları ve sıra numaraları."""
                if not (ad or "").strip():
                    gr.Markdown("Önce bir proje aç.")
                    return
                kayitlar = muzik.muzik_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kaydedilmiş müzik yok: yukarıdan müzik kaydet.")
                    return
                sirali = [str(gecen) for gecen in (secili or [])]
                for kayit in kayitlar:
                    sira = (sirali.index(kayit["ad"]) + 1
                            if kayit["ad"] in sirali else 0)
                    with gr.Row(equal_height=True,
                                elem_classes=["sf-saved-music-row"]):
                        # `interactive=True` şart: Gradio 6 render içinde değeri dolu
                        # gelen kutuyu salt okunur çizer, işaret kaldırılamaz.
                        kutu = gr.Checkbox(value=bool(sira), label=kayit["ad"],
                                           interactive=True, scale=3)
                        gr.Markdown(muzik.muzik_ozeti(kayit, sira),
                                    scale=2)
                    # İşaretleme: sıra `pj_muzik_secim`de tutulur ve projeye
                    # yazılır (bkz. `pj_muzik_isaret`).
                    kutu.change(pj_muzik_isaret(ad, kayit["ad"]),
                                [kutu, b.pj_muzik_secim], [b.pj_muzik_secim],
                                api_name=False)

            b.pj_muzik_tekrarla = gr.Checkbox(
                value=False, label="Müzik kısa kalırsa video sonuna kadar tekrarla",
                info="İşaretliyse seçili müzikler (sırayla) video bitene kadar "
                     "baştan çalar; uzun müzik video sonunda kesilir.")
            b.pj_muzik_ducking = gr.Checkbox(
                value=sabitler.MUZIK_VARSAYILAN_DUCKING,
                label="Anlatım konuşurken müziği otomatik kıs (ducking)",
                info="İşaretliyse müzik, anlatım konuşurken kendiliğinden "
                     "kısılır ve konuşma susunca geri yükselir. Kapalıyken "
                     "seviyeler olduğu gibi karışır.")
            with gr.Row():
                b.pj_muzik_ekle_btn = gr.Button("Videoya ekle", variant="primary",
                                                size="sm")
                b.pj_muzik_kaldir_btn = gr.Button("Müziği kaldır", variant="stop",
                                                size="sm")
            b.pj_ur_muzik_durum = editor.durum_kutusu(PJ_UR_MUZIK_HAZIR, "Müzik ekleme durumu")

    def _kur_altyazi(self, b):
        """**Altyazı** bölümü: görünüm, dile göre kaydet, kayıtlı altyazıyı videoya göm."""
        with gr.Accordion("Görünüm ve üretim · yazı tipi, renk, seviye", open=False):
            b.pj_altyazi = gr.Checkbox(value=True, label="Altyazı üret (SRT + VTT)")
            b.pj_altyazi_preset = gr.Dropdown(
                SUB_PRESETLER, value=PJ_VARSAYILAN.get("altyazi") or "dikey",
                label="Hazır ayar",
                info="Çıktı biçimi değişince biçime uygun öneriye geçer.")
            # Gömme görünümü: altyazı videoya eklenirken kullanılır. Liste dışı
            # bir font yazılabilir; libass bulamazsa Arial'e düşer.
            with gr.Row():
                b.pj_altyazi_font = gr.Dropdown(
                    gorunum.ALTYAZI_FONTLARI, value=gorunum.ALTYAZI_FONT,
                    label="Yazı tipi · videoya gömülürken", allow_custom_value=True,
                    scale=2)
                b.pj_altyazi_renk = gr.ColorPicker(value=gorunum.ALTYAZI_RENK,
                                                 label="Yazı rengi", scale=1)
                b.pj_altyazi_kalin = gr.Checkbox(value=False, label="Kalın", scale=1)
            # Seviye: yazının alt kenardan yüksekliği (tuval yüksekliğinin yüzdesi).
            # TikTok / Reels / Shorts arayüzünün açıklama satırı videonun alt
            # bölgesini kapladığı için hazır ayarlar yazıyı biraz yukarı taşır;
            # burada kendi videona göre ince ayar yapılır. Önizleme konumu aynen
            # gösterir, videoya da bu değer gömülür.
            b.pj_altyazi_seviye = gr.Slider(
                *gorunum.ALTYAZI_SEVIYE_SINIR,
                value=gorunum.ALTYAZI_SEVIYE, step=1,
                label="Seviye · yazının alttan yüksekliği (%)",
                info="Yazı arayüz çubuğunun (açıklama · düğmeler) arkasında kalıyorsa "
                     "yükselt; değer hazır ayarla birlikte gelir.")
            # Zemin yalnızca önizlemeyi etkiler: yazıyı karanlık, parlak ve
            # renkli bir sahnede ayrı ayrı görüp okunurluğunu tartabilirsin.
            # Gömülen videoya karışmadığı için proje ayarlarına yazılmaz.
            b.pj_altyazi_zemin = gr.Dropdown(
                gorunum.onizleme_zemin_secenekleri(),
                value=gorunum.ONIZLEME_ZEMIN, label="Önizleme zemini",
                info="Yalnızca önizlemeyi etkiler; videoya gömülmez.")
            # Önizleme: ayarlar değişince tek karelik gerçek bir libass çıktısı
            # üretilir; yazı tipi, renk, kalınlık ve konum burada görünür.
            b.pj_altyazi_onizleme_resim = gr.Image(
                label="Önizleme · videoya gömülecek hâlin küçüğü", type="filepath",
                interactive=False, height=280)
            b.pj_altyazi_onizleme_not = gr.Markdown("")
            # Panelin en altında: seçili görünümle videodaki altyazıyı baştan
            # kurar. **Altyazıyı videoya ekle** zaten eklenmiş altyazıyı
            # yenilemez, bu yüzden görünüm değişince kullanılacak düğme budur.
            b.pj_altyazi_yeniden_btn = gr.Button("Video altyazısını tekrar oluştur",
                                               variant="primary")
            editor.yardim(
                "Videodaki altyazıyı **yukarıdaki ayarlarla baştan** oluşturur: eski "
                "gömme kaldırılır (altyazı üst üste binmez), varsa seslendirme ve "
                "ekli dil geri uygulanır, altyazı yeniden gömülür. **Altyazı üret** "
                "kapalıysa yenisi gömülmez, yalnızca eski altyazı videodan kaldırılır.\n\n"
                "Altyazı dosyası hiç yoksa (`ses/seslendirme.srt`), altyazı **anlatım "
                "metninden sıfırdan üretilir**: ses dosyası varsa zamanlar **gerçek "
                "sesle hizalanır** (ses dinlenir), yoksa metinden tahmin edilir. Ses "
                "**yeniden üretilmez**.")

        # Altyazı paneli: altyazı artık dublajın kutucuğu değil, kendi
        # başına kaydedilen bir parçadır (her dil için ayrı kayıt).
        with gr.Accordion("Altyazı kaydet · dile göre ayrı altyazı",
                          open=True):
            editor.yardim(
                "Altyazı **dile göre ayrı kaydedilir** ve videoya aşağıdaki **Videoya "
                "göm** panelinden gömülür. Dili seç → **Altyazıyı "
                "kaydet**. Kaynak sırayla aranır: o dilin dublajıyla birlikte üretilmiş "
                "altyazı → projenin kendi altyazısı (anlatım dili) → ikisi de yoksa "
                "altyazı **metinden** yazılır (kelime zamanları uzunluğa göre tahmin "
                "edilir; hiçbir servise istek gitmez, ses yeniden üretilmez).  \n"
                "Görünüm (yazı tipi, renk, seviye) yukarıdaki **Görünüm ve üretim** "
                "panelinden gelir ve gömme anında uygulanır.")
            with gr.Accordion("Altyazıların saklandığı yer", open=False):
                gr.Markdown(
                    f"Kayıtlı altyazılar projenin `{sabitler.ALTYAZI_KLASORU}/` "
                    f"klasöründe (`<ad>.srt` ve `.vtt`), listesi "
                    f"`{sabitler.ALTYAZI_LISTE_ADI}` dosyasında saklanır.")
            b.pj_alt_dil = gr.Dropdown(
                [(ad, kod) for kod, ad in LANGUAGES.items() if kod != "auto"],
                value="en", label="Altyazı dili")
            b.pj_alt_ad = gr.Textbox(
                label="Altyazı adı (opsiyonel)",
                placeholder="ör. en-kisa · boş bırakırsan dil kodu kullanılır",
                info="Dublajla aynı adı verirsen o dublajın altyazısı kaydedilir.")
            b.pj_alt_kaydet_btn = gr.Button("Altyazıyı kaydet", variant="primary")
            b.pj_alt_durum = editor.durum_kutusu(PJ_ALTYAZI_HAZIR, "Altyazı durumu")
            with gr.Accordion("Altyazı dosyaları · srt · vtt",
                              open=False) as b.pj_alt_dosya_box:
                b.pj_alt_dosyalar = gr.File(label="Altyazı dosyaları (srt · vtt)",
                                          file_count="multiple")
            gr.Markdown("**Kaydedilmiş altyazılar** · videoya gömmek için aşağıdaki "
                        "**Videoya göm** panelinden seç.")
            b.pj_altyazi_liste = gr.State("")
            b.pj_altyazi_secim = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_altyazi_liste], queue=False)
            def _pj_altyazi_satirlari(ad, _damga):
                """Kaydedilmiş altyazıları listeler (kaydet/sil; gömme burada değil)."""
                if not (ad or "").strip():
                    gr.Markdown("Altyazı listesi için önce bir proje aç.")
                    return
                kayitlar = diller.altyazi_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı altyazı yok: dil seç ve **Altyazıyı "
                                "kaydet**'e bas.")
                    return
                for kayit in kayitlar:
                    with gr.Row(equal_height=True, elem_classes=["sf-saved-music-row"]):
                        gr.Markdown(f"**{kayit['ad']}** · "
                                    + altyazilar.altyazi_kayit_ozeti(kayit),
                                    scale=5)
                        sil_btn = gr.Button("🗑 Sil", variant="stop", size="sm",
                                            scale=0, min_width=90)
                    sil_btn.click(
                        lambda proje, isim=kayit["ad"]: diller.altyazi_sil(
                            proje, isim),
                        [b.pj_ad], b.pj_altyazi_ciktilari, api_name=False)

        with gr.Accordion("Videoya göm · kayıtlı altyazı",
                          open=True) as b.pj_ur_altyazi_box:
            editor.yardim(
                "Bir altyazı seç → **Seçili altyazıyı videoya göm**. Altyazı "
                "görüntünün içine yazılır (hard sub); ses akışı korunur. Videoda "
                "zaten gömülü bir altyazı varsa önce o kaldırılır (video ham "
                "videodan kurulur, ekli dublaj ve müzik geri uygulanır), sonra "
                "yenisi gömülür — yazılar üst üste binmez.")

            @gr.render(inputs=[b.pj_ad, b.pj_altyazi_liste, b.pj_altyazi_secim], queue=False)
            def _pj_ur_altyazi(ad, _damga, secili):
                """Kayıtlı altyazılar: seçim düğmesi + videodaki kaydın işareti."""
                if not (ad or "").strip():
                    gr.Markdown("Önce bir proje aç.")
                    return
                kayitlar = diller.altyazi_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı altyazı yok: yukarıdan dile göre altyazı kaydet.")
                    return
                ekli = diller.ekli_altyazi_adi(ad)
                secenekler = [(f"{kayit['ad']} · "
                               + altyazilar.altyazi_kayit_ozeti(
                                   kayit, kayit["ad"] == ekli), kayit["ad"])
                              for kayit in kayitlar]
                adlar = [kayit["ad"] for kayit in kayitlar]
                deger = next((x for x in (secili, ekli) if x in adlar), None)
                kutu = gr.Radio(secenekler, value=deger,
                                label="Kayıtlı altyazılar", show_label=False,
                                interactive=True)
                kutu.change(lambda isim, proje=ad: diller.altyazi_sec(
                    proje, isim), [kutu], [b.pj_altyazi_secim], api_name=False)

            b.pj_ur_altyazi_ekle_btn = gr.Button("Seçili altyazıyı videoya göm",
                                                 variant="primary", size="sm")
            b.pj_ur_altyazi_durum = editor.durum_kutusu(PJ_UR_ALTYAZI_HAZIR, "Altyazı gömme durumu")

    def _kur_efekt(self, b):
        """**Efekt** bölümü: ses efektlerini hazırla ve düzenle, kayıtlı efektleri videoya göm."""
        with gr.Accordion("Ses efektleri · yapay zekâ ya da elle · "
                          "Freesound (CC0)", open=True):
            editor.yardim(
                "Sesler **Freesound**'dan yalnızca **CC0** lisanslı kayıtlardan "
                "seçilir: atıf gerekmez, ticari kullanım serbesttir. GPU ya da "
                "video kotası harcanmaz.  \n"
                "**Yapay zekâ hazırlasın**: hangi sahnede ne sesi olacağına "
                "yapay zekâ karar verir (anlatım ve sahnenin görüntüsü okunur).  \n"
                "**Manuel hazırla**: videosu üretilmiş her sahne listelenir; "
                "istediğin sesi yaz (ör. *yemek yeme sesi*). Yapay zekâ "
                "**yalnızca** yazdığın sesleri bulur, kendiliğinden ses eklemez; "
                "boş bıraktığın sahne efektsiz kalır.  \n"
                "Sesleri yapay zekâ **Sahne prompt'larının yapay zekâsı** "
                "seçimiyle (en iyi model) seçer; Freesound anahtarı **API "
                "hesapları** sekmesindedir. Hazırlanan efektler bir **kayıt** "
                "olur; videoya aşağıdaki **Videoya göm** panelinden gömülür.")
            with gr.Row():
                b.pj_efekt_yz_btn = gr.Button("🤖 Yapay zekâ hazırlasın",
                                              variant="primary")
                b.pj_efekt_manuel_btn = gr.Button(
                    "✍️ Ses efektlerini manuel hazırla")
            b.pj_efekt_ad = gr.Textbox(
                label="Efekt kaydı adı (opsiyonel)",
                placeholder="ör. piramit-efektleri · boşsa tarihle adlandırılır",
                info="Aynı adla hazırlamak kaydı günceller.")

            # Manuel sahne listesi: **Manuel hazırla**ya basınca kutu açılır
            # ve liste o anki sahnelerle çizilir. Liste doğrudan düğmenin
            # tıklamasıyla tetiklenir: bir `gr.State` değişimine bağlı
            # çizim tarayıcıda tetiklenmiyordu (liste hiç gelmiyordu).
            with gr.Column(visible=False) as b.pj_efekt_manuel_kutu:
                @gr.render(inputs=[b.pj_ad],
                           triggers=[b.pj_efekt_manuel_btn.click,
                                     b.pj_ad.change],
                           queue=False)
                def _pj_efekt_manuel(ad):
                    """Manuel mod: videosu olan her sahne için bir istek kutusu."""
                    sahneler = efekt_ekleme.efekt_sahne_listesi(ad)
                    if not sahneler:
                        gr.Markdown("Önce bir proje aç; manuel efekt için "
                                    "videosu üretilmiş sahne gerekir.")
                        return
                    gr.Markdown(f"**{len(sahneler)} sahne** · her sahneye "
                                "istediğin sesi yaz; boş kalan sahne "
                                "efektsiz kalır.")
                    kutular = []
                    for sahne in sahneler:
                        bitis = sahne["bas"] + sahne["sure"]
                        kutular.append(gr.Textbox(
                            label=(f"Sahne {sahne['index']} · "
                                   f"{sahne['bas']:.1f}–{bitis:.1f} sn · "
                                   + (sahne["metin"][:110] or "—")),
                            placeholder="ör. yemek yeme sesi, kumda ayak sesi",
                            lines=1))
                    hazirla_btn = gr.Button("Manuel efektleri hazırla",
                                            variant="primary")
                    hazirla_btn.click(
                        pj_efekt_manuel_hazirla([s["index"] for s in sahneler]),
                        [b.pj_ad, b.pj_efekt_ad, b.pj_ai, *kutular],
                        b.pj_efekt_ciktilari, concurrency_limit=1,
                        api_name=False)

            b.pj_efekt_durum = editor.durum_kutusu(PJ_EFEKT_HAZIR, "Ses efekti durumu")
            b.pj_efekt_onizleme = gr.Audio(label="Seçili efekt izi · dinle",
                                           type="filepath",
                                           interactive=False)
            gr.Markdown("**Kaydedilmiş ses efektleri** · videoya gömmek için aşağıdaki "
                        "**Videoya göm** panelinden seç.")
            b.pj_efekt_liste = gr.State("")
            b.pj_efekt_secim = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_efekt_liste], queue=False)
            def _pj_efekt_satirlari(ad, _damga):
                """Kayıtlı efektler (sil; gömme burada değil)."""
                if not (ad or "").strip():
                    gr.Markdown("Efekt listesi için önce bir proje aç.")
                    return
                kayitlar = efekt_ekleme.efekt_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı ses efekti yok: yukarıdaki "
                                "düğmelerden biriyle hazırla.")
                    return
                ekli = efekt_ekleme.ekli_efekt_adi(ad)
                for kayit in kayitlar:
                    with gr.Row(equal_height=True,
                                elem_classes=["sf-saved-music-row"]):
                        gr.Markdown(f"**{kayit['ad']}** · " + efektler.efekt_ozeti(
                            kayit, kayit["ad"] == ekli), scale=5)
                        sil_btn = gr.Button("🗑 Sil", variant="stop", size="sm",
                                            scale=0, min_width=90)
                    sil_btn.click(
                        lambda proje, isim=kayit["ad"]: efekt_ekleme.efekt_sil(
                            proje, isim),
                        [b.pj_ad], b.pj_efekt_ciktilari, api_name=False)

        # ── Sesleri düzenle: sahne sırasıyla, her sesin karşısında arama ──
        # Solda sahnenin sesi (küçük çalar), sağda arama: **Bul** en uygun
        # sesi önerir, **Tekrar oluştur** sıradakini getirir, **Onayla** sesi
        # değiştirir. Onay izi kayıttan yeniden kurar; kayıt videodaysa
        # videonun sesi de tazelenir (bkz. `efekt_duzenleme.katman_koy`).
        with gr.Accordion("✏️ Sesleri düzenle", open=False):
            with gr.Row(equal_height=True):
                b.pj_efd_kayit = gr.Dropdown([], label="Efekt kaydı", scale=3)
                b.pj_efd_durum = gr.Textbox(label="Durum", lines=1,
                                            interactive=False, scale=5)
            b.pj_efd_damga = gr.State("")

            @gr.render(inputs=[b.pj_ad, b.pj_efd_kayit, b.pj_efd_damga],
                       queue=False)
            def _pj_efd_sahneler(ad, kayit, _damga):
                """Sahneler 1, 2, 3… sırasıyla; her ses bir satır."""
                if not kayit:
                    gr.Markdown("Düzenlemek için yukarıdan bir efekt kaydı seç.")
                    return
                sahneler, mesaj = efekt_duzenleme.duzenleme_sahneleri(ad, kayit)
                if not sahneler:
                    gr.Markdown(mesaj)
                    return
                for sahne in sorted(sahneler, key=lambda s: s["index"]):
                    # Sesi olmayan sahne tek boş satırla gelir: oradan eklenir.
                    for katman in sahne["katmanlar"] or [None]:
                        with gr.Row(equal_height=True,
                                    elem_classes=["sf-efd-satir"]):
                            with gr.Column(scale=2, min_width=220):
                                baslik = (f"**Sahne {sahne['index']}**"
                                          f" · {sahne['bas']:.1f} sn")
                                if katman:
                                    baslik += (" · " + (katman.get("etiket")
                                                        or katman["ad"])
                                               + f" ({katman.get('tur')})")
                                gr.Markdown(baslik)
                                gr.HTML(pj_efd_oynatici(
                                    katman["dosya"] if katman else None))
                            with gr.Column(scale=3, min_width=260):
                                with gr.Row(equal_height=True):
                                    sorgu = gr.Textbox(
                                        show_label=False, scale=4,
                                        placeholder=(
                                            "yerine ne sesi olsun? istediğini "
                                            "anlat: ör. kumda yavaş ayak sesi"
                                            if katman else
                                            "bu sahneye ne sesi eklensin? "
                                            "ör. uzakta rüzgâr uğultusu"))
                                    bul = gr.Button("🤖 Bul", size="sm",
                                                    scale=1, min_width=70)
                                oneri = gr.HTML("")
                                oneri_durum = gr.State({})
                                with gr.Row():
                                    onayla = gr.Button("✅ Onayla", size="sm",
                                                       variant="primary",
                                                       visible=False)
                                    tekrar = gr.Button("🔄 Tekrar oluştur",
                                                       size="sm",
                                                       visible=False)
                        cikis = [oneri_durum, oneri, onayla, tekrar]
                        tur = (katman or {}).get("tur") or "eylem"
                        # Arama yapay zekâlıdır: servis **Sahne
                        # prompt'larının yapay zekâsı** seçimidir.
                        for olay in (bul.click, sorgu.submit):
                            olay(lambda proje, metin, servis,
                                 i=sahne["index"], t=tur:
                                 pj_efd_bul(proje, metin, i, t, servis),
                                 [b.pj_ad, sorgu, b.pj_ai], cikis,
                                 concurrency_limit=2, api_name=False)
                        tekrar.click(pj_efd_tekrar, [oneri_durum], cikis,
                                     api_name=False)
                        # Önce satırda "onaylanıyor" yazısı çıkar ve
                        # düğmeler kilitlenir (indirme + iz kurma
                        # birkaç saniye sürer); sonra asıl onay çalışır,
                        # liste yenilenince satır yeni sesle gelir.
                        onayla.click(
                            pj_efd_onaylaniyor, None,
                            [oneri, onayla, tekrar, b.pj_efd_durum],
                            queue=False, api_name=False
                        ).then(
                            pj_efd_onayla(sahne["index"],
                                          katman["sira"] if katman else 0,
                                          katman),
                            [b.pj_ad, b.pj_efd_kayit, oneri_durum],
                            b.pj_efd_ciktilari, concurrency_limit=1,
                            api_name=False)

        with gr.Accordion("Videoya göm · kayıtlı ses efektleri",
                          open=True) as b.pj_ur_efekt_box:
            editor.yardim(
                "Bir efekt kaydı seç → **Seçili ses efektlerini videoya göm**. "
                "Efekt anlatımın ve müziğin **altına karışır**; görüntü ve "
                "gömülü altyazı korunur. Dublaj ya da altyazı videoyu yeniden "
                "kurduğunda efekt kendiliğinden geri uygulanır. **Seviyeyi** "
                "değiştirip yeniden gömmek için efektleri yeniden hazırlamak "
                "gerekmez.")

            @gr.render(inputs=[b.pj_ad, b.pj_efekt_liste, b.pj_efekt_secim],
                       queue=False)
            def _pj_ur_efekt(ad, _damga, secili):
                """Kayıtlı efektler: seçim düğmesi + videodaki kaydın işareti."""
                if not (ad or "").strip():
                    gr.Markdown("Önce bir proje aç.")
                    return
                kayitlar = efekt_ekleme.efekt_listesi(ad)
                if not kayitlar:
                    gr.Markdown("Kayıtlı ses efekti yok: yukarıdan efekt hazırla.")
                    return
                ekli = efekt_ekleme.ekli_efekt_adi(ad)
                secenekler = [(f"{kayit['ad']} · " + efektler.efekt_ozeti(
                    kayit, kayit["ad"] == ekli), kayit["ad"])
                    for kayit in kayitlar]
                adlar = [kayit["ad"] for kayit in kayitlar]
                deger = next((x for x in (secili, ekli,
                                          efekt_ekleme.efekt_secimi(ad))
                              if x in adlar), None)
                kutu = gr.Radio(secenekler, value=deger,
                                label="Kayıtlı ses efektleri", show_label=False,
                                interactive=True)
                kutu.change(lambda isim, proje=ad: efekt_ekleme.efekt_sec(
                    proje, isim), [kutu], [b.pj_efekt_secim], api_name=False)

            b.pj_efekt_seviye = gr.Slider(
                *efektler.EFEKT_SEVIYE_SINIR,
                value=efektler.EFEKT_VARSAYILAN_SEVIYE, step=10,
                label="Efekt seviyesi (%)",
                info="100 = hazırlanan izin kendi seviyesi (anlatımın "
                     "altında). Daha belirgin istersen %150–200 dene.")
            with gr.Row():
                b.pj_ur_efekt_ekle_btn = gr.Button(
                    "Seçili ses efektlerini videoya göm", variant="primary",
                    size="sm")
                b.pj_ur_efekt_kaldir_btn = gr.Button(
                    "Ses efektlerini kaldır", variant="stop", size="sm")
            b.pj_ur_efekt_durum = editor.durum_kutusu(PJ_UR_EFEKT_HAZIR, "Ses efekti gömme durumu")

    def _kur_onizleme(self, b):
        """Orta alan: durum, katman rozetleri, Video/Ses anahtarı, sonuç videosu ve video işlemleri."""
        # Durum, önizlemenin hemen üstünde: akışın son mesajı videoyla birlikte okunur.
        # 13 satır: çoklu üretimde başlık + on grup + özet aynı anda görünür.
        b.pj_durum = editor.durum_kutusu(
            "Hazır. Proje adını ve anlatım metnini yaz, ayarları seç, sonra "
            "**Projeye başlat**'a bas.",
            "Durum", elem_classes=["sf-current-status", "sf-stage-status"])
        with gr.Row(equal_height=True, elem_classes=["sf-stage-bar"]):
            # Videoda hangi katmanların olduğu: video her değiştiğinde tazelenir.
            b.pj_katmanlar = gr.HTML(katman_rozeti_html(None),
                                     elem_classes=["sf-katman-alani"])
            # **Video | Ses**: Ses seçiliyken seslendirme/dublaj/müzik düğmeleri
            # videoya dokunmaz, yalnızca `youtube/<dil>/ses.mp3` kurar (YouTube'un
            # çok dilli ses izleri için; bkz. `ses_ciktisi`).
            b.pj_cikti_modu = gr.Radio(CIKTI_MODLARI, value=CIKTI_VIDEO,
                                       show_label=False, container=False,
                                       scale=0, min_width=0,
                                       elem_classes=["sf-uretim-modu", "sf-cikti-modu"])
            b.pj_tam_ekran_btn = gr.Button("⛶ Tam ekran", size="sm", scale=0,
                                           min_width=120,
                                           elem_classes=["sf-tam-ekran"])
        # Sabit çerçeve: yükseklik videodan bağımsızdır, video içine sığdırılır
        # (dikey video yanlarda, yatay video üstte/altta koyu boşluk bırakır).
        # `interactive=False` şart: katman rozeti videoyu girdi olarak okuduğu için
        # Gradio kutuyu yükleme alanına çevirirdi; burası yalnızca önizlemedir.
        # Araç çubuğunda indirmenin yanında ♪ düğmesi: videonun yalnızca sesi
        # (anlatım/dublaj + müzik + efekt) MP3 olarak iner (bkz. `pj_sesi_indir`).
        b.pj_ses_indir_btn = gr.Button("", icon=str(ASSETS / "ses-indir.svg"),
                                       size="sm", elem_id="sf-ses-indir")
        b.pj_video = gr.Video(label="Sonuç videosu · proje.mp4", show_label=False,
                            interactive=False, height="clamp(320px, 60vh, 720px)",
                            buttons=["download", b.pj_ses_indir_btn],
                            elem_id="sf-onizleme", elem_classes=["sf-video-output"])
        # Ses modunun önizlemesi: video kutusunun yerine görünür, indirilebilir.
        b.pj_ses_cikti = gr.Audio(label="Ses dosyası · youtube/<dil>/ses.mp3",
                                  type="filepath", interactive=False, visible=False,
                                  buttons=["download"], elem_classes=["sf-ses-cikti"])
        # Hazırlanan MP3'ün taşıyıcısı: ekranda görünmez, indirmeyi JS başlatır.
        b.pj_ses_dosya = gr.File(show_label=False, interactive=False,
                                 elem_classes=["sf-ses-indir-dosya"])
        # Video oluştuktan sonra aranan işlemler videonun hemen altında durur:
        # **Sesi videoya ekle** ve **Altyazıyı videoya ekle** isteğe bağlıdır
        # (basılmazsa proje.mp4 sessiz ve altyazısız kalır), **Ham videoya geri
        # dön** ise videoyu eklenmiş ses ve altyazıdan arındırıp ilk hâline
        # döndürür (bkz. `diller.ham_videoya_geri_don`).
        with gr.Row(equal_height=True, elem_classes=["sf-video-actions"]):
            # Yalnızca **Ses** modunda görünür: güncel ses dosyasını indirir.
            b.pj_ses_indir_dugmesi = gr.Button("⬇ Sesi indir", variant="primary",
                                               size="sm", visible=False)
            b.pj_ses_ekle_btn = gr.Button("Sesi videoya ekle", size="sm")
            b.pj_altyazi_ekle_btn = gr.Button("Altyazıyı videoya ekle", size="sm")
            b.pj_cok_geri_btn = gr.Button("↺ Ham videoya geri dön", variant="stop",
                                          size="sm")
        # Ham video (`proje-ham.mp4`) ayrı bir panelde gösterilmez: arka
        # planda kurulur, dublaj/altyazı/müzik onun üzerine eklenir. Ekranda
        # tek video vardır, o da yukarıdaki sonuç videosudur.
        gr.Markdown("Ses ve altyazı, ilgili düğmelerle videoya ayrıca eklenir. "
                    "Kaydettiğin dublaj, müzik, altyazı ve ses efektleri "
                    "sağdaki panellerde.",
                    elem_classes=["sf-output-note"])

    def _kur_denetci(self, b):
        """Sağ panel: alttaki şeritten seçilen sahnenin karesi, bilgisi ve işlemleri."""
        gr.HTML('<div class="sf-denetci-baslik"><b>Sahne</b>'
                '<span>Şeritten bir sahne seç</span></div>')
        # Seçili sahnenin numarası; şeritteki tıklama gizli `pj_sahne_tik` alanına yazılır.
        b.pj_secili_sahne = gr.State(None)
        b.pj_ins_gorsel = gr.Image(show_label=False, type="filepath", interactive=False,
                                   height=210, elem_classes=["sf-denetci-kare"])
        b.pj_ins_bilgi = gr.Markdown(editor.sahne_detayi("", None)[1],
                                     elem_classes=["sf-denetci-bilgi"])
        with gr.Row(elem_classes=["sf-denetci-dugmeler"]):
            # Kare: kare silinir, aynı prompt'la yenisi üretilir, onay sıfırlanır
            # (eskiden "Görsel sahnelerini düzenle" ızgarasındaki düğme; o da duruyor).
            b.pj_ins_kare_btn = gr.Button("🗑 Kareyi kaldır ve yenile", size="sm",
                                          variant="stop")
            # Klip: yalnızca adımın videosu silinir, aynı kareden yenisi üretilir.
            b.pj_ins_klip_btn = gr.Button("↻ Klibi yeniden üret", size="sm")
        with gr.Group(visible=False, elem_classes=["sf-confirmation"]) as b.pj_ins_klip_onay:
            gr.Markdown("**Bu sahnenin klibi silinsin mi?** Silme geri alınamaz; kare ve "
                        "prompt'lar korunur, aynı kareden yeni video üretilir ve video "
                        "yeniden birleştirilir.")
            with gr.Row():
                b.pj_ins_klip_evet = gr.Button("Sil ve yeniden üret", variant="stop", size="sm")
                b.pj_ins_klip_vazgec = gr.Button("Vazgeç", size="sm")

        with gr.Accordion("Sahne prompt'u · düzenle ve yeniden üret", open=True) as b.pj_prompt_box:
            editor.yardim(
                "Bir sahne seçip görsel promptunu veya negatif promptunu düzenle. "
                "**Promptu onayla ve görseli yeniden üret** dediğinde yalnızca seçilen "
                "sahnenin eski karesi ve klibi kaldırılır; yeni prompt kaydedilir, görsel "
                "için hareket ve kontrol listesi yenilenir. Yeni kare üretilir; "
                "görselleri onayladığında bu kareden yeni video üretilir.")
            b.pj_prompt_incele_btn = gr.Button("Sahne promptlarını göster", variant="primary")
            with gr.Group(visible=False) as b.pj_prompt_editor:
                b.pj_prompt_sec = gr.Dropdown([], label="Düzenlenecek sahne",
                                              allow_custom_value=False)
                b.pj_prompt_not = gr.Markdown("")
                b.pj_prompt_gorsel = gr.Textbox(label="Görsel promptu", lines=8,
                                                  max_lines=16)
                b.pj_prompt_negatif = gr.Textbox(label="Negatif prompt", lines=3,
                                                   max_lines=8)
                b.pj_prompt_onay = gr.Button(
                    "Promptu onayla ve görseli yeniden üret", variant="primary")

    def _kur_zaman_cizelgesi(self, b):
        """Alt şerit: sahneler (süreyle orantılı, durum renkli) ve ses/altyazı izleri."""
        with gr.Column(elem_classes=["sf-zaman"]):
            b.pj_serit = gr.HTML(editor.sahne_seridi_html("", None),
                                 elem_classes=["sf-serit-kap"])
            b.pj_izler = gr.HTML(editor.izler_html(""), elem_classes=["sf-izler-kap"])
            # Şeritteki tıklamanın taşıyıcısı: görünmez, değeri JS yazar (bkz. studioflow.js).
            b.pj_sahne_tik = gr.Textbox(elem_id="sf-sahne-tik", show_label=False,
                                        container=False, elem_classes=["sf-gizli"])

    def _kur_ayarlar(self, b):
        """**Ayarlar** bölümü: çıktı biçimi, görsel ve video ayarları, ayar kaydı ve proje dosyaları."""
        # Çıktı biçimi: görsel oranını, altyazı önerisini ve birleştirme tuvalini
        # birlikte belirler (bkz. bicimler.CIKTI_BICIMLERI).
        with gr.Accordion("Çıktı biçimi · platform ve tuval ölçüsü", open=True):
            b.pj_on_ayar = gr.Dropdown(
                on_ayarlar.proje_on_ayar_secenekleri(),
                value=PJ_VARSAYILAN_ANAHTAR,
                # Filtre kapalı: açık liste kutudaki yazıya ("— elle ayarla —") göre
                # süzülüp yalnızca o seçeneği gösteriyordu; diğer kurulumlar görünmüyordu.
                filterable=False,
                label="Ön ayar · tek seçimle hazır kurulum",
                info="Görsel modelini ve adımını, video adımını, adım süresini, "
                     "hedef tuvali ve altyazı önerisini birlikte ayarlar.")
            # Ön ayarın notu açılışta görünür: seçili kurulumun ne getirdiği
            # hemen altında yazar.
            b.pj_on_ayar_not = gr.Markdown(PJ_VARSAYILAN_NOT)
            b.pj_bicim = gr.Dropdown(
                [(bilgi["ad"], anahtar)
                 for anahtar, bilgi in bicimler.CIKTI_BICIMLERI.items()],
                value=PJ_VARSAYILAN.get("bicim")
                or bicimler.VARSAYILAN_BICIM, label="Hedef biçim")
        with gr.Accordion("Görsel ayarları", open=False):
            b.pj_gorsel_model = gr.Dropdown(
                choices=gorsel_cloudflare.cf_model_choices(),
                value=PJ_VARSAYILAN_GORSEL.get("model")
                or gorsel_cloudflare.VARSAYILAN_MODEL, label="Model")
            with gr.Row():
                # Oranı çıktı biçimi belirler (varsayılan: Shorts dikey 9:16).
                b.pj_genislik = gr.Slider(256, 2048,
                                        value=PJ_VARSAYILAN_GORSEL.get("width") or 768,
                                        step=64, label="Genişlik (px)")
                b.pj_yukseklik = gr.Slider(256, 2048,
                                         value=PJ_VARSAYILAN_GORSEL.get("height") or 1344,
                                         step=64, label="Yükseklik (px)")
            with gr.Row():
                b.pj_adim = gr.Slider(
                    1, 20, value=PJ_VARSAYILAN_GORSEL.get("steps") or 4,
                    step=1, label="Adım (steps)")
                b.pj_guidance = gr.Slider(
                    1, 15, value=PJ_VARSAYILAN_GORSEL.get("guidance") or 7.5,
                    step=0.5, label="Guidance (CFG)")
        with gr.Accordion("Video ayarları", open=False):
            with gr.Row():
                # Space 1–10 adım ve 0,5–10 sn kabul eder (kendi API imzası).
                b.pj_video_adim = gr.Slider(
                    video_huggingface.ADIM_ALT, video_huggingface.ADIM_UST,
                    value=PJ_VARSAYILAN.get("video_adim")
                    or video_huggingface.ADIM_VARSAYILAN, step=1,
                                          label="Video adımı",
                                          info="4–8 adım önerilir.")
        self._kur_ayar_kaydi(b)
        with gr.Accordion("proje.txt · projenin tek kaydı", open=False):
            b.pj_ilerleme = gr.Textbox(label="proje.txt", show_label=False, lines=20,
                                     interactive=False)
        with gr.Accordion("Proje dosyaları", open=False) as b.pj_dosya_box:
            # `height` sabit yükseklik verir: panel büyümez, dosyalar içinde kayar.
            b.pj_dosyalar = gr.File(label="Proje dosyaları (kaydırarak gez)",
                                  file_count="multiple",
                                  height=DOSYA_PANEL_YUKSEKLIK)
        with gr.Accordion("Parça görselleri", open=False) as b.pj_gorsel_box:
            b.pj_gorseller = gr.Gallery(label="Parça görselleri", columns=3, height=260)
        # Dosya ve görsel listeleri önce bu durumlara yazılır; görünür bileşenler
        # yalnızca panel açıkken doldurulur. Gradio her dosyayı göndermeden önce
        # içeriğini okuyup önbelleğe işler (303 dosya + 191 görsel ≈ 4,3 sn); kapalı
        # paneller için bu bedel proje açılışında ve üretimin her güncellemesinde
        # boşuna ödeniyordu.
        b.pj_dosya_listesi = gr.State([])
        b.pj_gorsel_listesi = gr.State([])
        b.pj_dosya_acik = gr.State(False)
        b.pj_gorsel_acik = gr.State(False)

    def _karakter_paneli(self, b):
        """👥 Karakterler: düğmeye basınca açılan kadro paneli.

        Tek bir düzenleme kartı vardır: ad, tarif ve referans görsel. Görsel ya tariften
        üretilir ya da kullanıcı kendi görselini bırakır; **Karakteri kaydet** karakteri
        kadroya yazar ve kartı boşaltır. Kaydedilenler kartın altında listelenir: ada
        tıklayınca karakter karta gelir (düzenlenir), 🗑 ile kadrodan çıkar. Kadro
        `pj_kadro` State'inde durur; bir karede en fazla 4 karakter görünür ama kadro
        `kadro.AZAMI_KADRO` karaktere kadar büyüyebilir (bkz. `proje.karakterler`).
        """
        # Düğme panelin başlık çubuğudur: açık/kapalı durumunu oku gösterir. Panel kendi
        # bölümünde (şeritteki **Karakter**) durduğu için açık başlar.
        b.pj_karakter_btn = gr.Button(KARAKTER_DUGMESI[True], variant="secondary",
                                      elem_classes=["sf-kadro-dugme"])
        b.pj_karakter_acik = gr.State(True)
        b.pj_kadro = gr.State([])
        with gr.Column(visible=True, elem_classes=["sf-kadro-panel"]) as b.pj_karakter_panel:
            gr.HTML(
                '<div class="sf-kadro-ust"><b>Karakter kadrosu</b>'
                '<p>Tekrar eden karakterleri kaydet; her kare sahnedeki karakterlerin '
                'referans görseliyle üretilir, yüz ve kıyafet sahneden sahneye korunur. '
                'Anlatımda karakteri burada yazdığın <b>adla</b> an.</p>'
                '<span class="sf-kadro-rozet">FLUX.2 klein · karede en fazla '
                f'{kadro.AZAMI_KARAKTER} karakter · kadroda en fazla {kadro.AZAMI_KADRO}</span></div>')
            with gr.Column(elem_classes=["sf-kadro-kart"]):
                gr.HTML('<div class="sf-kadro-no">Karakter</div>')
                b.pj_karakter_gorsel = gr.Image(
                    label="Referans görsel", show_label=False, type="filepath",
                    sources=["upload", "clipboard"], height=220,
                    elem_classes=["sf-kadro-gorsel"])
                b.pj_karakter_ad = gr.Textbox(label="Adı", max_lines=1, placeholder="ör. Tekir")
                b.pj_karakter_tarif = gr.Textbox(
                    label="Görünüşü · İngilizce", lines=2, max_lines=4,
                    placeholder="ör. a chubby orange tabby cat, green eyes, "
                                "red collar with a golden bell")
                with gr.Row():
                    b.pj_karakter_uret_btn = gr.Button("✨ Tariften görsel üret", size="sm",
                                                       variant="secondary")
                    b.pj_karakter_kaydet_btn = gr.Button("💾 Karakteri kaydet", size="sm",
                                                         variant="primary")
            b.pj_karakter_not = gr.Markdown("", elem_classes=["sf-kadro-not"])

            @gr.render(inputs=[b.pj_kadro], queue=False)
            def _pj_kadro_listesi(kadro_):
                """Kaydedilen karakterler: ada tıkla → düzenle, 🗑 → kadrodan çıkar."""
                if not kadro_:
                    gr.Markdown("Henüz kayıtlı karakter yok: kartı doldur, "
                                "**Karakteri kaydet**'e bas.", elem_classes=["sf-kadro-bos"])
                    return
                gr.HTML(f'<div class="sf-kadro-no">Kayıtlı karakterler · {len(kadro_)}</div>')
                with gr.Row(elem_classes=["sf-kadro-liste"]):
                    for karakter in kadro_:
                        gorsel = karakter.get("gorsel") or ""
                        with gr.Column(min_width=0, elem_classes=["sf-kadro-oge"]):
                            gr.Image(value=gorsel if gorsel and Path(gorsel).is_file() else None,
                                     show_label=False, interactive=False, height=120,
                                     container=False, elem_classes=["sf-kadro-oge-gorsel"])
                            duzenle = gr.Button(karakter["ad"], size="sm", variant="secondary",
                                                elem_classes=["sf-kadro-oge-ad"])
                            sil = gr.Button("🗑 Sil", size="sm", variant="stop")
                        duzenle.click(lambda k, ad=karakter["ad"]: pj_karakter_duzenle(k, ad),
                                      [b.pj_kadro],
                                      [b.pj_karakter_ad, b.pj_karakter_tarif,
                                       b.pj_karakter_gorsel, b.pj_karakter_not],
                                      queue=False, api_name=False)
                        sil.click(lambda k, ad=karakter["ad"]: pj_karakter_sil(k, ad),
                                  [b.pj_kadro], [b.pj_kadro, b.pj_karakter_not],
                                  queue=False, api_name=False)

    def _kur_ayar_kaydi(self, b):
        """Ayarları genel dosyaya kaydetme / yükleme ve otomatik kaydetme tercihi."""
        with gr.Accordion("Ayarları kaydet · bütün ayarlar tek genel dosyada", open=False,
                          elem_classes=["sf-preset-save"]):
            editor.yardim(
                "Bu sayfadaki bütün ayarlar tek dosyaya kaydedilir ve uygulama her açılışta "
                f"kendiliğinden yükler. Dosya: `{proje_ayarlari.VARSAYILAN.yol}` (proje adı ve anlatım "
                "metni kaydedilmez).")
            with gr.Row():
                b.pj_ayar_kaydet_btn = gr.Button("Ayarları kaydet", variant="primary")
                b.pj_ayar_yukle_btn = gr.Button("Kayıtlı ayarları yükle")
                b.pj_ayar_sil_btn = gr.Button("Kayıtlı ayarı sil", variant="stop", size="sm",
                                            scale=0)
            b.pj_ayar_durum = editor.durum_kutusu(proje_ayarlari.VARSAYILAN.ozet(), "Ayar kaydı")
            # Otomatik kaydetme tercihi ayar kaydının altında durur: kapalı başlayan
            # açılır panel, yalnızca gerektiğinde açılır.
            with gr.Accordion("Üretilen dosyaları outputs klasörüne otomatik kaydet",
                              open=False):
                b.otomatik_kaydet = gr.Checkbox(
                    value=False, label="Otomatik kaydetmeyi aç",
                    info="Kapalıyken görsel, ses ve video geçici klasöre yazılır; yalnızca "
                         "indirme kutusundan alınır. Kalıcı olmasını istediklerin için bu "
                         "kutuyu işaretle.")
                b.kayit_durum = gr.Markdown(depolama.VARSAYILAN.durum_metni())

    def bagla(self, b):
        # Proje sekmesindeki kısa test: proje ayarlarıyla dili ve sesi dener.
        b.pj_ses_test_btn.click(pj_ses_testi,
                              [b.pj_ses_provider, b.pj_dil, b.pj_edge_ses, b.pj_gemini_ses, b.pj_gemini_model,
                               b.pj_stil, b.pj_hiz, b.pj_ton, b.pj_ref, b.pj_exag, b.pj_cfg],
                              [b.pj_ses_test_ses, b.pj_ses_test_durum], concurrency_limit=1,
                              api_name=False)
        # ── Proje oluştur sekmesi ────────────────────────────────────────
        # Pahalı ve uzun akış tek bir kuyruk işidir; aynı anda ikinci proje başlamasın.
        # Ayarları taşıyan alanlar tek listede: `pj_baslat` ve `pj_ayarlari_kaydet` bu sırayı
        # bekler, "Ayarları kaydet" de aynı listeyi girdi olarak kullanır.
        # `pj_bicim` listenin sonunda durur (`pj_ayar_sozlugu` ve `pj_ayar_uygula` sırası
        # buna göre); arayüzde ise sol sütunun en altında durur.
        b.pj_ayar_alanlari = [b.pj_ses_provider, b.pj_dil, b.pj_edge_ses, b.pj_hiz, b.pj_ton, b.pj_gemini_model,
                            b.pj_gemini_ses, b.pj_stil, b.pj_ref, b.pj_exag, b.pj_cfg, b.pj_altyazi,
                            b.pj_altyazi_preset, b.pj_altyazi_font, b.pj_altyazi_renk, b.pj_altyazi_kalin,
                            b.pj_altyazi_seviye, b.pj_gorsel_model, b.pj_genislik,
                            b.pj_yukseklik, b.pj_adim, b.pj_guidance,
                            b.pj_negatif, b.pj_video_adim, b.pj_adim_saniye, b.pj_ai, b.pj_ai_model,
                            b.pj_gorsel_stil, b.pj_genel_prompt, b.pj_bicim, b.pj_on_ayar,
                            b.pj_sahne_stratejisi,
                            # İlk sahne katmanları listenin **sonunda** durur: sıra
                            # `pj_ayar_sozlugu` ve `pj_ayar_uygula` ile birebir aynıdır.
                            b.pj_ilk_prompt, b.pj_ilk_negatif,
                            # Seslendirme seviyesi en sonda: sonradan eklendi, sıra yine
                            # `pj_ayar_sozlugu` ve `pj_ayar_uygula` ile aynıdır.
                            b.pj_ses_seviye,
                            # Kadro en sonda (`pj_kadro` State'i). Sıra
                            # `pj_ayar_sozlugu` ve `pj_ayar_uygula` ile aynıdır.
                            b.pj_kadro]
        # `self.pj_ayarlari_yukle` bunları döndürür: ayar alanları + strateji düğmelerinin
        # seçili görünümü + görünürlüğü değişen 3 grup ve negatif prompt notu.
        b.pj_ayar_ciktilari = b.pj_ayar_alanlari + [b.pj_sahne_default_btn,
                                                b.pj_sahne_tarih_btn, b.pj_sahne_pov_btn,
                                                b.pj_sahne_stratejisi_not, b.pj_edge_box,
                                                b.pj_gemini_box, b.pj_chatterbox_box, b.pj_negatif_not,
                                                # Prompt yapay zekâsı düğmeleri ve açıklaması:
                                                # içerikteki takım, ardından üretim kartındaki
                                                # **aynı seçimi gösteren** ikinci takım (tek
                                                # kaynak `pj_ai` durumudur).
                                                b.pj_ai_not, *b.pj_ai_dugmeleri,
                                                b.pj_ur_ai_not, *b.pj_ur_ai_dugmeleri]
        # `self._pj_prompt_guncellemeleri` yalnızca prompt katmanlarını değiştiren güncelleme
        # üretirken alanların sırasına ve ek alanlara ihtiyaç duyar.
        b.PJ_AYAR_SIRASI = {bilesen: sira for sira, bilesen in enumerate(b.pj_ayar_alanlari)}
        b.pj_ayar_ek_alanlari = b.pj_ayar_ciktilari[len(b.pj_ayar_alanlari):]
        # Projeye özel panel alanları: sahne planı notu, ses testi, dublaj bölümü, müzik
        # paneli (durum, tekrar tercihi, liste damgası, işaretleme sırası), altyazı
        # paneli ve üretim sayfasındaki üç ekleme panelinin durum satırları.
        # Bir proje açıldığında/yeni proje oluşturulduğunda tazelenir; önceki projede kalan
        # ses, dosya, müzik ya da açıklama yeni projede görünmez (bkz. `pj_panel_bos`).
        b.pj_panel_alanlari = [b.pj_sahne_not, b.pj_ses_test_ses, b.pj_ses_test_durum,
                             b.pj_cok_ses, b.pj_cok_dosyalar, b.pj_cok_durum, b.pj_cok_liste,
                             b.pj_muzik_durum, b.pj_muzik_tekrarla, b.pj_muzik_ducking,
                             b.pj_muzik_liste, b.pj_muzik_secim,
                             b.pj_dublaj_liste, b.pj_dublaj_secim,
                             b.pj_alt_durum, b.pj_alt_dosyalar,
                             b.pj_altyazi_liste, b.pj_altyazi_secim,
                             b.pj_ur_dublaj_durum, b.pj_ur_muzik_durum, b.pj_ur_altyazi_durum,
                             b.pj_gorsel_liste]
        # Proje adı elle değişince çıktı sırası: anlatım metni + prompt katmanları, panel
        # alanları, açık proje notu, panelin ait olduğu proje ve ayar kaydı notu
        # (`self.pj_ad_degisti`).
        b.PJ_AD_CIKTILARI = ([b.pj_metin, b.pj_genel_prompt, b.pj_gorsel_stil, b.pj_negatif,
                            b.pj_ilk_prompt, b.pj_ilk_negatif]
                           + b.pj_panel_alanlari + [b.pj_acik_not, b.pj_acik, b.pj_ayar_durum])
        # Kayıtlı bir proje seçilince görünümün yanı sıra anlatım metni, bütün ayarlar ve
        # projeye özel panel alanları kendi yerlerine yüklenir: çıktı sırası `self.pj_proje_sec`
        # ile birebir aynı olmalı.
        b.pj_proje_ciktilari = ([b.pj_ad, b.pj_durum, b.pj_ilerleme, b.pj_dosya_listesi, b.pj_gorsel_listesi,
                               b.pj_video, b.pj_cubuk, b.pj_metin]
                              + b.pj_ayar_ciktilari + [b.pj_ayar_durum] + b.pj_panel_alanlari)
        # Son girdi ana sayfada üretilen sahne planıdır (`pj_sahne_on_plan`): `pj_baslat`
        # son parametresi (`sahne_on_plan`) ile birebir eşleşir.
        b.pj_girdiler = [b.pj_ad, b.pj_metin] + b.pj_ayar_alanlari + [b.pj_sahne_on_plan]
        # Proje açma / yeni proje: yeni proje paneli ve alanları, seçim ekranının durum
        # satırı, ekran geçişi, açık proje notu ve panelin ait olduğu proje; ardından
        # çalışma panelinin bütün alanları (`self.pj_proje_sec` sırası).
        b.pj_ekran_ciktilari = ([b.pj_yeni_panel, b.pj_yeni_ad, b.pj_yeni_durum, b.pj_secim_durum,
                               b.pj_secim_ekrani, b.pj_calisma, b.pj_acik_not, b.pj_acik])
        b.pj_ac_ciktilari = b.pj_ekran_ciktilari + b.pj_proje_ciktilari
        # Dosya ve görsel listeleri görünür bileşenlere değil durumlara gider (bkz. `pj_dosya_listesi`).
        b.pj_ciktilar = [b.pj_durum, b.pj_ilerleme, b.pj_dosya_listesi, b.pj_gorsel_listesi, b.pj_video,
                         b.pj_cubuk]
        # ── Editör: bölüm şeridi, sahne şeridi, sağ panel ──────────────────
        # Şerit seçimi yalnızca tarayıcıda hangi panelin görüneceğini değiştirir. Başlat /
        # devam **Üretim** bölümünü, yeni proje ve geri dönüş **Metin** bölümünü açar;
        # üretim olaylarının girdi/çıktılarına dokunulmaz.
        b.pj_bolum.change(None, [b.pj_bolum], None, js=editor.BOLUM_JS, queue=False,
                          api_name=False)
        for pj_uretim_dugmesi in (b.pj_basla, b.pj_devam):
            pj_uretim_dugmesi.click(lambda: "uretim", None, [b.pj_bolum], queue=False,
                                    api_name=False)
        for pj_hazirlik_dugmesi in (b.pj_yeni_olustur_btn, b.pj_geri_btn):
            pj_hazirlik_dugmesi.click(lambda: editor.VARSAYILAN_BOLUM, None, [b.pj_bolum],
                                      queue=False, api_name=False)
        b.pj_araclar_btn.click(None, None, None, js=editor.ARACLAR_JS, queue=False,
                               api_name=False)
        b.pj_prompt_studyo_btn.click(None, None, None, js=editor.PROMPT_STUDYOSU_JS,
                                     queue=False, api_name=False)
        # Sahne şeridi proje açılınca ve üretim ilerledikçe (ilerleme çubuğu her pakette
        # değişir) tazelenir; izler kayıt listeleri ya da videodaki katmanlar değişince.
        # Başka proje açılınca seçim sıfırlanır: eski sahne numarası yeni projede yanlış
        # sahneye uygulanmasın (bkz. `pj_editor_proje_degisti`).
        b.pj_editor_sifir_ciktilari = [b.pj_secili_sahne, b.pj_ins_gorsel, b.pj_ins_bilgi,
                                       b.pj_ins_klip_onay, b.pj_serit]
        b.pj_acik.change(pj_editor_proje_degisti, [b.pj_ad], b.pj_editor_sifir_ciktilari,
                         queue=False, show_progress="hidden", api_name=False)
        b.pj_cubuk.change(pj_serit_tazele, [b.pj_ad, b.pj_secili_sahne], [b.pj_serit],
                          queue=False, show_progress="hidden", api_name=False)
        for tetik in (b.pj_acik.change, b.pj_katmanlar.change, b.pj_muzik_liste.change,
                      b.pj_dublaj_liste.change, b.pj_altyazi_liste.change,
                      b.pj_efekt_liste.change):
            tetik(pj_izler_tazele, [b.pj_ad], [b.pj_izler], queue=False,
                  show_progress="hidden", api_name=False)
        # Şeritteki tıklama: sağ panel o sahneyle dolar, şeritte seçim işaretlenir.
        b.pj_sahne_tik.change(
            pj_editor_sahne_sec, [b.pj_ad, b.pj_sahne_tik],
            [b.pj_secili_sahne, b.pj_ins_gorsel, b.pj_ins_bilgi, b.pj_prompt_sec,
             b.pj_prompt_editor, b.pj_serit], queue=False, api_name=False)
        b.pj_ins_kare_btn.click(
            pj_secili_kare_yenile, [b.pj_ad, b.pj_secili_sahne], b.pj_ciktilar,
            concurrency_limit=1, api_name=False
        ).then(pj_editor_sahne_tazele, [b.pj_ad, b.pj_secili_sahne],
               [b.pj_ins_gorsel, b.pj_ins_bilgi], api_name=False)
        # Klip silme geri alınamaz: önce onay kutusu açılır.
        b.pj_ins_klip_btn.click(lambda: gr.update(visible=True), None, [b.pj_ins_klip_onay],
                                queue=False, api_name=False)
        b.pj_ins_klip_vazgec.click(lambda: gr.update(visible=False), None,
                                   [b.pj_ins_klip_onay], queue=False, api_name=False)
        b.pj_ins_klip_evet.click(
            lambda: gr.update(visible=False), None, [b.pj_ins_klip_onay], queue=False,
            api_name=False
        ).then(pj_secili_klip_yenile, [b.pj_ad, b.pj_secili_sahne], b.pj_ciktilar,
               concurrency_limit=1, api_name=False
        ).then(pj_editor_sahne_tazele, [b.pj_ad, b.pj_secili_sahne],
               [b.pj_ins_gorsel, b.pj_ins_bilgi], api_name=False)
        b.pj_basla.click(pj_baslat, b.pj_girdiler, b.pj_ciktilar, concurrency_limit=1, api_name=False
                         ).then(pj_ham_video_goster, [b.pj_ad], [b.pj_cok_liste],
                                api_name=False)
        # Proje adı elle değiştirilirse içerik alanları o projeye ait olmaktan çıkar:
        # anlatım metni ve prompt'lar boşaltılır (bkz. `self.pj_ad_degisti`). `.change` yerine
        # `.input` kullanılır: yalnızca **kullanıcı** yazınca çalışır, proje açılırken
        # programatik olarak yazılan ad içeriği silmez.
        b.pj_ad.input(self.pj_ad_degisti, [b.pj_ad, b.pj_acik], b.PJ_AD_CIKTILARI, api_name=False)
        # Kayıtlı belgeler (Araçlar › Prompt): seçilince alanlar dolar. `.input` yalnızca
        # kullanıcının seçiminde tetiklenir; liste tazelenirken alanlar ezilmez.
        b.pj_ses_belge.input(pj_seslendirme_belgesi_ac, [b.pj_ses_belge],
                             [b.pj_metin, b.pj_belge_not], api_name=False)
        b.pj_prompt_belge.input(pj_prompt_belgesi_ac, [b.pj_prompt_belge],
                                [b.pj_genel_prompt, b.pj_gorsel_stil, b.pj_negatif, b.pj_ilk_prompt,
                                 b.pj_ilk_negatif, b.pj_belge_not], api_name=False)
        b.pj_belge_yenile.click(pj_belge_listeleri, [b.pj_ses_belge, b.pj_prompt_belge],
                                [b.pj_ses_belge, b.pj_prompt_belge], api_name=False)
        b.demo.load(pj_belge_listeleri, None, [b.pj_ses_belge, b.pj_prompt_belge], api_name=False)
        # Prompt sekmelerinde yeni belge kaydedilmiş olabilir: yeni proje açılırken tazelenir.
        b.pj_yeni_olustur_btn.click(pj_belge_listeleri, [b.pj_ses_belge, b.pj_prompt_belge],
                                    [b.pj_ses_belge, b.pj_prompt_belge], queue=False,
                                    api_name=False)
        b.pj_devam.click(pj_baslat, b.pj_girdiler, b.pj_ciktilar, concurrency_limit=1, api_name=False
                         ).then(pj_ham_video_goster, [b.pj_ad], [b.pj_cok_liste],
                                api_name=False)
        # Video altındaki düğmeler: ses / altyazı ekleme ve ham videoya dönme; hepsi
        # proje.mp4 üzerinde çalışır ve çıktılar `pj_ciktilar` ile aynıdır.
        b.pj_ses_ekle_btn.click(pj_modlu(ses_ekleme.videoya_ses_ekle,
                                         ses_ciktisi.seslendirme_sesi),
                              [b.pj_cikti_modu, b.pj_ad, b.pj_ses_seviye],
                              b.pj_ciktilar + [b.pj_ses_cikti, b.pj_katmanlar],
                              concurrency_limit=1, api_name=False)
        b.pj_altyazi_ekle_btn.click(ses_ekleme.videoya_altyazi_ekle, [b.pj_ad], b.pj_ciktilar,
                                  concurrency_limit=1, api_name=False)
        # Üretim sayfasındaki seslendirme seviyesi paneli: iki kaydırıcı senkron durur.
        # Ayarlar sekmesindeki değişince (proje açma dahil) buradaki de güncellenir; buradaki
        # yalnızca kullanıcı bırakınca (`release`) öbürüne yazar — döngü kurulmaz.
        b.pj_ses_seviye.change(lambda deger: deger, [b.pj_ses_seviye], [b.pj_ur_ses_seviye],
                               queue=False, api_name=False)
        b.pj_ur_ses_seviye.release(lambda deger: deger, [b.pj_ur_ses_seviye], [b.pj_ses_seviye],
                                   queue=False, api_name=False)
        # Dublaj paneli kaydırıcısı da aynı seviyedir: ayarlar sekmesindeki değişince
        # güncellenir, kullanıcı bırakınca oraya yazar (oradan üretim paneline geçer).
        b.pj_ses_seviye.change(lambda deger: deger, [b.pj_ses_seviye], [b.pj_ur_dublaj_seviye],
                               queue=False, api_name=False)
        b.pj_ur_dublaj_seviye.release(lambda deger: deger, [b.pj_ur_dublaj_seviye],
                                      [b.pj_ses_seviye], queue=False, api_name=False)
        b.pj_ur_ses_uygula_btn.click(pj_modlu(ses_ekleme.videoya_ses_ekle,
                                              ses_ciktisi.seslendirme_sesi),
                                     [b.pj_cikti_modu, b.pj_ad, b.pj_ur_ses_seviye],
                                     [b.pj_ur_ses_durum] + b.pj_ciktilar[1:] + [b.pj_ses_cikti, b.pj_katmanlar],
                                     concurrency_limit=1, api_name=False)
        # Altyazıyı **paneldeki ayarlarla** baştan kurar: eski gömme kaldırılır, yenisi
        # gömülür. Zaten eklenmiş altyazının görünümünü değiştirmenin tek yolu budur
        # (bkz. `videoya_altyazi_yeniden`).
        b.pj_altyazi_yeniden_btn.click(
            pj_altyazi_yeniden,
            [b.pj_ad, b.pj_altyazi, b.pj_altyazi_preset, b.pj_altyazi_font, b.pj_altyazi_renk,
             b.pj_altyazi_kalin, b.pj_altyazi_seviye],
            b.pj_ciktilar, concurrency_limit=1, api_name=False)
        # Kapalı panellerin başlığı içerik sayısını göstersin: dosya ve görseller
        # değiştiğinde (proje seçimi, adım üretimi, sıfırlama) başlık tazelenir.
        for liste in (b.pj_dosya_listesi, b.pj_gorsel_listesi):
            liste.change(pj_panel_sayilari, [b.pj_dosya_listesi, b.pj_gorsel_listesi],
                         [b.pj_dosya_box, b.pj_gorsel_box], queue=False, api_name=False)
        # Görünür dosya listesi ve galeri yalnızca panel açıkken dolar: panel açılınca
        # güncel liste yüklenir, açıkken liste değişirse (yeni adım, başka proje) tazelenir.
        for kutu, liste, acik, bilesen in ((b.pj_dosya_box, b.pj_dosya_listesi, b.pj_dosya_acik,
                                            b.pj_dosyalar),
                                           (b.pj_gorsel_box, b.pj_gorsel_listesi, b.pj_gorsel_acik,
                                            b.pj_gorseller)):
            kutu.expand(lambda deger: (True, deger), [liste], [acik, bilesen], api_name=False)
            kutu.collapse(lambda: False, None, [acik], queue=False, api_name=False)
            liste.change(pj_panel_doldur, [liste, acik], [bilesen], api_name=False)
        # İlk sahne prompt'u uzunluk uyarısı: model yalnızca ilk ~55 kelimeyi okuyor,
        # kullanıcı sessizce kaybetmesin (ölçüm: `pj_ilk_prompt_olcusu`).
        b.pj_ilk_prompt.change(pj_ilk_prompt_olcusu, [b.pj_ilk_prompt], [b.pj_ilk_prompt_not],
                             queue=False, show_progress="hidden", api_name=False)
        # ── Görsel onayı · kareleri incele / yenile ──────────────────────
        # Onay düğmesi videoları başlatır: çıktılar proje görünümüyle aynıdır, bitince
        # kare listesi de tazelenir (yeni kare üretilmiş olabilir).
        # Seslendirme sonrası kapı: seçilen prompt yapay zekâsını projeye işler ve akışı
        # sahne planı/prompt aşamasından sürdürür (bkz. `yonetim.prompt_uretimi_baslat`).
        b.pj_prompt_basla_btn.click(yonetim.prompt_uretimi_baslat,
                                    [b.pj_ad, b.pj_ai, b.pj_ai_model, b.pj_sahne_on_plan],
                                    b.pj_ciktilar, concurrency_limit=1, api_name=False)
        b.pj_gorsel_onay_btn.click(yonetim.gorsel_onayi_ver, [b.pj_ad], b.pj_ciktilar,
                                 concurrency_limit=1, api_name=False
                                 ).then(pj_gorsel_ac, None, [b.pj_gorsel_liste], api_name=False
                                 ).then(pj_ham_video_goster, [b.pj_ad],
                                        [b.pj_cok_liste], api_name=False)
        b.pj_gorsel_onay_ltx_btn.click(pj_gorsel_onay_ltx, [b.pj_ad], b.pj_ciktilar,
                                       concurrency_limit=1, api_name=False
                                       ).then(pj_gorsel_ac, None, [b.pj_gorsel_liste], api_name=False
                                       ).then(pj_ham_video_goster, [b.pj_ad],
                                              [b.pj_cok_liste], api_name=False)
        b.pj_gorsel_onay_agnes_btn.click(pj_gorsel_onay_agnes, [b.pj_ad], b.pj_ciktilar,
                                       concurrency_limit=1, api_name=False
                                       ).then(pj_gorsel_ac, None, [b.pj_gorsel_liste], api_name=False
                                       ).then(pj_ham_video_goster, [b.pj_ad],
                                              [b.pj_cok_liste], api_name=False)
        # Kaldır-yenile düğmeleri `gr.render` bloğunda bağlanır (bkz.
        # `_pj_gorsel_satirlari`); burada yalnızca listeyi tazeleyen düğme durur.
        b.pj_gorsel_goster_btn.click(pj_gorsel_ac, None, [b.pj_gorsel_liste], api_name=False)
        # Üretim bittiğinde (ya da onay kapısında durduğunda) liste kendiliğinden
        # tazelensin: kullanıcı paneli açtığında güncel kareleri görür.
        for pj_uretim_btn in (b.pj_basla, b.pj_devam):
            pj_uretim_btn.click(pj_gorsel_ac, None, [b.pj_gorsel_liste], api_name=False)
        # ── Ham video ────────────────────────────────────────────────────
        # Sonuç videosu her değiştiğinde (birleştirme, proje açma, ses/altyazı ekleme)
        # ham video ve dublaj panelindeki özet tazelenir. Akış bitince de bir kez
        # tazelenir: akış sürerken özet yazılmaz (bkz. `pj_ham_video_goster`).
        b.pj_video.change(pj_ham_video_goster, [b.pj_ad], [b.pj_cok_liste],
                          api_name=False)
        # Önizlemenin üstündeki katman satırı videoyla birlikte tazelenir.
        b.pj_video.change(pj_katmanlar, [b.pj_ad, b.pj_video, b.pj_cikti_modu],
                          [b.pj_katmanlar],
                          queue=False, show_progress="hidden", api_name=False)
        # Üretim modu: görsel ve video aşamaları bir sonraki başlangıçta bu seçimi okur.
        b.pj_uretim_modu.change(coklu_uretim.uretim_modu_ayarla, [b.pj_uretim_modu], None,
                                queue=False, show_progress="hidden", api_name=False)
        b.pj_cikti_modu_ciktilari = [b.pj_video, b.pj_ses_cikti, b.pj_altyazi_ekle_btn,
                                     b.pj_cok_geri_btn, b.pj_ses_ekle_btn,
                                     b.pj_ur_dublaj_ekle_btn, b.pj_muzik_ekle_btn,
                                     b.pj_muzik_kaldir_btn, b.pj_ses_indir_dugmesi,
                                     b.pj_katmanlar]
        for tetik in (b.pj_cikti_modu.change, b.pj_ad.change):
            tetik(pj_cikti_modu_degisti, [b.pj_cikti_modu, b.pj_ad, b.pj_video],
                  b.pj_cikti_modu_ciktilari, queue=False, show_progress="hidden",
                  api_name=False)
        # **Sesi indir**: dosya gizli kutuya konur, indirmeyi JS başlatır (♪ düğmesi gibi).
        b.pj_ses_indir_dugmesi.click(
            pj_ses_dosyasi_indir, [b.pj_ad], [b.pj_ses_dosya], api_name=False
        ).then(
            None, [b.pj_ses_dosya], None, api_name=False,
            js="(f) => { if (!f || !f.url) return; const a = document.createElement('a');"
               " a.href = f.url; a.download = f.orig_name || 'ses.mp3';"
               " document.body.appendChild(a); a.click(); a.remove(); }")
        # Tam ekran yalnızca tarayıcıda çalışır: önizlemedeki videoyu büyütür.
        b.pj_tam_ekran_btn.click(
            None, None, None, api_name=False,
            js="() => { const v = document.querySelector('#sf-onizleme video');"
               " if (!v) return; if (v.requestFullscreen) v.requestFullscreen();"
               " else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen(); }")
        # ♪ düğmesi: sesi MP3'e çıkar, sonra tarayıcıda indir (dosya kutusu gizli).
        b.pj_ses_indir_btn.click(
            pj_sesi_indir, [b.pj_ad, b.pj_video], [b.pj_ses_dosya], api_name=False
        ).then(
            None, [b.pj_ses_dosya], None, api_name=False,
            js="(f) => { if (!f || !f.url) return; const a = document.createElement('a');"
               " a.href = f.url; a.download = f.orig_name || 'ses.mp3';"
               " document.body.appendChild(a); a.click(); a.remove(); }")
        # ── Sahneler · adım incele / sil / yenile ────────────────────────
        # Liste `gr.render` bloğunda çizilir (bkz. `_pj_sahne_satirlari`); burada yalnızca
        # **Sahneleri incele** düğmesi bağlanır: zaman damgasını tazeler ve seçili adımı
        # temizler, böylece liste yeniden çizilir.
        b.pj_sahne_incele_btn.click(pj_sahne_ac, None, [b.pj_sahne_acik, b.pj_sahne_sec],
                                  api_name=False)
        b.pj_prompt_incele_btn.click(
            pj_prompt_listele, [b.pj_ad],
            [b.pj_prompt_sec, b.pj_prompt_gorsel, b.pj_prompt_negatif,
             b.pj_prompt_not, b.pj_prompt_editor], api_name=False)
        b.pj_prompt_sec.change(
            pj_prompt_secildi, [b.pj_ad, b.pj_prompt_sec],
            [b.pj_prompt_gorsel, b.pj_prompt_negatif, b.pj_prompt_not], api_name=False)
        b.pj_prompt_onay.click(
            pj_sahne_prompt_onayla,
            [b.pj_ad, b.pj_prompt_sec, b.pj_prompt_gorsel, b.pj_prompt_negatif],
            b.pj_ciktilar, concurrency_limit=1, api_name=False
        ).then(
            pj_prompt_listele, [b.pj_ad],
            [b.pj_prompt_sec, b.pj_prompt_gorsel, b.pj_prompt_negatif,
             b.pj_prompt_not, b.pj_prompt_editor], api_name=False)
        # ── Müzik: kaydet · sil (2. sekme) · videoya ekle · kaldır (üretim sekmesi) ──
        # Çıktılar müzik panelinin alanları + proje görünümüdür, böylece video ve dosya
        # listesi de aynı anda tazelenir. Liste damgası her işlemde değişir: `gr.render`
        # blokları (`_pj_muzik_satirlari`, `_pj_ur_muzik`) kayıtlı müzikleri
        # `parcalar.json`dan yeniden çizer.
        #
        # İki çıktı listesi **aynı sıradadır**, yalnızca ilk alan (durum satırı) değişir:
        # kaydetme kendi sekmesindeki duruma, videoya ekleme üretim sayfasındakine yazar.
        # Böylece kullanıcı hangi sekmedeyse cevabı orada görür.
        b.pj_muzik_ciktilari = ([b.pj_muzik_durum, b.pj_muzik_liste, b.pj_muzik_secim,
                               b.pj_muzik_tekrarla, b.pj_muzik_ducking] + b.pj_ciktilar[1:])
        b.pj_ur_muzik_ciktilari = ([b.pj_ur_muzik_durum] + b.pj_muzik_ciktilari[1:])
        # Yapay zekâ ile üretilen müzik dosya kutusuna konur (kutunun `change`i kırpmayı
        # kurar) ve müzik adı önerilir; kaydetmek kullanıcıya kalır.
        b.pj_muzik_yz_btn.click(pj_muzik_yz_uret,
                                [b.pj_ad, b.pj_muzik_yz_tarif, b.pj_muzik_yz_sure,
                                 b.pj_muzik_yz_bpm, b.pj_ai],
                                [b.pj_muzik_yz_durum, b.pj_muzik_dosya, b.pj_muzik_ad],
                                concurrency_limit=1, api_name=False)
        # Dosya yüklenince kırpma kaydırıcıları dosyanın süresine göre kurulur.
        b.pj_muzik_dosya.change(pj_muzik_dosya_degisti, [b.pj_muzik_dosya],
                              [b.pj_muzik_bas, b.pj_muzik_bit, b.pj_muzik_sure_not], api_name=False)
        b.pj_muzik_kaydet_btn.click(
            muzik.muzik_kaydet,
            [b.pj_ad, b.pj_muzik_dosya, b.pj_muzik_ad, b.pj_muzik_seviye, b.pj_muzik_bas, b.pj_muzik_bit,
             b.pj_muzik_giris_karartma, b.pj_muzik_cikis_karartma],
            b.pj_muzik_ciktilari, concurrency_limit=1, api_name=False)
        # Videoya ekleme girdisi **işaretleme sırasıdır** (`pj_muzik_secim`): müzikler o
        # sırayla çalar. Tekrar tercihi de karışımın bir parçasıdır.
        b.pj_muzik_ekle_btn.click(pj_modlu(muzik.muzik_videoya_ekle, ses_ciktisi.muzik_sesi),
                                [b.pj_cikti_modu, b.pj_ad, b.pj_muzik_secim,
                                 b.pj_muzik_tekrarla, b.pj_muzik_ducking],
                                b.pj_ur_muzik_ciktilari + [b.pj_ses_cikti, b.pj_katmanlar], concurrency_limit=1, api_name=False)
        b.pj_muzik_kaldir_btn.click(pj_modlu(muzik.muzikleri_kaldir,
                                             ses_ciktisi.muzik_sesi_kaldir),
                                  [b.pj_cikti_modu, b.pj_ad],
                                  b.pj_ur_muzik_ciktilari + [b.pj_ses_cikti, b.pj_katmanlar], concurrency_limit=1, api_name=False)
        # Tekrar tercihi projeye yazılır: video sonradan yeniden kurulursa karışım aynı
        # tercihle geri uygulanır (bkz. `muzik.muzik_geri_uygula`).
        b.pj_muzik_tekrarla.change(muzik.muzik_tekrarini_yaz, [b.pj_ad, b.pj_muzik_tekrarla],
                                 None, api_name=False)
        # Ducking tercihi de projeye yazılır: video yeniden kurulunca karışım aynı
        # tercihle geri uygulanır (bkz. `muzik.muzik_geri_uygula`).
        b.pj_muzik_ducking.change(muzik.muzik_duckingi_yaz, [b.pj_ad, b.pj_muzik_ducking],
                                None, api_name=False)
        # ── Dublaj: kaydet (2. sekme) · videoya ekle (üretim sekmesi) ────────────
        # Girdiler seçili projeye (`pj_ad`) uygulanır; çıktılar panel alanları + proje
        # görünümüdür, böylece video ve dosya listesi de aynı anda tazelenir. Müzikte
        # olduğu gibi iki liste aynı sıradadır, yalnızca durum satırı farklıdır.
        b.pj_dublaj_ciktilari = ([b.pj_cok_durum, b.pj_dublaj_liste, b.pj_dublaj_secim,
                                b.pj_cok_ses, b.pj_cok_dosyalar, b.pj_cok_liste]
                               + b.pj_ciktilar[1:])
        b.pj_ur_dublaj_ciktilari = ([b.pj_ur_dublaj_durum] + b.pj_dublaj_ciktilari[1:])
        b.pj_cok_uret_btn.click(
            diller.dil_sesi_uret,
            [b.pj_ad, b.pj_cok_dil, b.pj_cok_cevir, b.pj_cok_provider, b.pj_cok_edge_ses,
             b.pj_cok_gemini_model, b.pj_cok_gemini_ses, b.pj_cok_hiz, b.pj_cok_ton,
             b.pj_dublaj_ad, b.pj_cok_sahne, b.pj_cok_ceviri_ai],
            b.pj_dublaj_ciktilari, concurrency_limit=1, api_name=False)
        b.pj_ur_dublaj_ekle_btn.click(pj_modlu(diller.dublaj_videoya_ekle,
                                               ses_ciktisi.dublaj_sesi),
                                    [b.pj_cikti_modu, b.pj_ad, b.pj_dublaj_secim,
                                     b.pj_ur_dublaj_seviye],
                                    b.pj_ur_dublaj_ciktilari + [b.pj_ses_cikti, b.pj_katmanlar],
                                    concurrency_limit=1, api_name=False)
        # ── Altyazı kayıtları: kaydet (2. sekme) · videoya göm (üretim sekmesi) ──
        b.pj_altyazi_ciktilari = ([b.pj_alt_durum, b.pj_altyazi_liste, b.pj_altyazi_secim,
                                 b.pj_alt_dosyalar] + b.pj_ciktilar[1:])
        b.pj_ur_altyazi_ciktilari = ([b.pj_ur_altyazi_durum] + b.pj_altyazi_ciktilari[1:])
        b.pj_alt_kaydet_btn.click(diller.altyazi_kaydet,
                                [b.pj_ad, b.pj_alt_dil, b.pj_alt_ad], b.pj_altyazi_ciktilari,
                                concurrency_limit=1, api_name=False)
        b.pj_ur_altyazi_ekle_btn.click(diller.altyazi_videoya_ekle,
                                     [b.pj_ad, b.pj_altyazi_secim], b.pj_ur_altyazi_ciktilari,
                                     concurrency_limit=1, api_name=False)
        b.pj_alt_dosyalar.change(lambda dosyalar: gr.update(open=bool(dosyalar)),
                               [b.pj_alt_dosyalar], [b.pj_alt_dosya_box], api_name=False)
        # ── Ses efektleri: hazırla (2. sekme) · videoya göm / kaldır (üretim sekmesi) ──
        # Müzikteki gibi iki liste aynı sıradadır, yalnızca durum satırı farklıdır.
        # Hazırlama üreteçtir: plan → Freesound → seçim → iz adımlarında durum tazelenir.
        # Yapay zekâ servisi **Sahne prompt'larının yapay zekâsı** seçimidir (`pj_ai`).
        b.pj_efekt_ciktilari = ([b.pj_efekt_durum, b.pj_efekt_liste, b.pj_efekt_secim,
                                 b.pj_efekt_seviye, b.pj_efekt_onizleme] + b.pj_ciktilar[1:])
        b.pj_ur_efekt_ciktilari = ([b.pj_ur_efekt_durum] + b.pj_efekt_ciktilari[1:])
        b.pj_efekt_yz_btn.click(lambda: gr.update(visible=False), None,
                                [b.pj_efekt_manuel_kutu], queue=False, api_name=False)
        b.pj_efekt_yz_btn.click(pj_efekt_yz_hazirla, [b.pj_ad, b.pj_efekt_ad, b.pj_ai],
                                b.pj_efekt_ciktilari, concurrency_limit=1, api_name=False)
        # Manuel düğme yalnızca sahne listesini açar; hazırlama listenin altındaki
        # düğmededir (bkz. `_pj_efekt_manuel`).
        b.pj_efekt_manuel_btn.click(lambda: gr.update(visible=True), None,
                                    [b.pj_efekt_manuel_kutu], queue=False,
                                    api_name=False)
        b.pj_ur_efekt_ekle_btn.click(efekt_ekleme.efekt_videoya_ekle,
                                     [b.pj_ad, b.pj_efekt_secim, b.pj_efekt_seviye],
                                     b.pj_ur_efekt_ciktilari, concurrency_limit=1, api_name=False)
        b.pj_ur_efekt_kaldir_btn.click(efekt_ekleme.efektleri_kaldir, [b.pj_ad],
                                       b.pj_ur_efekt_ciktilari, concurrency_limit=1,
                                       api_name=False)
        # ── Ses efektleri · sahne sahne düzenleme ──
        # Her değişiklik düzenleme damgasını (sahne listesi yeniden çizilir) ve efekt
        # listesi damgasını (özetler, gömme paneli) tazeler; kayıt videodaysa video da
        # değişmiş olabilir, bu yüzden proje görünümü de çıktıdadır.
        b.pj_efd_ciktilari = ([b.pj_efd_durum, b.pj_efd_damga, b.pj_efekt_liste]
                              + b.pj_ciktilar[1:])
        # Kayıt listesi değişince (hazırlama/silme) ya da proje değişince seçici tazelenir.
        for tetik in (b.pj_efekt_liste.change, b.pj_ad.change):
            tetik(pj_efd_kayitlari, [b.pj_ad, b.pj_efd_kayit], [b.pj_efd_kayit], queue=False,
                  api_name=False)
        # **Ham videoya geri dön** düğmesi video kutusunun altında durur (sonuç sütunu);
        # işlevi seçili kayda bağlı olmadığı için bağlantısı burada kalır. Çıktısı eski
        # çok dilli paketidir: durum · ses · dosyalar · özet + proje görünümü.
        b.pj_cok_ciktilari = [b.pj_cok_durum, b.pj_cok_ses, b.pj_cok_dosyalar,
                            b.pj_cok_liste] + b.pj_ciktilar
        # Ses modunda aynı düğme **Sesi sıfırla**dır (bkz. `ses_ciktisi.sesi_sifirla`).
        b.pj_cok_geri_btn.click(pj_modlu(diller.ham_videoya_geri_don, ses_ciktisi.sesi_sifirla),
                              [b.pj_cikti_modu, b.pj_ad],
                              b.pj_cok_ciktilari + [b.pj_ses_cikti, b.pj_katmanlar],
                              concurrency_limit=1, api_name=False)
        # Ses ya da dosya geldiğinde ilgili bölüm kendiliğinden açılsın: içerik kapalı
        # panelde gizli kalmasın. Değer boşalırsa bölüm yine kapanır.
        b.pj_cok_ses.change(lambda ses: gr.update(open=bool(ses)), [b.pj_cok_ses], [b.pj_cok_ses_box],
                          api_name=False)
        b.pj_cok_dosyalar.change(lambda dosyalar: gr.update(open=bool(dosyalar)), [b.pj_cok_dosyalar],
                               [b.pj_cok_dosya_box], api_name=False)
        # Dil değişince o dilin hazır dosyaları indirme kutusuna gelir ve Edge sesleri tazelenir.
        b.pj_cok_dil.change(diller.dil_dosya_goster, [b.pj_ad, b.pj_cok_dil],
                          [b.pj_cok_dosyalar, b.pj_cok_durum], api_name=False)
        b.pj_cok_dil.change(pj_dil_degisti, [b.pj_cok_dil], [b.pj_cok_edge_ses], api_name=False)
        b.pj_cok_provider.change(
            lambda name: [gr.Group(visible=name == ad) for ad in ("edge", "gemini", "chatterbox")],
            [b.pj_cok_provider], [b.pj_cok_edge_box, b.pj_cok_gemini_box, b.pj_cok_chatterbox_box],
            api_name=False)
        # ── Altyazı görünümü önizlemesi ──────────────────────────────────
        # Yazı tipi, renk, kalınlık, hazır ayar ve hedef biçim değiştiğinde küçük kare
        # yeniden üretilir (bkz. `pj_altyazi_onizleme`).
        b.pj_onizleme_girdileri = [b.pj_bicim, b.pj_altyazi_font, b.pj_altyazi_renk, b.pj_altyazi_kalin,
                                 b.pj_altyazi_seviye, b.pj_altyazi_preset, b.pj_altyazi_zemin]
        b.pj_onizleme_ciktilari = [b.pj_altyazi_onizleme_resim, b.pj_altyazi_onizleme_not]
        for pj_onizleme_tetik in (b.pj_bicim, b.pj_altyazi_font, b.pj_altyazi_renk, b.pj_altyazi_kalin,
                                  b.pj_altyazi_seviye, b.pj_altyazi_preset, b.pj_altyazi_zemin):
            pj_onizleme_tetik.change(pj_altyazi_onizleme, b.pj_onizleme_girdileri,
                                     b.pj_onizleme_ciktilari, show_progress="hidden",
                                     api_name=False)
        # Hazır ayar değişince **Seviye** kaydırıcısı da şablonun değerine gelir; şu an bütün
        # şablonlar aynı varsayılanı getirir (bkz. `pj_altyazi_preset_degisti`).
        b.pj_altyazi_preset.change(pj_altyazi_preset_degisti, [b.pj_altyazi_preset],
                                 [b.pj_altyazi_seviye], api_name=False)
        # ── Ayarları kaydet / yükle / sil ────────────────────────────────
        b.pj_ayar_kaydet_btn.click(pj_ayarlari_kaydet, b.pj_ayar_alanlari, [b.pj_ayar_durum],
                                 api_name=False)
        b.pj_ayar_yukle_btn.click(self.pj_ayarlari_yukle, None, b.pj_ayar_ciktilari + [b.pj_ayar_durum],
                                api_name=False)
        b.pj_ayar_sil_btn.click(pj_ayarlari_sil, None, [b.pj_ayar_durum], api_name=False)
        # Açılışta kayıtlı ayarlar alanlara yüklenir; dosya yoksa hiçbir alan değişmez.
        # Açılışta kayıtlı ayarlar alanlara yüklenir, ardından önizleme o değerlerle çizilir.
        b.demo.load(self.pj_ayarlari_yukle, None, b.pj_ayar_ciktilari + [b.pj_ayar_durum],
                  api_name=False).then(pj_altyazi_onizleme, b.pj_onizleme_girdileri,
                                       b.pj_onizleme_ciktilari, api_name=False)
        b.pj_durdur.click(calisma_kilidi.durdur, None, [b.pj_durum], queue=False, api_name=False)
        b.pj_deneme_btn.click(yeniden_deneme.denemeleri_sifirla, [b.pj_ad], b.pj_ciktilar, api_name=False)
        # ── Seçim ekranı ↔ çalışma paneli ────────────────────────────────────────
        # Proje satırlarındaki **Aç** ve **Sil** düğmeleri `gr.render` bloğunda bağlanır
        # (bkz. `_pj_satirlari`); burada yalnızca ekran düzeyindeki düğmeler durur.
        b.pj_yeni_ac_btn.click(pj_yeni_panel_ac, None,
                             [b.pj_yeni_panel, b.pj_yeni_ad, b.pj_yeni_durum], api_name=False)
        b.pj_yeni_iptal_btn.click(pj_yeni_panel_kapat, None,
                                [b.pj_yeni_panel, b.pj_yeni_ad, b.pj_yeni_durum], api_name=False)
        b.pj_yeni_olustur_btn.click(self.pj_projeyi_olustur, [b.pj_yeni_ad], b.pj_ac_ciktilari,
                                  api_name=False)
        b.pj_geri_btn.click(pj_secime_don, None,
                          [b.pj_secim_ekrani, b.pj_calisma, b.pj_acik_not, b.pj_secim_durum, b.pj_projeler],
                          api_name=False)
        # Silme: **Onayla** projeyi siler ve paneli tazeler, **İptal** vazgeçer.
        b.pj_sil_onay_btn.click(pj_sil_onayla, [b.pj_sil_hedef],
                              [b.pj_secim_durum, b.pj_sil_panel, b.pj_projeler, b.pj_sil_hedef,
                               b.pj_sil_uyari], api_name=False)
        b.pj_sil_iptal_btn.click(pj_sil_iptal, None,
                               [b.pj_sil_panel, b.pj_sil_hedef, b.pj_sil_uyari], api_name=False)
        b.pj_ses_provider.change(pj_ses_servis_degisti, [b.pj_ses_provider],
                               [b.pj_edge_box, b.pj_gemini_box, b.pj_chatterbox_box], api_name=False)
        b.pj_dil.change(pj_dil_degisti, [b.pj_dil], [b.pj_edge_ses], api_name=False)
        # Prompt yapay zekâsı düğmeleri: strateji düğmeleriyle aynı desen (seçim duruma
        # yazılır, model listesi seçilen servise göre tazelenir, seçili düğme vurgulanır).
        # İki takım (içerik kartı + üretim kartı) aynı durumu besler; her basış **iki**
        # takımın görünümünü birlikte tazeler.
        b.pj_ai_ciktilari = [b.pj_ai, b.pj_ai_model, b.pj_ai_not, *b.pj_ai_dugmeleri,
                            b.pj_ur_ai_not, *b.pj_ur_ai_dugmeleri]
        for _takim in (b.pj_ai_dugmeleri, b.pj_ur_ai_dugmeleri):
            for _dugme, (_etiket, _ad) in zip(_takim, metin_ortak.ai_secenekleri()):
                _dugme.click(lambda ad=_ad: pj_prompt_ai_sec(ad), None, b.pj_ai_ciktilari,
                             queue=False, api_name=False)
        # Seçilen strateji hem sahne önizlemesine hem de projeye kaydedilen ayarlara
        # taşınır; düğmeler aynı anda yalnızca seçili olanı vurgular.
        _strateji_ciktilari = [b.pj_sahne_stratejisi, b.pj_sahne_default_btn,
                               b.pj_sahne_tarih_btn, b.pj_sahne_pov_btn,
                               b.pj_sahne_stratejisi_not]
        for _dugme, _strateji in ((b.pj_sahne_default_btn, STRATEJI_DEFAULT),
                                  (b.pj_sahne_tarih_btn, STRATEJI_TARIH),
                                  (b.pj_sahne_pov_btn, STRATEJI_BIRINCI_KISI)):
            _dugme.click(lambda strateji=_strateji: pj_sahne_stratejisi_sec(strateji), None,
                         _strateji_ciktilari, queue=False, api_name=False)
        # 👥 Karakterler: düğme paneli açıp kapatır; kartın düğmeleri karakterin referans
        # görselini tariften üretir (projenin görsel stili ve modeliyle) ve karakteri
        # kadroya kaydeder. Listedeki düzenle/sil olayları `_pj_kadro_listesi` içindedir.
        b.pj_karakter_btn.click(pj_karakter_paneli, [b.pj_karakter_acik],
                                [b.pj_karakter_acik, b.pj_karakter_panel, b.pj_karakter_btn],
                                queue=False,
                                api_name=False)
        b.pj_karakter_uret_btn.click(pj_karakter_referans_uret,
                                     [b.pj_karakter_ad, b.pj_karakter_tarif, b.pj_gorsel_stil,
                                      b.pj_gorsel_model],
                                     [b.pj_karakter_gorsel, b.pj_karakter_not],
                                     concurrency_limit=1, api_name=False)
        b.pj_karakter_kaydet_btn.click(pj_karakter_kaydet,
                                       [b.pj_kadro, b.pj_karakter_ad, b.pj_karakter_tarif,
                                        b.pj_karakter_gorsel],
                                       [b.pj_kadro, b.pj_karakter_ad, b.pj_karakter_tarif,
                                        b.pj_karakter_gorsel, b.pj_karakter_not],
                                       queue=False, api_name=False)
        # Sahne planı: yapay zekâ anlatımı içerik sınırlarından sahnelere böler ve her sahneye
        # ayrı süre verir; **Adım süresi** kaydırıcısı üst sınır olarak güncellenir. İşlev
        # üreteçtir: düğmeye basıldığı anda durum satırı "çalışıyor"a döner, plan hazır
        # olunca rapor aynı alana yazılır.
        # Tavan kaydırıcısı **girdidir**, çıktı değil: düğme kullanıcının seçtiği sınıra
        # uyar ve o değeri değiştirmez (eskiden plandaki en uzun sahneyi oraya yazıp
        # seçimi eziyordu).
        # Düğme iki şey üretir: rapor metni ve akışa taşınacak **plan kaydı**. Kayıt
        # başlatmada `pj_girdiler` üzerinden sahneleme aşamasına gider.
        # Proje adı da girdidir: plan açık projenin `proje.txt`'sine de yazılır.
        b.pj_sahne_btn.click(pj_sahne_planla,
                           [b.pj_metin, b.pj_ai, b.pj_ai_model, b.pj_dil, b.pj_hiz,
                            b.pj_adim_saniye, b.pj_sahne_stratejisi, b.pj_ad],
                           [b.pj_sahne_not, b.pj_sahne_on_plan], api_name=False)
        # Çıktı biçimi görsel boyutunu ve altyazı önerisini de belirler; üçü birlikte
        # güncellenir ki arayüz ile üretilen kare oranı hiç ayrışmasın.
        b.pj_bicim.change(pj_bicim_degisti, [b.pj_bicim],
                        [b.pj_genislik, b.pj_yukseklik, b.pj_altyazi_preset], api_name=False)
        # Ön ayar: tuval, altyazı, görsel modeli/boyutu/adımı, video adımı ve adım süresi.
        b.pj_on_ayar.change(pj_on_ayar_degisti, [b.pj_on_ayar],
                          [b.pj_bicim, b.pj_altyazi_preset, b.pj_gorsel_model, b.pj_adim, b.pj_guidance,
                           b.pj_genislik, b.pj_yukseklik, b.pj_video_adim, b.pj_adim_saniye,
                           b.pj_on_ayar_not, b.pj_negatif, b.pj_negatif_not], api_name=False)
        # Negatif prompt alanı, seçilen görsel modelinin desteğine göre açılır ya da kilitlenir.
        b.pj_gorsel_model.change(pj_gorsel_model_degisti, [b.pj_gorsel_model, b.pj_bicim],
                               [b.pj_adim, b.pj_guidance, b.pj_genislik, b.pj_yukseklik, b.pj_negatif,
                                b.pj_negatif_not], api_name=False)
        # İlk sahne negatifi de aynı kurala uyar (ön ayar ve proje yükleme de modeli
        # değiştirdiği için bu olay onlarda da tetiklenir).
        b.pj_gorsel_model.change(ilk_negatif_gorunumu, [b.pj_gorsel_model], [b.pj_ilk_negatif],
                                 queue=False, api_name=False)

    def _pj_prompt_guncellemeleri(self, icerik):
        """`pj_ayar_ciktilari` sırasında **yalnızca prompt katmanlarını** değiştiren liste.

        Prompt katmanları proje içeriğidir; seslendirme · altyazı · görsel · video
        **ayarları** genel ayardır ve ekranda olduğu gibi kalır (bu yüzden onlara
        `gr.update()` döner).
        """
        guncel = [gr.update() for _ in self.b.pj_ayar_alanlari]
        for bilesen, deger in ((self.b.pj_genel_prompt, icerik.get("genel") or ""),
                               (self.b.pj_gorsel_stil, icerik.get("stil") or ""),
                               (self.b.pj_negatif, icerik.get("negatif") or ""),
                               (self.b.pj_ilk_prompt, icerik.get("ilk_prompt") or ""),
                               (self.b.pj_ilk_negatif, icerik.get("ilk_negatif") or "")):
            guncel[self.b.PJ_AYAR_SIRASI[bilesen]] = gr.update(value=deger)
        return guncel + [gr.update() for _ in self.b.pj_ayar_ek_alanlari]

    def pj_ad_degisti(self, ad, acik):
        """Proje adı elle değiştirildi: panel içeriği artık başka bir projeye ait.

        Anlatım metni ve prompt katmanları **projeye özel içeriktir**; ad değiştiği anda
        panelden boşaltılır, böylece eski projenin metni/prompt'u yeni projeye geçmez.
        Projenin kendi kaydına dokunulmaz: aynı adı geri yazıp **Aç** ile içerik geri
        gelir. Ayarlar (seslendirme · altyazı · görsel · video) genel ayar olduğu için
        olduğu gibi kalır.
        """
        ad, onceki = (ad or "").strip(), (acik or "").strip()
        if not ad or depo.slug(ad) == onceki:
            return tuple(gr.update() for _ in self.b.PJ_AD_CIKTILARI)
        icerik = yonetim.icerik_varsayilanlari()
        notlar = [f"Açık proje: **{ad}**"]
        if onceki:
            notlar.append(f"Proje adı değişti: **{onceki}** projesinin anlatım metni ve "
                          "prompt'ları panelden boşaltıldı — içerik her zaman kendi "
                          "projesinde durur. **Aç** ile o projeyi geri yükleyebilirsin.")
        if ad in depo.liste():
            notlar.append(f"**{ad}** var olan bir proje: **Aç** ile projenin kaydını yükle.")
        else:
            notlar.append(f"**{ad}** yeni proje: metni ve prompt'ları önceki projeden "
                          "alınmadı; **Projeye başlat**'a basınca bu adla kurulur.")
        ayar_notu = (f"Proje adı değişti: **{onceki}** projesinin içeriği panelden boşaltıldı; "
                     "anlatım metni ve prompt'lar yalnızca kendi projesinde kalır.")
        return (gr.update(value=""), gr.update(value=icerik["genel"]),
                gr.update(value=icerik["stil"]), gr.update(value=icerik["negatif"]),
                # İlk sahne katmanları da projeye özel içeriktir: ad değişince boşalır.
                gr.update(value=icerik["ilk_prompt"]), gr.update(value=icerik["ilk_negatif"]),
                *pj_panel_bos(), gr.update(value="\n\n".join(notlar)), gr.update(value=""),
                gr.update(value=ayar_notu))

    def _pj_bos_alanlar(self, mesaj):
        """Proje yokken dönecek tam çıktı: görünüm, içerik ve panel alanları boşalır.

        Anlatım metni ve prompt katmanları proje içeriğidir; proje yokken ekranda kalmaz
        (genel ayar dosyasına kaydedilmiş prompt varsa o gelir). Seslendirme · altyazı ·
        görsel · video ayarlarına dokunulmaz. Dönüş sırası `pj_proje_ciktilari` ile
        birebir aynıdır: ad, durum, proje.txt, dosyalar, görseller, video, çubuk, anlatım
        metni, ayar alanları, ayar notu ve panel alanları.
        """
        return ((gr.update(), mesaj, "", [], [], None, ilerleme.bos_ilerleme_html(), "")
                + tuple(self._pj_prompt_guncellemeleri(yonetim.icerik_varsayilanlari()))
                + (gr.update(),) + pj_panel_bos())

    def pj_proje_sec(self, ad):
        """Listeden proje seçilince projenin **bütün verisini ilgili alanlara** getir.

        Proje.txt metni dosyalar/ilerleme panelinde görünür; bunun yanında projeye özgü
        veriler kendi alanlarına da yüklenir: anlatım metni, genel prompt, görsel stil,
        negatif prompt ve ses/altyazı/görsel/video ayarları. Böylece projeye dönüldüğünde
        ayarları metinden elle kopyalamak gerekmez; **Projeye başlat**'a basmak yeter.
        """
        if not (ad or "").strip():
            return self._pj_bos_alanlar("Listeden bir proje seç ya da yeni bir proje adı yaz.")
        durum, proje_metni, dosyalar, gorseller, video, cubuk = yonetim.proje_goster(ad)
        kayit = yonetim.proje_ayarlari(ad)
        if not kayit:
            # Görünüm yine de gelir (metin/dosyalar/ilerleme); ayar alanları değişmez.
            return ((ad, durum, proje_metni, dosyalar, gorseller, video, cubuk, gr.update())
                    + tuple(gr.update() for _ in self.b.pj_ayar_ciktilari) + (gr.update(),)
                    + pj_panel_bos())
        ayarlar = kayit["ayarlar"]
        notlar = []
        ref = ayarlar["ses"]["ref"]
        if ref and not Path(ref).is_file():
            ayarlar["ses"]["ref"] = ""
            notlar.append(f"Kayıtlı referans ses bulunamadı, alan boş bırakıldı: {ref}")
        notlar.append(f"Ayarlar, prompt'lar ve anlatım metni '{ad}' projesinden yüklendi.")
        # Kadronun referans görselleri projeye göreli kayıtlıdır; panel tam yolu gösterir.
        ayarlar["video"]["karakterler"] = kadro.mutlak_kadro(
            ayarlar["video"].get("karakterler") or [], depo.proje_klasoru(ad))
        return ((ad, durum, proje_metni, dosyalar, gorseller, video, cubuk, kayit["metin"])
                + tuple(pj_ayar_uygula(ayarlar)) + ("\n".join(notlar),)
                + pj_panel_projeden(ad))

    def _pj_yeni_alanlar(self, ad, mesaj):
        """Yeni proje açılışı: görünüm boşalır, ad yazılır, **proje içeriği** temizlenir.

        Anlatım metni ve prompt katmanları önceki projeden **alınmaz**: onlar proje
        içeriğidir. Başlangıç değeri yalnızca kullanıcının *Ayarları kaydet* ile genel
        ayar dosyasına yazdığı prompt'lardır (bkz. `yonetim.icerik_varsayilanlari`).
        Seslendirme · altyazı · görsel · video ayarlarına dokunulmaz: kullanıcı bunları ya
        kayıtlı genel ayarlardan ya da ekranda seçtiği gibi kullanır. Dönüş sırası
        `pj_proje_ciktilari` ile birebir aynıdır.
        """
        icerik = yonetim.icerik_varsayilanlari()
        return ((ad, mesaj, "", [], [], None,
                 ilerleme.bos_ilerleme_html(f"Yeni proje: **{ad}**. **Projeye başlat**'a "
                                                  "basınca klasör kurulur ve akış başlar."),
                 gr.update(value=icerik["metin"]))
                + tuple(self._pj_prompt_guncellemeleri(icerik))
                + (f"Yeni proje: **{ad}** · anlatım metni ve prompt katmanları önceki projeden "
                   "alınmadı; yalnızca kayıtlı genel ayarlar uygulandı.",)
                + pj_panel_bos())

    def pj_projeyi_ac(self, ad):
        """Liste satırındaki **Aç**: projeyi çalışma panelinde aç.

        Seçim ekranı gizlenir, çalışma paneli görünür; projenin anlatım metni, ayarları,
        dosyaları ve ilerlemesi alanlara yüklenir (`pj_proje_sec` ile aynı kaynak).
        """
        if not (ad or "").strip():
            return ((gr.update(), gr.update(), gr.update(),
                     gr.update(value="Önce listeden bir proje seç."),
                     gr.update(), gr.update(), gr.update(), gr.update())
                    + tuple(gr.update() for _ in self.b.pj_proje_ciktilari))
        return ((gr.update(), gr.update(), gr.update(), gr.update(value=""),
                 gr.update(visible=False), gr.update(visible=True),
                 gr.update(value=f"Açık proje: **{ad}** · kaldığı yerden sürer."),
                 # Panelin hangi projeye ait olduğu izlenir: ad elle değişirse içerik
                 # boşaltılır (bkz. `pj_ad_degisti`).
                 gr.update(value=depo.slug(ad)))
                + self.pj_proje_sec(ad))

    def pj_projeyi_olustur(self, ad):
        """Ad panelindeki **Oluştur**: adı doğrula ve çalışma panelini aç.

        Aynı ad daha önce kullanıldıysa yeni proje açılmaz; o ad zaten tek bir klasöre
        karşılık geldiği için var olan proje kaldığı yerden yüklenir. Yeni adda proje adı
        yazılır ve **proje içeriği** (anlatım metni + prompt katmanları) boşaltılır: yeni
        proje önceki projenin metnini ya da prompt'unu devralmaz; ayarlar ekranda olduğu
        gibi kalır (bkz. `_pj_yeni_alanlar`).
        """
        ham = (ad or "").strip()
        if not ham:
            return ((gr.update(), gr.update(),
                     gr.update(value="Yeni proje için bir ad yaz."), gr.update(),
                     gr.update(), gr.update(), gr.update(), gr.update())
                    + tuple(gr.update() for _ in self.b.pj_proje_ciktilari))
        # Ad klasör adına çevrilir (geçersiz karakterler atılır, boşluk `-` olur); panel de
        # listenin gösterdiği adı yazsın diye bu ad kullanılır.
        ad = depo.slug(ham)
        ceviri = f" (ad klasör adına çevrildi: **{ad}**)" if ad != ham else ""
        kapanis = (gr.update(visible=False), gr.update(value=""), gr.update(value=""),
                   gr.update(value=""), gr.update(visible=False), gr.update(visible=True))
        acik = gr.update(value=depo.slug(ad))
        if ad in depo.liste():
            return (kapanis + (gr.update(value=f"**{ad}** zaten vardı; var olan proje kaldığı "
                                            f"yerden açıldı.{ceviri}"), acik) + self.pj_proje_sec(ad))
        return (kapanis + (gr.update(value=f"Yeni proje: **{ad}**{ceviri} · anlatım metnini "
                                              "yaz, ayarları seç, sonra **Projeye başlat**'a "
                                              "bas."), acik)
                + self._pj_yeni_alanlar(ad, f"Yeni proje açıldı: **{ad}**{ceviri}. **Projeye "
                                       f"başlat**'a basınca '{ad}' klasörü kurulur ve akış "
                                       "başlar. Anlatım metni ve prompt'lar önceki projeden "
                                       "alınmadı; her projenin içeriği kendi kaydında durur."))

    def pj_ayarlari_yukle(self):
        """Kayıtlı ayarları oku ve alanlara uygula; dosya yoksa hiçbir şey değişmez."""
        ham = proje_ayarlari.VARSAYILAN.oku()
        if not ham:
            return ([gr.update()] * len(self.b.pj_ayar_ciktilari)
                    + [f"Kayıtlı ayar bulunamadı; alanlar varsayılan değerlerde kaldı.\n"
                       f"**Ayarları kaydet**'e basınca bu dosya oluşur: {proje_ayarlari.VARSAYILAN.yol}"])
        ayarlar = ayar_normalize.ayarlari_normalize(ham)
        notlar = []
        ref = ayarlar["ses"]["ref"]
        if ref and not Path(ref).is_file():
            ayarlar["ses"]["ref"] = ""
            notlar.append(f"Kayıtlı referans ses bulunamadı, alan boş bırakıldı: {ref}")
        # Kadro proje içeriğidir, genel ayar değildir: ayar dosyası yüklenince
        # paneldeki karakterlere dokunulmaz.
        return (pj_ayar_uygula(ayarlar, kadroyu_yaz=False)
                + ["\n".join(notlar + [proje_ayarlari.VARSAYILAN.ozet(ayarlar)])])
