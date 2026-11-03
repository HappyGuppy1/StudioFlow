/* Davranış katmanı: yalnızca görünümü etkiler, üretim olaylarına dokunmaz. */
(() => {
  /* Varsayılan tema koyu. Gradio temayı açılışta adresteki `__theme` değerinden okur;
     değer yoksa sistem temasını kullanır ve koyu temayı `body`'ye `dark` sınıfı
     ekleyerek uygular. Bu betik Gradio temayı okuduktan sonra sayfaya eklenir: adreste
     tema yoksa sınıf burada eklenir ve adrese `__theme=dark` yazılır (yeniden yüklemede
     Gradio da koyu açar). Ayarlar panelinden açık tema seçilirse adres
     `__theme=light` olur ve bu blok ona dokunmaz. */
  try {
    const adres = new URL(window.location.href);
    if (!adres.searchParams.has("__theme")) {
      adres.searchParams.set("__theme", "dark");
      window.history.replaceState(window.history.state, "", adres);
      const koyu = () => document.body.classList.add("dark");
      if (document.body) koyu(); else document.addEventListener("DOMContentLoaded", koyu);
    }
  } catch (hata) { /* adres değiştirilemezse sistem teması kalır */ }

  /* Tek açık panel: `.sf-tek-panel` içinde bir açılır panel açılınca aynı alandaki
     diğer açık paneller kapanır. Gradio paneli başlık düğmesine (`button.label-wrap`)
     tıklanınca açıp kapatır; açık olanın düğmesi `.open` sınıfını taşır. Olay
     yakalama evresinde dinlenir: tıklanan düğmenin sınıfı henüz değişmemiştir. */
  document.addEventListener("click", (olay) => {
    const dugme = olay.target.closest && olay.target.closest("button.label-wrap");
    if (!dugme || dugme.classList.contains("open")) return;
    const alan = dugme.closest(".sf-tek-panel");
    if (!alan) return;
    const panel = dugme.parentElement;
    alan.querySelectorAll("button.label-wrap.open").forEach((acik) => {
      // İç içe paneller birbirini kapatmaz; başka bir alanın paneline dokunulmaz.
      if (acik === dugme || panel.contains(acik) || acik.parentElement.contains(dugme)) return;
      if (acik.closest(".sf-tek-panel") !== alan) return;
      acik.click();
    });
  }, true);

  /* Proje editörü · alt şerit (bkz. `studioflow/arayuz/editor.py`).
     Sahneye tıklanınca sahne numarası görünmez `#sf-sahne-tik` alanına yazılır ve
     `input` olayı tetiklenir: sunucu sağ paneli o sahneyle doldurur. İze tıklanınca
     soldaki şeritte o katmanın bölümü seçilir. */
  document.addEventListener("click", (olay) => {
    const hedef = olay.target.closest && olay.target;
    if (!hedef) return;
    const sahne = hedef.closest(".sf-serit-sahne[data-sahne]");
    if (sahne) {
      const alan = document.querySelector("#sf-sahne-tik textarea, #sf-sahne-tik input");
      if (!alan) return;
      alan.value = sahne.dataset.sahne;
      alan.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    const iz = hedef.closest(".sf-iz[data-bolum]");
    if (iz) {
      const secim = document.querySelector(
        `.sf-ray-secim input[value="${iz.dataset.bolum}"]`);
      if (secim) secim.click();
    }
  });

  /* Sahne şeridi de fare tekerleğiyle sağa sola kayar (dikey hareket yataya çevrilir). */
  document.addEventListener("wheel", (olay) => {
    const serit = olay.target.closest && olay.target.closest(".sf-serit");
    if (!serit || serit.scrollWidth <= serit.clientWidth) return;
    if (Math.abs(olay.deltaY) <= Math.abs(olay.deltaX)) return;
    olay.preventDefault();
    serit.scrollLeft += olay.deltaY;
  }, { passive: false });

  /* Galeri şeridi: önizlemedeki küçük resimler fare tekerleğiyle de sağa sola kayar
     (dikey tekerlek hareketi yatay kaydırmaya çevrilir). */
  document.addEventListener("wheel", (olay) => {
    const serit = olay.target.closest && olay.target.closest(".thumbnails");
    if (!serit || serit.scrollWidth <= serit.clientWidth) return;
    if (Math.abs(olay.deltaY) <= Math.abs(olay.deltaX)) return;
    olay.preventDefault();
    serit.scrollLeft += olay.deltaY;
  }, { passive: false });

  /* Galeri önizlemesindeki çarpı (`Close`): tam ekrandayken Gradio yalnızca
     önizlemeyi kapatır, tam ekran kutusu boş ve siyah kalır. Gradio'nun tam ekranı
     tarayıcı tam ekranı değil, kutunun kendi durumudur; çarpıdan önce aynı araç
     çubuğundaki "Exit fullscreen mode" düğmesine basılır, böylece çarpı
     önizlemeden çıkıp galeriye döner. */
  document.addEventListener("click", (olay) => {
    const dugme = olay.target.closest && olay.target.closest('button[aria-label="Close"]');
    const onizleme = dugme && dugme.closest(".preview");
    if (!onizleme) return;
    const cikis = onizleme.querySelector('button[aria-label="Exit fullscreen mode"]');
    if (cikis) cikis.click();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, true);
})();
