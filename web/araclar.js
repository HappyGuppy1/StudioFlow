/* StudioFlow Editör · Araçlar ve API hesapları.
 *
 * StudioFlow'un araç sayfaları sunucuda (Gradio köprüsü, `sunucu/kopru.py`) kurulur; burada
 * gelen bileşen ağacı editörün tasarımıyla çizilir. Bir düğmeye basılınca ya da alan
 * değişince olay sunucuya gider, StudioFlow'un o olaya bağlı işlevi çalışır ve bileşen
 * güncellemeleri (yamalar) yoklanarak uygulanır. Değerlerin tek kaynağı sunucudur:
 * yazılan ama henüz gönderilmemiş değerler bir sonraki olayla birlikte gider.
 */
"use strict";

const A = { liste: null, arac: null, dugum: {}, el: {}, kirli: {}, olaylar: new Set(), dugmeIsi: {}, aktifIsler: 0, render: {} };
const ARAC_GRUPLARI = [
  ["Hazırlık", ["prompt-tool"]],
  ["Görüntü", ["image-tool", "character-tool", "video-tool", "map-tool", "upscale-tool"]],
  ["Ses", ["voice-tool", "music-tool", "sfx-tool", "transcribe-tool"]],
];

/* ── Ekran ──────────────────────────────────────────────────────────────── */
async function araclariAc(anahtar) {
  $("#kutuphane").hidden = true; $("#editor").hidden = true; $("#araclar").hidden = false;
  durakla?.();
  document.title = "Araçlar · StudioFlow";
  ustSekmeleriIsaretle(anahtar === "api-hesaplari" ? "api" : "araclar");
  if (!A.liste) {
    $("#arac-alani").replaceChildren(el("div", { class: "arac-bekle" }, el("span", { class: "donen" }), "StudioFlow araçları hazırlanıyor…"));
    try { A.liste = await api("/api/araclar"); }
    catch (hata) { $("#arac-alani").replaceChildren(el("p", { class: "hata-metin" }, `Araçlar yüklenemedi: ${hata.message}`)); return; }
  }
  const hedef = anahtar && A.liste.some(x => x.id === anahtar) ? anahtar : (A.arac?.id && A.arac.id !== "api-hesaplari" ? A.arac.id : "image-tool");
  aracListesiniCiz(hedef);
  if (A.arac?.id !== hedef) await aracYukle(hedef);
}
function ustSekmeleriIsaretle(ad) {
  $$(".ust-sekme").forEach(a => a.classList.toggle("secili", a.dataset.sekme === ad));
}
function aracListesiniCiz(secili) {
  const kap = $("#arac-listesi"), adres = (x) => "#" + (x.id === "api-hesaplari" ? "api-hesaplari" : `araclar/${x.id}`);
  const oge = (x) => el("a", { class: `arac-oge${x.id === secili ? " secili" : ""}`, href: adres(x) },
    el("span", { class: "arac-simge", "aria-hidden": "true" }, x.simge), el("span", {}, x.ad));
  const kullanilan = new Set(ARAC_GRUPLARI.flatMap(([, l]) => l));
  const gruplar = ARAC_GRUPLARI.map(([ad, l]) => [ad, l.map(id => A.liste.find(x => x.id === id)).filter(Boolean)]);
  const kalan = A.liste.filter(x => !kullanilan.has(x.id) && x.id !== "api-hesaplari");
  if (kalan.length) gruplar.push(["Diğer", kalan]);
  const hesap = A.liste.find(x => x.id === "api-hesaplari");
  kap.replaceChildren(...gruplar.filter(([, l]) => l.length).map(([ad, l]) => el("div", { class: "arac-grup" },
    el("div", { class: "arac-grup-ad" }, ad), ...l.map(oge))),
    hesap ? el("div", { class: "arac-grup" }, el("div", { class: "arac-grup-ad" }, "Bağlantılar"), oge(hesap)) : null);
}
async function aracYukle(anahtar) {
  const alan = $("#arac-alani");
  alan.replaceChildren(el("div", { class: "arac-bekle" }, el("span", { class: "donen" }), "Yükleniyor…"));
  let v;
  try { v = await api(`/api/arac/${encodeURIComponent(anahtar)}`); }
  catch (hata) { alan.replaceChildren(el("p", { class: "hata-metin" }, hata.message)); return; }
  Object.assign(A, { arac: v, dugum: {}, el: {}, kirli: {}, olaylar: new Set(v.olaylar), dugmeIsi: {}, render: {} });
  for (const r of v.render || []) A.render[r.girdi] = r;
  dizinle(v.agac);
  alan.replaceChildren(el("div", { class: "arac-sayfa" }, dugumCiz(v.agac, true)));
  alan.scrollTop = 0;
  if (v.is) isiIzleArac(v.is);
}
function dizinle(d) { if (!d) return; A.dugum[d.id] = d; (d.cocuklar || []).forEach(dizinle); }

/* ── Markdown (StudioFlow'un açıklama ve durum metinleri) ───────────────── */
function mdSatir(m) {
  return m.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(metin) {
  const kacis = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const satirlar = kacis(String(metin || "")).split(/\r?\n/);
  const cikti = []; let liste = null, tablo = null, paragraf = [];
  const paragrafiBitir = () => { if (paragraf.length) { cikti.push(`<p>${paragraf.join("<br>")}</p>`); paragraf = []; } };
  const listeyiBitir = () => { if (liste) { cikti.push(`<${liste.tur}>${liste.ogeler.map(x => `<li>${x}</li>`).join("")}</${liste.tur}>`); liste = null; } };
  const tabloyuBitir = () => {
    if (!tablo) return;
    const [ust, ...govde] = tablo.filter(s => !/^\|?\s*:?-{2,}/.test(s));
    const hucre = (s) => s.replace(/^\||\|$/g, "").split("|").map(x => mdSatir(x.trim()));
    cikti.push(`<table><thead><tr>${hucre(ust).map(x => `<th>${x}</th>`).join("")}</tr></thead><tbody>${govde.map(s => `<tr>${hucre(s).map(x => `<td>${x}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
    tablo = null;
  };
  for (const ham of satirlar) {
    const s = ham.replace(/\s+$/, "");
    if (/^\s*\|.*\|\s*$/.test(s)) { paragrafiBitir(); listeyiBitir(); (tablo ||= []).push(s.trim()); continue; }
    tabloyuBitir();
    const baslik = s.match(/^(#{1,4})\s+(.*)$/);
    const madde = s.match(/^\s*[-*•]\s+(.*)$/), sirali = s.match(/^\s*\d+[.)]\s+(.*)$/);
    if (baslik) { paragrafiBitir(); listeyiBitir(); const n = Math.min(baslik[1].length + 2, 6); cikti.push(`<h${n}>${mdSatir(baslik[2])}</h${n}>`); }
    else if (madde || sirali) {
      paragrafiBitir();
      const tur = madde ? "ul" : "ol";
      if (liste && liste.tur !== tur) listeyiBitir();
      (liste ||= { tur, ogeler: [] }).ogeler.push(mdSatir((madde || sirali)[1]));
    } else if (!s.trim()) { paragrafiBitir(); listeyiBitir(); }
    else { listeyiBitir(); paragraf.push(mdSatir(s.trim())); }
  }
  paragrafiBitir(); listeyiBitir(); tabloyuBitir();
  return cikti.join("");
}

/* ── Bileşen çizimi ─────────────────────────────────────────────────────── */
const secenekler = (c) => (c || []).map(x => Array.isArray(x) ? [String(x[0]), x[1]] : [String(x), x]);
const olayVar = (id, ad) => A.olaylar.has(`${id}:${ad}`);

function etiketli(d, girdi, satirIci = false) {
  const p = d.props;
  const ad = p.show_label === false || !p.label ? null : el("span", { class: "alan-ad" }, p.label, bilgiDugmesi(p.info));
  if (satirIci) return el("label", { class: "alan satir-alan" }, girdi, el("span", {}, p.label || ""), bilgiDugmesi(p.info));
  return el("div", { class: "alan" }, ad, girdi, !ad && p.info ? kucukNot(p.info) : null);
}

function dugumCiz(d, kok = false) {
  if (!d) return null;
  const p = d.props || {};
  let e;
  switch (d.tur) {
    case "Tab": e = el("div", { class: "k-sekme-icerik" }, ...(d.cocuklar || []).map(c => dugumCiz(c))); break;
    case "Tabs": e = sekmeleriCiz(d); break;
    case "Row": e = el("div", { class: "k-satir" }, ...(d.cocuklar || []).map(c => dugumCiz(c))); break;
    case "Column": e = el("div", { class: `k-sutun ${(p.elem_classes || []).includes("sf-tool-card") ? "k-kart" : ""}` }, ...(d.cocuklar || []).map(c => dugumCiz(c))); break;
    case "Group": e = el("div", { class: `k-grup ${(p.elem_classes || []).join(" ")}` }, ...(d.cocuklar || []).map(c => dugumCiz(c))); break;
    case "Accordion": {
      const yardim = (p.elem_classes || []).includes("sf-help");
      e = el("details", { class: `katlanir k-akordeon${yardim ? " k-yardim" : ""}`, open: p.open || null },
        el("summary", {}, yardim ? `ⓘ ${p.label}` : p.label), ...(d.cocuklar || []).map(c => dugumCiz(c)));
      break;
    }
    case "Markdown": e = el("div", { class: "k-md" }); e.innerHTML = md(p.value); break;
    case "HTML": e = el("div", { class: "k-html" }); e.innerHTML = p.value || ""; break;
    case "Textbox": e = metinKutusu(d); break;
    case "Number": e = etiketli(d, el("input", { type: "number", value: p.value ?? "", step: p.step || "any", disabled: p.interactive === false,
      onchange: (o) => degistir(d, o.target.value === "" ? null : Number(o.target.value)) })); break;
    case "Dropdown": e = acilirListe(d); break;
    case "Radio": e = etiketli(d, el("div", { class: "secenek-grubu sarili", role: "radiogroup" },
      secenekler(p.choices).map(([e2, v]) => el("button", { type: "button", class: `dugme kucuk${String(v) === String(p.value) ? " secili" : ""}`,
        disabled: p.interactive === false, onclick: () => degistir(d, v) }, e2)))); break;
    case "Checkbox": e = etiketli(d, el("input", { type: "checkbox", checked: !!p.value, disabled: p.interactive === false, onchange: (o) => degistir(d, o.target.checked) }), true); break;
    case "CheckboxGroup": {
      const secili = new Set((p.value || []).map(String));
      e = etiketli(d, el("div", { class: "k-kutular" }, secenekler(p.choices).map(([e2, v]) => el("label", { class: "satir-alan" },
        el("input", { type: "checkbox", checked: secili.has(String(v)), onchange: (o) => {
          const yeni = secenekler(p.choices).map(([, x]) => x).filter(x => (String(x) === String(v) ? o.target.checked : secili.has(String(x))));
          degistir(d, yeni); } }), el("span", {}, e2)))));
      break;
    }
    case "Slider": {
      const cikti = el("output", {}, sayiBicim(p.value ?? p.minimum ?? 0));
      e = etiketli(d, el("div", { class: "aralik-satir" }, el("input", { type: "range", min: p.minimum ?? 0, max: p.maximum ?? 100, step: p.step ?? 1,
        value: p.value ?? p.minimum ?? 0, disabled: p.interactive === false,
        oninput: (o) => { cikti.textContent = sayiBicim(o.target.value); }, onchange: (o) => degistir(d, Number(o.target.value)) }), cikti));
      break;
    }
    case "ColorPicker": e = etiketli(d, el("input", { type: "color", value: p.value || "#ffffff", onchange: (o) => degistir(d, o.target.value) })); break;
    case "Button": e = dugmeCiz(d); break;
    case "DownloadButton": e = p.value?.adres ? el("a", { class: "dugme", href: p.value.adres, download: p.value.ad }, `⬇ ${p.label || p.value.ad}`) : null; break;
    case "File": e = dosyaAlani(d); break;
    case "Image": case "Audio": case "Video": e = medyaAlani(d); break;
    case "Gallery": e = galeriCiz(d); break;
    case "State": e = A.render[d.id] ? renderAlani(d) : null; break;
    default: e = null;
  }
  if (!e) { e = el("span", { hidden: true }); }
  if (p.visible === false) e.hidden = true;
  // Satır içindeki genişlik payı (Gradio'nun scale/min_width'i): scale 0 → içeriği kadar.
  if (!kok && p.scale != null) e.style.flex = p.scale === 0 ? "0 0 auto" : `${p.scale} 1 0`;
  if (!kok && p.min_width != null && p.scale !== 0) e.style.minWidth = `min(${p.min_width || 0}px, 100%)`;
  A.el[d.id] = e; e.dataset.kimlik = d.id;
  return e;
}

function sekmeleriCiz(d) {
  const sekmeler = (d.cocuklar || []).filter(c => c.tur === "Tab");
  let secili = sekmeler.findIndex(s => s.props.selected) ; if (secili < 0) secili = 0;
  const cubuk = el("div", { class: "k-sekme-cubugu", role: "tablist" });
  const paneller = sekmeler.map((s, i) => { const pnl = dugumCiz(s); pnl.hidden = i !== secili; return pnl; });
  sekmeler.forEach((s, i) => cubuk.append(el("button", { type: "button", role: "tab", class: `k-sekme${i === secili ? " secili" : ""}`,
    onclick: () => {
      [...cubuk.children].forEach((b, j) => b.classList.toggle("secili", j === i));
      paneller.forEach((pnl, j) => { pnl.hidden = j !== i; });
      if (olayVar(s.id, "select")) olayGonder(s.id, "select");
    } }, s.props.label || `Sekme ${i + 1}`)));
  return el("div", { class: "k-sekmeler" }, cubuk, ...paneller);
}

function metinKutusu(d) {
  const p = d.props, salt = p.interactive === false, cok = (p.lines || 1) > 1 || (p.max_lines || 1) > 1 && salt;
  let zamanlayici;
  const yaz = (deger) => {
    A.kirli[d.id] = deger; d.props.value = deger;
    if (olayVar(d.id, "change") || olayVar(d.id, "input")) {
      clearTimeout(zamanlayici); zamanlayici = setTimeout(() => olayGonder(d.id, olayVar(d.id, "input") ? "input" : "change"), 600);
    }
  };
  const girdi = cok
    ? el("textarea", { rows: Math.min(Math.max(p.lines || 2, salt ? Math.min(String(p.value || "").split("\n").length, p.max_lines || 12) : 2), 24),
        value: salt ? String(p.value ?? "").replace(/\*\*/g, "") : (p.value ?? ""), placeholder: p.placeholder || null, readonly: salt || null, class: salt ? "salt-okunur" : null, oninput: (o) => yaz(o.target.value) })
    : el("input", { type: p.sifre ? "password" : "text", value: p.value ?? "", placeholder: p.placeholder || null, readonly: salt || null,
        oninput: (o) => yaz(o.target.value), onkeydown: (o) => { if (o.key === "Enter" && olayVar(d.id, "submit")) olayGonder(d.id, "submit"); } });
  if (salt && p.value && /^(⏳|✅|❌|⚠)/m.test(String(p.value))) girdi.classList.add("durum-yazisi");
  return etiketli(d, girdi);
}

function acilirListe(d) {
  const p = d.props, liste = secenekler(p.choices);
  if (p.multiselect) {
    const secili = new Set((p.value || []).map(String));
    return etiketli(d, el("select", { multiple: true, size: Math.min(6, liste.length || 1), onchange: (o) => degistir(d, [...o.target.selectedOptions].map(x => liste[x.index][1])) },
      liste.map(([e2, v]) => el("option", { value: String(v), selected: secili.has(String(v)) || null }, e2))));
  }
  if (p.allow_custom_value) {
    const dl = `dl-${d.id}`;
    return etiketli(d, el("div", {}, el("input", { list: dl, value: p.value ?? "", disabled: p.interactive === false,
      onchange: (o) => degistir(d, (liste.find(([e2]) => e2 === o.target.value) || [null, o.target.value])[1]) }),
      el("datalist", { id: dl }, liste.map(([e2, v]) => el("option", { value: String(v) }, e2)))));
  }
  const deger = p.value;
  const ogeler = liste.some(([, v]) => String(v) === String(deger)) || deger === null || deger === undefined || deger === "" ? liste : [[String(deger), deger], ...liste];
  return etiketli(d, el("select", { disabled: p.interactive === false, onchange: (o) => degistir(d, ogeler[o.target.selectedIndex - (deger == null || deger === "" ? 1 : 0)]?.[1] ?? null) },
    deger == null || deger === "" ? el("option", { value: "", selected: true }, "— seç —") : null,
    ogeler.map(([e2, v]) => el("option", { value: String(v), selected: String(v) === String(deger) || null }, e2))));
}

function dugmeCiz(d) {
  const p = d.props, metin = String(p.value ?? p.label ?? "");
  const sinif = `dugme${p.variant === "primary" ? " birincil" : p.variant === "stop" ? " tehlike" : ""}${p.size === "sm" ? " kucuk" : ""}`;
  if (p.link) return el("a", { class: sinif, href: p.link, target: "_blank", rel: "noopener" }, metin);
  const suruyor = !!A.dugmeIsi[d.id];
  return el("button", { type: "button", class: sinif, disabled: p.interactive === false || suruyor,
    onclick: () => olayGonder(d.id, "click") }, suruyor ? `⏳ ${metin}` : metin);
}

function dosyaListesi(deger) {
  const liste = Array.isArray(deger) ? deger : deger ? [deger] : [];
  return liste.length ? el("div", { class: "k-dosyalar" }, liste.map(f => el("a", { class: "dosya-satiri", href: f.adres, download: f.ad, target: "_blank" },
    el("span", {}, `📄 ${f.ad}`), el("span", { class: "soluk" }, "indir")))) : null;
}
function yukleyici(d, kabul, coklu, sonra) {
  return el("label", { class: "dugme kucuk" }, coklu ? "📁 Dosyaları seç" : "📁 Dosya seç",
    el("input", { type: "file", hidden: true, multiple: coklu || null, accept: kabul || null, onchange: async (o) => {
      const dosyalar = [...o.target.files]; if (!dosyalar.length) return;
      const yollar = [];
      for (const f of dosyalar) {
        try { const r = await api(`/api/arac-yukle?dosya=${encodeURIComponent(f.name)}`, { method: "POST", body: f }); yollar.push(r.yol); }
        catch (h) { aracBildir(`Yüklenemedi: ${h.message}`, "hata"); }
      }
      if (yollar.length) sonra(coklu ? yollar : yollar[0]);
    } }));
}
function dosyaAlani(d) {
  const p = d.props, girdi = p.interactive === true;
  const coklu = p.file_count === "multiple" || p.file_count === "directory";
  return etiketli(d, el("div", { class: "k-dosya-alani" }, dosyaListesi(p.value) || (girdi ? null : el("span", { class: "soluk kucuk-yazi" }, "Henüz dosya yok")),
    girdi ? el("div", { class: "dugme-satiri" }, yukleyici(d, (p.file_types || []).join(","), coklu, (yol) => dosyaDegisti(d, yol)),
      p.value ? el("button", { type: "button", class: "dugme kucuk", onclick: () => dosyaDegisti(d, null) }, "Temizle") : null) : null));
}
/* Bileşen bir olayın girdisi mi (kullanıcının dosya bırakacağı alan)? Sunucu girdileri
   ayrıca bildirmez; yükleme kaynağı (sources) olan medya ve etkileşimli dosya alanı girdidir. */
function girdiMi(id) { return A.dugum[id]?.props?.interactive === true; }
function dosyaDegisti(d, yol) {
  d.props.value = yol ? (Array.isArray(yol) ? yol.map(y => ({ ad: y.split(/[\\/]/).pop(), adres: null })) : { ad: yol.split(/[\\/]/).pop(), adres: null }) : null;
  A.kirli[d.id] = yol;
  if (olayVar(d.id, "upload") && yol) olayGonder(d.id, "upload"); else if (olayVar(d.id, "change")) olayGonder(d.id, "change");
  else aracDegerleriniGonder();
  yenidenCiz(d.id);
}
function medyaAlani(d) {
  const p = d.props, deger = p.value, adres = deger?.adres;
  const kaynaklar = p.sources || [], girdi = p.interactive === true && (kaynaklar.includes("upload") || !p.sources);
  const kabul = { Image: "image/*", Audio: "audio/*", Video: "video/*" }[d.tur];
  let goster = null;
  if (adres) {
    if (d.tur === "Image") goster = el("a", { href: adres, target: "_blank" }, el("img", { src: adres, alt: p.label || "", class: "k-gorsel" }));
    if (d.tur === "Audio") goster = el("audio", { controls: true, src: adres, class: "dinle" });
    if (d.tur === "Video") goster = el("video", { controls: true, src: adres, class: "k-video", preload: "metadata" });
  }
  const yapistir = girdi && kaynaklar.includes("clipboard") ? el("button", { type: "button", class: "dugme kucuk", title: "Panodaki görseli yapıştır", onclick: async () => {
    try {
      const ogeler = await navigator.clipboard.read();
      for (const oge of ogeler) for (const tur of oge.types) if (tur.startsWith("image/")) {
        const blob = await oge.getType(tur);
        const r = await api(`/api/arac-yukle?dosya=pano.png`, { method: "POST", body: blob });
        return dosyaDegisti(d, r.yol);
      }
      aracBildir("Panoda görsel yok.", "uyari");
    } catch (h) { aracBildir(`Panodan okunamadı: ${h.message}`, "uyari"); }
  } }, "📋 Yapıştır") : null;
  return etiketli(d, el("div", { class: "k-medya" }, goster || el("div", { class: "k-medya-bos soluk" }, girdi ? "Dosya bırak ya da seç" : "Henüz yok"),
    girdi ? el("div", { class: "dugme-satiri" }, yukleyici(d, kabul, false, (yol) => dosyaDegisti(d, yol)), yapistir,
      adres ? el("button", { type: "button", class: "dugme kucuk", onclick: () => dosyaDegisti(d, null) }, "Temizle") : null) : null,
    !girdi && adres ? el("a", { class: "dugme kucuk", href: adres, download: deger.ad }, "⬇ İndir") : null));
}
function galeriCiz(d) {
  const ogeler = d.props.value || [];
  return etiketli(d, ogeler.length ? el("div", { class: "k-galeri", style: `--sutun:${d.props.columns || 2}` }, ogeler.map(g => el("figure", {},
    el("a", { href: g.adres, target: "_blank" }, el("img", { src: g.adres, alt: g.baslik || g.ad, loading: "lazy" })),
    el("figcaption", {}, el("span", {}, g.baslik || g.ad), el("a", { href: g.adres, download: g.ad, title: "İndir" }, "⬇")))))
    : el("div", { class: "k-medya-bos soluk" }, "Henüz görsel yok"));
}
/* Ses efekti aracının bulunan sesler listesi (StudioFlow'da `gr.render`). */
function renderAlani(d) {
  const kap = el("div", { class: "k-render" });
  const ciz = (adaylar) => {
    kap.replaceChildren(...(adaylar?.length ? adaylar.map(a => el("div", { class: "kayit" },
      el("div", { class: "kayit-sec" }, el("b", {}, a.ad || `#${a.id}`), el("span", { class: "soluk" }, ` · ${sayiBicim(a.sure || 0)} sn · CC0 · `),
        a.url ? el("a", { href: a.url, target: "_blank", rel: "noopener" }, "Freesound") : null, el("span", { class: "soluk" }, a.sahip ? ` (${a.sahip})` : "")),
      (a.etiketler || []).length ? el("small", { class: "soluk" }, a.etiketler.slice(0, 5).join(", ")) : null,
      a.onizleme ? el("audio", { controls: true, preload: "none", src: a.onizleme, class: "dinle" }) : null,
      el("div", { class: "kayit-islem" }, el("button", { type: "button", class: "dugme kucuk birincil", onclick: async () => {
        try { const r = await gonder("/api/arac-ef-indir", { aday: a }); if (r.is) isiIzleArac(r.is); } catch (h) { aracBildir(h.message, "hata"); }
      } }, "⬇ İndir"))))
      : [el("p", { class: "soluk" }, "Henüz ses yok: soldan isteğini yaz ve Ses bul'a bas.")]));
  };
  ciz(d.props.state || []);
  kap.ciz = ciz;
  return kap;
}

/* ── Olaylar ve yamalar ─────────────────────────────────────────────────── */
function degistir(d, deger) {
  d.props.value = deger; A.kirli[d.id] = deger;
  if (olayVar(d.id, "change") || olayVar(d.id, "input") || olayVar(d.id, "select")) {
    olayGonder(d.id, olayVar(d.id, "change") ? "change" : olayVar(d.id, "input") ? "input" : "select");
  } else aracDegerleriniGonder();
  if (["Radio", "Dropdown", "Checkbox", "CheckboxGroup"].includes(d.tur)) yenidenCiz(d.id);
}
let degerZamanlayici;
function aracDegerleriniGonder() {
  clearTimeout(degerZamanlayici);
  degerZamanlayici = setTimeout(async () => {
    const degerler = A.kirli; A.kirli = {};
    if (Object.keys(degerler).length) try { await gonder("/api/arac-deger", { degerler }); } catch { Object.assign(A.kirli, degerler); }
  }, 400);
}
async function olayGonder(id, olay) {
  const degerler = A.kirli; A.kirli = {};
  try {
    const r = await gonder("/api/arac-olay", { bilesen: id, olay, degerler });
    if (r.is) {
      if (olay === "click") { A.dugmeIsi[id] = r.is; yenidenCiz(id); }
      isiIzleArac(r.is, olay === "click" ? id : null);
    }
  } catch (h) { Object.assign(A.kirli, degerler); aracBildir(h.message, "hata"); }
}
async function isiIzleArac(no, dugme = null) {
  const arac = A.arac?.id;
  let son = 0, bekleme = 120, gosterilen = 0;
  A.aktifIsler++; aracDurumunuGoster();
  try {
    for (;;) {
      await new Promise(r => setTimeout(r, bekleme));
      if (A.arac?.id !== arac) break;
      let d;
      try { d = await api(`/api/arac-is/${no}?son=${son}`); } catch { bekleme = 1000; continue; }
      for (const y of d.yamalar) yamaUygula(y.id, y.props);
      son = d.son;
      for (const u of d.uyarilar.slice(gosterilen)) aracBildir(u.metin, u.tur === "uyari" ? "uyari" : "bilgi");
      gosterilen = d.uyarilar.length;
      if (d.durum !== "calisiyor") { if (d.hata) aracBildir(d.hata, "hata"); break; }
      bekleme = Math.min(bekleme + 80, 700);
    }
  } finally {
    A.aktifIsler--; aracDurumunuGoster();
    if (dugme != null && A.dugmeIsi[dugme] === no) { delete A.dugmeIsi[dugme]; yenidenCiz(dugme); }
  }
}
function yamaUygula(id, props) {
  const d = A.dugum[id];
  if (!d) return;
  if ("state" in props && A.render[id]) { d.props.state = props.state; A.el[id]?.ciz?.(props.state); return; }
  Object.assign(d.props, props);
  if (d.tur in { Row: 1, Column: 1, Group: 1, Tab: 1, Tabs: 1 }) {
    if ("visible" in props && A.el[id]) A.el[id].hidden = props.visible === false;
    return;
  }
  if (d.tur === "Accordion") {
    if (A.el[id]) { if ("visible" in props) A.el[id].hidden = props.visible === false; if ("open" in props) A.el[id].open = !!props.open; if ("label" in props) A.el[id].querySelector("summary").textContent = props.label; }
    return;
  }
  if ("value" in props) delete A.kirli[id];
  yenidenCiz(id);
}
function yenidenCiz(id) {
  const eski = A.el[id], d = A.dugum[id];
  if (!eski || !d || !eski.isConnected) return;
  // Kullanıcı yazarken alanın içeriği ezilmez; yalnızca görünürlük ve etiket güncellenir.
  if (eski.contains(document.activeElement) && /TEXTAREA|INPUT/.test(document.activeElement.tagName) && document.activeElement.type !== "range" && d.tur === "Textbox") {
    eski.hidden = d.props.visible === false; return;
  }
  const yeni = dugumCiz(d);
  eski.replaceWith(yeni);
}
function aracDurumunuGoster() {
  const k = $("#arac-durum"); if (!k) return;
  k.hidden = A.aktifIsler <= 0;
}
function aracBildir(metin, tur = "bilgi") {
  const kap = $("#arac-bildirimler"); if (!kap) return;
  const b = el("div", { class: `arac-bildirim ${tur}`, role: "status" }, el("span", {}, String(metin).replace(/\*\*/g, "")),
    el("button", { type: "button", class: "dugme hayalet kucuk", onclick: () => b.remove() }, "✕"));
  kap.append(b);
  setTimeout(() => b.remove(), tur === "hata" ? 15000 : 8000);
}
