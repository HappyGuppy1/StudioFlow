"""Proje sekmesi · Ses efektleri: hazırlama (yapay zekâ / manuel) geri çağrıları.

Hazırlama uzun sürer (plan, Freesound araması, seçim, indirme); geri çağrılar
üreteçtir ve her adımda durum kutusunu tazeler. Ara adımlarda yalnızca durum metni
değişir, diğer çıktılar `gr.skip()` ile olduğu gibi kalır; iş bitince paket
`efekt_ekleme.efekt_durum_paketi` ile bir kez kurulur (liste, seçim, önizleme, proje
görünümü).
"""
import html
from urllib.parse import quote

import gradio as gr

from studioflow.proje.katmanlar.efekt_duzenleme import katman_koy, yz_ses_bul
from studioflow.proje.katmanlar.efekt_ekleme import efekt_durum_paketi, efekt_listesi
from studioflow.proje.katmanlar.efekt_hazirlama import efekt_hazirla

# Efekt çıktı paketinin uzunluğu: durum + liste damgası + seçim + seviye + önizleme +
# proje görünümü (5 alan). Bkz. `efekt_ekleme.efekt_paketi`.
PAKET_UZUNLUGU = 10

PJ_EFEKT_HAZIR = ("Ses efektleri hazır değil. **Yapay zekâ hazırlasın**'a bas ya da "
                  "**manuel hazırla** ile her sahneye istediğin sesi yaz.")
PJ_UR_EFEKT_HAZIR = "Kayıtlı bir ses efekti seç ve videoya göm."


def _ara_paket(satirlar):
    return ("\n".join(satirlar),) + tuple(gr.skip() for _ in range(PAKET_UZUNLUGU - 1))


def _hazirla(ad, yontem, istekler, isim, servis):
    satirlar = []
    for olay in efekt_hazirla(ad, yontem, istekler, isim, servis):
        if olay[0] == "durum":
            satirlar.append("⏳ " + olay[1])
            yield _ara_paket(satirlar)
        elif olay[0] == "hata":
            yield efekt_durum_paketi(ad, "\n".join(satirlar + ["❌ " + olay[1]]))
            return
        else:
            _tur, kayit, mesaj = olay
            yield efekt_durum_paketi(ad, "✅ " + mesaj)
            return


def pj_efekt_yz_hazirla(ad, isim, servis):
    """**Yapay zekâ hazırlasın**: hangi sahnede ne sesi olacağına yapay zekâ karar verir."""
    yield from _hazirla(ad, "yapay_zeka", None, isim, servis)


def pj_efd_kayitlari(ad, secili=None):
    """Düzenleyicinin kayıt listesi: seçim listede yoksa ilk kayda düşer."""
    adlar = [k["ad"] for k in efekt_listesi(ad)]
    return gr.update(choices=adlar, value=secili if secili in adlar else
                     (adlar[0] if adlar else None))


def oynatici(kaynak, yukseklik=34):
    """Küçük ses çalar (HTML `<audio>`): büyük dalga kutusu yerine tek satır.

    `kaynak` yerel dosya ise Gradio'nun dosya ucundan (proje klasörü `allowed_paths`'te),
    `http` adresi ise doğrudan çalınır (Freesound önizlemesi, indirmeden).
    """
    if not kaynak:
        return '<span style="opacity:.6">— ses yok</span>'
    kaynak = str(kaynak)
    adres = kaynak if kaynak.startswith("http") else (
        "/gradio_api/file=" + quote(kaynak.replace("\\", "/"), safe=":/"))
    return (f'<audio controls preload="none" src="{html.escape(adres, quote=True)}" '
            f'style="width:100%;height:{yukseklik}px"></audio>')


def _oneri(durum, mesaj=""):
    """Öneri alanı: sıradaki aday (çalar + ad) ve Onayla / Tekrar oluştur düğmeleri."""
    adaylar, i = durum.get("adaylar") or [], int(durum.get("i") or 0)
    if not adaylar:
        return (durum, f'<div style="opacity:.75">{html.escape(mesaj or "Sonuç yok.")}</div>',
                gr.update(visible=False), gr.update(visible=False))
    aday = adaylar[i]
    mesaj = mesaj or durum.get("mesaj") or ""
    ust = ((f'<div style="font-size:11px;opacity:.65">{html.escape(mesaj)}</div>'
            if mesaj else "")
           + f'<div style="font-size:12px;opacity:.8">{i + 1}/{len(adaylar)} · '
           f'<b>{html.escape(aday["ad"])}</b> · {aday["sure"]:g} sn</div>')
    return (durum, ust + oynatici(aday["onizleme"]), gr.update(visible=True),
            gr.update(visible=len(adaylar) > 1))


def pj_efd_bul(ad, sorgu, index, tur, servis=""):
    """**Bul**: yapay zekâ isteği kütüphane sorgularına çevirir, bulunanları isteğe uyana
    göre sıralar; en iyisi önerilir (bkz. `efekt_duzenleme.yz_ses_bul`)."""
    adaylar, mesaj = yz_ses_bul(ad, sorgu, index, tur, servis)
    return _oneri({"adaylar": adaylar, "i": 0, "mesaj": mesaj}, mesaj)


def pj_efd_tekrar(durum):
    """**Tekrar oluştur**: aynı aramanın sıradaki sesi (sona gelince başa döner)."""
    durum = dict(durum or {})
    if durum.get("adaylar"):
        durum["i"] = (int(durum.get("i") or 0) + 1) % len(durum["adaylar"])
    return _oneri(durum)


PJ_EFD_ONAYLANIYOR = ("⏳ Onaylanıyor… ses indiriliyor ve efekt izi yeniden kuruluyor; "
                      "bitince liste yenilenir.")


def pj_efd_onaylaniyor():
    """Onayla'ya basılır basılmaz: satırda küçük bir "onaylanıyor" yazısı, düğmeler kilitli."""
    yazi = (f'<div style="font-size:12px;opacity:.8">{html.escape(PJ_EFD_ONAYLANIYOR)}'
            '</div>')
    return (yazi, gr.update(interactive=False), gr.update(interactive=False),
            PJ_EFD_ONAYLANIYOR)


def pj_efd_onayla(index, sira, katman):
    """**Onayla**: önerilen ses o satırdaki sesin yerine geçer (ya da boş sahneye eklenir)."""
    def onayla(ad, kayit, durum):
        adaylar, i = (durum or {}).get("adaylar") or [], int((durum or {}).get("i") or 0)
        aday = adaylar[i] if adaylar else None
        return katman_koy(ad, kayit, index, sira, aday, (katman or {}).get("tur") or "eylem",
                          (katman or {}).get("bas") or 0.0, (katman or {}).get("etiket") or "")
    onayla.__name__ = "pj_efd_onayla"
    return onayla


def pj_efekt_manuel_hazirla(indexler):
    """Manuel panelin düğmesi: sahne kutularındaki metinler `indexler` sırasıyla gelir."""
    def hazirla(ad, isim, servis, *metinler):
        istekler = {index: metin for index, metin in zip(indexler, metinler)}
        yield from _hazirla(ad, "manuel", istekler, isim, servis)
    hazirla.__name__ = "pj_efekt_manuel_hazirla"
    return hazirla
