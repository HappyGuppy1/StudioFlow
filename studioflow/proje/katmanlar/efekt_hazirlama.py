"""Ses efektlerini hazırla: yapay zekâ planlar, Freesound'dan CC0 ses bulunur, iz kurulur.

İki yol vardır, ikisi de aynı üç adımı izler:

1. **Plan** — yapay zekâ her sahne için katmanları yazar: tür (`ortam` sahne boyunca
   süren ses, `eylem` belirli bir an), kısa Türkçe etiket ve Freesound'da aranacak
   İngilizce sorgu.
   - *Yapay zekâ hazırlasın*: hangi sahnede ne sesi olacağına yapay zekâ karar verir
     (anlatım, sahnenin video prompt'u ve projenin görsel stili/dönemi okunur).
   - *Manuel*: kullanıcı sahne başına ne istediğini yazar ("yemek yeme sesi"); yapay
     zekâ **yalnızca** o isteği sorguya çevirir, kendiliğinden ses eklemez. Boş
     bırakılan sahnede efekt olmaz.
2. **Seçim** — her katman için Freesound'dan CC0 adaylar alınır; yapay zekâ adların,
   etiketlerin ve açıklamaların üstünden isteğe **gerçekten uyan** adayı seçer. Uyan
   yoksa katman boş kalır ve sebebi yazılır: uymayan bir ses asla "en yakını" diye
   konmaz.
3. **İz** — seçilen sesler indirilir, sahnelerin videodaki anlarına yerleştirilir ve
   tek bir WAV olarak kaydedilir (bkz. `efektler.iz_kur`).

Yapay zekâ `metin_ai.HesapliMetin`'dir: tek servis, **tek (en iyi) model**; kota ya da
yetki hatasında aynı servisin sıradaki hesabı denenir, zayıf bir modele düşülmez.
"""
import json
import time
from datetime import datetime

from studioflow.cekirdek.metin import ilk_satir as _ilk_satir
from studioflow.proje.katmanlar import efektler
from studioflow.proje.dosya import not_ekle, proje_yaz
from studioflow.proje.dosya_yollari import sure_metni
from studioflow.proje.hedef import proje_hedefi
from studioflow.proje.json_yardim import json_nesnesi
from studioflow.proje.sabitler import EFEKT_KATMAN_SINIRI
from studioflow.saglayicilar.efekt_freesound import FreesoundEfekt, FreesoundHatasi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import AI_SAGLAYICILAR

ADAY_SAYISI = 8
SECIM_GRUBU = 8              # seçim isteğine giren katman sayısı
SECIM_DENEME = 3             # bir seçim grubu için en fazla deneme
SECIM_BEKLEME = 20           # denemeler arası bekleme (sn)
TURLER = ("ortam", "eylem")

_ORTAK_KURALLAR = (
    "Rules for every layer:\n"
    "- type 'ortam' = ambience/room tone that lasts the whole scene; type 'eylem' = a "
    "specific action/foley sound.\n"
    "- query: 2-3 plain English words the way sound libraries name files: the sound source "
    "plus the action (e.g. 'footsteps sand', 'rope snap', 'crowd murmur', 'stone scrape'). "
    "The library matches ALL words, so no adjectives (ancient, quiet, heavy, dawn), no "
    "years, no places.\n"
    "- alt_query: a different phrasing of the same sound, used if the first finds nothing.\n"
    "- label_tr: very short, grammatical Turkish label of the sound (e.g. 'kumda ayak "
    "sesi', 'ip kopması', 'uzak kalabalık uğultusu').\n"
    "- start: seconds after the scene start when an 'eylem' sound begins (0 for 'ortam').\n"
    "- Never music, never singing, never narration or intelligible speech.\n"
    "- Respect the era and place of the story: no modern sounds (cars, engines, phones, "
    "electricity hum) in a historical story.\n"
    f"- At most {EFEKT_KATMAN_SINIRI} layers per scene.\n"
    'Return ONLY JSON: {"scenes": [{"index": <scene index>, "layers": [{"type": "ortam|eylem", '
    '"label_tr": "...", "query": "...", "alt_query": "...", "start": 0.0}]}]}')

PLAN_SISTEM_YZ = (
    "You are a film sound designer planning foley and ambience for a short vertical video. "
    "For each scene decide which sound effects make it feel real: usually one ambience "
    "layer plus the one or two actions that are visible or described. Leave a scene "
    "without layers if nothing would sound natural.\n" + _ORTAK_KURALLAR)

PLAN_SISTEM_MANUEL = (
    "You are a film sound designer. The user wrote, for some scenes, which sound effect "
    "they want (in Turkish or English). Turn EACH request into layers that produce "
    "exactly the requested sound — nothing else. Do not add ambience or any sound the user "
    "did not ask for. If one request names several sounds, make one layer per sound. Only "
    "include the scenes that have a request.\n" + _ORTAK_KURALLAR)

SECIM_SISTEM = (
    "You pick sound-library recordings for a video. For each request you get candidate "
    "recordings (name, tags, description, duration). Choose the ONE candidate that really "
    "is the requested sound. Prefer clean recordings of just that sound. Reject candidates "
    "that contain music, speech, or modern noise unless requested, and reject anything "
    "that is a different sound. If no candidate matches, answer null — a wrong sound is "
    "worse than no sound.\n"
    'Return ONLY JSON: {"choices": [{"key": "<request key>", "id": <candidate id or null>, '
    '"reason": "short reason"}]}')


def _servis(servis, veri):
    """Kullanılacak yapay zekâ servisi: ekranda seçili olan, yoksa projenin servisi."""
    for aday in (servis, ((veri.get("ayarlar") or {}).get("video") or {}).get("ai"),
                 "cloudflare"):
        if aday in AI_SAGLAYICILAR:
            return aday
    return "cloudflare"


def _json_iste(ai, sistem, kullanici, anahtar, bildir):
    """JSON yanıtı iste; okunamazsa aynı servisten bir kez düzeltme iste."""
    cevap = ai.metin(sistem, kullanici, json_modu=True, bildir=bildir)
    veri = json_nesnesi(cevap)
    if isinstance(veri, dict) and isinstance(veri.get(anahtar), list):
        return veri
    bildir("Yanıt beklenen JSON biçiminde değil; aynı servisten düzeltme isteniyor.")
    cevap = ai.metin(sistem, kullanici + "\n\nYour previous answer was not valid. Answer "
                     "again with ONLY the JSON object described above.\n"
                     f"Previous answer (first 300 chars): {str(cevap)[:300]}",
                     json_modu=True, bildir=bildir)
    veri = json_nesnesi(cevap)
    if isinstance(veri, dict) and isinstance(veri.get(anahtar), list):
        return veri
    raise ValueError("Yapay zekâ yanıtı okunamadı: " + _ilk_satir(cevap, 160))


def plan_istegi(veri, sahneler, istekler=None):
    """Plan isteğinin kullanıcı mesajı (manuelde yalnızca isteği olan sahneler)."""
    video = (veri.get("ayarlar") or {}).get("video") or {}
    satirlar = [f"Visual style / era of the story: {video.get('stil') or '-'}",
                f"Full narration: {str(veri.get('metin') or '')[:1500]}", "", "Scenes:"]
    for sahne in sahneler:
        if istekler is not None and not istekler.get(sahne["index"]):
            continue
        satir = (f"- index {sahne['index']} · {sahne['sure']:.1f} s · narration: "
                 f"\"{sahne['metin']}\" · on screen: \"{sahne['video_prompt']}\"")
        if istekler is not None:
            satir += f" · USER REQUEST: \"{istekler[sahne['index']]}\""
        satirlar.append(satir)
    return "\n".join(satirlar)


def plani_coz(yanit, sahneler, istekler=None):
    """Plan yanıtını doğrula: `{sahne index: [katman, ...]}`.

    Bilinmeyen sahne, sorgusu boş katman ve fazla katman atılır; manuelde isteği
    olmayan sahneye yazılmış katmanlar da atılır (yapay zekâ kendiliğinden ses eklemez).
    """
    sureler = {s["index"]: s["sure"] for s in sahneler}
    plan = {}
    for sahne in (yanit or {}).get("scenes") or []:
        try:
            index = int(sahne.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if index not in sureler or (istekler is not None and not istekler.get(index)):
            continue
        katmanlar = []
        for katman in sahne.get("layers") or []:
            if not isinstance(katman, dict):
                continue
            sorgu = " ".join(str(katman.get("query") or "").split())[:80]
            if not sorgu:
                continue
            tur = katman.get("type") if katman.get("type") in TURLER else "eylem"
            try:
                bas = float(katman.get("start") or 0)
            except (TypeError, ValueError):
                bas = 0.0
            katmanlar.append({
                "tur": tur, "sorgu": sorgu,
                "yedek_sorgu": " ".join(str(katman.get("alt_query") or "").split())[:80],
                "etiket": " ".join(str(katman.get("label_tr") or sorgu).split())[:60],
                "bas": 0.0 if tur == "ortam" else round(min(max(0.0, bas),
                                                            max(0.0, sureler[index] - 0.3)), 2)})
        if katmanlar:
            plan.setdefault(index, []).extend(katmanlar)
            plan[index] = plan[index][:EFEKT_KATMAN_SINIRI]
    return plan


# Sorguyu gevşetirken atlanan dolgu kelimeleri: Freesound **bütün** kelimeleri eşler,
# "quiet", "ancient" gibi bir sıfat sonucu sıfıra indirir.
_DOLGU = {"a", "an", "the", "of", "on", "in", "with", "and", "sound", "sounds", "noise",
          "effect", "ambient", "ambience", "quiet", "soft", "loud", "heavy", "light",
          "ancient", "old", "distant", "close", "dry", "gentle", "small", "big", "large"}


def sorgu_adaylari(sorgu, yedek=""):
    """Denenecek sorgular, darlıktan genişe: tam sorgu → yedek → kelime ikilileri →
    tek kelimeler.

    Ölçüm (goldetest, CC0 süzgeci): "straw mat rustle" 0 sonuç, "straw rustle" 4;
    "bread tearing" 0, "tearing" yüzlerce. Genişleyen sorgu yanlış adaylar da getirir;
    onları seçim adımındaki yapay zekâ eler (uymayan ses konmaz).
    """
    sirali = []

    def ekle(metin):
        metin = " ".join(metin.split())
        if metin and metin.lower() not in {s.lower() for s in sirali}:
            sirali.append(metin)

    ekle(sorgu)
    ekle(yedek)
    for kaynak in (sorgu, yedek):
        kelimeler = [k for k in kaynak.lower().split() if k not in _DOLGU]
        ekle(" ".join(kelimeler))
        for i in range(len(kelimeler)):
            for j in range(i + 1, len(kelimeler)):
                ekle(f"{kelimeler[i]} {kelimeler[j]}")
    for kaynak in (sorgu, yedek):
        for kelime in kaynak.lower().split():
            if kelime not in _DOLGU and len(kelime) > 3:
                ekle(kelime)
    return sirali


def adaylari_topla(freesound, katman, sahne_suresi, hedef=ADAY_SAYISI):
    """Katmanın Freesound adayları: sorgu kademeli gevşetilir, `hedef` adaya ulaşınca durur."""
    sure_alt = min(3.0, max(0.5, sahne_suresi * 0.5)) if katman["tur"] == "ortam" else 0.2
    adaylar, gorulen = [], set()
    for sorgu in sorgu_adaylari(katman["sorgu"], katman.get("yedek_sorgu", ""))[:8]:
        for aday in freesound.ara(sorgu, hedef, sure_alt, 180):
            if aday["id"] not in gorulen:
                gorulen.add(aday["id"])
                adaylar.append(aday)
        if len(adaylar) >= hedef:
            break
    return adaylar[:hedef]


def secim_istegi(talepler):
    """Seçim isteğinin kullanıcı mesajı: her talep için aday listesi."""
    parcalar = []
    for anahtar, (katman, istek, adaylar) in talepler.items():
        parcalar.append({
            "key": anahtar, "wanted": katman["etiket"], "search": katman["sorgu"],
            "type": katman["tur"], "user_request": istek or None,
            "candidates": [{"id": a["id"], "name": a["ad"], "tags": a["etiketler"][:6],
                            "description": a["aciklama"][:100], "seconds": a["sure"]}
                           for a in adaylar]})
    return json.dumps({"requests": parcalar}, ensure_ascii=False)


def secimi_coz(yanit, talepler):
    """`{anahtar: aday ya da None}`; listede olmayan kimlik seçilmemiş sayılır."""
    secimler = {}
    for secim in (yanit or {}).get("choices") or []:
        if not isinstance(secim, dict):
            continue
        anahtar = str(secim.get("key") or "")
        if anahtar not in talepler:
            continue
        try:
            kimlik = int(secim.get("id"))
        except (TypeError, ValueError):
            secimler[anahtar] = None
            continue
        secimler[anahtar] = next((a for a in talepler[anahtar][2] if a["id"] == kimlik), None)
    return secimler


def _kayit_adi(isim, yontem):
    ad = efektler.efekt_adi(isim)
    if ad:
        return ad
    return f"{'yz' if yontem == 'yapay_zeka' else 'manuel'}-{datetime.now():%Y%m%d-%H%M%S}"


def efekt_hazirla(ad, yontem, istekler=None, isim="", servis="", ai=None, freesound=None,
                  bekle=time.sleep):
    """Efekt kaydını hazırla (üreteç): `("durum", metin)` … sonra
    `("bitti", kayıt, metin)` ya da `("hata", metin)`.

    `yontem`: `"yapay_zeka"` ya da `"manuel"`. Manuelde `istekler` = `{sahne index:
    kullanıcının yazdığı metin}`; boş metinli sahneler efektsiz kalır.
    """
    veri, klasor, hata = proje_hedefi(ad, "ses efekti hazırla",
                                      "Ses efekti için önce bir proje seç ya da aç.")
    if hata:
        yield "hata", hata
        return
    sahneler = efektler.efekt_sahneleri(veri, klasor)
    if not sahneler:
        yield "hata", "Projede videosu üretilmiş sahne yok; önce sahneleri üret."
        return
    manuel = yontem == "manuel"
    if manuel:
        istekler = {int(k): " ".join(str(v or "").split())
                    for k, v in (istekler or {}).items() if str(v or "").strip()}
        if not istekler:
            yield "hata", "Hiçbir sahneye efekt yazılmadı: en az bir sahnenin kutusuna " \
                          "istediğin sesi yaz (ör. 'yemek yeme sesi')."
            return
    else:
        istekler = None
    freesound = freesound or FreesoundEfekt()
    if not freesound.anahtar_var_mi():
        yield "hata", ("Freesound anahtarı yok: **API hesapları** sekmesinde **Freesound** "
                       "servisine anahtar ekle (ücretsiz, freesound.org/apiv2/apply).")
        return
    servis = _servis(servis, veri)
    try:
        ai = ai or HesapliMetin(servis)
    except ValueError as exc:
        yield "hata", str(exc)
        return
    notlar = []

    def bildir(mesaj):
        notlar.append(mesaj)

    toplam_sure = sahneler[-1]["bas"] + sahneler[-1]["sure"]
    yield "durum", (f"{len(sahneler)} sahne ({sure_metni(toplam_sure)}) · {ai.label} "
                    f"({ai.model}) " + ("isteklerini sorguya çeviriyor…" if manuel else
                                         "hangi sahnede ne sesi olacağını planlıyor…"))
    for deneme in range(1, SECIM_DENEME + 1):
        try:
            yanit = _json_iste(ai, PLAN_SISTEM_MANUEL if manuel else PLAN_SISTEM_YZ,
                               plan_istegi(veri, sahneler, istekler), "scenes", bildir)
            break
        except Exception as exc:
            if deneme == SECIM_DENEME:
                yield "hata", "Efekt planı yazılamadı: " + _ilk_satir(exc, 240)
                return
            yield "durum", (f"Plan alınamadı ({_ilk_satir(exc, 80)}); {SECIM_BEKLEME} sn "
                            f"sonra yeniden deneniyor ({deneme + 1}/{SECIM_DENEME})…")
            bekle(SECIM_BEKLEME)
    plan = plani_coz(yanit, sahneler, istekler)
    if not plan:
        yield "hata", "Yapay zekâ hiçbir sahne için efekt planlamadı; yeniden dene."
        return
    katman_sayisi = sum(len(k) for k in plan.values())
    yield "durum", (f"Plan hazır: {len(plan)} sahne, {katman_sayisi} ses. Freesound'da "
                    "CC0 adaylar aranıyor…")

    sureler = {s["index"]: s for s in sahneler}
    talepler, bulunamayan = {}, {}
    try:
        for index, katmanlar in sorted(plan.items()):
            for sira, katman in enumerate(katmanlar, 1):
                adaylar = adaylari_topla(freesound, katman, sureler[index]["sure"])
                if adaylar:
                    talepler[f"{index}-{sira}"] = (katman, (istekler or {}).get(index, ""),
                                                   adaylar)
                else:
                    bulunamayan.setdefault(index, []).append(katman["etiket"])
    except FreesoundHatasi as exc:
        yield "hata", str(exc)
        return
    if not talepler:
        yield "hata", "Freesound'da planlanan seslerin hiçbiri için CC0 kayıt bulunamadı."
        return
    # Seçim gruplar hâlinde istenir: her istek küçük kalır (hız ve kota), servis bir
    # grupta dalgalanırsa yalnızca o grup yeniden denenir.
    anahtarlar = list(talepler)
    gruplar = [anahtarlar[i:i + SECIM_GRUBU] for i in range(0, len(anahtarlar), SECIM_GRUBU)]
    secimler = {}
    for sira, grup in enumerate(gruplar, 1):
        yield "durum", (f"{len(talepler)} ses için aday bulundu; {ai.label} isteğe uyan "
                        f"kaydı seçiyor ({sira}/{len(gruplar)})…")
        parca = {anahtar: talepler[anahtar] for anahtar in grup}
        # Servis dalgalanırsa (503) grup birkaç kez yeniden istenir: plan ve arama
        # emeği tek bir geçici hatayla boşa gitmesin.
        for deneme in range(1, SECIM_DENEME + 1):
            try:
                secimler.update(secimi_coz(_json_iste(ai, SECIM_SISTEM, secim_istegi(parca),
                                                      "choices", bildir), parca))
                break
            except Exception as exc:
                if deneme == SECIM_DENEME:
                    yield "hata", "Ses seçimi yapılamadı: " + _ilk_satir(exc, 240)
                    return
                yield "durum", (f"Seçim grubu {sira}/{len(gruplar)} alınamadı "
                                f"({_ilk_satir(exc, 80)}); {SECIM_BEKLEME} sn sonra yeniden "
                                f"deneniyor ({deneme + 1}/{SECIM_DENEME})…")
                bekle(SECIM_BEKLEME)

    kaynak = efektler.efekt_kaynak_klasoru(klasor)
    katman_dizileri, kayit_sahneleri = [], {}
    for anahtar, (katman, istek, _adaylar) in talepler.items():
        index = int(anahtar.split("-")[0])
        sahne_kaydi = kayit_sahneleri.setdefault(
            index, {"index": index, "istek": istek, "katmanlar": [], "bulunamayan": []})
        aday = secimler.get(anahtar)
        if aday is None:
            sahne_kaydi["bulunamayan"].append(katman["etiket"])
            continue
        try:
            yol = freesound.indir(aday, kaynak / f"{aday['id']}.mp3")
            ses = efektler.ses_oku(yol)
        except (FreesoundHatasi, ValueError, OSError) as exc:
            sahne_kaydi["bulunamayan"].append(f"{katman['etiket']} (indirilemedi: "
                                              f"{_ilk_satir(exc, 80)})")
            continue
        katman_dizileri.append((sureler[index], katman["tur"], ses, katman["bas"]))
        sahne_kaydi["katmanlar"].append({
            "tur": katman["tur"], "etiket": katman["etiket"], "sorgu": katman["sorgu"],
            "bas": katman["bas"], "id": aday["id"], "ad": aday["ad"], "sahip": aday["sahip"],
            "url": aday["url"], "onizleme": aday["onizleme"], "kazanc": 0.0})
    for index, etiketler in bulunamayan.items():
        kayit_sahneleri.setdefault(index, {"index": index,
                                           "istek": (istekler or {}).get(index, ""),
                                           "katmanlar": [], "bulunamayan": []})
        kayit_sahneleri[index]["bulunamayan"].extend(etiketler)
    if not katman_dizileri:
        yield "hata", ("Adaylar bulundu ama hiçbiri isteğe uymadı ya da indirilemedi:\n"
                       + efektler.plan_metni({"sahneler": sorted(kayit_sahneleri.values(),
                                                                 key=lambda s: s["index"])}))
        return
    yield "durum", f"{len(katman_dizileri)} ses indirildi; efekt izi video süresine göre kuruluyor…"

    isim = _kayit_adi(isim, yontem)
    kayit = efektler.yeni_kayit(isim, yontem, toplam_sure,
                                sorted(kayit_sahneleri.values(), key=lambda s: s["index"]),
                                f"{ai.label} · {ai.model}")
    try:
        iz = efektler.iz_kur(sahneler, katman_dizileri, toplam_sure)
        efektler.iz_yaz(iz, klasor / kayit["dosya"])
        (efektler.efekt_klasoru(klasor) / f"{isim}-kaynaklar.txt").write_text(
            "Freesound · lisans: CC0 (atıf gerekmez, ticari kullanım serbest)\n\n"
            + efektler.plan_metni(kayit) + "\n\n"
            + "\n".join(f"#{k['id']} {k['url']}" for s in kayit["sahneler"]
                        for k in s["katmanlar"]) + "\n", encoding="utf-8")
        efektler.kaydi_yaz(klasor, kayit)
    except (OSError, ValueError) as exc:
        yield "hata", "Efekt izi kaydedilemedi: " + _ilk_satir(exc, 240)
        return
    ses_sayisi = sum(len(s["katmanlar"]) for s in kayit["sahneler"])
    baslik = (f"'{isim}' ses efektleri kaydedildi ({YONTEM_METNI[yontem]} · "
              f"{sum(1 for s in kayit['sahneler'] if s['katmanlar'])} sahne · {ses_sayisi} ses).")
    not_ekle(veri, baslik)
    proje_yaz(veri)
    ek = ("\n\nNotlar:\n" + "\n".join(f"- {n}" for n in notlar[-5:])) if notlar else ""
    yield "bitti", kayit, (baslik + " Videoya eklemek için aşağıdaki **Videoya göm** "
                           "panelinden seç.\n\n" + efektler.plan_metni(kayit) + ek)


YONTEM_METNI = {"yapay_zeka": "yapay zekâ seçti", "manuel": "manuel istek"}
