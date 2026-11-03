"""Kelime zamanlarından okunabilir altyazı blokları; SRT/VTT yazma; metinden zaman tahmini."""
import re

from studioflow.altyazi.kural import (SUB_AYAR, SUB_BREAK_GAP, SUB_CLAUSE_END, SUB_MIN_GAP,
                                      SUB_SENTENCE_END)


def _stamp(seconds, decimal=","):
    """Saniyeyi SRT/VTT zaman damgasına çevir.

    Hesap tamamen milisaniye üzerinden yapılır: ondalık kısımdan yuvarlama
    `00:00:01,1000` gibi geçersiz bir damga üretebiliyordu (ör. 1,9996 sn).
    """
    total = max(int(round(float(seconds) * 1000)), 0)
    return (f"{total // 3_600_000:02}:{total // 60_000 % 60:02}:{total // 1_000 % 60:02}"
            f"{decimal}{total % 1_000:03}")


def wrap_lines(text, ayar=None):
    """Metni ayarlardaki satır sınırına göre böl; kelime asla ortadan ayrılmaz.

    İki satır gerekiyorsa satırlar dengeli seçilir, ama iki satır da karakter
    sınırının içinde kalır. Tek bir kelime sınırı aşıyorsa o kelime bölünmez,
    kendi satırında kalır: kelimeyi ortadan kesmektense satırı uzatmak doğrudur.
    """
    ayar = ayar or SUB_AYAR
    limit, en_cok = ayar["line_chars"], ayar["max_lines"]
    text = " ".join((text or "").split())
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]
    if en_cok == 2 and len(text) <= limit * 2:
        secilen, fark = None, None
        for index, char in enumerate(text):
            if char != " ":
                continue
            sol, sag = text[:index].strip(), text[index + 1:].strip()
            if not sol or not sag or len(sol) > limit or len(sag) > limit:
                continue
            uzaklik = abs(len(sol) - len(sag))
            if fark is None or uzaklik < fark:
                secilen, fark = [sol, sag], uzaklik
        if secilen:
            return secilen
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and len(trial) > limit:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _ends_with(text, marks):
    return text.rstrip("\"')]}”’»").endswith(tuple(marks))


def _block_text(block):
    """Bloktaki kelimeleri tek metne çevir; "Dünya 'ya" değil "Dünya'ya" yaz."""
    text = ""
    for word in block:
        kelime = word[2]
        if text and not kelime.startswith(("'", "’")):
            text += " "
        text += kelime
    return text


def _fits(block, start, end, word, ayar):
    """Yeni kelime eklenirse blok okunabilirlik sınırlarını aşar mı?

    Satır sayısı doğrudan sarma sonucuyla ölçülür: karakter sayısından tahmin
    etmek yanıltıcı olur, çünkü uzun kelimeler bloğu fazladan satıra taşırır.
    """
    if end - block[0][0] > ayar["max_seconds"]:
        return False
    aday = _block_text(list(block) + [(start, end, word)])
    return len(wrap_lines(aday, ayar)) <= ayar["max_lines"]


def _yetimleri_dengele(blocks, ayar):
    """Cümlenin son bir iki kelimesi tek başına bloğa düşmesin ("other." gibi).

    Önceki blok dolduğu için taşan kısa kuyruk, önceki blokla birleştirilip iki
    dengeli bloğa yeniden bölünür; iki parça da satır ve süre sınırına uyar.
    """
    for index in range(1, len(blocks)):
        onceki, blok = blocks[index - 1], blocks[index]
        if (len(blok) > 2 or len(_block_text(blok)) > 30
                or _ends_with(onceki[-1][2], SUB_SENTENCE_END + SUB_CLAUSE_END)
                or blok[0][0] - onceki[-1][1] >= SUB_BREAK_GAP):
            continue
        tum = onceki + blok
        secilen, puan = None, None
        for k in range(1, len(tum) - 2):
            sol, sag = tum[:k], tum[k:]
            if any(len(wrap_lines(_block_text(p), ayar)) > ayar["max_lines"]
                   or p[-1][1] - p[0][0] > ayar["max_seconds"] for p in (sol, sag)):
                continue
            fark = abs(len(_block_text(sol)) - len(_block_text(sag)))
            if _ends_with(sol[-1][2], SUB_CLAUSE_END):
                fark -= 20
            if puan is None or fark < puan:
                secilen, puan = k, fark
        if secilen:
            blocks[index - 1], blocks[index] = tum[:secilen], tum[secilen:]
    return blocks


def build_cues(words, ayar=None):
    """Kelime zamanlarından okunabilir altyazı blokları üret.

    Blok; cümle sonunda, yeterince dolmuş bir virgülde ya da kelimeler arasında
    SUB_BREAK_GAP kadar sessizlik olduğunda kapanır. Ayrıca ayarlardaki satır ve
    süre sınırını aşacak kelime bir sonraki bloğa geçer.
    """
    ayar = ayar or SUB_AYAR
    blocks, current = [], []
    for start, end, text in words:
        word = (text or "").strip()
        if not word:
            continue
        if current:
            gap = start - current[-1][1]
            if gap >= SUB_BREAK_GAP or not _fits(current, start, end, word, ayar):
                blocks.append(current)
                current = []
        current.append((start, end, word))
        if _ends_with(word, SUB_SENTENCE_END):
            blocks.append(current)
            current = []
        elif (_ends_with(word, SUB_CLAUSE_END)
              and (len(current) >= 4 or current[-1][1] - current[0][0] >= 2.0)):
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    blocks = _yetimleri_dengele(blocks, ayar)

    cues = []
    for block in blocks:
        start = block[0][0]
        cues.append({"start": start,
                     "end": max(block[-1][1], start + ayar["min_seconds"]),
                     "text": "\n".join(wrap_lines(_block_text(block), ayar))})
    # Bloklar üst üste binmesin: araya en az SUB_MIN_GAP boşluk koy.
    for index in range(len(cues) - 1):
        limit = cues[index + 1]["start"] - SUB_MIN_GAP
        if cues[index]["end"] > limit:
            cues[index]["end"] = max(min(cues[index]["end"], limit), cues[index]["start"] + 0.3)
    return cues


def write_srt(cues, path):
    """Blokları SRT olarak yaz (YouTube'a bu dosya yüklenir)."""
    if not cues:
        return None
    blocks = [f"{index}\n{_stamp(cue['start'])} --> {_stamp(cue['end'])}\n{cue['text']}\n"
              for index, cue in enumerate(cues, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def write_vtt(cues, path):
    """Aynı blokları WebVTT olarak yaz (tarayıcı ve kurgu programları için)."""
    if not cues:
        return None
    blocks = [f"{_stamp(cue['start'], '.')} --> {_stamp(cue['end'], '.')}\n{cue['text']}\n" for cue in cues]
    path.write_text("WEBVTT\n\n" + "\n".join(blocks), encoding="utf-8")
    return path


def build_subtitles(words, run_dir, ayar=None):
    """Kelime zamanlarından SRT ve VTT yaz.

    Döndürdüğü üçüncü değer en uzun satırın karakter sayısıdır: oynatıcı kutusuna
    sığıp sığmadığını bu sayıya bakarak ayarlayabilirsin.
    """
    cues = build_cues(words, ayar)
    if not cues:
        return [], 0, 0
    written = [write_srt(cues, run_dir / "seslendirme.srt"),
               write_vtt(cues, run_dir / "seslendirme.vtt")]
    en_uzun = max(len(satir) for cue in cues for satir in cue["text"].split("\n"))
    return [path for path in written if path], len(cues), en_uzun


def tahmini_kelimeler(metin, sure, offset=0.0):
    """Kelime zamanlarını metinden tahmin et (ASR hizalaması güvenilmezse).

    TTS aynı metni durağan bir hızda okur; kelimeleri **karakter ağırlığıyla**
    orantılı dağıtmak altyazıyı sesle büyük ölçüde hizalar. Cümle sonuna ve
    virgüle kısa bir duraklama eklenir ki blok sınırları doğal yerde oluşsun.
    Döndürdüğü biçim `cf_listen` ile aynıdır: `(başlangıç sn, bitiş sn, kelime)`.
    """
    kelimeler = [k for k in re.split(r"\s+", (metin or "").strip()) if k]
    if not kelimeler or sure <= 0:
        return []
    agirliklar = []
    for kelime in kelimeler:
        temiz = kelime.rstrip("\"')]}”’»")
        agirlik = len(kelime) + 1
        if temiz.endswith((".", "!", "?", "…")):
            agirlik += 6
        elif temiz.endswith((",", ";", ":", "—")):
            agirlik += 3
        agirliklar.append(agirlik)
    toplam = sum(agirliklar)
    words, gecen = [], 0.0
    for kelime, agirlik in zip(kelimeler, agirliklar):
        pay = sure * agirlik / toplam
        words.append((offset + gecen, offset + gecen + pay, kelime))
        gecen += pay
    return words


class AltyaziOlusturucu:
    """Bir kural setiyle bağlı nesne: aynı ayarla bloklama, sarma ve dosya yazma."""

    def __init__(self, ayar=None):
        self.ayar = dict(ayar or SUB_AYAR)

    def sar(self, text):
        return wrap_lines(text, self.ayar)

    def bloklar(self, words):
        return build_cues(words, self.ayar)

    def yaz(self, words, run_dir):
        return build_subtitles(words, run_dir, self.ayar)
