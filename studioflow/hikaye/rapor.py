"""Araştırma raporu: sentezi ve kaynaklı bilgileri okunur bir metin dosyasına dönüştürür.

Dosyalar `outputs/arastirma/` klasörüne yazılır:

- `<tarih>_<konu>.txt` — insan için rapor (seslendirme ve prompt aşamalarının girdisi);
  kullanıcı arayüzde düzenleyip kaydedebilir.
- `<tarih>_<konu>.json` — aynı araştırmanın ham verisi (plan, bilgiler, kaynak metinleri);
  sonraki aşamalar kaynaklara geri dönebilsin diye.
"""
import json
import re
import unicodedata
from datetime import datetime

from studioflow.cekirdek.yollar import OUTPUTS

KLASOR = OUTPUTS / "arastirma"

TUR_ADLARI = {"zaman": "Zaman", "kisi": "Kişiler", "yer": "Yerler", "sayi": "Sayılar",
              "olay": "Olaylar", "teknik": "Teknik / lojistik", "gorsel": "Görsel detaylar",
              "alinti": "Alıntılar", "sonuc": "Sonuçlar", "diger": "Diğer"}


def kaynak_etiketi(nolar):
    nolar = [n for n in nolar or [] if isinstance(n, int)]
    return f" [{', '.join(f'K{n}' for n in nolar)}]" if nolar else ""


def _liste(deger):
    return deger if isinstance(deger, list) else []


def _yazi(deger):
    return str(deger or "").strip()


def _ad_aciklama(ad, aciklama):
    """`Ad — açıklama`; açıklama boşsa yalnızca ad (sonda sarkan tire kalmasın)."""
    ad, aciklama = _yazi(ad), _yazi(aciklama)
    return f"{ad} — {aciklama}" if aciklama else ad


def dosya_adi(konu, zaman=None):
    zaman = zaman or datetime.now()
    sade = unicodedata.normalize("NFKD", (konu or "").replace("ı", "i").replace("İ", "I"))
    sade = "".join(c for c in sade if not unicodedata.combining(c))
    sade = re.sub(r"[^A-Za-z0-9]+", "-", sade).strip("-").lower()[:50] or "arastirma"
    return f"{zaman:%Y%m%d_%H%M%S}_{sade}"


def metin_olustur(konu, plan, sentez, bilgiler, kaynaklar, bilgi_satiri, cevapsiz=()):
    """Raporun tam metni. `sentez` yoksa (yapay zekâ yazamadıysa) ham bilgiler yine yazılır."""
    plan = plan or {}
    sentez = sentez or {}
    baslik = _yazi(sentez.get("baslik")) or _yazi(plan.get("baslik")) or konu
    s = [f"# KONU: {baslik}", f"Girdi: {konu}", bilgi_satiri, ""]

    def bolum(ad, satirlar):
        satirlar = [satir for satir in satirlar if satir]
        if satirlar:
            s.extend([f"## {ad}", *satirlar, ""])

    if not sentez:
        s.extend(["⚠ Sentez yazılamadı; aşağıda kaynaklı ham bilgiler var.", ""])
    bolum("ÖZET", [_yazi(sentez.get("ozet")) or _yazi(plan.get("tanim"))])
    bolum("ZAMAN ÇİZELGESİ", [
        f"- {_yazi(k.get('tarih'))}: {_yazi(k.get('olay'))}{kaynak_etiketi(k.get('kaynak'))}"
        for k in _liste(sentez.get("zaman_cizelgesi")) if isinstance(k, dict) and k.get("olay")])
    bolum("KİŞİLER", [
        f"- {_ad_aciklama(k.get('ad'), k.get('rol'))}{kaynak_etiketi(k.get('kaynak'))}"
        for k in _liste(sentez.get("kisiler")) if isinstance(k, dict) and k.get("ad")])
    bolum("YERLER", [
        f"- {_ad_aciklama(k.get('ad'), k.get('aciklama'))}{kaynak_etiketi(k.get('kaynak'))}"
        for k in _liste(sentez.get("yerler")) if isinstance(k, dict) and k.get("ad")])
    bolum("KESİN BİLGİLER", [
        f"- {_yazi(k.get('bilgi'))}{kaynak_etiketi(k.get('kaynak'))}"
        for k in _liste(sentez.get("kesin_bilgiler")) if isinstance(k, dict) and k.get("bilgi")])
    tartisma = []
    for k in _liste(sentez.get("tartismali")):
        if not isinstance(k, dict) or not k.get("konu"):
            continue
        tartisma.append(f"- {_yazi(k.get('konu'))} ⚠")
        tartisma.extend(f"    • {_yazi(g.get('gorus'))}{kaynak_etiketi(g.get('kaynak'))}"
                        for g in _liste(k.get("gorusler")) if isinstance(g, dict) and g.get("gorus"))
    bolum("TARTIŞMALI / RİVAYET", tartisma)
    bolum("GÖRSEL DETAYLAR (prompt aşaması için)", [
        f"- {_yazi(k.get('konu'))}: {_yazi(k.get('detay'))}{kaynak_etiketi(k.get('kaynak'))}"
        for k in _liste(sentez.get("gorsel_detaylar")) if isinstance(k, dict) and k.get("detay")])
    bolum("ANLATIM ÖNERİLERİ (kanca ve dramatik anlar)",
          [f"- {_yazi(k)}" for k in _liste(sentez.get("anlatim_onerileri")) if _yazi(k)])
    bolum("CEVAPSIZ KALAN SORULAR", [f"- {_yazi(k)}" for k in cevapsiz if _yazi(k)])

    gruplar = {}
    for bilgi in bilgiler:
        gruplar.setdefault(bilgi.get("tur") or "diger", []).append(bilgi)
    ham = []
    for tur in [*TUR_ADLARI, *[t for t in gruplar if t not in TUR_ADLARI]]:
        if tur not in gruplar:
            continue
        ham.append(f"### {TUR_ADLARI.get(tur, tur)}")
        for bilgi in gruplar[tur]:
            isaret = {"rivayet": " (rivayet)", "tartismali": " ⚠ tartışmalı"}.get(
                bilgi.get("kesinlik"), "")
            ham.append(f"- {bilgi['bilgi']}{isaret}{kaynak_etiketi(bilgi.get('kaynak'))}")
    bolum("TÜM BİLGİLER (kaynaklı ham liste)", ham)
    bolum("KAYNAKLAR", [
        f"[K{k['no']}] {k['baslik']} — {k['url']}  ({k['saglayici']}"
        f"{' · ' + k['okuyucu'] if k.get('okuyucu') else ''})" for k in kaynaklar])
    return "\n".join(s).rstrip() + "\n"


def kaydet(ad, metin, veri, klasor=None):
    """Raporu ve ham veriyi yaz; `(txt yolu, json yolu)` döndürür."""
    klasor = klasor or KLASOR
    klasor.mkdir(parents=True, exist_ok=True)
    txt, jsn = klasor / f"{ad}.txt", klasor / f"{ad}.json"
    txt.write_text(metin, encoding="utf-8")
    jsn.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    return txt, jsn
