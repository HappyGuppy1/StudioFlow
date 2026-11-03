"""Tasarım promptu: kayıtlı bir araştırmadan genel prompt, stil, negatif ve (isteğe bağlı) ilk sahne.

Üretilenler **Proje oluştur** sayfasının prompt alanlarıyla birebir eşleşir (anahtarlar
`yonetim.icerik_varsayilanlari` ile aynıdır); proje sayfasında **Prompt belgesi**
seçilince hepsi kendi alanına dolar:

| Anahtar | Proje sayfasındaki alan | Kural (`docs/STIL-PROMPT-KILAVUZU.md`) |
|---------|-------------------------|------------------------------------------|
| `genel` | Genel video prompt'u (pozitif) | konu, karakterler, mekân, atmosfer, kamera dili; stil terimi yok |
| `stil` | Görsel stil katmanı | 12–18 kelime, ilk kelime `Photorealistic`, ressam dili yok |
| `negatif` | Negatif prompt | `painting, signature, canvas texture` şart; önceliğe göre sıralı |
| `ilk_prompt` | İlk sahne · ne görünsün (+) | kanca karesinin içeriği; stil **eklenmez** (akış başa ekler) |
| `ilk_negatif` | İlk sahne · negatif prompt (−) | yalnızca o kareye özgü yasaklar |

Yapay zekânın yazdığı stil ve negatif **kodla da denetlenir**: yasak (ressam) terim içeren
öğe atılır, `Photorealistic` başta değilse eklenir, 18 kelimeyi aşan kuyruk kırpılır,
zorunlu negatif öğeler eklenir. Yapılan her düzeltme kontrol listesine yazılır.

İlk sahnenin içeriği, seçilmişse kayıtlı bir seslendirmenin **ilk cümlesinden** (kanca)
kurulur: strateji "ilk görsel ilk cümleyi göstersin" der.
"""
import json
import re
from datetime import datetime

from studioflow.cekirdek.metin import kelime_kirp, kelime_sayisi, negatif_duzenle, stil_ekle
from studioflow.cekirdek.yollar import OUTPUTS
from studioflow.hikaye import istemler, kayitlar
from studioflow.hikaye.rapor import kaynak_etiketi
from studioflow.hikaye.yanit import YapayZekaIsi
from studioflow.proje.sabitler import NEGATIF_ONCELIK
from studioflow.saglayicilar import gorsel_cloudflare
from studioflow.saglayicilar.metin_ai import HesapliMetin

KLASOR = OUTPUTS / "tasarim"

# Ad verilerek kaydedilen tasarımlar (sahne planlama / proje bu kütüphaneden seçecek).
TASARIMLAR = kayitlar.Kutuphane(lambda: KLASOR / "kayitli", "tasarım")

RAPOR_SINIRI = 60000
STIL_ARALIGI = (12, 18)
GENEL_ARALIGI = (60, 120)     # genel prompt: bütün sahneleri yazan yapay zekânın okuduğu çerçeve
ILK_SAHNE_EN_AZ = 25          # stil düşüldükten sonra sahneye kalan en az kelime

# Dönem ve kıyafet analizi: dönem analizi + kıyafet araştırması sonunda üretilen kompakt
# cümle. Analiz kayda, rehbere ve yalnızca görünür kıyafete uygulanan brief bilgisine girer.
KIYAFET_KILIT_KELIME = 18

# Modeli resme iten terimler (kılavuz 4. bölüm): stil öğesinde geçerse öğe atılır.
RESSAM_DILI = ("painterly", "painting", "illustration", "concept art", "matte", "artstation",
               "palette", "haze", "dreamy", "ethereal", "stylized", "drawing", "sketch")

# Fotoğraf görünümü için negatifte bulunması gerekenler (kılavuz 7. bölüm).
ZORUNLU_NEGATIF = ("painting", "oil painting", "illustration", "signature", "canvas texture",
                   "cartoon", "3d render", "plastic skin")


def _ogeler(metin):
    return [" ".join(p.split()).strip(" .;") for p in str(metin or "").split(",")
            if " ".join(p.split()).strip(" .;")]


def stil_duzelt(stil):
    """Stil metnini kılavuza uydur; `(yeni stil, [yapılan düzeltmeler])`."""
    notlar = []
    ogeler = []
    for oge in _ogeler(stil):
        if any(terim in oge.lower() for terim in RESSAM_DILI):
            notlar.append(f"ressam dili çıkarıldı: '{oge}'")
            continue
        ogeler.append(oge)
    if not ogeler or not ogeler[0].lower().startswith("photorealistic"):
        ogeler = [o for o in ogeler if o.lower() != "photorealistic"]
        ogeler.insert(0, "Photorealistic")
        notlar.append("'Photorealistic' başa eklendi")
    sonuc = []
    for oge in ogeler:
        if kelime_sayisi(", ".join(sonuc + [oge])) > STIL_ARALIGI[1]:
            notlar.append(f"18 kelimeyi aşan kuyruk kırpıldı: '{oge}'")
            continue
        sonuc.append(oge)
    return ", ".join(sonuc), notlar


def negatif_tamamla(negatif):
    """Zorunlu öğeleri ekle, tekrarları at, önceliğe göre sırala; `(negatif, [eklenenler])`."""
    mevcut = {o.casefold() for o in _ogeler(negatif)}
    eksik = [o for o in ZORUNLU_NEGATIF if o.casefold() not in mevcut]
    birlesik = ", ".join(_ogeler(negatif) + eksik)
    return negatif_duzenle(birlesik, NEGATIF_ONCELIK), eksik


def tasarim_metni(ad, genel, stil, negatif, ilk_prompt="", ilk_negatif="", rehber="", bilgi="",
                  kiyafet_kilidi=""):
    """Kayıt dosyasının okunur hâli (başlıklar proje sayfasındaki alan adlarıdır)."""
    s = [f"# TASARIM · {ad}"] + ([bilgi] if bilgi else []) + [
        "", "## GENEL VİDEO PROMPT'U (pozitif)", genel or "—",
        "", "## GÖRSEL STİL KATMANI", stil or "—",
        "", "## NEGATİF PROMPT", negatif or "—"]
    if (kiyafet_kilidi or "").strip():
        s += ["", "## DÖNEM VE KIYAFET ANALİZİ", kiyafet_kilidi.strip()]
    if (ilk_prompt or "").strip():
        s += ["", "## İLK SAHNE · NE GÖRÜNSÜN (+)", ilk_prompt.strip(),
              "", "## İLK SAHNE · NEGATİF PROMPT (−)", (ilk_negatif or "").strip() or "—"]
    if (rehber or "").strip():
        s += ["", "## GÖRSEL REHBER", rehber.strip()]
    return "\n".join(s).rstrip() + "\n"


def rehber_metni(rehber):
    """Görsel rehber sözlüğünü okunur metne çevir (karakter/mekân kaynaklarıyla)."""
    if not isinstance(rehber, dict):
        return ""
    s = []
    if rehber.get("donem"):
        s.append(f"Dönem: {rehber['donem']}")
    for anahtar, baslik in (("kiyafet", "Kıyafet"), ("mimari", "Mimari / arazi"),
                            ("arac_gerec", "Araç / gereç"), ("renk_isik", "Renk / ışık")):
        ogeler = [str(o).strip() for o in rehber.get(anahtar) or [] if str(o).strip()]
        if ogeler:
            s.append(f"{baslik}: " + "; ".join(ogeler))
    for anahtar, baslik in (("karakterler", "Karakterler"), ("mekanlar", "Mekânlar")):
        kayitlar_ = [k for k in rehber.get(anahtar) or [] if isinstance(k, dict) and k.get("ad")]
        if kayitlar_:
            s.append(f"{baslik}:")
            # Model kaynak etiketini bazen metnin içine de yazıyor: iki kez basılmasın.
            s += [f"- {k['ad']}: {k.get('gorunum', '')}"
                  + ("" if "[K" in str(k.get("gorunum", "")) else kaynak_etiketi(k.get("kaynak")))
                  for k in kayitlar_]
    return "\n".join(s)


class TasarimYazari(YapayZekaIsi):
    """Tek bir tasarım. `adimlar()` durum satırları üretir; bitince `sonuc` dolar."""

    def __init__(self, arastirma_adi, rapor_metni, gorsel_model, ilk_sahne=False, kanca="",
                 provider="gemini", model="", *, ai=None, iptal=None, klasor=None):
        self.arastirma_adi = str(arastirma_adi or "").strip()
        self.rapor_metni = str(rapor_metni or "").strip()
        self.gorsel_model = gorsel_model or gorsel_cloudflare.VARSAYILAN_MODEL
        self.spec = gorsel_cloudflare.cf_model_spec(self.gorsel_model) or {}
        self.sinir = gorsel_cloudflare.prompt_kelime_siniri(self.gorsel_model)
        self.negatif_destek = gorsel_cloudflare.supports_negative(self.gorsel_model)
        self.ilk_sahne = bool(ilk_sahne)
        self.kanca = str(kanca or "").strip()
        self.iptal = iptal
        self.ai = ai or HesapliMetin(provider, model, bekle=self._bekle)
        self.klasor = klasor or KLASOR
        self.genel = self.stil = self.negatif = self.ilk_prompt = self.ilk_negatif = ""
        self.rehber = {}
        # Dönem/kıyafet süzgecinin çıktıları (bkz. `_donem_uret` · `_kiyafet_uret`).
        self.donem = {}
        self.kiyafet = {}
        self.kiyafet_kilidi = ""
        self.kiyafet_kacin = []
        self.kontroller = []
        self.sonuc = None
        self._notlar = []

    def _model_adi(self):
        return self.spec.get("label") or self.gorsel_model

    def _stil_uret(self):
        sistem = istemler.TASARIM_STIL.format(
            model=self._model_adi(), sinir=self.sinir,
            negatif="SUPPORTED" if self.negatif_destek else "NOT supported by this model")
        veri = self._json(sistem, f"Research report:\n\n{self.rapor_metni[:RAPOR_SINIRI]}"
                          + "\nPERIOD WARDROBE ANALYSIS (visible clothing only): "
                          + self.kiyafet_kilidi) or {}
        self.rehber = veri.get("rehber") if isinstance(veri.get("rehber"), dict) else {}
        self.genel = " ".join(str(veri.get("genel") or "").split())
        adet = kelime_sayisi(self.genel)
        self.kontroller.append(("✅" if GENEL_ARALIGI[0] <= adet <= GENEL_ARALIGI[1] else "⚠",
                                f"Genel prompt {adet} kelime (hedef 60–120)"))
        self.stil, notlar = stil_duzelt(veri.get("stil"))
        adet = kelime_sayisi(self.stil)
        self.kontroller.append(("✅" if STIL_ARALIGI[0] <= adet <= STIL_ARALIGI[1] else "⚠",
                                f"Stil {adet} kelime (kılavuz 12–18)"))
        self.kontroller += [("🔧", f"Stil düzeltmesi: {n}") for n in notlar]
        self.negatif, eksik = negatif_tamamla(veri.get("negatif"))
        if eksik:
            self.kontroller.append(("🔧", "Negatife eklendi: " + ", ".join(eksik)))
        self.kontroller.append(("✅", "Negatifte painting, signature, canvas texture var"))
        if not self.negatif_destek:
            self.kontroller.append(("ℹ", f"{self._model_adi()} negatif prompt almaz; negatif "
                                          "SDXL tabanlı modeller için saklanır."))
        return bool(veri)

    def _donem_uret(self):
        """Konunun dönemini araştırma raporundan çıkar.

        Sahne prompt'ları yazılmadan önce çalışan süzgecin **birinci** adımıdır; ikinci
        adım (`_kiyafet_uret`) bu dönemi girdi alır. Dönem bulunamazsa (modern/soyut konu)
        kıyafet adımı atlanır ve davranış eskisiyle birebir aynı kalır.
        """
        veri = self._json(istemler.TASARIM_DONEM,
                          f"Research report:\n\n{self.rapor_metni[:RAPOR_SINIRI]}") or {}
        self.donem = veri if isinstance(veri, dict) else {}
        tarihsel = bool(self.donem.get("tarihsel"))
        self.kontroller.append(("✅" if tarihsel else "ℹ",
                                "Dönem: " + (str(self.donem.get("donem") or "").strip() or "—")
                                + ("" if tarihsel else
                                   " (tarihsel konu değil; kıyafet süzgeci atlanır)")))
        return tarihsel

    def _kiyafet_uret(self):
        """Dönemin kıyafetini araştır ve kompakt bir dönem/kıyafet analizi üret.

        Süzgecin **ikinci** adımıdır. Analiz cümlesi `KIYAFET_KILIT_KELIME` kelimeyi
        aşamaz; aşarsa kırpılır. Döneme aykırı öğeler (`kacin`) negatife eklenir.
        """
        kullanici = (f"ERA:\n{json.dumps(self.donem, ensure_ascii=False)}\n\n"
                     f"RESEARCH REPORT:\n\n{self.rapor_metni[:RAPOR_SINIRI]}")
        veri = self._json(istemler.TASARIM_KIYAFET, kullanici) or {}
        self.kiyafet = veri if isinstance(veri, dict) else {}
        kilit = " ".join(str(self.kiyafet.get("kilit") or "").split())
        if kelime_sayisi(kilit) > KIYAFET_KILIT_KELIME:
            self.kontroller.append(("🔧", f"Dönem/kıyafet analizi {kelime_sayisi(kilit)} → "
                                          f"{KIYAFET_KILIT_KELIME} kelimeye kırpıldı"))
            kilit = kelime_kirp(kilit, KIYAFET_KILIT_KELIME)
        self.kiyafet_kilidi = kilit
        self.kiyafet_kacin = [str(o).strip() for o in (self.kiyafet.get("kacin") or [])
                              if str(o).strip()]
        self.kontroller.append(("✅" if kilit else "ℹ",
                                "Kıyafet analizi: " + (kilit or "—")
                                + (f" · yasak {len(self.kiyafet_kacin)} öğe"
                                   if self.kiyafet_kacin else "")))
        return bool(kilit)

    def _kiyafeti_bagla(self):
        """Analizi brief/rehber/negatife taşı; gizli bedeni görünür kılma."""
        if not self.kiyafet_kilidi:
            return
        if isinstance(self.rehber, dict):
            if not self.rehber.get("donem"):
                self.rehber["donem"] = str(self.donem.get("donem") or "").strip()
            if not self.rehber.get("kiyafet") and self.kiyafet.get("ogeler"):
                self.rehber["kiyafet"] = [str(o).strip() for o in self.kiyafet["ogeler"]
                                          if str(o).strip()]
        if self.kiyafet_kilidi not in self.genel:
            self.genel += (" Period wardrobe for visible people: " + self.kiyafet_kilidi
                           + ". Apply only to visible clothing; preserve the requested crop "
                           "and do not add people or hidden body parts.")
        if self.kiyafet_kacin:
            self.negatif = negatif_duzenle(
                ", ".join(_ogeler(self.negatif) + self.kiyafet_kacin), NEGATIF_ONCELIK)
        self.kontroller.append(("✅", f"Dönem ve kıyafet analizi kayda işlendi · "
                                      f"{kelime_sayisi(self.kiyafet_kilidi)} kelime"))

    def _ilk_sahne_uret(self):
        kelime = max(ILK_SAHNE_EN_AZ, self.sinir - kelime_sayisi(self.stil))
        sistem = istemler.TASARIM_ILK.format(
            model=self._model_adi(), stil=self.stil, kelime=kelime,
            negatif_kurali=(istemler.TASARIM_NEGATIFLI if self.negatif_destek
                            else istemler.TASARIM_NEGATIFSIZ))
        kanca = (f"FIRST NARRATION SENTENCE (the frame must show this):\n{self.kanca}\n\n"
                 if self.kanca else
                 "No narration yet: choose the most striking, concrete moment of the story "
                 "that would work as the video's hook.\n\n")
        kullanici = (f"{kanca}MASTER BRIEF OF THE VIDEO:\n{self.genel}\n\n"
                     f"VISUAL GUIDE:\n{json.dumps(self.rehber, ensure_ascii=False)}\n\n"
                     f"RESEARCH REPORT:\n\n{self.rapor_metni[:RAPOR_SINIRI]}")
        veri = self._json(sistem, kullanici) or {}
        prompt = " ".join(str(veri.get("prompt") or "").split())
        if kelime_sayisi(prompt) > kelime:
            self.kontroller.append(("🔧", f"İlk sahne prompt'u {kelime_sayisi(prompt)} → {kelime} "
                                          "kelimeye kırpıldı (modelin okuduğu kadar)"))
            prompt = kelime_kirp(prompt, kelime)
        self.ilk_prompt = prompt
        self.ilk_negatif = negatif_duzenle(", ".join(_ogeler(veri.get("negatif"))), NEGATIF_ONCELIK)
        self.kontroller.append(("✅" if prompt else "⚠",
                                f"İlk sahne prompt'u {kelime_sayisi(prompt)} kelime (en fazla {kelime}; "
                                f"stil başa eklenince toplam ≤ {self.sinir})"))
        if self.kanca:
            self.kontroller.append(("☐", f"Kare kanca cümlesini gösteriyor mu? “{self.kanca}”"))

    def onizleme(self):
        """Görsel modeline gidecek hâli: stil başta + ilk sahne içeriği (akışın yaptığı gibi)."""
        return stil_ekle(self.ilk_prompt, self.stil, self.sinir) if self.ilk_prompt else ""

    def _kaydet(self, zaman):
        ad = kayitlar.ad_temizle(f"{self.arastirma_adi} · tasarım · {zaman:%Y%m%d_%H%M%S}")
        self.klasor.mkdir(parents=True, exist_ok=True)
        txt, jsn = self.klasor / f"{ad}.txt", self.klasor / f"{ad}.json"
        txt.write_text(self.metin(zaman), encoding="utf-8")
        jsn.write_text(json.dumps(self.veri(), ensure_ascii=False, indent=1), encoding="utf-8")
        return txt, jsn

    def veri(self):
        return {"arastirma": self.arastirma_adi, "gorsel_model": self.gorsel_model,
                "yapay_zeka": {"servis": self.ai.provider, "model": self.ai.model},
                "genel": self.genel, "stil": self.stil, "negatif": self.negatif,
                "ilk_prompt": self.ilk_prompt,
                "ilk_negatif": self.ilk_negatif, "kanca": self.kanca, "rehber": self.rehber,
                "donem": self.donem, "kiyafet_kilidi": self.kiyafet_kilidi,
                "kiyafet_kacin": self.kiyafet_kacin,
                "rehber_metni": rehber_metni(self.rehber), "onizleme": self.onizleme(),
                "kontroller": [list(k) for k in self.kontroller]}

    def metin(self, zaman):
        bilgi = (f"Tarih: {zaman:%d.%m.%Y %H:%M} · Araştırma: {self.arastirma_adi} · Görsel modeli: "
                 f"{self._model_adi()} · Yapay zekâ: {self.ai.label} · {self.ai.model}")
        metin = tasarim_metni(self.arastirma_adi, self.genel, self.stil, self.negatif, self.ilk_prompt,
                              self.ilk_negatif, rehber_metni(self.rehber), bilgi,
                              self.kiyafet_kilidi)
        kontrol = "\n".join(f"{d} {a}" for d, a in self.kontroller)
        return metin + f"\n## KONTROL LİSTESİ\n{kontrol}\n"

    def adimlar(self):
        if not self.rapor_metni:
            raise ValueError("Önce kayıtlı bir araştırma seç.")
        zaman = datetime.now()
        yield (f"Görsel modeli: {self._model_adi()} · prompt ~{self.sinir} kelime · negatif "
               f"{'destekli' if self.negatif_destek else 'desteklenmiyor'}")
        yield "Dönem analizi yapılıyor · " + f"{self.ai.label} · {self.ai.model}…"
        tarihsel = self._donem_uret()
        yield from self._notlari_bosalt()
        if tarihsel:
            yield "Dönemin kıyafetleri araştırılıyor…"
            self._kiyafet_uret()
            yield from self._notlari_bosalt()
        yield f"Stil, negatif ve görsel rehber yazılıyor · {self.ai.label} · {self.ai.model}…"
        tamam = self._stil_uret()
        yield from self._notlari_bosalt()
        if not tamam:
            raise RuntimeError("Yapay zekâ stil yazamadı. Hesapları kontrol edip yeniden dene.")
        self._kiyafeti_bagla()
        yield (f"Genel prompt · {kelime_sayisi(self.genel)} kelime · stil "
               f"{kelime_sayisi(self.stil)} kelime · negatif {len(_ogeler(self.negatif))} öğe")
        if self.kiyafet_kilidi:
            yield f"Dönem ve kıyafet analizi hazır · {self.kiyafet_kilidi}"
        if self.ilk_sahne:
            self._dur_mu()
            yield "İlk sahne prompt'u yazılıyor" + (" (kanca cümlesinden)…" if self.kanca else "…")
            self._ilk_sahne_uret()
            yield from self._notlari_bosalt()
            yield f"İlk sahne · {kelime_sayisi(self.ilk_prompt)} kelime"
        txt, jsn = self._kaydet(zaman)
        self.sonuc = {**self.veri(), "txt": txt, "json": jsn,
                      "onerilen_ad": kayitlar.ad_temizle(f"{self.arastirma_adi} · tasarım")}
        duzeltme = sum(1 for d, _a in self.kontroller if d == "🔧")
        yield f"Tamamlandı · {duzeltme} otomatik düzeltme · {txt}"


def kanca_cumlesi(seslendirme_metni):
    """Seslendirme metninin ilk cümlesi (ilk sahnenin göstereceği an)."""
    parca = re.split(r"(?<=[.!?…])\s+", (seslendirme_metni or "").strip(), maxsplit=1)
    return parca[0] if parca and parca[0] else ""
