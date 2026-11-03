"""Microsoft Edge okuma servisi: anahtar istemez, yerel CPU'da model çalıştırmaz."""
import asyncio
import difflib
import io
import re
import time

import soundfile as sf

from studioflow.cekirdek.diller import LANGUAGES
from studioflow.saglayicilar.taban import SesSaglayici

# Ağ erişilemezse bilinen Türkçe seslere düşülür.
EDGE_FALLBACK = {"tr": ["tr-TR-AhmetNeural", "tr-TR-EmelNeural"]}

# Microsoft bir sesi ara sıra ses vermeden kapatıyor (`NoAudioReceived`); 19.10.2026'da
# tr-TR-AhmetNeural 12 denemenin 12'sinde boş döndü, EmelNeural 12'de 12 okudu. Boş
# parça bu aralıklarla (sn) yeniden okunur; ses yine gelmezse sesin adı söylenir.
# Başka sese kendiliğinden geçilmez: anlatımın ortasında ses değişirdi.
EDGE_BOS_BEKLEMELERI = (2, 5)


def restore_punctuation(words, text):
    """Edge kelimeleri noktalama işareti taşımaz; işaretleri kaynak metinden geri koy.

    Servisin verdiği kelime zamanları konuşulan kelimelerle birebir eşleşir. Kaynak
    metnin sözcükleri sırayla hizalanır ve "arkadaşlar" yerine "arkadaşlar," yazılır;
    böylece altyazı okunur olur ve cümle sonu tespiti çalışır. Eşleşmeyen kelimede
    (örneğin sayılar okunuşuna açıldığında) servisin metni aynen korunur.
    """
    tokens = re.findall(r"\S+", text or "")
    if not tokens or not words:
        return words

    def plain(value):
        return re.sub(r"[^\w]+", "", value, flags=re.UNICODE).casefold()

    spoken = [plain(word[2]) for word in words]
    source = [plain(token) for token in tokens]
    matched, text_of = {}, {}
    for block in difflib.SequenceMatcher(a=spoken, b=source, autojunk=False).get_matching_blocks():
        for shift in range(block.size):
            matched[block.a + shift] = tokens[block.b + shift]
    for index, (start, end, word) in enumerate(words):
        text_of[index] = matched.get(index, word)
    return [(start, end, text_of[index].strip() or word) for index, (start, end, word) in enumerate(words)]


class EdgeSes(SesSaglayici):
    """Edge sesleri (dil başına önbellekli liste) ve parça seslendirme."""

    ad = "edge"

    def __init__(self, yedek_sesler=None):
        self.yedek_sesler = dict(yedek_sesler if yedek_sesler is not None else EDGE_FALLBACK)
        self._onbellek = {}

    def sesler(self, language):
        """Seçili dilin Edge seslerini döndür; ağ erişilemezse bilinen Türkçe seslere düş."""
        if not self._onbellek:
            import edge_tts
            for voice in asyncio.run(edge_tts.list_voices()):
                self._onbellek.setdefault(voice["Locale"].split("-")[0], []).append(voice["ShortName"])
            for names in self._onbellek.values():
                names.sort()
        return self._onbellek.get(language, [])

    def guvenli_sesler(self, language):
        try:
            return self.sesler(language) or self.yedek_sesler.get(language, [])
        except Exception:
            return self.yedek_sesler.get(language, [])

    def kontrol(self, language="tr"):
        names = self.sesler(language)
        if not names:
            raise RuntimeError(f"Edge servisinde '{LANGUAGES.get(language, language)}' için ses bulunamadı. Başka bir dil seç.")
        return f"Edge okuma servisi hazır · {LANGUAGES.get(language, language)} için {len(names)} ses · anahtar gerekmez"

    def parca_uret(self, text, voice, rate, pitch, output):
        """Bir parçayı seslendir, WAV olarak yaz ve kelime zamanlarını döndür.

        `boundary="WordBoundary"` Microsoft servisinden kelime kelime zaman ister.
        Varsayılan ayar cümle sınırı verir; o zaman altyazı da cümle başına bir blok
        olur ve ekranda çok uzun kalır, bu yüzden kelime zamanları istenir.
        """
        import edge_tts

        async def speak():
            speech = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
            subtitles, audio = edge_tts.SubMaker(), io.BytesIO()
            async for chunk in speech.stream():
                if chunk["type"] == "audio":
                    audio.write(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    subtitles.feed(chunk)
            return audio.getvalue(), subtitles.cues

        from edge_tts.exceptions import NoAudioReceived

        for bekleme in (*EDGE_BOS_BEKLEMELERI, None):
            try:
                data, cues = asyncio.run(speak())
            except NoAudioReceived:
                data = b""
            if data or bekleme is None:
                break
            time.sleep(bekleme)
        if not data:
            raise RuntimeError(
                f"Edge servisi '{voice}' sesiyle {len(EDGE_BOS_BEKLEMELERI) + 1} denemede de ses "
                "döndürmedi. Microsoft bu sesi şu an okumuyor olabilir; Seslendirme panelinden "
                "başka bir ses seçip tekrar dene.")
        samples, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        sf.write(output, samples, sample_rate, subtype="PCM_16")
        words = [(cue.start.total_seconds(), cue.end.total_seconds(), cue.content) for cue in cues]
        return restore_punctuation(words, text), len(samples) / sample_rate


VARSAYILAN = EdgeSes()
