"""Gemini metin üretimi: önce Interactions API, sonra generateContent; model yedekleri."""
import json
import time

import requests

from studioflow.saglayicilar.metin_ortak import hata
from studioflow.saglayicilar.taban import MetinAI

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# Yeni kullanıcılara kapatılan modeller için sırayla denenen güncel adlar.
GEMINI_YEDEK = ("gemini-flash-latest", "gemini-flash-lite-latest",
                "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash")


# Seçilen model "high demand" 503'ü verince aynı anahtarla bu modele geçilir. 503 hesabın
# değil modelin sorunudur: 19.10.2026'da 3.8/3.7/flash-latest 20 hesabın hepsinde (Google'ın
# kendi SDK'sıyla da) 503 verirken 3.6-flash aynı anahtarlarla yanıt veriyordu. Yoğun model
# `GEMINI_YOGUN_SURE` saniye denenmez: her istekte boşa bir 503 (ve 3.8'in ücretsiz
# katmandaki günde 20 isteği) harcanmaz; süre dolunca seçilen model yeniden denenir.
GEMINI_YOGUN_YEDEK = "gemini-3.6-flash"
GEMINI_YOGUN_SURE = 300
_YOGUN = {}                      # model → yeniden denenebileceği an (monotonic)


class GeminiYeniden(Exception):
    """Model ya da uç nokta kullanılamıyor; sıradaki model/uç nokta denenebilir."""


class GeminiYogun(RuntimeError):
    """Model "high demand" 503'ü verdi; hesap değiştirmek çözmez, model değişmeli."""


def _gemini_hata(response, anahtar):
    """Model kullanılamıyorsa GeminiYeniden, öbür hatalarda RuntimeError yükselt."""
    try:
        veri = response.json()
    except ValueError:
        veri = None
    kod = response.status_code
    mesaj = ""
    if isinstance(veri, dict) and isinstance(veri.get("error"), dict):
        kod = veri["error"].get("code", kod)
        mesaj = str(veri["error"].get("message") or "")
    kucuk = (mesaj or response.text or "").lower()
    # Interactions API kodu metin olarak verir ("service_unavailable"); HTTP durumu esastır.
    if response.status_code == 503 or kod in (503, "service_unavailable") or "high demand" in kucuk:
        raise GeminiYogun(str(hata(response, anahtar)))
    if kod == 404 or "not_found" in kucuk or "no longer available" in kucuk or "is not found" in kucuk:
        raise GeminiYeniden(f"HTTP {kod}: {(mesaj or response.text or '')[:220]}")
    raise hata(response, anahtar)


def _gemini_adaylari(model):
    """Önce seçilen model, sonra bilinen güncel modeller (yeni kullanıcı kısıtları için)."""
    adaylar = [model, *GEMINI_YEDEK]
    return list(dict.fromkeys(a for a in adaylar if a))


def _interactions_metni(body):
    """Interactions API yanıtından metni çıkar."""
    if not isinstance(body, dict):
        return ""
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    parcalar = []
    for adim in body.get("steps") or []:
        if not isinstance(adim, dict):
            continue
        for icerik in adim.get("content") or []:
            if isinstance(icerik, dict) and icerik.get("type") == "text":
                parcalar.append(str(icerik.get("text") or ""))
    return "".join(parcalar)


# Yanıt sınırı **düşünme token'larını da kapsar**. 8192 iken gemini-3.8-flash 15 bloğun
# çevirisinde ~7.800 token düşünüp yanıta ~300 token bırakıyordu: JSON 10. blokta
# kesiliyor, yanıt `status: incomplete` dönüyordu (İspanyolca dublaj, 17.10.2026).
GEMINI_AZAMI_CIKTI = 32768


class GeminiMetin(MetinAI):
    ad = "gemini"
    son_model = ""               # son yanıtı yazan model (503'te `GEMINI_YOGUN_YEDEK` olabilir)

    def _interactions(self, anahtar, model, sistem, kullanici):
        """Google'ın önerdiği yeni Interactions API (text üretimi)."""
        payload = {"model": model, "input": kullanici, "system_instruction": sistem,
                   "store": False,
                   "generation_config": {"max_output_tokens": GEMINI_AZAMI_CIKTI}}
        response = requests.post(GEMINI_INTERACTIONS_URL,
                                 headers={"x-goog-api-key": anahtar.strip()},
                                 json=payload, timeout=(20, 180))
        if not response.ok:
            _gemini_hata(response, anahtar)
        body = response.json()
        metin = _interactions_metni(body)
        if not metin.strip():
            # Boş yanıt **hesabın suçu değildir**: model yalnızca "düşünme" adımı
            # döndürmüş olabilir. `GeminiYeniden` ile eski uç noktaya düşülür; orası
            # JSON modunu da destekler, yani prompt üretimi için daha güvenlidir.
            raise GeminiYeniden("Interactions API boş yanıt döndürdü: "
                                + json.dumps(body, ensure_ascii=False)[:200])
        return metin

    def _generate_content(self, anahtar, model, sistem, kullanici, json_modu):
        """Eski uç nokta; Interactions API kullanılamazsa yedek olarak denenir."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        ayar = {"temperature": 0.7, "maxOutputTokens": GEMINI_AZAMI_CIKTI}
        if json_modu:
            ayar["responseMimeType"] = "application/json"
        payload = {"systemInstruction": {"parts": [{"text": sistem}]},
                   "contents": [{"parts": [{"text": kullanici}]}],
                   "generationConfig": ayar}
        response = requests.post(url, headers={"x-goog-api-key": anahtar.strip()},
                                 json=payload, timeout=(20, 180))
        if not response.ok:
            _gemini_hata(response, anahtar)
        body = response.json()
        parcalar = ((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(str(p.get("text") or "") for p in parcalar)

    def metin(self, anahtar, model, sistem, kullanici, json_modu):
        """Önce Interactions API, sonra eski uç nokta; her adımda model yedeği dener."""
        return self._dene(_gemini_adaylari(model), anahtar, sistem, kullanici, json_modu)

    def metin_tek_model(self, anahtar, model, sistem, kullanici, json_modu=True):
        """Yalnızca seçilen modeli dene (iki uç nokta); daha zayıf yedek modele düşülmez.

        Tek istisna: model "high demand" 503'ü verirse `GEMINI_YOGUN_YEDEK` yazar.
        """
        return self._dene([model], anahtar, sistem, kullanici, json_modu)

    def _dene(self, adaylar, anahtar, sistem, kullanici, json_modu):
        """Yoğun (503) modeller atlanıp `GEMINI_YOGUN_YEDEK` ile denenir; `son_model` yazanı tutar."""
        self.son_model = ""
        simdi = time.monotonic()
        sira = [aday for aday in adaylar if _YOGUN.get(aday, 0) <= simdi]
        if len(sira) < len(adaylar) and GEMINI_YOGUN_YEDEK not in sira:
            sira.append(GEMINI_YOGUN_YEDEK)
        try:
            return self._uclari_dene(sira, anahtar, sistem, kullanici, json_modu)
        except GeminiYogun as exc:
            _YOGUN[exc.model] = time.monotonic() + GEMINI_YOGUN_SURE
            if exc.model == GEMINI_YOGUN_YEDEK:
                raise
            return self._uclari_dene([GEMINI_YOGUN_YEDEK], anahtar, sistem, kullanici, json_modu)

    def _uclari_dene(self, adaylar, anahtar, sistem, kullanici, json_modu):
        hatalar = []
        for uc in (lambda aday: self._interactions(anahtar, aday, sistem, kullanici),
                   lambda aday: self._generate_content(anahtar, aday, sistem, kullanici,
                                                       json_modu)):
            for aday in adaylar:
                try:
                    cevap = uc(aday)
                except GeminiYeniden as exc:
                    hatalar.append(str(exc))
                    continue
                except GeminiYogun as exc:
                    exc.model = aday
                    raise
                self.son_model = aday
                return cevap
        son = hatalar[-1] if hatalar else "bilinmeyen hata"
        raise RuntimeError(
            "Gemini bu modeli kabul etmedi. Model alanına `gemini-flash-latest` yazıp tekrar dene. "
            f"Ayrıntı: {son}")
