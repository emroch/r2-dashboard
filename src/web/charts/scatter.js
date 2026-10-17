// The `scatter` template (docs/presentation.md, "Components"): series of points,
// with optional quoted-window whiskers, plus line, band and rule layers, drawn
// with d3 from a house-schema spec (render/specs.py).
//
// Colors come entirely from CSS: each series group carries its category class
// and its marks fill with var(--mark); accents and chrome are custom properties.
// So a theme change restyles the chart with no redraw, and nothing here knows a
// hex value. The axes are fixed to the spec's domains, so hiding a series never
// rescales. Pan and zoom with d3-zoom, without taking over the page's scrolling:
// a plain wheel scrolls the page, and the chart zooms on a trackpad pinch or
// ⌘/Ctrl + wheel; with a mouse, drag pans; on touch, one finger scrolls the page
// and two pan and pinch the chart. Double-click or "Reset view" returns. Layers
// that share a `group` (the build front, its projection and band) are one legend
// entry and draw above the points. Whiskers follow ?whiskers= (state.js). The
// chart redraws when its width changes, keeping what the legend hides.
//
// x is a date axis, or a number line with `x.type: "linear"` (§vin-by-config: VIN sequence).
// y is a number line, or rows with `y.type: "rows"` (§vin-by-config): `y.rows` lists the
// rows top to bottom ({label, short, group, mark, symbol, and a value per
// filtered dimension}), and a point's y is its row's index plus a jitter (set in
// Python). Each run of rows sharing a `group` gets a heading line above it; a
// row is labelled with its mark (its `mark` category's color in its `symbol`'s
// shape), and on a wide chart its `short` label too. `filters` replace the
// legend with a chip group per dimension (house legend behavior, hidden kept
// as "dim:value"); a dimension with one value has none. Rows a filter hides
// are left out, so the chart gets shorter.
//
// With `toggles.boxes` ({min_n, unit}), Points / Boxes buttons swap the points
// for a box per week (or month, when weeks are too narrow: lib/grain.js) of
// the visible series' y values: the middle half, a median tick, whiskers to the
// furthest value within 1.5 box-lengths, and the values beyond drawn as points.
// A week with fewer than min_n values keeps its points, and an `open` series'
// points stay over the boxes. The `median` line is drawn through the boxes'
// medians. Boxes are the default, as they show the spread better; Points is
// there to drill into single orders, kept in the URL (?<chart>=points).

import { view } from "../data.js";
import { legend } from "../lib/legend.js";
import { groupOf, heading, offered, pick } from "../lib/grain.js";
import { loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { get as getState, set as setState, whiskersShown } from "../state.js";

// dimensions.yaml wheel symbols -> d3's. A diamond is a square
// turned 45° (d3's own symbolDiamond is a tall rhombus), so it keeps a 1:1 shape.
export const SYMBOLS = { circle: "symbolCircle", square: "symbolSquare",
                         diamond: "symbolSquare", "triangle-up": "symbolTriangle" };
export const ROTATE = { diamond: 45 };

// Wheel zooms only with a pinch (browsers send it as ctrl + wheel) or ⌘/Ctrl
// held, so a plain wheel scrolls the page; touch needs two fingers, so one finger
// scrolls the page; a mouse drag (primary button) pans. Pure, for the tests.
export function zoomAllowed(ev) {
  if (ev.type === "wheel") return Boolean(ev.ctrlKey || ev.metaKey);
  if (ev.type.startsWith("touch")) return (ev.touches?.length ?? 0) >= 2;
  return !ev.button;
}

// Legend entries for layers: one per group (or per ungrouped layer), in order.
export function layerEntries(layers) {
  const seen = new Map();
  for (const l of layers) {
    if (!l.color) continue;
    const name = l.group || l.name;
    if (!seen.has(name)) seen.set(name, { name, accent: l.color.slice(4) });
  }
  return [...seen.values()];
}

const slug = (v) => String(v).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// "color:Launch Green" -> "cat-color-launch-green" (render/categories.py's rule).
export function categoryClass(ref) {
  const i = ref.indexOf(":");
  // "acc:<name>" is an accent fill (render/categories.py ACCENTS): .acc-<name>;
  // "neutral" is the uncategorized grey (css/05-components.css .tr-neutral).
  if (ref === "neutral") return "tr-neutral";
  if (ref.slice(0, i) === "acc") return `acc-${ref.slice(i + 1)}`;
  return `cat-${ref.slice(0, i)}-${slug(ref.slice(i + 1))}`;
}

// A whisker: the window as a horizontal line at the order's VIN, with end caps.
export function whiskerPath(x0, x1, y, cap = 4) {
  return `M${x0},${y}H${x1}M${x0},${y - cap}V${y + cap}M${x1},${y - cap}V${y + cap}`;
}

// The candidate nearest (px, py) within `radius` pixels, or null.
// candidates: [{x, y, ...}] in pixels.
export function nearest(candidates, px, py, radius = 18) {
  let best = null, bd = radius * radius;
  for (const c of candidates) {
    const d2 = (c.x - px) ** 2 + (c.y - py) ** 2;
    if (d2 <= bd) { bd = d2; best = c; }
  }
  return best;
}

const date = (s) => new Date(s + "T12:00:00");

// A box's numbers for the values `ys`: quartiles by d3's linear rule (the same
// as pandas', so the median matches the Python's), whiskers to the furthest
// values within 1.5 box-lengths of the box. Pure, for the tests.
export function boxStats(d3, ys) {
  const v = [...ys].sort((a, b) => a - b);
  const [q1, med, q3] = [0.25, 0.5, 0.75].map((q) => d3.quantileSorted(v, q));
  const reach = 1.5 * (q3 - q1);
  const inside = v.filter((y) => y >= q1 - reach && y <= q3 + reach);
  return { n: v.length, q1, med, q3, lo: inside[0], hi: inside.at(-1), min: v[0], max: v.at(-1) };
}

// A box is at least this wide; narrower, weeks group into months.
const BOX_MIN_PX = 8;

// Under this width a chart is narrow: its y axis label sits above the axis,
// level, rather than turned beside it (which cost the plot its width), and its
// points are smaller.
export const NARROW = 600;

// The y axis label: turned beside the axis, or on a narrow chart (`m.t` left
// room for it) level above the axis's numbers.
export function yAxisLabel(svg, text, narrow, m, H) {
  const t = svg.append("text").attr("class", "axis-label").text(text);
  if (narrow) t.attr("text-anchor", "start").attr("x", 4).attr("y", 12);
  else t.attr("text-anchor", "middle").attr("transform", `translate(14,${(m.t + H - m.b) / 2}) rotate(-90)`);
  return t;
}

// The left margin a rows axis needs: its longest label at about 6.2 px a character
// (the 11px axis font), clamped so the plot keeps at least half the width.
export function rowsMargin(rows, width) {
  const longest = Math.max(0, ...rows.map((r) => String(r).length));
  return Math.round(Math.min(width * 0.5, Math.max(64, longest * 6.2 + 14)));
}

// The rows still shown, as slots top to bottom: a heading slot where the group
// changes, then a slot per row. slotOf maps a row's index to its slot. Pure.
export function rowLayout(rows, keep = () => true) {
  const slots = [], slotOf = new Map();
  let group;
  rows.forEach((r, i) => {
    if (!keep(r)) return;
    if (r.group !== undefined && r.group !== group) {
      group = r.group;
      slots.push({ heading: group });
    }
    slotOf.set(i, slots.length);
    slots.push({ row: r });
  });
  return { slots, slotOf };
}

export async function mount(el) {
  const [d3, data] = await Promise.all([loadD3(), view()]);
  const spec = data.components[el.dataset.chart];
  if (!spec) throw new Error(`no spec for ${el.dataset.chart} in r2_view.json`);
  let h = draw(d3, el, spec);
  // Redraw at the new width (not a stretched copy), keeping the legend's state.
  const plotEl = el.querySelector(".chart-plot");
  let width = plotEl.clientWidth, timer = null;
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      if (Math.abs(plotEl.clientWidth - width) < 2) return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        width = plotEl.clientWidth;
        h = draw(d3, el, spec, { hidden: (el.r2sc || h).hidden() });
      }, 150);
    }).observe(plotEl);
  }
}

// Draw `spec` into the mount `el`. Returns a handle for tests: zoomTo(k) zooms
// like the wheel does (about the plot's center), panBy(dx, dy) drags, redraw()
// re-places everything at the current view, reset() returns to the full view.
export function draw(d3, el, given, { hidden: startHidden = new Set() } = {}) {
  const plotEl = el.querySelector(".chart-plot");
  plotEl.replaceChildren();
  const W = Math.max(320, plotEl.clientWidth || 0);   // 0 before layout (and in tests)
  const filters = given.filters || null;
  // Rows: the filters' survivors, laid out in slots, each point moved to its
  // row's slot (keeping its jitter) or dropped with its row.
  let spec = given, layout = null;
  if (given.y.type === "rows") {
    const keep = (r) => !filters || filters.every((f) => !startHidden.has(`${f.dim}:${r[f.dim]}`));
    layout = rowLayout(given.y.rows, keep);
    spec = { ...given,
      y: { ...given.y, domain: [-0.6, layout.slots.length - 0.4] },
      series: given.series.map((s) => ({ ...s, points: s.points.flatMap((p) => {
        const i = Math.round(p.y), slot = layout.slotOf.get(i);
        return slot === undefined ? [] : [{ ...p, y: slot + p.y - i }];
      }) })) };
  }
  const rows = layout ? layout.slots : null;
  // A wide chart labels each row with its short label beside its mark.
  const rowText = Boolean(rows) && W >= NARROW;
  const narrow = W < NARROW && !rows;
  const m = { t: narrow ? 30 : 24, r: 16, b: 52,
              l: !rows ? (narrow ? 40 : 64) : rowText ? rowsMargin(given.y.rows.map((r) => r.short), W) + 18 : 30 };
  // Rows get a fixed pitch, so a long list grows the chart instead of cramming
  // it, and a filtered one shrinks.
  const H = rows ? Math.max(160, rows.length * 20 + m.t + m.b) : (W < 600 ? 420 : 560);
  const linearX = spec.x.type === "linear";
  const xv = linearX ? (v) => v : date;
  const x0 = (linearX ? d3.scaleLinear() : d3.scaleUtc()).domain(spec.x.domain.map(xv)).range([m.l, W - m.r]);
  // Rows run top to bottom, so row 0 is at the top of the plot.
  const y0 = d3.scaleLinear().domain(spec.y.domain).range(rows ? [m.t, H - m.b] : [H - m.b, m.t]);
  let x = x0, y = y0;

  const svg = d3.select(plotEl).append("svg").attr("class", "chart-svg")
    .attr("viewBox", [0, 0, W, H]).attr("aria-hidden", "true");
  const clip = `${el.dataset.chart}-clip`;
  svg.append("clipPath").attr("id", clip).append("rect")
    .attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b);
  // Gridlines are axes of their own (full-length ticks, no labels), so d3 updates
  // them in place on every redraw. Cloning the tick lines instead re-cloned the
  // previous clones each time and doubled them per zoom event, which hung the page.
  const gridX = svg.append("g").attr("class", "grid").attr("transform", `translate(0,${H - m.b})`);
  const gridY = svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`);
  const gx = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`);
  const gy = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
  // Rows' labels: a heading line per group, across the chart (no points share
  // its slot), and per row its mark, with its short label when there's room.
  const rowG = svg.append("g").attr("class", "rows-axis");
  if (rows && !rows.length) {
    svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle").attr("x", (m.l + W - m.r) / 2)
      .attr("y", (m.t + H - m.b) / 2).text("No configurations match these filters.");
  }
  function placeRows(inView) {
    const items = rowG.selectAll("g.slot").data(inView, (i) => i).join((e) => {
      const g = e.append("g").attr("class", (i) => (rows[i].heading ? "slot slot-head" : "slot"));
      g.filter((i) => rows[i].heading).append("text").attr("class", "row-head").attr("x", 4).attr("dy", "0.35em")
        .text((i) => rows[i].heading);
      const r = g.filter((i) => rows[i].row);
      if (rowText) {
        r.append("text").attr("class", "row-label").attr("text-anchor", "end").attr("x", m.l - 20).attr("dy", "0.35em")
          .text((i) => rows[i].row.short);
      }
      r.append("g").attr("class", (i) => `${categoryClass(rows[i].row.mark)} pt-true`).append("path").attr("class", "pt")
        .attr("d", (i) => d3.symbol(d3[SYMBOLS[rows[i].row.symbol] || "symbolCircle"], ROTATE[rows[i].row.symbol] ? 48 : 60)())
        .attr("transform", (i) => `translate(${m.l - 10},0)${ROTATE[rows[i].row.symbol] ? ` rotate(${ROTATE[rows[i].row.symbol]})` : ""}`);
      return g;
    });
    items.attr("transform", (i) => `translate(0,${y(i)})`);
  }
  svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
    .attr("x", (m.l + W - m.r) / 2).attr("y", H - 10).text(spec.x.label);
  if (!rows) yAxisLabel(svg, spec.y.label, narrow, m, H);
  const plot = svg.append("g").attr("clip-path", `url(#${clip})`);
  // Points first, then the layers above them, so the build front stays visible.
  const whiskG = plot.append("g"), dotG = plot.append("g"), layerG = plot.append("g");
  const layerName = (l) => l.group || l.name;

  const accent = (l) => `var(--${l.color.slice(4)})`;
  const bands = spec.layers.filter((l) => l.type === "band");
  const lines = spec.layers.filter((l) => l.type === "line");
  const rules = spec.layers.filter((l) => l.type === "rule");
  const bandSel = layerG.selectAll("path.band").data(bands).join("path")
    .attr("class", "band").attr("data-name", layerName).style("fill", accent);
  const lineSel = layerG.selectAll("g.line").data(lines).join("g")
    .attr("class", "line").attr("data-name", layerName);
  lineSel.append("path").attr("fill", "none").style("stroke", accent)
    .attr("stroke-width", (l) => (l.dash ? 2.5 : 3)).attr("stroke-dasharray", (l) => (l.dash ? "6,4" : null));
  lineSel.filter((l) => !l.dash).selectAll("circle").data((l) => l.points.map((pt) => ({ pt, l })))
    .join("circle").attr("r", 3.5).style("fill", (o) => accent(o.l));
  const ruleSel = layerG.selectAll("g.rule").data(rules).join("g").attr("class", "rule");
  ruleSel.append("line"); ruleSel.append("text").text((l) => l.label);

  const series = spec.series.map((s) => ({ s, cls: categoryClass(s.color) }));
  const whisk = whiskG.selectAll("g").data(series).join("g")
    .attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
  whisk.selectAll("path").data((o) => o.s.points.filter((p) => p.lo)).join("path").attr("class", "whisker");
  // A series with `open` draws hollow points (§order-to-delivery: a delivery still scheduled);
  // one with `true`, its category's true color, outlined (the configuration scatters' paints).
  const dots = dotG.selectAll("g").data(series).join("g")
    .attr("class", (o) => o.cls + (o.s.open ? " pt-open" : "") + (o.s.true ? " pt-true" : ""))
    .attr("data-name", (o) => o.s.name);
  const turn = (d) => (ROTATE[d.o.s.symbol] ? ` rotate(${ROTATE[d.o.s.symbol]})` : "");
  dots.selectAll("path").data((o) => o.s.points.map((p) => ({ p, o }))).join("path").attr("class", "pt")
    .attr("d", (d) => d3.symbol(d3[SYMBOLS[d.o.s.symbol] || "symbolCircle"],
      (ROTATE[d.o.s.symbol] ? 64 : 80) * (W < NARROW ? 0.6 : 1))());

  let hidden = new Set(startHidden), showWhiskers = whiskersShown();
  // Hidden: by its legend entry, or (a series with `parts`) by a filter on its
  // paint or wheels.
  const partsOf = new Map(spec.series.map((s) => [s.name, s.parts]));
  const off = (name) => hidden.has(name) || Boolean(filters && partsOf.get(name)
    && filters.some((f) => hidden.has(`${f.dim}:${partsOf.get(name)[f.dim]}`)));
  // A point with its own category (`cat`, filtered by `point_filter`) hides by
  // it, kept in `hidden` as the category ref ("color:Midnight"); one with none
  // (an unreported paint) hides once any is filtered, so "Midnight alone" is.
  const catRefs = new Set((spec.point_filter?.values || []).map((v) => v.ref));
  const catFiltered = () => [...hidden].some((k) => catRefs.has(k));
  const pointOff = (p) => (p.cat ? hidden.has(p.cat) : catFiltered());

  // Boxes (toggles.boxes): the grain that fits, and whether they're showing.
  const boxSpec = spec.toggles?.boxes;
  const boxG = plot.insert("g", () => dotG.node())
    .attr("class", spec.series.length ? categoryClass(spec.series[0].color) : null);
  let boxView = Boolean(boxSpec) && getState(el.dataset.chart) !== "points", boxGrain = "week", boxes = [], inBox = new Set();
  if (boxSpec) {
    const [lo, hi] = spec.x.domain.map((v) => new Date(`${v}T00:00:00Z`));
    boxGrain = pick(lo, hi, W - m.l - m.r, offered(lo, hi), BOX_MIN_PX);
  }
  // The boxes of the visible series, by group, and the points still drawn over
  // them: a small group's, those beyond the whiskers, and an open series'.
  function computeBoxes() {
    const by = new Map();
    inBox = new Set();
    for (const o of series) {
      if (off(o.s.name)) continue;
      for (const p of o.s.points) {
        if (pointOff(p)) continue;
        const g = groupOf(date(p.x), boxGrain), wk = groupOf(date(p.x), "week").start;
        if (!by.has(g.key)) by.set(g.key, { ...g, first: wk, last: wk, pts: [] });
        const b = by.get(g.key);
        if (wk < b.first) b.first = wk;
        if (wk > b.last) b.last = wk;
        b.pts.push({ p, open: o.s.open });
      }
    }
    const r = (v) => Math.round(v);
    boxes = [...by.values()].sort((a, b) => a.start - b.start).flatMap((b) => {
      if (b.pts.length < boxSpec.min_n) {
        for (const q of b.pts) inBox.add(q.p);
        return [];
      }
      const st = boxStats(d3, b.pts.map((q) => q.p.y));
      for (const q of b.pts) if (q.open || q.p.y < st.lo || q.p.y > st.hi) inBox.add(q.p);
      const u = boxSpec.unit ? ` ${boxSpec.unit}` : "";
      return [{ ...b, st, mid: new Date((b.start.getTime() + b.end.getTime()) / 2),
        tip: [heading(boxGrain, b.first, b.last), `${st.n} orders`, `Median: ${r(st.med)}${u}`,
              `Middle half: ${r(st.q1)}–${r(st.q3)}${u}`, `Range: ${r(st.min)}–${r(st.max)}${u}`] }];
    });
  }
  if (boxSpec) computeBoxes();
  // A line's points in pixels-to-be: as given, or for the median line in box
  // view, the boxes' medians.
  // With some categories filtered out, the median follows what's left (the
  // boxes' medians) in either view: the weekly median over every order would
  // describe points that aren't there.
  const throughBoxes = (l) => l.median && (boxView || catFiltered());
  const linePts = (l) => (throughBoxes(l) ? boxes.map((b) => ({ x: b.mid, y: b.st.med, tip: b.tip }))
    : l.points.map((pt, i) => ({ x: xv(pt[0]), y: pt[1], tip: l.tips?.[i] })));
  function placeBoxes() {
    boxG.style("display", boxView ? null : "none");
    if (!boxView) return;
    const g = boxG.selectAll("g.box").data(boxes).join((e) => {
      const n = e.append("g").attr("class", "box");
      n.append("path").attr("class", "box-whisk");
      n.append("rect").attr("class", "box-iqr");
      n.append("line").attr("class", "box-med");
      return n;
    });
    g.each(function (b) {
      const x0 = x(b.start), x1 = x(b.end), pad = Math.max(1, (x1 - x0) * 0.15);
      const l = x0 + pad, rr = x1 - pad, c = (x0 + x1) / 2, cap = (rr - l) / 4;
      const n = d3.select(this);
      n.select("rect").attr("x", l).attr("width", Math.max(1, rr - l))
        .attr("y", y(b.st.q3)).attr("height", Math.max(1, y(b.st.q1) - y(b.st.q3)));
      n.select("line").attr("x1", l).attr("x2", rr).attr("y1", y(b.st.med)).attr("y2", y(b.st.med));
      n.select("path").attr("d", `M${c},${y(b.st.q3)}V${y(b.st.hi)}M${c - cap},${y(b.st.hi)}H${c + cap}`
        + `M${c},${y(b.st.q1)}V${y(b.st.lo)}M${c - cap},${y(b.st.lo)}H${c + cap}`);
    });
  }
  function place() {
    const xt = Math.max(3, W / 120);
    gridX.call(d3.axisBottom(x).ticks(xt).tickSize(-(H - m.t - m.b)).tickFormat(""));
    gx.call(linearX ? d3.axisBottom(x).ticks(xt, "~s") : d3.axisBottom(x).ticks(xt));
    if (rows) {
      // A row's label and gridline stay put while it's in view; rows panned out of
      // the plot drop theirs rather than piling up at its edge.
      const [lo, hi] = y.domain();
      const inView = d3.range(rows.length).filter((i) => i >= Math.min(lo, hi) && i <= Math.max(lo, hi));
      gridY.call(d3.axisLeft(y).tickValues(inView.filter((i) => rows[i].row)).tickSize(-(W - m.l - m.r)).tickFormat(""));
      placeRows(inView);
    } else {
      gridY.call(d3.axisLeft(y).ticks(8).tickSize(-(W - m.l - m.r)).tickFormat(""));
      gy.call(d3.axisLeft(y).ticks(8, "~s"));
    }
    bandSel.attr("d", (l) => d3.area().x((d) => x(xv(d[0]))).y0((d) => y(d[1])).y1((d) => y(d[2]))(l.points));
    // `curve` smooths a line through its points (monotone, so it never
    // overshoots a week's value); the rest join them straight.
    lineSel.select("path").attr("d", (l) => d3.line().curve(l.curve ? d3.curveMonotoneX : d3.curveLinear)
      .x((d) => x(d.x)).y((d) => y(d.y))(linePts(l)));
    // In box view the median's points are the boxes' median ticks.
    lineSel.selectAll("circle").attr("cx", (o) => x(xv(o.pt[0]))).attr("cy", (o) => y(o.pt[1]))
      .style("display", (o) => (throughBoxes(o.l) ? "none" : null));
    ruleSel.select("line").attr("x1", (l) => x(xv(l.value))).attr("x2", (l) => x(xv(l.value)))
      .attr("y1", m.t).attr("y2", H - m.b);
    ruleSel.select("text").attr("x", (l) => x(xv(l.value)) + 4).attr("y", m.t + 10);
    // A point with its own category (`cat`: §order-to-delivery's paint) wears
    // its color in the points view; in the box view it takes its series' color
    // again, so the boxes and the points left over them read as one.
    dots.selectAll("path.pt").attr("transform", (d) => `translate(${x(xv(d.p.x))},${y(d.p.y)})${turn(d)}`)
      .attr("class", (d) => (d.p.cat && !boxView ? `pt pt-cat ${categoryClass(d.p.cat)}` : "pt"))
      .style("display", (d) => (pointOff(d.p) || (boxView && !inBox.has(d.p)) ? "none" : null));
    placeBoxes();
    whiskG.style("display", showWhiskers ? null : "none");
    whisk.selectAll("path.whisker").attr("d", (p) => whiskerPath(x(xv(p.lo)), x(xv(p.hi)), y(p.y)));
  }
  function visibility() {
    svg.selectAll("[data-name]").style("display", function () { return off(this.dataset.name) ? "none" : null; });
    // Boxes summarize what's visible, so hiding a series redraws them.
    if (boxSpec) { computeBoxes(); place(); }
  }
  place();
  visibility();

  // Legend: every series, then one entry per layer group; or with `filters`, a
  // chip group per dimension with more than one value, then the layer groups'
  // entries as one more, "Overlays" (§build-front's build front). A filter change on rows redraws the chart whole
  // (its rows and height change), and focus returns to the chip; on points it
  // hides their series. On a phone the chips (44px each) fold into a Filters
  // disclosure, closed until opened, that says how many values are hidden.
  const legendEl = el.querySelector(".chart-legend");
  if (filters) {
    const doc = el.ownerDocument;
    const choosable = filters.filter((f) => f.values.length > 1);
    const sum = Object.assign(doc.createElement("summary"), { className: "fl-sum" });
    const layers = layerEntries(spec.layers);
    const count = () => {
      const n = choosable.reduce((a, f) => a + f.values.filter((v) => hidden.has(`${f.dim}:${v.value}`)).length, 0)
        + layers.filter((l) => hidden.has(l.name)).length;
      sum.textContent = n ? `Filters (${n} hidden)` : "Filters (all shown)";
    };
    count();
    const box = Object.assign(doc.createElement("details"), { className: "fl-box" });
    box.append(sum);
    const phone = doc.defaultView?.matchMedia?.("(width < 768px)").matches ?? false;
    box.open = !phone || Boolean(el.r2filtersOpen);
    box.addEventListener("toggle", () => { if (phone) el.r2filtersOpen = box.open; });
    legendEl.replaceChildren(box);
    // A labelled row of chips in the disclosure.
    const group = (dim, label) => {
      const wrap = Object.assign(doc.createElement("div"), { className: "fl-group" });
      wrap.dataset.dim = dim;
      const name = Object.assign(doc.createElement("span"), { className: "fl-label", textContent: label });
      const chips = Object.assign(doc.createElement("div"), { className: "fl-chips" });
      chips.setAttribute("role", "group");
      chips.setAttribute("aria-label", label);
      wrap.append(name, chips);
      box.append(wrap);
      return chips;
    };
    for (const f of choosable) {
      const chips = group(f.dim, f.label);
      const valueOf = new Map(f.values.map((v) => [v.label, v.value]));
      const cls = (v) => (v.symbol ? `tr-neutral swatch-sym sym-${v.symbol}` : categoryClass(`${f.dim}:${v.value}`));
      legend(chips, f.values.map((v) => ({ name: v.label, cls: cls(v) })), (hs) => {
        const next = new Set([...hidden].filter((k) => !k.startsWith(`${f.dim}:`)));
        for (const label of hs) next.add(`${f.dim}:${valueOf.get(label)}`);
        if (!rows) {
          hidden = next;
          count();
          visibility();
          return;
        }
        const focused = el.ownerDocument.activeElement?.textContent;
        draw(d3, el, given, { hidden: next });
        [...el.querySelectorAll(`.fl-group[data-dim="${f.dim}"] .lg-item`)]
          .find((b) => b.textContent === focused)?.focus();
      }, new Set(f.values.filter((v) => hidden.has(`${f.dim}:${v.value}`)).map((v) => v.label)));
    }
    if (layers.length) {
      const names = new Set(layers.map((l) => l.name));
      legend(group("layers", "Overlays"), layers, (hs) => {
        hidden = new Set([...[...hidden].filter((k) => !names.has(k)), ...hs]);
        count();
        visibility();
      }, new Set([...hidden].filter((k) => names.has(k))));
    }
  } else {
    // Beside point filters, the legend is a labelled row too (spec.legend:
    // "Orders"), so its chips line up with the filters' under one label column.
    let host = legendEl;
    if (spec.point_filter) {
      const doc = el.ownerDocument;
      legendEl.replaceChildren();
      const wrap = Object.assign(doc.createElement("div"), { className: "fl-group" });
      wrap.dataset.dim = "series";
      host = Object.assign(doc.createElement("div"), { className: "fl-chips" });
      host.setAttribute("role", "group");
      host.setAttribute("aria-label", spec.legend || "Series");
      wrap.append(Object.assign(doc.createElement("span"), { className: "fl-label", textContent: spec.legend || "Series" }), host);
      legendEl.append(wrap);
    }
    // The point filters' own entries live in `hidden` too; the legend keeps them.
    const own = new Set([...series.map((o) => o.s.name), ...layerEntries(spec.layers).map((l) => l.name)]);
    legend(host,
      [...series.map((o) => ({ name: o.s.name, cls: o.s.open ? `${o.cls} swatch-open` : o.cls })),
       ...layerEntries(spec.layers)],
      (h) => { hidden = new Set([...[...hidden].filter((k) => !own.has(k)), ...h]); visibility(); },
      new Set([...hidden].filter((k) => own.has(k))));
  }
  // Filters on the points' own categories (`point_filter`: §order-to-delivery's
  // paints), under the legend, in the phone's Filters disclosure as the series
  // filters are. A change hides the points in place and recomputes the boxes.
  if (spec.point_filter) {
    const doc = el.ownerDocument, f = spec.point_filter;
    const refs = new Set(f.values.map((v) => v.ref));
    const sum = Object.assign(doc.createElement("summary"), { className: "fl-sum" });
    const count = () => {
      const n = [...hidden].filter((k) => refs.has(k)).length;
      sum.textContent = n ? `Filters (${n} hidden)` : "Filters (all shown)";
    };
    count();
    const box = Object.assign(doc.createElement("details"), { className: "fl-box" });
    const phone = doc.defaultView?.matchMedia?.("(width < 768px)").matches ?? false;
    box.open = !phone || Boolean(el.r2filtersOpen);
    box.addEventListener("toggle", () => { if (phone) el.r2filtersOpen = box.open; });
    const wrap = Object.assign(doc.createElement("div"), { className: "fl-group" });
    wrap.dataset.dim = "cat";
    const chips = Object.assign(doc.createElement("div"), { className: "fl-chips" });
    chips.setAttribute("role", "group");
    chips.setAttribute("aria-label", f.label);
    wrap.append(Object.assign(doc.createElement("span"), { className: "fl-label", textContent: f.label }), chips);
    box.append(sum, wrap);
    legendEl.append(box);
    const refOf = new Map(f.values.map((v) => [v.label, v.ref]));
    legend(chips, f.values.map((v) => ({ name: v.label, cls: categoryClass(v.ref) })), (hs) => {
      hidden = new Set([...[...hidden].filter((k) => !refs.has(k)), ...[...hs].map((l) => refOf.get(l))]);
      count();
      if (boxSpec) computeBoxes();
      place();
      tip.hide();
    }, new Set(f.values.filter((v) => hidden.has(v.ref)).map((v) => v.label)));
  }

  // Controls: the whisker toggle (kept in the URL), when the spec has whiskers,
  // and Reset view.
  const controls = el.ownerDocument.createElement("div");
  controls.className = "chart-controls ts-controls";
  if (boxSpec) {
    const g = Object.assign(el.ownerDocument.createElement("div"), { className: "chart-switch seg" });
    g.setAttribute("role", "group");
    g.setAttribute("aria-label", "Show");
    const views = [["points", "Points"], ["boxes", "Boxes"]].map(([v, label]) => {
      const b = Object.assign(el.ownerDocument.createElement("button"), { type: "button", className: "lg-item", textContent: label });
      b.dataset.view = v;
      b.addEventListener("click", () => {
        if ((v === "boxes") === boxView) return;
        boxView = v === "boxes";
        setState(el.dataset.chart, v === "boxes" ? null : v);
        sync();
        place();
        tip.hide();
      });
      g.append(b);
      return b;
    });
    const sync = () => views.forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.view === "boxes") === boxView)));
    sync();
    controls.append(g);
  }
  if (spec.toggles?.whiskers) {
    const wb = Object.assign(el.ownerDocument.createElement("button"), { type: "button", className: "lg-item" });
    const syncW = () => { wb.textContent = showWhiskers ? "Hide whiskers" : "Show whiskers"; };
    wb.addEventListener("click", () => { showWhiskers = !showWhiskers; setState("whiskers", showWhiskers ? null : "0"); syncW(); place(); });
    syncW();
    controls.append(wb);
  }
  const reset = Object.assign(el.ownerDocument.createElement("button"), { type: "button", className: "lg-item", textContent: "Reset view" });
  controls.append(reset);
  plotEl.prepend(controls);

  // Tooltips: the nearest visible point, or week of the build front.
  const tip = tooltip(plotEl);
  svg.on("pointermove", (ev) => {
    const [px, py] = d3.pointer(ev);
    const cands = [];
    for (const o of series) {
      if (off(o.s.name)) continue;
      for (const p of o.s.points) if (!pointOff(p) && (!boxView || inBox.has(p))) cands.push({ x: x(xv(p.x)), y: y(p.y), tip: p.tip });
    }
    for (const l of lines) {
      if (!hidden.has(layerName(l))) for (const q of linePts(l)) if (q.tip) cands.push({ x: x(q.x), y: y(q.y), tip: q.tip });
    }
    // Else the box under the pointer, whiskers included.
    const hit = nearest(cands, px, py) || (boxView ? boxes.find((b) => px >= x(b.start) && px < x(b.end)
      && py >= y(b.st.hi) - 4 && py <= y(b.st.lo) + 4) : null);
    const [hx, hy] = d3.pointer(ev, plotEl);
    if (hit) tip.show(hit.tip, hx, hy); else tip.hide();
  }).on("pointerleave", () => tip.hide());

  const zoom = d3.zoom().scaleExtent([1, 40]).filter(zoomAllowed)
    .extent([[m.l, m.t], [W - m.r, H - m.b]])
    .translateExtent([[m.l, m.t], [W - m.r, H - m.b]])
    .on("zoom", (ev) => { x = ev.transform.rescaleX(x0); y = ev.transform.rescaleY(y0); place(); tip.hide(); });
  const home = () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
  svg.call(zoom).on("dblclick.zoom", home);
  reset.addEventListener("click", home);
  const handle = {
    svg: svg.node(),
    zoomTo: (k) => svg.call(zoom.scaleTo, k),
    panBy: (dx, dy) => svg.call(zoom.translateBy, dx, dy),
    redraw: place,                                 // what a whisker toggle does
    hidden: () => new Set(hidden),
    reset: () => svg.call(zoom.transform, d3.zoomIdentity),
    boxes: () => (boxView ? boxes : null),
  };
  // The latest drawing, for a resize after a filter redraw.
  el.r2sc = handle;
  return handle;
}
