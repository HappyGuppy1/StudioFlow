"""Araçlar › Seslendirme sekmesi (ses testi dâhil)."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_ses import (
    check_voice_service, narrate, ses_test_metni, ses_test_sesleri, ses_testi,
    ses_testi_durdur, ses_testi_tumu, subtitle_preset, voice_options)
from studioflow.arayuz.sabitler import STYLE, SUB_PRESETLER
from studioflow.arayuz.sayfa import Sayfa
from studioflow.saglayicilar import ses_edge
from studioflow.altyazi.kural import SUB_AYAR, SUB_AYAR_SINIR
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.saglayicilar.ses_ortak import (
    CHATTERBOX_URL, GEMINI_MODELS, VOICES, plan_text, test_cumlesi)


class SesAraciSayfasi(Sayfa):
    ad = "ses"

    def kur(self, b):
        with gr.Tab("Seslendirme", elem_id="sf-voice-tool"):
            gr.HTML(tema.VOICE_HEADING)
            with gr.Accordion('Ses servisleri ve altyazı bilgisi', open=False, elem_classes=["sf-help"]):
                gr.Markdown(
                    "Üç servis de uzakta çalışır; model bu bilgisayara indirilmez.\n"
                    "- **Gemini** · En doğal tonlama ve üslup yönergesi; **varsayılan** seçim. Ücretsiz [AI Studio anahtarı](https://aistudio.google.com/apikey) ve günlük kota gerekir.\n"
                    "- **Edge** · Microsoft okuma servisi. Anahtar istemez, kota yok, saniyeler sürer; kelime zamanlarını servis kendisi verir, altyazı birebir hizalanır.\n"
                    f"- **Chatterbox** · Kendi sesini klonlar. [ZeroGPU Space]({CHATTERBOX_URL}) üzerinde çalışır, sıra beklenir.\n\n"
                    "**Altyazı:** Aşağıdaki *Altyazı üret* kutusu işaretliyse her üretimde `seslendirme.srt` ve "
                    "`seslendirme.vtt` yazılır ve sağdaki altyazı kutusundan ayrıca indirilebilir. Bloklar varsayılan "
                    "olarak Netflix Türkçe kılavuzuna göre bölünür (en fazla iki satır, satırda 42 karakter, ekranda "
                    "1,2–7 saniye); **Altyazı ayarları** bölümünden bu sınırları kendine göre değiştirebilirsin. "
                    "Edge kelime zamanlarını kendisi verir. Gemini ve Chatterbox zaman bilgisi vermez; bu iki serviste "
                    "ses, **Görsel üret** sekmesinde kayıtlı Cloudflare hesabıyla whisper'a dinletilir (ücretsiz günlük "
                    "kota, dakikada ~47 neuron). Hizalama başarısız olursa ses yine kaydedilir, yalnızca altyazı üretilmez."
                )
            with gr.Row(elem_classes=["sf-tool-grid"]):
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-tool-card", "sf-tool-editor"]):
                    gr.HTML(tema.panel_heading('01', 'Metin ve ses', 'Anlatımını yaz ve ses karakterini belirle.'))
                    b.provider = gr.Radio(
                        [("Edge · anahtarsız, hızlı", "edge"), ("Gemini · en doğal", "gemini"), ("Chatterbox · ses klonu", "chatterbox")],
                        value="gemini", label="Servis")
                    b.language = gr.Dropdown([(name, code) for code, name in LANGUAGES.items()], value="tr", label="Metnin dili")
                    b.text = gr.Textbox(label="Seslendirilecek metin", lines=10,
                                      placeholder="YouTube videonun anlatım metnini buraya yapıştır…")
                    b.plan = gr.Textbox(label="Metin planı", interactive=False, lines=2,
                                      value="Metni hedef dilde yaz. Dil seçimi metni otomatik çevirmiyor.")
                    with gr.Group(visible=False) as b.edge_box:
                        b.edge_voice = gr.Dropdown(choices=ses_edge.VARSAYILAN.guvenli_sesler("tr"), value="tr-TR-AhmetNeural", label="Edge sesi")
                        with gr.Row():
                            b.rate = gr.Slider(-50, 50, value=0, step=5, label="Konuşma hızı (%)")
                            b.pitch = gr.Slider(-50, 50, value=0, step=5, label="Ton (Hz)")
                    with gr.Group(visible=True) as b.gemini_box:
                        with gr.Row():
                            b.model = gr.Dropdown(GEMINI_MODELS, value=GEMINI_MODELS[0], label="Gemini modeli")
                            b.voice = gr.Dropdown(VOICES, value="Charon", label="Gemini sesi")
                        b.style = gr.Textbox(label="Anlatım üslubu (İngilizce yaz)", value=STYLE, lines=2)
                    with gr.Group(visible=False) as b.chatterbox_box:
                        gr.Markdown("ZeroGPU kotası tokensiz çok düşüktür. Tokenını sayfanın üstündeki **Hugging Face hesabı** bölümüne gir, sonra *Servisi kontrol et* ile doğrula.")
                        b.reference = gr.Audio(label="Referans ses · 3–30 saniye temiz kayıt", type="filepath", sources=["upload", "microphone"])
                        with gr.Row():
                            b.exaggeration = gr.Slider(0, 2, value=0.5, step=0.05, label="Duygu yoğunluğu")
                            b.cfg = gr.Slider(0, 1, value=0.5, step=0.05, label="Referansa bağlılık")
                    b.altyazi = gr.Checkbox(value=True, label="Altyazı üret (SRT + VTT)",
                                          info="Kapatırsan altyazı dosyası yazılmaz ve Gemini/Chatterbox için "
                                               "Cloudflare kotası harcanmaz.")
                    with gr.Accordion("Altyazı ayarları", open=False):
                        gr.Markdown(
                            "Varsayılanlar Netflix Türkçe kılavuzudur: satırda 42 karakter, iki satır, "
                            "ekranda 1,2–7 saniye. **Satırda en fazla karakter × blokta en fazla satır** "
                            "bir bloğun toplam uzunluğunu belirler. Ayarlar kaydedilmez; yalnızca bu "
                            "oturumdaki yeni üretimleri etkiler.\n\n"
                            "Alt yazı **her zaman kelime aralarından** bölünür: bir kelime asla ortadan "
                            "ayrılmaz (tek başına sınırı aşan çok uzun bir kelime kendi satırında kalır). "
                            "Dikey/kısa videolarda (Shorts, TikTok) veya CapCut gibi programlarda satırlar "
                            "programın kutusuna sığmayıp kelime bölünüyorsa **25–30 karakter** ve gerekirse "
                            "**1 satır** seç: satırlar kutuya sığar."
                        )
                        b.sub_preset = gr.Dropdown(SUB_PRESETLER, value="yatay", label="Hazır ayar")
                        with gr.Row():
                            b.sub_line_chars = gr.Slider(*SUB_AYAR_SINIR["line_chars"],
                                                       value=SUB_AYAR["line_chars"], step=1,
                                                       label="Satırda en fazla karakter")
                            b.sub_max_lines = gr.Slider(*SUB_AYAR_SINIR["max_lines"],
                                                      value=SUB_AYAR["max_lines"], step=1,
                                                      label="Blokta en fazla satır")
                        with gr.Row():
                            b.sub_min_seconds = gr.Slider(*SUB_AYAR_SINIR["min_seconds"],
                                                        value=SUB_AYAR["min_seconds"], step=0.1,
                                                        label="Blok ekranda en az (saniye)")
                            b.sub_max_seconds = gr.Slider(*SUB_AYAR_SINIR["max_seconds"],
                                                        value=SUB_AYAR["max_seconds"], step=0.5,
                                                        label="Blok ekranda en fazla (saniye)")
                    with gr.Row():
                        b.check_voice = gr.Button("Servisi kontrol et")
                        b.speak = gr.Button("Seslendirmeyi üret", variant="primary")
                    # Ses testi: test cümlesiyle sesleri dener; hiçbir test sesi kaydedilmez.
                    with gr.Accordion("Ses testi · her dilde her sesi dene (kaydedilmez)",
                                      open=False):
                        gr.Markdown(
                            "Test, seçtiğin dilin hazır cümlesiyle çalışır ve yukarıdaki servis/üslup "
                            "ayarlarını kullanır. Üretilen sesler **hiçbir yere kaydedilmez**: yalnızca "
                            "dinlemek için geçici klasörde tutulur ve bir sonraki testte silinir.")
                        b.pt_dil = gr.Dropdown(
                            [(ad, kod) for kod, ad in LANGUAGES.items() if kod != "auto"],
                            value="tr", label="Test dili")
                        b.pt_cumle = gr.Textbox(label="Test cümlesi · dile göre hazır gelir", lines=2,
                                              value=test_cumlesi("tr"),
                                              info="İstediğin gibi değiştirebilirsin; yalnızca testte "
                                                   "kullanılır.")
                        b.pt_ses = gr.Dropdown(choices=VOICES, value="Charon", label="Denenecek ses",
                                             info="Edge'de o dilin sesleri, Gemini'de otuz ses "
                                                  "listelenir.")
                        with gr.Row():
                            b.pt_tek_btn = gr.Button("Seçili sesi test et", variant="primary",
                                                   size="lg", elem_classes=["sf-test-btn"])
                            b.pt_tum_btn = gr.Button("Bu dildeki bütün sesleri dene")
                            b.pt_durdur_btn = gr.Button("Durdur", variant="stop", size="sm", scale=0)
                        b.pt_audio = gr.Audio(label="Test sesi · kaydedilmez", type="filepath",
                                            autoplay=True)
                        b.pt_dosyalar = gr.File(label="Test dosyaları · geçici, kaydedilmez",
                                              file_count="multiple")
                        b.pt_durum = gr.Textbox(label="Test durumu", lines=4, interactive=False,
                                              value="Hazır. Dili ve sesi seç, **Seçili sesi test et**'e "
                                                    "bas.")
                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-tool-output"]):
                    gr.HTML(tema.panel_heading('02', 'Dinle ve indir', 'Seslendirme ve altyazı dosyaların.'))
                    b.audio = gr.Audio(label="Seslendirme", type="filepath")
                    b.audio_files = gr.File(label="Ses dosyaları (WAV)", file_count="multiple")
                    b.altyazi_dosyalar = gr.File(label="Altyazı dosyaları (SRT + VTT)", file_count="multiple")
                    b.voice_status = gr.Textbox(label="Durum", lines=5, interactive=False,
                                              value="Hazır. Gemini seçili; anahtarı **API hesapları** "
                                                    "sekmesinden kaydet. Anahtarsız denemek için Edge'i "
                                                    "seç.")
            with gr.Accordion("Kayıt ve kullanım notları", open=False, elem_classes=["sf-help"]):
                gr.Markdown("Ses dosyaları, **Ayarları kaydet** panelindeki **otomatik kaydet** kutusu işaretliyse **outputs/audio** altında her çalışma için "
                            "ayrı klasöre yazılır; kapalıyken geçici klasörde kalır ve yalnızca indirme kutusundan alınır. Altyazı dosyaları sesin yanına yazılır."
                            " YouTube'a **seslendirme.srt** dosyasını yükle. Hata olursa tamamlanan parçalar korunur, otomatik tekrar yapılmaz. Anahtar ve token çıktı dosyalarına yazılmaz.")

    def bagla(self, b):
        b.provider.change(lambda name: [gr.Group(visible=name == key_name) for key_name in ("edge", "gemini", "chatterbox")],
                        [b.provider], [b.edge_box, b.gemini_box, b.chatterbox_box], api_name=False)
        b.language.change(voice_options, [b.language], [b.edge_voice], api_name=False)
        b.language.change(plan_text, [b.text, b.language], [b.plan], api_name=False)
        b.text.change(plan_text, [b.text, b.language], [b.plan], api_name=False)
        b.sub_preset.change(subtitle_preset, [b.sub_preset], [b.sub_line_chars, b.sub_max_lines], api_name=False)
        b.check_voice.click(check_voice_service, [b.provider, b.language, b.model], [b.voice_status], api_name=False)
        b.speak.click(narrate,
                    [b.provider, b.text, b.language, b.edge_voice, b.rate, b.pitch, b.model, b.voice, b.style,
                     b.reference, b.exaggeration, b.cfg, b.altyazi, b.sub_line_chars, b.sub_max_lines,
                     b.sub_max_seconds, b.sub_min_seconds],
                    [b.audio, b.audio_files, b.altyazi_dosyalar, b.voice_status], concurrency_limit=1, api_name=False)
        # ── Ses testi · dil ve ses listesi servise göre tazelenir; hiçbir test sesi kaydedilmez.
        b.provider.change(ses_test_sesleri, [b.provider, b.pt_dil], [b.pt_ses], api_name=False)
        b.pt_dil.change(ses_test_metni, [b.pt_dil], [b.pt_cumle], api_name=False)
        b.pt_dil.change(ses_test_sesleri, [b.provider, b.pt_dil], [b.pt_ses], api_name=False)
        b.pt_tek_btn.click(ses_testi,
                         [b.provider, b.pt_dil, b.pt_cumle, b.pt_ses, b.model, b.style, b.rate, b.pitch, b.reference,
                          b.exaggeration, b.cfg],
                         [b.pt_audio, b.pt_dosyalar, b.pt_durum], concurrency_limit=1, api_name=False)
        b.pt_tum_btn.click(ses_testi_tumu,
                         [b.provider, b.pt_dil, b.pt_cumle, b.model, b.style, b.rate, b.pitch, b.reference,
                          b.exaggeration, b.cfg],
                         [b.pt_audio, b.pt_dosyalar, b.pt_durum], concurrency_limit=1, api_name=False)
        # Durdurma kuyruğa girmemeli: basıldığı anda süren testi keser.
        b.pt_durdur_btn.click(ses_testi_durdur, None, [b.pt_durum], queue=False, api_name=False)
