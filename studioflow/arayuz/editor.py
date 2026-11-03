"""Proje editörünün görünüm parçaları: sol şerit bölümleri, sahne şeridi, izler, yardım.

Proje sayfası CapCut tarzı tek ekranlı bir editördür: solda bölüm şeridi ve seçili
bölümün paneli, ortada önizleme, sağda seçili sahnenin paneli, altta sahne şeridi ve
ses/altyazı izleri. Bu modül yalnızca HTML ve küçük bileşen yardımcıları üretir; üretim
ve dosya işlemleri `proje` katmanındadır.
"""
from html import escape
from urllib.parse import quote

import gradio as gr

from studioflow.proje import depo, yonetim
from studioflow.proje.dosya import proje_oku
from studioflow.proje.katmanlar import diller, efekt_ekleme, muzik

# Sol şerit: (anahtar, etiket). Etiketteki satır sonu simgeyi yazının üstüne alır
# (CSS `white-space: pre-line`). Sıra iş akışını izler: hazırlık → içerik → sahneler →
# üretim → ses katmanları → ayarlar.
BOLUMLER = [
    ("hazirlik", "📄\nHazırlık"),
    ("metin", "📝\nMetin"),
    ("karakter", "👥\nKarakter"),
    ("sahneler", "🎞\nSahneler"),
    ("uretim", "▶\nÜretim"),
    ("seslendirme", "🎙\nSeslendirme"),
    ("dublaj", "🌐\nDublaj"),
    ("muzik", "🎵\nMüzik"),
    ("altyazi", "💬\nAltyazı"),
    ("efekt", "🔊\nEfekt"),
    ("ayarlar", "⚙\nAyarlar"),
]
BOLUM_ANAHTARLARI = [anahtar for anahtar, _etiket in BOLUMLER]
VARSAYILAN_BOLUM = "metin"
BOLUM_SECENEKLERI = [(etiket, anahtar) for anahtar, etiket in BOLUMLER]

# Şerit değişince yalnızca tarayıcıda çalışır: editör kabının `data-bolum` özniteliği
# değişir, CSS yalnızca o bölümün panelini gösterir (sunucuya istek gitmez).
BOLUM_JS = ("(bolum) => { const e = document.querySelector('.sf-editor');"
            " if (e && bolum) e.setAttribute('data-bolum', bolum); }")
# Şeritteki **Araçlar**: üst sekme çubuğundaki Araçlar sekmesine geçer.
ARACLAR_JS = ("() => { const t = [...document.querySelectorAll('button[role=tab]')]"
              ".find(b => b.textContent.trim() === 'Araçlar'); if (t) t.click(); }")
# Hazırlık bölümündeki **Prompt stüdyosunu aç**: Araçlar › Prompt sekmesine geçer.
PROMPT_STUDYOSU_JS = (
    "() => { const sekme = (ad) => [...document.querySelectorAll('button[role=tab]')]"
    ".find(b => b.textContent.trim() === ad); const a = sekme('Araçlar'); if (a) a.click();"
    " setTimeout(() => { const p = sekme('Prompt'); if (p) p.click(); }, 120); }")

_DURUM_SINIFI = {"TAMAM": "tamam", "YARIM": "yarim", "HATA": "hata"}

# Panelin başındaki tek satırlık açıklama: bölümde ne yapıldığı.
BOLUM_ACIKLAMALARI = {
    "hazirlik": "Konudan sahne planına: Prompt stüdyosu adımları.",
    "metin": "Anlatım metni, prompt katmanları ve sahne planı.",
    "karakter": "Tekrar eden karakterler ve referans görselleri.",
    "sahneler": "Kareleri incele, kare ya da klip yenile.",
    "uretim": "Prompt kapısı, görsel onayı ve ilerleme.",
    "seslendirme": "Ses servisi, ses testi ve videodaki seviye.",
    "dublaj": "Dublajı üret, kaydet ve videoya ekle.",
    "muzik": "Müziği üret ya da yükle, kaydet ve videoya ekle.",
    "altyazi": "Görünüm, dile göre kayıt ve videoya gömme.",
    "efekt": "Ses efektlerini hazırla, düzenle ve videoya göm.",
    "ayarlar": "Çıktı biçimi, üretim ayarları ve proje dosyaları.",
}


def bolum_basligi(anahtar):
    """Bölüm panelinin başlığı: şeritteki ad ve tek satırlık açıklama."""
    etiket = dict(BOLUMLER)[anahtar].replace("\n", " ")
    return (f'<div class="sf-bolum-baslik"><h2>{escape(etiket)}</h2>'
            f"<p>{escape(BOLUM_ACIKLAMALARI[anahtar])}</p></div>")


def yardim(metin, baslik="Nasıl çalışır?"):
    """Uzun açıklamayı kapalı bir ⓘ kutusuna al: başlığa tıklayınca açılır.

    Açıklamalar panelin başında paragraf paragraf duruyordu; artık yer kaplamaz,
    gereken anda okunur.
    """
    return gr.Markdown(f'<details class="sf-yardim"><summary>ⓘ {escape(baslik)}</summary>'
                       f"\n\n{metin}\n\n</details>", elem_classes=["sf-yardim-kutu"])


def durum_kutusu(deger="", etiket="Durum", elem_classes=None):
    """Durum mesajı alanı: Markdown olarak çizilir, `**kalın**` yazılar biçimlenir.

    Eskiden salt okunur metin kutusuydu ve yıldızlar olduğu gibi görünüyordu. Satır
    sonları korunur (CSS `white-space: pre-wrap`); başlık CSS'teki `data` değil sınıf
    üzerinden verilir.
    """
    return gr.Markdown(deger, label=etiket, show_label=False,
                       elem_classes=["sf-durum"] + list(elem_classes or []))


def _dosya_adresi(yol):
    """Gradio'nun izinli klasörlerden dosya sunduğu adres (proje klasörü izinlidir)."""
    return "/gradio_api/file=" + quote(str(yol).replace("\\", "/"), safe="/:")


def _sure(saniye):
    toplam = int(round(float(saniye or 0)))
    return f"{toplam // 60}:{toplam % 60:02d}"


def sahne_seridi_html(ad, secili=None):
    """Alttaki sahne şeridi: her sahne küçük resmi, süresi ve durum rengiyle.

    Genişlik sahne süresiyle orantılıdır; tıklanınca sahne sağ panelde açılır
    (tıklamayı `assets/studioflow.js` yakalar ve gizli `sf-sahne-tik` alanına yazar).
    """
    kayitlar = yonetim.gorsel_listesi(ad) if (ad or "").strip() else []
    if not kayitlar:
        return ('<div class="sf-serit bos">Sahneler burada görünür: önce '
                "<b>Projeye başlat</b>'a bas, anlatım sahnelere bölünsün.</div>")
    toplam = sum(max(kayit["sure"], 0.5) for kayit in kayitlar)
    hazir = sum(1 for kayit in kayitlar if kayit["durum"] == "TAMAM")
    ogeler = []
    for kayit in kayitlar:
        sinif = _DURUM_SINIFI.get(kayit["durum"], "bekliyor")
        if str(kayit["index"]) == str(secili):
            sinif += " secili"
        resim = (f'<img src="{_dosya_adresi(kayit["gorsel"])}" alt="" loading="lazy">'
                 if kayit["gorsel"] else '<span class="sf-serit-bos-kare"></span>')
        ipucu = escape(f"Sahne {kayit['index']} · {kayit['sure']:g} sn · {kayit['durum']}"
                       f" · {kayit['metin']}")
        ogeler.append(
            f'<button type="button" class="sf-serit-sahne {sinif}" data-sahne="{kayit["index"]}"'
            f' style="flex-grow:{max(kayit["sure"], 0.5):.2f}" title="{ipucu}">'
            f'{resim}<span class="sf-serit-no">{kayit["index"]}</span></button>')
    return (f'<div class="sf-serit-ust"><b>Sahneler</b><span>{hazir}/{len(kayitlar)} tamam · '
            f'{_sure(toplam)}</span><span class="sf-serit-lejant"><i class="tamam"></i>tamam'
            '<i class="yarim"></i>yarım<i class="hata"></i>hata<i class="bekliyor"></i>bekliyor'
            f'</span></div><div class="sf-serit" role="list">{"".join(ogeler)}</div>')


def _iz(bolum, etiket, cipler, bos):
    """Tek iz satırı: solda iz adı, sağda kayıt çipleri (videodakiler vurgulu)."""
    icerik = "".join(
        f'<span class="sf-iz-cip{" ekli" if ekli else ""}">{"✓ " if ekli else ""}'
        f"{escape(ad)}</span>" for ad, ekli in cipler) or f'<span class="sf-iz-bos">{bos}</span>'
    return (f'<div class="sf-iz" data-bolum="{bolum}" title="{escape(etiket)} bölümünü aç">'
            f'<span class="sf-iz-ad">{escape(etiket)}</span>'
            f'<span class="sf-iz-icerik">{icerik}</span></div>')


def izler_html(ad):
    """Sahne şeridinin altındaki izler: hangi ses ve altyazı kayıtları var, hangisi videoda.

    Salt görünümdür: ize tıklamak o katmanın bölümünü açar; ekleme ve kaldırma o
    bölümün düğmeleriyle yapılır.
    """
    ad = (ad or "").strip()
    klasor = depo.guvenli_klasor(ad) if ad else None
    veri = proje_oku(klasor) if klasor else None
    if veri is None:
        return '<div class="sf-izler"></div>'
    dublaj_ekli = diller.ekli_dublaj_adi(ad)
    altyazi_ekli = diller.ekli_altyazi_adi(ad)
    muzik_ekli = ({str(parca) for parca in veri.get("muzikler") or []}
                  if veri.get("muzik_ekleme") == "TAMAM" else set())
    efekt_ekli = efekt_ekleme.ekli_efekt_adi(ad)
    ses_var = (veri.get("ses") or {}).get("durum") == "TAMAM"
    satirlar = [
        _iz("seslendirme", "Seslendirme",
            [("anlatım", veri.get("ses_ekleme") == "TAMAM" and not dublaj_ekli)] if ses_var else [],
            "henüz seslendirilmedi"),
        _iz("dublaj", "Dublaj",
            [(k["ad"], k["ad"] == dublaj_ekli) for k in diller.dublaj_listesi(ad)],
            "kayıtlı dublaj yok"),
        _iz("muzik", "Müzik",
            [(k["ad"], k["ad"] in muzik_ekli) for k in muzik.muzik_listesi(ad)],
            "kayıtlı müzik yok"),
        _iz("altyazi", "Altyazı",
            [(k["ad"], k["ad"] == altyazi_ekli) for k in diller.altyazi_listesi(ad)],
            "kayıtlı altyazı yok"),
        _iz("efekt", "Efekt",
            [(k["ad"], k["ad"] == efekt_ekli) for k in efekt_ekleme.efekt_listesi(ad)],
            "kayıtlı ses efekti yok"),
    ]
    return f'<div class="sf-izler">{"".join(satirlar)}</div>'


def sahne_detayi(ad, index):
    """Sağ panel için seçili sahne: kare yolu ve bilgi satırı (`None` → seçim yok)."""
    if index in (None, ""):
        return None, "Alttaki şeritten bir sahneye tıkla: karesi, anlatımı ve prompt'u burada açılır."
    kayit = next((k for k in yonetim.gorsel_listesi(ad) if str(k["index"]) == str(index)), None)
    if kayit is None:
        return None, f"Sahne {escape(str(index))} bulunamadı; proje değişmiş olabilir."
    durum = kayit["durum"] + (" · klip var" if kayit["videolu"] else " · klip yok")
    return (kayit["gorsel"] or None,
            f"**Sahne {kayit['index']}** · {kayit['sure']:g} sn · {durum}  \n"
            f"{escape(kayit['metin'] or '—')}")
