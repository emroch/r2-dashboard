// Chart-library spike (#107): what all three prototypes share. Temporary: this
// directory is deleted once the library is chosen.
//
// Colors: a spec names a category ("color:Launch Green") or an accent
// ("var:cadence-front"); the page's CSS owns the value, per theme. A probe
// element takes the category class, and its resolved mark color is read back
// as sRGB from a 1px canvas, because Plotly can't parse oklch().
(function () {
  "use strict";
  const slug = (v) => String(v).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  function toRgb(css) {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = "#000"; ctx.fillStyle = css; ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
  }
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.documentElement.append(probe);
  function color(ref, role = "mark") {
    if (ref.startsWith("var:")) {
      probe.className = "";
      probe.style.color = `var(--${ref.slice(4)})`;
    } else {
      const [dim, ...rest] = ref.split(":");
      probe.className = `cat-${dim}-${slug(rest.join(":"))}`;
      probe.style.color = `var(--${role})`;
    }
    return toRgb(getComputedStyle(probe).color);
  }
  function chrome() {
    const cs = getComputedStyle(document.documentElement);
    const v = (n) => toRgb(cs.getPropertyValue(n).trim());
    return { text: v("--fg"), muted: v("--desc"), grid: v("--card-bd"),
             card: v("--card-bg"), edge: v("--desc") };
  }
  // The house legend: HTML buttons, so it reads and works the same whatever
  // draws the chart. Click hides a series; double-click isolates it (again to
  // show all). onChange(hiddenSet) redraws.
  function legend(el, items, onChange) {
    const hidden = new Set();
    el.innerHTML = "";
    for (const it of items) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "lg-item"; b.dataset.name = it.name;
      b.innerHTML = `<i class="swatch ${it.cls || ""}"></i>${it.name}`;
      b.setAttribute("aria-pressed", "true");
      let timer = null;
      b.addEventListener("click", () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          hidden.has(it.name) ? hidden.delete(it.name) : hidden.add(it.name);
          sync();
        }, 220);
      });
      b.addEventListener("dblclick", () => {
        clearTimeout(timer);
        const others = items.filter((o) => o.name !== it.name).map((o) => o.name);
        const isolated = !hidden.has(it.name) && others.every((o) => hidden.has(o));
        hidden.clear();
        if (!isolated) others.forEach((o) => hidden.add(o));
        sync();
      });
      el.append(b);
    }
    function sync() {
      for (const b of el.children) b.setAttribute("aria-pressed", String(!hidden.has(b.dataset.name)));
      onChange(hidden);
    }
    return hidden;
  }
  const catClass = (ref) => { const [d, ...r] = ref.split(":"); return `cat-${d}-${slug(r.join(":"))}`; };
  const symbols = {
    plot: { "triangle-up": "triangle", square: "square", diamond: "diamond", circle: "circle" },
    echarts: { "triangle-up": "triangle", square: "rect", diamond: "diamond", circle: "circle" },
  };
  function load(src) {
    return new Promise((ok, fail) => {
      const s = Object.assign(document.createElement("script"), { src, crossOrigin: "anonymous" });
      s.onload = ok; s.onerror = () => fail(new Error("failed to load " + src));
      document.head.append(s);
    });
  }
  // Load a panel's library when it nears the viewport, and record what it cost.
  function whenNear(el, fn) {
    new IntersectionObserver((es, obs) => {
      if (es.some((e) => e.isIntersecting)) { obs.disconnect(); fn(); }
    }, { rootMargin: "400px" }).observe(el);
  }
  function cost(el, urls, t0) {
    const res = performance.getEntriesByType("resource").filter((r) => urls.some((u) => r.name === u));
    const kb = res.reduce((s, r) => s + (r.encodedBodySize || r.transferSize || 0), 0) / 1024;
    el.textContent = `${kb ? kb.toFixed(0) + " KB on the wire" : "size n/a (cached or opaque)"} · ready in ${(performance.now() - t0).toFixed(0)} ms`;
  }
  const whiskersOn = () => new URLSearchParams(location.search).get("whiskers") !== "0";
  window.Spike = { color, chrome, legend, catClass, symbols, load, whenNear, cost,
                   whiskersOn, view: JSON.parse(document.getElementById("spike-data").textContent) };
})();
