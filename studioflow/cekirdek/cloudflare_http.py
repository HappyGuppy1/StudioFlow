"""Cloudflare REST API ortak parçaları: adresler, hata metni, durum ipuçları.

Hem görsel üretimi (Workers AI) hem de altyazı hizalaması (Whisper) bu modülü kullanır;
böylece altyazı katmanı görsel sağlayıcısına bağımlı olmaz. Burada ağ çağrısı yoktur:
yalnızca adresler ve yanıt metinlerinin okunması.
"""
import json
import re

CF_API = "https://api.cloudflare.com/client/v4"
CF_DASHBOARD_URL = "https://dash.cloudflare.com/"
CF_TOKENS_URL = "https://dash.cloudflare.com/profile/api-tokens"
CF_GUIDE_URL = "https://developers.cloudflare.com/workers-ai/get-started/rest-api/"


def mask_account(account_id):
    if not account_id:
        return ""
    if len(account_id) <= 10:
        return account_id[0] + "*" * (len(account_id) - 1)
    return f"{account_id[:6]}…{account_id[-4:]}"


def cf_error(response):
    try:
        data = response.json()
    except Exception:
        return f"HTTP {response.status_code}: {(response.text or '')[:300]}"
    errors = data.get("errors") if isinstance(data, dict) else None
    if errors:
        parcalar = []
        for item in errors:
            if isinstance(item, dict):
                parcalar.append(str(item.get("message") or item.get("code") or item))
            else:
                parcalar.append(str(item))
        return " · ".join(parcalar)[:400]
    return f"HTTP {response.status_code}: {json.dumps(data, ensure_ascii=False)[:300]}"


def cf_status_hint(status):
    if status == 401:
        return ("Cloudflare bu istekte token'ı reddetti (401). Token geçerli olabilir; sorun "
                "token'ın bu hesaba/Workers AI'a yetkisi olmaması olabilir. 'Sorunu teşhis et' "
                "düğmesi sebebi madde madde yazar. ")
    if status == 403:
        return ("Token yetkisiz (403): Workers AI izni ya da hesap erişimi eksik. Token'ı "
                "düzenleyip 'Account → Workers AI → Edit' ekle. ")
    if status == 404:
        return "Hesap kimliği ya da model adı bulunamadı (404). "
    if status == 429:
        return "Kota ya da hız sınırı aşıldı (429). "
    return ""


def is_plausible_cf_token(token):
    token = (token or "").strip()
    if not 20 <= len(token) <= 200:
        return False
    return re.fullmatch(r"[A-Za-z0-9._\-]+", token) is not None
