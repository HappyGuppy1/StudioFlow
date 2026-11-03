"""Seslendirme akışı: metni parçalara böl, seçili servisle üret, birleştir, altyazı yaz.

Kimlik bilgileri hiçbir çıktı dosyasına yazılmaz. Üç servis de aynı akıştan geçer;
servise özgü işler `EdgeSes`, `GeminiSes`, `ChatterboxSes` sınıflarındadır.
"""
import itertools
import json
import re
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import soundfile as sf

from studioflow.altyazi.bloklar import build_subtitles
from studioflow.altyazi.hizalama import align_parts
from studioflow.altyazi.kural import SUB_AYAR
from studioflow.cekirdek import depolama as _depolama
from studioflow.cekirdek.diller import LANGUAGES
from studioflow.cekirdek.hatalar import ses_hatasi_temizle
from studioflow.saglayicilar import ses_chatterbox, ses_edge, ses_gecis, ses_gemini
from studioflow.saglayicilar.ses_ortak import (CHATTERBOX_LANGUAGES, CHATTERBOX_SPACE,
                                               GEMINI_MODELS, PROVIDERS, VOICES, combine_wavs,
                                               split_text)


# Gemini uzun okumalarda ara sıra "The audio stream could not be completed. Please retry"
# diyor (Japonca/İspanyolca 09.10.2026, Gambusia 17.10.2026). Böyle bir parça cümle
# sınırından ikiye bölünüp yeniden okunur; en fazla bu kadar kez iç içe bölünür.
GECICI_IPUCLARI = ("could not be completed", "please retry", "http 500", "http 502",
                   "http 503", "http 504", "internal error", "overloaded", "unavailable")
AZAMI_BOLME = 2


def gecici_hata_mi(exc):
    dusuk = str(exc).lower()
    return any(ipucu in dusuk for ipucu in GECICI_IPUCLARI)


def ikiye_bol(metin):
    """Metni ortasına en yakın cümle (yoksa kelime) sınırından ikiye böl."""
    metin = metin.strip()
    orta = len(metin) // 2
    sinirlar = [m.end() for m in re.finditer(r"[.!?。！？](?:\s+|$)|\n", metin)
                if 0 < m.end() < len(metin)]
    if not sinirlar:
        sinirlar = [m.end() for m in re.finditer(r"\s+", metin) if 0 < m.end() < len(metin)]
    if not sinirlar:
        return [metin]
    kes = min(sinirlar, key=lambda s: abs(s - orta))
    return [metin[:kes].strip(), metin[kes:].strip()]


def onceki_parcalar(temel, imza, chunks, haric):
    """Aynı imzalı önceki çalışmalarda bitmiş parçalar: `{sıra: dosya}`.

    Bir parça yalnızca metni birebir aynıysa alınır; en yeni çalışma önceliklidir. Kota
    ya da geçici hata yüzünden yarıda kalan bir seslendirme yeniden denendiğinde biten
    parçalar baştan okunmaz (eskiden her deneme parça 1'den başlıyordu).
    """
    bulunan = {}
    for klasor in sorted(Path(temel).glob("*/manifest.json"), reverse=True):
        if klasor.parent == haric:
            continue
        try:
            eski = json.loads(klasor.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if eski.get("imza") != imza:
            continue
        for sira, metin in enumerate(eski.get("chunks") or [], 1):
            dosya = klasor.parent / f"part_{sira:03}.wav"
            if sira in bulunan or sira > len(chunks) or chunks[sira - 1] != metin:
                continue
            if sira <= int(eski.get("completed") or 0) and dosya.is_file():
                bulunan[sira] = dosya
    return bulunan


class SesUretici:
    """Üç ses servisini tek akışta sarmalar; sağlayıcılar değiştirilebilir."""

    def __init__(self, edge=None, gemini=None, chatterbox=None, depolama=None):
        self.edge = edge or ses_edge.VARSAYILAN
        self.gemini = gemini or ses_gemini.VARSAYILAN
        self.chatterbox = chatterbox or ses_chatterbox.VARSAYILAN
        self.depolama = depolama or _depolama.VARSAYILAN

    def uret(self, provider, text, language, *, key="", model=GEMINI_MODELS[0], voice="Charon",
             style="Natural, warm documentary narration with varied emphasis and a relaxed pace.",
             token="", reference=None, exaggeration=0.5, cfg=0.5,
             edge_voice="", rate=0, pitch=0, cf_account="", cf_token="", subtitles=True,
             subtitle_ayar=None, hedef_klasor=None):
        """Yields status, final WAV, download list, subtitle files. Saved parts survive quota failures.

        Altyazı `subtitles=True` iken üretilir: Edge kelime zamanlarını kendisi verir,
        Gemini ve Chatterbox sesi Cloudflare whisper (SUB_ASR_MODEL) ile dinlenir ve
        zamanlar bloklanır. Blok sınırları `subtitle_ayar` (bkz. sub_rules) ile belirlenir.
        Hizalama başarısız olursa ses yine teslim edilir; yalnızca altyazı üretilmez ve
        durum alanı nedenini yazar.
        """
        if provider not in PROVIDERS or language not in LANGUAGES:
            raise ValueError("Geçersiz servis veya dil.")
        if provider == "gemini":
            if not (key or "").strip():
                raise ValueError("Gemini API anahtarını **API hesapları** sekmesinden kaydet.")
            if model not in GEMINI_MODELS or voice not in VOICES:
                raise ValueError("Geçersiz Gemini modeli veya ses seçimi.")
        elif provider == "edge":
            if not re.fullmatch(r"[a-z]{2,3}-[A-Za-z0-9-]+Neural", (edge_voice or "").strip()):
                raise ValueError("Önce listeden bir Edge sesi seç.")
            if not -50 <= int(rate) <= 50 or not -50 <= int(pitch) <= 50:
                raise ValueError("Hız ve ton -50 ile +50 arasında olmalı.")
        elif language not in CHATTERBOX_LANGUAGES:
            raise ValueError("Chatterbox bu dili desteklemiyor. Bu dil için Edge veya Gemini'yi kullan.")
        if not 0 <= float(exaggeration) <= 2 or not 0 <= float(cfg) <= 1:
            raise ValueError("Geçersiz Chatterbox ayarı.")
        chunks = split_text(text, {"edge": 3000, "gemini": 1600}.get(provider, 300))
        # `hedef_klasor` verilirse (ses testi) çıktı oraya yazılır: test sesi otomatik kaydetme
        # açık olsa bile `outputs` klasörüne asla düşmez.
        temel = Path(hedef_klasor) if hedef_klasor else self.depolama.hedef_klasoru("audio")
        run_dir = temel / f"{provider}_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        parts, client, job = [], None, None
        words, offset = [], 0.0      # words: (baslangic sn, bitis sn, kelime)
        subtitle_note = ""
        engine = {"gemini": model, "edge": edge_voice}.get(provider, CHATTERBOX_SPACE)
        imza = {"provider": provider, "language": language, "engine": engine,
                "voice": voice if provider == "gemini" else "", "style": style if provider == "gemini" else "",
                "rate": int(rate) if provider == "edge" else 0, "pitch": int(pitch) if provider == "edge" else 0,
                "reference": str(reference or ""), "exaggeration": float(exaggeration), "cfg": float(cfg)}
        manifest = {"provider": provider, "language": language, "chunks": chunks, "completed": 0,
                    "status": "running", "model": engine, "imza": imza}
        manifest_path = run_dir / "manifest.json"

        def save_manifest():
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        save_manifest()
        # Edge kelime zamanlarını üretimde verir; hazır parçadan alınamaz, yeniden okunur.
        hazir = {} if provider == "edge" else onceki_parcalar(temel, imza, chunks, run_dir)
        try:
            if not subtitles:
                subtitle_note = "Altyazı seçeneği kapalı."
            elif provider != "edge" and not ((cf_account or "").strip() and (cf_token or "").strip()):
                subtitle_note = ("Altyazı üretilmeyecek: Gemini ve Chatterbox sesi Cloudflare whisper ile "
                                 "hizalanır, bunun için Araçlar › Görsel üret sekmesindeki anahtar "
                                 "bölümüne "
                                 "Account ID ve token kaydet. ")
            yield f"{len(chunks)} parça hazırlanıyor…", None, [], []
            if provider == "edge":
                self.edge.kontrol(language)
            if provider == "chatterbox":
                yield self.chatterbox.kontrol(token), None, [], []
                audio_ref = None
                if reference:
                    audio_ref = self.chatterbox.referans_hazirla(reference, run_dir)
                client = self.chatterbox.istemci_ac(token, run_dir)
            if hazir:
                yield (f"Önceki denemeden {len(hazir)}/{len(chunks)} parça hazır; yalnızca eksikler "
                       "okunacak.", None, [], [])
            for index, chunk in enumerate(chunks, 1):
                output = run_dir / f"part_{index:03}.wav"
                if index in hazir:
                    output.write_bytes(hazir[index].read_bytes())
                    parts.append(output)
                    manifest["completed"] = index
                    save_manifest()
                    continue
                yield f"Parça {index}/{len(chunks)} üretiliyor…", None, [str(p) for p in parts], []
                if provider == "edge":
                    part_words, seconds = self.edge.parca_uret(chunk, edge_voice.strip(),
                                                               f"{int(rate):+d}%", f"{int(pitch):+d}Hz", output)
                    words += [(start + offset, end + offset, text) for start, end, text in part_words]
                    offset += seconds
                elif provider == "gemini":
                    bolundu = yield from self._gemini_parca(chunk, language, style, voice, model,
                                                            key, output, run_dir, index)
                    if bolundu:
                        manifest.setdefault("bolunen", []).append(index)
                else:
                    job = self.chatterbox.istek_gonder(client, chunk, language, audio_ref,
                                                       exaggeration, cfg)
                    started = time.monotonic()
                    while not job.done():
                        elapsed = int(time.monotonic() - started)
                        if elapsed > 360:
                            raise TimeoutError("Chatterbox 6 dakika içinde yanıt vermedi. İptal istendi.")
                        yield f"Chatterbox · Parça {index}/{len(chunks)} · GPU sırası / üretim · {elapsed} sn", None, [str(p) for p in parts], []
                        time.sleep(2)
                    self.chatterbox.sonucu_yaz(job, output)
                parts.append(output)
                manifest["completed"] = index
                save_manifest()
            final = run_dir / "seslendirme.wav"
            combine_wavs(parts, final)
            # Gemini parçası çoğu zaman öncekinden yüksek başlıyor: geçişler yumuşatılır (bkz.
            # ses_gecis). Yalnız kazanç değişir, zamanlama aynı kalır; hata olursa ses olduğu gibi
            # teslim edilir.
            gecis_notu = ""
            if provider == "gemini" and len(parts) > 1:
                try:
                    sinirlar = list(itertools.accumulate(sf.info(str(p)).duration for p in parts[:-1]))
                    rapor = ses_gecis.dosyada_yumusat(final, sinirlar)
                    manifest["gecis_yumusatma"] = rapor
                    gecis_notu = ses_gecis.rapor_ozeti(rapor)
                except Exception as exc:
                    gecis_notu = "geçiş yumuşatma atlandı (" + str(exc)[:120] + ")"
            subtitle_files, cue_count, en_uzun_satir = [], 0, 0
            if subtitles:
                if provider != "edge" and not subtitle_note:
                    yield "Altyazı hizalanıyor · ses Cloudflare whisper ile dinleniyor…", None, [str(p) for p in parts], []
                    try:
                        words, tahmin = align_parts(parts, chunks, cf_account, cf_token, language)
                        if tahmin:
                            subtitle_note = (f"{tahmin} parçada ses çözümü güvenilir değildi; "
                                             "o parçaların altyazı zamanları metinden tahmin edildi. ")
                    except Exception as exc:
                        subtitle_note = "Altyazı üretilemedi. " + ses_hatasi_temizle(exc, cf_token, key, token)
                subtitle_files, cue_count, en_uzun_satir = build_subtitles(words, run_dir, subtitle_ayar)
            manifest["status"] = "complete"
            manifest["subtitles"] = {"cues": cue_count, "files": [path.name for path in subtitle_files],
                                    "note": subtitle_note, "uzun_satir": en_uzun_satir,
                                    "ayar": dict(subtitle_ayar or SUB_AYAR)}
            save_manifest()
            seconds = sf.info(final).duration
            if subtitle_files:
                extra = (f" · {cue_count} altyazı bloğu (SRT + VTT) · en uzun satır {en_uzun_satir} "
                         "karakter")
                if subtitle_note:
                    extra += " · NOT: " + subtitle_note.rstrip(". ")
            else:
                extra = " · " + (subtitle_note or "Altyazı üretilemedi").rstrip(".")
            if gecis_notu:
                extra = f" · {gecis_notu}{extra}"
            yield (f"Tamamlandı · {seconds:.1f} saniye · {len(chunks)} parça birleştirildi{extra}.\nKlasör: {run_dir}",
                   str(final), [str(final)], [str(path) for path in subtitle_files])
        except Exception as exc:
            message = ses_hatasi_temizle(exc, key, token)
            manifest.update(status="failed", error=message)
            save_manifest()
            yield (f"{message}\nTamamlanan {len(parts)}/{len(chunks)} parça korundu. Otomatik tekrar yapılmadı.",
                   None, [str(p) for p in parts], [])
        finally:
            if job is not None and not job.done():
                job.cancel()
            if client is not None:
                client.close()


    def _gemini_parca(self, chunk, language, style, voice, model, key, output, run_dir, index,
                      derinlik=0):
        """Parçayı oku; yarıda kesilirse cümle sınırından ikiye bölüp yarıları birleştir.

        Üreteçtir (durum satırı verir); parça bölündüyse True döndürür. Kota/yetki gibi
        geçici olmayan hatalar olduğu gibi yükselir: hesap değiştirme üst katmanın işidir.
        """
        try:
            self.gemini.parca_uret(chunk, language, style, voice, model, key, output)
            return False
        except Exception as exc:
            yarilar = ikiye_bol(chunk)
            if not gecici_hata_mi(exc) or derinlik >= AZAMI_BOLME or len(yarilar) < 2:
                raise
        yield (f"Parça {index}: Gemini okumayı yarıda kesti; parça ikiye bölünüp yeniden "
               "okunuyor…", None, [], [])
        dosyalar = []
        for harf, yari in zip("ab", yarilar):
            hedef = run_dir / f"{output.stem}{harf}.wav"
            yield from self._gemini_parca(yari, language, style, voice, model, key, hedef,
                                          run_dir, index, derinlik + 1)
            dosyalar.append(hedef)
        combine_wavs(dosyalar, output)
        return True


VARSAYILAN = SesUretici()
