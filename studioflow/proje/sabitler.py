"""Proje sabitleri: süreler, dosya adları, deneme kuralları, servis adları."""

from studioflow.saglayicilar import video_huggingface

# Adım süresi bir ayardır (`video.adim_saniye`): kullanıcının seçtiği **tavan**.
# Buradaki değer yeni projelerin varsayılanı ve eski projeleri okuma değeridir.
ADIM_SANIYE = 6.0


# Bir **sahnenin** alabileceği süre aralığı. Space teknik olarak 0,5 saniyelik klip de
# üretebiliyor (`video_huggingface.SURE_ALT`) ama yarım saniyelik kesit videoda göz
# kırpması gibi geçiyor, sahne olarak okunmuyor; bu yüzden taban 1 saniyeye çekildi.
# Tavan burada teknik sınırdır: gerçek tavanı kullanıcı seçer (`SAHNE_TAVAN_ARALIGI`).
SAHNE_SURE_ALT = 1.0

# Bir sahnenin (dolayısıyla videonun) **en uzun** süresi: 8 sn (kullanıcı kararı,
# 20.10.2026). LTX-2.3 tek seferde en fazla 8 sn üretir; 9,6 sn'lik sahnede son 1,6 sn
# son kare dondurulmuş, video "takılmış" görünmüştü (Gambusia, adım 1). Bütün video
# servisleri için aynı tavan geçerlidir.
SAHNE_SURE_UST = 8.0

SURE_SINIRLARI = (SAHNE_SURE_ALT, min(SAHNE_SURE_UST, video_huggingface.SURE_UST))


# Kullanıcının **tavanı seçebileceği** aralık ("Adım süresi · üst sınır" kaydırıcısı).
# Sahne süresi tavanı videoya göre değişir: 6 saniyeyi aşan kesitlerde tek görselden
# üretilen klipte hareket tükenip kare donuklaşıyor, ama bu her videoda aynı değil.
# Bu yüzden tavan sabitlenmedi, **seçime** bırakıldı; 5'in altı bir tavan ise sahneleri
# gereksiz parçaladığı için aralığın dışında tutuldu.
SAHNE_TAVAN_ARALIGI = (5.0, SAHNE_SURE_UST)


ADIM_SINIRLARI = (video_huggingface.ADIM_ALT, video_huggingface.ADIM_UST)


# Kancanın sahnesi: elle yazılan ilk sahne içeriği yalnızca bu adıma uygulanır.
# `adim_promptlari` ile `prompt_uretimi` ikisi de kullanıyor, biri diğerini içe
# aktaramadığı için (döngü) sabit burada durur.
ILK_SAHNE_INDEX = 1


VARSAYILAN_NEGATIF = ("blurry, low quality, watermark, text, signature, deformed hands, "
                      "extra fingers, extra limbs, distorted face")


# Negatif prompt'ta **önce** modele ulaşması gereken terimlerin anahtar sözcükleri.
# SDXL'in metin penceresi 77 token: uzun bir negatif listesinin sonu modele hiç
# ulaşmaz (bkz. `metin.negatif_duzenle`). Kareyi asıl kurtaran terimler — bozuk el ve
# yüz, fazla uzuv, yazı/filigran/altyazı — çoğu zaman listenin sonuna yazıldığı için
# sessizce düşüyordu. Bu anahtarlardan birini içeren öğeler listenin başına alınır;
# dünya/dönem yasakları (ör. "Roman armor") arkalarına dizilir ve bütçe biterse
# oradan kırpılır: anakronik bir nesne, bozuk bir elden daha az göze batar.
NEGATIF_ONCELIK = (
    "hand", "finger", "limb", "arm", "leg", "face", "eye", "anatomy", "deformed",
    "distorted", "disfigured", "mutated", "malformed", "extra", "blurry", "blurred",
    "low quality", "worst quality", "lowres", "jpeg", "artifact", "watermark",
    "signature", "logo", "text", "caption", "subtitle", "letter", "writing",
)


# ── görsel prompt'unun kelime sınırı ────────────────────────────────────────
# Görsel modelinin metin kodlayıcısı (CLIP) 77 token alır; pratikte **~55 kelimeden**
# sonrası modele hiç ulaşmaz. Ölçüm (aynı seed, SDXL base): prompt'un sonuna konan
# ayırt edici bir nesne 27 kelimede kareye giriyor, 68 kelimede hiç çıkmıyor; aynı
# nesne başa alındığında 104 kelimede bile çıkıyor. Bu yüzden prompt yazan yapay
# zekâya sınır **söylenir** ve yanıt **denetlenir** (bkz. `adim_promptlari`), elle
# yazılan ilk sahne prompt'unda da arayüz canlı uyarı verir.
PROMPT_KELIME_SINIRI = 55


# ── görsel denetimi ─────────────────────────────────────────────────────────
# Her kare üretildikten sonra görsel hakem (bkz. `saglayicilar.gorsel_denetim`) kareyi
# sahnenin denetim listesine göre okur; geçmezse kare **düzeltilmiş prompt'la**
# yeniden üretilir. `GORSEL_DENETIM_DENEME` bir karenin toplam üretim hakkıdır
# (ilk kare dâhil); en iyi puanlı kare tutulur. 3 hak × 14 sahne FLUX.2 klein 4B'de en
# kötü durumda ~4.400 + hakem ~1.500 nöron eder: günlük ücretsiz 10.000 nöronun içinde.
GORSEL_DENETIM_DENEME = 3
# Yazı denetimi (bkz. `akis_kare.yazisiz_kare`): karede yazı çıkarsa toplam üretim
# hakkı. Hak bitince kare tutulur ama videosu kilitlenir; yazılı kare kabul edilmez.
YAZI_DENEME = 3
GORSEL_DENETIM_ARALIGI = (1, 5)
# Anlatım hızının (dakikada kelime) alt uyarı sınırı; olağan anlatım 130–160. Altında
# kalırsa ses metin dışında bir şey okumuş ya da uzun duraklamalar yapmış olabilir.
SES_HIZ_ALT_SINIRI = 95


# Seslendirme üslubu (ses.stil) — görsel stiliyle karıştırılmasın.
VARSAYILAN_STIL = "Natural, warm documentary narration with varied emphasis and a relaxed pace."


# Görsel stil katmanı (video.stil). Ölçümle seçildi (bkz. docs/STIL-PROMPT-KILAVUZU.md):
# SDXL tarihî/anlatısal konularda **varsayılan olarak yağlı boya tablo** üretiyor —
# stil hiç verilmediğinde imzalı tablo bile çıkıyor. Fotoğraf görünümünü bu dört terim
# sağladı: `Photorealistic` (ortamı belirler), `film still` (sinema karesi),
# `shot on 35mm film` (gerçek kamera), `sharp focus` + `natural skin texture`
# (yumuşatma ve plastik cilt eğilimini keser). Biçimden bağımsızdır: dikey/yatay
# ipucu içermez, onu çıktı biçimi belirler. 15 kelime — 55 kelimelik bütçenin
# geri kalanı sahne içeriğine kalır.
VARSAYILAN_GORSEL_STIL = ("Photorealistic film still, shot on 35mm film, sharp focus, "
                          "natural skin texture, available light, high detail")


GUNLUK_SINIR = 120


DOSYA_ADI = "proje.txt"


# ---------------------------------------------- çok dilli ses · ham video
# Sesi ve altyazısı olmayan video **ham video** olarak ayrı tutulur. Bir dil eklenirken
# `proje.mp4` her zaman bu dosyadan yeniden kurulur; böylece üst üste eklenen dillerin
# sesleri birbirine karışmaz ve "ham videoya geri dön" videoyu ilk hâline çevirir.
HAM_VIDEO_ADI = "proje-ham.mp4"


DIL_KLASORU = "diller"       # `ses/` altında: seslendirme-<dil>.wav · .srt · metin-<dil>.txt


# ------------------------------------------------------ dublaj · kayıtlı dil sesleri
# Dublajlar da müzikler gibi **kaydedilir ve listelenir**: üretilen her dil sesi
# `ses/diller/dublajlar.json` listesine yazılır (ad, dil, servis, ses, süre, altyazı).
# Dosya adı `seslendirme-<ad>.wav`tır ve ad yazılmazsa dil kodudur, yani tek dilli
# eski projelerin dosya adları (`seslendirme-en.wav`) aynen korunur. Videoya eklemek
# **üretim sayfasındaki** dublaj panelindedir; bu liste yalnızca kaydı tutar.
DUBLAJ_LISTE_ADI = "dublajlar.json"


# ---------------------------------------------------- altyazı · kayıtlı altyazılar
# Altyazı artık dublaja iliştirilmiş bir kutucuk değil, **kendi başına kaydedilen**
# bir parçadır: her dil için ayrı altyazı kaydedilir (`altyazi/<ad>.srt`) ve liste
# `altyazi/altyazilar.json`da durur. Videoya gömmek üretim sayfasındaki altyazı
# panelindedir; burada yalnızca kayıt tutulur.
ALTYAZI_KLASORU = "altyazi"


ALTYAZI_LISTE_ADI = "altyazilar.json"


# ------------------------------------------------------ müzik · proje müzikleri
# Kullanıcı **birden fazla** müzik yükleyebilir: her müziği kırpar, ses seviyesini
# ayarlar ve **kaydeder**. Kaydedilen dosya (`muzik/<ad>.m4a`) kırpılmış ve seviyesi
# uygulanmış **son hâlidir**; yüklenen kaynak dosya `muzik/kaynak/` altında saklanır,
# böylece aynı adla yeniden kaydetmek müziği üst üste kısmadan günceller. Liste
# `muzik/parcalar.json`da tutulur (kayıt sırası, seçim ve tekrar tercihi); videoya
# eklenen karışım `proje.txt`e yazılır.
#
# Videoya ekleme: `proje.mp4`ün **görüntüsü kopyalanır** (gömülü altyazı korunur),
# yalnızca ses akışı baştan kurulur: anlatım/ekli dil (varsa) + işaretlenen müziklerin
# **işaretleme sırasıyla** karışımı. Böylece üst üste eklemek sesleri katlamaz ve aynı
# yol "Müziği kaldır" için de kullanılır (müzik katmanı boş kalır).
MUZIK_KLASORU = "muzik"


MUZIK_LISTE_ADI = "parcalar.json"


MUZIK_KAYNAK_KLASORU = "kaynak"   # `muzik/` altında: yüklenen kaynak dosyalar


# Ses seviyesi yüzdesi: 100 = dosyanın kendi seviyesi. Anlatım varsa müziğin altında
# kalması için varsayılan düşük tutulur (videoya eklerken yeniden ayar gerekmez):
# **%10**, yani müzik anlatımın belirgin biçimde altında bir fon olarak girer.
# Kullanıcı kaydırıcıdan yükseltebilir; kayıtlı müziklerin kendi seviyesi dosyaya
# işlendiği için bu değer yalnızca **yeni** kayıtların başlangıcıdır.
MUZIK_SEVIYE_SINIR = (0, 200)


MUZIK_VARSAYILAN_SEVIYE = 10


# Seslendirme (anlatım/dublaj) ses seviyesi yüzdesi: 100 = ses dosyasının kendi
# seviyesi. TTS çıktısı (özellikle Gemini) çoğu zaman kısık gelir; kaydırıcı sesi
# videoya eklerken **%400'e kadar** yükseltir. Seviye ses dosyasına işlenmez, her
# eklemede dosyadan yeniden uygulanır; bu yüzden üst üste yükseltme olmaz. 100'ün
# üstünde tepe noktaları kırpılmasın diye sona yumuşak sınırlayıcı eklenir.
SES_SEVIYE_SINIR = (25, 400)


SES_VARSAYILAN_SEVIYE = 100


# Ducking (anlatım altında otomatik kısma): anlatım konuşurken müzik kendiliğinden
# kısılır, konuşma susunca geri yükselir. `amix` seviyeleri olduğu gibi karıştırdığı
# için, ducking olmadan müziğin anlatımın altında kalması yalnızca kullanıcının
# seçtiği seviyeye bağlıydı. Kapalıyken eski davranış (düz karışım) aynen korunur.
MUZIK_VARSAYILAN_DUCKING = True


# `sidechaincompress` ayarları: anlatım yan-zincir (sidechain) anahtarıdır.
#   esik   0,03 ≈ −30 dBFS · ffmpeg varsayılanı 0,125 (−18 dB) anlatımın çoğunu
#          kaçırırdı; TTS anlatımı bu seviyenin altında konuşur.
#   oran   8    · eşiğin ~10 dB üstündeki konuşmada ~9 dB kısma: müzik duyulmaya
#          devam eder ama anlatımın altına iner.
#   atak   20 ms · müzik ilk hecede iner; daha hızlısı tıklama üretir.
#   birak  350 ms · cümle bitince ~1/3 saniyede geri gelir. Kısası kelimeler arasında
#          pompalar, uzunu doğal duraklarda müziği bastırır.
#   telafi 1    · telafi kazancı yok (amaç kısmak, geri yükseltmek değil).
MUZIK_DUCKING_ESIK = 0.03
MUZIK_DUCKING_ORAN = 8
MUZIK_DUCKING_ATAK = 20
MUZIK_DUCKING_BIRAKMA = 350


MUZIK_VARSAYILAN_SINIR = 600.0     # süresi okunamayan dosyada kırpma kaydırıcısı sınırı


# Karartma (fade): müziğin başında ses 0'dan yükselir, sonunda yavaş yavaş 0'a iner.
# Kırpma ve seviyeden farklı olarak **dosyaya işlenmez**; videoya eklenirken uygulanır.
# Böylece müzik videoda erken kesiliyorsa karartma tam kesildiği yere oturur: ses
# video sonunda sıfıra iner (bkz. `_muzik_bed`). Süreler müziğin uzunluğuna göre
# kırpılır; 0 = karartma yok.
MUZIK_KARARTMA_SINIR = (0.0, 10.0)


MUZIK_VARSAYILAN_KARARTMA = 0.0


# Ses efektleri: her sahneye Freesound'dan **CC0** (atıfsız, ticari kullanım serbest)
# sesler bulunur ve videonun zaman çizelgesine hizalı **tek bir efekt izine** işlenir
# (`efektler/<ad>.wav`). Kayıtlar `efektler.json`dadır; videoda hangi kaydın olduğu
# (`ekli`) ve efekt seviyesi de oradadır — `proje.txt` biçimine dokunulmaz.
EFEKT_KLASORU = "efektler"


EFEKT_LISTE_ADI = "efektler.json"


EFEKT_KAYNAK_KLASORU = "kaynak"    # `efektler/` altında: indirilen Freesound sesleri


# Efekt seviyesi (%): 100 = izin kendi seviyesi. İz, anlatımın altında duyulacak
# biçimde kurulur (ortam −34, eylem −26 dBFS RMS); seviye videoya eklenirken uygulanır,
# bu yüzden değiştirmek için efektleri yeniden hazırlamak gerekmez.
EFEKT_SEVIYE_SINIR = (0, 300)


EFEKT_VARSAYILAN_SEVIYE = 100


# Sahne başına en fazla katman (ör. bir ortam sesi + iki eylem sesi).
EFEKT_KATMAN_SINIRI = 3


# Katman türüne göre hedef seviye (dBFS RMS, sahne süresi boyunca).
EFEKT_KATMAN_DB = {"ortam": -34.0, "eylem": -26.0}


# Anlatımı hedef dile çeviren yapay zekâ isteğinin sistem mesajı.
COK_DIL_CEVIRI_SISTEM = (
    "You are a professional audiovisual translator and dubbing scriptwriter. "
    "Translate the narration into the target language so it can be read aloud: keep the "
    "meaning, tone and pacing, keep numbers and units in a speakable form, keep proper "
    "names, and use natural punctuation for speech. "
    "Never add commentary, notes, quotes, stage directions, speaker labels or markup. "
    "Reply ONLY with the translated narration text."
)


# ------------------------------------ hata sonrası otomatik yeniden başlatma
# Bir işlem (seslendirme · prompt · görsel · video) hata verdiğinde akış kullanıcıyı
# beklemez: **aynı işlem** kendiliğinden yeniden başlatılır. Koruma kuralları:
#
#   · Deneme hakkı işlem başına `YENIDEN_SINIR` tanedir ve bu sayaç `proje.txt`'e
#     yazılır: uygulama kapansa da hak kendiliğinden yenilenmez.
#   · Sorunsuz biten bir deneme sayacı **sıfırlar**. Yani başarılı bir yeniden
#     başlatma korumayı devreye sokmaz; akış kaldığı yerden kendiliğinden sürer ve
#     sonraki işlemler kendi üç deneme hakkıyla başlar.
#   · Kullanıcı **Durdur**'a bastıysa hiç yeniden denenmez.
#   · Hak dolduğunda hata metne yazılır ve proje durur; **Deneme hakkını yenile**
#     düğmesi (ya da `Deneme` satırını `0/3` yapmak) sayacı açar.
YENIDEN_SINIR = 3


# Denemeler arasında beklenecek saniye. Hemen üst üste denemek yerine kotanın
# yenilenmesi ve uykudaki Space'lerin ayağa kalkması için kısa bir fırsat bırakılır;
# bekleme sırasında **Durdur** yine çalışır.
YENIDEN_BEKLEME = (5.0, 15.0)

# Bir hizmetin bütün hesapları yalnızca **dakikalık** hız sınırındaysa (429, ama günlük
# kota değil) turlar arası beklemeler (sn). Kota bitmediği için hesap elenmez; beklenip
# aynı hesaplar yeniden denenir. Tur sayısı bu demetin uzunluğu kadardır.
HIZ_BEKLEMELERI = (60.0, 120.0, 180.0)


# İşlem adlarının proje.txt'te görünen karşılıkları: `Deneme` satırı bunları kullanır.
DENEME_ADI = {"ses": "seslendirme", "prompt": "prompt", "gorsel": "görsel", "video": "video"}


DENEME_ISLEM = {ad: islem for islem, ad in DENEME_ADI.items()}


# Sayaçların projede mi adımda mı tutulduğu: seslendirme ve prompt proje düzeyindedir,
# görsel ve video üretimi adıma bağlıdır (adımın kendi satırına yazılır).
ADIM_DENEMELERI = ("gorsel", "video")


PROJE_DENEMELERI = ("ses", "prompt")


NASIL_OKUNUR = (
    "Bu dosya projenin tek kaydıdır: uygulama kaldığı yeri buradan bulur.",
    "Her bölüm bir ADIM'dır (süresi başlıktaki `başlangıç–bitiş` aralığında yazar; sahne",
    "süreleri anlatımın içeriğine göre değişir) ve şu",
    "durumlardan birini taşır:",
    "  BEKLİYOR · henüz üretilmedi",
    "  YARIM    · görsel var, video yok → adım baştan üretilir",
    "  TAMAM    · görsel ve video hazır; dosya adları alanlarında yazar",
    "  HATA     · sebebi Hata satırında yazar; adım baştan üretilir",
    "Bir adımın durumunu elle BEKLİYOR yaparsan o adım baştan üretilir, TAMAM",
    "yaparsan atlanır. AYARLAR satırlarını değiştirirsen yalnızca kalan adımlar",
    "yeni ayarla üretilir. Alan satırlarını silme: uygulama her şeyi buradan okur.",
    "",
    "Hata sonrası otomatik yeniden başlatma: bir işlem (seslendirme, prompt, görsel,",
    "video) hata verdiğinde akış kullanıcıyı beklemez; **aynı işlem** en fazla 3 kez",
    "kendiliğinden yeniden denenir. Denemelerden biri sorunsuz biterse akış kaldığı",
    "yerden sürer ve o işlemin deneme sayacı sıfırlanır. Üç deneme de hata verirse",
    "hata bu dosyaya yazılır ve proje durur.",
    "Deneme sayaçları `Deneme` satırlarındadır: başlıkta seslendirme ve prompt,",
    "ADIM bloklarında görsel ve video (`Deneme       : görsel 1/3 · video 2/3`).",
    "Hakkı elle yenilemek için sayıyı `0/3` yap; arayüzdeki **Deneme hakkını yenile**",
    "düğmesi de aynı işi yapar.",
    "",
    "Prompt yapay zekâsı yedeği: prompt'ları yazan servis (ör. Gemini) kota, yetki ya da",
    "model hatası verirse akış durmaz; **anahtarı kayıtlı sıradaki servise** (ChatGPT,",
    "Claude) kendiliğinden geçilir. Geçişler günlüğe yazılır ve prompt dosyasında hangi",
    "servisin yazdığı görünür. Anahtarı kayıtlı yedek yoksa davranış eskisi gibidir:",
    "hata bu dosyaya yazılır ve proje durur.",
)
