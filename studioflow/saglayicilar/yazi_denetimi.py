"""Yazı denetimi: üretilen karede sonradan eklenmiş yazı var mı?

Kullanıcı kararı (09.10.2026): karede yazı kabul edilmez. Japon mitolojisi projesinde
ukiyo-e üslubu karelerin çoğuna başlık kartuşu, mühür ve dikey yazıt (anlamsız sözde
Japonca) ekledi; Mısır ve Aztek karelerinin köşelerine sahte ressam imzası düştü.
FLUX.2 klein olumsuz prompt almadığı için ("no text" bile yazıyı çağırıyor) kare
üretildikten sonra denetlenir.

**Sahnenin parçası olan** eski yazı yazı sayılmaz (kullanıcı kararı): tapınak
duvarındaki hiyeroglif kabartmaları, Aztek glifleri gibi mimariye ya da nesneye oyulmuş,
boyanmış kadim işaretler serbesttir. Reddedilen: imza, mühür, kartuş, başlık, altyazı,
tabela/bayrak/fıçı/parşömen üzerindeki okunur ya da sözde yazı.

Denetimi **Cloudflare**'in görsel dil modeli yapar (Gemini'nin kotası dar; kullanıcı
kararı). Görselle aynı Cloudflare hesaplarını kullanır; kotası ya da yetkisi biten
hesaptan sıradakine geçilir.
"""

from studioflow.cekirdek.hatalar import hata_etiketle
from studioflow.saglayicilar import gorsel_denetim
from studioflow.saglayicilar.hesap_havuzu import hesap_ele, hesap_elendi, hesap_listesi

SISTEM = (
    "You inspect AI-generated illustrations for a video. Find writing that was ADDED to the "
    "picture. Report has_text=true for any of these, readable or not, in any script: "
    "artist signatures or monograms (check every corner and edge), seal or stamp marks, "
    "title cartouches or labels, captions, columns of calligraphy or characters (kanji, "
    "kana, Chinese), and letters or pseudo-letters written on banners, flags, signboards, "
    "paper scrolls, books, barrels or jars.\n"
    "Do NOT report (has_text=false): ancient hieroglyphs, glyphs or reliefs carved or "
    "painted on temple walls, columns, statues and other architecture or objects as part "
    "of the scene; ornament such as knotwork, meanders, spirals and geometric borders; "
    "pictures and symbols.\n"
    'Reply ONLY with JSON: {"has_text": <bool>, "where": "<short description or empty>"}')


def _coz(metin):
    # Workers AI JSON yanıtını çoğu zaman hazır nesne olarak döndürüyor (metin değil).
    veri = gorsel_denetim._json_nesnesi(metin)
    if not isinstance(veri, dict) or not isinstance(veri.get("has_text"), bool):
        return None
    return veri["has_text"], " ".join(str(veri.get("where") or "").split())[:200]


class YaziDenetimi:
    """Cloudflare görsel dil modeliyle yazı denetimi; hesaplar sırayla denenir."""

    def __init__(self, hakem=None, modeller=gorsel_denetim.HAKEM_MODELLERI):
        self.hakem = hakem or gorsel_denetim.GorselHakem()
        self.modeller = tuple(modeller)

    def denetle(self, dosya, hatalar=None):
        """`(yazı var mı, nerede)` ya da denetlenemezse `None`."""
        try:
            resim = gorsel_denetim._kucult(dosya)
        except Exception as exc:
            if hatalar is not None:
                hatalar.append(f"kare okunamadı: {exc}")
            return None
        for hesap in hesap_listesi("cloudflare"):
            if hesap_elendi("cloudflare", hesap):
                continue
            degerler = hesap.get("degerler") or {}
            hesap_id = (degerler.get("cf_account_id") or "").strip()
            token = (degerler.get("cf_token") or "").strip()
            if not hesap_id or not token:
                continue
            for model in self.modeller:
                try:
                    ham = self.hakem._istek(model, hesap_id, token, SISTEM,
                                            "Is there added writing in this frame?", resim)
                except Exception as exc:
                    mesaj = str(exc)
                    if hatalar is not None:
                        hatalar.append(f"{hesap['ad']} · {model}: {mesaj[:160]}")
                    if hata_etiketle(mesaj) in ("KOTA", "YETKİ"):
                        # Görselle ortak nöron hakkı: hesap bu çalışma boyunca elenir.
                        hesap_ele("cloudflare", hesap, mesaj)
                        break
                    continue
                sonuc = _coz(ham)
                if sonuc is not None:
                    return sonuc
                if hatalar is not None:
                    hatalar.append(f"{hesap['ad']} · {model}: yanıt okunamadı")
        return None


VARSAYILAN = YaziDenetimi()
