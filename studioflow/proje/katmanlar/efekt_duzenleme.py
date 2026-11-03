"""Ses efektlerini elle, sahne sahne düzenle: dinle · değiştir · sil · ekle · ayarla.

Bir efekt kaydı (`efektler.json` › `kayitlar`) sahne başına katmanlar taşır; her katman
bir Freesound sesidir (`id`) ve `tur` (ortam/eylem), sahne içi başlangıç (`bas`) ve
kazanç (`kazanc`, dB) bilgisi vardır. Buradaki her işlem kaydı değiştirir ve efekt
izini **kayıttan baştan kurar** (`efektler.kayittan_iz_kur`): indirilmiş sesler
`efektler/kaynak/`tan okunur, eksik olan Freesound'dan yeniden alınır. İz kurulunca her
sahnenin kendi parçası ayrı WAV olarak yazılır (paneldeki "sahneyi dinle").

Kayıt videoya gömülüyse (`ekli`) videonun sesi de hemen tazelenir; böylece düzenleme
ile video birbirini tutar. Seçimi burada yapay zekâ değil **kullanıcının kulağı**
yapar: arama adayları dinlenir, beğenilen "Bunu kullan" ile katmana konur.
"""
import json
import time

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir, sayi as _sayi
from studioflow.proje.katmanlar import efektler
from studioflow.proje.katmanlar.efekt_hazirlama import adaylari_topla
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.json_yardim import json_nesnesi
from studioflow.proje.ilerleme import arayuz_paketi, bos_ilerleme_html
from studioflow.proje.katmanlar.muzik import ses_katmanini_kur
from studioflow.proje.sabitler import EFEKT_KATMAN_SINIRI
from studioflow.saglayicilar.efekt_freesound import FreesoundEfekt, FreesoundHatasi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR

ARAMA_ADET = 8
TUR_ADLARI = {"ortam": "ortam (sahne boyunca)", "eylem": "eylem (belirli an)"}


def _hedef(ad):
    return proje_hedefi(ad, "ses efektini düzenle",
                        "Ses efektini düzenlemek için önce bir proje aç.")


def _kayit(klasor, isim):
    isim = efektler.efekt_adi(isim)
    durum = efektler.efekt_durumu_oku(klasor)
    return durum, next((k for k in durum["kayitlar"] if k["ad"] == isim), None)


def duzenleme_sahneleri(ad, isim):
    """Panel için sahneler: zaman çizelgesi + kayıttaki katmanlar + dinleme dosyaları.

    Kayıtta hiç katmanı olmayan sahneler de listelenir (efektsiz kalan sahneye ses
    eklenebilsin). Dönüş: `(sahneler, mesaj)`; her sahne `{"index", "bas", "sure",
    "metin", "istek", "katmanlar": [...], "bulunamayan": [...], "onizleme": yol|None}`,
    her katmanın `"dosya"` alanı dinlenecek yerel sestir (yoksa önizleme adresi).
    """
    veri, klasor, hata = _hedef(ad)
    if hata:
        return [], hata
    durum, kayit = _kayit(klasor, isim)
    if kayit is None:
        return [], "Düzenlemek için bir efekt kaydı seç."
    kayittaki = {int(_sayi(s.get("index"), 0)): s for s in kayit["sahneler"]}
    sahneler = []
    for sahne in efektler.efekt_sahneleri(veri, klasor):
        eski = kayittaki.get(sahne["index"], {})
        katmanlar = []
        for sira, katman in enumerate(eski.get("katmanlar") or [], 1):
            yol = efektler.kaynak_yolu(klasor, katman["id"])
            katmanlar.append({**katman, "sira": sira,
                              "kazanc": efektler.kazanc(katman.get("kazanc")),
                              "dosya": str(yol) if yol.is_file() else
                              (katman.get("onizleme") or None)})
        onizleme = efektler.sahne_onizleme_yolu(klasor, kayit["ad"], sahne["index"])
        sahneler.append({**sahne, "istek": eski.get("istek") or "",
                         "katmanlar": katmanlar,
                         "bulunamayan": eski.get("bulunamayan") or [],
                         "onizleme": str(onizleme) if onizleme.is_file() else None})
    return sahneler, ""


def _paket(veri, mesaj):
    """Düzenleme panelinin çıktı paketi: durum, düzenleme damgası, liste damgası +
    proje görünümü (video değişmiş olabilir)."""
    damga = f"{time.time():.6f}"
    return (mesaj, damga, damga) + arayuz_paketi(veri, mesaj)[1:]


def _bos(mesaj):
    return (mesaj, "", "", "", [], [], None, bos_ilerleme_html())


def _getirici(freesound):
    """Eksik sesi indiren işlev: önizleme adresi kayıtta yoksa kimlikten bulunur."""
    def getir(katman):
        aday = {"id": katman["id"], "onizleme": katman.get("onizleme") or ""}
        if not aday["onizleme"]:
            bilgi = freesound.bilgi(katman["id"])
            if bilgi is None:
                raise FreesoundHatasi(f"#{katman['id']} artık CC0 değil ya da silinmiş.")
            aday["onizleme"] = katman["onizleme"] = bilgi["onizleme"]
        return freesound.indir(aday, katman["_hedef"])
    return getir


def yeniden_kur(veri, klasor, kayit, freesound=None):
    """Kaydın izini baştan kur, sahne dinlemelerini yaz, kaydı sakla; videodaysa
    videonun sesini tazele. Dönüş: ek not (boş = sorun yok)."""
    freesound = freesound or FreesoundEfekt()
    sahneler = efektler.efekt_sahneleri(veri, klasor)
    for sahne in kayit["sahneler"]:
        for katman in sahne.get("katmanlar") or []:
            katman["_hedef"] = str(efektler.kaynak_yolu(klasor, katman["id"]))
    getir = _getirici(freesound) if freesound.anahtar_var_mi() else None
    try:
        iz, toplam, eksikler = efektler.kayittan_iz_kur(klasor, kayit, sahneler, getir)
    finally:
        for sahne in kayit["sahneler"]:
            for katman in sahne.get("katmanlar") or []:
                katman.pop("_hedef", None)
    efektler.iz_yaz(iz, klasor / kayit["dosya"])
    efektler.sahne_onizlemelerini_yaz(klasor, kayit["ad"], iz, sahneler)
    kayit["sure"] = round(toplam, 3)
    durum = efektler.efekt_durumu_oku(klasor)
    adlar = [k["ad"] for k in durum["kayitlar"]]
    if kayit["ad"] in adlar:
        durum["kayitlar"][adlar.index(kayit["ad"])] = kayit
    else:
        durum["kayitlar"].append(kayit)
    efektler.efekt_durumu_yaz(klasor, durum)
    notlar = []
    if eksikler:
        notlar.append("⚠ Bulunamayan ses dosyaları atlandı: " + ", ".join(eksikler) + ".")
    if durum["ekli"] == kayit["ad"] and (klasor / "proje.mp4").is_file():
        ok, mesaj = ses_katmanini_kur(veri, klasor)
        notlar.append("Kayıt videoda olduğu için videonun sesi de tazelendi." if ok else
                      "Video sesi tazelenemedi: " + _ilk_satir(mesaj, 160))
    return " ".join(notlar)


def _duzenle(ad, isim, islem, freesound=None):
    """Ortak kalıp: kaydı bul → `islem(kayit)` (mesaj ya da hata döner) → izi kur."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return _bos(hata)
    _durum, kayit = _kayit(klasor, isim)
    if kayit is None:
        return _paket(veri, "Düzenlemek için bir efekt kaydı seç.")
    sonuc = islem(kayit)
    if sonuc.startswith("!"):
        return _paket(veri, sonuc[1:])
    try:
        ek = yeniden_kur(veri, klasor, kayit, freesound)
    except (OSError, ValueError, FreesoundHatasi) as exc:
        return _paket(veri, "Efekt izi yeniden kurulamadı: " + _ilk_satir(exc, 200))
    return _paket(veri, (sonuc + " " + ek).strip())


def duzenlemeyi_ac(ad, isim):
    """Düzenleyiciyi aç: sahne dinleme dosyaları yoksa (eski kayıt) iz bir kez yeniden
    kurulur; kaydın kendisi değişmez."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return _bos(hata)
    _durum, kayit = _kayit(klasor, isim)
    if kayit is None:
        return _paket(veri, "Düzenlemek için bir efekt kaydı seç.")
    if any(efektler.onizleme_klasoru(klasor, kayit["ad"]).glob("sahne-*.wav")):
        return _paket(veri, f"'{kayit['ad']}' düzenleniyor: sahneyi ya da tek tek sesleri "
                            "dinle, değiştir, sil ya da ekle.")
    return _duzenle(ad, isim, lambda _k: f"'{kayit['ad']}' düzenleniyor: sahne dinlemeleri "
                                        "hazırlandı.")


def _sahne(kayit, index, olustur=False):
    index = int(_sayi(index, 0))
    for sahne in kayit["sahneler"]:
        if int(_sayi(sahne.get("index"), 0)) == index:
            return sahne
    if not olustur:
        return None
    sahne = {"index": index, "istek": "", "katmanlar": [], "bulunamayan": []}
    kayit["sahneler"].append(sahne)
    kayit["sahneler"].sort(key=lambda s: int(_sayi(s.get("index"), 0)))
    return sahne


def katman_sil(ad, isim, index, sira):
    """Sahnenin `sira`. sesini kaydan çıkar."""
    def islem(kayit):
        sahne = _sahne(kayit, index)
        sira_ = int(_sayi(sira, 0))
        if sahne is None or not 1 <= sira_ <= len(sahne.get("katmanlar") or []):
            return "!Silinecek ses bulunamadı; listeyi yenile."
        katman = sahne["katmanlar"].pop(sira_ - 1)
        return f"Sahne {index}: '{katman.get('etiket') or katman.get('ad')}' kaldırıldı."
    return _duzenle(ad, isim, islem)


def katman_ayarla(ad, isim, index, sira, kazanc_db, bas):
    """Sesin seviyesini (dB) ve sahne içi başlangıcını değiştir."""
    def islem(kayit):
        sahne = _sahne(kayit, index)
        sira_ = int(_sayi(sira, 0))
        if sahne is None or not 1 <= sira_ <= len(sahne.get("katmanlar") or []):
            return "!Ayarlanacak ses bulunamadı; listeyi yenile."
        katman = sahne["katmanlar"][sira_ - 1]
        katman["kazanc"] = efektler.kazanc(kazanc_db)
        if katman.get("tur") != "ortam":
            katman["bas"] = round(max(0.0, _sayi(bas, 0.0, float)), 2)
        return (f"Sahne {index}: '{katman.get('etiket') or katman.get('ad')}' → "
                f"{katman['kazanc']:+g} dB" + (f", {katman['bas']:g} sn'de başlar"
                                               if katman.get("tur") != "ortam" else "") + ".")
    return _duzenle(ad, isim, islem)


def katman_koy(ad, isim, index, sira, aday, tur="eylem", bas=0.0, etiket=""):
    """Adayı sahneye koy: `sira` > 0 ise o sesin **yerine**, 0 ise **yeni** ses olarak."""
    def islem(kayit):
        if not isinstance(aday, dict) or not aday.get("id"):
            return "!Önce aramadan bir ses seç."
        sahne = _sahne(kayit, index, olustur=True)
        sahne.setdefault("katmanlar", [])
        sira_ = int(_sayi(sira, 0))
        tur_ = tur if tur in efektler.EFEKT_KATMAN_DB else "eylem"
        yeni = {"tur": tur_, "etiket": " ".join(str(etiket or aday.get("ad") or "").split())[:60],
                "sorgu": aday.get("sorgu") or "", "bas": 0.0 if tur_ == "ortam" else
                round(max(0.0, _sayi(bas, 0.0, float)), 2), "id": int(aday["id"]),
                "ad": aday.get("ad") or "", "sahip": aday.get("sahip") or "",
                "url": aday.get("url") or "", "onizleme": aday.get("onizleme") or "",
                "kazanc": 0.0}
        if 1 <= sira_ <= len(sahne["katmanlar"]):
            eski = sahne["katmanlar"][sira_ - 1]
            yeni["kazanc"] = efektler.kazanc(eski.get("kazanc"))
            sahne["katmanlar"][sira_ - 1] = yeni
            return f"Sahne {index}: '{eski.get('etiket') or eski.get('ad')}' → '{yeni['ad']}'."
        if len(sahne["katmanlar"]) >= EFEKT_KATMAN_SINIRI + 2:
            return f"!Sahne {index} dolu: bir sahneye en fazla {EFEKT_KATMAN_SINIRI + 2} ses."
        sahne["katmanlar"].append(yeni)
        sahne["bulunamayan"] = []
        return f"Sahne {index}: '{yeni['ad']}' eklendi ({tur_})."
    return _duzenle(ad, isim, islem)


CEVIRI_SISTEM = ("Translate the user's sound effect description into 2-3 plain English "
                 "words the way sound libraries name files (e.g. 'footsteps sand', 'rope "
                 "snap'). Answer with the words only.")


def _ingilizceye_cevir(veri, sorgu):
    """Türkçe aramayı Freesound'a uygun İngilizce kelimelere çevir (projenin yapay
    zekâsı, en iyi model); çevrilemezse boş metin."""
    servis = ((veri.get("ayarlar") or {}).get("video") or {}).get("ai")
    try:
        cevap = HesapliMetin(servis if servis in AI_SAGLAYICILAR else "gemini").metin(
            CEVIRI_SISTEM, sorgu, json_modu=False)
    except Exception:
        return ""
    return " ".join(str(cevap or "").replace('"', " ").split()[:4])


def ses_bul(ad, sorgu, index=0, tur="eylem", freesound=None, cevir=None):
    """Arama kutusu: sorguya uyan CC0 sesler, en alakalısı önce; `(adaylar, mesaj)`.

    Arama önce yazıldığı gibi yapılır. En iyi aday aranan kelimelerin **hepsini**
    taşımıyorsa sorgu İngilizceye çevrilip yeniden aranır ve daha alakalı sonuç
    kullanılır. Ölçüm: "ayak sesi" Freesound'da Türkçe adlı rastgele kayıtları getiriyordu
    ("Ortam sesi", "Çan Sesi" — yalnızca "sesi" eşleşiyor); çeviri ("footsteps") doğrudan
    ayak seslerini getirir. Panel adayları **tek tek** gösterir: "Tekrar oluştur"
    sıradakine geçer.
    """
    sorgu = " ".join(str(sorgu or "").split())
    adaylar, mesaj = aday_ara(ad, sorgu, tur, index, freesound)
    if not sorgu or (adaylar and en_iyi_alaka(adaylar, sorgu) >= 1.0):
        return adaylar, mesaj
    veri, _klasor, hata = _hedef(ad)
    if hata:
        return adaylar, mesaj
    ingilizce = (cevir or (lambda s: _ingilizceye_cevir(veri, s)))(sorgu)
    if not ingilizce or ingilizce.lower() == sorgu.lower():
        return adaylar, mesaj
    cevrilen, cevrilen_mesaj = aday_ara(ad, ingilizce, tur, index, freesound)
    if cevrilen and (not adaylar or en_iyi_alaka(cevrilen, ingilizce)
                     >= en_iyi_alaka(adaylar, sorgu)):
        return cevrilen, f"'{sorgu}' → '{ingilizce}' diye arandı. " + cevrilen_mesaj
    return adaylar, mesaj


YZ_SORGU_SISTEM = (
    "You help a video editor find a sound effect in the Freesound library. You get the "
    "user's request (often Turkish) and the scene it is for. Write 3 different search "
    "queries of 1-3 plain English words the way library files are named: the sound "
    "source plus the action (e.g. 'rock fall', 'stone tumble', 'boulder impact'). The "
    "library matches ALL words, so avoid adjectives, places and years. Order them from "
    "most specific to most general.\n"
    'Return ONLY JSON: {"queries": ["...", "...", "..."], "label_tr": "short Turkish label"}')

YZ_SIRA_SISTEM = (
    "You rank sound-library recordings for a video editor. You get the user's request, "
    "the scene, and candidate recordings (name, tags, description, seconds). Keep ONLY "
    "candidates that really are the requested sound and fit the scene; drop music, speech "
    "and modern noise unless requested, and drop different sounds. Order the kept ones "
    "from best to worst.\n"
    'Return ONLY JSON: {"ids": [best id, next id, ...]}')


def _yz(veri, servis, ai):
    """Aramanın yapay zekâsı. Kullanıcı düğmeye basıp bekliyor: servis dalgalanırsa
    hesaplar **beklemeden** denenir (`HesapliMetin`in 10/30/60 sn beklemeleri uzun
    işler içindir; ölçüm: 503'te kelime aramasına düşmek 4 dakika sürüyordu)."""
    if ai is not None:
        return ai
    servis = servis if servis in AI_SAGLAYICILAR else (
        ((veri.get("ayarlar") or {}).get("video") or {}).get("ai"))
    return HesapliMetin(servis if servis in AI_SAGLAYICILAR else "gemini",
                        bekle=lambda _saniye: None)


def yz_ses_bul(ad, istek, index=0, tur="eylem", servis="", ai=None, freesound=None):
    """Yapay zekâlı arama: istek → 3 kütüphane sorgusu → adaylar → alakaya göre sıra.

    1. Yapay zekâ isteği (çoğu zaman Türkçe) sahnenin anlatımı/görüntüsüyle birlikte
       okuyup Freesound'un dosya adlandırmasına uygun 3 İngilizce sorgu yazar.
    2. Her sorgunun CC0 adayları toplanır (yinelenenler atılır).
    3. Yapay zekâ adayları ad/etiket/açıklamadan okuyup **isteğe uyanları** en iyiden
       kötüye sıralar; uymayanlar listeye girmez. "Tekrar oluştur" bu sırayla ilerler.

    Yapay zekâ yanıt vermezse (kota, servis yoğunluğu) kelime aramasına (`ses_bul`)
    geçilir ve bu mesajda söylenir. Dönüş: `(adaylar, mesaj)`.
    """
    istek = " ".join(str(istek or "").split())
    if not istek:
        return [], "Ne sesi istediğini yaz (ör. 'taş yuvarlanıp düşüyor')."
    veri, klasor, hata = _hedef(ad)
    if hata:
        return [], hata
    freesound = freesound or FreesoundEfekt()
    if not freesound.anahtar_var_mi():
        return [], "Freesound anahtarı yok: **API hesapları** sekmesinden ekle."
    sahne = next((s for s in efektler.efekt_sahneleri(veri, klasor)
                  if s["index"] == int(_sayi(index, 0))), None) or {
        "metin": "", "video_prompt": "", "sure": 5.0}
    stil = ((veri.get("ayarlar") or {}).get("video") or {}).get("stil") or "-"
    baglam = (f"User request: \"{istek}\"\nSound type: {tur}\nScene narration: "
              f"\"{sahne['metin']}\"\nOn screen: \"{sahne['video_prompt']}\"\n"
              f"Story style/era: {stil}")
    try:
        return yz_adaylari(_yz(veri, servis, ai), baglam, tur, sahne["sure"], freesound)
    except FreesoundHatasi as exc:
        return [], str(exc)
    except Exception as exc:
        adaylar, mesaj = ses_bul(ad, istek, index, tur, freesound)
        return adaylar, (f"Yapay zekâ şu an yanıt vermedi ({_ilk_satir(exc, 60)}); kelime "
                         "aramasıyla bulundu. " + mesaj)


def yz_adaylari(ai, baglam, tur, sure, freesound):
    """Yapay zekâlı aramanın projeden bağımsız çekirdeği: `(adaylar, mesaj)`.

    `baglam` isteği (ve varsa sahneyi) anlatan metindir. Yapay zekâ ya da Freesound
    hatası **yükseltilir**; kelime aramasına düşmek çağırana kalır (proje paneli
    `ses_bul`a, Araçlar › Ses efekti üret kelime aramasına geçer).
    """
    plan = json_nesnesi(ai.metin(YZ_SORGU_SISTEM, baglam, json_modu=True))
    sorgular = [" ".join(str(q).split())[:60] for q in (plan or {}).get("queries") or []
                if str(q).strip()][:3]
    if not sorgular:
        raise ValueError("sorgu yazılmadı")
    adaylar, gorulen = [], set()
    for sorgu in sorgular:
        for aday in adaylari_topla(freesound, {"tur": tur, "sorgu": sorgu,
                                               "yedek_sorgu": ""}, sure, 8):
            if aday["id"] not in gorulen:
                gorulen.add(aday["id"])
                aday["sorgu"] = sorgu
                adaylar.append(aday)
    if not adaylar:
        return [], f"'{', '.join(sorgular)}' aramalarında CC0 ses bulunamadı; isteği başka türlü yaz."
    liste = [{"id": a["id"], "name": a["ad"], "tags": a["etiketler"][:6],
              "description": a["aciklama"][:100], "seconds": a["sure"]} for a in adaylar[:24]]
    sira = json_nesnesi(ai.metin(YZ_SIRA_SISTEM, baglam + "\nCandidates: "
                                 + json.dumps(liste, ensure_ascii=False), json_modu=True))
    kimlikler = []
    for kimlik in (sira or {}).get("ids") or []:
        try:
            kimlikler.append(int(kimlik))
        except (TypeError, ValueError):
            continue
    eslesme = {a["id"]: a for a in adaylar}
    sirali = [eslesme[k] for k in dict.fromkeys(kimlikler) if k in eslesme]
    if not sirali:
        return [], (f"Yapay zekâ '{', '.join(sorgular)}' aramalarındaki {len(adaylar)} sesin "
                    "hiçbirini isteğe uygun bulmadı; isteği başka türlü yaz.")
    return sirali, (f"🤖 '{', '.join(sorgular)}' diye arandı; {len(adaylar)} sesten "
                    f"isteğe uyan {len(sirali)} tanesi en iyisinden sıralandı.")


def _kelimeler(sorgu):
    return [k for k in str(sorgu or "").lower().split() if len(k) > 2]


def _alaka(aday, kelimeler):
    """Adayın adında/etiketlerinde aranan kelimelerden kaçı geçiyor (kök eşleşir)."""
    metin = " ".join([aday.get("ad") or ""] + list(aday.get("etiketler") or [])).lower()
    return sum(1 for k in kelimeler if k.rstrip("s") in metin)


def en_iyi_alaka(adaylar, sorgu):
    """En alakalı adayın oranı: 1,0 = aranan kelimelerin hepsi geçiyor."""
    kelimeler = _kelimeler(sorgu)
    if not kelimeler or not adaylar:
        return 0.0
    return max(_alaka(a, kelimeler) for a in adaylar) / len(kelimeler)


def alakaya_gore(adaylar, sorgu):
    """Adayları aramayla alakasına göre sırala: adında/etiketlerinde aranan kelimelerin
    **kaçını** taşıdığı önce gelir, eşitlikte Freesound'un kendi sırası korunur.

    Sorgu kelime kelime gevşetildiğinde ("footsteps sand" → "sand") alakasız sesler de
    geliyordu (ör. "camera flash"); kullanıcı "Tekrar oluştur"da önce isteğe uyanları
    duymalı. Kelime kökü eşleşir: "footstep" ↔ "footsteps".
    """
    kelimeler = _kelimeler(sorgu)
    return sorted(adaylar, key=lambda aday: _alaka(aday, kelimeler), reverse=True)


def aday_ara(ad, sorgu, tur="eylem", index=0, freesound=None):
    """Freesound'da CC0 adaylar (dinlenebilir önizleme adresleriyle); `(adaylar, mesaj)`."""
    veri, klasor, hata = _hedef(ad)
    if hata:
        return [], hata
    sorgu = " ".join(str(sorgu or "").split())
    if not sorgu:
        return [], "Aranacak sesi yaz (İngilizce daha çok sonuç verir: *rope snap*, *footsteps sand*)."
    freesound = freesound or FreesoundEfekt()
    if not freesound.anahtar_var_mi():
        return [], "Freesound anahtarı yok: **API hesapları** sekmesinden ekle."
    sure = next((s["sure"] for s in efektler.efekt_sahneleri(veri, klasor)
                 if s["index"] == int(_sayi(index, 0))), 5.0)
    try:
        adaylar = adaylari_topla(freesound, {"tur": tur, "sorgu": sorgu, "yedek_sorgu": ""},
                                 sure, ARAMA_ADET * 2)
    except FreesoundHatasi as exc:
        return [], str(exc)
    adaylar = alakaya_gore(adaylar, sorgu)[:ARAMA_ADET]
    for aday in adaylar:
        aday["sorgu"] = sorgu
    if not adaylar:
        return [], f"'{sorgu}' için CC0 ses bulunamadı; başka kelimelerle dene."
    return adaylar, f"'{sorgu}' için {len(adaylar)} CC0 ses bulundu: dinle, beğendiğini kullan."
