// Spike (#107): Observable Plot + d3. SVG, so the chrome is CSS-colorable; the
// house legend and tooltips (Plot's pointer + tip) cover the interactions.
(function () {
  "use strict";
  const S = window.Spike;
  const D3 = "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js";
  const PLOT = "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/dist/plot.umd.min.js";
  const TOPO = "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js";
  const STATES = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json";
  const WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
  let libs = null;
  const ready = () => libs || (libs = S.load(D3).then(() => S.load(PLOT)));

  function scatter(el, spec, hidden) {
    const c = S.chrome();
    const date = (s) => new Date(s + "T12:00:00");
    const vis = spec.series.filter((s) => !hidden.has(s.name));
    const pts = vis.flatMap((s) => s.points.map((p) => ({ ...p, s, fill: S.color(s.color) })));
    const marks = [];
    for (const l of spec.layers) {
      if (l.type === "band") marks.push(Plot.areaY(l.points, { x: (d) => date(d[0]), y1: (d) => d[1], y2: (d) => d[2], fill: S.color(l.color), curve: "linear" }));
      if (l.type === "line") marks.push(Plot.line(l.points, { x: (d) => date(d[0]), y: (d) => d[1], stroke: S.color(l.color), strokeWidth: l.dash ? 2.5 : 3, strokeDasharray: l.dash ? "6,4" : null }));
      if (l.type === "rule") marks.push(Plot.ruleX([date(l.value)], { stroke: c.muted, strokeDasharray: "4,3" }), Plot.text([date(l.value)], { x: (d) => d, frameAnchor: "top", dy: -6, text: () => l.label, fill: c.muted }));
    }
    if (S.whiskersOn()) {
      const w = pts.filter((p) => p.lo);
      marks.push(Plot.link(w, { x1: (p) => date(p.lo), x2: (p) => date(p.hi), y1: "y", y2: "y", stroke: "fill", strokeOpacity: 0.55, strokeWidth: 1.4 }));
    }
    marks.push(Plot.dot(pts, { x: (p) => date(p.x), y: "y", fill: "fill", symbol: (p) => S.symbols.plot[p.s.symbol], r: 5, stroke: c.edge, strokeWidth: 0.8 }));
    marks.push(Plot.tip(pts, Plot.pointer({ x: (p) => date(p.x), y: "y", title: (p) => p.tip.join("\n") })));
    el.replaceChildren(Plot.plot({
      width: el.clientWidth, height: 560, marginLeft: 60, style: { color: c.text, background: "transparent" },
      x: { type: "utc", label: spec.x.label, grid: true }, y: { label: spec.y.label, grid: true },
      symbol: { type: "identity" }, marks,
    }));
  }

  let geo = null;
  async function map(el, spec) {
    if (!geo) {
      await S.load(TOPO);
      const [us, world] = await Promise.all([fetch(STATES).then((r) => r.json()), fetch(WORLD).then((r) => r.json())]);
      const countries = topojson.feature(world, world.objects.countries).features
        .filter((f) => ["124", "484", "840"].includes(f.id));        // Canada, Mexico, US
      geo = { countries, states: topojson.mesh(us, us.objects.states, (a, b) => a !== b) };
    }
    const c = S.chrome();
    const b = spec.bubbles;
    el.replaceChildren(Plot.plot({
      width: el.clientWidth, height: Math.round(el.clientWidth * 0.62),
      projection: { type: "conic-equal-area", rotate: [96, 0], parallels: [29.5, 45.5],
                    domain: { type: "MultiPoint", coordinates: [[-125, 24], [-66, 24], [-60, 52], [-128, 52]] } },
      style: { color: c.text, background: "transparent" }, r: { range: [0, 34] },
      marks: [
        Plot.geo(geo.countries, { fill: c.grid, fillOpacity: 0.35, stroke: c.muted, strokeWidth: 0.6 }),
        Plot.geo(geo.states, { stroke: c.muted, strokeOpacity: 0.6, strokeWidth: 0.5 }),
        Plot.dot(b, { x: "lon", y: "lat", r: "n", fill: (d) => S.color(d.color), fillOpacity: 0.75, stroke: c.edge, strokeWidth: 0.5 }),
        Plot.dot(spec.markers, { x: "lon", y: "lat", symbol: "star", r: 7, fill: c.text }),
        Plot.tip(b, Plot.pointer({ x: "lon", y: "lat", title: (d) => d.tip.join("\n") })),
      ],
    }));
  }

  window.SpikePlot = { ready, scatter, map, urls: [D3, PLOT] };
})();
