"""Altyazı blok kuralları: satır uzunluğu, satır sayısı, süre sınırları.

Netflix Türkçe kılavuzu: satırda en fazla 42 karakter, en fazla iki satır,
yetişkin içerikte saniyede 17 karakter. Bu dört değer arayüzden değiştirilebilir;
`SUB_AYAR` yalnızca varsayılandır.
"""
# ── altyazı · okunabilir bloklar ve hizalama ─────────────────────────
# Netflix Türkçe kılavuzu: satırda en fazla 42 karakter, en fazla iki satır,
# yetişkin içerikte saniyede 17 karakter. Bu dört değer arayüzden değiştirilebilir;
# SUB_AYAR yalnızca varsayılandır.
SUB_AYAR = {"line_chars": 42, "max_lines": 2, "min_seconds": 1.2, "max_seconds": 7.0}
SUB_AYAR_SINIR = {"line_chars": (16, 60), "max_lines": (1, 3),
                  "min_seconds": (0.5, 5.0), "max_seconds": (2.0, 15.0)}
SUB_MIN_GAP = 0.04
SUB_BREAK_GAP = 0.7
# Devanagari "।"/"॥" (Hintçe vb.) ve Doğu Asya "。！？" de cümle sonudur: eksikken Hintçe
# altyazıda iki cümle tek bloğa giriyordu (22.10.2026).
SUB_SENTENCE_END = ".!?…।॥。！？"
SUB_CLAUSE_END = ",;:،、，"


def sub_rules(line_chars=None, max_lines=None, min_seconds=None, max_seconds=None):
    """Arayüzden gelen altyazı ayarlarını izin verilen aralığa sıkıştır.

    Eksik ya da sayı olmayan değer varsayılanı korur; böylece altyazı üretimi
    hiçbir ayar yüzünden bozulmaz.
    """
    gelen = {"line_chars": line_chars, "max_lines": max_lines,
             "min_seconds": min_seconds, "max_seconds": max_seconds}
    ayar = dict(SUB_AYAR)
    for ad, deger in gelen.items():
        if isinstance(deger, (int, float)) and not isinstance(deger, bool):
            alt, ust = SUB_AYAR_SINIR[ad]
            ayar[ad] = type(SUB_AYAR[ad])(min(max(deger, alt), ust))
    if ayar["min_seconds"] >= ayar["max_seconds"]:
        ayar["max_seconds"] = min(ayar["min_seconds"] + 1.0, SUB_AYAR_SINIR["max_seconds"][1])
    return ayar
