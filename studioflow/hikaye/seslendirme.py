"""Seslendirme metni: kayıtlı bir araştırmadan, şablona ve hedef süreye göre anlatım yazar.

**Ses üretmez**; yalnızca seslendirilecek metni yazar.

Akış (her adım bir durum satırı üretir):

1. **Bölüm planı** (kod) — şablonun bölümleri hedef süreye göre zamanlanır, her bölüme
   kelime bütçesi verilir (`sablonlar.bolum_plani`; saniyede 2,5 kelime).
2. **Hikâye planı** (yapay zekâ) — araştırma raporundan yapı (merak / gerilim / beklenti
   bozma), kanca türü, kancanın açtığı soru, merkezdeki insan ve amacı, doruğa saklanacak
   sürpriz ve her bölümde anlatılacak kaynaklı bilgiler.
3. **Bölüm bölüm yazım** — her bölüm ayrı istekle, önceki bölümlerin devamı olarak yazılır.
   Bütçeden çok saparsa (uzun ya da çok kısa) bir kez yeniden yazdırılır.
4. **Kontrol** (kod) — strateji belgesinin yayın öncesi listesinden otomatik
   denetlenebilenler: ilk cümlede selamlama yok, kanca ≤ 12 kelime, toplam kelime hedefe
   yakın, her bölüm yazıldı, kullanılan bilgilerin kaynağı var.
5. **Türkçe önizleme** — metin başka dilde yazıldıysa Türkçeye çevrilir (yalnızca okumak
   için; seslendirilmez).
6. **Yedek kayıt** — `outputs/seslendirme/`: `<ad>.txt` yalnızca seslendirilecek metin,
   `<ad> - rapor.txt` plan + bölümler + doğrulama listesi + kontrol listesi (panelde
   gösterilmez, arka planda kalır), `<ad>.json` ham veri. Kullanıcı metni ad vererek
   `SESLENDIRMELER` kütüphanesine kaydeder; ses aşaması girdisini oradan seçer.

Bölümler ayrı ayrı yazılır ama **tek, kesintisiz bir metin** olarak birleştirilir
(`metni_birlestir`): boşluklar ve bölüm sonlarındaki noktalama kodla da düzeltilir.
"""
import json
import re
from datetime import datetime

from studioflow.cekirdek.metin import kelime_sayisi
from studioflow.cekirdek.yollar import OUTPUTS
from studioflow.hikaye import istemler, kayitlar, sablonlar
from studioflow.hikaye.rapor import kaynak_etiketi
from studioflow.hikaye.yanit import YapayZekaIsi
from studioflow.proje.sahneleme import KELIME_HIZI
from studioflow.saglayicilar.metin_ai import HesapliMetin

KLASOR = OUTPUTS / "seslendirme"

# Ad verilerek kaydedilen seslendirme metinleri (ses aşamasının girdisi).
SESLENDIRMELER = kayitlar.Kutuphane(lambda: KLASOR / "kayitli", "seslendirme")

DILLER = {"tr": "Turkish", "en": "English"}

# Yapay zekâya giden araştırma raporunun üst sınırı (karakter).
RAPOR_SINIRI = 60000

# Bütçeden bu oranların dışına çıkan bölüm bir kez yeniden yazdırılır.
UZUN_ORAN, KISA_ORAN = 1.25, 0.6

# İlk cümlede olmaması gereken boş girişler (strateji 6.2 · kanca kuralları).
SELAMLAMALAR = ("merhaba", "selam", "bugün size", "bugün sizlere", "bu videoda", "hiç düşündünüz mü",
                "hiç merak ettiniz mi", "hello", "hi everyone", "hey guys", "today we", "today i",
                "in this video", "have you ever wondered")


def ilk_cumle(metin):
    parca = re.split(r"(?<=[.!?…])\s+", (metin or "").strip(), maxsplit=1)
    return parca[0] if parca else ""


def kaynaklar_bolumu(rapor_metni):
    """Araştırma raporunun `## KAYNAKLAR` bölümü (K numaralarının karşılığı)."""
    eslesme = re.search(r"^## KAYNAKLAR\s*\n(.*?)(?=^## |\Z)", rapor_metni or "", re.S | re.M)
    return eslesme.group(1).strip() if eslesme else ""


def noktalama_duzelt(metin):
    """Boşlukları tekleştir, noktalamadan önceki ve açılan tırnak/parantezden sonraki boşluğu sil.

    Noktadan **sonra** boşluk eklenmez: "M.Ö." ve "3.5" gibi yazımlar bozulurdu.
    """
    metin = re.sub(r"\s+", " ", str(metin or "")).strip()
    metin = re.sub(r"\s+([,.;:!?…%)\]”’])", r"\1", metin)
    return re.sub(r"([(\[“‘])\s+", r"\1", metin)


def metni_birlestir(parcalar):
    """Bölüm metinlerini tek, kesintisiz bir seslendirme metnine dönüştür.

    Cümle bitiş işaretiyle bitmeyen bölüme nokta eklenir; bilerek virgülle ya da
    noktalı virgülle bitirilen (ilk cümleye bağlanan döngü) son cümleye dokunulmaz.
    """
    temiz = []
    for parca in parcalar:
        parca = noktalama_duzelt(parca)
        if not parca:
            continue
        if parca[-1].isalnum() or parca[-1] in "\"'”’)":
            parca += "."
        temiz.append(parca)
    return noktalama_duzelt(" ".join(temiz))


def turkce_onizleme(ai, metin, bildir=None):
    """Seslendirme metninin Türkçe çevirisi (yalnızca okumak için; seslendirilmez)."""
    if not (metin or "").strip():
        return ""
    return noktalama_duzelt(ai.metin(istemler.CEVIRI, metin, json_modu=False, bildir=bildir))


def _metni_kurtar(cevap):
    """Kesik yanıttan `"metin": "..."` alanını kurtar (tırnak kapanmadıysa sonuna kadar)."""
    eslesme = re.search(r'"metin"\s*:\s*"((?:[^"\\]|\\.)*)', cevap or "", re.S)
    if not eslesme:
        return None
    try:
        metin = json.loads(f'"{eslesme.group(1)}"')
    except ValueError:
        metin = eslesme.group(1)
    return {"metin": metin} if metin.strip() else None


class SeslendirmeYazari(YapayZekaIsi):
    """Tek bir seslendirme metni. `adimlar()` durum satırları üretir; bitince `sonuc` dolar."""

    def __init__(self, arastirma_adi, rapor_metni, sablon=sablonlar.VARSAYILAN_SABLON,
                 alt=sablonlar.VARSAYILAN_ALT, sure=sablonlar.VARSAYILAN_SURE,
                 provider="gemini", model="", dil="tr", *, ai=None, iptal=None, klasor=None):
        self.arastirma_adi = str(arastirma_adi or "").strip()
        self.rapor_metni = str(rapor_metni or "").strip()
        self.sablon, self.alt = sablon, alt
        self.sablon_bilgisi = sablonlar.alt_sablon(sablon, alt)
        self.sure = sablonlar.sure_sinirla(sure)
        self.dil = dil if dil in DILLER else "tr"
        self.iptal = iptal
        self.ai = ai or HesapliMetin(provider, model, bekle=self._bekle)
        self.klasor = klasor or KLASOR
        self.bolumler = sablonlar.bolum_plani(sablon, alt, self.sure)
        self.plan = {}
        self.yazilan = []          # [{ad, etiket, bas, son, kelime, metin, yazilan_kelime, kullanilan}]
        self.kontroller = []       # [(durum, açıklama)]; durum: ✅ ⚠ ☐
        self.ceviri = ""           # Türkçe önizleme (metin Türkçe değilse)
        self.sonuc = None
        self._notlar = []

    # ------------------------------------------------------------------ adımlar

    def _bolum_listesi(self):
        return "\n".join(f"{i}. {b['ad']} ({b['etiket']}) · {b['bas']:g}-{b['son']:g} s · "
                         f"~{b['kelime']} words · {b['gorev']}"
                         for i, b in enumerate(self.bolumler, 1))

    def _rapor(self):
        return self.rapor_metni[:RAPOR_SINIRI]

    def _planla(self):
        sistem = istemler.SES_PLAN.format(sure=self.sure, dil=DILLER[self.dil],
                                          kurallar=self.sablon_bilgisi["kurallar"],
                                          bolumler=self._bolum_listesi())
        self.plan = self._json(sistem, f"Research report:\n\n{self._rapor()}") or {}

    def _bolum_plani(self, ad):
        for oge in self.plan.get("bolumler") or []:
            if isinstance(oge, dict) and oge.get("ad") == ad:
                return oge
        return {}

    def _ust_sinir(self, bolum):
        return max(bolum["kelime"] + 3, round(bolum["kelime"] * UZUN_ORAN))

    def _yaz(self, bolum):
        ust = self._ust_sinir(bolum)
        if bolum["ad"] == "kanca":
            ust = min(ust, 12)
        sistem = istemler.SES_PARCA.format(
            dil=DILLER[self.dil], kurallar=self.sablon_bilgisi["kurallar"], etiket=bolum["etiket"],
            bas=bolum["bas"], son=bolum["son"], kelime=bolum["kelime"], ust=ust, gorev=bolum["gorev"])
        onceki = "\n\n".join(y["metin"] for y in self.yazilan) or "(nothing yet: this is the start)"
        kullanici = (f"PLAN:\n{json.dumps(self.plan, ensure_ascii=False, indent=1)}\n\n"
                     f"THIS SECTION'S PLAN:\n"
                     f"{json.dumps(self._bolum_plani(bolum['ad']), ensure_ascii=False)}\n\n"
                     f"NARRATION WRITTEN SO FAR:\n{onceki}\n\n"
                     f"RESEARCH REPORT:\n\n{self._rapor()}")
        veri = self._json(sistem, kullanici, kurtar=_metni_kurtar) or {}
        metin = re.sub(r"\s+", " ", str(veri.get("metin") or "")).strip()
        kullanilan = [k for k in veri.get("kullanilan") or [] if isinstance(k, dict) and k.get("ifade")]
        adet = kelime_sayisi(metin)
        if metin and (adet > ust or adet < bolum["kelime"] * KISA_ORAN):
            duzelt = self._json(
                istemler.SES_UZUNLUK.format(dil=DILLER[self.dil], kelime=bolum["kelime"], ust=ust),
                f"TEXT BEFORE THIS SECTION:\n{onceki}\n\nSECTION TO REWRITE ({adet} words):\n{metin}",
                kurtar=_metni_kurtar) or {}
            yeni = re.sub(r"\s+", " ", str(duzelt.get("metin") or "")).strip()
            # Yeniden yazım hedefe daha yakınsa o tutulur.
            if yeni and abs(kelime_sayisi(yeni) - bolum["kelime"]) < abs(adet - bolum["kelime"]):
                self._notlar.append(f"{bolum['etiket']} bütçeye göre yeniden yazıldı "
                                    f"({adet} → {kelime_sayisi(yeni)} kelime).")
                metin, adet = yeni, kelime_sayisi(yeni)
        self.yazilan.append({**{k: bolum[k] for k in ("ad", "etiket", "bas", "son", "kelime")},
                             "metin": metin, "yazilan_kelime": adet, "kullanilan": kullanilan})

    def _kontrol_et(self):
        metin = self.seslendirme_metni()
        ilk = ilk_cumle(metin)
        ilk_kucuk = ilk.lower()
        hedef = sum(b["kelime"] for b in self.bolumler)
        toplam = kelime_sayisi(metin)
        k = self.kontroller
        k.append(("✅" if not any(s in ilk_kucuk for s in SELAMLAMALAR) else "⚠",
                  "İlk cümle hikâyenin kendisi (selamlama / boş giriş yok)"))
        k.append(("✅" if 0 < kelime_sayisi(ilk) <= 12 else "⚠",
                  f"İlk cümle en fazla 12 kelime ({kelime_sayisi(ilk)} kelime)"))
        k.append(("✅" if re.search(r"\d|[A-ZÇĞİÖŞÜ][a-zçğıöşü]+", ilk[1:] if ilk else "") else "⚠",
                  "İlk cümlede somut bir isim, tarih ya da sayı var"))
        k.append(("✅" if all(y["metin"] for y in self.yazilan) else "⚠",
                  f"Bölümlerin hepsi yazıldı ({len(self.yazilan)})"))
        k.append(("✅" if abs(toplam - hedef) <= hedef * 0.15 else "⚠",
                  f"Kelime sayısı hedefe uygun ({toplam} / ~{hedef}; ±%15)"))
        kaynaksiz = [x["ifade"] for y in self.yazilan for x in y["kullanilan"] if not x.get("kaynak")]
        k.append(("✅" if not kaynaksiz else "⚠",
                  "Kullanılan her tarih/sayı/isim kaynaklı" if not kaynaksiz
                  else f"Kaynağı belirtilmeyen ifadeler: {', '.join(map(str, kaynaksiz[:6]))}"))
        k.append(("☐", "En büyük sürpriz doruğa saklandı mı? (planda: "
                       f"{(self.plan.get('surpriz') or {}).get('detay', '—')})"))
        k.append(("☐", f"Kancadaki soru sonuçta açıkça cevaplandı mı? ({self.plan.get('acilan_soru', '—')})"))
        k.append(("☐", "Rivayet / tartışmalı bilgiler metinde öyle belirtildi mi?"))
        k.append(("☐", "Tüm tarih, sayı ve isimler bağımsız bir kaynaktan doğrulandı mı?"))

    # ------------------------------------------------------------------ çıktı

    def seslendirme_metni(self):
        return metni_birlestir(y["metin"] for y in self.yazilan)

    def _rapor_metni(self, zaman):
        metin = self.seslendirme_metni()
        toplam = kelime_sayisi(metin)
        hedef = sum(b["kelime"] for b in self.bolumler)
        sablon = f"{sablonlar.SABLONLAR[self.sablon]['etiket']} › {self.sablon_bilgisi['etiket']}"
        s = [f"# SESLENDİRME · {self.arastirma_adi}",
             f"Tarih: {zaman:%d.%m.%Y %H:%M} · Şablon: {sablon} · Dil: {DILLER[self.dil]} · "
             f"Yapay zekâ: {self.ai.label} · {self.ai.model}",
             f"Hedef: {self.sure:g} sn (~{hedef} kelime) · Yazılan: {toplam} kelime "
             f"(~{toplam / KELIME_HIZI:.0f} sn)", "", "## SESLENDİRME METNİ", metin, "",
             "## BÖLÜMLER"]
        for y in self.yazilan:
            s.append(f"### {y['etiket']} · {y['bas']:g}–{y['son']:g} sn · "
                     f"{y['yazilan_kelime']}/{y['kelime']} kelime")
            s.append(y["metin"] or "⚠ yazılamadı")
        plan = self.plan
        surpriz = plan.get("surpriz") or {}
        s += ["", "## PLAN",
              f"- Yapı: {plan.get('yapi', '—')} — {plan.get('yapi_nedeni', '')}",
              f"- Kanca türü: {plan.get('kanca_turu', '—')}",
              f"- Açılan soru: {plan.get('acilan_soru', '—')}",
              f"- İnsan ve amacı: {plan.get('insan', '—')}",
              f"- Doruktaki sürpriz: {surpriz.get('detay', '—')}{kaynak_etiketi(surpriz.get('kaynak'))}",
              f"- Cevap: {plan.get('cevap', '—')}",
              f"- Son cümle fikri: {plan.get('son_cumle', '—')}",
              "", "## DOĞRULAMA LİSTESİ (seslendirilmez)"]
        for y in self.yazilan:
            for x in y["kullanilan"]:
                nolar = [n for n in x.get("kaynak") or [] if isinstance(n, int)]
                s.append(f"- {x['ifade']}{kaynak_etiketi(nolar) or ' ⚠ kaynak yok'} · {y['etiket']}")
        s += ["", "## KONTROL LİSTESİ (✅ otomatik geçti · ⚠ bak · ☐ elle kontrol et)"]
        s += [f"{durum} {aciklama}" for durum, aciklama in self.kontroller]
        kaynak = kaynaklar_bolumu(self.rapor_metni)
        if kaynak:
            s += ["", f"## KAYNAKLAR (araştırma: {self.arastirma_adi})", kaynak]
        return "\n".join(s).rstrip() + "\n"

    def _kaydet(self, zaman):
        ad = kayitlar.ad_temizle(f"{self.arastirma_adi} · {self.sure:g} sn · {zaman:%Y%m%d_%H%M%S}")
        self.klasor.mkdir(parents=True, exist_ok=True)
        txt = self.klasor / f"{ad}.txt"
        rapor_txt = self.klasor / f"{ad} - rapor.txt"
        jsn = self.klasor / f"{ad}.json"
        txt.write_text(self.seslendirme_metni() + "\n", encoding="utf-8")
        rapor_txt.write_text(self._rapor_metni(zaman), encoding="utf-8")
        jsn.write_text(json.dumps({
            "arastirma": self.arastirma_adi, "sablon": [self.sablon, self.alt], "sure": self.sure,
            "dil": self.dil, "yapay_zeka": {"servis": self.ai.provider, "model": self.ai.model},
            "bolum_plani": [{k: v for k, v in b.items() if k != "gorev"} for b in self.bolumler],
            "plan": self.plan, "bolumler": self.yazilan, "metin": self.seslendirme_metni(),
            "ceviri": self.ceviri, "rapor": str(rapor_txt),
            "kontroller": [list(k) for k in self.kontroller]}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return txt, rapor_txt, jsn

    # ------------------------------------------------------------------ akış

    def adimlar(self):
        if not self.rapor_metni:
            raise ValueError("Önce kayıtlı bir araştırma seç.")
        zaman = datetime.now()
        hedef = sum(b["kelime"] for b in self.bolumler)
        yield (f"Bölüm planı · {self.sure:g} sn · ~{hedef} kelime · "
               + " → ".join(f"{b['etiket']} {b['bas']:g}–{b['son']:g} sn" for b in self.bolumler))
        yield f"Hikâye planı yazılıyor · {self.ai.label} · {self.ai.model}…"
        self._planla()
        yield from self._notlari_bosalt()
        if self.plan:
            yield (f"Plan · yapı: {self.plan.get('yapi', '—')} · kanca: "
                   f"{self.plan.get('kanca_turu', '—')} · soru: {self.plan.get('acilan_soru', '—')}")
        else:
            yield "⚠ Hikâye planı yazılamadı; bölümler yalnızca şablon kurallarıyla yazılacak."
        for bolum in self.bolumler:
            self._dur_mu()
            yield f"{bolum['etiket']} yazılıyor · hedef ~{bolum['kelime']} kelime…"
            self._yaz(bolum)
            yield from self._notlari_bosalt()
            son = self.yazilan[-1]
            yield (f"{son['etiket']} · {son['yazilan_kelime']}/{son['kelime']} kelime"
                   + ("" if son["metin"] else " · ⚠ yazılamadı"))
        if not self.seslendirme_metni():
            raise RuntimeError("Hiçbir bölüm yazılamadı. Yapay zekâ hesaplarını kontrol et.")
        self._kontrol_et()
        if self.dil != "tr":
            self._dur_mu()
            yield "Türkçe önizleme çevriliyor…"
            try:
                self.ceviri = turkce_onizleme(self.ai, self.seslendirme_metni(),
                                              bildir=self._notlar.append)
            except Exception as exc:
                self._notlar.append(f"⚠ Türkçe önizleme çevrilemedi: {str(exc)[:160]}")
            yield from self._notlari_bosalt()
        txt, rapor_txt, jsn = self._kaydet(zaman)
        toplam = kelime_sayisi(self.seslendirme_metni())
        uyari = sum(1 for durum, _a in self.kontroller if durum == "⚠")
        self.sonuc = {"metin": self.seslendirme_metni(), "ceviri": self.ceviri,
                      "rapor": rapor_txt.read_text(encoding="utf-8"),
                      "txt": txt, "rapor_txt": rapor_txt, "json": jsn,
                      "onerilen_ad": kayitlar.ad_temizle(
                          f"{self.arastirma_adi} · {self.sure:g} sn · {self.dil}")}
        yield (f"Tamamlandı · {toplam} kelime (~{toplam / KELIME_HIZI:.0f} sn) · "
               f"{uyari} uyarı · {txt}")
