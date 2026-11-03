"""Gemini ile sesten yazıya: `gemini-3.5-transcribe` modeliyle tek parça döküm.

Model yanıtı düz metin olarak değil, parçaların `audio_transcription` alanında verir.
İki kip vardır ve **birlikte kullanılamaz** (14.10.2026'da denendi: "Transcription mode
SMART is incompatible with …"):

- `SMART`: dolgu sözcüklerini ("eee", "ııı") ve yanlış başlangıçları model kendisi
  temizler; özel kelime listesi de verilebilir. Kelime zamanı yoktur.
- Kelime zamanlı (`VERBATIM`): her kelimenin başlangıç/bitiş saniyesi gelir (0,1 sn
  çözünürlük). Altyazı bunlardan kurulur; dolgu sözcükleri akışta ayıklanır.
"""
from google import genai
from google.genai import types

MODEL = "gemini-3.5-transcribe"
# Model sayfası: istek başına en fazla 1 saat, kelime zamanı açıkken 30 dakika.
AZAMI_SURE = 30 * 60


def _saniye(deger):
    """SDK zamanı `timedelta` ya da "1.800s" metni olarak verebilir."""
    if hasattr(deger, "total_seconds"):
        return float(deger.total_seconds())
    return float(str(deger or "0").rstrip("s") or 0)


def zamanlari_duzelt(kelimeler, sure):
    """Bozuk kelime zamanlarını komşularından düzelt; `(kelimeler, düzeltilen sayısı)`.

    Model ara sıra tek bir kelimeye saçma bir zaman veriyor (14.10.2026: 1,82 sn olması
    gereken bir kelime 182 sn geldi; arkasından gelen 30 cümlenin zamanı kaydı). Başlangıcı
    hem önceki hem sonraki komşularından belirgin biçimde kopan kelime aykırı sayılır ve
    sağlam komşularının ortasına alınır; bitişi sonraki kelimenin başını aşan kelime kırpılır.
    """
    bas = [k[0] for k in kelimeler]
    son = [k[1] for k in kelimeler]
    aykiri = set()
    for i, deger in enumerate(bas):
        ileri, geri = bas[i + 1:i + 3], bas[max(0, i - 2):i]
        yuksek = ileri and deger > max(ileri) + 2 and (not geri or deger > max(geri) + 5)
        alcak = geri and deger < min(geri) - 2 and (not ileri or deger < min(ileri) - 5)
        if yuksek or alcak or deger > sure + 1:
            aykiri.add(i)
    for i in aykiri:
        once = next((bas[j] for j in range(i - 1, -1, -1) if j not in aykiri), 0.0)
        sonra = next((bas[j] for j in range(i + 1, len(bas)) if j not in aykiri), sure)
        bas[i] = (once + sonra) / 2
    duzeltilen = len(aykiri)
    for i in range(len(son)):
        sonraki = bas[i + 1] if i + 1 < len(bas) else sure
        if son[i] > sonraki + 0.3 or son[i] < bas[i]:
            son[i] = max(bas[i] + 0.05, min(sonraki, bas[i] + 1.5))
            duzeltilen += 1
    return [(bas[i], son[i], kelimeler[i][2]) for i in range(len(kelimeler))], duzeltilen


def dok(key, veri, mime, dil="", zamanli=False, terimler=()):
    """Bir ses parçasını yazıya dök: `(metin, [(bas, son, kelime)])`.

    `dil` ISO kodu ("tr") ya da boş (otomatik algılama). `zamanli` kelime zamanlarını
    ister (SMART kipi ve özel kelimeler kapanır); kapalıyken kelime listesi boş döner.
    """
    ayar = {"language_codes": [dil]} if dil else {}
    if zamanli:
        ayar["word_timestamp"] = True
    else:
        ayar["mode"] = "SMART"
        if terimler:
            ayar["custom_vocabulary"] = list(terimler)
    client = genai.Client(api_key=(key or "").strip())
    yanit = client.models.generate_content(
        model=MODEL, contents=[types.Part.from_bytes(data=veri, mime_type=mime)],
        config=types.GenerateContentConfig(
            audio_transcription_config=types.AudioTranscriptionConfig(**ayar)))
    dokumler = [p.audio_transcription for aday in (yanit.candidates or [])
                for p in (aday.content.parts if aday.content else []) or []
                if getattr(p, "audio_transcription", None)]
    metin = " ".join((d.text or "").strip() for d in dokumler).strip()
    kelimeler = [(_saniye(k.start_offset), _saniye(k.end_offset), k.word)
                 for d in dokumler for k in (d.words or []) if (k.word or "").strip()]
    return metin, kelimeler
