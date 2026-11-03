"""Küçük metin/sayı yardımcıları: modüller arasında tekrar eden tek satırlıklar."""
import re


def ilk_satir(metin, sinir=160):
    """Metnin ilk satırı (kırpılmış). Hata mesajlarını tek satıra indirmek için.

    HTML etiketleri atılır: Hugging Face "No GPU" hatası bir `<a style=…>Subscribe to
    Pro</a>` bağlantısı taşır ve günlüğe, panele ham HTML olarak düşüyordu.
    """
    satir = re.sub(r"<[^<>]+>", "", str(metin or "")).strip().splitlines()
    return (satir[0] if satir else "").strip()[:sinir]


def tek_satir(metin, sinir=400):
    """Metni tek satıra indir: metin dosyasındaki alanlar satır satır okunur."""
    return re.sub(r"\s+", " ", str(metin or "")).strip()[:sinir]


def tek_satir_tam(metin):
    """Metni tek satıra indir ama **kısaltma**: uzunluğu bilgi taşıyan alanlar için.

    `proje.txt` projenin tek kaydıdır; prompt alanları oradan okunup üretime geri
    gider. Uzunluk sınırı koymak, kaldığı yerden devam eden projede modele kesik
    prompt göndermek demektir. Satır sonları yine boşluğa çevrilir: dosya biçimi
    `anahtar : değer` satırlarına dayanır.
    """
    return re.sub(r"\s+", " ", str(metin or "")).strip()


def negatif_birlestir(*parcalar):
    """Virgülle ayrılmış negatif prompt listelerini tek listede birleştir.

    Sıra korunur ve tekrarlar (büyük/küçük harf duyarsız) atılır: ilk gelen yazım
    kalır. Sıra bilinçlidir — çağıran, **kareye özgü** terimleri başa koyar; genel
    varsayılanlar sona gider. SDXL'in negatif prompt'u da CLIP'in 77 tokenlık
    penceresinden geçtiği için, sona düşen terimler modele ulaşmayabilir.
    """
    gorulen, sonuc = set(), []
    for parca in parcalar:
        for oge in str(parca or "").split(","):
            oge = " ".join(oge.split())
            if oge and oge.casefold() not in gorulen:
                gorulen.add(oge.casefold())
                sonuc.append(oge)
    return ", ".join(sonuc)


# Aynı görsel kavramı taşıyan kelime aileleri: pozitifte biri geçerken negatifte
# ailenin herhangi biri geçerse ikisi çatışır (bkz. `negatif_celiski_ayikla`).
KAVRAM_AILELERI = (
    frozenset({"fire", "fires", "flame", "flames", "flaming", "burn", "burns", "burning",
               "burnt", "blaze", "blazes", "blazing", "alight", "ablaze", "torch",
               "torches", "embers"}),
    frozenset({"smoke", "smoking", "smoky", "smoldering"}),
    frozenset({"snow", "snowy", "snowfall", "ice", "icy", "frost", "frozen"}),
    frozenset({"blood", "bloody", "bleeding", "wound", "wounded", "wounds"}),
    frozenset({"water", "river", "rivers", "sea", "lake", "flood", "waves"}),
    frozenset({"night", "nighttime", "moonlight", "moonlit"}),
    frozenset({"rain", "raining", "rainy", "storm"}),
)

# Negatif öğesinde çatışma ararken anlamı taşımayan dolgu kelimeleri.
_DOLGU = frozenset({"a", "an", "the", "of", "on", "in", "any", "animal", "animals",
                    "body", "bodies", "with", "and", "or", "no", "fur", "skin", "person",
                    "people", "visible", "scene", "background", "foreground"})


def _kelimeler(metin):
    return set(re.findall(r"[a-z]+", str(metin or "").casefold()))


def negatif_celiski_ayikla(pozitif, negatif):
    """Negatiften, pozitifte **istenen** bir şeyi bastıracak öğeleri çıkar.

    Ölçüldü (Timur 10. sahne, SDXL base, aynı prompt, 3 seed): pozitif "hay bundles
    blazing, fire solely on dry cargo" iken negatifte `burning animal, fire on animal
    body, burning fur` varken **3 seed'in 3'ünde de ateş yoktu**; yalnızca bu üç öğe
    çıkarılınca alev geri geldi. Negatif prompt "hayvanın üstünde ateş olmasın"
    ayrımını yapamaz: `burning` kavramını bütünüyle bastırır.

    Kural iki koldan biridir, ikisi de dar tutuldu:
    1. öğe, pozitifte geçen bir kelimeyle **aynı kavram ailesinden** (`KAVRAM_AILELERI`)
       bir kelime içeriyor (pozitif "blazing", negatif "burning fur" → atılır);
    2. öğe pozitifte **bitişik ifade olarak** geçiyor (negatif "camels", pozitif
       "baggage camels" → atılır).
    Kısmi ya da dağınık kelime eşleşmesi çatışma sayılmaz: pozitif "lamellar armor"
    varken "plate armor" meşru bir dönem yasağıdır; pozitifte "canvas tent walls" ve
    "natural skin texture" ayrı ayrı geçse de "canvas texture" (tablo dokusu yasağı)
    kalır — uçtan uca denemede bu yanlış eşleşme yakalandı. Dönüş:
    `(temiz liste, atılanlar)`.
    """
    # "no snow", "without smoke" istenen değil yasaklanan şeydir: pozitif sayılmaz.
    olumlu = re.sub(r"\b(?:no|without|never|not)\s+[a-z]+", " ", str(pozitif or "").casefold())
    poz = _kelimeler(olumlu)
    duz = " " + " ".join(re.findall(r"[a-z]+", olumlu)) + " "
    aileler = [aile for aile in KAVRAM_AILELERI if aile & poz]
    kalan, atilan = [], []
    for ham in str(negatif or "").split(","):
        oge = " ".join(ham.split())
        if not oge:
            continue
        kel = _kelimeler(oge) - _DOLGU
        ifade = " " + " ".join(re.findall(r"[a-z]+", oge.casefold())) + " "
        catisma = bool(kel) and (any(aile & kel for aile in aileler) or ifade in duz)
        (atilan if catisma else kalan).append(oge)
    return ", ".join(kalan), atilan


def _token_tahmini(oge):
    """Bir negatif prompt öğesinin **tahmini** CLIP token maliyeti (ayırıcı dâhil).

    Gerçek sayım modelin BPE sözlüğüne bağlıdır; burada yaklaşık ama **temkinli**
    bir tahmin yapılır: her kelime 1 token, uzun (9 harften fazla) kelime 2 token
    sayılır, sona bir ayırıcı eklenir. Tahmin fazla sayarsa listenin sonundan bir
    öğe daha düşer; eksik sayarsa sığdığını sandığımız öğe modelde kesilir — bu
    yüzden bilerek yukarı yuvarlanır.
    """
    return sum(2 if len(kelime) > 9 else 1 for kelime in oge.split()) + 1


def _oncelikli_mi(oge, anahtarlar):
    """Öğe öncelikli terimlerden birini içeriyor mu? **Kelime** düzeyinde bakılır.

    Alt dize araması yanlış eşleşme üretiyordu: "Roman armor" içindeki "armor",
    "arm" anahtarına takılıp dönem yasağını kalite terimlerinin arasına taşıyordu.
    Tek kelimelik anahtarlar kelimenin kendisiyle ya da basit çoğuluyla eşleşir
    ("hand" → "hands"), çok kelimeli anahtarlar ("low quality") alt dize aranır.
    """
    kucuk = oge.casefold()
    kelimeler = {kelime.strip(".,;:!?()[]\"'") for kelime in kucuk.split()}
    for anahtar in anahtarlar:
        if " " in anahtar:
            if anahtar in kucuk:
                return True
        elif kelimeler & {anahtar, anahtar + "s", anahtar + "es"}:
            return True
    return False


def negatif_duzenle(metin, oncelikli=(), sinir=75):
    """Negatif prompt listesini **önceliğe göre sırala ve token penceresine sığdır**.

    SDXL'in metin kodlayıcısı (CLIP) 77 tokenlık bir pencere kullanır: daha uzun bir
    negatif prompt'un sonu modele hiç ulaşmaz. Uzun listelerde kareyi asıl kurtaran
    terimler (bozuk el, fazla parmak, yazı/filigran) çoğu zaman sona yazıldığı için
    sessizce düşerdi.

    Yapılan iş üç adımdır ve **hiçbir terim eklenmez**:

    1. öğeler temizlenir ve tekrarlar atılır (büyük/küçük harf ve sondaki noktalama
       duyarsız: "watermarks" ile "watermarks." aynı sayılır),
    2. `oncelikli` anahtarlardan biriyle eşleşen öğeler başa alınır (kendi
       aralarındaki sıra korunur), kalanlar arkalarına dizilir,
    3. liste tahmini token bütçesi (`sinir`) dolana dek alınır, gerisi atılır.

    Böylece kullanıcının/yapay zekânın yazdığı liste aynı kalır, yalnızca modele
    **ulaşan** kısmı doğru terimlerden oluşur.
    """
    ogeler, gorulen = [], set()
    for ham in str(metin or "").split(","):
        oge = " ".join(ham.split()).strip(" .;")
        anahtar = oge.casefold()
        if oge and anahtar not in gorulen:
            gorulen.add(anahtar)
            ogeler.append(oge)
    if not ogeler:
        return ""
    anahtarlar = tuple(k.casefold() for k in oncelikli)
    onde = [oge for oge in ogeler if _oncelikli_mi(oge, anahtarlar)]
    arkada = [oge for oge in ogeler if oge not in onde]
    sonuc, toplam = [], 0
    for oge in onde + arkada:
        maliyet = _token_tahmini(oge)
        if toplam + maliyet > sinir:
            continue          # sığmayan öğeyi atla, daha kısa olan sonraki sığabilir
        sonuc.append(oge)
        toplam += maliyet
    return ", ".join(sonuc)


def stil_ekle(prompt, stil, sinir, *, sona=False):
    """Görsel stilini kareye **garantili** ekle; kelime bütçesini aşma.

    Stil yalnızca prompt'u yazan yapay zekânın onu tekrarlamasına bırakılıyordu.
    Ölçümde sahne başına stilin ortalama **%10'u** geçiyordu ve her sahnede başka
    parçası: kareler birbirinden kopuyor, `photorealistic` / `35mm` / `film still`
    gibi terimler hiçbir sahneye ulaşmadığı için model illüstrasyona kayıyordu.
    Prompt'lar 29–38 kelimeyken bütçe 55 olduğu için yer de boşta duruyordu.

    Stil prompt'un **başına** yazılır, sonuna değil. Bu kozmetik bir tercih değil,
    ölçümle bulundu: aynı kelimeler ve aynı seed ile stil sona eklendiğinde SDXL
    yağlı boya tablo üretti, başa alındığında fotoğraf üretti. CLIP'in 77 tokenlık
    penceresinde baştaki terimler çok daha ağır basıyor; sona eklenen
    `photorealistic` pratikte hiç okunmuyor.

    `sona=True` öznel kamera sahnelerinde bakış açısını ve beden sahipliğini
    önde tutar; yalnızca bütçeye sığan stil öğeleri sona eklenir.

    Zaten karede geçen stil öğesi tekrar eklenmez (anahtar sözcüklerinin tamamı
    prompt'ta varsa o öğe geçmiş sayılır). Bütçeye sığmayan öğe atlanır ve sıradaki
    daha kısa öğe denenir; böylece sahne içeriği asla kırpılmaz.
    """
    prompt = tek_satir_tam(prompt)
    parcalar = [p.strip() for p in str(stil or "").split(",") if p.strip()]
    if not parcalar:
        return prompt
    sayac = kelime_sayisi(prompt)
    mevcut = set(re.findall(r"[a-z0-9]+", prompt.lower()))
    onek = []
    for parca in parcalar:
        anahtar = [k for k in re.findall(r"[a-z0-9]+", parca.lower()) if len(k) > 3]
        if anahtar and all(k in mevcut for k in anahtar):
            continue
        ek = len(parca.split())
        if sayac + ek > sinir:
            continue
        onek.append(parca)
        sayac += ek
        mevcut.update(re.findall(r"[a-z0-9]+", parca.lower()))
    if not onek:
        return prompt
    # Öznel kamerada bedenin kime ait olduğu stil ayrıntılarından önce okunmalı.
    if sona:
        # Cümleyle biten prompt'a stil yeni cümle olarak eklenir ("frame., Photo…" olmaz).
        ayrac = " " if re.search(r"[.!?]$", prompt) else ", "
        return prompt + ayrac + ", ".join(onek)
    return ", ".join(onek) + ", " + prompt


def stil_ile_birlestir(prompt, stil, sinir, *, sona=False, stil_ayri=False):
    """Sahne içeriğine stili ekle ve modele gidecek son metni bütçeye oturt.

    `stil_ayri=False` (CLIP'li modeller): stil ve içerik aynı `sinir`ı paylaşır;
    sığmayan stil öğesi atlanır, sonra metin `sinir`a kırpılır (eski davranış).
    `stil_ayri=True` (uzun metin okuyan modeller): `sinir` yalnızca içeriğindir;
    içerik ona kırpılır ve stil **tamamı** üstüne eklenir.
    """
    if stil_ayri:
        icerik = kelime_kirp(prompt, sinir)
        return stil_ekle(icerik, stil, sinir + kelime_sayisi(stil), sona=sona)
    return kelime_kirp(stil_ekle(prompt, stil, sinir, sona=sona), sinir)


def kelime_kirp(metin, sinir):
    """Metni ilk `sinir` kelimeye indir (zaten kısaysa dokunmaz).

    Görsel modelinin okumadığı kuyruğu kayıtta tutmak yanıltıcı olurdu: `proje.txt`
    prompt'u modele **gerçekten giden** hâliyle göstermeli. Kelime sınırı kelime
    sınırında kesilir, cümle ortasında kalan kısım atılır.
    """
    kelimeler = [k for k in str(metin or "").split() if k]
    if sinir <= 0 or len(kelimeler) <= sinir:
        return " ".join(kelimeler)
    return " ".join(kelimeler[:sinir]).rstrip(",;:·-")


# Görsel modeli olumsuzluğu anlamaz, **adı geçeni çizer**: "my left hand remains
# outside the frame", "no hands visible" gibi cümleler eli kareye çağırıyordu
# (piramit, 28.09.2026: 12 sahnenin 4'ünde bu tür cümle vardı). FLUX negatif prompt
# da almadığı için yasaklar pozitif prompt'a cümle olarak sızıyordu. İki desen:
# kareden dışlama cümlesi **bütünüyle** atılır (öncesi de uzvu adlandırır);
# "no X / without X" gibi ek olumsuzlukta yalnızca olumsuzluktan sonrası atılır.
_DISLAMA = re.compile(
    r"\b(?:outside|out)\s+(?:of\s+)?(?:the\s+)?(?:frame|view|shot|image|picture)\b|"
    r"\bout\s+of\s+(?:frame|view|shot|sight)\b|"
    r"\b(?:remains?|stays?|kept|keep|is|are)\s+(?:\w+\s+)?(?:hidden|unseen|invisible|off[- ]?screen)\b|"
    r"\b(?:not|never)\s+(?:\w+\s+)?(?:visible|seen|shown|in\s+(?:the\s+)?frame)\b|"
    r"\bhidden\s+from\s+view\b|\boff[- ]?screen\b", re.I)
_OLUMSUZ = re.compile(r"\b(?:no|not|never|without|none|nobody|nothing|free\s+of|"
                      r"instead\s+of|rather\s+than)\b", re.I)
_BAGLAC_SONU = re.compile(r"(?:\s+\b(?:with|and|or|while|but|as|its|their|his|her|my|"
                          r"the|a|an|of|to|in|on|at|by|showing)\b)+\s*$", re.I)


def olumsuz_ayikla(prompt):
    """Görsel prompt'undan olumsuz/dışlayıcı ifadeleri at. Dönüş: `(temiz, atılanlar)`.

    Cümle `.;!?` ile, cümle de virgülle parçalara bölünür; karar parça düzeyinde
    verilir. Kareden dışlama bildiren parça ("hands remain outside the frame",
    "face not visible") tamamen atılır. Olumsuz sözcükle başlayan parça ("no snow")
    atılır; parçanın ortasındaki olumsuzlukta ("standing on dry earth without snow")
    olumsuzluktan öncesi korunur. Hiçbir sözcük eklenmez.
    """
    metin = " ".join(str(prompt or "").split())
    if not metin:
        return metin, []
    atilan, cumleler = [], []
    for cumle, ayrac in re.findall(r"([^.;!?]+)([.;!?]*)", metin):
        parcalar = []
        for parca in cumle.split(","):
            parca = parca.strip()
            if not parca:
                continue
            if _DISLAMA.search(parca):
                atilan.append(parca)
                continue
            eslesme = _OLUMSUZ.search(parca)
            if eslesme:
                once = _BAGLAC_SONU.sub("", parca[:eslesme.start()]).strip()
                atilan.append(parca[eslesme.start():].strip())
                if len(once.split()) < 2:
                    continue
                parca = once
            parcalar.append(parca)
        if parcalar:
            cumleler.append(", ".join(parcalar) + (ayrac.strip()[:1] or ""))
    return " ".join(cumleler).strip(), atilan


HEDEF_ORANI = 0.7


def hedef_kelime(sinir):
    """Yapay zekâya söylenen **hedef** kelime sayısı: sınırın ~%70'i.

    Dil modeli kelime sayamaz; "100'ün altında yaz" dendiğinde 90–157 kelime yazdı
    (piramit, test5) ve kod kuyruğu kesti. Hedef sınırın altında verilince taşan yanıt
    da sınıra yetişmez; sınır kodda güvenlik kesmesi olarak kalır.
    """
    return max(20, round(int(sinir) * HEDEF_ORANI))


def kelime_sayisi(metin):
    return len([k for k in (metin or "").split() if k.strip()])


def sayi(deger, varsayilan, tip=int):
    """Sayıya çevir; çevrilemiyorsa varsayılana düş."""
    try:
        return tip(deger)
    except (TypeError, ValueError):
        return varsayilan


def metin(deger, varsayilan=""):
    """Metne çevir ve kırp; boşsa varsayılana düş."""
    sonuc = str(deger).strip() if deger is not None else ""
    return sonuc or varsayilan


def evet(deger, varsayilan=True):
    """`açık`/`kapalı`, `evet`/`hayır`, 1/0 ve true/false değerlerini oku."""
    sonuc = str(deger or "").strip().lower()
    if not sonuc:
        return varsayilan
    if sonuc in ("açık", "acik", "evet", "1", "true", "yes", "on"):
        return True
    if sonuc in ("kapalı", "kapali", "hayır", "hayir", "0", "false", "no", "off"):
        return False
    return varsayilan


def sinirla(deger, alt, ust, varsayilan, tip=float):
    """Değeri aralığa kırp; okunamayan/boş değerde varsayılana düş."""
    try:
        return max(alt, min(ust, tip(deger)))
    except (TypeError, ValueError):
        return varsayilan


def kirp(deger, alt, ust):
    """Değeri aralığa kırp; sayı okunamazsa alt sınıra düş."""
    try:
        deger = float(deger)
    except (TypeError, ValueError):
        return float(alt)
    return max(float(alt), min(float(ust), deger))


def temiz(deger):
    """Metinden okunan alanı boş/tire ise boş metne çevir."""
    sonuc = str(deger or "").strip()
    return "" if sonuc in ("-", "—") else sonuc


def numara(deger):
    """Ondalık sayıyı Türkçe biçimde tek haneyle yaz: 2.5 → `2,5`."""
    return f"{float(deger):.1f}".replace(".", ",")
