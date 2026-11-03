"""Araçlar › Video büyütme (Kaggle) sekmesi. — geri çağrı işlevleri."""
from datetime import datetime

import gradio as gr

from studioflow.cekirdek.yollar import GECICI, OUTPUTS
from studioflow.saglayicilar import buyutme_kaggle as kaggle

CIKTI_KOKU = OUTPUTS / "buyutme"


def buyutme_yontemi(yontem):
    """Real-ESRGAN seçilince SeedVR2'ye özgü ayarlar gizlenir."""
    return gr.update(visible=yontem == kaggle.YONTEM_SEEDVR2)


def buyutme_baglanti_testi():
    """Kaggle'a gerçekten bağlanıp kimliği doğrula (anahtar gösterilmez)."""
    return kaggle.baglanti_testi()


def buyutme_calistir(videolar, yontem, model, cozunurluk, max_cozunurluk, batch, gurultu):
    """Kaggle akışını çalıştır; durum satırları canlı akar. Çıkışlar:
    (durum, önizleme videosu, çıktı dosyaları, Kaggle günlüğü)."""
    satirlar = []

    def durum(metin):
        satirlar.append(metin)
        return "\n".join(satirlar[-40:])

    hedef = CIKTI_KOKU / datetime.now().strftime("%Y%m%d-%H%M%S")
    calisma = GECICI / "kaggle" / hedef.name
    yield durum("Başlatılıyor…"), None, [], ""
    olaylar = kaggle.buyut(videolar or [], hedef, calisma, yontem=yontem, model=model,
                           cozunurluk=cozunurluk, max_cozunurluk=max_cozunurluk,
                           batch=batch, gurultu=gurultu)
    for olay in olaylar:
        if olay[0] == "durum":
            yield durum(olay[1]), None, [], ""
        elif olay[0] == "bitti":
            ciktilar = [str(v) for v in olay[1]]
            yield (durum(f"Tamamlandı · {len(ciktilar)} video kaydedildi: {hedef}\n"
                         "Not: çıktıda ses olmayabilir; ses projede sonradan eklenir."),
                   ciktilar[0], ciktilar, olay[2])
        else:
            yield durum("HATA: " + olay[1]), None, [], olay[2] or "(Kaggle günlüğü alınamadı.)"
