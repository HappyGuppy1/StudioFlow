"""OpenAIMetin: openai sohbet uç noktasından metin üretimi."""
import requests

from studioflow.saglayicilar.metin_ortak import hata
from studioflow.saglayicilar.taban import MetinAI


class OpenAIMetin(MetinAI):
    ad = "openai"

    def metin(self, anahtar, model, sistem, kullanici, json_modu):
        # Yanıt JSON moduna zorlanmaz: model bir dizi döndürürse OpenAI json_object
        # biçimini reddedebilir. Yanıt yine de _json_listesi ile ayrıştırılır.
        payload = {"model": model, "temperature": 0.7,
                   "messages": [{"role": "system", "content": sistem},
                                {"role": "user", "content": kullanici}]}
        response = requests.post("https://api.openai.com/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {anahtar.strip()}"},
                                 json=payload, timeout=(20, 180))
        if not response.ok:
            raise hata(response, anahtar)
        body = response.json()
        return str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
