"""API hesapları sekmesi: hizmet başına çoklu hesap, Cloudflare araçları."""
import gradio as gr

from studioflow.arayuz import tema
from studioflow.arayuz.islevler_gorsel import gorsel_cf_teshis, gorsel_cf_test, gorsel_hesap_bul
from studioflow.arayuz.islevler_hesaplar import (
    aktif_metni, api_aktif_yap, api_hesap_degisti, api_kaydet, api_servis_degisti, api_sil,
    api_yenile, arama_baglanti_testi, hesap_ozeti, kaggle_baglanti_testi, kota_hesabi_cikar,
    kota_listesi_metni, kota_listesini_temizle)
from studioflow.arayuz.sabitler import API_ALANLAR
from studioflow.arayuz.sayfa import Sayfa
from studioflow.ayarlar import api_hesaplari


class HesaplarSayfasi(Sayfa):
    ad = "hesaplar"

    def kur(self, b):
        with gr.Tab("API hesapları", elem_id="sf-accounts", elem_classes=["sf-secondary"]):
            gr.HTML(tema.ACCOUNTS_HEADING)
            with gr.Row(elem_classes=["sf-tool-grid"]):
                # Sol sütun iki karttır: hesap düzenleme (01) ve hemen altında kota bekleme
                # listesi (03). Liste uzadıkça sayfa itilmesin diye tablo sabit yükseklikte,
                # kendi içinde kaydırılır; sütun başlıkları kaydırırken üstte kalır.
                with gr.Column(scale=3, min_width=0, elem_classes=["sf-account-left"]):
                    with gr.Column(elem_classes=["sf-tool-card", "sf-account-editor"]):
                        gr.HTML(tema.panel_heading('01', 'Servis ve hesap', 'Kayıtlı hesabını seç veya yeni bir hesap ekle.'))
                        with gr.Row():
                            b.api_hizmet = gr.Dropdown(
                                [(bilgi["label"], ad) for ad, bilgi in api_hesaplari.HIZMETLER.items()],
                                value="gemini", label="Hizmet", scale=3)
                            b.api_link_btn = gr.Button("🔗 Anahtar sayfasını aç", size="sm", scale=1,
                                                     link=api_hesaplari.HIZMETLER["gemini"]["link"])
                        b.api_not = gr.Markdown("")
                        with gr.Row():
                            b.api_hesap = gr.Dropdown(choices=[], value=None, label="Kayıtlı hesap", scale=2)
                            b.api_yeni_ad = gr.Textbox(label="Yeni hesap adı", scale=2,
                                                     placeholder="boş bırak = seçili hesabı güncelle (ör. kişisel, iş)")
                        b.api_alan_kutulari = {}
                        with gr.Row():
                            for _ad, _etiket, _gizli in API_ALANLAR:
                                b.api_alan_kutulari[_ad] = gr.Textbox(
                                    label=_etiket, visible=False, type="password" if _gizli else "text")
                        b.api_kutulari = [b.api_alan_kutulari[ad] for ad, _e, _g in API_ALANLAR]
                        b.api_aktif = gr.Markdown(aktif_metni("gemini"))
                        with gr.Row(elem_classes=["sf-account-actions"]):
                            b.api_kaydet_btn = gr.Button("Hesabı kaydet ve aktif yap", variant="primary")
                            b.api_aktif_btn = gr.Button("Seçili hesabı aktif yap")
                            b.api_sil_btn = gr.Button("Seçili hesabı sil")
                            b.api_yenile_btn = gr.Button("Dosyadan yeniden yükle")

                    with gr.Column(elem_classes=["sf-tool-card", "sf-quota-panel"]):
                        gr.HTML(tema.panel_heading('03', 'Kota bekleme listesi',
                                                   'Kotası dolan hesaplar açılış saatine kadar kullanılmaz.'))
                        gr.Markdown(
                            "**Kota uyarısı veren her hesap** (bütün servisler) buraya alınır ve "
                            "açılış saatine kadar tekli ya da çoklu üretimde **hiç kullanılmaz**. "
                            "Açılış, servisin bildirdiği süredir (Hugging Face \"Try again in\", dakikalık "
                            "sınırda birkaç saniye); süre yoksa günlük sıfırlanma saatidir (Cloudflare "
                            "03:00, Gemini 11:00, diğerleri 24 saat). Liste uygulama kapansa da kalır. "
                            "Token'ı değiştirilen hesap da listeden düşer.",
                            elem_classes=["sf-quota-note"])
                        b.api_kota_liste = gr.Markdown("", max_height=420, elem_classes=["sf-quota-table"])
                        with gr.Row(elem_classes=["sf-quota-actions"]):
                            b.api_kota_yenile_btn = gr.Button("Listeyi yenile", size="sm")
                            b.api_kota_cikar_btn = gr.Button("Seçili hesabı listeden çıkar", size="sm")
                            b.api_kota_temizle_btn = gr.Button("Listeyi temizle", size="sm")

                with gr.Column(scale=2, min_width=0, elem_classes=["sf-tool-card", "sf-account-status"]):
                    gr.HTML(tema.panel_heading('02', 'Bağlantı özeti', 'Aktif hesaplarını ve işlem sonucunu takip et.'))
                    b.api_durum = gr.Textbox(label="Durum", interactive=False, lines=7, value=hesap_ozeti())
                    gr.Markdown("Anahtarlar bu bilgisayarda düz metin olarak saklanır. Hesap bilgilerini paylaşma.",
                                elem_classes=["sf-storage-note"])
                    with gr.Accordion("Hesap yönetimi ve yedek servisler", open=False, elem_classes=["sf-help"]):
                        gr.Markdown(
                            "# API hesapları\n"
                            "Bütün servislerin anahtarları **tek dosyada** tutulur ve her servise **birden fazla hesap** "
                            "ekleyebilirsin. Seçtiğin **aktif** hesap, ilgili üretim sekmelerinde kullanılır. Hesap "
                            "değiştirmek için listeden seçip **Seçili hesabı aktif yap**'a bas; yeni hesap için adını "
                            "yazıp **Hesabı kaydet ve aktif yap**'a bas.\n\n"
                            "**Proje çalışırken** bir hesap kota, yetki ya da bağlantı hatası verirse o hesap "
                            "atlanır ve **aynı işlem sıradaki hesapla sürer**; çalışan hesap otomatik olarak aktif "
                            "hesap yapılır. Yani bir hizmete birden fazla hesap kaydetmek, kotası dolan hesabın "
                            "yerine diğerinin geçmesini sağlar.\n\n"
                            "**Prompt üretiminde servis yedeği:** seçili prompt yapay zekâsı (ör. Gemini) kota, "
                            "yetki ya da model hatası verirse aynı işlem **anahtarı kayıtlı sıradaki prompt "
                            "servisiyle** (ChatGPT, Claude) sürdürülür; geçiş günlüğe yazılır ve akış durmaz. "
                            "Ücretsiz Gemini kotası bittiğinde bu yüzden iş kaybolmaz: yedek anahtar kayıtlıysa "
                            "prompt'lar onunla yazılır.\n\n"
                            "**Hikâye araştırması için arama servisleri:** Araçlar › Prompt › Araştırma "
                            "sırasıyla **Tavily → Exa → DDGS** ile arar. Tavily ve Exa ücretsiz kayıtla "
                            "anahtar verir (kredi kartı istemez); birden fazla hesap eklersen kotası biten "
                            "hesabın yerine sıradaki geçer, hepsi bitince sıradaki servise geçilir. DDGS "
                            "anahtarsızdır. **Jina Reader** sayfa okuma içindir ve anahtarsız da çalışır; "
                            "anahtar yalnızca sınırı yükseltir.\n\n"
                            f"Kayıt yeri: `{api_hesaplari.VARSAYILAN.yol}` · proje klasörünün dışında, bu bilgisayara özel. "
                            "Dosyayı Not Defteri ile elle düzenleyebilirsin; sonra *Dosyadan yeniden yükle*'ye bas.\n\n"
                            "⚠️ Dosya düz metindir; anahtarları kimseyle paylaşma."
                        )
                    with gr.Accordion("Bütün servislerin kurulum sayfaları", open=False):
                        gr.Markdown(
                            "Aşağıdaki bağlantılar ilgili servisin anahtar oluşturma sayfasını yeni sekmede açar. "
                            "Kurulum adımları her hizmetin kendi bölümünde de yazılıdır.\n\n"
                            + "\n".join(
                                f"- **{etiket}** — [kurulum sayfası]({link})  \n  {adimlar}"
                                for etiket, link, adimlar in api_hesaplari.KURULUM_SAYFALARI))
                    with gr.Group(visible=False, elem_classes=["sf-diagnostics"]) as b.api_cf_diag:
                        gr.Markdown("**Cloudflare araçları** · yukarıdaki alanlardaki Account ID ve token ile çalışır.")
                        with gr.Row():
                            b.api_cf_hesap_btn = gr.Button("Token'dan Account ID'yi bul")
                            b.api_cf_test_btn = gr.Button("Cloudflare bağlantısını test et")
                            b.api_cf_teshis_btn = gr.Button("Sorunu teşhis et")
                        b.api_cf_sonuc = gr.Markdown("")
                        gr.Markdown(
                            "**Cloudflare bağlantısını test et** gerçekten 512×512'lik küçük bir görsel üretir; "
                            "görsel dönerse hem token hem Account ID doğrudur. **Sorunu teşhis et** hiçbir şeyi "
                            "değiştirmez, yalnızca token'ı Cloudflare'e sorup sorunu madde madde yazar."
                        )
                    with gr.Group(visible=False, elem_classes=["sf-diagnostics"]) as b.api_kaggle_diag:
                        gr.Markdown("**Kaggle testi** · kaydedilmiş aktif hesabı Kaggle'a sorar; "
                                    "önce **Hesabı kaydet ve aktif yap**'a bas.")
                        b.api_kaggle_test_btn = gr.Button("Kaggle bağlantısını test et")
                        b.api_kaggle_sonuc = gr.Markdown("")
                    with gr.Group(visible=False, elem_classes=["sf-diagnostics"]) as b.api_arama_diag:
                        gr.Markdown("**Arama servisi testi** · yukarıdaki alandaki anahtarla (kaydetmeden) "
                                    "küçük bir deneme yapar. Tavily'de 2, Exa'da çok küçük bir kredi harcar.")
                        b.api_arama_test_btn = gr.Button("Arama servisini test et")
                        b.api_arama_sonuc = gr.Markdown("")

    def bagla(self, b):
        b.api_hizmet.change(api_servis_degisti, [b.api_hizmet],
                          [b.api_hesap, b.api_yeni_ad, b.api_aktif, b.api_durum, b.api_not, b.api_link_btn,
                           b.api_cf_diag, b.api_kaggle_diag, b.api_arama_diag] + b.api_kutulari,
                          api_name=False)
        b.api_hesap.change(api_hesap_degisti, [b.api_hizmet, b.api_hesap],
                         b.api_kutulari + [b.api_aktif], api_name=False)
        b.api_kaydet_btn.click(api_kaydet, [b.api_hizmet, b.api_hesap, b.api_yeni_ad] + b.api_kutulari,
                             [b.api_hesap, b.api_yeni_ad, b.api_aktif, b.api_durum] + b.api_kutulari, api_name=False)
        b.api_aktif_btn.click(api_aktif_yap, [b.api_hizmet, b.api_hesap], [b.api_aktif, b.api_durum], api_name=False)
        b.api_sil_btn.click(api_sil, [b.api_hizmet, b.api_hesap],
                          [b.api_hesap, b.api_yeni_ad, b.api_aktif, b.api_durum] + b.api_kutulari, api_name=False)
        b.api_yenile_btn.click(api_yenile, [b.api_hizmet],
                             [b.api_hesap, b.api_yeni_ad, b.api_aktif, b.api_durum] + b.api_kutulari, api_name=False)
        b.api_cf_hesap_btn.click(gorsel_hesap_bul,
                               [b.api_alan_kutulari["cf_token"], b.api_alan_kutulari["cf_account_id"]],
                               [b.api_alan_kutulari["cf_account_id"], b.api_cf_sonuc], api_name=False)
        b.api_cf_test_btn.click(gorsel_cf_test,
                              [b.api_alan_kutulari["cf_account_id"], b.api_alan_kutulari["cf_token"]],
                              [b.api_cf_sonuc], api_name=False)
        b.api_cf_teshis_btn.click(gorsel_cf_teshis,
                                [b.api_alan_kutulari["cf_token"], b.api_alan_kutulari["cf_account_id"]],
                                [b.api_cf_sonuc], api_name=False)
        b.api_kaggle_test_btn.click(kaggle_baglanti_testi, None, [b.api_kaggle_sonuc], api_name=False)
        b.api_kota_yenile_btn.click(kota_listesi_metni, None, [b.api_kota_liste], api_name=False)
        b.api_kota_cikar_btn.click(kota_hesabi_cikar, [b.api_hizmet, b.api_hesap],
                                   [b.api_kota_liste, b.api_durum], api_name=False)
        b.api_kota_temizle_btn.click(kota_listesini_temizle, None, [b.api_kota_liste, b.api_durum],
                                     api_name=False)
        b.demo.load(kota_listesi_metni, None, [b.api_kota_liste], api_name=False)
        b.api_arama_test_btn.click(arama_baglanti_testi, [b.api_hizmet] + b.api_kutulari,
                                   [b.api_arama_sonuc], api_name=False)
        b.demo.load(api_servis_degisti, [b.api_hizmet],
                  [b.api_hesap, b.api_yeni_ad, b.api_aktif, b.api_durum, b.api_not, b.api_link_btn,
                   b.api_cf_diag, b.api_kaggle_diag, b.api_arama_diag] + b.api_kutulari,
                  api_name=False)
