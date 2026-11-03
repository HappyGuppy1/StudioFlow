"""Araçlar › Prompt sekmesi. — geri çağrı işlevleri."""
import gradio as gr

from studioflow.ayarlar import api_hesaplari
from studioflow.proje import prompt_uretimi, sahneleme
from studioflow.saglayicilar import metin_ai, metin_ortak
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.hatalar import ses_hatasi_temizle as clean_error


def prompt_ai_secenekleri(ai_provider):
    """Prompt yapay zekâsı değişince o servisin model listesini yükle."""
    modeller = metin_ortak.AI_SAGLAYICILAR.get(ai_provider, {}).get("models") or []
    return gr.update(choices=modeller, value=modeller[0] if modeller else None)


def prompt_ai_kontrol(ai_provider, ai_model):
    """Seçili prompt yapay zekâsının aktif anahtarını küçük bir istekle doğrula."""
    anahtar = metin_ortak.ai_anahtari(ai_provider, api_hesaplari.VARSAYILAN.aktif_degerler(ai_provider))
    try:
        return metin_ai.VARSAYILAN.yokla(ai_provider, anahtar, ai_model)
    except Exception as exc:
        return "Bağlantı kurulamadı: " + clean_error(exc, anahtar)


def prompt_uret(ai_provider, ai_model, metin, dil, ses_provider, edge_ses, hiz, ton,
                gemini_model, gemini_ses, gizli_stil, gorsel_stil, ref, exag, cfg, parca_saniye):
    """Sesi gerçekten üret, süreyi ölç, parçalara böl ve her parça için prompt yaz."""
    def bos(durum):
        return None, [], "", durum

    anahtar = metin_ortak.ai_anahtari(ai_provider, api_hesaplari.VARSAYILAN.aktif_degerler(ai_provider))
    gemini_key = api_hesaplari.VARSAYILAN.aktif_deger("gemini", "gemini_key")
    hf_token = api_hesaplari.VARSAYILAN.aktif_deger("huggingface", "hf_token")
    metin = (metin or "").strip()
    if not metin:
        yield bos("Önce videonun anlatım metnini yaz.")
        return
    try:
        parca_saniye = max(float(parca_saniye), 0.5)
    except (TypeError, ValueError):
        parca_saniye = sahneleme.PARCA_SANIYE

    yield bos("Seslendirme üretiliyor; toplam süre gerçekten ölçülecek…")
    sure, ses_yolu, ses_notu = sahneleme.ses_suresi(
        ses_provider, metin, dil, key=gemini_key, model=gemini_model, voice=gemini_ses,
        style=gizli_stil, token=hf_token, reference=ref, exag=exag, cfg=cfg,
        edge_ses=edge_ses, hiz=hiz, ton=ton)
    parcalar = sahneleme.parcalara_bol(metin, sure, parca_saniye)
    if not parcalar:
        yield bos("Anlatım metni parçalara bölünemedi.")
        return
    yield (ses_yolu, [], "",
           f"Toplam süre {sure:.1f} sn · parça başı {parca_saniye:g} sn · {len(parcalar)} parça. "
           "Prompt'lar üretiliyor…" + (f" {ses_notu}" if ses_notu else ""))
    kayitlar = []
    kullanilan = {}
    try:
        for baslangic in range(0, len(parcalar), prompt_uretimi.GRUP_BOYU):
            grup = parcalar[baslangic:baslangic + prompt_uretimi.GRUP_BOYU]
            notlar = []
            kayitlar += prompt_uretimi.prompt_grubu_uret(
                ai_provider, anahtar, ai_model, grup, LANGUAGES.get(dil, dil), gorsel_stil,
                bildir=notlar.append, kullanilan=kullanilan)
            durum = f"Parça {len(kayitlar)}/{len(parcalar)} hazır…"
            if notlar:
                # Servis değiştiyse geçiş satırları da gösterilir: kullanıcı hangi yapay
                # zekânın prompt'ları yazdığını görür (kota bitince akış durmaz).
                durum = "\n".join(notlar[-2:] + [durum])
            yield (ses_yolu, [], prompt_uretimi.onizleme(kayitlar), durum)
    except Exception as exc:
        yield (ses_yolu, [], prompt_uretimi.onizleme(kayitlar),
               "Prompt üretilemedi: " + clean_error(exc, anahtar))
        return

    bilgi = metin_ortak.AI_SAGLAYICILAR.get(ai_provider, {})
    varsayilan = (bilgi.get("models") or [""])[0]
    if kullanilan:
        # Prompt'ları gerçekte yazan servis: yedek devreye girdiyse raporda görünür.
        ai_bilgi = f"{kullanilan.get('label', ai_provider)} · {kullanilan.get('model') or varsayilan}"
        if kullanilan.get("provider") != ai_provider:
            ai_bilgi += (f" · seçili servis {bilgi.get('label', ai_provider)} yazamadı, "
                         "yedek servise otomatik geçildi")
    else:
        ai_bilgi = f"{bilgi.get('label', ai_provider)} · {ai_model or varsayilan}"
    ses_bilgi = f"{ses_provider} · {LANGUAGES.get(dil, dil)}" + (
        f" · {edge_ses}" if ses_provider == "edge" and edge_ses else "")
    icerik = prompt_uretimi.metin_raporu(kayitlar, metin=metin, sure=sure, parca_saniye=parca_saniye,
                                        ses_bilgi=ses_bilgi, ai_bilgi=ai_bilgi, not_=ses_notu)
    dosyalar = prompt_uretimi.dosyalari_yaz(icerik)
    nerede = "\n".join(f"• {yol}" for yol in dosyalar) or "Dosya yazılamadı."
    yield (ses_yolu, [str(yol) for yol in dosyalar], icerik,
           f"Tamamlandı · {len(kayitlar)} parça yazıldı.\n{nerede}")
