"""İlk sahne (kanca karesi): prompt'un hangi ilk sahne metniyle yazıldığının izi,
yeniden yazımdan önceki yedek ve metin değiştiğinde prompt'un tazelenmesi.
"""
import hashlib

from studioflow.proje.adim_promptlari import ILK_SAHNE_INDEX, ilk_sahne_kaydi
from studioflow.proje.akis_kare import gorsel_hazir
from studioflow.proje.dosya import not_ekle, proje_yaz


def kanca_izi(metin):
    """İlk sahne metninin kısa parmak izi (boş metin → boş iz).

    `proje.txt`teki `Kanca izi` satırı, 1. sahnenin prompt'unun **hangi** metinle
    yazıldığını söyler. İz aynıysa prompt yeniden yazılmaz: beğenilen kanca prompt'u
    her "kaldığın yerden devam"da değişmesin (boşuna yapay zekâ çağrısı da olmasın).
    """
    temiz = " ".join(str(metin or "").split())
    return hashlib.sha1(temiz.encode("utf-8")).hexdigest()[:12] if temiz else ""


def kanca_izini_yaz(veri):
    """1. sahnenin prompt'u yazıldıktan sonra izi kaydet (yazmadan **değiştirmez**)."""
    adim = next((oge for oge in veri["adimlar"]
                 if int(oge.get("index") or 0) == ILK_SAHNE_INDEX), None)
    if adim is None or not adim.get("image_prompt"):
        return False
    iz = kanca_izi((veri["ayarlar"]["video"] or {}).get("ilk_prompt"))
    if (veri.get("kanca_izi") or "") == iz:
        return False
    veri["kanca_izi"] = iz
    return True


def kanca_yedegi(veri):
    """1. sahnenin prompt'larının kopyası (yeniden yazma başarısız olursa geri konur)."""
    adim = next((oge for oge in veri["adimlar"]
                 if int(oge.get("index") or 0) == ILK_SAHNE_INDEX), None)
    if adim is None:
        return None
    return {alan: adim.get(alan) or ""
            for alan in ("image_prompt", "negative_prompt", "video_prompt")}


def kanca_geri_al(veri, yedek):
    """Yeniden yazma başarısız olduysa eski kanca prompt'unu geri koy; `True` döner.

    Prompt'u silip yenisini yazdıramamak, projeyi başladığından **kötü** bırakırdı:
    kullanıcının elindeki çalışan prompt kaybolurdu. Bu yüzden kayıp geri alınır.
    """
    adim = next((oge for oge in veri["adimlar"]
                 if int(oge.get("index") or 0) == ILK_SAHNE_INDEX), None)
    if adim is None or not yedek or adim.get("image_prompt"):
        return False
    adim.update(yedek)
    not_ekle(veri, f"Adım {ILK_SAHNE_INDEX} (kanca) prompt'u yeniden yazdırılamadı; "
                   "önceki prompt geri kondu.")
    proje_yaz(veri)
    return True


def ilk_sahneyi_tazele(veri, klasor):
    """Kanca sahnesinin prompt'unu yapay zekâya **yeniden yazdır**; tazelendiyse `True`.

    Kullanıcı ilk sahnenin içeriğini yazdıysa (`video.ilk_prompt`) o sahnenin prompt'u
    diğer sahnelerle aynı biçimde kurulmalıdır — aynı stil katmanı, aynı kamera dili.
    Bunun yolu kareyi birebir kopyalamak değil, prompt aşamasını o sahne için yeniden
    çalıştırmaktır: kayıt boşaltılır, `adim_prompt` onu eksik sayıp yapay zekâya
    yazdırır (kullanıcının metni isteğe bağlam olarak girer).

    **Yalnızca metin değiştiyse** çalışır (`Kanca izi` karşılaştırması): aynı metinle
    her devam edişte prompt yeniden yazılsaydı beğenilen kanca prompt'u sabit kalmaz,
    her seferinde bir yapay zekâ çağrısı da boşa giderdi. Metin silindiyse iz eşleşmez
    ve prompt kullanıcının içeriği olmadan yeniden yazılır.

    Karesi **üretilmiş** sahneye hiç dokunulmaz: hazır bir kare metin değişti diye
    geçersiz kılınmaz. Prompt aşamasından **önce** çağrılır.
    """
    adim = next((oge for oge in veri["adimlar"]
                 if int(oge.get("index") or 0) == ILK_SAHNE_INDEX), None)
    if adim is None or gorsel_hazir(klasor, adim) or not adim.get("image_prompt"):
        return False
    ilk_sahne = ilk_sahne_kaydi(veri["ayarlar"]["video"]) or {}
    iz = kanca_izi(ilk_sahne.get("prompt"))
    if iz == (veri.get("kanca_izi") or ""):
        return False          # metin değişmemiş: prompt olduğu gibi kalır
    adim.update(image_prompt="", negative_prompt="", video_prompt="")
    # Denetim listesi eski prompt'a göre yazılmıştı; yenisiyle birlikte yazılır.
    adim.pop("kontrol", None)
    not_ekle(veri, f"Adım {ILK_SAHNE_INDEX} (kanca) ilk sahne metni değişti; prompt "
                   "yeniden yazdırılacak (diğer sahnelerle aynı biçimde).")
    proje_yaz(veri)
    return True
