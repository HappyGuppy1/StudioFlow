"""CloudflareMetin: Workers AI sohbet uç noktasından metin üretimi.

Görsel üretimiyle **aynı** hesabı ve aynı ücretsiz nöron bütçesini kullanır, bu yüzden
ayrı bir servis kaydı istemez. Kimlik iki parçalıdır (Account ID + token); havuz tek
metin taşıdığı için `metin_ortak.ai_anahtari` ile birleştirilir, burada ayrılır.
"""
import json

import requests

from studioflow.saglayicilar.metin_ortak import anahtar_ayir, hata
from studioflow.saglayicilar.taban import MetinAI

CF_API = "https://api.cloudflare.com/client/v4"

# Yanıt için ayrılan üst sınır. Akıl yürüten modeller (gpt-oss, nemotron) düşünme
# adımlarını da bu bütçeden harcar; 6 sahnelik bir grup için 2000 token yetmiyordu.
# 6000 de yetmedi (29.09.2026): nemotron'un istekleri tam 6000'de kesildi, JSON yarıda
# kaldı ve 3 grubun 2'si düştü; 16000 ile 14/14 sahne yazıldı (en uzun yanıt ~7.700).
AZAMI_TOKEN = 16000
# Uzun düşünen modelde tek istek iki dakikayı aşabiliyor.
ZAMAN_ASIMI = 300


class CloudflareMetin(MetinAI):
    ad = "cloudflare"

    def metin(self, anahtar, model, sistem, kullanici, json_modu=True):
        # json_modu kullanılmıyor: Workers AI modelleri bir JSON **dizisi** istendiğinde
        # şema zorlamasıyla çakışabiliyor. Yanıt yine `json_listesi` ile ayrıştırılır.
        parcalar = anahtar_ayir(anahtar)
        if len(parcalar) != 2 or not all(p.strip() for p in parcalar):
            raise RuntimeError("Cloudflare Account ID ya da token eksik.")
        hesap, token = (p.strip() for p in parcalar)
        payload = {"messages": [{"role": "system", "content": sistem},
                                {"role": "user", "content": kullanici}],
                   "max_tokens": AZAMI_TOKEN, "temperature": 0.7}
        response = requests.post(f"{CF_API}/accounts/{hesap}/ai/run/{model}",
                                 headers={"Authorization": f"Bearer {token}"},
                                 json=payload, timeout=(20, ZAMAN_ASIMI))
        if not response.ok:
            raise hata(response, token)
        return _yanit_metni(response.json())


def _yanit_metni(body):
    """Workers AI iki biçimde yanıt veriyor; ikisini de tek metne indir.

    Çoğu model `result.response` döndürür, akıl yürüten modeller (gpt-oss, nemotron)
    OpenAI biçiminde `result.choices[0].message.content` döndürür. Yalnızca birini
    okumak bu modelleri "boş yanıt verdi" gibi gösteriyordu.
    """
    sonuc = body.get("result") or {}
    metin = sonuc.get("response")
    if not metin:
        secim = (sonuc.get("choices") or [{}])[0]
        metin = (secim.get("message") or {}).get("content") or ""
    if isinstance(metin, (list, dict)):
        # Bazı modeller diziyi doğrudan nesne olarak döndürüyor; çözümleyici metin bekler.
        return json.dumps(metin, ensure_ascii=False)
    return str(metin or "")
