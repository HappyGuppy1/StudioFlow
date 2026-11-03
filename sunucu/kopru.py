"""Gradio köprüsü: StudioFlow'un **Araçlar** ve **API hesapları** sayfaları editörde.

StudioFlow'un araç sayfaları (`studioflow/arayuz/sayfa_*.py`) burada Gradio sunucusu
başlatılmadan kurulur; bileşen ağacı ve olay bağlantıları (`demo.fns`) okunur:

    ağaç      her sekmenin düzeni ve bileşenleri (etiket, seçenekler, sınırlar, açıklama…)
              → editör bunu kendi tasarımıyla çizer (bkz. `web/araclar.js`)
    olay      editörde bir düğmeye basılınca / alan değişince StudioFlow'un o olaya bağlı
              işlevi **aynı girdilerle** çalıştırılır; çıktılar bileşen güncellemesi
              (yama) olarak editöre döner. Üreteç işlevlerin ara çıktıları da gelir.
    zincir    Gradio'daki gibi: bir çıktı bir bileşenin değerini değiştirirse o bileşenin
              `change` olayları da çalışır.

Böylece araçların her düğmesi ve alanı StudioFlow'dakiyle birebir aynıdır; StudioFlow'da
bir araç değişirse editör de kendiliğinden değişir. Değerlerin tek kaynağı sunucudaki
oturumdur (tek kullanıcı, bu bilgisayar).

Ses efekti aracının `gr.render` listesi (bulunan sesler) özel olarak taşınır: liste
editörde çizilir, **İndir** StudioFlow'un `ef_indir` işlevini çalıştırır.
"""
import hashlib
import inspect
import itertools
import math
import threading
import time
from collections import defaultdict
from pathlib import Path

from sunucu import ayar

YOK = object()
DUZEN = {"Row", "Column", "Group", "Accordion", "Tab", "Tabs", "Form", "Blocks"}
DOSYA_TURLERI = {"File", "Image", "Audio", "Video", "Gallery", "DownloadButton"}
YUKLEMELER = ayar.GECICI / "arac-yuklemeleri"
GECICI = ayar.GECICI
PROPLAR = ("label", "choices", "minimum", "maximum", "step", "info", "placeholder", "lines",
           "max_lines", "visible", "interactive", "open", "variant", "size", "link", "file_count",
           "type", "sources", "scale", "min_width", "show_label", "columns", "height",
           "max_height", "elem_classes", "elem_id", "multiselect", "allow_custom_value",
           "file_types", "selected")
SIMGE = {"Fotoğraftan video": "🎞", "Görsel üret": "🖼", "Sabit karakter": "🧍", "Seslendirme": "🎙",
         "Prompt": "📝", "Müzik üret": "🎵", "Ses efekti üret": "🔊", "Sesten yazıya": "✍",
         "Video büyütme (Kaggle)": "🔍", "Harita animasyonu": "🗺", "API hesapları": "🔑"}


class KopruHatasi(RuntimeError):
    pass


def _json(deger):
    """JSON'a çevrilebilir hâle getir (tuple → liste, Path → metin, sayı sınırları)."""
    if isinstance(deger, (str, bool)) or deger is None:
        return deger
    if isinstance(deger, (int, float)):
        return deger if not (isinstance(deger, float) and (math.isnan(deger) or math.isinf(deger))) else None
    if isinstance(deger, Path):
        return str(deger)
    if isinstance(deger, dict):
        return {str(k): _json(v) for k, v in deger.items()}
    if isinstance(deger, (list, tuple, set)):
        return [_json(x) for x in deger]
    return str(deger)


class Is:
    """Bir olayın çalışması: yamalar sırayla birikir, editör yokladıkça yenilerini alır."""

    def __init__(self, no, baslik):
        self.no, self.baslik = no, baslik
        self.durum = "calisiyor"
        self.yamalar = []          # [(bileşen kimliği, {prop: değer})]
        self.uyarilar = []         # gr.Warning / gr.Info metinleri
        self.hata = ""
        self.baslangic = time.time()
        self.bitis = None

    def yama(self, kimlik, props):
        self.yamalar.append((kimlik, props))

    def ozet(self, son=0):
        return {"no": self.no, "durum": self.durum, "hata": self.hata,
                "yamalar": [{"id": k, "props": p} for k, p in self.yamalar[son:]],
                "son": len(self.yamalar), "uyarilar": self.uyarilar,
                "sure": round((self.bitis or time.time()) - self.baslangic, 1)}


class Kopru:
    def __init__(self):
        self._kilit = threading.RLock()
        self._kuruldu = False
        self._sayac = itertools.count(1)
        self._isler = {}
        self._dosyalar = {}
        self._yerel = threading.local()

    # ── Kurulum ───────────────────────────────────────────────────────────────
    def _kur(self):
        with self._kilit:
            if self._kuruldu:
                return
            import gradio as gr
            from studioflow.arayuz import uygulama
            self.gr = gr
            app = uygulama.Uygulama()
            b = app.b
            araclar = [app.video, app.gorsel, app.karakter, app.ses, app.prompt, app.muzik,
                       app.efekt, app.yazi, app.buyutme, app.harita]
            with gr.Blocks() as demo:
                b.demo = demo
                with gr.Tabs() as arac_sekmeleri:
                    for sayfa in araclar:
                        sayfa.kur(b)
                with gr.Tabs() as hesap_sekmesi:
                    app.hesaplar.kur(b)
                for sayfa in [app.hesaplar, app.video, app.ses, app.gorsel, app.karakter, app.prompt,
                              app.muzik, app.efekt, app.yazi, app.buyutme, app.arastirma,
                              app.konu_bul, app.seslendirme_promptu, app.tasarim_promptu, app.harita]:
                    sayfa.bagla(b)
            self.demo, self.b = demo, b
            self.bloklar = demo.blocks
            self.olaylar = defaultdict(list)
            self.acilis = []
            self.render = []
            for fn in demo.fns.values():
                if fn.fn is None:
                    continue
                if fn.renderable is not None:
                    self.render.append(fn)
                    continue
                for hedef, olay in fn.targets:
                    if olay == "load":
                        self.acilis.append(fn)
                    else:
                        self.olaylar[(hedef, olay)].append(fn)
            # Gradio'nun kuralı: açıkça belirtilmemişse yalnızca bir olayın girdisi olan
            # bileşen düzenlenebilir; yalnızca çıktı olan (üretilen video, durum) salt okunur.
            self.girdiler = {c._id for fn in demo.fns.values() for c in fn.inputs}
            self.degerler = {}
            for kimlik, blok in self.bloklar.items():
                if type(blok).__name__ in DUZEN:
                    continue
                deger = getattr(blok, "value", None)
                if callable(deger):
                    try:
                        deger = deger()
                    except Exception:
                        deger = None
                self.degerler[kimlik] = deger
            self.araclar = []
            for sira, sekme in enumerate(list(arac_sekmeleri.children) + list(hesap_sekmesi.children)):
                ad = getattr(sekme, "label", "") or f"Araç {sira + 1}"
                anahtar = "api-hesaplari" if sekme in hesap_sekmesi.children else (
                    getattr(sekme, "elem_id", None) or f"arac-{sira}").removeprefix("sf-")
                self.araclar.append({"id": anahtar, "ad": ad, "simge": SIMGE.get(ad, "🧰"),
                                     "blok": sekme, "altlar": self._alt_kimlikler(sekme)})
            self._uyarilari_yakala()
            self._kuruldu = True

    def _alt_kimlikler(self, blok):
        kimlikler = {blok._id}
        for cocuk in getattr(blok, "children", []) or []:
            kimlikler |= self._alt_kimlikler(cocuk)
        return kimlikler

    def _uyarilari_yakala(self):
        """`gr.Warning` / `gr.Info` çağrıları çalışan işin uyarılarına yazılsın (Gradio
        sunucusu yokken bunlar yalnızca konsola düşerdi)."""
        gr, yerel = self.gr, self._yerel
        eski_uyari, eski_bilgi = gr.Warning, gr.Info

        def yakala(eski, tur):
            def islev(message="", *a, **k):
                is_ = getattr(yerel, "is_", None)
                if is_ is not None:
                    is_.uyarilar.append({"tur": tur, "metin": str(message)})
                    return None
                return eski(message, *a, **k)
            return islev
        gr.Warning = yakala(eski_uyari, "uyari")
        gr.Info = yakala(eski_bilgi, "bilgi")

    # ── Ağaç ──────────────────────────────────────────────────────────────────
    def liste(self):
        self._kur()
        return [{"id": a["id"], "ad": a["ad"], "simge": a["simge"]} for a in self.araclar]

    def _arac(self, anahtar):
        self._kur()
        arac = next((a for a in self.araclar if a["id"] == anahtar), None)
        if arac is None:
            raise KopruHatasi(f"Böyle bir araç yok: {anahtar}")
        return arac

    def agac(self, anahtar):
        arac = self._arac(anahtar)
        with self._kilit:
            dugum = self._dugum(arac["blok"])
        olayli = sorted({f"{h}:{o}" for (h, o) in self.olaylar if h in arac["altlar"]})
        render = [self._render_bilgisi(fn) for fn in self.render
                  if any(c._id in arac["altlar"] for c in fn.inputs)]
        return {"id": arac["id"], "ad": arac["ad"], "simge": arac["simge"], "agac": dugum,
                "olaylar": olayli, "render": render}

    def _render_bilgisi(self, fn):
        """`gr.render` listesi: editör girdinin (State) değerinden kendisi çizer."""
        girdi = fn.inputs[0]._id if fn.inputs else None
        return {"girdi": girdi, "tur": "ef_adaylar" if getattr(self.b, "ef_adaylar", None) is not None
                and girdi == self.b.ef_adaylar._id else "bilinmiyor"}

    def _dugum(self, blok):
        tur = type(blok).__name__
        if tur == "Form":
            return [self._dugum(c) for c in blok.children]
        try:
            ayarlar = blok.get_config()
        except Exception:
            ayarlar = {}
        siniflar = ayarlar.get("elem_classes") or []
        if "sf-stil" in siniflar or "sf-gizli" in siniflar:
            return None
        props = {k: _json(ayarlar[k]) for k in PROPLAR if ayarlar.get(k) is not None}
        if tur in ("Tab",):
            props["label"] = getattr(blok, "label", "")
        if tur == "Accordion":
            props["label"] = getattr(blok, "label", "")
            props["open"] = bool(getattr(blok, "open", False))
        if tur in ("Textbox",) and ayarlar.get("type") == "password":
            props["sifre"] = True
        if tur not in DUZEN:
            props["value"] = self._istemci_degeri(blok, self.degerler.get(blok._id))
            if getattr(blok, "interactive", None) is None and tur not in ("Button", "DownloadButton"):
                props["interactive"] = blok._id in self.girdiler
        cocuklar = []
        for c in getattr(blok, "children", []) or []:
            d = self._dugum(c)
            if isinstance(d, list):
                cocuklar.extend(x for x in d if x)
            elif d:
                cocuklar.append(d)
        dugum = {"id": blok._id, "tur": tur, "props": props}
        if tur in DUZEN:
            dugum["cocuklar"] = cocuklar
        return dugum

    # ── Değerler ──────────────────────────────────────────────────────────────
    def dosya_adresi(self, yol):
        yol = Path(str(yol))
        if not yol.is_file():
            return None
        anahtar = hashlib.sha1(f"{yol.resolve()}|{yol.stat().st_mtime}".encode()).hexdigest()[:16]
        self._dosyalar[anahtar] = yol
        return f"/arac-dosya/{anahtar}/{yol.name}"

    def dosya(self, anahtar):
        return self._dosyalar.get(anahtar)

    def _resim_kaydet(self, resim):
        GECICI.mkdir(parents=True, exist_ok=True)
        hedef = GECICI / f"arac-{time.time():.6f}.png"
        resim.save(hedef)
        return hedef

    def _istemci_degeri(self, blok, deger):
        tur = type(blok).__name__
        if tur == "State":
            return None
        if deger is None:
            return None
        if tur in ("File", "DownloadButton", "Image", "Audio", "Video"):
            if hasattr(deger, "save") and tur == "Image":
                deger = self._resim_kaydet(deger)
            if isinstance(deger, dict):
                deger = deger.get("path") or deger.get("name")
            if isinstance(deger, (list, tuple)) and tur in ("Video",):
                deger = deger[0] if deger else None
            if isinstance(deger, (list, tuple)):
                return [x for x in ({"ad": Path(str(y)).name, "adres": self.dosya_adresi(y)}
                                    for y in deger if y) if x["adres"]]
            adres = self.dosya_adresi(deger) if deger else None
            return {"ad": Path(str(deger)).name, "adres": adres} if adres else None
        if tur == "Gallery":
            sonuc = []
            for oge in deger or []:
                baslik = ""
                if isinstance(oge, (list, tuple)):
                    oge, baslik = oge[0], (oge[1] if len(oge) > 1 else "")
                if hasattr(oge, "save"):
                    oge = self._resim_kaydet(oge)
                if isinstance(oge, dict):
                    oge = oge.get("path") or (oge.get("image") or {}).get("path")
                adres = self.dosya_adresi(oge) if oge else None
                if adres:
                    sonuc.append({"adres": adres, "baslik": str(baslik or ""), "ad": Path(str(oge)).name})
            return sonuc
        return _json(deger)

    def _iceri(self, blok, deger):
        tur = type(blok).__name__
        if tur in ("Number", "Slider") and deger not in (None, ""):
            try:
                deger = float(deger)
                return int(deger) if deger.is_integer() and tur == "Slider" and float(
                    getattr(blok, "step", 1) or 1).is_integer() else deger
            except (TypeError, ValueError):
                return None
        if tur == "Checkbox":
            return bool(deger)
        if tur in ("File", "Image", "Audio", "Video") and deger in ("", []):
            return None
        return deger

    def degerleri_yaz(self, degerler):
        self._kur()
        with self._kilit:
            for kimlik, deger in (degerler or {}).items():
                kimlik = int(kimlik)
                blok = self.bloklar.get(kimlik)
                if blok is None or type(blok).__name__ in DUZEN or type(blok).__name__ == "State":
                    continue
                self.degerler[kimlik] = self._iceri(blok, deger)

    # ── Olaylar ───────────────────────────────────────────────────────────────
    def olay(self, kimlik, olay, degerler=None):
        """Editördeki olay: değerleri yaz, bağlı işlevleri arka planda çalıştır."""
        self.degerleri_yaz(degerler)
        islevler = self.olaylar.get((int(kimlik), olay), [])
        if not islevler:
            return None
        blok = self.bloklar.get(int(kimlik))
        baslik = str(getattr(blok, "value", "") if type(blok).__name__ == "Button" else
                     getattr(blok, "label", "") or "")
        return self._baslat(baslik, lambda is_: [self._calistir(fn, is_) for fn in islevler])

    def acilis_olaylari(self, anahtar):
        """Araç açılınca `demo.load` işlevleri (listeleri, özetleri doldurur)."""
        arac = self._arac(anahtar)
        islevler = [fn for fn in self.acilis if any(c._id in arac["altlar"] for c in fn.outputs)]
        if not islevler:
            return None
        return self._baslat("Açılış", lambda is_: [self._calistir(fn, is_) for fn in islevler])

    def ef_indir(self, aday):
        """Ses efekti aracının listesindeki **İndir** (StudioFlow'un `ef_indir`'i)."""
        self._kur()
        from studioflow.arayuz.islevler_efekt_araci import ef_indir

        def calis(is_):
            sonuc = self._guvenli(is_, lambda: ef_indir(aday))
            if sonuc is not YOK:
                self._uygula([self.b.ef_durum, self.b.ef_dosya], sonuc, is_)
        return self._baslat("İndir", calis)

    def _baslat(self, baslik, govde):
        is_ = Is(next(self._sayac), baslik)
        self._isler[is_.no] = is_
        for eski in [n for n in self._isler if n < is_.no - 200]:
            self._isler.pop(eski, None)

        def calis():
            self._yerel.is_ = is_
            try:
                govde(is_)
                if is_.durum == "calisiyor":
                    is_.durum = "bitti"
            except Exception as hata:        # beklenmedik: sunucu düşmesin
                is_.durum, is_.hata = "hata", f"Beklenmeyen hata: {hata}"
            finally:
                is_.bitis = time.time()
                self._yerel.is_ = None
        threading.Thread(target=calis, daemon=True, name=f"arac-{is_.no}").start()
        return is_.no

    def is_durumu(self, no, son=0):
        is_ = self._isler.get(int(no))
        if is_ is None:
            raise KopruHatasi("İş bulunamadı")
        return is_.ozet(int(son or 0))

    def _guvenli(self, is_, cagri):
        gr = self.gr
        try:
            return cagri()
        except gr.Error as hata:
            is_.hata = str(getattr(hata, "message", hata))
            is_.durum = "hata"
        except Exception as hata:
            is_.hata = f"{type(hata).__name__}: {hata}"
            is_.durum = "hata"
        return YOK

    def _calistir(self, fn, is_, derinlik=0):
        with self._kilit:
            girdiler = [self.degerler.get(c._id) for c in fn.inputs]
        degisen = set()

        def cagri():
            sonuc = fn.fn(*girdiler)
            if inspect.isgenerator(sonuc):
                for paket in sonuc:
                    degisen.update(self._uygula(fn.outputs, paket, is_))
            else:
                degisen.update(self._uygula(fn.outputs, sonuc, is_))
            return True
        if self._guvenli(is_, cagri) is YOK:
            return
        if derinlik < 6:
            for kimlik in sorted(degisen):
                for sonraki in self.olaylar.get((kimlik, "change"), []):
                    self._calistir(sonraki, is_, derinlik + 1)

    def _uygula(self, ciktilar, paket, is_):
        gr = self.gr
        ciktilar = list(ciktilar or [])
        if not ciktilar:
            return set()
        if len(ciktilar) == 1:
            degerler = [paket]
        else:
            degerler = list(paket) if isinstance(paket, (tuple, list)) else [paket]
        degisen = set()
        for blok, deger in zip(ciktilar, degerler):
            props = {}
            yeni = deger
            if isinstance(deger, dict) and deger.get("__type__") == "update":
                props = {k: v for k, v in deger.items() if k != "__type__"}
                yeni = props.pop("value", YOK)
            elif isinstance(deger, gr.blocks.Block):
                for parca in getattr(deger, "_constructor_args", None) or []:
                    if isinstance(parca, dict):
                        props.update(parca)
                yeni = props.pop("value", YOK)
            props = {k: _json(v) for k, v in props.items() if k in PROPLAR}
            if yeni is not YOK:
                with self._kilit:
                    eski = self.degerler.get(blok._id, YOK)
                    self.degerler[blok._id] = yeni
                try:
                    farkli = eski is YOK or eski != yeni
                except Exception:
                    farkli = True
                if farkli:
                    degisen.add(blok._id)
                if type(blok).__name__ == "State":
                    try:
                        props["state"] = _json(yeni)
                    except Exception:
                        pass
                else:
                    props["value"] = self._istemci_degeri(blok, yeni)
            if props:
                is_.yama(blok._id, props)
        return degisen

    # ── Yükleme ───────────────────────────────────────────────────────────────
    def yukle(self, dosya_adi, icerik):
        YUKLEMELER.mkdir(parents=True, exist_ok=True)
        temiz = "".join(c if c.isalnum() or c in "-_." else "-" for c in Path(dosya_adi or "dosya").name)
        hedef = YUKLEMELER / f"{time.strftime('%Y%m%d-%H%M%S')}-{temiz.strip('.-') or 'dosya'}"
        hedef.write_bytes(icerik)
        return {"yol": str(hedef), "ad": hedef.name, "adres": self.dosya_adresi(hedef)}


KOPRU = Kopru()
