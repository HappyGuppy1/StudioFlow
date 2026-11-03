"""EvrenMetin: SSB'nin EVREN LLM geçidinden (OpenAI uyumlu) metin üretimi.

Düşünme modu **hiçbir koşulda kapatılmaz** (`thinking` alanı gönderilmez). Düşünen
model uzun süre sessiz kalabildiği için istek **akışlı** yapılır: sunucu düşünürken her
10 saniyede bir `:` ile başlayan yorum satırı gönderir, bağlantı kopmaz. Okuma zaman
aşımı parça başınadır; isteğin toplam süresi `TOPLAM_SURE` ile ayrıca sınırlanır.

Ölçüm (18.10.2026, Greek + Norse, ilk 12'şer sahne, uygulamanın gerçek prompt kodu):
- deepseek-v4.1-flash: 24/24 sahne, yeniden deneme yok; grup başına 73–207 sn;
  iç/dış ilk cümle ve dönem adı her sahnede, kelime sınırı aşılmadı.
- glm-5.3: kurallara uydu ama grup başına 6,5–9,5 dk; akışsız istekte 10 dakikalık
  zaman aşımına düştü.
İlk istekten önce hesabın kullanım şartlarını onaylaması gerekir; onaylanmamış hesap
her istekte `403 terms_not_accepted` alır (bkz. `hesap_havuzu` sağlık kontrolü).
"""
import json
import time

import requests

from studioflow.saglayicilar.metin_ortak import hata
from studioflow.saglayicilar.taban import MetinAI

EVREN_API = "https://evren-llmapi.ssyz.org.tr/v1"

# Düşünme ve yanıt aynı bütçeyi paylaşır; EVREN en az 2048 (önerilen 4096) ister.
# DeepSeek'te 6 sahnelik grup ~3.000–4.600 token harcadı (düşünme dahil).
AZAMI_TOKEN = 16000
# Tek isteğin azami süresi: glm-5.3 bir grubu 10 dakikayı aşarak yazabiliyor.
TOPLAM_SURE = 1800
# Parça başına okuma süresi; sunucu her 10 sn'de bir canlı tutma satırı gönderir.
OKUMA_SURESI = 120


class EvrenMetin(MetinAI):
    ad = "evren"

    def metin(self, anahtar, model, sistem, kullanici, json_modu=True):
        # Yanıt JSON moduna zorlanmaz (bkz. `OpenAIMetin`); `json_listesi` ayrıştırır.
        payload = {"model": model, "temperature": 0.7, "max_tokens": AZAMI_TOKEN,
                   "stream": True,
                   "messages": [{"role": "system", "content": sistem},
                                {"role": "user", "content": kullanici}]}
        baslangic = time.monotonic()
        response = requests.post(f"{EVREN_API}/chat/completions",
                                 headers={"Authorization": f"Bearer {anahtar.strip()}"},
                                 json=payload, timeout=(20, OKUMA_SURESI), stream=True)
        if not response.ok:
            raise hata(response, anahtar)
        parcalar = []
        with response:
            for satir in response.iter_lines(decode_unicode=True):
                if time.monotonic() - baslangic > TOPLAM_SURE:
                    raise RuntimeError(f"EVREN yanıtı {TOPLAM_SURE // 60} dakikada bitirmedi.")
                # Boş satır ve ':' ile başlayan canlı tutma yorumları veri değildir.
                if not satir or not satir.startswith("data:"):
                    continue
                veri = satir[5:].strip()
                if veri == "[DONE]":
                    break
                govde = json.loads(veri)
                if govde.get("error"):
                    raise RuntimeError(f"EVREN: {govde['error'].get('message') or govde['error']}")
                for secim in govde.get("choices") or []:
                    # Düşünme metni (`reasoning_content`) yanıta katılmaz.
                    parca = (secim.get("delta") or {}).get("content")
                    if parca:
                        parcalar.append(parca)
        return "".join(parcalar)
