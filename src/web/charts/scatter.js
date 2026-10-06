// The `scatter` template (docs/presentation.md, "Components"): series of points,
// with optional quoted-window whiskers, plus line, band and rule layers, drawn
// with d3 from a house-schema spec (render/specs.py).
//
// Colors come entirely from CSS: each series group carries its category class
// and its marks fill with var(--mark); accents and chrome are custom properties.
// So a theme change restyles the chart with no redraw, and nothing here knows a
// hex value. The axes are fixed to the spec's domains, so hiding a series never
// rescales. Pan and zoom with d3-zoom (wheel, pinch, drag); double-click or
// "Reset view" returns. Whiskers follow ?whiskers= (lib/../state.js).

import { view } from "../data.js";
import { legend } from "../lib/legend.js";
import { loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { set as setState, whiskersShown } from "../state.js";

// dimensions.yaml wheel symbols (Plotly's names) -> d3's.
export const SYMBOLS = { circle: "symbolCircle", square: "symbolSquare",
                         diamond: "symbolDiamond", "triangle-up": "symbolTriangle" };

const slug = (v) => String(v).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// "color:Launch Green" -> "cat-color-launch-green" (render/categories.py's rule).
export function categoryClass(ref) {
  const i = ref.indexOf(":");
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

export async function mount(el) {
  const [d3, data] = await Promise.all([loadD3(), view()]);
  const spec = data.components[el.dataset.chart];
  if (!spec) throw new Error(`no spec for ${el.dataset.chart} in r2_view.json`);
  draw(d3, el, spec);
}

function draw(d3, el, spec) {
  const plotEl = el.querySelector(".chart-plot");
  plotEl.replaceChildren();
  const W = Math.max(320, plotEl.clientWidth), H = W < 600 ? 420 : 560;
  const m = { t: 24, r: 16, b: 52, l: 64 };
  const x0 = d3.scaleUtc().domain(spec.x.domain.map(date)).range([m.l, W - m.r]);
  const y0 = d3.scaleLinear().domain(spec.y.domain).range([H - m.b, m.t]);
  let x = x0, y = y0;

  const svg = d3.select(plotEl).append("svg").attr("class", "chart-svg")
    .attr("viewBox", [0, 0, W, H]).attr("aria-hidden", "true");
  const clip = `${el.dataset.chart}-clip`;
  svg.append("clipPath").attr("id", clip).append("rect")
    .attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b);
  const gx = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`);
  const gy = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
  svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
    .attr("x", (m.l + W - m.r) / 2).attr("y", H - 10).text(spec.x.label);
  svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
    .attr("transform", `translate(14,${(m.t + H - m.b) / 2}) rotate(-90)`).text(spec.y.label);
  const plot = svg.append("g").attr("clip-path", `url(#${clip})`);
  const layerG = plot.append("g"), whiskG = plot.append("g"), dotG = plot.append("g");

  const accent = (l) => `var(--${l.color.slice(4)})`;
  const bands = spec.layers.filter((l) => l.type === "band");
  const lines = spec.layers.filter((l) => l.type === "line");
  const rules = spec.layers.filter((l) => l.type === "rule");
  const bandSel = layerG.selectAll("path.band").data(bands).join("path")
    .attr("class", "band").attr("data-name", (l) => l.name).style("fill", accent);
  const lineSel = layerG.selectAll("g.line").data(lines).join("g")
    .attr("class", "line").attr("data-name", (l) => l.name);
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
  const dots = dotG.selectAll("g").data(series).join("g")
    .attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
  dots.selectAll("path").data((o) => o.s.points.map((p) => ({ p, o }))).join("path").attr("class", "pt")
    .attr("d", (d) => d3.symbol(d3[SYMBOLS[d.o.s.symbol] || "symbolCircle"], 80)());

  let hidden = new Set(), showWhiskers = whiskersShown();
  function place() {
    gx.call(d3.axisBottom(x).ticks(Math.max(3, W / 120)))
      .call((g) => g.selectAll(".tick line").clone().attr("class", "grid").attr("y2", -(H - m.t - m.b)));
    gy.call(d3.axisLeft(y).ticks(8, "~s"))
      .call((g) => g.selectAll(".tick line").clone().attr("class", "grid").attr("x2", W - m.l - m.r));
    bandSel.attr("d", (l) => d3.area().x((d) => x(date(d[0]))).y0((d) => y(d[1])).y1((d) => y(d[2]))(l.points));
    lineSel.select("path").attr("d", (l) => d3.line().x((d) => x(date(d[0]))).y((d) => y(d[1]))(l.points));
    lineSel.selectAll("circle").attr("cx", (o) => x(date(o.pt[0]))).attr("cy", (o) => y(o.pt[1]));
    ruleSel.select("line").attr("x1", (l) => x(date(l.value))).attr("x2", (l) => x(date(l.value)))
      .attr("y1", m.t).attr("y2", H - m.b);
    ruleSel.select("text").attr("x", (l) => x(date(l.value)) + 4).attr("y", m.t + 10);
    dots.selectAll("path.pt").attr("transform", (d) => `translate(${x(date(d.p.x))},${y(d.p.y)})`);
    whiskG.style("display", showWhiskers ? null : "none");
    whisk.selectAll("path.whisker").attr("d", (p) => whiskerPath(x(date(p.lo)), x(date(p.hi)), y(p.y)));
  }
  function visibility() {
    svg.selectAll("[data-name]").style("display", function () { return hidden.has(this.dataset.name) ? "none" : null; });
  }
  place();

  // Legend: every series, then the layers that have an accent of their own.
  legend(el.querySelector(".chart-legend"),
    [...series.map((o) => ({ name: o.s.name, cls: o.cls })),
     ...spec.layers.filter((l) => l.color).map((l) => ({ name: l.name, accent: l.color.slice(4) }))],
    (h) => { hidden = h; visibility(); });

  // Controls: the whisker toggle (kept in the URL) and Reset view.
  const controls = el.ownerDocument.createElement("div");
  controls.className = "chart-controls";
  const wb = Object.assign(el.ownerDocument.createElement("button"), { type: "button", className: "lg-item" });
  const syncW = () => { wb.textContent = showWhiskers ? "Hide whiskers" : "Show whiskers"; wb.setAttribute("aria-pressed", String(showWhiskers)); };
  wb.addEventListener("click", () => { showWhiskers = !showWhiskers; setState("whiskers", showWhiskers ? null : "0"); syncW(); place(); });
  syncW();
  const reset = Object.assign(el.ownerDocument.createElement("button"), { type: "button", className: "lg-item", textContent: "Reset view" });
  controls.append(wb, reset);
  plotEl.prepend(controls);

  // Tooltips: the nearest visible point, or week of the build front.
  const tip = tooltip(plotEl);
  svg.on("pointermove", (ev) => {
    const [px, py] = d3.pointer(ev);
    const cands = [];
    for (const o of series) if (!hidden.has(o.s.name)) for (const p of o.s.points) cands.push({ x: x(date(p.x)), y: y(p.y), tip: p.tip });
    for (const l of lines) if (l.tips && !hidden.has(l.name)) l.points.forEach((pt, i) => cands.push({ x: x(date(pt[0])), y: y(pt[1]), tip: l.tips[i] }));
    const hit = nearest(cands, px, py);
    const [hx, hy] = d3.pointer(ev, plotEl);
    if (hit) tip.show(hit.tip, hx, hy); else tip.hide();
  }).on("pointerleave", () => tip.hide());

  const zoom = d3.zoom().scaleExtent([1, 40])
    .extent([[m.l, m.t], [W - m.r, H - m.b]])
    .translateExtent([[m.l, m.t], [W - m.r, H - m.b]])
    .on("zoom", (ev) => { x = ev.transform.rescaleX(x0); y = ev.transform.rescaleY(y0); place(); tip.hide(); });
  const home = () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity);
  svg.call(zoom).on("dblclick.zoom", home);
  reset.addEventListener("click", home);
}
