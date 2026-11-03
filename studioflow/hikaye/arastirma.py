"""Hikâye araştırması: bir olayı web'de araştırır, net bilgileri kaynaklı bir metin dosyasında toplar.

Akış (her adım bir durum satırı üretir, `iptal` her adım arasında denetlenir):

1. **Plan** — yapay zekâ konuyu çözer: kanonik ad, dönem, yer, anahtar kelimeler,
   Wikipedia başlıkları ve farklı bakış açılarından araştırma soruları (STORM fikri:
   iki taraf, lojistik, sayılar, görgü tanıkları, görsel detaylar…).
2. **Wikipedia** (TR + EN) — omurga: kesin tarih/kişi/yer bilgisi buradan kurulur.
3. **Web turu** — her soru `AramaHavuzu` ile aranır (Tavily → Exa → DDGS); metni kısa
   gelen sonuç `sayfa_okuma` ile okunur (trafilatura → Jina Reader).
4. **Bilgi çıkarma** — kaynaklar paketler hâlinde yapay zekâya verilir; yalnızca
   kaynakta yazan, kaynak numaralı, atomik bilgiler alınır.
5. **Boşluk kontrolü** (local-deep-researcher döngüsü) — cevapsız sorular için yeni
   sorgular üretilir ve 3–4. adımlar derinliğe göre tekrarlanır.
6. **Sentez** — bilgilerden özet, zaman çizelgesi, kişiler, tartışmalı noktalar, görsel
   detaylar ve anlatım önerileri; kaynak numaraları korunur.

Yapay zekâ `HesapliMetin`'dir: yalnızca seçilen (en iyi) model kullanılır, kota biten
hesabın yerine aynı servisin sıradaki hesabı geçer.
"""
import re
import unicodedata
from datetime import datetime

from studioflow.hikaye import istemler, rapor
from studioflow.hikaye.yanit import Durduruldu, YapayZekaIsi
from studioflow.proje.json_yardim import json_listesi
from studioflow.saglayicilar import arama_wikipedia, sayfa_okuma
from studioflow.saglayicilar.arama_havuzu import ETIKETLER, AramaHavuzu
from studioflow.saglayicilar.arama_ortak import AramaHatasi, alan_adi
from studioflow.saglayicilar.metin_ai import HesapliMetin
from studioflow.saglayicilar.metin_ortak import kisa

DERINLIKLER = {
    # tur: web turu sayısı · soru: ilk turdaki soru · sonuc: sorgu başına sonuç ·
    # kaynak: web kaynağı üst sınırı (Wikipedia hariç)
    "hizli": {"etiket": "Hızlı · 1 tur", "tur": 1, "soru": 4, "sonuc": 4, "kaynak": 12},
    "standart": {"etiket": "Standart · 2 tur", "tur": 2, "soru": 6, "sonuc": 5, "kaynak": 18},
    "derin": {"etiket": "Derin · 3 tur", "tur": 3, "soru": 8, "sonuc": 6, "kaynak": 28},
}
VARSAYILAN_DERINLIK = "standart"

DILLER = {"tr": "Turkish", "en": "English"}

WIKI_MAKALE = 2              # dil başına en fazla Wikipedia makalesi
WIKI_KARAKTER = 12000        # bir Wikipedia makalesinden yapay zekâya giden en fazla metin
KAYNAK_KARAKTER = 7000       # bir web kaynağından giden en fazla metin
PAKET_KARAKTER = 24000       # tek bilgi çıkarma isteğine giden kaynak metni
KISA_METIN = 800             # bundan kısa arama sonucu sayfadan yeniden okunur
EN_AZ_METIN = 200            # bundan kısa kaynak hiç kullanılmaz

# Metni okunamayan ya da bilgi taşımayan alan adları (video, sosyal medya).
ATLANAN_ALANLAR = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com",
                   "x.com", "twitter.com", "pinterest.com", "reddit.com")


# Eski ad: arayüz ve testler bu adla yakalar; seslendirme de aynı istisnayı kullanır.
ArastirmaDurdu = Durduruldu


# ────────────────────────────────────────────────────────── metin yardımcıları

def sade(metin):
    """Karşılaştırma için: küçük harf, Türkçe i/ı eşitlenmiş, aksansız."""
    metin = str(metin or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", metin) if not unicodedata.combining(c))


def kokler(*metinler):
    """Anahtar kelime kökleri: 4+ harfli kelimelerin ilk 5 harfi (Türkçe ekleri tolere eder)."""
    return {kelime[:5] for metin in metinler for kelime in re.findall(r"\w{4,}", sade(metin))}


def ilgili_parcalar(metin, anahtarlar, sinir):
    """Uzun metinden konuyla ilgili satırları seç (sıra korunur, ilk satır hep kalır).

    Uzun bir Wikipedia makalesinde aranan olay ortalarda kalabiliyor; baştan kırpmak onu
    kaybediyordu. Satırlar anahtar köklerle eşleşme sayısına göre puanlanır.
    """
    metin = re.sub(r"\n{3,}", "\n\n", str(metin or "").strip())
    if len(metin) <= sinir:
        return metin
    satirlar = [s.strip() for s in metin.splitlines() if s.strip()]
    if not satirlar:
        return metin[:sinir]
    puanlar = [len(kokler(s) & anahtarlar) for s in satirlar]
    secilen, toplam = {0}, len(satirlar[0])
    for i in sorted(range(1, len(satirlar)), key=lambda i: (-puanlar[i], i)):
        if puanlar[i] == 0:
            break
        if toplam + len(satirlar[i]) + 1 > sinir:
            continue
        secilen.add(i)
        toplam += len(satirlar[i]) + 1
    return "\n".join(satirlar[i] for i in sorted(secilen))[:sinir]


def url_anahtari(url):
    url = str(url or "").split("#")[0].rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", url).lower()


def _bilgileri_kurtar(cevap):
    """Yarıda kesilmiş bilgi yanıtından tamamlanmış bilgi nesnelerini topla (yoksa `None`)."""
    bilgiler = [oge for oge in json_listesi(cevap) or []
                if isinstance(oge, dict) and oge.get("bilgi")]
    return {"bilgiler": bilgiler} if bilgiler else None


def _sayi_listesi(deger):
    if not isinstance(deger, list):
        deger = [deger]
    nolar = []
    for oge in deger:
        eslesme = re.search(r"\d+", str(oge))
        if eslesme:
            nolar.append(int(eslesme.group()))
    return nolar


# ──────────────────────────────────────────────────────────────── araştırma

class Arastirma(YapayZekaIsi):
    """Tek bir araştırma. `adimlar()` durum satırları üretir; bitince `sonuc` dolar."""

    def __init__(self, konu, derinlik=VARSAYILAN_DERINLIK, provider="gemini", model="",
                 dil="tr", *, ai=None, arama=None, wikipedia=None, okuyucu=None,
                 jina_anahtari="", iptal=None):
        self.konu = str(konu or "").strip()
        self.derinlik = derinlik if derinlik in DERINLIKLER else VARSAYILAN_DERINLIK
        self.ayar = DERINLIKLER[self.derinlik]
        self.dil = dil if dil in DILLER else "tr"
        self.ai = ai or HesapliMetin(provider, model, bekle=self._bekle)
        self.arama = arama or AramaHavuzu()
        self.wiki = wikipedia or arama_wikipedia.VARSAYILAN
        self.okuyucu = okuyucu or sayfa_okuma.oku
        self.jina_anahtari = jina_anahtari
        self.iptal = iptal
        self.plan = {}
        self.anahtarlar = set()
        self.sorular = []            # [{"soru", "sorgu", "dil", "bakis"}]
        self.kullanilan_sorgular = set()
        self.kaynaklar = []          # [{"no", "baslik", "url", "saglayici", "okuyucu", "metin"}]
        self.bilgiler = []           # [{"bilgi", "kaynak": [no], "tur", "kesinlik"}]
        self.cevapsiz = []
        self.sentez = None
        self.sonuc = None            # {"metin", "txt", "json"}
        self._gorulen = set()
        self._notlar = []

    # ------------------------------------------------------------ yardımcılar

    def _kaynak_ekle(self, baslik, url, metin, saglayici, okuyucu="", sinir=KAYNAK_KARAKTER,
                     ek_anahtar=""):
        anahtarlar = self.anahtarlar | kokler(ek_anahtar)
        kaynak = {"no": len(self.kaynaklar) + 1, "baslik": baslik, "url": url,
                  "saglayici": saglayici, "okuyucu": okuyucu,
                  "metin": ilgili_parcalar(metin, anahtarlar, sinir)}
        self.kaynaklar.append(kaynak)
        self._gorulen.add(url_anahtari(url))
        return kaynak

    # ------------------------------------------------------------------ adımlar

    def _planla(self):
        dil = DILLER[self.dil]
        veri = self._json(istemler.PLAN.format(dil=dil, soru=self.ayar["soru"]),
                          f"Topic: {self.konu}") or {}
        self.plan = veri
        sorular = []
        for oge in veri.get("sorular") or []:
            if isinstance(oge, dict) and str(oge.get("sorgu") or "").strip():
                sorular.append({"soru": str(oge.get("soru") or oge["sorgu"]).strip(),
                                "sorgu": str(oge["sorgu"]).strip(),
                                "dil": "en" if str(oge.get("dil")).lower().startswith("en") else "tr",
                                "bakis": str(oge.get("bakis") or "").strip()})
        if not sorular:
            # Plan okunamadıysa araştırma yine yürür: konunun kendisi iki dilde aranır.
            sorular = [{"soru": self.konu, "sorgu": self.konu, "dil": self.dil, "bakis": ""}]
        self.sorular = sorular[:self.ayar["soru"]]
        self.anahtarlar = kokler(self.konu, veri.get("baslik"), veri.get("yer"),
                                 " ".join(map(str, veri.get("anahtar_kelimeler") or [])))

    def _wikipedia(self):
        istekler = [w for w in self.plan.get("wikipedia") or []
                    if isinstance(w, dict) and str(w.get("baslik") or "").strip()]
        if not istekler:
            istekler = [{"dil": self.dil, "baslik": self.konu}]
        sayac = {}
        for istek in istekler:
            self._dur_mu()
            dil = "en" if str(istek.get("dil")).lower().startswith("en") else "tr"
            if sayac.get(dil, 0) >= WIKI_MAKALE:
                continue
            try:
                basliklar = self.wiki.basliklar(istek["baslik"], 1, dil)
                makale = self.wiki.makale(basliklar[0], dil) if basliklar else None
            except AramaHatasi as exc:
                yield f"Wikipedia ({dil}) okunamadı: {kisa(exc)}"
                continue
            if not makale or url_anahtari(makale["url"]) in self._gorulen:
                continue
            sayac[dil] = sayac.get(dil, 0) + 1
            kaynak = self._kaynak_ekle(makale["baslik"], makale["url"], makale["metin"],
                                       makale["saglayici"], sinir=WIKI_KARAKTER)
            yield f"Wikipedia ({dil}) · {makale['baslik']} · K{kaynak['no']}"

    def _web_turu(self, sorgular):
        """Sorguları ara ve yeni kaynakları ekle.

        Kaynak sınırı sorulara **eşit** bölünür: ilk sorular bütün kotayı doldurup son
        soruları (çoğu zaman görsel detaylar) aramasız bırakmasın.
        """
        sinir = self.ayar["kaynak"]
        for sira, sorgu in enumerate(sorgular, 1):
            self._dur_mu()
            web_sayisi = sum(1 for k in self.kaynaklar if not k["saglayici"].startswith("Wikipedia"))
            if web_sayisi >= sinir:
                yield f"Kaynak sınırına ulaşıldı ({sinir}); kalan sorgular atlandı."
                return
            pay = max(2, -(-(sinir - web_sayisi) // (len(sorgular) - sira + 1)))
            self.kullanilan_sorgular.add(sade(sorgu["sorgu"]))
            sonuclar, servis = self.arama.ara(sorgu["sorgu"], self.ayar["sonuc"], sorgu["dil"],
                                              bildir=self._notlar.append)
            yield from self._notlari_bosalt()
            if not servis:
                yield f"Arama {sira}/{len(sorgular)} · sonuç yok · {sorgu['sorgu']}"
                continue
            eklenen = 0
            for kayit in sonuclar:
                self._dur_mu()
                url = kayit["url"]
                if (url_anahtari(url) in self._gorulen
                        or any(alan_adi(url).endswith(alan) for alan in ATLANAN_ALANLAR)):
                    continue
                if eklenen >= pay or web_sayisi + eklenen >= sinir:
                    break
                metin, okuyucu = kayit["metin"], ""
                if len(metin) < KISA_METIN:
                    okunan, okuyucu = self.okuyucu(url, self.jina_anahtari)
                    if len(okunan) > len(metin):
                        metin = okunan
                    else:
                        okuyucu = ""
                if len(metin) < EN_AZ_METIN:
                    metin = "\n".join(p for p in (metin, kayit["ozet"]) if p)
                if len(metin) < EN_AZ_METIN:
                    self._gorulen.add(url_anahtari(url))
                    continue
                self._kaynak_ekle(kayit["baslik"], url, metin, kayit["saglayici"], okuyucu,
                                  ek_anahtar=sorgu["soru"])
                eklenen += 1
            yield (f"Arama {sira}/{len(sorgular)} · {ETIKETLER.get(servis, servis)} · "
                   f"{eklenen} yeni kaynak · {sorgu['sorgu']}")

    def _paketler(self, kaynaklar):
        paket, boy = [], 0
        for kaynak in kaynaklar:
            uzunluk = len(kaynak["metin"])
            if paket and boy + uzunluk > PAKET_KARAKTER:
                yield paket
                paket, boy = [], 0
            paket.append(kaynak)
            boy += uzunluk
        if paket:
            yield paket

    def _bilgi_cikar(self, kaynaklar):
        sistem = istemler.BILGI.format(dil=DILLER[self.dil])
        sorular = "\n".join(f"- {s['soru']}" for s in self.sorular)
        paketler = list(self._paketler(kaynaklar))
        for sira, paket in enumerate(paketler, 1):
            gecerli = {k["no"] for k in paket}
            metin = "\n\n".join(f"[K{k['no']}] {k['baslik']} ({k['url']})\n{k['metin']}"
                                for k in paket)
            veri = self._json(sistem, f"Topic: {self.konu}\n\nResearch questions:\n{sorular}"
                                      f"\n\nSources:\n\n{metin}", kurtar=_bilgileri_kurtar)
            yield from self._notlari_bosalt()
            yeni = 0
            for oge in (veri or {}).get("bilgiler") or []:
                if not isinstance(oge, dict) or not str(oge.get("bilgi") or "").strip():
                    continue
                nolar = [n for n in _sayi_listesi(oge.get("kaynak")) if n in gecerli]
                if not nolar:
                    continue          # kaynaksız bilgi rapora girmez
                self.bilgiler.append({"bilgi": str(oge["bilgi"]).strip(), "kaynak": nolar,
                                      "tur": str(oge.get("tur") or "diger").strip().lower(),
                                      "kesinlik": str(oge.get("kesinlik") or "kesin").strip().lower()})
                yeni += 1
            aralik = f"K{paket[0]['no']}–K{paket[-1]['no']}" if len(paket) > 1 else f"K{paket[0]['no']}"
            yield (f"Bilgi çıkarma {sira}/{len(paketler)} · {aralik} · {yeni} bilgi"
                   + ("" if veri else " · ⚠ yanıt okunamadı"))

    def _bosluk(self):
        """Cevapsız sorular için yeni sorgular; yeterliyse boş liste."""
        adet = max(2, self.ayar["soru"] // 2)
        sorular = "\n".join(f"- {s['soru']}" for s in self.sorular)
        bilgiler = "\n".join(f"- {b['bilgi']} ({len(b['kaynak'])} kaynak)" for b in self.bilgiler)
        kullanilan = "\n".join(f"- {s}" for s in sorted(self.kullanilan_sorgular))
        veri = self._json(istemler.BOSLUK.format(dil=DILLER[self.dil], adet=adet),
                          f"Topic: {self.konu}\n\nResearch questions:\n{sorular}\n\n"
                          f"Used queries:\n{kullanilan}\n\nFacts:\n{bilgiler or '(none)'}") or {}
        self.cevapsiz = [str(c).strip() for c in veri.get("cevapsiz") or [] if str(c).strip()]
        yeni = []
        for oge in veri.get("sorgular") or []:
            sorgu = str((oge or {}).get("sorgu") if isinstance(oge, dict) else oge or "").strip()
            if not sorgu or sade(sorgu) in self.kullanilan_sorgular:
                continue
            dil = "en" if isinstance(oge, dict) and str(oge.get("dil")).lower().startswith("en") else "tr"
            yeni.append({"soru": str(oge.get("neden") or sorgu) if isinstance(oge, dict) else sorgu,
                         "sorgu": sorgu, "dil": dil, "bakis": "boşluk"})
        return yeni[:adet]

    def _sentezle(self):
        satirlar = "\n".join(
            f"{i}. {b['bilgi']}"
            + {"rivayet": " (legend)", "tartismali": " (disputed)"}.get(b["kesinlik"], "")
            + f" [{', '.join(f'K{n}' for n in b['kaynak'])}]"
            for i, b in enumerate(self.bilgiler, 1))
        self.sentez = self._json(istemler.SENTEZ.format(dil=DILLER[self.dil]),
                                 f"Topic: {self.konu}\n\nFacts:\n{satirlar}")

    # ------------------------------------------------------------------ akış

    def adimlar(self):
        """Araştırmayı yürüt; her adımda bir durum satırı üret. Bitince `self.sonuc` dolar."""
        if not self.konu:
            raise ValueError("Araştırılacak konuyu yaz.")
        baslangic = datetime.now()
        yield (f"Plan hazırlanıyor · {self.ai.label} · {self.ai.model} · "
               f"{self.ayar['etiket']} · arama: {self.arama.ozet()}")
        self._planla()
        yield from self._notlari_bosalt()
        if not self.plan:
            yield "⚠ Plan yazılamadı; konu doğrudan aranacak."
        yield (f"Plan: {self.plan.get('baslik') or self.konu} · {len(self.sorular)} soru"
               + (f" · {self.plan.get('donem')}" if self.plan.get("donem") else ""))

        yield from self._wikipedia()
        sorgular = list(self.sorular)
        for tur in range(1, self.ayar["tur"] + 1):
            yield f"── Tur {tur}/{self.ayar['tur']} · {len(sorgular)} sorgu ──"
            onceki = len(self.kaynaklar) if tur > 1 else 0
            yield from self._web_turu(sorgular)
            yeni_kaynaklar = self.kaynaklar[onceki:]
            if yeni_kaynaklar:
                yield from self._bilgi_cikar(yeni_kaynaklar)
            if tur >= self.ayar["tur"]:
                break
            yield "Boşluk kontrolü · cevapsız sorular aranıyor…"
            sorgular = self._bosluk()
            yield from self._notlari_bosalt()
            if not sorgular:
                yield "Boşluk kontrolü · kapsam yeterli, ek tur gerekmedi."
                break
            self.sorular.extend(sorgular)

        if not self.bilgiler:
            raise RuntimeError("Hiç kaynaklı bilgi toplanamadı. Arama servislerini ve yapay "
                               "zekâ hesaplarını kontrol et.")
        yield f"Sentez yazılıyor · {len(self.bilgiler)} bilgi · {len(self.kaynaklar)} kaynak…"
        self._sentezle()
        yield from self._notlari_bosalt()
        if not self.sentez:
            yield "⚠ Sentez yazılamadı; rapor kaynaklı ham bilgilerle kaydedilecek."

        sure = int((datetime.now() - baslangic).total_seconds())
        aramalar = ", ".join(f"{ETIKETLER.get(s, s)} {n}" for s, n in self.arama.sayac.items())
        bilgi_satiri = (f"Tarih: {baslangic:%d.%m.%Y %H:%M} · {self.ayar['etiket']} · "
                        f"Yapay zekâ: {self.ai.label} · {self.ai.model} · "
                        f"Arama: {aramalar or 'yalnızca Wikipedia'} · "
                        f"{len(self.kaynaklar)} kaynak · {len(self.bilgiler)} bilgi · {sure} sn")
        metin = rapor.metin_olustur(self.konu, self.plan, self.sentez, self.bilgiler,
                                    self.kaynaklar, bilgi_satiri, self.cevapsiz)
        veri = {"konu": self.konu, "derinlik": self.derinlik, "dil": self.dil,
                "yapay_zeka": {"servis": self.ai.provider, "model": self.ai.model},
                "plan": self.plan, "sorular": self.sorular, "sentez": self.sentez,
                "bilgiler": self.bilgiler, "cevapsiz": self.cevapsiz, "kaynaklar": self.kaynaklar}
        txt, jsn = rapor.kaydet(rapor.dosya_adi(self.plan.get("baslik") or self.konu, baslangic),
                                metin, veri)
        baslik = ((self.sentez or {}).get("baslik") or self.plan.get("baslik") or self.konu)
        self.sonuc = {"metin": metin, "txt": txt, "json": jsn, "baslik": str(baslik).strip()}
        yield f"Tamamlandı · {sure} sn · {txt}"
