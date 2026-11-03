"""AnthropicMetin: anthropic sohbet uç noktasından metin üretimi."""
import requests

from studioflow.saglayicilar.metin_ortak import hata
from studioflow.saglayicilar.taban import MetinAI


class AnthropicMetin(MetinAI):
    ad = "anthropic"

    def metin(self, anahtar, model, sistem, kullanici, json_modu):
        payload = {"model": model, "max_tokens": 8192, "system": sistem,
                   "messages": [{"role": "user", "content": kullanici}]}
        response = requests.post("https://api.anthropic.com/v1/messages",
                                 headers={"x-api-key": anahtar.strip(),
                                          "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"},
                                 json=payload, timeout=(20, 180))
        if not response.ok:
            raise hata(response, anahtar)
        body = response.json()
        return "".join(str(blok.get("text") or "") for blok in body.get("content") or [])
