/* StudioFlow Editör · ön yüz.
 *
 * Tek bir küresel zaman (`durum.t`, saniye) her şeyi yönetir: oynatıcı, oynatma çizgisi,
 * seçili sahne ve altyazı bu zamana göre çizilir. Oynarken saat tarayıcının saatidir;
 * her ses izi (seslendirme · dublaj · müzik · efekt) kendi <audio> öğesinde çalar ve bu
 * saate göre hizalanır.
 *
 * İz başına iki düğme:  göz → yalnızca ÖNİZLEME   ·   işaret → yalnızca DIŞA AKTARMA.
 * Kurgu (çıkarılan sahneler, aralık) ve ses (seviye, karartma, müzik sırası) dışa aktarma
 * ayarıdır (`disa-aktarim/ayar.json`). Üretim işleri (devam, onay, sahne yenileme…)
 * StudioFlow'un işlevlerini sunucuda çalıştırır ve kota harcar.
 */
"use strict";

const $ = (s, kok = document) => kok.querySelector(s);
const $$ = (s, kok = document) => [...kok.querySelectorAll(s)];
const el = (etiket, ozellik = {}, ...cocuk) => {
  const e = document.createElement(etiket);
  for (const [k, v] of Object.entries(ozellik)) {
    if (k === "class") e.className = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "value" || k === "disabled") e[k] = v;
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of cocuk.flat()) if (c !== null && c !== undefined && c !== false) e.append(c);
  return e;
};
const sureYaz = (sn, ondalik = true) => {
  sn = Math.max(0, sn || 0);
  const d = Math.floor(sn / 60), s = sn - d * 60;
  return `${d}:${ondalik ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0")}`;
};
const api = async (yol, secenek) => {
  const yanit = await fetch(yol, secenek);
  if (!yanit.ok) {
    let ayrinti = ""; try { ayrinti = (await yanit.json()).detail || ""; } catch { /* metin değil */ }
    throw new Error(ayrinti || `${yanit.status} ${yol}`);
  }
  return yanit.json();
};
const gonder = (yol, govde, yontem = "POST") => api(yol, { method: yontem,
  headers: { "Content-Type": "application/json" }, body: JSON.stringify(govde ?? {}) });
const yerelOku = (k, v) => { try { return localStorage.getItem(k) ?? v; } catch { return v; } };
const yerelYaz = (k, v) => { try { localStorage.setItem(k, v); } catch { /* gizli pencere */ } };
const projeYolu = (ek = "") => `/api/proje/${encodeURIComponent(durum.proje.ad)}${ek}`;

const IZLER = [
  { anahtar: "video", ad: "Video", sinif: "video" },
  { anahtar: "seslendirme", ad: "Seslendirme", ses: true },
  { anahtar: "dublaj", ad: "Dublaj", ses: true, secim: "dublaj" },
  { anahtar: "muzik", ad: "Müzik", ses: true },
  { anahtar: "altyazi", ad: "Altyazı", secim: "altyazi" },
  { anahtar: "efekt", ad: "Efekt", ses: true, secim: "efekt" },
];
const SES_IZLERI = IZLER.filter(i => i.ses).map(i => i.anahtar);

const durum = {
  proje: null, sahneler: [], t: 0, oynuyor: false, secili: null, sonKare: 0,
  pxSn: Number(yerelOku("sf-zoom", 12)),
  ayar: null, goz: {}, altyazi: [], sesler: {},
  isZamanlayici: null, sunucuEski: false,
  uretim: null, uretimVar: true, mod: "tekli", servisler: [], uretimZamanlayici: null,
  sonYenileme: 0,
};

/* ── Kütüphane ──────────────────────────────────────────────────────────── */
async function kutuphaneyiAc() {
  $("#editor").hidden = true; $("#araclar").hidden = true; $("#kutuphane").hidden = false;
  ustSekmeleriIsaretle("projeler");
  durakla(); document.title = "StudioFlow";
  clearInterval(durum.isZamanlayici);
  durum.proje = null;
  const izgara = $("#proje-izgara"); izgara.replaceChildren();
  $("#kutuphane-durum").textContent = "Projeler yükleniyor…";
  izgara.append(el("button", { class: "proje-kart yeni-kart", type: "button", role: "listitem",
    onclick: yeniProjeAc }, el("span", { class: "arti", "aria-hidden": "true" }, "+"),
    el("h3", {}, "Yeni proje"), el("p", { class: "ozet" }, "Ad ver; metni, prompt'ları ve ayarları doldur, sonra başlat")));
  try {
    const projeler = await api("/api/projeler");
    $("#kutuphane-durum").textContent = projeler.length ? "" : "Henüz proje yok: + Yeni proje ile başla.";
    for (const p of projeler) {
      const oran = p.sahne ? Math.round(100 * p.tamam / p.sahne) : 0;
      izgara.append(el("button", { class: `proje-kart${p.taslak ? " taslak-kart" : ""}`, type: "button", role: "listitem",
        onclick: () => { location.hash = "#" + encodeURIComponent(p.ad); } },
        el("div", { class: "kapak", style: p.kapak ? `background-image:url("${p.kapak}")` : null },
          p.taslak ? el("span", { class: "taslak-rozet" }, "Taslak · başlatılmadı") : null),
        el("h3", {}, p.ad),
        el("p", { class: "ozet" }, p.taslak ? `Taslak · ${p.tuval.genislik}×${p.tuval.yukseklik} · ${p.guncellendi || ""}`
          : `${p.sahne} sahne · ${p.tamam} tamam · ${sureYaz(p.sure, false)} · ${p.tuval.genislik}×${p.tuval.yukseklik}`),
        el("div", { class: "ilerleme", title: `%${oran} tamam` }, el("span", { style: `width:${oran}%` }))));
    }
  } catch (hata) {
    $("#kutuphane-durum").textContent = `Projeler okunamadı: ${hata.message}`;
  }
}

/* ── Yeni proje: StudioFlow'daki gibi önce ad, sonra taslakta içerik ve ayarlar ── */
function yeniProjeAc() {
  $("#yp-hata").hidden = true; $("#yp-ad").value = "";
  $("#yeni-proje").showModal(); $("#yp-ad").focus();
}
async function yeniProjeOlustur(olay) {
  olay.preventDefault();
  const hata = $("#yp-hata"), dugme = $("#yp-olustur");
  hata.hidden = true; dugme.disabled = true;
  try {
    const sonuc = await gonder("/api/yeni-proje", { ad: $("#yp-ad").value });
    $("#yeni-proje").close();
    location.hash = "#" + encodeURIComponent(sonuc.ad);
    setTimeout(() => panelSec("metin"), 400);
  } catch (e) { hata.textContent = e.message; hata.hidden = false; }
  finally { dugme.disabled = false; }
}

/* ── Proje aç ───────────────────────────────────────────────────────────── */
async function projeyiAc(ad, bekle = 0) {
  $("#kutuphane").hidden = true; $("#araclar").hidden = true; $("#editor").hidden = false;
  durakla(); bolumleriSifirla();
  let p, disa;
  try { p = await api(`/api/proje/${encodeURIComponent(ad)}`); }
  catch (hata) {
    // Yeni proje: klasörü akış kurar; birkaç saniye içinde hazır olur.
    if (bekle < 20 && durum.uretim?.ad === ad && durum.uretim.durum === "calisiyor") {
      $("#proje-adi").textContent = ad; bildir("Proje hazırlanıyor…");
      return setTimeout(() => projeyiAc(ad, bekle + 1), 1500);
    }
    bildir(`Proje açılamadı: ${hata.message}`); return kutuphaneyiAc();
  }
  if (p.taslak) disa = { is: null, ayar: { isaret: { video: true, seslendirme: true, dublaj: false, muzik: false, altyazi: false, efekt: false },
    dublaj: "", altyazi: "", efekt: "", muzik: [], seviye: { seslendirme: 100, dublaj: 100, muzik: 100, efekt: 100 },
    muzik_karartma: { giris: 0, cikis: 0 }, cikarilan: [], aralik: { bas: null, bit: null } } };
  else try { disa = await api(`/api/proje/${encodeURIComponent(ad)}/disa-aktar`); }
  catch {
    // Sunucu bu sürümden eskiyse (Baslat.bat yeniden açılmadıysa) dışa aktarma ucu yoktur.
    const k = p.izler, ilk = (l) => (l.find(x => x.ekli) || l[0])?.ad || "";
    disa = { eski: true, is: null, ayar: {
      isaret: { video: true, seslendirme: k.seslendirme.length > 0, dublaj: false, muzik: false, altyazi: false, efekt: false },
      dublaj: ilk(k.dublaj), altyazi: ilk(k.altyazi), efekt: ilk(k.efekt), muzik: k.muzik.map(m => m.ad),
      seviye: { seslendirme: 100, dublaj: 100, muzik: 100, efekt: 100 }, muzik_karartma: { giris: 0, cikis: 0 },
      cikarilan: [], aralik: { bas: null, bit: null } } };
  }
  durum.sunucuEski = !!disa.eski;
  durum.varsayilanHedef = disa.varsayilan_hedef || "";
  $("#disa-aktar").disabled = durum.sunucuEski || !!p.taslak;
  $("#disa-aktar").title = durum.sunucuEski
    ? "StudioFlow eski sürümle çalışıyor: uygulamayı kapatıp yeniden aç"
    : "İşaretli izlerden video oluştur: kayıt konumunu seç, ilerlemeyi pencerede izle";
  Object.assign(durum, { proje: p, sahneler: p.sahneler, t: 0, secili: null, altyazi: [], ayar: disa.ayar });
  let gozler = null; try { gozler = JSON.parse(yerelOku(`sf-goz:${p.ad}`, "null")); } catch { /* bozuk */ }
  durum.goz = Object.fromEntries(IZLER.map(i => [i.anahtar, gozler?.[i.anahtar] ?? !!disa.ayar.isaret[i.anahtar]]));
  document.title = `${p.ad} · StudioFlow`;
  projeBasliginiCiz();
  // Editör açılırken dışa aktarma sürüyorsa pencere kilitli hâlde yeniden açılır.
  if ($("#disa-pencere").open) { dp.kilitli = false; $("#disa-pencere").close(); }
  isDurumunuGoster(disa.is);
  if (disa.is?.durum === "calisiyor") { disaPenceresiniAc(disa.is); isiIzle(); }
  zamanCizelgesiniCiz(); sesleriKur(); await altyaziyiYukle();
  panelleriCiz(); bilgiyiCiz(); sesPaneliniCiz();
  await ayarlariYukle();
  await uretimDurumunuAl(); uretimPaneliniCiz();
  zamanaGit(0); sahneyiSec(p.sahneler[0]?.index ?? null, false);
  if (p.taslak) {
    $("#denetci-baslik").textContent = "Taslak"; $("#denetci-durum").className = "durum-cip"; $("#denetci-durum").textContent = "";
    $("#denetci-icerik").replaceChildren(el("p", { class: "soluk" }, "Proje henüz başlatılmadı. Metin bölümünde anlatımı yaz, Seslendirme · Altyazı · Ayarlar bölümlerinde seçimleri yap, sonra üstteki ▶ Projeye başlat'a bas."),
      el("button", { type: "button", class: "dugme genis-dugme", onclick: () => panelSec("metin") }, "📝 Metin bölümünü aç"));
  }
  const acik = $(".ray-oge.secili")?.dataset.panel; if (acik) bolumAcildi(acik);
}

function projeBasliginiCiz() {
  const p = durum.proje;
  $("#proje-adi").textContent = p.ad;
  $("#tuval-cip").textContent = `${p.tuval.genislik}×${p.tuval.yukseklik}`;
  $("#proje-durum-cip").textContent = p.durum_adi || p.durum || "";
  $("#baslat").hidden = !p.taslak;
  $("#disa-aktar").hidden = !!p.taslak;
  $("#editor").classList.toggle("taslak", !!p.taslak);
  $$(".ray-oge[data-proje]").forEach(b => b.classList.toggle("pasif", !!p.taslak));
  $("#proje-durum-cip").hidden = !(p.durum_adi || p.durum);
  $("#tuval").style.setProperty("--oran", `${p.tuval.genislik} / ${p.tuval.yukseklik}`);
  $("#tuval").style.setProperty("--oran-sayi", p.tuval.genislik / p.tuval.yukseklik);
  $("#durum-cipler").replaceChildren(...Object.entries(p.sayim).filter(([, n]) => n)
    .map(([d, n]) => el("span", { class: `durum-cip ${d}`, title: d }, `${n} ${d.toLocaleLowerCase("tr")}`)));
  const indir = $("#video-indir"); indir.hidden = !p.video; if (p.video) indir.href = p.video;
}

/* Üretim sürerken proje modeli (sahne durumları, kareler) tazelenir; seçim ve zaman korunur. */
async function projeyiTazele() {
  if (!durum.proje) return;
  try {
    const p = await api(projeYolu());
    // Taslak başlatıldı (klasör kuruldu): zaman çizelgesi ve izler yeni modelle baştan açılır.
    if (!!p.taslak !== !!durum.proje.taslak) return projeyiAc(p.ad);
    durum.proje = p; durum.sahneler = p.sahneler;
    projeBasliginiCiz(); panelleriCiz(); izleriYenile(); sesleriKur(); bilgiyiCiz(); uretimPaneliniCiz();
    const s = durum.sahneler.find(x => x.index === durum.secili);
    if (s) denetciyiDoldur(s);
    onizlemeyiGuncelle(true);
  } catch { /* geçici */ }
}

/* Dışa aktarma ayarı (iz işaretleri, seçili kayıtlar) sunucuda değişti: zaman çizelgesi tazelenir. */
async function disaAyariniTazele() {
  if (!durum.proje || durum.proje.taslak) return;
  try {
    const p = await api(projeYolu());
    durum.proje = p; durum.sahneler = p.sahneler;
    durum.ayar = (await api(projeYolu("/disa-aktar"))).ayar;
    for (const iz of ["dublaj", "muzik", "altyazi", "efekt"]) if (durum.ayar.isaret[iz]) durum.goz[iz] = true;
    izBasliklariniCiz(); izleriYenile(); sesleriKur(); sesPaneliniCiz(); await altyaziyiYukle();
  } catch { /* geçici */ }
}

function bildir(mesaj) { $("#zc-bilgi").textContent = mesaj; console.warn(mesaj); }

/* ── Dışa aktarma ayarları (işaret, seçim, ses, kurgu) ─────────────────── */
function gozuDegistir(iz) {
  durum.goz[iz] = !durum.goz[iz];
  yerelYaz(`sf-goz:${durum.proje.ad}`, JSON.stringify(durum.goz));
  izBasliklariniCiz(); izleriYenile(); sesleriHizala(true); onizlemeyiGuncelle(true);
}
async function ayariKaydet(degisiklik) {
  const yeni = { ...durum.ayar, ...degisiklik, isaret: { ...durum.ayar.isaret, ...(degisiklik.isaret || {}) } };
  if (durum.sunucuEski) {
    durum.ayar = yeni; bildir("StudioFlow eski sürümle çalışıyor: uygulamayı yeniden açınca ayarlar kaydedilir.");
  } else {
    // Yalnızca değişiklik gönderilir; sunucu kayıtlı ayarla birleştirir. Tamamını göndermek,
    // arka planda bir işin yaptığı değişikliği (ör. Videoya ekle → müzik) eski kopyayla
    // siliyordu (20.10.2026). Yanıt güncel ayarın tamamıdır.
    try { durum.ayar = await gonder(projeYolu("/disa-aktar/ayar"), degisiklik, "PUT"); }
    catch (hata) { bildir(`Ayar kaydedilemedi: ${hata.message}`); }
  }
  izBasliklariniCiz(); izleriYenile(); panelleriCiz(); sesSeviyesi();
}
async function secimiDegistir(iz, deger) {
  await ayariKaydet({ [iz]: deger });
  if (iz === "altyazi") await altyaziyiYukle();
  sesleriKur(); onizlemeyiGuncelle(true);
}
const cikarildiMi = (index) => (durum.ayar?.cikarilan || []).includes(index);
async function cikarmayiDegistir(index) {
  const liste = new Set(durum.ayar.cikarilan || []);
  liste.has(index) ? liste.delete(index) : liste.add(index);
  await ayariKaydet({ cikarilan: [...liste] });
  const s = durum.sahneler.find(x => x.index === index); if (s) denetciyiDoldur(s);
}
async function araligiKoy(uc) {
  const a = { ...(durum.ayar.aralik || { bas: null, bit: null }) };
  if (uc === "temizle") { a.bas = a.bit = null; }
  else a[uc] = Math.round(durum.t * 1000) / 1000;
  if (a.bas !== null && a.bit !== null && a.bit <= a.bas) { bildir("Bitiş, başlangıçtan sonra olmalı."); return; }
  await ayariKaydet({ aralik: a });
}

/* ── Sesler ─────────────────────────────────────────────────────────────── */
function sesParcalari(iz) {
  const k = durum.proje.izler, a = durum.ayar;
  const bul = (liste, ad) => liste.find(x => x.ad === ad) || null;
  const tek = (kayit) => kayit?.ses ? [{ adres: kayit.ses, bas: 0, sure: kayit.sure || durum.proje.sure, ad: kayit.ad }] : [];
  if (iz === "seslendirme") return tek(k.seslendirme[0]);
  if (iz === "dublaj") return tek(bul(k.dublaj, a.dublaj));
  if (iz === "efekt") return tek(bul(k.efekt, a.efekt));
  // Projeye eklenen müzik sabittir (ducking'i eklenirken uygulandı): önizleme de onu çalar.
  if (iz === "muzik" && durum.proje.muzik_sabit?.ses)
    return [{ adres: durum.proje.muzik_sabit.ses, bas: 0, sure: durum.proje.muzik_sabit.sure || durum.proje.sure, ad: "sabit müzik" }];
  if (iz === "muzik") {   // seçili müzikler sırayla; tekrarla açıksa video sonuna kadar baştan
    const liste = (a.muzik || []).map(ad => bul(k.muzik, ad)).filter(m => m?.ses && m.sure > 0);
    const tekrarla = !!durum.proje.muzik_tercih?.tekrarla, son = durum.proje.sure || 0;
    const parcalar = []; let bas = 0;
    while (liste.length && bas < son && parcalar.length < 500) {
      for (const m of liste) { if (bas >= son) break; parcalar.push({ adres: m.ses, bas, sure: m.sure, ad: m.ad }); bas += m.sure; }
      if (!tekrarla) break;
    }
    return parcalar;
  }
  return [];
}
function sesleriKur() {
  for (const iz of SES_IZLERI) {
    durum.sesler[iz]?.oge.pause();
    const oge = durum.sesler[iz]?.oge || new Audio();
    oge.preload = "auto";
    durum.sesler[iz] = { oge, parcalar: sesParcalari(iz), adres: durum.sesler[iz]?.adres || null };
  }
  sesSeviyesi(); sesleriHizala(true);
}
/* Önizleme düzeyi = ana düzey × iz seviyesi × (konuşmada) projenin konuşma seviyesi.
   21.10.2026: tarayıcının `volume`u %100'ü geçemediği için konuşma seviyesi (ör. %400)
   önizlemede hiç duyulmuyordu. Ses Web Audio kazancından geçer; konuşma izlerinde dışa
   aktarmadaki gibi bir sınırlayıcı (compressor) tepe noktalarını tutar. Web Audio
   kurulamazsa eski yol (`volume`, en fazla %100) kullanılır. */
const KONUSMA_IZLERI = ["seslendirme", "dublaj"];
let sesBaglami = null;
function sesBaglamiAl() {
  if (sesBaglami === null) {
    try { sesBaglami = new (window.AudioContext || window.webkitAudioContext)(); }
    catch { sesBaglami = false; }
  }
  return sesBaglami || null;
}
function sesYolu(iz, s) {
  if (s.kazanc !== undefined) return s.kazanc;
  const b = sesBaglamiAl();
  if (!b) return (s.kazanc = null);
  try {
    const kaynak = b.createMediaElementSource(s.oge);
    const kazanc = b.createGain();
    kaynak.connect(kazanc);
    if (KONUSMA_IZLERI.includes(iz)) {
      const sinir = b.createDynamicsCompressor();      // alimiter=limit=0.97 karşılığı
      sinir.threshold.value = -1; sinir.knee.value = 0; sinir.ratio.value = 20;
      sinir.attack.value = 0.002; sinir.release.value = 0.1;
      kazanc.connect(sinir); sinir.connect(b.destination);
      // Ducking ölçeri: müzik, o an **çalan** konuşmanın seviyesine göre kısılır.
      s.olcer = b.createAnalyser(); s.olcer.fftSize = 1024;
      kazanc.connect(s.olcer);
    } else {
      kazanc.connect(b.destination);
    }
    s.oge.volume = 1;
    return (s.kazanc = kazanc);
  } catch { return (s.kazanc = null); }
}
function konusmaSeviyesi() {
  const v = Number(typeof P !== "undefined" ? P.ayar?.degerler?.["ses.seviye"] : NaN);
  return Number.isFinite(v) && v > 0 ? v / 100 : 1;
}
function sesSeviyesi() {
  const ana = Number($("#ses-duzeyi").value);
  for (const iz of SES_IZLERI) {
    const s = durum.sesler[iz]; if (!s) continue;
    let duzey = ana * (durum.ayar?.seviye?.[iz] ?? 100) / 100;
    if (iz === "muzik") duzey *= muzikKarartmaCarpani() * duckingCarpani();
    if (KONUSMA_IZLERI.includes(iz)) duzey *= konusmaSeviyesi();
    const kazanc = sesYolu(iz, s);
    if (kazanc) kazanc.gain.value = Math.max(0, Math.min(8, duzey));
    else s.oge.volume = Math.max(0, Math.min(1, duzey));
  }
}
/* Ducking (önizleme): konuşma sürerken müzik ~6 dB kısılır (dışa aktarma StudioFlow'un
   sidechain sıkıştırıcısıyla aynı işi yapar).
   21.10.2026: konuşmanın ne zaman sürdüğü **seçili altyazı izinden** okunuyordu; İngilizce
   anlatım çalarken altyazı tr seçiliyse müzik Türkçe cümlelere göre kısılıyordu. Artık o an
   çalan konuşma sesinin kendisi ölçülür (eşik ve bırakma süresi dışa aktarmadakiyle aynı). */
const DUCKING_ESIK = 0.03, DUCKING_BIRAKMA_MS = 350;
function duckingCarpani() {
  if (!durum.proje?.muzik_tercih?.ducking) return 1;
  if (durum.proje?.muzik_sabit?.ses) return 1;   // sabit müzikte ducking dosyaya işlenmiş
  const izler = KONUSMA_IZLERI.map(iz => durum.sesler[iz]).filter(Boolean);
  if (izler.some(s => s.olcer)) {
    let rms = 0;
    for (const s of izler) {
      if (!s.olcer || s.oge.paused) continue;
      const v = s.tampon || (s.tampon = new Float32Array(s.olcer.fftSize));
      s.olcer.getFloatTimeDomainData(v);
      let t = 0; for (const x of v) t += x * x;
      rms = Math.max(rms, Math.sqrt(t / v.length));
    }
    const simdi = performance.now();
    if (rms > DUCKING_ESIK) durum.sonKonusma = simdi;
    return simdi - (durum.sonKonusma ?? -1e9) < DUCKING_BIRAKMA_MS ? 0.5 : 1;
  }
  // Web Audio yoksa: konuşma izi çalıyorsa kıs; altyazı yalnızca **çalan konuşmanın
  // diliyle aynıysa** cümle aralarını bulmak için kullanılır.
  const calan = KONUSMA_IZLERI.find(iz => durum.goz[iz] && (durum.sesler[iz]?.parcalar || []).some(p => durum.t >= p.bas && durum.t < p.bas + (p.sure || 1e9)));
  if (!calan) return 1;
  const dil = calan === "dublaj" ? durum.ayar?.dublaj : P.ayar?.degerler?.["ses.dil"];
  if (durum.altyazi.length && dil && durum.ayar?.altyazi === dil
      && !durum.altyazi.some(b => durum.t >= b.bas - 0.15 && durum.t < b.bit + 0.35)) return 1;
  return 0.5;
}
function muzikKarartmaCarpani() {
  const k = durum.ayar?.muzik_karartma || {}, parcalar = durum.sesler.muzik?.parcalar || [];
  if (!parcalar.length) return 1;
  const son = Math.min(durum.proje.sure, parcalar.at(-1).bas + (parcalar.at(-1).sure || durum.proje.sure));
  let c = 1;
  if (k.giris > 0 && durum.t < k.giris) c = Math.min(c, durum.t / k.giris);
  if (k.cikis > 0 && durum.t > son - k.cikis) c = Math.min(c, Math.max(0, (son - durum.t) / k.cikis));
  return c;
}
function sesleriHizala(zorla = false) {
  for (const iz of SES_IZLERI) {
    const s = durum.sesler[iz]; if (!s) continue;
    const parca = durum.goz[iz] ? s.parcalar.find(p => durum.t >= p.bas && durum.t < p.bas + (p.sure || 1e9)) : null;
    if (!parca) { if (!s.oge.paused) s.oge.pause(); continue; }
    if (s.adres !== parca.adres) { s.adres = parca.adres; s.oge.src = parca.adres; zorla = true; }
    const ic = durum.t - parca.bas;
    if (zorla || Math.abs(s.oge.currentTime - ic) > 0.3) {
      try { s.oge.currentTime = ic; } catch { /* meta veri henüz yok */ }
    }
    if (durum.oynuyor && s.oge.paused) s.oge.play().catch(() => {});
    if (!durum.oynuyor && !s.oge.paused) s.oge.pause();
  }
  if (durum.proje?.muzik_tercih?.ducking || (durum.ayar?.muzik_karartma && (durum.ayar.muzik_karartma.giris || durum.ayar.muzik_karartma.cikis))) sesSeviyesi();
}

async function altyaziyiYukle() {
  const ad = durum.ayar.altyazi;
  durum.altyazi = ad ? await api(projeYolu(`/altyazi/${encodeURIComponent(ad)}`)).catch(() => []) : [];
  izleriYenile(); onizlemeyiGuncelle();
}

/* ── Sol panel: sahneler, metin, bilgi ─────────────────────────────────── */
function panelleriCiz() {
  const suzgec = $("#sahne-suzgec").value;
  const uygun = (s) => !suzgec || (suzgec === "cikarilan" ? cikarildiMi(s.index) : s.durum === suzgec);
  $("#sahne-izgara").replaceChildren(...durum.sahneler.filter(uygun).map(s =>
    el("button", { class: `sahne-kart ${s.durum}${s.index === durum.secili ? " secili" : ""}${cikarildiMi(s.index) ? " cikarilan" : ""}`,
      type: "button", dataset: { sahne: s.index }, title: `Sahne ${s.index} · ${s.durum} · ${s.metin}`, onclick: () => sahneyiSec(s.index) },
      s.kare ? el("img", { src: s.kare, alt: "", loading: "lazy" }) : el("span", { class: "kare-yok" }),
      el("span", { class: "no" }, s.index),
      el("span", { class: "alt" }, el("span", {}, sureYaz(s.bas, false)), el("span", {}, `${s.sure.toFixed(1)} sn`)))));
  $("#metin-listesi").replaceChildren(...durum.sahneler.map(s =>
    el("li", { dataset: { sahne: s.index }, class: cikarildiMi(s.index) ? "cikarilan" : null, onclick: () => sahneyiSec(s.index) },
      el("span", { class: "zaman-etiket" }, `${s.index} · ${sureYaz(s.bas)}`), s.metin || "—")));
}
function bilgiyiCiz() {
  const p = durum.proje, satir = (a, b) => [el("dt", {}, a), el("dd", {}, b)];
  $("#proje-bilgi").replaceChildren(...[
    ["Süre", sureYaz(p.sure)], ["Tuval", `${p.tuval.ad}`], ["Sahne", `${p.sahneler.length}`],
    ["Durum", p.durum_adi || p.durum || "—"], ["Görsel onayı", p.gorsel_onay || "—"],
    ["Video servisi", p.video_servisi || "—"], ["StudioFlow videosu", p.video ? "var" : "henüz yok"],
    ["Dışa aktarılanlar", "projects/" + p.ad + "/disa-aktarim/"],
  ].flatMap(([a, b]) => satir(a, b)));
  $("#proje-sil").onclick = projeyiSil;
}
async function projeyiSil() {
  const ad = durum.proje.ad;
  if (!(await onayIste(`'${ad}' silinsin mi?`, "Proje çalışıyorsa ya da dışa aktarılıyorsa önce durdurulur. Proje klasörü; kareler, klipler, sesler, altyazılar ve dışa aktarılan videolar dahil kalıcı olarak silinir. Geri alınamaz."))) return;
  try {
    const sonuc = await api(projeYolu(), { method: "DELETE" });
    history.replaceState(null, "", location.pathname); await kutuphaneyiAc();
    $("#kutuphane-durum").textContent = sonuc.mesaj.replace(/\*\*/g, "");
  } catch (hata) { alertKutusu(`Silinemedi: ${hata.message}`); }
}

/* ── Ses paneli (v0.5): iz seviyeleri, müzik karartması ve sırası ─────── */
function sesPaneliniCiz() {
  const a = durum.ayar, k = durum.proje.izler, kap = $("#iz-listesi");
  const seviye = (iz, ad) => {
    const deger = a.seviye?.[iz] ?? 100;
    // Sürgü ve yazılabilir % kutusu birbirini günceller; yazılan değer 0–200'e sıkıştırılır.
    const uygula = (v) => { durum.ayar.seviye = { ...durum.ayar.seviye, [iz]: v }; sesSeviyesi(); };
    const surgu = el("input", { id: `seviye-${iz}`, type: "range", min: 0, max: 200, step: 5, value: deger,
      oninput: (o) => { kutu.value = o.target.value; uygula(Number(o.target.value)); },
      onchange: (o) => ayariKaydet({ seviye: { ...a.seviye, [iz]: Number(o.target.value) } }) });
    const kutu = el("input", { type: "number", min: 0, max: 200, step: 5, value: deger, class: "seviye-deger", title: `${ad} seviyesi (%)`,
      oninput: (o) => { const v = Number(o.target.value); if (o.target.value !== "" && Number.isFinite(v)) { const c = Math.min(200, Math.max(0, v)); surgu.value = c; uygula(c); } },
      onchange: (o) => {
        const v = Number(o.target.value);
        const son = o.target.value === "" || !Number.isFinite(v) ? Number(surgu.value) : Math.min(200, Math.max(0, v));
        o.target.value = son; surgu.value = son; uygula(son);
        ayariKaydet({ seviye: { ...a.seviye, [iz]: son } });
      },
      onkeydown: (o) => { if (o.key === "Enter") o.target.blur(); } });
    return el("div", { class: "seviye-satir" }, el("label", { for: `seviye-${iz}` }, ad), surgu,
      el("span", { class: "seviye-kutu" }, kutu, "%"));
  };
  const karartma = (uc, ad) => el("label", { class: "kucuk-alan" }, ad,
    el("input", { type: "number", min: 0, max: 10, step: 0.5, value: a.muzik_karartma?.[uc] ?? 0,
      onchange: (o) => ayariKaydet({ muzik_karartma: { ...a.muzik_karartma, [uc]: Number(o.target.value) } }) }), " sn");
  const sira = a.muzik || [];
  const muzikler = [...sira.map(ad => k.muzik.find(m => m.ad === ad)).filter(Boolean),
                    ...k.muzik.filter(m => !sira.includes(m.ad))];
  const tasi = (ad, yon) => { const l = [...sira]; const i = l.indexOf(ad), j = i + yon; if (i < 0 || j < 0 || j >= l.length) return; [l[i], l[j]] = [l[j], l[i]]; ayariKaydet({ muzik: l }).then(sesPaneliniCiz).then(sesleriKur); };
  const dahil = (ad, acik) => ayariKaydet({ muzik: acik ? [...sira, ad] : sira.filter(x => x !== ad) }).then(sesPaneliniCiz).then(sesleriKur);
  kap.replaceChildren(
    el("p", { class: "soluk aciklama" }, "Seviye ve karartma dışa aktarılan videoya uygulanır; önizlemede %100'e kadar duyulur. 👁 göz ve ☑ işaret zaman çizelgesinde iz başlarındadır."),
    el("div", { class: "iz-grup" }, el("h3", {}, "Seviye"),
      seviye("seslendirme", "Seslendirme"), seviye("dublaj", "Dublaj"), seviye("muzik", "Müzik"), seviye("efekt", "Efekt")),
    el("div", { class: "iz-grup" }, el("h3", {}, "Müzik"),
      k.muzik.length ? [
        el("div", { class: "karartma" }, karartma("giris", "Başta yükselme"), karartma("cikis", "Sonda kısılma")),
        el("ol", { class: "muzik-sirasi" }, muzikler.map(m => {
          const i = sira.indexOf(m.ad);
          return el("li", { class: i < 0 ? "disarida" : null },
            el("input", { type: "checkbox", checked: i >= 0, title: "Videoya girsin", onchange: (o) => dahil(m.ad, o.target.checked) }),
            el("span", { class: "muzik-ad" }, `${i >= 0 ? i + 1 + ". " : ""}${m.ad}`),
            el("span", { class: "soluk" }, sureYaz(m.sure, false)),
            el("button", { type: "button", class: "dugme ikon kucuk", title: "Öne al", disabled: i <= 0, onclick: () => tasi(m.ad, -1) }, "↑"),
            el("button", { type: "button", class: "dugme ikon kucuk", title: "Sona al", disabled: i < 0 || i >= sira.length - 1, onclick: () => tasi(m.ad, 1) }, "↓"));
        })),
      ] : el("p", { class: "soluk" }, "Kayıtlı müzik yok: Müzik bölümünde üret ya da yükle.")),
    el("div", { class: "iz-grup" }, el("h3", {}, "Kayıtlar"),
      ["seslendirme", "dublaj", "altyazi", "efekt"].map(iz => el("p", { class: "soluk" },
        `${IZLER.find(i => i.anahtar === iz).ad}: ${k[iz].map(x => x.ad + (x.ekli ? " (StudioFlow videosunda)" : "")).join(", ") || "yok"}`))));
}

/* ── Zaman çizelgesi ────────────────────────────────────────────────────── */
const genislik = () => Math.max(durum.proje.sure * durum.pxSn + 24, $("#zc-kaydirma").clientWidth);

function zamanCizelgesiniCiz() {
  $("#zoom").value = durum.pxSn;
  const izler = $("#izler"); izler.replaceChildren();
  for (const i of IZLER) izler.append(el("div", { class: `iz ${i.sinif || ""}`, dataset: { iz: i.anahtar } }));
  izBasliklariniCiz(); izleriYenile();
}
function izBasliklariniCiz() {
  if (!durum.ayar) return;
  const k = durum.proje.izler;
  const secenekler = { dublaj: k.dublaj, altyazi: k.altyazi, efekt: k.efekt };
  $("#zc-adlar").replaceChildren(...IZLER.map(i => {
    const acik = !!durum.goz[i.anahtar], isaretli = !!durum.ayar.isaret[i.anahtar];
    const liste = i.secim ? secenekler[i.secim] : null;
    return el("div", { class: `zc-ad ${i.sinif || ""}${acik ? "" : " gizli"}${isaretli ? "" : " disarida"}`, dataset: { iz: i.anahtar } },
      el("button", { class: `goz${acik ? "" : " kapali"}`, type: "button", "aria-pressed": String(acik),
        title: acik ? `${i.ad} önizlemede görünüyor · gizlemek için tıkla` : `${i.ad} önizlemede gizli · göstermek için tıkla`,
        onclick: () => gozuDegistir(i.anahtar) }, gozIkonu(acik)),
      el("input", { type: "checkbox", class: "isaret", checked: isaretli,
        title: isaretli ? `${i.ad} dışa aktarılan videoya girer · çıkarmak için işareti kaldır` : `${i.ad} dışa aktarılan videoya girmez · katmak için işaretle`,
        onchange: (o) => ayariKaydet({ isaret: { [i.anahtar]: o.target.checked } }) }),
      el("span", { class: "zc-ad-yazi" }, i.ad),
      liste && liste.length > 1 ? el("select", { class: "iz-secim", title: `${i.ad} kaydı`,
        onchange: (o) => secimiDegistir(i.secim, o.target.value) },
        liste.map(x => el("option", { value: x.ad, selected: x.ad === durum.ayar[i.secim] || null }, x.ad))) : null);
  }));
}
function gozIkonu(acik) {
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
  const yol = document.createElementNS(ns, "path");
  yol.setAttribute("d", acik
    ? "M12 5C6.5 5 2.7 9.2 1.5 12c1.2 2.8 5 7 10.5 7s9.3-4.2 10.5-7C21.3 9.2 17.5 5 12 5zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zm0-2.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"
    : "M2.3 3.7 3.7 2.3l18 18-1.4 1.4-3.2-3.2A11.6 11.6 0 0 1 12 19C6.5 19 2.7 14.8 1.5 12a13 13 0 0 1 3.8-4.9L2.3 3.7zM12 5c5.5 0 9.3 4.2 10.5 7a13.3 13.3 0 0 1-2.6 3.8l-3.4-3.4A4.5 4.5 0 0 0 11.6 7.5L8.9 4.8C9.9 4.6 10.9 5 12 5zm-4.4 5 6.4 6.4A4.5 4.5 0 0 1 7.6 10z");
  svg.append(yol); return svg;
}
function izleriYenile() {
  if (!durum.proje || !durum.ayar || !$(".iz[data-iz]")) return;
  const px = durum.pxSn, w = genislik(), k = durum.proje.izler;
  $("#zc-icerik").style.width = `${w}px`;
  const kap = (a) => $(`.iz[data-iz="${a}"]`);
  for (const i of IZLER) {
    kap(i.anahtar).classList.toggle("gizli", !durum.goz[i.anahtar]);
    kap(i.anahtar).classList.toggle("disarida", !durum.ayar.isaret[i.anahtar]);
  }
  kap("video").replaceChildren(...durum.sahneler.map(s => el("div", {
    class: `blok sahne ${s.durum}${s.index === durum.secili ? " secili" : ""}${cikarildiMi(s.index) ? " cikarilan" : ""}`,
    dataset: { sahne: s.index }, title: `Sahne ${s.index} · ${s.sure.toFixed(1)} sn · ${s.durum}${cikarildiMi(s.index) ? " · videodan çıkarıldı" : ""}\n${s.metin}`,
    style: `left:${s.bas * px}px;width:${Math.max(s.sure * px - 1, 2)}px;${s.kare && s.sure * px > 18 ? `background-image:url("${s.kare}")` : ""}`,
  }, s.sure * px > 26 ? el("span", { class: "blok-yazi" }, s.index) : null)));
  const sesIzi = (iz, sinif, bos) => {
    const parcalar = sesParcalari(iz);
    kap(iz).replaceChildren(...(parcalar.length ? parcalar.map(p => el("div", {
      class: `blok ${sinif}`, title: `${p.ad} · ${sureYaz(p.sure, false)} · seviye %${durum.ayar.seviye?.[iz] ?? 100}`,
      style: `left:${p.bas * px}px;width:${Math.max((p.sure || durum.proje.sure) * px - 1, 4)}px`,
    }, el("span", { class: "blok-yazi" }, `${p.ad}${(durum.ayar.seviye?.[iz] ?? 100) !== 100 ? ` · %${durum.ayar.seviye[iz]}` : ""}`))) : [el("span", { class: "iz-bos" }, bos)]));
  };
  sesIzi("seslendirme", "ses", "seslendirme yok");
  sesIzi("dublaj", "dublaj", k.dublaj.length ? "dublaj seçilmedi" : "dublaj yok");
  sesIzi("muzik", "muzik", k.muzik.length ? "müzik seçilmedi" : "müzik yok");
  sesIzi("efekt", "efekt", k.efekt.length ? "efekt seçilmedi" : "ses efekti yok");
  kap("altyazi").replaceChildren(...(durum.altyazi.length ? durum.altyazi.map(b => el("div", {
    class: "blok altyazi", title: `${sureYaz(b.bas)}–${sureYaz(b.bit)}\n${b.metin}`,
    style: `left:${b.bas * px}px;width:${Math.max((b.bit - b.bas) * px - 1, 2)}px`,
  }, (b.bit - b.bas) * px > 40 ? el("span", { class: "blok-yazi" }, b.metin) : null))
    : [el("span", { class: "iz-bos" }, k.altyazi.length ? "altyazı seçilmedi" : "altyazı yok")]));
  // Dışa aktarma aralığının dışı karartılır
  const a = durum.ayar.aralik || {};
  const sol = $("#aralik-sol"), sag = $("#aralik-sag");
  sol.hidden = a.bas == null; sag.hidden = a.bit == null;
  if (a.bas != null) { sol.style.left = "0"; sol.style.width = `${a.bas * px}px`; }
  if (a.bit != null) { sag.style.left = `${a.bit * px}px`; sag.style.width = `${Math.max(0, (durum.proje.sure - a.bit) * px)}px`; }
  cetveliCiz(); oynatmaCizgisiniKoy();
  const kesik = (durum.ayar.cikarilan || []).length, aralik = a.bas != null || a.bit != null;
  $("#zc-bilgi").textContent = `${durum.sahneler.length} sahne · ${sureYaz(durum.proje.sure, false)}`
    + (kesik ? ` · ${kesik} sahne çıkarıldı` : "") + (aralik ? ` · aralık ${sureYaz(a.bas ?? 0, false)}–${sureYaz(a.bit ?? durum.proje.sure, false)}` : "")
    + ` · ${px.toFixed(px < 10 ? 1 : 0)} px/sn`;
}
function cetveliCiz() {
  // Cetvel yalnızca görünen alan kadar çizilir ve kaydırdıkça yeniden çizilir: projenin
  // tam genişliğinde tek tuval yakınlaştırınca tarayıcının sınırını aşıp beyaz kalıyordu.
  const kay = $("#zc-kaydirma"), tuval = $("#cetvel"), oran = window.devicePixelRatio || 1;
  const w = Math.max(kay.clientWidth, 1), px = durum.pxSn, sol = kay.scrollLeft;
  if (tuval.width !== Math.round(w * oran)) { tuval.width = Math.round(w * oran); tuval.style.width = `${w}px`; }
  if (tuval.height !== Math.round(26 * oran)) { tuval.height = Math.round(26 * oran); tuval.style.height = "26px"; }
  const c = tuval.getContext("2d"); c.setTransform(oran, 0, 0, oran, 0, 0);
  const stil = getComputedStyle(document.documentElement);
  c.fillStyle = stil.getPropertyValue("--yuzey"); c.fillRect(0, 0, w, 26);
  const a = durum.ayar?.aralik || {};
  if (a.bas != null || a.bit != null) {   // aralık cetvelde vurgulanır
    c.fillStyle = stil.getPropertyValue("--vurgu-koyu");
    const x1 = (a.bas ?? 0) * px - sol, x2 = (a.bit ?? durum.proje.sure) * px - sol;
    c.fillRect(Math.max(0, x1), 22, Math.max(0, Math.min(w, x2) - Math.max(0, x1)), 4);
  }
  const adimlar = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const ana = adimlar.find(x => x * px >= 70) || 600, parca = ana >= 60 ? 6 : 5, ara = ana / parca;
  c.font = `11px ${stil.getPropertyValue("--mono")}`; c.textBaseline = "top";
  const ilk = Math.max(0, Math.floor(sol / px / ara) - 1), sonT = Math.min(durum.proje.sure, (sol + w) / px) + ara;
  for (let n = ilk; n * ara <= sonT; n++) {
    const t = n * ara, x = Math.round(t * px - sol) + .5, buyuk = n % parca === 0;
    c.strokeStyle = buyuk ? stil.getPropertyValue("--soluk") : stil.getPropertyValue("--cizgi");
    c.beginPath(); c.moveTo(x, buyuk ? 12 : 18); c.lineTo(x, 26); c.stroke();
    if (buyuk) { c.fillStyle = stil.getPropertyValue("--soluk"); c.fillText(sureYaz(t, false), x + 3, 2); }
  }
}
function oynatmaCizgisiniKoy() {
  const x = durum.t * durum.pxSn;
  $("#oynatma-cizgisi").style.left = `${x}px`;
  if (durum.oynuyor && $("#takip").checked) {
    const kay = $("#zc-kaydirma");
    const gorunur = x >= kay.scrollLeft + 40 && x <= kay.scrollLeft + kay.clientWidth - 80;
    // Elle kaydırınca takip durur, oynatma çizgisi görünür alana yeniden girince sürer;
    // böylece oynarken başka kareler incelenebilir (eskiden her karede geri çekiyordu).
    if (durum.elleKaydirdi) { if (gorunur) durum.elleKaydirdi = false; }
    else if (!gorunur) kay.scrollLeft = x - 120;
  }
}
function yakinlastir(px, odakT = durum.t) {
  const kay = $("#zc-kaydirma"), ekranX = odakT * durum.pxSn - kay.scrollLeft;
  durum.pxSn = Math.min(160, Math.max(0.5, Math.round(px * 100) / 100)); yerelYaz("sf-zoom", durum.pxSn);
  $("#zoom").value = durum.pxSn; izleriYenile();
  kay.scrollLeft = odakT * durum.pxSn - ekranX;
}
function sigdir() { yakinlastir(($("#zc-kaydirma").clientWidth - 30) / Math.max(durum.proje.sure, 1), 0); }

/* ── Seçim ve zaman ─────────────────────────────────────────────────────── */
const sahneBul = (t) => {
  const s = durum.sahneler;
  let alt = 0, ust = s.length - 1;
  while (alt <= ust) { const o = (alt + ust) >> 1; if (t < s[o].bas) ust = o - 1; else if (t >= s[o].bit) alt = o + 1; else return s[o]; }
  return s[Math.min(alt, s.length - 1)] || null;
};

function sahneyiSec(index, zamaniTasi = true) {
  const s = durum.sahneler.find(x => x.index === index);
  durum.secili = s ? s.index : null;
  $$(".sahne-kart.secili, .metin-listesi li.secili, .blok.sahne.secili").forEach(e => e.classList.remove("secili"));
  if (!s) return;
  $$(`[data-sahne="${s.index}"]`).forEach(e => e.classList.add("secili"));
  $(`.sahne-kart[data-sahne="${s.index}"]`)?.scrollIntoView({ block: "nearest" });
  $(`.metin-listesi li[data-sahne="${s.index}"]`)?.scrollIntoView({ block: "nearest" });
  if (zamaniTasi) zamanaGit(s.bas + 0.001);
  denetciyiDoldur(s);
}

/* ── Sağ panel (v0.3): sahne ayrıntısı ve düzenleme ────────────────────── */
async function denetciyiDoldur(s) {
  $("#denetci-baslik").textContent = `Sahne ${s.index}`;
  const cip = $("#denetci-durum"); cip.className = `durum-cip ${s.durum}`; cip.textContent = s.durum;
  const icerik = $("#denetci-icerik");
  let a;
  try { a = await api(projeYolu(`/sahne/${s.index}`)); }
  catch (hata) { icerik.replaceChildren(el("p", { class: "soluk" }, `Sahne okunamadı: ${hata.message}`)); return; }
  if (durum.secili !== s.index) return;   // bu arada başka sahne seçildi
  const meşgul = !!(durum.uretim && durum.uretim.durum === "calisiyor");
  durum.denetciKilitli = meşgul;
  const alan = (baslik, metin, sinif = "") => metin ? el("div", {},
    el("div", { class: "alan-baslik" }, baslik, el("button", { type: "button", title: "Panoya kopyala",
      onclick: (o) => kopyala(metin, o.currentTarget) }, "kopyala")),
    el("p", { class: `alan-metin ${sinif}` }, metin)) : null;
  const islemler = durum.uretimVar && !durum.sunucuEski ? el("div", { class: "denetci-islemler" },
    el("div", { class: "alan-baslik" }, el("span", {}, "Görsel prompt'u", bilgiDugmesi("Model prompt'un ilk ~55 kelimesini okur: en önemli öğeyi başa yaz. Kaydet ve kareyi yeniden üret yalnızca bu sahnenin karesini ve klibini siler, yeni prompt'la kare üretir; görsel onayı yeniden sorulur."))),
    el("textarea", { id: "ins-prompt", rows: 6, value: a.gorsel_prompt, disabled: meşgul }),
    el("div", { class: "alan-baslik" }, "Negatif prompt"),
    el("textarea", { id: "ins-negatif", rows: 2, value: a.negatif_prompt, disabled: meşgul }),
    el("div", { class: "dugme-satiri" },
      el("button", { type: "button", class: "dugme birincil", disabled: meşgul,
        title: "Prompt'u kaydet ve yalnızca bu sahnenin karesini yeniden üret (görsel kotası harcar)",
        onclick: () => sahneIslemi(a.index, "prompt", { gorsel: $("#ins-prompt").value, negatif: $("#ins-negatif").value },
          "Prompt kaydedilip kare yeniden üretilsin mi?", "Bu sahnenin karesi ve klibi silinir, yeni prompt'la kare üretilir; görsel onayı yeniden sorulur.") },
        "Kaydet ve kareyi yeniden üret")),
    el("div", { class: "dugme-satiri" },
      el("button", { type: "button", class: "dugme", disabled: meşgul,
        onclick: () => sahneIslemi(a.index, "kare", {}, "Kare yenilensin mi?", "Kare (ve varsa klibi) silinir, aynı prompt'la yenisi üretilir; görsel onayı yeniden sorulur.") }, "🗑 Kareyi yenile"),
      el("button", { type: "button", class: "dugme", disabled: meşgul || !a.kare,
        onclick: () => sahneIslemi(a.index, "klip", {}, "Klip yeniden üretilsin mi?", "Yalnızca bu sahnenin klibi silinir, aynı kareden yenisi üretilir (video kotası harcar).") }, "↻ Klibi yeniden üret"))) : null;
  icerik.replaceChildren(...[
    // Kare/klip ortadaki önizlemede görünür; sağ panel yalnızca bilgi ve işlemleri taşır.
    a.kare ? null : el("p", { class: "soluk" }, "Bu sahnenin karesi henüz üretilmedi."),
    el("p", { class: "soluk" }, `${sureYaz(a.bas)} – ${sureYaz(a.bit)} · ${a.sure.toFixed(1)} sn${a.bitti ? ` · ${a.bitti}` : ""}`),
    alan("Anlatım", a.metin), alan("Hata", a.hata, "hata"),
    islemler || alan("Görsel prompt'u", a.gorsel_prompt), islemler ? null : alan("Negatif prompt", a.negatif_prompt),
    alan("Video prompt'u", a.video_prompt), alan("Kontrol listesi", a.kontrol), alan("Karakterler", a.karakterler),
  ].filter(Boolean));
}
async function kopyala(metin, dugme) {
  try { await navigator.clipboard.writeText(metin); dugme.textContent = "kopyalandı"; }
  catch { dugme.textContent = "kopyalanamadı"; }
  setTimeout(() => { dugme.textContent = "kopyala"; }, 1400);
}
function onayIste(baslik, metin) {
  return new Promise((coz) => {
    const p = $("#onay"); $("#onay-baslik").textContent = baslik; $("#onay-metin").textContent = metin;
    p.returnValue = ""; p.addEventListener("close", () => coz(p.returnValue === "evet"), { once: true });
    p.showModal();
  });
}
async function sahneIslemi(index, islem, govde, baslik, metin) {
  if (!(await onayIste(baslik, metin))) return;
  try { durum.uretim = await gonder(projeYolu(`/sahne/${index}/${islem}`), govde); uretimiIzle(); }
  catch (hata) { bildir(hata.message); alertKutusu(hata.message); }
}
/* Yerel dosyayı uygulamanın içinde göster (görsel · video · ses · metin/PDF). */
function dosyaGoster(adres, baslik) {
  const ad = decodeURIComponent(new URL(adres).pathname.split("/").pop() || "");
  const uzanti = (ad.match(/\.([a-z0-9]+)$/i)?.[1] || "").toLowerCase();
  const icerik = /^(png|jpe?g|webp|gif|bmp|svg)$/.test(uzanti) ? el("img", { src: adres, alt: ad })
    : /^(mp4|webm|mov|mkv|m4v)$/.test(uzanti) ? el("video", { src: adres, controls: true, autoplay: true })
    : /^(mp3|wav|ogg|m4a|flac|aac)$/.test(uzanti) ? el("audio", { src: adres, controls: true, autoplay: true })
    : el("iframe", { src: adres, title: ad });
  $("#gr-baslik").textContent = baslik && baslik.length < 80 ? baslik : ad;
  Object.assign($("#gr-indir"), { href: adres, download: ad });
  $("#gr-icerik").replaceChildren(icerik);
  $("#goruntuleyici").showModal();
}

function alertKutusu(mesaj) {
  $("#uretim-ozet").hidden = false; $("#uretim-ozet").classList.add("uyari");
  $("#uretim-ozet-mesaj").textContent = String(mesaj || "").replace(/\*\*/g, "");
  $("#uretim-ozet-durdur").hidden = true; $("#uretim-ozet-kapat").hidden = false;
}

function zamanaGit(t) {
  durum.t = Math.min(Math.max(0, t), durum.proje?.sure || 0);
  durum.elleKaydirdi = false;
  sesleriHizala(true); onizlemeyiGuncelle(true); oynatmaCizgisiniKoy();
  const s = sahneBul(durum.t);
  if (s && s.index !== durum.secili) sahneyiSec(s.index, false);
}

/* ── Önizleme ───────────────────────────────────────────────────────────── */
let gosterilenSahne = null;
function onizlemeyiGuncelle(zorla = false) {
  if (!durum.proje) return;
  const s = sahneBul(durum.t), video = $("#onizleme-video"), kare = $("#onizleme-kare");
  $("#zaman").textContent = `${sureYaz(durum.t)} / ${sureYaz(durum.proje.sure)}`;
  const videoAcik = durum.goz.video;
  $("#onizleme-bos").hidden = !!s && videoAcik;
  $("#onizleme-bos").textContent = s ? "Video izi gizli (👁)"
    : durum.proje.taslak ? "Taslak · proje başlatılınca sahneler burada oynar" : "Sahne yok";
  $("#onizleme-etiket").textContent = s ? `Sahne ${s.index} · ${s.durum}${cikarildiMi(s.index) ? " · çıkarıldı" : ""}` : "";
  if (!s || !videoAcik) {
    video.hidden = kare.hidden = true; video.pause(); gosterilenSahne = null;
  } else {
    const icT = durum.t - s.bas;
    if (s !== gosterilenSahne || zorla) {
      const yeni = s !== gosterilenSahne;
      gosterilenSahne = s;
      if (s.klip) {
        kare.hidden = true; video.hidden = false;
        if (yeni || !video.src.endsWith(s.klip)) { video.src = s.klip; video.poster = s.kare || ""; }
        const oturt = () => { video.currentTime = Math.min(icT, Math.max((video.duration || icT) - 0.05, 0)); if (durum.oynuyor) video.play().catch(() => {}); };
        if (video.readyState >= 1) oturt(); else video.addEventListener("loadedmetadata", oturt, { once: true });
      } else {
        video.hidden = true; video.removeAttribute("src"); video.load();
        kare.hidden = !s.kare; if (s.kare) kare.src = s.kare;
        kare.classList.toggle("kayan", durum.oynuyor);
      }
    } else if (s.klip && durum.oynuyor && Math.abs(video.currentTime - icT) > 0.4 && icT < (video.duration || 1e9)) {
      video.currentTime = icT;
    }
  }
  if (s && durum.oynuyor && s.index !== durum.secili) sahneyiSec(s.index, false);
  const blok = durum.goz.altyazi ? durum.altyazi.find(b => durum.t >= b.bas && durum.t < b.bit) : null;
  const yazi = $("#onizleme-altyazi"); yazi.hidden = !blok; if (blok) yazi.textContent = blok.metin;
}

/* ── Oynatma ────────────────────────────────────────────────────────────── */
function oynat() {
  if (!durum.proje) return;
  if (durum.t >= durum.proje.sure - 0.05) zamanaGit(0);
  durum.oynuyor = true; durum.elleKaydirdi = false; $("#oynat").textContent = "⏸";
  // Web Audio bağlamı kullanıcı etkileşimiyle başlar (tarayıcı kuralı).
  if (sesBaglami && sesBaglami.state === "suspended") sesBaglami.resume().catch(() => {});
  sesSeviyesi();
  durum.sonKare = performance.now();
  sesleriHizala(true); onizlemeyiGuncelle(true); requestAnimationFrame(tik);
}
function durakla() {
  durum.oynuyor = false; $("#oynat").textContent = "▶";
  for (const s of Object.values(durum.sesler)) s.oge.pause();
  $("#onizleme-video").pause();
  $("#onizleme-kare").classList.remove("kayan");
}
let sonHizalama = 0;
function tik(simdi) {
  if (!durum.oynuyor) return;
  durum.t += (simdi - durum.sonKare) / 1000;
  durum.sonKare = simdi;
  // Kesik önizleme: çıkarılan sahneye girilince sonuna atlanır (dışa aktarmadaki gibi).
  if ($("#kesik-onizleme").checked && (durum.ayar?.cikarilan || []).length) {
    let s = sahneBul(durum.t), atla = false;
    while (s && cikarildiMi(s.index) && durum.t < durum.proje.sure) { durum.t = s.bit + 0.001; s = sahneBul(durum.t); atla = true; }
    if (atla) sesleriHizala(true);
  }
  if (durum.t >= durum.proje.sure) { durum.t = durum.proje.sure; durakla(); }
  onizlemeyiGuncelle(); oynatmaCizgisiniKoy();
  if (simdi - sonHizalama > 250) { sonHizalama = simdi; sesleriHizala(); }
  requestAnimationFrame(tik);
}
function sahneAtla(yon) {
  const s = sahneBul(durum.t); if (!s) return;
  const i = durum.sahneler.indexOf(s) + yon;
  const hedef = durum.sahneler[Math.min(Math.max(i, 0), durum.sahneler.length - 1)];
  sahneyiSec(hedef.index);
}

/* ── Üretim (v0.4) ─────────────────────────────────────────────────────── */
async function uretimDurumunuAl() {
  try {
    const u = await api("/api/uretim");
    durum.uretimVar = true; durum.uretim = u.is; durum.mod = u.mod; durum.servisler = u.servisler;
  } catch { durum.uretimVar = false; }
  uretimOzetiniGoster();
}
function uretimOzetiniGoster() {
  const u = durum.uretim, kutu = $("#uretim-ozet");
  const ilgili = u && (!durum.proje || u.ad === durum.proje.ad);
  if (!kutu.hidden && kutu.classList.contains("uyari") && !(ilgili && u.durum === "calisiyor")) return;   // uyarı kapatılana dek kalır
  kutu.classList.remove("uyari"); $("#uretim-ozet-kapat").hidden = true;
  kutu.hidden = !(ilgili && u.durum === "calisiyor");
  $("#uretim-ozet-durdur").hidden = !["devam", "prompt", "onay", "yeni", "sahne_prompt", "kare", "klip"].includes(u?.tur);
  if (ilgili) $("#uretim-ozet-mesaj").textContent = `${u.baslik}: ${u.mesaj.split("\n")[0].slice(0, 90)}`;
}
function uretimiIzle() {
  clearInterval(durum.uretimZamanlayici);
  const tur = async () => {
    const onceki = durum.uretim?.durum;
    await uretimDurumunuAl(); uretimPaneliniCiz();
    const calisiyor = durum.uretim?.durum === "calisiyor";
    // İş başlayınca/bitince sağ paneldeki düzenleme düğmeleri kilitlenir/açılır.
    if (durum.denetciKilitli !== undefined && durum.denetciKilitli !== calisiyor && durum.secili != null) {
      const s = durum.sahneler.find(x => x.index === durum.secili); if (s) denetciyiDoldur(s);
    }
    if (onceki === "calisiyor" && !calisiyor) { await isBitti(durum.uretim); bolumleriCiz(); }
    else if (onceki !== durum.uretim?.durum) bolumleriCiz();
    // Üretim sürerken sahne durumları ve kareler 6 sn'de bir tazelenir; bitince bir kez daha.
    if (durum.proje && (calisiyor && performance.now() - durum.sonYenileme > 6000 || (onceki === "calisiyor" && !calisiyor))) {
      durum.sonYenileme = performance.now(); await projeyiTazele();
    }
    if (!calisiyor) clearInterval(durum.uretimZamanlayici);
  };
  tur(); durum.uretimZamanlayici = setInterval(tur, 2000);
}
async function uretimBaslat(islem, govde, baslik, metin) {
  if (baslik && !(await onayIste(baslik, metin))) return;
  try { durum.uretim = await gonder(projeYolu(`/uretim/${islem}`), govde); uretimiIzle(); }
  catch (hata) { alertKutusu(hata.message); }
}
async function uretimDurdur() {
  try { durum.uretim = (await gonder("/api/uretim/durdur", {})).is; uretimOzetiniGoster(); uretimPaneliniCiz(); } catch { /* izleme sürer */ }
}
function uretimPaneliniCiz() {
  const kap = $("#uretim-paneli"); if (!durum.proje) return;
  if (!durum.uretimVar || durum.sunucuEski) {
    kap.replaceChildren(el("p", { class: "soluk" }, "Üretim kontrolü için editör sunucusunu yeniden başlat (Baslat.bat)."));
    return;
  }
  const p = durum.proje, u = durum.uretim, buProje = u && u.ad === p.ad, calisiyor = u?.durum === "calisiyor";
  const baskaProje = calisiyor && !buProje;
  const mod = el("div", { class: "secenek-grubu", role: "radiogroup", "aria-label": "Üretim modu" },
    [["tekli", "Tekli"], ["coklu", "Çoklu"]].map(([d, e]) => el("button", { type: "button", class: `dugme kucuk${durum.mod === d ? " secili" : ""}`,
      "aria-pressed": String(durum.mod === d), disabled: calisiyor,
      title: d === "coklu" ? "Kareler ve klipler hesaplara bölünüp paralel üretilir" : "Sırayla, hesap sırasıyla",
      onclick: async () => { try { durum.mod = (await gonder("/api/uretim/mod", { mod: d })).mod; } catch { /* eski sunucu */ } uretimPaneliniCiz(); } }, e)));
  const gunluk = buProje ? el("div", { class: "uretim-gunlugu" }, el("div", { class: "alan-baslik" }, `${u.baslik} · ${({ calisiyor: "sürüyor", bitti: "bitti", hata: "hata", durduruldu: "durduruldu" })[u.durum] || u.durum} · ${sureYaz(u.sure, false)}`),
    el("pre", { class: "alan-metin" }, (u.gecmis.length ? u.gecmis : [u.mesaj]).join("\n"))) : null;
  if (p.taslak) {
    const a = P.ayar, d = a?.degerler || {};
    const etiket = (anahtar) => (a?.secenekler[anahtar] || []).find(([, v]) => v === d[anahtar])?.[0] || d[anahtar] || "—";
    const madde = (tamam, metin) => el("li", { class: tamam ? "tamam" : "eksik" }, `${tamam ? "✓" : "○"} ${metin}`);
    kap.replaceChildren(...[
      el("p", {}, el("b", {}, "Taslak: "), "proje henüz başlatılmadı. Başlatınca klasör kurulur; akış seslendirmeyi yapar, sahne planını çıkarır ve prompt kapısında durur."),
      el("ul", { class: "kontrol-listesi" },
        madde(!!String(a?.metin || "").trim(), `Anlatım metni${String(a?.metin || "").trim() ? ` · ${kelimeSay(a.metin)} kelime` : " · Metin bölümünde yaz"}`),
        madde(true, `Sahne stratejisi · ${etiket("video.sahne_stratejisi")}`),
        madde(true, `Seslendirme · ${etiket("ses.provider")} · ${etiket("ses.dil")}`),
        madde(true, `Biçim · ${etiket("video.bicim")}`),
        madde(true, `Görsel modeli · ${etiket("gorsel.model")}`),
        madde(!!d["video.genel"], `Genel prompt${d["video.genel"] ? "" : " · boşsa anlatımdan türetilir"}`),
        madde(!!a?.sahne_plani, `🎬 Sahne planı${a?.sahne_plani ? " · kayıtlı, aynen kullanılacak" : " · isteğe bağlı (Metin › Sahne süresi)"}`)),
      el("div", { class: "alan-baslik" }, "Üretim modu"), mod,
      el("button", { type: "button", class: "dugme birincil genis-dugme", disabled: calisiyor, onclick: taslagiBaslat }, "▶ Projeye başlat"),
      gunluk,
    ].filter(Boolean));
    uretimOzetiniGoster();
    return;
  }
  const aiSecimi = () => {
    const a = P.ayar; if (!a) return null;
    const ai = a.degerler["video.ai"], modeller = a.secenekler["video.model"][ai] || [], model = a.degerler["video.model"];
    return [el("div", { class: "secenek-grubu sarili" }, a.secenekler["video.ai"].map(([e, v]) => el("button", { type: "button",
        class: `dugme kucuk${v === ai ? " secili" : ""}`, disabled: calisiyor, onclick: () => alanDegisti("video.ai", v).then(uretimPaneliniCiz) }, e))),
      el("label", { class: "kucuk-alan" }, "Prompt modeli", el("select", { disabled: calisiyor, onchange: (o) => alanDegisti("video.model", o.target.value, false) },
        [...(model && !modeller.includes(model) ? [model] : []), ...modeller].map(m => el("option", { value: m, selected: m === model || null }, m))))];
  };
  const onayGerek = p.durum === "gorsel_onay" || (p.gorsel_onay !== "VERİLDİ" && p.sayim.YARIM + p.sayim.TAMAM === p.sahneler.length && p.sahneler.length);
  const kapi = p.durum === "prompt_onay"
    ? el("div", { class: "kapi" }, el("p", {}, el("b", {}, "① Prompt'lar: "), "seslendirme bitti. Sahne planını ve prompt'ları yazacak yapay zekâyı seç, başlat."),
        aiSecimi(),
        el("button", { type: "button", class: "dugme birincil", disabled: calisiyor,
          onclick: async () => { await ayarlariKaydetSimdi(); uretimBaslat("prompt", { ai: P.ayar?.degerler["video.ai"], model: P.ayar?.degerler["video.model"] },
            "Prompt üretimi başlasın mı?", "Seçilen yapay zekâ sahne planını ve prompt'ları yazar; ardından kareler üretilir ve görsel onayında durur (görsel kotası harcar)."); } }, "▶ Prompt üretimine başla"))
    : onayGerek
      ? el("div", { class: "kapi" }, el("p", {}, el("b", {}, "② Görsel onayı: "), "kareleri sahnelerden incele; beğenmediğini sağ panelden yenile, sonra videoları başlat. Hazır sahne videoları korunur, üretim ilk eksik sahneden sürer."),
          ...durum.servisler.map((s, i) => el("button", { type: "button", class: `dugme${s.anahtar === "ltx" ? " birincil" : ""}${s.anahtar === "huggingface" ? " kucuk" : ""}`, disabled: calisiyor,
            onclick: () => uretimBaslat("onay", { servis: s.anahtar }, "Görseller onaylansın mı?", `Onay projeye yazılır ve videolar ${s.ad} ile üretilmeye başlar (video kotası harcar). Kaldığı yerden devam da bu servisle sürer.`) },
            `✅ Onayla · ${s.ad} ile videoları üret`)))
      : null;
  kap.replaceChildren(...[
    el("dl", { class: "bilgi-listesi" }, el("dt", {}, "Durum"), el("dd", {}, p.durum_adi || p.durum || "—"),
      el("dt", {}, "Sahneler"), el("dd", {}, `${p.sayim.TAMAM}/${p.sahneler.length} tamam · ${p.sayim.YARIM} yarım · ${p.sayim.HATA} hata · ${p.sayim["BEKLİYOR"]} bekliyor`),
      el("dt", {}, "Görsel onayı"), el("dd", {}, p.gorsel_onay || "—"), el("dt", {}, "Video servisi"), el("dd", {}, p.video_servisi || "—")),
    el("div", { class: "alan-baslik" }, "Üretim modu"), mod,
    kapi,
    el("div", { class: "dugme-satiri" },
      calisiyor && buProje
        ? el("button", { type: "button", class: "dugme tehlike", onclick: uretimDurdur }, "⏹ Durdur")
        : el("button", { type: "button", class: "dugme birincil", disabled: calisiyor,
            onclick: () => uretimBaslat("devam", {}, "Kaldığı yerden devam edilsin mi?", "StudioFlow'un akışı eksik ve hatalı sahneleri tamamlar; kota harcar. StudioFlow uygulamasında aynı anda çalıştırma.") }, "⏵ Kaldığı yerden devam et"),
      el("button", { type: "button", class: "dugme", disabled: calisiyor, title: "Deneme hakkı dolup duran adımları yeniden denenebilir yapar",
        onclick: async () => { try { alertKutusu((await gonder(projeYolu("/uretim/deneme"), {})).mesaj); await projeyiTazele(); } catch (e) { alertKutusu(e.message); } } }, "↻ Deneme hakkını yenile")),
    baskaProje ? el("p", { class: "hata-metin" }, `'${u.ad}' projesinde bir iş sürüyor.`) : null,
    gunluk,
  ].filter(Boolean));
  uretimOzetiniGoster();
}

/* ── Dışa aktarma ───────────────────────────────────────────────────────── */
/* Dışa aktar'a basınca pencere açılır: önce kayıt konumu seçilir, sonra ilerleme aynı
   pencerede izlenir. İş sürerken pencere kilitlidir: Esc ile ya da başka yolla kapanmaz,
   arkadaki editör kullanılamaz (modal); yalnızca İptal durdurur. Üst çubuk değişmez. */
const dp = { kilitli: false, son: null };
const DP_ROZET = { calisiyor: "Sürüyor", bitti: "Hazır", hata: "Hata", iptal: "İptal edildi" };
const klasorunu = (yol) => String(yol || "").replace(/[\\/][^\\/]*$/, "");
const dosyaAdi = (yol) => String(yol || "").split(/[\\/]/).pop();

function dpDugmeler(gorunen) {
  for (const id of ["dp-vazgec", "dp-iptal", "dp-goster", "dp-ac", "dp-kapat", "dp-baslat"])
    $("#" + id).hidden = !gorunen.includes(id);
}
function dpHata(mesaj) { $("#dp-hata").textContent = mesaj || ""; $("#dp-hata").hidden = !mesaj; }

async function disaPenceresiniAc(suren = null) {
  const pencere = $("#disa-pencere");
  dpHata("");
  if (suren) { isDurumunuGoster(suren); if (!pencere.open) pencere.showModal(); return; }
  dp.kilitli = false; dp.son = null;
  $("#dp-hazirlik").hidden = false; $("#dp-ilerleme").hidden = true; $("#dp-durum").hidden = true;
  $("#dp-baslik").textContent = "Dışa aktar";
  dpDugmeler(["dp-vazgec", "dp-baslat"]);
  $("#dp-baslat").disabled = false;
  // Her açılışta yeni zaman damgalı ad; klasör, son seçilen klasör (hatırlanır).
  try { durum.varsayilanHedef = (await api(projeYolu("/disa-aktar"))).varsayilan_hedef || durum.varsayilanHedef; } catch { /* eskisi kalır */ }
  const sonKlasor = yerelOku("sf-disa-klasor", "");
  $("#dp-hedef").value = sonKlasor && durum.varsayilanHedef
    ? `${sonKlasor}\\${dosyaAdi(durum.varsayilanHedef)}` : durum.varsayilanHedef;
  $("#dp-izler").replaceChildren(...IZLER.map(i => {
    const acik = !!durum.ayar?.isaret?.[i.anahtar];
    const secim = i.anahtar === "muzik" ? (durum.ayar?.muzik || []).join(", ")
      : ["dublaj", "altyazi", "efekt"].includes(i.anahtar) ? durum.ayar?.[i.anahtar] : "";
    return el("span", { class: `dp-iz${acik ? " acik" : ""}`, title: acik ? "Videoya girer" : "Zaman çizelgesinde işaretli değil: videoya girmez" },
      `${acik ? "✓" : "–"} ${i.ad}${acik && secim ? ` · ${secim}` : ""}`);
  }));
  if (!pencere.open) pencere.showModal();
  $("#dp-hedef").focus(); $("#dp-hedef").select();
}

async function konumSec() {
  const dugme = $("#dp-gozat");
  dugme.disabled = true; dpHata("");
  try {
    const r = await gonder(projeYolu("/disa-aktar/konum"), { hedef: $("#dp-hedef").value.trim() });
    if (!r.pencere) { dpHata("Kayıt penceresi yalnızca uygulama penceresinde açılır; yolu kutuya elle yaz."); $("#dp-hedef").focus(); }
    else if (r.hedef) $("#dp-hedef").value = r.hedef;
  } catch (h) { dpHata(h.message); }
  finally { dugme.disabled = false; }
}

async function disaAktar() {
  const hedef = $("#dp-hedef").value.trim();
  if (!hedef) { dpHata("Kayıt konumunu seç ya da yaz."); return; }
  $("#dp-baslat").disabled = true; dpHata("");
  const isaretli = IZLER.filter(i => durum.ayar.isaret[i.anahtar]).map(i => i.ad);
  bildir(`Dışa aktarılıyor: ${isaretli.join(", ") || "yalnızca siyah görüntü"}`);
  try {
    const is = await gonder(projeYolu("/disa-aktar"), { hedef });
    yerelYaz("sf-disa-klasor", klasorunu(hedef));
    isDurumunuGoster(is); isiIzle();
  } catch (hata) { dpHata(hata.message); $("#dp-baslat").disabled = false; }
}

/* İşin durumu: üst çubuktaki düğme yalnızca kilitlenir; ayrıntı pencerede gösterilir. */
function isDurumunuGoster(is) {
  dp.son = is;
  $("#disa-aktar").disabled = durum.sunucuEski || !!durum.proje?.taslak || is?.durum === "calisiyor";
  if (!is || !$("#disa-pencere").open) return;
  const suruyor = is.durum === "calisiyor";
  dp.kilitli = suruyor;
  $("#dp-hazirlik").hidden = true; $("#dp-ilerleme").hidden = false;
  $("#dp-baslik").textContent = suruyor ? "Dışa aktarılıyor…" : is.durum === "bitti" ? "Dışa aktarma tamam" : "Dışa aktarma durdu";
  const rozet = $("#dp-durum");
  rozet.hidden = false; rozet.className = `dp-rozet ${is.durum}`; rozet.textContent = DP_ROZET[is.durum] || is.durum;
  const yuzde = Math.max(0, Math.min(100, Number(is.yuzde) || 0));
  $("#dp-cubuk").style.width = `${yuzde}%`; $("#dp-cubuk").className = is.durum;
  $("#dp-yuzde").textContent = `%${yuzde}`;
  $("#dp-mesaj").textContent = is.mesaj || "";
  $("#dp-kilit").hidden = !suruyor;
  const yol = $("#dp-yol");
  yol.hidden = !is.yol; yol.textContent = is.yol ? `${is.durum === "bitti" ? "Kaydedildi" : "Hedef"}: ${is.yol}` : "";
  const ac = $("#dp-ac");
  if (is.dosya) { ac.href = is.dosya; ac.title = is.dosya_adi || ""; }
  dpDugmeler(suruyor ? ["dp-iptal"]
    : is.durum === "bitti" ? ["dp-goster", ...(is.dosya ? ["dp-ac"] : []), "dp-kapat"] : ["dp-kapat"]);
  $("#dp-iptal").disabled = false;
}
function isiIzle() {
  clearInterval(durum.isZamanlayici);
  const ad = durum.proje.ad;
  durum.isZamanlayici = setInterval(async () => {
    if (!durum.proje || durum.proje.ad !== ad) return clearInterval(durum.isZamanlayici);
    try {
      const { is } = await api(projeYolu("/disa-aktar"));
      isDurumunuGoster(is);
      if (!is || is.durum !== "calisiyor") clearInterval(durum.isZamanlayici);
    } catch { /* sunucu kısa süre yanıt vermediyse sonraki turda */ }
  }, 1000);
}

/* ── Olaylar ────────────────────────────────────────────────────────────── */
function baglantilar() {
  $("#geri").addEventListener("click", () => { location.hash = ""; });
  $("#oynat").addEventListener("click", () => durum.oynuyor ? durakla() : oynat());
  $("#onceki").addEventListener("click", () => sahneAtla(-1));
  $("#sonraki").addEventListener("click", () => sahneAtla(1));
  $("#ses-duzeyi").addEventListener("input", sesSeviyesi);
  // Uygulama penceresinde sekme yoktur: yeni sekmede açılan **yerel** dosyalar (kare,
  // video, belge) görüntüleyicide açılır; dış bağlantılar sistem tarayıcısına gider.
  document.addEventListener("click", (o) => {
    const a = o.target.closest?.("a[target=_blank]");
    if (!a || a.hasAttribute("download") || o.ctrlKey || o.shiftKey) return;
    const adres = new URL(a.href, location.href);
    if (adres.origin !== location.origin) return;
    o.preventDefault();
    dosyaGoster(adres.href, a.title || a.textContent.trim());
  });
  $("#gr-kapat").addEventListener("click", () => $("#goruntuleyici").close());
  $("#goruntuleyici").addEventListener("close", () => $("#gr-icerik").replaceChildren());
  // Tam ekran: görüntüyle birlikte kontroller (oynat/duraklat, ileri/geri, süre, ses) de
  // tam ekrana girer (21.10.2026: yalnızca #tuval giriyordu, kontroller kayboluyordu).
  // Oynatırken fare 2,5 sn kıpırdamazsa kontroller gizlenir; fare oynayınca geri gelir.
  const alan = $(".sahne-alani");
  const tamEkranDegistir = () => document.fullscreenElement
    ? document.exitFullscreen?.().catch(() => {}) : alan.requestFullscreen?.().catch(() => {});
  let gizleZamanlayici = null;
  const kontrolleriGoster = () => {
    alan.classList.remove("kontrol-gizli");
    clearTimeout(gizleZamanlayici);
    if (document.fullscreenElement === alan && durum.oynuyor)
      gizleZamanlayici = setTimeout(() => alan.classList.add("kontrol-gizli"), 2500);
  };
  $("#tam-ekran").addEventListener("click", tamEkranDegistir);
  $("#tuval").addEventListener("dblclick", tamEkranDegistir);
  alan.addEventListener("mousemove", kontrolleriGoster);
  $("#oynat").addEventListener("click", () => setTimeout(kontrolleriGoster, 0));
  document.addEventListener("fullscreenchange", () => {
    const tam = document.fullscreenElement === alan;
    $("#tam-ekran").title = tam ? "Tam ekrandan çık (Esc)" : "Tam ekran (çift tıkla da olur)";
    kontrolleriGoster();
  });
  $("#disa-aktar").addEventListener("click", () => disaPenceresiniAc());
  $("#dp-baslat").addEventListener("click", disaAktar);
  $("#dp-hedef").addEventListener("keydown", (o) => { if (o.key === "Enter") { o.preventDefault(); disaAktar(); } });
  $("#dp-gozat").addEventListener("click", konumSec);
  $("#dp-iptal").addEventListener("click", async () => {
    $("#dp-iptal").disabled = true; $("#dp-mesaj").textContent = "İptal ediliyor…";
    try { isDurumunuGoster(await gonder(projeYolu("/disa-aktar/iptal"), {})); } catch { /* izleme sürer */ }
  });
  $("#dp-goster").addEventListener("click", async () => {
    try { await gonder(projeYolu("/disa-aktar/goster"), {}); } catch (h) { dpHata(h.message); }
  });
  for (const id of ["dp-vazgec", "dp-kapat"])
    $("#" + id).addEventListener("click", () => { if (!dp.kilitli) $("#disa-pencere").close(); });
  // Kilitliyken Esc pencereyi kapatmaz; tarayıcı yine de kapatırsa hemen yeniden açılır.
  $("#disa-pencere").addEventListener("cancel", (o) => { if (dp.kilitli) o.preventDefault(); });
  $("#disa-pencere").addEventListener("close", () => {
    if (dp.kilitli) requestAnimationFrame(() => { if (!$("#disa-pencere").open) $("#disa-pencere").showModal(); });
  });
  $("#uretim-ozet-durdur").addEventListener("click", uretimDurdur);
  $("#yeni-proje-form").addEventListener("submit", yeniProjeOlustur);
  $("#yp-vazgec").addEventListener("click", () => $("#yeni-proje").close());
  $("#aralik-bas").addEventListener("click", () => araligiKoy("bas"));
  $("#aralik-bit").addEventListener("click", () => araligiKoy("bit"));
  $("#aralik-temizle").addEventListener("click", () => araligiKoy("temizle"));
  $("#sahne-suzgec").addEventListener("change", panelleriCiz);
  $$(".ray-oge").forEach(b => b.addEventListener("click", () => panelSec(b.dataset.panel)));
  $("#baslat").addEventListener("click", taslagiBaslat);
  $("#uretim-ozet-kapat").addEventListener("click", () => { $("#uretim-ozet").classList.remove("uyari"); $("#uretim-ozet").hidden = true; });
  $("#zoom").addEventListener("input", (o) => yakinlastir(Number(o.target.value)));
  $("#zoom-azalt").addEventListener("click", () => yakinlastir(durum.pxSn / 1.4));
  $("#zoom-arttir").addEventListener("click", () => yakinlastir(durum.pxSn * 1.4));
  $("#sigdir").addEventListener("click", sigdir);
  const kay = $("#zc-kaydirma");
  const tdenX = (o) => (o.clientX - kay.getBoundingClientRect().left + kay.scrollLeft) / durum.pxSn;
  let surukle = false;
  const cetvel = $("#cetvel");
  const birak = () => { surukle = false; };
  cetvel.addEventListener("pointerdown", (o) => {
    if (o.button !== 0) return;
    o.preventDefault();
    surukle = true;
    cetvel.setPointerCapture(o.pointerId);
    zamanaGit(tdenX(o));
  });
  // Yalnızca sol tuş basılıyken izle; bırakma olayı kaçsa bile buttons=0 sürüklemeyi bitirir.
  cetvel.addEventListener("pointermove", (o) => {
    if (!surukle) return;
    if (!(o.buttons & 1)) { birak(); return; }
    zamanaGit(tdenX(o));
  });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach(ad => cetvel.addEventListener(ad, birak));
  window.addEventListener("pointerup", birak);
  window.addEventListener("blur", birak);
  $("#izler").addEventListener("click", (o) => zamanaGit(tdenX(o)));
  kay.addEventListener("wheel", (o) => {
    if (o.ctrlKey) { o.preventDefault(); yakinlastir(durum.pxSn * (o.deltaY < 0 ? 1.15 : 1 / 1.15), tdenX(o)); }
    else {
      durum.elleKaydirdi = true;
      if (Math.abs(o.deltaY) > Math.abs(o.deltaX) && !o.shiftKey) { o.preventDefault(); kay.scrollLeft += o.deltaY; }
    }
  }, { passive: false });
  // Alttaki kaydırma çubuğunu sürüklemek de elle kaydırmadır (çubuk clientHeight'in altında kalır).
  kay.addEventListener("pointerdown", (o) => { if (o.target === kay && o.offsetY >= kay.clientHeight) durum.elleKaydirdi = true; });
  $("#takip").addEventListener("change", () => { durum.elleKaydirdi = false; oynatmaCizgisiniKoy(); });
  let cetvelBekliyor = false;
  kay.addEventListener("scroll", () => {
    $("#zc-adlar").scrollTop = kay.scrollTop;
    if (!cetvelBekliyor && durum.proje) {
      cetvelBekliyor = true;
      requestAnimationFrame(() => { cetvelBekliyor = false; cetveliCiz(); });
    }
  });
  document.addEventListener("keydown", (o) => {
    if ($("#editor").hidden || /INPUT|SELECT|TEXTAREA/.test(o.target.tagName) || document.querySelector("dialog[open]")) return;
    if (o.code === "Space") { o.preventDefault(); durum.oynuyor ? durakla() : oynat(); }
    else if (o.key === "ArrowLeft") { o.preventDefault(); sahneAtla(-1); }
    else if (o.key === "ArrowRight") { o.preventDefault(); sahneAtla(1); }
    else if (o.key === "+" || o.key === "=") yakinlastir(durum.pxSn * 1.25);
    else if (o.key === "-") yakinlastir(durum.pxSn / 1.25);
    else if (o.key === "Home") zamanaGit(0);
    else if (o.key === "End") zamanaGit(durum.proje.sure);
    else if (o.key === "i" || o.key === "I") araligiKoy("bas");
    else if (o.key === "o" || o.key === "O") araligiKoy("bit");
  });
  window.addEventListener("resize", () => durum.proje && izleriYenile());
  window.addEventListener("hashchange", yonlendir);
}

function panelSec(ad) {
  $$(".ray-oge").forEach(x => x.classList.toggle("secili", x.dataset.panel === ad));
  $$(".panel-bolum").forEach(p => { p.hidden = p.dataset.panel !== ad; });
  if (durum.proje) bolumAcildi(ad);
}
async function taslagiBaslat() {
  await ayarlariKaydetSimdi();
  if (!String(P.ayar?.metin || "").trim()) { alertKutusu("Önce Metin bölümünde anlatım metnini yaz."); return panelSec("metin"); }
  const a = P.ayar.degerler;
  if (!(await onayIste("Proje başlatılsın mı?", `Klasör kurulur ve akış başlar: seslendirme (${a["ses.provider"]} · ${a["ses.dil"]}) → sahne planı (${a["video.sahne_stratejisi"]}) → prompt kapısında durur. Seslendirme kotası harcanır.`))) return;
  try { durum.uretim = await gonder(projeYolu("/baslat"), {}); uretimiIzle(); panelSec("uretim"); }
  catch (hata) { alertKutusu(hata.message); }
}

function yonlendir() {
  const ad = decodeURIComponent(location.hash.slice(1));
  if (ad === "araclar" || ad.startsWith("araclar/")) return araclariAc(ad.split("/")[1] || "");
  if (ad === "api-hesaplari") return araclariAc("api-hesaplari");
  $("#araclar").hidden = true;
  if (ad) projeyiAc(ad); else kutuphaneyiAc();
}

baglantilar();
uretimDurumunuAl().then(() => { if (durum.uretim?.durum === "calisiyor") uretimiIzle(); });
yonlendir();
