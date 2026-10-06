// Spike (#107): ECharts 6, canvas. Whiskers and the band are custom series; the
// map needs geometry registered from the same public TopoJSON Plot uses.
(function () {
  "use strict";
  const S = window.Spike;
  const EC = "https://cdn.jsdelivr.net/npm/echarts@6.1.0/dist/echarts.min.js";
  const TOPO = "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js";
  const STATES = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json";
  const WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
  let libs = null;
  const ready = () => libs || (libs = S.load(EC));
  const charts = new Map();
  function inst(el) {
    let ch = charts.get(el);
    if (!ch) { ch = echarts.init(el, null, { renderer: "canvas" }); charts.set(el, ch); new ResizeObserver(() => ch.resize()).observe(el); }
    return ch;
  }
  const t = (s) => new Date(s + "T12:00:00").getTime();
  const tip = (c) => ({ trigger: "item", backgroundColor: c.card, borderColor: c.grid, textStyle: { color: c.text },
                         formatter: (p) => (p.data && p.data.tip ? p.data.tip.join("<br>") : p.name) });

  function scatter(el, spec, hidden) {
    const c = S.chrome();
    const axis = (o) => ({ ...o, nameLocation: "middle", nameGap: 34, axisLine: { lineStyle: { color: c.muted } },
                           axisLabel: { color: c.muted }, nameTextStyle: { color: c.text }, splitLine: { lineStyle: { color: c.grid } } });
    const series = [];
    for (const l of spec.layers) {
      if (l.type === "band") series.push({ type: "custom", silent: true, z: 1, data: [0],
        renderItem: (params, api) => ({ type: "polygon", style: { fill: S.color(l.color) },
          shape: { points: [...l.points.map((d) => api.coord([t(d[0]), d[1]])), ...l.points.slice().reverse().map((d) => api.coord([t(d[0]), d[2]]))] } }) });
      if (l.type === "line") series.push({ type: "line", silent: true, z: 2, showSymbol: !l.dash, symbolSize: 6,
        data: l.points.map((d) => [t(d[0]), d[1]]), lineStyle: { color: S.color(l.color), width: l.dash ? 2.5 : 3, type: l.dash ? "dashed" : "solid" },
        itemStyle: { color: S.color(l.color) } });
      if (l.type === "rule") series.push({ type: "line", data: [], markLine: { silent: true, symbol: "none", label: { formatter: l.label, color: c.muted },
        lineStyle: { color: c.muted, type: "dashed" }, data: [{ xAxis: t(l.value) }] } });
    }
    for (const s of spec.series) {
      if (hidden.has(s.name)) continue;
      const fill = S.color(s.color);
      if (S.whiskersOn()) series.push({ type: "custom", silent: true, z: 3, data: s.points.filter((p) => p.lo).map((p) => [t(p.lo), t(p.hi), p.y]),
        renderItem: (params, api) => {
          const a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
          const cap = 4;
          return { type: "group", children: [
            { type: "line", shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: { stroke: fill, opacity: 0.55, lineWidth: 1.4 } },
            { type: "line", shape: { x1: a[0], y1: a[1] - cap, x2: a[0], y2: a[1] + cap }, style: { stroke: fill, opacity: 0.55 } },
            { type: "line", shape: { x1: b[0], y1: b[1] - cap, x2: b[0], y2: b[1] + cap }, style: { stroke: fill, opacity: 0.55 } }] };
        } });
      series.push({ type: "scatter", name: s.name, z: 4, symbol: S.symbols.echarts[s.symbol], symbolSize: 10,
        itemStyle: { color: fill, borderColor: c.edge, borderWidth: 0.8 },
        data: s.points.map((p) => ({ value: [t(p.x), p.y], tip: p.tip })) });
    }
    inst(el).setOption({ animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      grid: { left: 70, right: 20, top: 30, bottom: 50 }, tooltip: tip(c),
      xAxis: axis({ type: "time", name: spec.x.label }), yAxis: axis({ type: "value", name: spec.y.label, scale: true, nameGap: 50 }),
      series }, { notMerge: true });
  }

  let registered = false;
  async function map(el, spec) {
    if (!registered) {
      await S.load(TOPO);
      const [us, world] = await Promise.all([fetch(STATES).then((r) => r.json()), fetch(WORLD).then((r) => r.json())]);
      const countries = topojson.feature(world, world.objects.countries).features.filter((f) => ["124", "484"].includes(f.id));
      const states = topojson.feature(us, us.objects.states).features;
      echarts.registerMap("na", { type: "FeatureCollection", features: [...countries, ...states].map((f, i) => ({ ...f, properties: { name: f.properties.name || "f" + i } })) });
      registered = true;
    }
    const c = S.chrome();
    const max = Math.max(...spec.bubbles.map((b) => b.n));
    inst(el).setOption({ tooltip: tip(c),
      geo: { map: "na", roam: false, boundingCoords: [[-128, 53], [-62, 23]], aspectScale: 0.78, silent: true,
             itemStyle: { areaColor: c.grid, borderColor: c.muted, borderWidth: 0.5, opacity: 0.6 } },
      series: [
        { type: "scatter", coordinateSystem: "geo", data: spec.bubbles.map((b) => ({ name: b.name, value: [b.lon, b.lat, b.n], tip: b.tip,
            itemStyle: { color: S.color(b.color), opacity: 0.75, borderColor: c.edge, borderWidth: 0.5 } })),
          symbolSize: (v) => 2 + 34 * Math.sqrt(v[2] / max) },
        { type: "scatter", coordinateSystem: "geo", symbol: "path://M50,0 61,35 98,35 68,57 79,91 50,70 21,91 32,57 2,35 39,35z", symbolSize: 14,
          itemStyle: { color: c.text }, data: spec.markers.map((m) => ({ name: m.name, value: [m.lon, m.lat] })) }] }, { notMerge: true });
  }

  window.SpikeEcharts = { ready, scatter, map, urls: [EC] };
})();
