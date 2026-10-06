// Spike (#107): plain d3 7, no Plot. SVG, colored entirely by CSS: each series
// carries its category class and fills with var(--mark), axes use the theme's
// custom properties, so a theme change needs no redraw at all. Pan and zoom via
// d3-zoom (wheel, pinch, drag; double-click resets), axes fixed to all the data
// so hiding a series never rescales, tooltips by nearest point (d3.Delaunay).
(function () {
  "use strict";
  const S = window.Spike;
  const D3 = "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js";
  const TOPO = "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js";
  const NA = "https://cdn.jsdelivr.net/npm/sane-topojson@4.0.0/dist/north-america_50m.json";
  let libs = null;
  const ready = () => libs || (libs = S.load(D3));
  const date = (s) => new Date(s + "T12:00:00");
  const SYM = { circle: "symbolCircle", square: "symbolSquare", diamond: "symbolDiamond", "triangle-up": "symbolTriangle" };

  function tooltip(host) {
    let tip = host.querySelector(".d3-tip");
    if (!tip) { tip = Object.assign(document.createElement("div"), { className: "d3-tip", role: "status", hidden: true }); host.append(tip); }
    return {
      show(lines, x, y) { tip.textContent = ""; lines.forEach((l, i) => { const d = document.createElement(i ? "div" : "b"); d.textContent = l; tip.append(d); });
                          tip.style.left = x + 14 + "px"; tip.style.top = y + 14 + "px"; tip.hidden = false; },
      hide() { tip.hidden = true; },
    };
  }

  // ---- §10 scatter ----------------------------------------------------------
  function scatter(el, spec, hidden) {
    if (el._d3) return el._d3.visibility(hidden);           // legend change: no redraw
    el.style.position = "relative";
    const W = el.clientWidth, H = 560, m = { t: 24, r: 16, b: 52, l: 72 };
    const pts = spec.series.flatMap((s) => s.points.map((p) => ({ ...p, s })));
    // Fixed domains from every series and layer, so toggling never rescales.
    const xs = pts.flatMap((p) => [p.x, p.lo, p.hi]).filter(Boolean).map(date);
    const ys = pts.map((p) => p.y);
    for (const l of spec.layers) {
      if (l.type === "rule") xs.push(date(l.value));
      else for (const d of l.points) { xs.push(date(d[0])); ys.push(...d.slice(1)); }
    }
    const x0 = d3.scaleUtc().domain(d3.extent(xs)).nice().range([m.l, W - m.r]);
    const y0 = d3.scaleLinear().domain(d3.extent(ys)).nice().range([H - m.b, m.t]);
    let x = x0, y = y0;
    const svg = d3.select(el).append("svg").attr("class", "d3-chart").attr("viewBox", [0, 0, W, H])
      .attr("role", "img").attr("aria-label", spec.title);
    const clipId = "clip-" + Math.random().toString(36).slice(2);
    svg.append("clipPath").attr("id", clipId).append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b);
    const gx = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`);
    const gy = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
    svg.append("text").attr("class", "axis-label").attr("x", (m.l + W - m.r) / 2).attr("y", H - 10).attr("text-anchor", "middle").text(spec.x.label);
    svg.append("text").attr("class", "axis-label").attr("transform", `translate(16,${(m.t + H - m.b) / 2}) rotate(-90)`).attr("text-anchor", "middle").text(spec.y.label);
    const plot = svg.append("g").attr("clip-path", `url(#${clipId})`);
    const layers = plot.append("g"), whisk = plot.append("g"), dots = plot.append("g");
    const band = spec.layers.filter((l) => l.type === "band"), lines = spec.layers.filter((l) => l.type === "line"),
          rules = spec.layers.filter((l) => l.type === "rule");
    const bandG = layers.selectAll("path.band").data(band).join("path").attr("class", "band").attr("data-name", (l) => l.name)
      .style("fill", (l) => `var(--${l.color.slice(4)})`);
    const lineG = layers.selectAll("g.line").data(lines).join("g").attr("class", "line").attr("data-name", (l) => l.name);
    lineG.append("path").style("stroke", (l) => `var(--${l.color.slice(4)})`).attr("fill", "none")
      .attr("stroke-width", (l) => (l.dash ? 2.5 : 3)).attr("stroke-dasharray", (l) => (l.dash ? "6,4" : null));
    lineG.filter((l) => !l.dash).selectAll("circle").data((l) => l.points.map((d) => ({ d, l }))).join("circle").attr("r", 3.5)
      .style("fill", (o) => `var(--${o.l.color.slice(4)})`);
    const ruleG = layers.selectAll("g.rule").data(rules).join("g").attr("class", "rule");
    ruleG.append("line").attr("class", "today"); ruleG.append("text").attr("class", "today-label").text((l) => l.label);
    const series = spec.series.map((s) => ({ s, cls: S.catClass(s.color) }));
    const wG = whisk.selectAll("g").data(series).join("g").attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
    const dG = dots.selectAll("g").data(series).join("g").attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
    const sym = (o) => d3.symbol(d3[SYM[o.s.symbol] || "symbolCircle"], 90)();
    dG.selectAll("path").data((o) => o.s.points.map((p) => ({ p, o }))).join("path").attr("class", "pt").attr("d", (d) => sym(d.o));
    wG.selectAll("path").data((o) => o.s.points.filter((p) => p.lo)).join("path").attr("class", "whisker");

    function place() {
      gx.call(d3.axisBottom(x).ticks(W / 110)).call((g) => g.selectAll(".tick line").clone().attr("class", "grid").attr("y2", -(H - m.t - m.b)));
      gy.call(d3.axisLeft(y).ticks(8, "~s")).call((g) => g.selectAll(".tick line").clone().attr("class", "grid").attr("x2", W - m.l - m.r));
      const area = d3.area().x((d) => x(date(d[0]))).y0((d) => y(d[1])).y1((d) => y(d[2]));
      bandG.attr("d", (l) => area(l.points));
      const line = d3.line().x((d) => x(date(d[0]))).y((d) => y(d[1]));
      lineG.select("path").attr("d", (l) => line(l.points));
      lineG.selectAll("circle").attr("cx", (o) => x(date(o.d[0]))).attr("cy", (o) => y(o.d[1]));
      ruleG.select("line").attr("x1", (l) => x(date(l.value))).attr("x2", (l) => x(date(l.value))).attr("y1", m.t).attr("y2", H - m.b);
      ruleG.select("text").attr("x", (l) => x(date(l.value)) + 4).attr("y", m.t + 10);
      dG.selectAll("path.pt").attr("transform", (d) => `translate(${x(date(d.p.x))},${y(d.p.y)})`);
      wG.selectAll("path.whisker").attr("d", (p) => {
        const a = x(date(p.lo)), b = x(date(p.hi)), v = y(p.y);
        return `M${a},${v}H${b}M${a},${v - 4}V${v + 4}M${b},${v - 4}V${v + 4}`;
      }).style("display", S.whiskersOn() ? null : "none");
    }
    place();

    // Tooltips: the nearest visible point (or front week) within 18px.
    const tt = tooltip(el);
    let shown = new Set(spec.series.map((s) => s.name).concat(spec.layers.map((l) => l.name)));
    svg.on("pointermove", (ev) => {
      const [px, py] = d3.pointer(ev);
      let best = null, bd = 18 * 18;
      for (const p of pts) if (shown.has(p.s.name)) {
        const dx = x(date(p.x)) - px, dy = y(p.y) - py, d2 = dx * dx + dy * dy;
        if (d2 < bd) { bd = d2; best = p.tip; }
      }
      for (const l of lines) if (!l.dash && shown.has(l.name)) for (const d of l.points) {
        const dx = x(date(d[0])) - px, dy = y(d[1]) - py, d2 = dx * dx + dy * dy;
        if (d2 < bd) { bd = d2; best = [l.name, `Week of ${d3.utcFormat("%b %d")(date(d[0]))}: front ≈ VIN ${d3.format(",.0f")(d[1])}`]; }
      }
      const [hx, hy] = d3.pointer(ev, el);
      best ? tt.show(best, hx, hy) : tt.hide();
    }).on("pointerleave", () => tt.hide());

    // Pan/zoom: wheel or pinch zooms, drag pans, double-click resets.
    const zoom = d3.zoom().scaleExtent([1, 40]).extent([[m.l, m.t], [W - m.r, H - m.b]])
      .translateExtent([[m.l - 200, m.t - 200], [W - m.r + 200, H - m.b + 200]])
      .on("zoom", (ev) => { x = ev.transform.rescaleX(x0); y = ev.transform.rescaleY(y0); place(); tt.hide(); });
    svg.call(zoom).on("dblclick.zoom", () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity));
    const reset = Object.assign(document.createElement("button"), { type: "button", className: "lg-item d3-reset", textContent: "Reset view" });
    reset.addEventListener("click", () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity));
    el.prepend(reset);

    el._d3 = {
      visibility(h) {
        shown = new Set([...spec.series.map((s) => s.name), ...spec.layers.map((l) => l.name)].filter((n) => !h.has(n)));
        svg.selectAll("[data-name]").style("display", function () { return h.has(this.dataset.name) ? "none" : null; });
        place();
      },
    };
    el._d3.visibility(hidden);
  }

  // ---- §12 map: lower 48 + Canada + Mexico, Alaska and Hawaii inset ----------
  let na = null;
  async function map(el, spec) {
    if (el._d3) return;                                        // CSS-colored: nothing to redraw
    if (!na) {
      await S.load(TOPO);
      na = await fetch(NA).then((r) => r.json());
    }
    el.style.position = "relative";
    const W = el.clientWidth, H = Math.round(W * 0.62);
    const feats = (k) => topojson.feature(na, na.objects[k]).features;
    const subunits = feats("subunits");
    const inset = (id) => subunits.filter((f) => f.id === id);
    const others = feats("countries").filter((f) => f.id !== "USA");
    const lower = subunits.filter((f) => !["AK", "HI"].includes(f.id));
    // The view: the lower 48 with southern Canada and northern Mexico around it.
    const view = { type: "MultiPoint", coordinates: [[-124, 25], [-67, 25], [-64, 50], [-127, 50]] };
    const main = d3.geoConicEqualArea().rotate([96, 0]).parallels([29.5, 45.5]).fitExtent([[0, 0], [W, H]], view)
      .clipExtent([[0, 0], [W, H]]);
    // Insets in the bottom-left corner, as d3.geoAlbersUsa places them: each
    // state fitted into its own box (with the projections albersUsa uses), so
    // nothing is cropped whatever the card's width.
    const box = (x0, y0, x1, y1) => [[W * x0, H * y0], [W * x1, H * y1]];
    const fitted = (proj, id, b) => proj.fitExtent([[b[0][0] + 6, b[0][1] + 6], [b[1][0] - 6, b[1][1] - 6]],
      { type: "FeatureCollection", features: inset(id) }).clipExtent(b);
    const ak = fitted(d3.geoConicEqualArea().rotate([154, 0]).parallels([55, 65]), "AK", box(0.01, 0.74, 0.21, 0.99));
    const hi = fitted(d3.geoConicEqualArea().rotate([157, 0]).parallels([8, 18]), "HI", box(0.22, 0.86, 0.33, 0.99));
    const proj = (b) => (b.name === "AK" ? ak : b.name === "HI" ? hi : main)([b.lon, b.lat]);
    const svg = d3.select(el).append("svg").attr("class", "d3-map").attr("viewBox", [0, 0, W, H])
      .attr("role", "img").attr("aria-label", spec.title);
    const pm = d3.geoPath(main);
    svg.append("g").selectAll("path").data(others).join("path").attr("class", "land").attr("d", pm);
    svg.append("g").selectAll("path").data(lower).join("path").attr("class", "land").attr("d", pm);
    svg.append("g").selectAll("path").data(feats("lakes")).join("path").attr("class", "lake").attr("d", pm);
    svg.append("path").attr("class", "border").attr("d", pm(topojson.mesh(na, na.objects.subunits, (a, b) => a !== b)));
    for (const [p, box, id] of [[ak, ak.clipExtent(), "AK"], [hi, hi.clipExtent(), "HI"]]) {
      svg.append("rect").attr("class", "inset").attr("x", box[0][0]).attr("y", box[0][1])
        .attr("width", box[1][0] - box[0][0]).attr("height", box[1][1] - box[0][1]);
      svg.append("g").selectAll("path").data(inset(id)).join("path").attr("class", "land").attr("d", d3.geoPath(p));
    }
    const r = d3.scaleSqrt().domain([0, d3.max(spec.bubbles, (b) => b.n)]).range([0, 26]);
    const bub = spec.bubbles.map((b) => ({ b, xy: proj(b) })).filter((o) => o.xy);
    svg.append("g").selectAll("circle").data(bub).join("circle").attr("class", (o) => "bubble " + S.catClass(o.b.color))
      .attr("cx", (o) => o.xy[0]).attr("cy", (o) => o.xy[1]).attr("r", (o) => Math.max(2.5, r(o.b.n)));
    svg.append("g").selectAll("path").data(spec.markers).join("path").attr("class", "plant")
      .attr("d", d3.symbol(d3.symbolStar, 140)()).attr("transform", (mk) => `translate(${main([mk.lon, mk.lat])})`);
    const tt = tooltip(el);
    svg.on("pointermove", (ev) => {
      const [px, py] = d3.pointer(ev);
      const hit = bub.filter((o) => Math.hypot(o.xy[0] - px, o.xy[1] - py) <= Math.max(8, r(o.b.n)))
        .sort((a, b) => a.b.n - b.b.n)[0];
      const [hx, hy] = d3.pointer(ev, el);
      hit ? tt.show(hit.b.tip, hx, hy) : tt.hide();
    }).on("pointerleave", () => tt.hide());
    el._d3 = {};
  }

  window.SpikeD3 = { ready, scatter, map, urls: [D3], themeNeedsRedraw: false };
})();
