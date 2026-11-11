# StudioFlow

[![Kurulum testi](https://github.com/HappyGuppy1/StudioFlow/actions/workflows/test.yml/badge.svg)](https://github.com/HappyGuppy1/StudioFlow/actions/workflows/test.yml)

StudioFlow; senaryo, görsel, video, seslendirme, dublaj, müzik ve altyazıyı tek bir
editörde birleştiren, yapay zekâ destekli bir video üretim stüdyosudur. Bilgisayarınızda
yerel bir sunucu olarak çalışır ve kendi uygulama penceresinde (ya da tarayıcıda) açılır.

> Uygulama arayüzü Türkçedir.

## Özellikler

- **Proje akışı:** konu → senaryo → sahneler → görseller → klipler → seslendirme → kurgu
- **Görsel üretimi:** Cloudflare Workers AI
- **Fotoğraftan video:** Hugging Face ZeroGPU Space'leri (LTX-2.3, Wan 2.2), Agnes AI
- **Seslendirme ve dublaj:** Gemini TTS, Edge TTS, Chatterbox; çok dilli dublaj
- **Müzik ve efekt:** Lyria, Freesound; otomatik ducking
- **Altyazı:** sesten yazıya, zamanlı SRT
- **Araştırma:** Tavily, Exa, DuckDuckGo, Wikipedia, YouTube ve TikTok verisi
- **Büyütme:** Kaggle GPU üzerinde görüntü/video büyütme

## Kurulum

Gereksinimler: **Windows** ve **Python 3.12**. ffmpeg'i kurmanıza gerek yok: bilgisayarda
yoksa `Baslat.bat` indirir.

### Kolay yol

1. Depoyu indirin (**Code › Download ZIP**) ve bir klasöre açın.
2. `Baslat.bat` dosyasına çift tıklayın.

İlk açılışta `.venv` sanal ortamı kurulur ve paketler indirilir (birkaç dakika). ffmpeg
bilgisayarda yoksa bir kez bu klasördeki `ffmpeg/` altına indirilir (~110 MB,
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) Windows derlemesi, SHA-256 özeti doğrulanır).
Sonraki açılışlar doğrudan başlar. Kurulum yarıda kesilirse `Baslat.bat` kaldığı yerden
devam eder.

### Elle kurulum

```bash
git clone https://github.com/HappyGuppy1/StudioFlow.git
cd StudioFlow
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m sunucu.ffmpeg_indir  # ffmpeg bilgisayarda yoksa ffmpeg/ klasörüne indirir
python -m sunucu            # uygulama penceresinde açar
python -m sunucu --tarayici # tarayıcıda açar (http://127.0.0.1:7870)
```

## Veri klasörü ve API anahtarları

Kullanıcı verisi kod klasörünün **dışında** tutulur. Yer `veri-klasoru.txt` dosyasında
yazar (varsayılan `%USERPROFILE%\Documents\StudioFlow`); `STUDIOFLOW_VERI` ortam
değişkeniyle de değiştirilebilir.

```
Documents\StudioFlow\
├── Ayarlar\    API anahtarları ve hesaplar (api-hesaplari.txt)
├── Projeler\   projeleriniz
└── Kayitlar\   kayıtlar
```

Depoda **hiçbir API anahtarı bulunmaz**. Anahtarlarınızı uygulama içinden
**Ayarlar › Hesaplar** sayfasından girin; her hizmetin yanında anahtarı nereden alacağınız
yazar. Hepsi isteğe bağlıdır; yalnızca kullanacağınız hizmetin anahtarı gerekir.

| Hizmet | Ne için |
| --- | --- |
| Hugging Face | Fotoğraftan video, Chatterbox ses klonlama |
| Gemini | Metin, seslendirme (TTS), müzik |
| Cloudflare Workers AI | Görsel üretimi, metin, sesten yazıya |
| Agnes AI | Fotoğraftan / metinden video |
| OpenAI, Anthropic, EVREN | Prompt üretimi (isteğe bağlı) |
| Kaggle | GPU ile büyütme |
| Freesound | Ses efektleri |
| Tavily, Exa, Jina | Web araması ve sayfa okuma |
| YouTube Data API, Apify | Konu bulma / viral içerik verisi |

### Kendi LTX Space'leriniz (isteğe bağlı)

Resmî `Lightricks/LTX-2-3` Space'inin kopyalarını kendi Hugging Face hesabınızda
çalıştırıyorsanız, `Ayarlar\ltx-spaceler.txt` dosyasına her satıra bir
`kullanici/space-adi` yazın ve erişim anahtarını `Ayarlar\ltx-space-erisim.txt` dosyasına
koyun. Bu dosyalar yoksa resmî Space kullanılır.

## Güvenlik

- `Ayarlar/` klasörünü, `api-hesaplari.txt` ve benzeri dosyaları **asla** depoya
  eklemeyin; `.gitignore` bunları zaten dışarıda bırakır.
- Sunucu yalnızca `127.0.0.1` üzerinden erişilebilir.

## Lisans

[MIT](LICENSE)
