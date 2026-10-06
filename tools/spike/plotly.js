// Spike (#107): Plotly's geo partial bundle (scatter + scattergeo + choropleth),
// redrawn from the spec with Plotly.react on every change, so nothing is
// re-tinted by index. Its own legend is off: the house legend drives it.
(function () {
  "use strict";
  const S = window.Spike;
  const PL = "https://cdn.jsdelivr.net/npm/plotly.js-geo-dist-min@4.1.2/plotly-geo.min.js";
  let libs = null;
  const ready = () => libs || (libs = S.load(PL));
  const cfg = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["select2d", "lasso2d"] };
  const layoutBase = (c) => ({ paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: c.text },
                               showlegend: false, hoverlabel: { bgcolor: c.card, bordercolor: c.grid, font: { color: c.text } } });

  function scatter(el, spec, hidden) {
    const c = S.chrome();
    const data = [];
    const shapes = [], annotations = [];
    for (const l of spec.layers) {
      if (l.type === "band") data.push({ type: "scatter", mode: "lines", hoverinfo: "skip", fill: "toself", fillcolor: S.color(l.color), line: { width: 0 },
        x: [...l.points.map((d) => d[0]), ...l.points.slice().reverse().map((d) => d[0])],
        y: [...l.points.map((d) => d[1]), ...l.points.slice().reverse().map((d) => d[2])] });
      if (l.type === "line") data.push({ type: "scatter", mode: l.dash ? "lines" : "lines+markers", hoverinfo: "skip", x: l.points.map((d) => d[0]), y: l.points.map((d) => d[1]),
        line: { color: S.color(l.color), width: l.dash ? 2.5 : 3, dash: l.dash ? "dash" : "solid" }, marker: { color: S.color(l.color), size: 6 } });
      if (l.type === "rule") { shapes.push({ type: "line", xref: "x", yref: "paper", x0: l.value, x1: l.value, y0: 0, y1: 1, line: { color: c.muted, dash: "dash", width: 1.5 } });
        annotations.push({ x: l.value, y: 1, xref: "x", yref: "paper", text: l.label, showarrow: false, yanchor: "bottom", font: { color: c.muted, size: 10 } }); }
    }
    for (const s of spec.series) {
      if (hidden.has(s.name)) continue;
      const fill = S.color(s.color);
      if (S.whiskersOn()) {
        const x = [], y = [];
        for (const p of s.points) if (p.lo) x.push(p.lo, p.hi, null), y.push(p.y, p.y, null);
        data.push({ type: "scatter", mode: "lines", hoverinfo: "skip", x, y, opacity: 0.55, line: { color: fill, width: 1.4 } });
      }
      data.push({ type: "scatter", mode: "markers", name: s.name, x: s.points.map((p) => p.x), y: s.points.map((p) => p.y),
        text: s.points.map((p) => p.tip.join("<br>")), hovertemplate: "%{text}<extra></extra>",
        marker: { color: fill, size: 10, symbol: s.symbol, line: { color: c.edge, width: 0.8 } } });
    }
    const ax = (title, type) => ({ title: { text: title }, type, gridcolor: c.grid, linecolor: c.muted, zerolinecolor: c.grid });
    Plotly.react(el, data, { ...layoutBase(c), height: 560, margin: { l: 70, r: 20, t: 30, b: 50 }, hovermode: "closest",
      xaxis: ax(spec.x.label, "date"), yaxis: ax(spec.y.label, "linear"), shapes, annotations }, cfg);
  }

  function map(el, spec) {
    const c = S.chrome();
    const b = spec.bubbles, max = Math.max(...b.map((d) => d.n));
    Plotly.react(el, [
      { type: "scattergeo", lat: b.map((d) => d.lat), lon: b.map((d) => d.lon), text: b.map((d) => d.tip.join("<br>")), hovertemplate: "%{text}<extra></extra>",
        marker: { size: b.map((d) => d.n), sizemode: "area", sizeref: (2 * max) / 34 ** 2, sizemin: 3, color: b.map((d) => S.color(d.color)), opacity: 0.75,
                  line: { color: c.edge, width: 0.5 } } },
      { type: "scattergeo", lat: spec.markers.map((m) => m.lat), lon: spec.markers.map((m) => m.lon), text: spec.markers.map((m) => m.name),
        hovertemplate: "%{text}<extra></extra>", marker: { symbol: "star", size: 12, color: c.text } }],
      { ...layoutBase(c), height: Math.round(el.clientWidth * 0.62), margin: { l: 0, r: 0, t: 0, b: 0 }, dragmode: false,
        geo: { scope: "north america", resolution: 50, bgcolor: "rgba(0,0,0,0)", showland: true, landcolor: c.grid, showsubunits: true,
               subunitcolor: c.muted, showcountries: true, countrycolor: c.muted, showlakes: false, lataxis: { range: [23, 55] }, lonaxis: { range: [-128, -60] } } },
      cfg);
  }

  window.SpikePlotly = { ready, scatter, map, urls: [PL] };
})();
