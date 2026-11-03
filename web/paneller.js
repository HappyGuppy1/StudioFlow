/* StudioFlow Editör · proje bölümleri (StudioFlow'un proje sayfasının karşılığı).
 *
 * Metin · Seslendirme · Altyazı · Ayarlar formları sunucudaki alan tanımından (`form`)
 * çizilir; değer değişince bağlı alanlar sunucuda hesaplanır (ön ayar → biçim, model…) ve
 * değişiklik kısa bir gecikmeyle kaydedilir (projede proje.txt, taslakta taslak dosyası).
 * Dublaj · Müzik · Altyazı kaydı · Efekt · Sonuç videosu işlemleri StudioFlow'un kendi
 * işlevlerini arka plan işi olarak çalıştırır; iş bitince bölüm kendini tazeler.
 *
 * editor.js'teki yardımcıları kullanır ($, el, api, gonder, durum, projeYolu…); bu dosya
 * yalnızca işlev tanımlar, çağrılar editor.js yüklendikten sonra olur.
 */
"use strict";

const P = {
  ayar: null, bekleyen: {}, kayitZamanlayici: null,
  ciktiModu: "video",
  belgeler: null, belgeNotu: "",
  planRaporu: "", testSesi: null, testMesaji: "",
  kadro: null, kart: { ad: "", tarif: "", gorsel: "", adres: null }, kadroNotu: "",
  kutuphane: null, kutuphaneYazilan: "", kutuphaneAriyor: false, aramaNo: 0,
  dublaj: null, dublajForm: null, edgeSesleri: {},
  muzik: null, muzikDosya: null, muzikForm: { tarif: "", sure: 60, bpm: 0, isim: "", seviye: 10, bas: 0, bit: 0, giris: 0, cikis: 0 },
  altyazilar: null, altyaziForm: { dil: "en", isim: "" }, zemin: "koyu", onizlemeZamanlayici: null,
  efekt: null, efektIsim: "", manuel: null, efdKayit: "", efd: null, oneriler: {}, efektSeviye: 100,
  sonuc: null, mp3: null,
  genelOzet: "", otomatik: null,
};

const taslakMi = () => !!durum.proje?.taslak;
const isSuruyor = () => durum.uretim?.durum === "calisiyor";
const kilitli = () => isSuruyor() || !!P.ayar?.calisiyor;
const sayiBicim = (v) => (Math.round(Number(v) * 100) / 100).toLocaleString("tr-TR");
const kelimeSay = (m) => String(m || "").split(/\s+/).filter(Boolean).length;
const panelAcikMi = (ad) => !$(`.panel-bolum[data-panel="${ad}"]`)?.hidden;
const aciklama = (metin) => el("p", { class: "soluk aciklama" }, metin);
const kucukNot = (metin, sinif = "soluk") => metin ? el("small", { class: `alan-not ${sinif}` }, metin) : null;
/* ⓘ: açıklama etiketin yanında küçük düğmede durur, tıklayınca balonda açılır. */
function bilgiDugmesi(metin) {
  if (!metin) return null;
  const temiz = String(metin).replace(/\*\*/g, "");
  return el("button", { type: "button", class: "bilgi-i", "aria-label": "Açıklama", title: "Açıklama",
    onclick: (o) => { o.preventDefault(); o.stopPropagation(); balonGoster(o.currentTarget, temiz); } }, "i");
}
function balonGoster(dugme, metin) {
  let b = $("#bilgi-balon");
  if (!b) {
    b = el("div", { id: "bilgi-balon", role: "tooltip", hidden: true });
    document.body.append(b);
    document.addEventListener("click", () => { b.hidden = true; });
    document.addEventListener("keydown", (o) => { if (o.key === "Escape") b.hidden = true; });
    document.addEventListener("scroll", () => { b.hidden = true; }, true);
  }
  if (!b.hidden && b.dataset.sahip === metin) { b.hidden = true; return; }
  b.textContent = metin; b.dataset.sahip = metin; b.hidden = false;
  const r = dugme.getBoundingClientRect(), w = Math.min(320, window.innerWidth - 24);
  b.style.width = `${w}px`;
  b.style.left = `${Math.max(12, Math.min(r.left - 12, window.innerWidth - w - 12))}px`;
  const asagi = r.bottom + 8 + b.offsetHeight < window.innerHeight;
  b.style.top = `${asagi ? r.bottom + 8 : Math.max(8, r.top - 8 - b.offsetHeight)}px`;
}
const lejant = (baslik, metin) => el("legend", {}, baslik, bilgiDugmesi(metin));
const ozet = (baslik, metin) => el("summary", {}, baslik, bilgiDugmesi(metin));
const etiketSatiri = (etiket, metin) => el("span", { class: "alan-ad" }, etiket, bilgiDugmesi(metin));
const dinle = (adres) => adres ? el("audio", { controls: true, preload: "none", src: adres, class: "dinle" }) : null;

/* DOM'a ekle; boş (null/false) çocuklar atlanır. */
const ekle = (kap, ...cocuk) => kap.append(...cocuk.flat(3).filter(c => c !== null && c !== undefined && c !== false));
/* Bölümü yeniden çiz: açık bölmeler (details) ve kaydırma konumu korunur; açılan bölme
   içeriğini yeniden yükler (toggle olayı). */
function yerindeCiz(kap, ...cocuk) {
  const anahtar = (d) => d.dataset.anahtar || d.querySelector(":scope > summary")?.textContent || "";
  const acik = new Set($$("details[open]", kap).map(anahtar));
  const panel = kap.closest(".panel"), kaydirma = panel?.scrollTop;
  kap.replaceChildren(); ekle(kap, ...cocuk);
  for (const d of $$("details", kap)) if (acik.has(anahtar(d)) && !d.open) d.open = true;
  if (panel && kaydirma != null) panel.scrollTop = kaydirma;
}

function kayitDurumu(metin) { $$(".kayit-durum").forEach(e => { e.textContent = metin; }); }

/* Kota harcayan ya da videoyu değiştiren işi başlat; iş üst çubukta ve Üretim bölümünde izlenir. */
async function isBaslat(yol, govde = {}, onay = null, yontem = "POST") {
  if (onay && !(await onayIste(onay[0], onay[1]))) return null;
  try {
    const ozet = await api(projeYolu(yol), { method: yontem, headers: { "Content-Type": "application/json" },
      body: yontem === "DELETE" ? undefined : JSON.stringify(govde) });
    durum.uretim = ozet; uretimiIzle(); bolumleriCiz();
    return ozet;
  } catch (hata) { alertKutusu(hata.message); disaAyariniTazele(); return null; }
}

/* ── Ayarlar: yükle, çiz, kaydet ───────────────────────────────────────── */
async function ayarlariYukle(ciz = true) {
  if (!durum.proje) return;
  if (Object.keys(P.bekleyen).length) await ayarlariKaydetSimdi();   // yazılmamış değişiklik kaybolmasın
  try { P.ayar = await api(projeYolu("/ayarlar")); P.bekleyen = {}; }
  catch (hata) { P.ayar = null; kayitDurumu(`Ayarlar okunamadı: ${hata.message}`); }
  if (ciz) ayarBolumleriniCiz();
}
function ayarBolumleriniCiz() {
  metinBolumunuCiz(); seslendirmeBolumunuCiz(); altyaziBolumunuCiz(); ayarlarBolumunuCiz();
}
function kaydetZamanla() {
  clearTimeout(P.kayitZamanlayici);
  kayitDurumu("değişti…");
  P.kayitZamanlayici = setTimeout(ayarlariKaydetSimdi, 700);
}
async function ayarlariKaydetSimdi() {
  clearTimeout(P.kayitZamanlayici);
  const govde = P.bekleyen; P.bekleyen = {};
  if (!Object.keys(govde).length || !durum.proje) return;
  kayitDurumu("kaydediliyor…");
  try {
    const yeni = await gonder(projeYolu("/ayarlar"), govde, "PUT");
    const yazilan = { ...P.bekleyen };
    P.ayar = { ...yeni, degerler: { ...yeni.degerler, ...yazilan } };
    if ("metin" in yazilan) P.ayar.metin = yazilan.metin;
    kayitDurumu("kaydedildi ✓");
    if ("video.bicim" in govde || "gorsel.width" in govde) projeyiTazele();
    if ("ses.ref" in govde) seslendirmeBolumunuCiz();
  } catch (hata) {
    kayitDurumu(`kaydedilemedi: ${hata.message}`);
    alertKutusu(`Ayar kaydedilemedi: ${hata.message}`);
    await ayarlariYukle();
  }
}
async function alanDegisti(anahtar, deger, ciz = true) {
  const a = P.ayar; if (!a) return;
  a.degerler[anahtar] = deger; P.bekleyen[anahtar] = deger;
  if (ciz) {
    try {
      const b = await gonder("/api/ayar/bagli", { alan: anahtar, degerler: a.degerler });
      Object.assign(a.degerler, b.degisen); Object.assign(P.bekleyen, b.degisen);
      a.notlar = b.notlar; a.model = b.model; a.edge_sesleri = b.edge_sesleri;
    } catch { /* bağlı alanlar hesaplanamadıysa yalnızca bu alan yazılır */ }
    ayarBolumleriniCiz();
  }
  kaydetZamanla();
}

function secenekListesi(f) {
  const a = P.ayar, s = a.secenekler, d = a.degerler;
  if (f.anahtar === "ses.edge_ses") return (a.edge_sesleri || []).map(x => [x, x]);
  if (f.anahtar === "video.model") return (s["video.model"][d["video.ai"]] || []).map(m => [m, m]);
  return s[f.anahtar] || [];
}
const gorunur = (f) => !f.kosul || Object.entries(f.kosul).every(([k, v]) => P.ayar.degerler[k] === v);

function aralikSiniri(f) {
  const m = P.ayar.model || {};
  if (f.anahtar === "gorsel.steps" && m.steps) return { min: m.steps.min, max: m.steps.max, adim: 1 };
  if (f.anahtar === "gorsel.guidance" && m.guidance) return { min: m.guidance.min, max: m.guidance.max, adim: 0.5 };
  if (f.anahtar === "gorsel.width" || f.anahtar === "gorsel.height") {
    return m.boyut ? { min: m.boyut.min, max: m.boyut.max, adim: m.boyut.adim } : { min: f.min, max: f.max, adim: f.adim, kilit: true };
  }
  return { min: f.min, max: f.max, adim: f.adim };
}

function alanCiz(f) {
  const a = P.ayar, d = a.degerler, deger = d[f.anahtar], kilit = kilitli();
  const degis = (v, ciz = true) => alanDegisti(f.anahtar, v, ciz);
  const negatifKilit = (f.anahtar === "gorsel.negatif" || f.anahtar === "video.ilk_negatif") && a.model && !a.model.negatif;
  let girdi, satirIci = false;
  if (f.tur === "secim") {
    let liste = secenekListesi(f);
    if (deger !== null && deger !== undefined && deger !== "" && !liste.some(([, v]) => String(v) === String(deger)))
      liste = [[String(deger), deger], ...liste];
    const bos = deger === null || deger === undefined || deger === "";
    // Değer boşken ilk seçenek seçiliymiş gibi görünmesin (gerçekte hiçbir şey seçili değildir).
    girdi = el("select", { disabled: kilit, onchange: (o) => { if (o.target.value !== "") degis(o.target.value); } },
      bos ? el("option", { value: "", selected: true }, "— seç —") : null,
      liste.map(([e, v]) => el("option", { value: v, selected: String(v) === String(deger) || null }, e)));
  } else if (f.tur === "dugmeler") {
    girdi = el("div", { class: "secenek-grubu sarili", role: "radiogroup", "aria-label": f.etiket },
      secenekListesi(f).map(([e, v]) => el("button", { type: "button", class: `dugme kucuk${v === deger ? " secili" : ""}`,
        "aria-pressed": String(v === deger), disabled: kilit, onclick: () => degis(v) }, e)));
  } else if (f.tur === "uzun" || f.tur === "metin") {
    const sayac = f.sayac ? el("small", { class: "alan-not soluk" }) : null;
    const sayacYaz = (m) => {
      if (!sayac) return;
      const n = kelimeSay(m), sinir = a.kelime_siniri || 55;
      sayac.textContent = n ? (n <= sinir ? `≈${n} kelime · tamamı modele ulaşır.` : `⚠ ≈${n} kelime · model yalnızca ilk ~${sinir} kelimeyi okur; en önemli öğeyi başa yaz.`) : "";
      sayac.classList.toggle("uyari", n > sinir);
    };
    girdi = [el("textarea", { rows: f.satir || 2, value: deger ?? "", placeholder: f.yer || null, disabled: kilit || negatifKilit,
      oninput: (o) => { degis(o.target.value, false); sayacYaz(o.target.value); } }), sayac];
    sayacYaz(deger);
  } else if (f.tur === "aralik") {
    const s = aralikSiniri(f), cikti = el("output", {}, sayiBicim(deger));
    girdi = el("div", { class: "aralik-satir" },
      el("input", { type: "range", min: s.min, max: s.max, step: s.adim, value: deger, disabled: kilit || s.kilit,
        oninput: (o) => { cikti.textContent = sayiBicim(o.target.value); }, onchange: (o) => degis(Number(o.target.value)) }), cikti);
  } else if (f.tur === "evet") {
    satirIci = true;
    girdi = el("input", { type: "checkbox", checked: !!deger, disabled: kilit, onchange: (o) => degis(o.target.checked) });
  } else if (f.tur === "renk") {
    girdi = el("input", { type: "color", value: deger || "#ffffff", disabled: kilit, onchange: (o) => degis(o.target.value) });
  } else if (f.tur === "dosya") {
    const dosyaAdi = deger ? String(deger).split(/[\\/]/).pop() : "";
    girdi = el("div", { class: "dosya-alani" },
      a.ref_adres ? dinle(a.ref_adres) : el("span", { class: "soluk" }, dosyaAdi || "Referans ses yok"),
      el("div", { class: "dugme-satiri" },
        el("label", { class: `dugme kucuk${kilit ? " pasif" : ""}` }, "Dosya seç",
          el("input", { type: "file", accept: f.kabul || "*/*", hidden: true, disabled: kilit,
            onchange: async (o) => { const dosya = o.target.files[0]; if (dosya) { await dosyaYukle("referans", dosya); await ayarlariYukle(); } } })),
        deger ? el("button", { type: "button", class: "dugme kucuk", disabled: kilit, onclick: () => degis("", true) }, "Kaldır") : null));
  }
  // Seçim zaten düğmenin renginden okunur: "Seçili …" notları gösterilmez. Kalan notlar
  // (ön ayarın, modelin açıklaması) ⓘ balonuna girer; yalnızca kilit uyarısı görünür kalır.
  const notMetni = ["video.ai", "video.sahne_stratejisi"].includes(f.anahtar) ? "" : (a.notlar?.[f.anahtar] || "");
  const kilitUyarisi = f.anahtar === "gorsel.negatif" && notMetni;
  const yardim = [f.bilgi, kilitUyarisi ? "" : notMetni].filter(Boolean).join("\n\n");
  const kap = satirIci
    ? el("label", { class: "alan satir-alan" }, girdi, el("span", {}, f.etiket), bilgiDugmesi(yardim))
    : el(f.tur === "dugmeler" || f.tur === "aralik" || f.tur === "dosya" ? "div" : "label", { class: "alan" },
        etiketSatiri(f.etiket, yardim), girdi);
  kap.dataset.alan = f.anahtar;
  if (kilitUyarisi) kap.append(el("small", { class: "alan-not uyari" }, "🔒 Bu görsel modeli negatif prompt almaz; alan kilitli.", bilgiDugmesi(notMetni)));
  return kap;
}

function ayarFormu(bolum) {
  const a = P.ayar; if (!a?.form?.[bolum]) return [];
  return a.form[bolum].map(g => {
    const icerik = [...g.alanlar.filter(gorunur).map(alanCiz), ozelBolum(g.ozel)].filter(Boolean);
    return g.kapali
      ? el("details", { class: "katlanir grup", dataset: { anahtar: g.grup } }, ozet(g.grup, g.aciklama), ...icerik)
      : el("fieldset", { class: "grup" }, lejant(g.grup, g.aciklama), ...icerik);
  });
}
function ozelBolum(ad) {
  if (ad === "plan") return planKutusu();
  if (ad === "altyazi_onizleme") return altyaziOnizlemeKutusu();
  return null;
}
function kilitNotu() {
  if (P.ayar?.calisiyor) return el("p", { class: "hata-metin" }, "Proje çalışıyor; ayarlar durunca değiştirilebilir.");
  return null;
}

/* ── Metin ──────────────────────────────────────────────────────────────── */
function metinBolumunuCiz() {
  const kap = $("#panel-metin"); if (!kap) return;
  const a = P.ayar;
  if (!a) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  const sayac = el("small", { class: "alan-not soluk" });
  const sayacYaz = (m) => { const n = kelimeSay(m); sayac.textContent = n ? `${n} kelime · ~${Math.round(n / (a.kelime_hizi || 2.2))} sn seslendirme` : ""; };
  sayacYaz(a.metin);
  yerindeCiz(kap, ...[
    kilitNotu(),
    belgelerKutusu(),
    el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Anlatım metni (seslendirilecek yazı)"),
      el("textarea", { id: "anlatim-metni", class: "anlatim", rows: 9, value: a.metin, readonly: a.metin_kilitli || null,
        disabled: kilitli(), placeholder: "Videonun anlatım metnini buraya yapıştır…",
        oninput: (o) => { a.metin = o.target.value; P.bekleyen.metin = o.target.value; kaydetZamanla(); sayacYaz(o.target.value); } }),
      sayac,
      a.metin_kilitli ? kucukNot("Bu projede anlatım seslendirildi; metin değiştirilemez (StudioFlow da kayıtlı metni kullanır). Yeni metin için yeni proje başlat.") : null),
    ...ayarFormu("metin"),
    el("button", { type: "button", class: "dugme genis-dugme", onclick: () => panelSec("karakterler") },
      "👥 Karakterler · hazır karakterler ve kadro"),
  ].filter(Boolean));
}

function belgelerKutusu() {
  const kutu = el("details", { class: "katlanir", ontoggle: (o) => { if (o.target.open && !P.belgeler) belgeleriYukle(); } },
    ozet("📄 Kayıtlı belgeler · seslendirme ve prompt belgesini yükle", "Araçlar › Prompt'ta kaydedilen belgeler: seslendirme belgesi anlatım metnini, prompt belgesi genel prompt, stil, negatif ve ilk sahneyi doldurur. Hazırlık sırası: konu bul → araştırma → seslendirme promptu → tasarım promptu."));
  kutu.dataset.anahtar = "belgeler";
  if (P.belgeler) kutu.open = true;
  const secici = (tur, etiket, yardim) => el("label", { class: "alan" }, etiketSatiri(etiket, yardim),
    el("select", { disabled: kilitli() || (tur === "seslendirme" && P.ayar.metin_kilitli),
      onchange: (o) => { if (o.target.value) belgeAc(tur, o.target.value); } },
      el("option", { value: "" }, P.belgeler ? `— ${(P.belgeler[tur] || []).length} belge —` : "— yükleniyor —"),
      (P.belgeler?.[tur] || []).map(ad => el("option", { value: ad }, ad))));
  ekle(kutu, 
    el("a", { class: "dugme kucuk", href: "#araclar/prompt-tool" }, "🧰 Prompt stüdyosunu aç"),
    secici("seslendirme", "Seslendirme belgesi", "Anlatım metnini doldurur."),
    secici("prompt", "Prompt belgesi", "Genel prompt, stil, negatif ve ilk sahneyi doldurur."),
    el("div", { class: "dugme-satiri" }, el("button", { type: "button", class: "dugme kucuk", onclick: belgeleriYukle }, "↻ Listeyi yenile")),
    kucukNot(P.belgeNotu, "vurgulu"));
  return kutu;
}
async function belgeleriYukle() {
  try { P.belgeler = await api("/api/belgeler"); } catch (hata) { P.belgeNotu = `Belgeler okunamadı: ${hata.message}`; }
  metinBolumunuCiz();
}
async function belgeAc(tur, ad) {
  try {
    const b = await api(`/api/belge/${tur}/${encodeURIComponent(ad)}`);
    if (tur === "seslendirme") { P.ayar.metin = b.metin; P.bekleyen.metin = b.metin; }
    else for (const [k, v] of Object.entries(b.alanlar)) { P.ayar.degerler[k] = v; P.bekleyen[k] = v; }
    P.belgeNotu = `✅ ${b.not}`; kaydetZamanla();
  } catch (hata) { P.belgeNotu = `⚠ ${hata.message}`; }
  metinBolumunuCiz();
}

function planKutusu() {
  const a = P.ayar, suruyor = isSuruyor() && durum.uretim?.tur === "plan";
  return el("div", { class: "plan-kutusu" },
    el("button", { type: "button", class: "dugme genis-dugme", disabled: kilitli() || !String(a.metin || "").trim(),
      title: "Anlatımı seçili strateji ve tavanla sahnelere böl; her sahneye içeriğine göre süre ver",
      onclick: async () => { await ayarlariKaydetSimdi(); P.planRaporu = ""; await isBaslat("/plan", {}); } },
      suruyor ? "⏳ Sahne planı çıkarılıyor…" : "🎬 Video sürelerini yapay zekâ ayarlasın"),
    a.sahne_plani && !P.planRaporu ? kucukNot("Kayıtlı sahne planı var: proje başlarken yapay zekâya yeniden sorulmaz, sahneler aynen bununla kurulur.", "vurgulu") : null,
    P.planRaporu ? el("pre", { class: "alan-metin rapor" }, P.planRaporu.replace(/\*\*/g, "")) : null);
}

/* 👥 Karakterler bölümü: hazır karakter kütüphanesi (arama + örnekler) ve projenin kadrosu. */
function karakterlerBolumunuCiz() {
  const kap = $("#panel-karakterler"); if (!kap) return;
  yerindeCiz(kap, kutuphaneKutusu(), kadroKutusu());
}
async function karakterleriAc() {
  const isler = [];
  if (!P.kutuphane) isler.push(kutuphaneAra(""));
  if (!P.kadro && durum.proje) isler.push(kadroyuYukle());
  karakterlerBolumunuCiz();
  await Promise.all(isler);
}

function kutuphaneKutusu() {
  const ara = () => kutuphaneAra(P.kutuphaneYazilan);
  return el("fieldset", { class: "grup kutuphane" },
    el("legend", {}, el("span", { id: "kutuphane-baslik" }, kutuphaneBasligi()), bilgiDugmesi(
      "Hazır karakterler: her birinin referans görseli ve İngilizce tarifi var. Karta tıkla, aşağıdaki kartta adını düzenleyip kaydet; ya da ＋ ile doğrudan kadroya ekle. Aramaya bir kelime yaz (ör. kırmızı, salyangoz, Afrika, tetra): yapay zekâ kütüphaneden alakalı karakterleri bulur.")),
    el("div", { class: "kutuphane-ara" },
      el("input", { type: "search", value: P.kutuphaneYazilan, placeholder: "Karakter ara… (ör. kırmızı balık)",
        "aria-label": "Karakter ara",
        oninput: (o) => { P.kutuphaneYazilan = o.target.value; if (!o.target.value.trim() && P.kutuphane?.sorgu) kutuphaneAra(""); },
        onkeydown: (o) => { if (o.key === "Enter") { o.preventDefault(); ara(); } } }),
      el("button", { type: "button", class: "dugme kucuk birincil", title: "Yapay zekâyla ara", onclick: ara }, "🔍 Ara")),
    el("div", { id: "kutuphane-sonuc", class: "kutuphane-sonuc" }, kutuphaneSonucu()));
}
function kutuphaneSonucu() {
  const s = P.kutuphane, kilit = kilitli() || !durum.proje;
  if (!s) return [el("p", { class: "soluk" }, "Yükleniyor…")];
  const kartlar = (s.karakterler || []).map(c => el("div", { class: "kutuphane-oge", title: c.tarif },
    el("button", { type: "button", class: "kutuphane-gorsel", disabled: kilit, "aria-label": `${c.ad} kartı doldursun`,
      onclick: () => karakterSec(c) }, el("img", { src: c.adres, alt: c.ad, loading: "lazy" })),
    el("div", { class: "kutuphane-alt" },
      el("span", { class: "kutuphane-ad" }, c.ad, el("small", { class: "soluk" }, c.grup)),
      el("button", { type: "button", class: "dugme kucuk", title: "Kadroya ekle", disabled: kilit,
        onclick: () => kutuphanedenEkle(c) }, "＋"))));
  return [
    P.kutuphaneAriyor ? kucukNot("✨ Yapay zekâ kütüphanede arıyor…", "vurgulu") : null,
    s.mesaj ? kucukNot(s.mesaj, s.karakterler?.length ? "uyari" : "soluk") : null,
    kartlar.length ? el("div", { class: "kutuphane-izgara" }, kartlar) : null,
    el("div", { class: "dugme-satiri" },
      s.sorgu ? el("button", { type: "button", class: "dugme kucuk", onclick: () => { P.kutuphaneYazilan = ""; kutuphaneAra(""); karakterlerBolumunuCiz(); } }, "✕ Aramayı temizle")
              : el("button", { type: "button", class: "dugme kucuk", onclick: () => kutuphaneAra("") }, "🎲 Başka örnekler"),
      s.toplam ? el("small", { class: "soluk" }, `Kütüphanede ${s.toplam} karakter`) : null),
  ].filter(Boolean);
}
const kutuphaneBasligi = () => P.kutuphane?.sorgu ? `“${P.kutuphane.sorgu}” için sonuçlar` : "Örnek karakterler";
/* Yalnızca başlığı ve sonuç alanını tazele: arama kutusuna yazılırken odak kaybolmasın. */
function kutuphaneSonucunuCiz() {
  const kap = $("#kutuphane-sonuc");
  if (!kap) { if (panelAcikMi("karakterler")) karakterlerBolumunuCiz(); return; }
  kap.replaceChildren(); ekle(kap, kutuphaneSonucu());
  const baslik = $("#kutuphane-baslik"); if (baslik) baslik.textContent = kutuphaneBasligi();
}
async function kutuphaneAra(sorgu) {
  sorgu = String(sorgu || "").trim();
  const no = ++P.aramaNo, adres = `/api/kutuphane?ara=${encodeURIComponent(sorgu)}`;
  const yaz = (s, ariyor) => { if (no !== P.aramaNo) return; P.kutuphane = s; P.kutuphaneAriyor = ariyor; kutuphaneSonucunuCiz(); };
  try {
    if (!sorgu) return yaz(await api(adres), false);
    // Önce yerel eşleşme (anında), ardından yapay zekânın seçtikleri.
    yaz(await api(`${adres}&yz=0`), true);
    yaz(await api(adres), false);
  } catch (hata) {
    yaz({ ...(P.kutuphane || {}), mesaj: `Arama yapılamadı: ${hata.message}` }, false);
  }
}
function karakterSec(c) {
  Object.assign(P.kart, { ad: c.ad, tarif: c.tarif, gorsel: c.yol, adres: c.adres });
  P.kadroNotu = `${c.ad} karta alındı: adını anlatımda kullanacağın adla değiştir, Karakteri kaydet'e bas.`;
  karakterlerBolumunuCiz();
  $("#panel-karakterler .kadro-kart")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
async function kutuphanedenEkle(c) {
  try { P.kadro = await gonder(projeYolu("/kadro"), { ad: c.ad, tarif: c.tarif, gorsel: c.yol }); P.kadroNotu = P.kadro.mesaj; }
  catch (hata) { P.kadroNotu = `⚠ ${hata.message}`; }
  karakterlerBolumunuCiz();
}

/* 👥 Karakter kadrosu */
function kadroKutusu() {
  const kutu = el("fieldset", { class: "grup kadro" },
    lejant("Kadro · tek ya da çok karakterli senaryo", `Tekrar eden karakterleri kaydet; her kare sahnedeki karakterlerin referans görseliyle üretilir, yüz ve kıyafet sahneden sahneye korunur. Anlatımda karakteri burada yazdığın adla an. FLUX.2 klein · karede en fazla ${P.kadro?.azami_kare ?? 4} karakter · kadroda en fazla ${P.kadro?.azami_kadro ?? 40}.`));
  if (!durum.proje) { ekle(kutu, el("p", { class: "soluk" }, "Kadro için bir proje aç.")); return kutu; }
  const k = P.kart, kilit = kilitli();
  const liste = P.kadro?.karakterler || [];
  ekle(kutu, 
    P.kadro && !P.kadro.model_uygun ? el("p", { class: "hata-metin" }, "Seçili görsel modeli referans görsel almıyor: karakterli proje için Ayarlar › Görsel modelini FLUX.2 klein 4B yap.") : null,
    el("div", { class: "kadro-kart" },
      el("div", { class: "kadro-gorsel" }, k.adres ? el("img", { src: k.adres, alt: k.ad || "Referans" }) : el("span", { class: "soluk" }, "Referans görsel")),
      el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Adı"),
        el("input", { value: k.ad, placeholder: "ör. Tekir", disabled: kilit, oninput: (o) => { k.ad = o.target.value; } })),
      el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Görünüşü · İngilizce"),
        el("textarea", { rows: 2, value: k.tarif, disabled: kilit, placeholder: "ör. a chubby orange tabby cat, green eyes, red collar with a golden bell",
          oninput: (o) => { k.tarif = o.target.value; } })),
      el("div", { class: "dugme-satiri" },
        el("label", { class: `dugme kucuk${kilit ? " pasif" : ""}` }, "🖼 Görsel yükle",
          el("input", { type: "file", accept: "image/*", hidden: true, disabled: kilit,
            onchange: async (o) => { const d = o.target.files[0]; if (!d) return; const s = await dosyaYukle("karakter", d); if (s) { k.gorsel = s.yol; k.adres = s.adres; kadroBolumunuCiz(); } } })),
        el("button", { type: "button", class: "dugme kucuk", disabled: kilit, onclick: karakterReferansiUret }, "✨ Tariften görsel üret"),
        el("button", { type: "button", class: "dugme kucuk birincil", disabled: kilit, onclick: karakteriKaydet }, "💾 Karakteri kaydet"))),
    kucukNot(P.kadroNotu, "vurgulu"),
    liste.length ? el("div", { class: "kadro-liste" }, liste.map(c => {
      const duzenle = () => { Object.assign(P.kart, { ad: c.ad, tarif: c.tarif, gorsel: c.gorsel, adres: c.adres }); P.kadroNotu = `${c.ad} düzenleniyor: değiştirip Karakteri kaydet'e bas.`; kadroBolumunuCiz(); };
      return el("div", { class: `kadro-oge${P.kart.ad === c.ad ? " secili" : ""}` },
        el("button", { type: "button", class: "kadro-oge-gorsel", title: `${c.ad} · düzenle`, disabled: kilit, onclick: duzenle },
          c.adres ? el("img", { src: c.adres, alt: c.ad, loading: "lazy" }) : el("span", { class: "kare-yok" })),
        el("div", { class: "kadro-oge-alt" },
          el("button", { type: "button", class: "kadro-oge-ad", title: c.ad, disabled: kilit, onclick: duzenle }, c.ad),
          el("button", { type: "button", class: "dugme kucuk tehlike", title: "Kadrodan çıkar", disabled: kilit, onclick: () => karakteriSil(c.ad) }, "🗑")));
    }))
      : (P.kadro ? el("p", { class: "soluk" }, "Henüz kayıtlı karakter yok: kartı doldur, Karakteri kaydet'e bas.") : null));
  return kutu;
}
function kadroBolumunuCiz() {
  const eski = $("#panel-karakterler fieldset.kadro");
  if (eski) eski.replaceWith(kadroKutusu()); else karakterlerBolumunuCiz();
}
async function kadroyuYukle() {
  try { P.kadro = await api(projeYolu("/kadro")); } catch (hata) { P.kadroNotu = hata.message; }
  kadroBolumunuCiz();
}
async function karakterReferansiUret() {
  const k = P.kart;
  if (!k.ad.trim() || !k.tarif.trim()) { P.kadroNotu = "Önce karakterin adını ve tarifini yaz."; return kadroBolumunuCiz(); }
  if (!(await onayIste("Referans görsel üretilsin mi?", "Projenin görsel stili ve modeliyle tam boy bir referans üretilir (görsel kotası harcar)."))) return;
  P.kadroNotu = "⏳ Referans üretiliyor…"; kadroBolumunuCiz();
  try { const s = await gonder(projeYolu("/kadro/referans"), { ad: k.ad, tarif: k.tarif }); k.gorsel = s.yol; k.adres = s.adres; P.kadroNotu = s.mesaj; }
  catch (hata) { P.kadroNotu = `⚠ ${hata.message}`; }
  kadroBolumunuCiz();
}
async function karakteriKaydet() {
  const k = P.kart;
  try {
    P.kadro = await gonder(projeYolu("/kadro"), { ad: k.ad, tarif: k.tarif, gorsel: k.gorsel });
    P.kadroNotu = P.kadro.mesaj; Object.assign(P.kart, { ad: "", tarif: "", gorsel: "", adres: null });
  } catch (hata) { P.kadroNotu = `⚠ ${hata.message}`; }
  kadroBolumunuCiz();
}
async function karakteriSil(ad) {
  if (!(await onayIste(`${ad} kadrodan çıkarılsın mı?`, "Karakter kadrodan çıkar; üretilmiş karelere dokunulmaz."))) return;
  try { P.kadro = await api(projeYolu(`/kadro/${encodeURIComponent(ad)}`), { method: "DELETE" }); P.kadroNotu = P.kadro.mesaj; }
  catch (hata) { P.kadroNotu = `⚠ ${hata.message}`; }
  kadroBolumunuCiz();
}

async function dosyaYukle(tur, dosya) {
  try {
    return await api(projeYolu(`/yukle?tur=${tur}&dosya=${encodeURIComponent(dosya.name)}`), { method: "POST", body: dosya });
  } catch (hata) { alertKutusu(`Yüklenemedi: ${hata.message}`); return null; }
}

/* ── Seslendirme ────────────────────────────────────────────────────────── */
function seslendirmeBolumunuCiz() {
  const kap = $("#panel-seslendirme"); if (!kap) return;
  if (!P.ayar) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  yerindeCiz(kap, ...[
    kilitNotu(),
    P.ayar.ses_hazir ? aciklama("Bu projenin seslendirmesi bitti: ses ayarlarını değiştirmek mevcut sesi değiştirmez (seviye hariç; o videoya eklenirken uygulanır).") : null,
    ...ayarFormu("seslendirme"),
    el("fieldset", { class: "grup" }, lejant("Ses testi · kaydedilmez", "Seçili servis, dil ve sesle dilin hazır test cümlesini okur. Test sesi projeye yazılmaz."),
      el("button", { type: "button", class: "dugme birincil genis-dugme", id: "ses-test",
        onclick: sesiTestEt }, "Sesi test et · kaydedilmez"),
      P.testSesi ? el("audio", { controls: true, autoplay: true, src: P.testSesi, class: "dinle" }) : null,
      kucukNot(P.testMesaji, "vurgulu")),
  ].filter(Boolean));
}
async function sesiTestEt() {
  await ayarlariKaydetSimdi();
  const d = $("#ses-test"); d.disabled = true; d.textContent = "⏳ Test ediliyor…";
  try { const s = await gonder(projeYolu("/ses-testi"), {}); P.testSesi = s.adres; P.testMesaji = s.mesaj; }
  catch (hata) { P.testSesi = null; P.testMesaji = `⚠ ${hata.message}`; }
  seslendirmeBolumunuCiz();
}

/* ── Altyazı ────────────────────────────────────────────────────────────── */
function altyaziOnizlemeKutusu() {
  const s = P.ayar.secenekler["altyazi.zemin"] || [];
  const kutu = el("div", { class: "altyazi-onizleme" },
    el("label", { class: "alan" }, etiketSatiri("Önizleme zemini", "Yalnızca önizlemeyi etkiler; videoya gömülmez."),
      el("select", { onchange: (o) => { P.zemin = o.target.value; altyaziOnizlemesiniTazele(); } },
        s.map(([e, v]) => el("option", { value: v, selected: v === P.zemin || null }, e)))),
    el("div", { class: "onizleme-kare", id: "altyazi-onizleme-kare" }, el("span", { class: "soluk" }, "Önizleme hazırlanıyor…")),
    el("small", { class: "alan-not soluk", id: "altyazi-onizleme-not" }));
  clearTimeout(P.onizlemeZamanlayici);
  P.onizlemeZamanlayici = setTimeout(altyaziOnizlemesiniTazele, 250);
  return kutu;
}
async function altyaziOnizlemesiniTazele() {
  const kare = $("#altyazi-onizleme-kare"); if (!kare || !P.ayar) return;
  try {
    const s = await gonder("/api/altyazi-onizleme", { degerler: P.ayar.degerler, zemin: P.zemin });
    kare.replaceChildren(s.adres ? el("img", { src: s.adres, alt: "Altyazı önizlemesi" }) : el("span", { class: "soluk" }, "Önizleme üretilemedi."));
    $("#altyazi-onizleme-not").textContent = s.not || "";
  } catch (hata) { kare.replaceChildren(el("span", { class: "soluk" }, `Önizleme: ${hata.message}`)); }
}
function altyaziBolumunuCiz() {
  const kap = $("#panel-altyazi"); if (!kap) return;
  if (!P.ayar) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  const parcalar = [kilitNotu(), ...ayarFormu("altyazi")];
  if (!taslakMi()) {
    const kilit = isSuruyor(), f = P.altyaziForm, liste = P.altyazilar;
    const secili = liste?.find(x => x.secili)?.ad || "";
    parcalar.push(
      el("div", { class: "dugme-satiri" }, el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: kilit,
        onclick: async () => { await ayarlariKaydetSimdi(); isBaslat("/altyazi-yeniden", {}, ["Video altyazısı tekrar oluşturulsun mu?", "Videodaki altyazı yukarıdaki ayarlarla baştan kurulur: eski gömme kaldırılır, seslendirme ve ekli dil geri uygulanır."]); } },
        "Video altyazısını tekrar oluştur"),
        bilgiDugmesi("Videodaki altyazıyı yukarıdaki ayarlarla baştan kurar: eski gömme kaldırılır, seslendirme ve ekli dil geri uygulanır. Altyazı Üret kapalıysa yenisi gömülmez, yalnızca eski altyazı kaldırılır. Altyazı dosyası yoksa anlatım metninden üretilir (ses yeniden üretilmez).")),
      el("fieldset", { class: "grup" }, lejant("Altyazı kaydet · dile göre ayrı altyazı", "Dili seç → Altyazıyı kaydet. Kaynak sırayla: o dilin dublajının altyazısı → projenin kendi altyazısı → yoksa metinden yazılır (hiçbir servise istek gitmez)."),
        el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Altyazı dili"),
          el("select", { onchange: (o) => { f.dil = o.target.value; } },
            (P.ayar.secenekler.dil || []).map(([e, v]) => el("option", { value: v, selected: v === f.dil || null }, e)))),
        el("label", { class: "alan" }, etiketSatiri("Altyazı adı (opsiyonel)", "Dublajla aynı adı verirsen o dublajın altyazısı kaydedilir."),
          el("input", { value: f.isim, placeholder: "ör. en-kisa · boşsa dil kodu", oninput: (o) => { f.isim = o.target.value; } })),
        el("button", { type: "button", class: "dugme birincil", disabled: kilit,
          onclick: () => isBaslat("/altyazilar", { dil: f.dil, isim: f.isim }) }, "Altyazıyı kaydet")),
      el("fieldset", { class: "grup" }, lejant("Kayıtlı altyazılar · videoya göm", "Seçili altyazı görüntüye yazılır (hard sub); videoda gömülü altyazı varsa önce o kaldırılır, yazılar üst üste binmez."),
        liste === null ? el("p", { class: "soluk" }, "Yükleniyor…")
          : liste.length ? el("div", { class: "kayit-listesi" }, liste.map(k => el("div", { class: `kayit${k.secili ? " secili" : ""}` },
              el("label", { class: "kayit-sec" }, el("input", { type: "radio", name: "altyazi-secim", checked: k.secili, disabled: kilit,
                onchange: () => secimYaz(`/altyazilar/${encodeURIComponent(k.ad)}/sec`, altyazilariYukle) }),
                el("b", {}, k.ad), el("span", { class: "soluk" }, ` · ${k.ozet}`)),
              el("div", { class: "kayit-islem" },
                k.srt ? el("a", { class: "dugme kucuk", href: k.srt, download: true }, "srt") : null,
                k.vtt ? el("a", { class: "dugme kucuk", href: k.vtt, download: true }, "vtt") : null,
                el("button", { type: "button", class: "dugme kucuk tehlike", disabled: kilit,
                  onclick: () => isBaslat(`/altyazilar/${encodeURIComponent(k.ad)}`, {}, [`${k.ad} silinsin mi?`, "Altyazı kaydı ve dosyaları silinir; videoda gömülüyse video yeniden kurulur."], "DELETE") }, "🗑")))))
          : el("p", { class: "soluk" }, "Kayıtlı altyazı yok: dil seç ve Altyazıyı kaydet'e bas."),
        el("button", { type: "button", class: "dugme birincil", disabled: kilit || !secili,
          onclick: () => isBaslat(`/altyazilar/${encodeURIComponent(secili)}/gom`, {}) }, "Seçili altyazıyı videoya göm")));
  } else {
    parcalar.push(aciklama("Altyazı kaydı ve videoya gömme proje başlatılınca açılır; ayarlar şimdiden projeye yazılır."));
  }
  yerindeCiz(kap, ...parcalar.filter(Boolean));
}
async function altyazilariYukle() {
  if (taslakMi()) return;
  try { P.altyazilar = await api(projeYolu("/altyazilar")); } catch { P.altyazilar = []; }
  altyaziBolumunuCiz();
}
async function secimYaz(yol, sonra) {
  try { await gonder(projeYolu(yol), {}); } catch (hata) { alertKutusu(hata.message); }
  await sonra(); await disaAyariniTazele();
}

/* ── Ayarlar ────────────────────────────────────────────────────────────── */
function ayarlarBolumunuCiz() {
  const kap = $("#panel-ayarlar"); if (!kap) return;
  if (!P.ayar) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  const kilit = kilitli();
  const YARDIM = { "Ayarları kaydet · bütün ayarlar tek genel dosyada": "Bu projenin bütün ayarları tek dosyaya kaydedilir; StudioFlow her açılışta, editör her yeni projede kendiliğinden yükler (proje adı, anlatım metni ve karakterler kaydedilmez).",
                   "Üretilen dosyaları outputs klasörüne otomatik kaydet": "Kapalıyken görsel, ses ve video geçici klasöre yazılır. Bu tercih editörün kendi işlemleri içindir." };
  const katlanir = (baslik, ac, ...icerik) => el("details", { class: "katlanir", dataset: { anahtar: baslik }, ontoggle: (o) => { if (o.target.open && ac) ac(o.target); } }, ozet(baslik, YARDIM[baslik]), ...icerik);
  yerindeCiz(kap, ...[
    kilitNotu(),
    aciklama(taslakMi() ? "Ayarlar taslağa yazılır; proje başlatılınca bu ayarlarla kurulur."
      : "Değişiklik proje.txt'e yazılır ve yalnızca kalan adımlara uygulanır; hazır kare, klip ve ses korunur."),
    ...ayarFormu("ayarlar"),
    katlanir("Ayarları kaydet · bütün ayarlar tek genel dosyada", async (d) => {
      try { P.genelOzet = (await api("/api/ayar/genel")).ozet; } catch { /* eski sunucu */ }
      const pre = d.querySelector("pre"); if (pre) pre.textContent = P.genelOzet.replace(/\*\*/g, "");
    },
      el("div", { class: "dugme-satiri" },
        el("button", { type: "button", class: "dugme birincil", disabled: kilit, onclick: async () => {
          await ayarlariKaydetSimdi();
          try { const s = await gonder(projeYolu("/ayar/genel-kaydet"), {}); P.genelOzet = s.ozet; alertKutusu(s.mesaj); } catch (h) { alertKutusu(h.message); }
          ayarlarBolumunuCiz(); } }, "Ayarları kaydet"),
        el("button", { type: "button", class: "dugme", disabled: kilit, onclick: async () => {
          if (!(await onayIste("Kayıtlı ayarlar yüklensin mi?", "Genel ayar dosyasındaki değerler bu projenin ayarlarının üzerine yazılır (karakterler hariç)."))) return;
          try { P.ayar = await gonder(projeYolu("/ayar/genel-yukle"), {}); alertKutusu("Kayıtlı ayarlar yüklendi."); } catch (h) { alertKutusu(h.message); }
          ayarBolumleriniCiz(); projeyiTazele(); } }, "Kayıtlı ayarları yükle"),
        el("button", { type: "button", class: "dugme kucuk tehlike", onclick: async () => {
          if (!(await onayIste("Kayıtlı genel ayar silinsin mi?", "Genel ayar dosyası silinir; projedeki değerler değişmez."))) return;
          try { P.genelOzet = (await api("/api/ayar/genel", { method: "DELETE" })).ozet; } catch (h) { alertKutusu(h.message); }
          ayarlarBolumunuCiz(); } }, "Kayıtlı ayarı sil")),
      el("pre", { class: "alan-metin" }, (P.genelOzet || "Yükleniyor…").replace(/\*\*/g, ""))),
    katlanir("Üretilen dosyaları outputs klasörüne otomatik kaydet", async () => {
      try { P.otomatik = await api("/api/ayar/otomatik"); } catch { /* eski sunucu */ }
      const k = $("#otomatik-kaydet"); if (k && P.otomatik) { k.checked = P.otomatik.acik; $("#otomatik-not").textContent = P.otomatik.mesaj; }
    },
      el("label", { class: "alan satir-alan" }, el("input", { type: "checkbox", id: "otomatik-kaydet", checked: !!P.otomatik?.acik,
        onchange: async (o) => { try { P.otomatik = await gonder("/api/ayar/otomatik", { acik: o.target.checked }); $("#otomatik-not").textContent = P.otomatik.mesaj; } catch (h) { alertKutusu(h.message); } } }),
        el("span", {}, "Otomatik kaydetmeyi aç")),
      el("small", { class: "alan-not soluk", id: "otomatik-not" }, P.otomatik?.mesaj || "Kapalıyken görsel, ses ve video geçici klasöre yazılır. Bu tercih editörün kendi işlemleri içindir.")),
    taslakMi() ? null : katlanir("proje.txt · projenin tek kaydı", async (d) => {
      const pre = d.querySelector("pre"); pre.textContent = "Yükleniyor…";
      try { pre.textContent = await (await fetch(projeYolu("/kayit"))).text(); } catch (h) { pre.textContent = h.message; }
    }, el("pre", { class: "alan-metin proje-kaydi" }, "")),
    taslakMi() ? null : katlanir("Proje dosyaları", async (d) => {
      const kap2 = d.querySelector(".dosya-listesi"); kap2.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…"));
      try {
        const liste = await api(projeYolu("/dosyalar"));
        d.querySelector("summary").textContent = `Proje dosyaları · ${liste.length} dosya`;
        kap2.replaceChildren(...liste.map(x => el("a", { href: x.adres, target: "_blank", class: "dosya-satiri" },
          el("span", {}, x.yol), el("span", { class: "soluk" }, boyutYaz(x.boyut)))));
      } catch (h) { kap2.replaceChildren(el("p", { class: "soluk" }, h.message)); }
    }, el("div", { class: "dosya-listesi" })),
    taslakMi() ? null : katlanir("Parça görselleri", (d) => {
      const g = d.querySelector(".parca-izgara");
      g.replaceChildren(...durum.sahneler.filter(s => s.kare).map(s => el("a", { href: s.kare, target: "_blank", title: `Sahne ${s.index}` },
        el("img", { src: s.kare, alt: `Sahne ${s.index}`, loading: "lazy" }))));
      if (!g.children.length) g.append(el("p", { class: "soluk" }, "Henüz kare yok."));
    }, el("div", { class: "parca-izgara" })),
  ].filter(Boolean));
}
const boyutYaz = (b) => b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

/* ── Dublaj ─────────────────────────────────────────────────────────────── */
function dublajFormu() {
  if (!P.dublajForm) {
    const s = P.ayar?.secenekler || {};
    P.dublajForm = { dil: "en", cevir: true, ceviri_ai: "gemini", sahneye_gore: false, provider: "gemini",
      edge_ses: "", hiz: 0, ton: 0, gemini_model: (s["ses.gemini_model"] || [[""]])[0][1] || "",
      gemini_ses: "Charon", isim: "" };
  }
  return P.dublajForm;
}
async function edgeSesleriniAl(dil) {
  if (!P.edgeSesleri[dil]) {
    try { P.edgeSesleri[dil] = (await gonder("/api/ayar/bagli", { alan: "ses.dil", degerler: { "ses.dil": dil } })).edge_sesleri; }
    catch { P.edgeSesleri[dil] = []; }
  }
  return P.edgeSesleri[dil];
}
function dublajBolumunuCiz() {
  const kap = $("#panel-dublaj"); if (!kap) return;
  if (taslakMi()) { kap.replaceChildren(aciklama("Dublaj proje başlatılıp seslendirme bittikten sonra üretilir.")); return; }
  if (!P.ayar) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  const f = dublajFormu(), s = P.ayar.secenekler, kilit = isSuruyor();
  const sec = (etiket, liste, deger, yaz, ek) => el("label", { class: "alan" }, etiketSatiri(etiket, ek),
    el("select", { onchange: (o) => { yaz(o.target.value); } }, liste.map(([e, v]) => el("option", { value: v, selected: String(v) === String(deger) || null }, e))));
  const kutu = (etiket, deger, yaz, ek) => el("label", { class: "alan satir-alan" }, el("input", { type: "checkbox", checked: deger, onchange: (o) => yaz(o.target.checked) }), el("span", {}, etiket), bilgiDugmesi(ek));
  const aralik = (etiket, min, max, adim, deger, yaz) => { const c = el("output", {}, deger); return el("div", { class: "alan" }, el("span", { class: "alan-ad" }, etiket),
    el("div", { class: "aralik-satir" }, el("input", { type: "range", min, max, step: adim, value: deger, oninput: (o) => { c.textContent = o.target.value; yaz(Number(o.target.value)); } }), c)); };
  const sesler = P.edgeSesleri[f.dil];
  if (f.provider === "edge" && !sesler) edgeSesleriniAl(f.dil).then(dublajBolumunuCiz);
  const liste = P.dublaj, secili = liste?.find(x => x.secili)?.ad || "";
  const seviye = Number(P.ayar.degerler["ses.seviye"] ?? 100);
  yerindeCiz(kap, 
    el("fieldset", { class: "grup" }, lejant("Dublaj üret ve kaydet · dil · ses servisi · çeviri", "Dili seç → gerekirse çeviriyi aç → ses servisini seç → Dublajı kaydet. Ad verirsen aynı dile birden fazla dublaj kaydedebilirsin; ad boşsa dil koduyla saklanır ve aynı dili yeniden üretmek kaydı günceller. Dublajla birlikte altyazı da üretilirse ayrı bir altyazı kaydı olur."),
      sec("Hedef dil", s.dil || [], f.dil, (v) => { f.dil = v; f.edge_ses = ""; dublajBolumunuCiz(); }),
      kutu("Anlatımı hedef dile çevir", f.cevir, (v) => { f.cevir = v; }, "Kapatırsan metin zaten o dilde olmalı; projenin diliyle aynı dili seçersen çeviri yapılmaz."),
      sec("Çeviriyi yapan yapay zekâ", s["video.ai"] || [], f.ceviri_ai, (v) => { f.ceviri_ai = v; }, "Ses servisinden bağımsızdır; kota biterse aynı servisin sıradaki hesabına geçilir."),
      kutu("Sahnelere göre hizala", f.sahneye_gore, (v) => { f.sahneye_gore = v; }, "Çeviri ve ses sahne sahne kurulur: her cümle kendi sahnesinin süresine sığar, sesler üst üste binmez. Kapalıyken dublaj tek parça üretilir."),
      el("div", { class: "alan" }, el("span", { class: "alan-ad" }, "Ses servisi"),
        el("div", { class: "secenek-grubu sarili" }, (s["ses.provider"] || []).map(([e, v]) => el("button", { type: "button",
          class: `dugme kucuk${v === f.provider ? " secili" : ""}`, onclick: () => { f.provider = v; dublajBolumunuCiz(); } }, e)))),
      f.provider === "edge" ? [
        sec("Edge sesi", (sesler || []).map(x => [x, x]), f.edge_ses || sesler?.[0], (v) => { f.edge_ses = v; }),
        aralik("Konuşma hızı (%)", -50, 50, 5, f.hiz, (v) => { f.hiz = v; }),
        aralik("Ton (Hz)", -50, 50, 5, f.ton, (v) => { f.ton = v; }),
      ] : null,
      f.provider === "gemini" ? [
        sec("Gemini modeli", s["ses.gemini_model"] || [], f.gemini_model, (v) => { f.gemini_model = v; }),
        sec("Gemini sesi", s["ses.gemini_ses"] || [], f.gemini_ses, (v) => { f.gemini_ses = v; }),
      ] : null,
      f.provider === "chatterbox" ? aciklama("Chatterbox, API hesaplarındaki Hugging Face tokenıyla çalışır ve sesi referans kaydı olmadan üretir. Sesi klonlamak için Araçlar › Seslendirme aracını kullan.") : null,
      el("label", { class: "alan" }, etiketSatiri("Dublaj adı (opsiyonel)", "Ad dosya adına çevrilir (boşluk - olur). Aynı adla kaydetmek kaydı günceller."),
        el("input", { value: f.isim, placeholder: "ör. en-charon · boşsa dil kodu", oninput: (o) => { f.isim = o.target.value; } })),
      el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: kilit,
        onclick: () => isBaslat("/dublaj", { ...f, edge_ses: f.edge_ses || sesler?.[0] || "" },
          ["Dublaj üretilsin mi?", "Seçilen dilde dublaj üretilip kaydedilir (çeviri ve ses kotası harcar)."]) }, "Dublajı kaydet")),
    el("fieldset", { class: "grup" }, lejant("Kayıtlı dublajlar · videoya ekle", "Video modunda video ham videodan yeniden kurulur: tek konuşma sesi olur, gömülü altyazı kalkar (yeniden gömebilirsin), ekli müzik geri uygulanır."),
      liste === null ? el("p", { class: "soluk" }, "Yükleniyor…")
        : liste.length ? el("div", { class: "kayit-listesi" }, liste.map(k => el("div", { class: `kayit${k.secili ? " secili" : ""}` },
            el("label", { class: "kayit-sec" }, el("input", { type: "radio", name: "dublaj-secim", checked: k.secili, disabled: kilit,
              onchange: () => secimYaz(`/dublaj/${encodeURIComponent(k.ad)}/sec`, dublajlariYukle) }),
              el("b", {}, k.ad), el("span", { class: "soluk" }, ` · ${k.ozet}`)),
            dinle(k.ses),
            el("div", { class: "kayit-islem" },
              k.altyazi ? el("a", { class: "dugme kucuk", href: k.altyazi, download: true }, "altyazı") : null,
              el("button", { type: "button", class: "dugme kucuk tehlike", disabled: kilit,
                onclick: () => isBaslat(`/dublaj/${encodeURIComponent(k.ad)}`, {}, [`${k.ad} silinsin mi?`, "Dublaj kaydı ve ses dosyası silinir; videodaysa video yeniden kurulur."], "DELETE") }, "🗑")))))
        : el("p", { class: "soluk" }, "Kayıtlı dublaj yok: dil seç ve Dublajı kaydet'e bas."),
      hedefNotu(),
      aralikSatiri("Dublaj ses seviyesi (%)", 25, 400, 5, seviye, (v) => alanDegisti("ses.seviye", v, false), "100 = dublajın kendi seviyesi; seslendirme seviyesiyle aynı değerdir."),
      el("button", { type: "button", class: "dugme birincil", disabled: kilit || !secili,
        onclick: () => isBaslat(`/dublaj/${encodeURIComponent(secili)}/ekle`, { seviye: Number(P.ayar.degerler["ses.seviye"] ?? 100), mod: P.ciktiModu }) },
        P.ciktiModu === "ses" ? "Seçili dublajı sese ekle" : "Seçili dublajı videoya ekle")));
}
/* Sürgü + yazılabilir sayı kutusu: ikisi birbirini günceller. Yazılan sayı aralığa
   sıkıştırılır (adıma yuvarlanmaz: %12 gibi ara değerler de girilebilir). */
function aralikSatiri(etiket, min, max, adim, deger, yaz, bilgi) {
  const sinirla = (v) => Math.min(max, Math.max(min, v));
  const surgu = el("input", { type: "range", min, max, step: adim, value: deger,
    oninput: (o) => { kutu.value = o.target.value; }, onchange: (o) => yaz(Number(o.target.value)) });
  const kutu = el("input", { type: "number", min, max, step: adim, value: deger, class: "aralik-sayi",
    oninput: (o) => { const v = Number(o.target.value); if (o.target.value !== "" && Number.isFinite(v)) surgu.value = sinirla(v); },
    onchange: (o) => {
      const v = Number(o.target.value);
      const son = o.target.value === "" || !Number.isFinite(v) ? Number(surgu.value) : sinirla(v);
      o.target.value = son; surgu.value = son; yaz(son);
    },
    onkeydown: (o) => { if (o.key === "Enter") o.target.blur(); } });
  return el("div", { class: "alan" }, etiketSatiri(etiket, bilgi),
    el("div", { class: "aralik-satir" }, surgu, kutu));
}
async function dublajlariYukle() {
  if (taslakMi()) return;
  try { P.dublaj = await api(projeYolu("/dublaj")); } catch { P.dublaj = []; }
  dublajBolumunuCiz();
}

/* Katmanın nereye ekleneceği: StudioFlow videosu yoksa (proje bitmediyse) zaman çizelgesi. */
function hedefNotu() {
  if (P.ciktiModu === "ses") return el("p", { class: "soluk kucuk-yazi" }, "Hedef: ♪ Ses (youtube/<dil>/ses.mp3)");
  return el("p", { class: "soluk kucuk-yazi" }, durum.proje?.video
    ? "Ekle: projenin videosu (zaman çizelgesi, Dışa aktar) ve StudioFlow videosu (proje.mp4)."
    : "Ekle: hazır seslendirme ve toplam süreyle projenin videosuna (zaman çizelgesi, Dışa aktar). Bitmiş video gerekmez.");
}

/* ── Müzik ──────────────────────────────────────────────────────────────── */
function muzikBolumunuCiz() {
  const kap = $("#panel-muzik"); if (!kap) return;
  if (taslakMi()) { kap.replaceChildren(aciklama("Müzik proje başlatılınca eklenir.")); return; }
  const f = P.muzikForm, kilit = isSuruyor(), m = P.muzik, d = P.muzikDosya;
  const yz = isSuruyor() && durum.uretim?.tur === "muzik_yz";
  const ust = d ? Math.max(1, Math.round((Number(d.sure) || 0) + 0.5)) : 600;
  yerindeCiz(kap, 
    el("fieldset", { class: "grup" }, lejant("🎵 Yapay zekâ ile müzik üret · Lyria (ücretsiz · telifsiz)", "Google Lyria RealTime enstrümantal müzik üretir (Gemini anahtarıyla, seslendirme kotasından yemez). Müziği Türkçe tarif et; boş bırakırsan projenin anlatımından ve stilinden çıkarılır. 60 sn müzik yaklaşık 1 dakika sürer. Çıktıda duyulmayan bir SynthID filigranı vardır."),
      el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Müzik tarifi (opsiyonel)"),
        el("textarea", { rows: 2, value: f.tarif, placeholder: "ör. eski Mısır esintisi, gizemli, ney ve darbuka, yavaş · boşsa projeden çıkarılır", oninput: (o) => { f.tarif = o.target.value; } })),
      aralikSatiri("Süre (sn)", 10, 300, 5, f.sure, (v) => { f.sure = v; }),
      aralikSatiri("Tempo (BPM)", 0, 200, 1, f.bpm, (v) => { f.bpm = v; }, "0 = yapay zekâ tarife göre seçer."),
      el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: kilit,
        onclick: () => isBaslat("/muzik/uret", { tarif: f.tarif, sure: f.sure, bpm: f.bpm }) }, yz ? "⏳ Müzik üretiliyor…" : "🎵 Müzik üret")),
    el("fieldset", { class: "grup" }, lejant("Müzik kaydet · yükle · kırp · seviye · karartma", "Dosyayı yükle (ya da üret) → kırp → ses seviyesini ayarla → karartmaları seç → Müziği kaydet. Kaydedilen müzik aşağıdaki listede durur; videoya Videoya ekle ile girer. Kırpma ve seviye dosyaya işlenir; karartma eklenirken uygulanır. Varsayılan seviye %10: müzik anlatımın altında fon olarak kalır."),
      el("div", { class: "dugme-satiri" }, el("label", { class: `dugme${kilit ? " pasif" : ""}` }, "📁 Müzik dosyası yükle",
        el("input", { type: "file", accept: "audio/*", hidden: true, disabled: kilit, onchange: async (o) => {
          const dosya = o.target.files[0]; if (!dosya) return;
          const s = await dosyaYukle("muzik", dosya); if (!s) return;
          P.muzikDosya = { ...s, ad: dosya.name.replace(/\.[^.]+$/, "") };
          // Her yeni dosya kendi adını alır; önceki müziğin adı kalırsa kayıt onun üzerine yazıyordu.
          f.isim = P.muzikDosya.ad; f.bas = 0; f.bit = Math.round((s.sure || 0) * 2) / 2; muzikBolumunuCiz(); } }))),
      d ? [
        el("p", { class: "soluk" }, `Dosya: ${String(d.yol || "").split(/[\\/]/).pop()} · ${d.sure ? sureYaz(d.sure, false) : "süre okunamadı"}`),
        dinle(d.adres),
        d.not ? kucukNot(d.not) : null,
        aralikSatiri("Kırpma · başlangıç (sn)", 0, ust, 0.5, f.bas, (v) => { f.bas = v; }),
        aralikSatiri("Kırpma · bitiş (sn)", 0, ust, 0.5, f.bit || ust, (v) => { f.bit = v; }),
        aralikSatiri("Başlangıç karartma (sn)", 0, 10, 0.5, f.giris, (v) => { f.giris = v; }, "Müzik başlarken ses bu süre boyunca 0'dan yükselir."),
        aralikSatiri("Bitiş karartma (sn)", 0, 10, 0.5, f.cikis, (v) => { f.cikis = v; }, "Müzik biterken ses bu süre boyunca 0'a iner; video müziği kesiyorsa tam kesildiği yere uygulanır."),
        aralikSatiri("Ses seviyesi (%)", 0, 200, 5, f.seviye, (v) => { f.seviye = v; }, "100 = dosyanın kendi seviyesi. Müziğin duyulmasını daha çok istersen %20–40 dene."),
        el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Müzik adı"),
          el("input", { value: f.isim || d.ad || "", placeholder: "ör. yaz-muzigi · aynı adla kaydedersen üzerine yazar", oninput: (o) => { f.isim = o.target.value; } })),
        el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: kilit,
          onclick: () => isBaslat("/muzik", { yol: d.yol, isim: f.isim || d.ad || "", seviye: f.seviye, bas: f.bas, bit: f.bit || ust, giris: f.giris, cikis: f.cikis }) }, "Müziği kaydet"),
      ] : el("p", { class: "soluk" }, "Henüz dosya yok: yükle ya da yukarıdan üret.")),
    el("fieldset", { class: "grup" }, lejant("Kayıtlı müzikler · videoya ekle", "Kutuları işaretlediğin sırayla müzikler videoya girer (1. bitince 2. başlar). Videoya ekle müziği anlatımın/dublajın altına karıştırır; Müziği kaldır yalnızca müzik katmanını çıkarır."),
      m === null ? el("p", { class: "soluk" }, "Yükleniyor…")
        : m.kayitlar.length ? [
          el("div", { class: "kayit-listesi" }, m.kayitlar.map(k => el("div", { class: `kayit${k.sira ? " secili" : ""}` },
            el("label", { class: "kayit-sec muzik-sec" }, el("input", { type: "checkbox", checked: !!k.sira, disabled: kilit,
              onchange: (o) => muzikSeciminiYaz(k.ad, o.target.checked) }),
              el("span", { class: `secim-rozet${k.sira ? " acik" : ""}` }, k.sira ? `✓ ${k.sira}. sırada videoya girecek` : "Videoya girsin mi? İşaretle"),
              el("b", {}, k.ad), el("span", { class: "soluk" }, ` · ${k.ozet}`)),
            dinle(k.ses),
            el("div", { class: "kayit-islem" }, el("button", { type: "button", class: "dugme kucuk tehlike", disabled: kilit,
              onclick: () => isBaslat(`/muzik/${encodeURIComponent(k.ad)}`, {}, [`${k.ad} silinsin mi?`, "Müzik listeden ve diskten kaldırılır; videoda duyuluyorsa karışım tazelenir."], "DELETE") }, "🗑"))))),
          el("label", { class: "alan satir-alan" }, el("input", { type: "checkbox", checked: m.tekrarla, disabled: kilit, onchange: (o) => muzikTercihi({ tekrarla: o.target.checked }) }),
            el("span", {}, "Müzik kısa kalırsa video sonuna kadar tekrarla")),
          el("label", { class: "alan satir-alan" }, el("input", { type: "checkbox", checked: m.ducking, disabled: kilit, onchange: (o) => muzikTercihi({ ducking: o.target.checked }) }),
            el("span", {}, "Anlatım konuşurken müziği otomatik kıs (ducking)")),
          hedefNotu(),
          el("div", { class: "dugme-satiri" },
            el("button", { type: "button", class: "dugme birincil", disabled: kilit, onclick: async () => {
              // Hiç müzik işaretlenmediyse: tek kayıt varsa o seçilir, birden çoksa sorulur.
              if (!P.muzik.secim.length) {
                if (P.muzik.kayitlar.length === 1) await muzikSeciminiYaz(P.muzik.kayitlar[0].ad, true);
                else { alertKutusu("Önce videoya girecek müzikleri işaretle (her müziğin üstündeki kutu)."); return; }
              }
              isBaslat("/muzik/ekle", { mod: P.ciktiModu });
            } },
              P.ciktiModu === "ses" ? "Müziği ekle" : "Videoya ekle"),
            el("button", { type: "button", class: "dugme tehlike", disabled: kilit,
              onclick: () => isBaslat("/muzik/kaldir", { mod: P.ciktiModu }, ["Müzik kaldırılsın mı?", "Yalnızca müzik katmanı çıkarılır; konuşma sesi kalır."]) }, "Müziği kaldır")),
        ] : [
          el("p", { class: "soluk" }, "Kaydedilmiş müzik yok: yukarıdan yükle, kırp ve Müziği kaydet'e bas."),
          // Kayıtlı müzik silinmiş olsa da projeye eklenmiş müzik kalabilir (21.10.2026:
          // liste boşalınca "Müziği kaldır" kayboluyordu ve müzik videodan çıkarılamıyordu).
          m.ekli ? el("div", { class: "dugme-satiri" },
            el("span", { class: "soluk kucuk-yazi" }, "Projede eklenmiş müzik var."),
            el("button", { type: "button", class: "dugme tehlike", disabled: kilit,
              onclick: () => isBaslat("/muzik/kaldir", { mod: P.ciktiModu }, ["Müzik kaldırılsın mı?", "Yalnızca müzik katmanı çıkarılır; konuşma sesi kalır."]) }, "Müziği kaldır")) : null,
        ]));
}
async function muzikleriYukle() {
  if (taslakMi()) return;
  try { P.muzik = await api(projeYolu("/muzik")); } catch { P.muzik = { kayitlar: [], secim: [], tekrarla: false, ducking: true }; }
  muzikBolumunuCiz();
}
async function muzikSeciminiYaz(ad, isaretli) {
  const secim = P.muzik.secim.filter(x => x !== ad); if (isaretli) secim.push(ad);
  try { P.muzik = await gonder(projeYolu("/muzik/secim"), { secim }, "PUT"); } catch (h) { alertKutusu(h.message); }
  muzikBolumunuCiz(); disaAyariniTazele();
}
async function muzikTercihi(degisiklik) {
  try { P.muzik = await gonder(projeYolu("/muzik/tercih"), degisiklik, "PUT"); } catch (h) { alertKutusu(h.message); }
  muzikBolumunuCiz(); disaAyariniTazele();
}

/* ── Ses efektleri ──────────────────────────────────────────────────────── */
function efektBolumunuCiz() {
  const kap = $("#panel-efekt"); if (!kap) return;
  if (taslakMi()) { kap.replaceChildren(aciklama("Ses efektleri sahnelerin videoları üretildikten sonra hazırlanır.")); return; }
  const kilit = isSuruyor(), liste = P.efekt, secili = liste?.find(x => x.secili)?.ad || "";
  yerindeCiz(kap, 
    el("fieldset", { class: "grup" }, lejant("Ses efektleri · yapay zekâ ya da elle · Freesound (CC0)", "Sesler Freesound'dan yalnızca CC0 lisanslı kayıtlardan seçilir: atıf gerekmez, ticari kullanım serbesttir; GPU ya da video kotası harcanmaz. Yapay zekâ hazırlasın: hangi sahnede ne sesi olacağına yapay zekâ karar verir. Manuel: videosu üretilmiş her sahneye istediğin sesi yazarsın; boş sahne efektsiz kalır."),
      el("label", { class: "alan" }, etiketSatiri("Efekt kaydı adı (opsiyonel)", "Aynı adla hazırlamak kaydı günceller."),
        el("input", { value: P.efektIsim, placeholder: "ör. piramit-efektleri · boşsa tarihle adlandırılır", oninput: (o) => { P.efektIsim = o.target.value; } })),
      el("div", { class: "dugme-satiri" },
        el("button", { type: "button", class: "dugme birincil", disabled: kilit, onclick: () => isBaslat("/efekt/hazirla", { yontem: "yapay_zeka", isim: P.efektIsim }) }, "🤖 Yapay zekâ hazırlasın"),
        el("button", { type: "button", class: "dugme", disabled: kilit, onclick: manuelAc }, "✍️ Ses efektlerini manuel hazırla")),
      P.manuel ? el("div", { class: "manuel-liste" },
        P.manuel.length ? [
          el("p", { class: "soluk" }, `${P.manuel.length} sahne · her sahneye istediğin sesi yaz; boş kalan sahne efektsiz kalır.`),
          ...P.manuel.map(s => el("label", { class: "alan" },
            el("span", { class: "alan-ad" }, `Sahne ${s.index} · ${sayiBicim(s.bas)}–${sayiBicim(s.bas + s.sure)} sn · ${(s.metin || "—").slice(0, 110)}`),
            el("input", { value: s.istek || "", placeholder: "ör. yemek yeme sesi, kumda ayak sesi", oninput: (o) => { s.istek = o.target.value; } }))),
          el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: kilit, onclick: () => isBaslat("/efekt/hazirla",
            { yontem: "manuel", isim: P.efektIsim, istekler: Object.fromEntries(P.manuel.filter(s => (s.istek || "").trim()).map(s => [s.index, s.istek])) }) }, "Manuel efektleri hazırla"),
        ] : el("p", { class: "soluk" }, "Manuel efekt için videosu üretilmiş sahne gerekir.")) : null),
    el("fieldset", { class: "grup" }, lejant("Kayıtlı ses efektleri · videoya göm", "Efekt anlatımın ve müziğin altına karışır; görüntü ve gömülü altyazı korunur. Seviyeyi değiştirip yeniden gömmek için efektleri yeniden hazırlamak gerekmez."),
      liste === null ? el("p", { class: "soluk" }, "Yükleniyor…")
        : liste.length ? el("div", { class: "kayit-listesi" }, liste.map(k => el("div", { class: `kayit${k.secili ? " secili" : ""}` },
            el("label", { class: "kayit-sec" }, el("input", { type: "radio", name: "efekt-secim", checked: k.secili, disabled: kilit,
              onchange: () => secimYaz(`/efekt/${encodeURIComponent(k.ad)}/sec`, efektleriYukle) }),
              el("b", {}, k.ad), el("span", { class: "soluk" }, ` · ${k.ozet}`)),
            dinle(k.ses),
            el("div", { class: "kayit-islem" }, el("button", { type: "button", class: "dugme kucuk tehlike", disabled: kilit,
              onclick: () => isBaslat(`/efekt/${encodeURIComponent(k.ad)}`, {}, [`${k.ad} silinsin mi?`, "Efekt kaydı silinir; videodaysa efekt katmanı kaldırılır."], "DELETE") }, "🗑")))))
        : el("p", { class: "soluk" }, "Kayıtlı ses efekti yok: yukarıdaki düğmelerden biriyle hazırla."),
      aralikSatiri("Efekt seviyesi (%)", 0, 300, 10, P.efektSeviye, (v) => { P.efektSeviye = v; }, "100 = hazırlanan izin kendi seviyesi. Daha belirgin istersen %150–200 dene."),
      el("div", { class: "dugme-satiri" },
        el("button", { type: "button", class: "dugme birincil", disabled: kilit || !secili, onclick: () => isBaslat(`/efekt/${encodeURIComponent(secili)}/gom`, { seviye: P.efektSeviye }) }, "Seçili ses efektlerini videoya göm"),
        el("button", { type: "button", class: "dugme tehlike", disabled: kilit, onclick: () => isBaslat("/efekt/kaldir", {}, ["Ses efektleri kaldırılsın mı?", "Efekt katmanı videodan çıkarılır; kayıtlar silinmez."]) }, "Ses efektlerini kaldır"))),
    efektDuzenlemeKutusu(liste || []));
}
function efektDuzenlemeKutusu(liste) {
  const kutu = el("details", { class: "katlanir", open: !!P.efdKayit || null, dataset: { anahtar: "efd" } },
    ozet("✏️ Sesleri düzenle", "Solda sahnenin sesi, sağda arama: 🤖 Bul en uygun sesi önerir, 🔄 Tekrar oluştur sıradakini getirir, ✅ Onayla sesi değiştirir (boş sahneye ekler)."));
  const kilit = isSuruyor();
  ekle(kutu, 
    el("label", { class: "alan" }, el("span", { class: "alan-ad" }, "Efekt kaydı"),
      el("select", { onchange: (o) => { P.efdKayit = o.target.value; P.efd = null; P.oneriler = {}; efektDuzenlemeYukle(); } },
        el("option", { value: "" }, "— kayıt seç —"), liste.map(k => el("option", { value: k.ad, selected: k.ad === P.efdKayit || null }, k.ad)))));
  if (P.efdKayit && !P.efd) ekle(kutu, el("p", { class: "soluk" }, "Yükleniyor…"));
  if (P.efd) {
    if (P.efd.mesaj) ekle(kutu, kucukNot(P.efd.mesaj));
    for (const s of P.efd.sahneler) {
      for (const k of (s.katmanlar.length ? s.katmanlar : [null])) {
        const anahtar = `${s.index}:${k ? k.sira : 0}`, o = P.oneriler[anahtar] || { sorgu: "" };
        const aday = o.adaylar?.[o.i || 0];
        ekle(kutu, el("div", { class: "efd-satir" },
          el("div", { class: "efd-sol" }, el("b", {}, `Sahne ${s.index}`), el("span", { class: "soluk" }, ` · ${sayiBicim(s.bas)} sn${k ? ` · ${k.etiket || k.ad} (${k.tur})` : ""}`),
            k?.adres ? dinle(k.adres) : el("span", { class: "soluk" }, "— ses yok")),
          el("div", { class: "efd-sag" },
            el("div", { class: "dugme-satiri" },
              el("input", { value: o.sorgu, placeholder: k ? "yerine ne sesi olsun? ör. kumda yavaş ayak sesi" : "bu sahneye ne sesi eklensin? ör. uzakta rüzgâr",
                oninput: (e) => { P.oneriler[anahtar] = { ...o, sorgu: e.target.value }; },
                onkeydown: (e) => { if (e.key === "Enter") efektBul(anahtar, s, k); } }),
              el("button", { type: "button", class: "dugme kucuk", disabled: kilit || o.araniyor, onclick: () => efektBul(anahtar, s, k) }, o.araniyor ? "⏳" : "🤖 Bul")),
            o.mesaj ? kucukNot(o.mesaj) : null,
            aday ? [el("small", { class: "soluk" }, `${(o.i || 0) + 1}/${o.adaylar.length} · ${aday.ad} · ${sayiBicim(aday.sure)} sn`), dinle(aday.onizleme),
              el("div", { class: "dugme-satiri" },
                el("button", { type: "button", class: "dugme kucuk birincil", disabled: kilit, onclick: () => isBaslat(`/efekt/${encodeURIComponent(P.efdKayit)}/onayla`,
                  { index: s.index, sira: k ? k.sira : 0, aday, tur: k?.tur || "eylem", bas: k?.bas || 0, etiket: k?.etiket || "" }) }, "✅ Onayla"),
                o.adaylar.length > 1 ? el("button", { type: "button", class: "dugme kucuk", onclick: () => { o.i = ((o.i || 0) + 1) % o.adaylar.length; efektBolumunuCiz(); } }, "🔄 Tekrar oluştur") : null)] : null)));
      }
    }
  }
  return kutu;
}
async function efektBul(anahtar, s, k) {
  const o = P.oneriler[anahtar] || { sorgu: "" };
  P.oneriler[anahtar] = { ...o, araniyor: true }; efektBolumunuCiz();
  try {
    const r = await gonder(projeYolu("/efekt/bul"), { sorgu: o.sorgu, index: s.index, tur: k?.tur || "eylem" });
    P.oneriler[anahtar] = { sorgu: o.sorgu, adaylar: r.adaylar, i: 0, mesaj: r.mesaj };
  } catch (h) { P.oneriler[anahtar] = { sorgu: o.sorgu, mesaj: h.message }; }
  efektBolumunuCiz();
}
async function efektDuzenlemeYukle() {
  efektBolumunuCiz();
  if (!P.efdKayit) return;
  try { P.efd = await api(projeYolu(`/efekt/${encodeURIComponent(P.efdKayit)}/duzenle`)); } catch (h) { P.efd = { sahneler: [], mesaj: h.message }; }
  efektBolumunuCiz();
}
async function manuelAc() {
  try { P.manuel = (await api(projeYolu("/efekt-sahneleri"))).map(s => ({ ...s, istek: "" })); } catch (h) { alertKutusu(h.message); }
  efektBolumunuCiz();
}
async function efektleriYukle() {
  if (taslakMi()) return;
  try { P.efekt = await api(projeYolu("/efekt")); } catch { P.efekt = []; }
  efektBolumunuCiz();
}

/* ── Sonuç videosu ──────────────────────────────────────────────────────── */
function sonucBolumunuCiz() {
  const kap = $("#panel-sonuc"); if (!kap) return;
  if (taslakMi()) { kap.replaceChildren(aciklama("Sonuç videosu proje üretilince oluşur.")); return; }
  const s = P.sonuc, kilit = isSuruyor(), ses = P.ciktiModu === "ses";
  if (!s) { kap.replaceChildren(el("p", { class: "soluk" }, "Yükleniyor…")); return; }
  const seviye = Number(P.ayar?.degerler["ses.seviye"] ?? s.ses_seviye ?? 100);
  const katmanlar = ses ? s.ses_katmanlari : s.katmanlar;
  yerindeCiz(kap, 
    el("div", { class: "satir-ortali" }, el("div", { class: "secenek-grubu", role: "radiogroup", "aria-label": "Çıktı" },
      [["video", "🎬 Video"], ["ses", "♪ Ses"]].map(([v, e]) => el("button", { type: "button", class: `dugme kucuk${P.ciktiModu === v ? " secili" : ""}`,
        title: v === "ses" ? "Seslendirme/dublaj/müzik yalnızca youtube/<dil>/ses.mp3'e yazılır (YouTube çok dilli ses izleri); video değişmez" : "Katmanlar proje.mp4'e eklenir",
        onclick: () => { P.ciktiModu = v; sonucBolumunuCiz(); dublajBolumunuCiz(); muzikBolumunuCiz(); } }, e))),
      bilgiDugmesi("StudioFlow'un sonuç videosu (proje.mp4) ve katmanları; editörün kendi Dışa aktar'ından bağımsızdır, buradaki işlemler proje.mp4'ü StudioFlow'daki gibi değiştirir. Video: katmanlar proje.mp4'e eklenir. Ses: seslendirme, dublaj ve müzik yalnızca youtube/<dil>/ses.mp3'e yazılır (YouTube çok dilli ses izleri), video değişmez. Dublaj ve müzik Dublaj/Müzik, altyazı Altyazı, efekt Efekt bölümünden eklenir; hepsi bu seçime uyar.")),
    el("div", { class: "katman-rozetleri" }, katmanlar?.length
      ? katmanlar.map(k => el("span", { class: `cip${k.var ? " var" : ""}` }, `${k.var ? "✓" : "–"} ${k.ad}`))
      : el("span", { class: "cip" }, ses ? "Ses dosyası henüz yok" : "Video henüz üretilmedi")),
    ses ? (s.ses ? dinle(s.ses) : el("p", { class: "soluk" }, "Henüz ses dosyası yok: önce seslendirmeyi ya da bir dublajı ekle."))
      : (s.video ? el("video", { src: s.video, controls: true, preload: "metadata", class: "sonuc-video" }) : el("p", { class: "soluk" }, "proje.mp4 henüz yok.")),
    aralikSatiri("Seslendirme ses seviyesi (%)", 25, 400, 5, seviye, (v) => alanDegisti("ses.seviye", v, false), "100 = sesin kendi seviyesi. Kısık geliyorsa 150–200 dene; ses eklenirken uygulanır."),
    el("div", { class: "dugme-satiri" },
      el("button", { type: "button", class: "dugme birincil", disabled: kilit, onclick: async () => { await ayarlariKaydetSimdi(); isBaslat("/sonuc/ses", { seviye: Number(P.ayar?.degerler["ses.seviye"] ?? 100), mod: P.ciktiModu }); } },
        ses ? "Seslendirmeyi ekle" : "Sesi videoya ekle"),
      ses ? null : el("button", { type: "button", class: "dugme", disabled: kilit, onclick: () => isBaslat("/sonuc/altyazi", {}) }, "Altyazıyı videoya ekle"),
      el("button", { type: "button", class: "dugme tehlike", disabled: kilit, onclick: () => isBaslat("/sonuc/geri", { mod: P.ciktiModu },
        ses ? ["Ses sıfırlansın mı?", "Ses modundaki dosya sıfırlanır."] : ["Ham videoya geri dönülsün mü?", "Video eklenmiş ses, altyazı, müzik ve efektten arındırılıp ilk hâline döner."]) },
        ses ? "↺ Sesi sıfırla" : "↺ Ham videoya geri dön")),
    el("div", { class: "dugme-satiri" },
      ses ? (s.ses ? el("a", { class: "dugme", href: s.ses, download: true }, "⬇ Sesi indir") : null)
        : [s.video ? el("a", { class: "dugme", href: s.video, download: true }, "⬇ Videoyu indir") : null,
           s.video ? el("button", { type: "button", class: "dugme", onclick: async () => {
             try { const r = await gonder(projeYolu("/sonuc/mp3"), {}); P.mp3 = r.adres; sonucBolumunuCiz(); } catch (h) { alertKutusu(h.message); } } }, "♪ Videonun sesini MP3 yap") : null,
           P.mp3 ? el("a", { class: "dugme birincil", href: P.mp3, download: true }, "⬇ MP3'ü indir") : null]),
  );
}
async function sonucuYukle() {
  if (taslakMi()) return;
  try { P.sonuc = await api(projeYolu("/sonuc")); } catch { P.sonuc = null; }
  sonucBolumunuCiz();
}

/* ── Bölümler arası ─────────────────────────────────────────────────────── */
const BOLUM_YUKLE = { karakterler: karakterleriAc, dublaj: dublajlariYukle, muzik: muzikleriYukle, altyazi: altyazilariYukle, efekt: efektleriYukle, sonuc: sonucuYukle };
const BOLUM_CIZ = { metin: metinBolumunuCiz, karakterler: karakterlerBolumunuCiz, seslendirme: seslendirmeBolumunuCiz, altyazi: altyaziBolumunuCiz, ayarlar: ayarlarBolumunuCiz,
                    dublaj: dublajBolumunuCiz, muzik: muzikBolumunuCiz, efekt: efektBolumunuCiz, sonuc: sonucBolumunuCiz };

function bolumAcildi(ad) { (BOLUM_YUKLE[ad] || BOLUM_CIZ[ad] || (() => {}))(); }
/* İş başlayınca/bitince düğmeler kilitlenir/açılır: açık bölüm yeniden çizilir. */
function bolumleriCiz() {
  for (const [ad, ciz] of Object.entries(BOLUM_CIZ)) if (panelAcikMi(ad)) {
    // Metin alanına yazılırken bölüm yeniden çizilmez (imleç kaybolmasın).
    if (document.activeElement && $(`.panel-bolum[data-panel="${ad}"]`)?.contains(document.activeElement)
        && /TEXTAREA|INPUT/.test(document.activeElement.tagName) && document.activeElement.type !== "range") continue;
    ciz();
  }
}
/* Projedeki yeni bölüm verisi sıfırlanır (başka proje açılınca eski proje görünmesin). */
function bolumleriSifirla() {
  Object.assign(P, { ayar: null, bekleyen: {}, belgeler: null, belgeNotu: "", planRaporu: "", testSesi: null, testMesaji: "",
    kadro: null, kart: { ad: "", tarif: "", gorsel: "", adres: null }, kadroNotu: "", dublaj: null, dublajForm: null,
    muzik: null, muzikDosya: null, altyazilar: null, efekt: null, manuel: null, efdKayit: "", efd: null, oneriler: {},
    sonuc: null, mp3: null });
  clearTimeout(P.kayitZamanlayici);
}
/* Bir iş bitti: sonucunu al, açık bölümleri ve proje modelini tazele. */
const URETIM_ISLERI = ["devam", "prompt", "onay", "yeni", "sahne_prompt", "kare", "klip", "plan"];
async function isBitti(u) {
  if (!u || !durum.proje || u.ad !== durum.proje.ad) return;
  // Katman işinin sonucu (başarılı ya da değil) kapatılana dek üst çubukta kalır.
  if (!URETIM_ISLERI.includes(u.tur) && u.mesaj) alertKutusu(`${u.baslik}: ${u.mesaj}`);
  disaAyariniTazele();
  if (u.tur === "muzik_yz" && u.sonuc) {
    P.muzikDosya = u.sonuc; P.muzikForm.isim = u.sonuc.ad || P.muzikForm.isim;
    P.muzikForm.bas = 0; P.muzikForm.bit = Math.round((u.sonuc.sure || 0) * 2) / 2;
  }
  if (u.tur === "plan" && u.sonuc) P.planRaporu = u.sonuc.rapor;
  if (u.tur === "efekt_onay") { P.oneriler = {}; P.efd = null; efektDuzenlemeYukle(); }
  await ayarlariYukle(false);
  const onbellek = { karakterler: "kadro", dublaj: "dublaj", muzik: "muzik", altyazi: "altyazilar", efekt: "efekt", sonuc: "sonuc" };
  for (const [ad, yukle] of Object.entries(BOLUM_YUKLE)) {
    if (panelAcikMi(ad)) yukle(); else P[onbellek[ad]] = null;   // kapalı bölüm açılınca yeniden okunur
  }
  P.kadro = null;
  bolumleriCiz();
}
