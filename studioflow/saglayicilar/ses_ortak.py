"""Ses servislerinin ortak parçaları: sabitler, metin bölme, WAV birleştirme, test klasörü."""
import re
import shutil

import requests
import soundfile as sf
from pathlib import Path

from studioflow.cekirdek import depolama as _depolama
from studioflow.cekirdek.diller import LANGUAGES  # noqa: F401

CHATTERBOX_SPACE = "ResembleAI/Chatterbox-Multilingual-TTS"
CHATTERBOX_URL = f"https://huggingface.co/spaces/{CHATTERBOX_SPACE}"
GEMINI_MODELS = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]
VOICES = "Kore Puck Charon Zephyr Fenrir Leda Orus Aoede Callirrhoe Autonoe Enceladus Iapetus Umbriel Algieba Despina Erinome Algenib Rasalgethi Laomedeia Achernar Alnilam Schedar Gacrux Pulcherrima Achird Zubenelgenubi Vindemiatrix Sadachbia Sadaltager Sulafat".split()
CHATTERBOX_LANGUAGES = set("ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr zh".split())

# Ses testi: her dil için aynı anlamı taşıyan kısa cümle. Test üretimleri **hiçbir zaman**
# kalıcı klasöre yazılmaz; yalnızca dinlemek için geçici klasörde tutulur ve bir sonraki
# testte silinir (bkz. `test_klasoru`).
TEST_CUMLESI = {
    "tr": "Bu bir test cümlesidir; sesi denemeniz için hazırlandı.",
    "en": "This is a test sentence, prepared to help you try this voice.",
    "de": "Dies ist ein Testsatz, der vorbereitet wurde, damit du diese Stimme ausprobieren kannst.",
    "es": "Esta es una frase de prueba, preparada para que puedas probar esta voz.",
    "fr": "Ceci est une phrase de test, préparée pour vous aider à essayer cette voix.",
    "it": "Questa è una frase di prova, preparata per aiutarti a provare questa voce.",
    "pt": "Esta é uma frase de teste, preparada para você experimentar esta voz.",
    "ar": "هذه جملة اختبار، أُعدّت لمساعدتك على تجربة هذا الصوت.",
    "ru": "Это тестовое предложение, подготовленное, чтобы вы могли проверить этот голос.",
    "zh": "这是一句测试句子，用来帮助你试听这个声音。",
    "ja": "これはテスト用の文です。この声を試すために用意しました。",
    "ko": "이것은 테스트 문장입니다. 이 목소리를 시험해 보시라고 준비했습니다.",
    "hi": "यह एक परीक्षण वाक्य है, जो इस आवाज़ को आज़माने के लिए तैयार किया गया है।",
    "nl": "Dit is een testzin, gemaakt zodat u deze stem kunt uitproberen.",
    "pl": "To jest zdanie testowe, przygotowane, abyś mógł wypróbować ten głos.",
    "sv": "Det här är en testmening, framtagen för att du ska kunna prova den här rösten.",
    "no": "Dette er en testsetning, laget for at du skal kunne prøve denne stemmen.",
    "da": "Dette er en testsætning, lavet så du kan prøve denne stemme.",
    "fi": "Tämä on testilause, joka on tehty, jotta voit kokeilla tätä ääntä.",
    "el": "Αυτή είναι μια δοκιμαστική πρόταση, φτιαγμένη για να δοκιμάσετε αυτή τη φωνή.",
    "he": "זהו משפט בדיקה, שהוכן כדי שתוכלו לנסות את הקול הזה.",
    "ms": "Ini ialah ayat ujian, disediakan untuk anda mencuba suara ini.",
    "sw": "Hii ni sentensi ya majaribio, iliyoandaliwa ili uweze kujaribu sauti hii.",
    "uk": "Це тестове речення, підготовлене, щоб ви могли перевірити цей голос.",
    "vi": "Đây là một câu thử nghiệm, được chuẩn bị để bạn thử giọng nói này.",
    "id": "Ini adalah kalimat uji, disiapkan agar Anda bisa mencoba suara ini.",
    "th": "นี่คือประโยคทดสอบที่เตรียมไว้ให้คุณลองเสียงนี้",
    "bn": "এটি একটি পরীক্ষামূলক বাক্য, যা এই কণ্ঠস্বর পরীক্ষা করার জন্য তৈরি করা হয়েছে।",
    "ro": "Aceasta este o propoziție de test, pregătită ca să puteți încerca această voce.",
    "cs": "Toto je testovací věta, připravená k vyzkoušení tohoto hlasu.",
    "hu": "Ez egy tesztmondat, amelyet azért készítettünk, hogy kipróbálhasd ezt a hangot.",
    "ta": "இது ஒரு சோதனை வாக்கியம்; இந்தக் குரலைச் சோதிக்க உருவாக்கப்பட்டது.",
    "te": "ఇది ఒక పరీక్ష వాక్యం; ఈ స్వరాన్ని పరీక్షించడానికి తయారు చేయబడింది.",
    "ur": "یہ ایک آزمائشی جملہ ہے، جو اس آواز کو جانچنے کے لیے تیار کیا گیا ہے۔",
    "fa": "این یک جمله آزمایشی است که برای امتحان کردن این صدا آماده شده است.",
    "az": "Bu bir test cümləsidir; bu səsi sınamaq üçün hazırlanmışdır.",
    "fil": "Ito ay isang pangungusap na pangsubok, inihanda para masubukan mo ang boses na ito.",
}
# Test seslerinin yazıldığı geçici klasör: kalıcı klasörün (`outputs`) dışındadır ve
# her testten önce boşaltılır.
TEST_KLASORU = _depolama.GECICI / "ses-testi"
MAX_TEXT = 12000
PROVIDERS = ("edge", "gemini", "chatterbox")


def split_text(text, limit):
    """Keep every non-whitespace character; split at sentences, then words, then hard limit."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Önce seslendirilecek metni yaz.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Bir çalışmada en fazla {MAX_TEXT:,} karakter kullan. Metni bölümlere ayır.")
    chunks = []
    while len(text) > limit:
        window = text[:limit]
        boundaries = list(re.finditer(r"[.!?。！？](?:\s+|$)|\n", window))
        cut = boundaries[-1].end() if boundaries else 0
        if cut < limit // 3:
            spaces = list(re.finditer(r"\s+", window))
            cut = spaces[-1].end() if spaces else limit
        chunks.append(text[:cut].strip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def plan_text(text, language):
    if not (text or "").strip():
        return "Metni hedef dilde yaz. Dil seçimi metni otomatik çevirmiyor."
    try:
        edge = len(split_text(text, 3000))
        gem = len(split_text(text, 1600))
        chat = len(split_text(text, 300))
        chat_info = f"Chatterbox {chat} istek" if language in CHATTERBOX_LANGUAGES else "Chatterbox bu dili desteklemiyor"
        return (f"{len(text):,} karakter · Edge {edge} istek (kotasız) · Gemini {gem} istek (kotadan düşer) · "
                f"{chat_info}. Dil seçimi metni çevirmez.")
    except ValueError as exc:
        return str(exc)


def http_json(response):
    if not response.ok:
        # Do not include request headers, URL keys or full server traceback.
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:650]}")
    return response.json()


def hf_identity(token):
    """Tokenı doğrula ve hesap adını döndür. Token yoksa anonim kotayı bildir."""
    if not (token or "").strip():
        return "anonim · IP başına düşük ZeroGPU kotası. Token girersen kotan artar."
    data = http_json(requests.get("https://huggingface.co/api/whoami-v2",
                                   headers={"Authorization": f"Bearer {token.strip()}"}, timeout=30))
    plan = "PRO" if data.get("isPro") else "ücretsiz hesap"
    return f"{data.get('name', 'bilinmeyen hesap')} · {plan}"


def test_cumlesi(dil):
    """Dilin test cümlesini döndür; çevirisi yoksa İngilizcesi kullanılır."""
    return TEST_CUMLESI.get(dil) or TEST_CUMLESI["en"]


def test_klasoru():
    """Ses testi klasörünü boşalt ve hazırla.

    Test sesleri **hiçbir zaman** `outputs` klasörüne yazılmaz: hepsi buradadır ve yeni bir
    test başlarken öncekiler silinir, böylece testten geriye dosya kalmaz.
    """
    shutil.rmtree(TEST_KLASORU, ignore_errors=True)
    TEST_KLASORU.mkdir(parents=True, exist_ok=True)
    return TEST_KLASORU


def combine_wavs(paths, output):
    info = sf.info(paths[0])
    with sf.SoundFile(output, "w", samplerate=info.samplerate, channels=info.channels, subtype="PCM_16") as target:
        for path in paths:
            current = sf.info(path)
            if (current.samplerate, current.channels) != (info.samplerate, info.channels):
                raise RuntimeError("Ses parçalarının biçimleri farklı. Parçalar klasörde korundu.")
            for block in sf.blocks(path, blocksize=65536, dtype="float32", always_2d=True):
                target.write(block)


def find_audio(result):
    if isinstance(result, str) and Path(result).is_file():
        return Path(result)
    if isinstance(result, dict):
        for name in ("path", "audio", "value"):
            if name in result and (path := find_audio(result[name])):
                return path
    if isinstance(result, (list, tuple)):
        for item in result:
            if path := find_audio(item):
                return path
    return None
