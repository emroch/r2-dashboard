// The `timeseries` template (docs/presentation.md, "Components"): weekly columns,
// stacked by series, and lines over dates, drawn with d3 from a house-schema spec
// (render/specs.py).
//
// As in scatter.js, colors come entirely from CSS: a column series carries its
// category or accent class and fills with var(--mark); a line names a custom
// property. The axes are fixed to the spec's domains, so hiding a series restacks
// the columns but never rescales. A y axis with `clip` stops there, and a column
// taller than it is cut at the top and labelled with its total, so one spike (the
// reveal week) doesn't flatten every other week. No zoom: a week is the finest
// grain there is. Hovering a week lists its counts. The chart redraws when its
// width changes, keeping what the legend hides.

import { view } from "../data.js";
import { legend } from "../lib/legend.js";
import { loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { categoryClass } from "./scatter.js";

const DAY = 864e5;
const date = (iso) => new Date(`${iso}T00:00:00Z`);
const fmt = (n) => n.toLocaleString("en-US");

// The columns of week i, bottom to top: each visible series' [y0, y1]. Pure, for
// the tests.
export function stackAt(series, i, hidden) {
  let base = 0;
  return series.map((s) => {
    if (hidden.has(s.name)) return null;
    const v = s.values[i][1];
    const seg = [base, base + v];
    base += v;
    return seg;
  });
}

// What a week's tooltip says: its label, each visible series (a series' own tip
// when it has one), and the total when more than one is stacked.
export function weekTip(series, i, hidden) {
  const shown = series.filter((s) => !hidden.has(s.name));
  const week = new Date(date(series[0].values[i][0]).getTime());
  const lines = [`Week of ${week.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}`];
  for (const s of shown) lines.push(s.tips ? s.tips[i] : `${s.name}: ${fmt(s.values[i][1])}`);
  if (shown.length > 1) lines.push(`Total: ${fmt(shown.reduce((a, s) => a + s.values[i][1], 0))}`);
  return lines;
}

export async function mount(el) {
  const [d3, data] = await Promise.all([loadD3(), view()]);
  const spec = data.components[el.dataset.chart];
  if (!spec) throw new Error(`no spec for ${el.dataset.chart} in r2_view.json`);
  let h = draw(d3, el, spec);
  const plotEl = el.querySelector(".chart-plot");
  let width = plotEl.clientWidth, timer = null;
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      if (Math.abs(plotEl.clientWidth - width) < 2) return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        width = plotEl.clientWidth;
        h = draw(d3, el, spec, { hidden: h.hidden() });
      }, 150);
    }).observe(plotEl);
  }
}

// Draw `spec` into the mount `el`. Returns a handle for tests.
export function draw(d3, el, spec, { hidden: startHidden = new Set() } = {}) {
  const plotEl = el.querySelector(".chart-plot");
  plotEl.replaceChildren();
  const W = Math.max(320, plotEl.clientWidth), H = W < 600 ? 260 : 320;
  const m = { t: 22, r: 16, b: 48, l: 56 };
  const x = d3.scaleUtc().domain(spec.x.domain.map(date)).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain(spec.y.domain).range([H - m.b, m.t]);
  const top = spec.y.domain[1];

  const svg = d3.select(plotEl).append("svg").attr("class", "chart-svg")
    .attr("viewBox", [0, 0, W, H]).attr("aria-hidden", "true");
  const xt = Math.max(3, W / 120);
  svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`)
    .call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat(""));
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
    .call(d3.axisBottom(x).ticks(xt));
  svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
    .call(d3.axisLeft(y).ticks(5, spec.y.format === "pct" ? null : "~s")
      .tickFormat(spec.y.format === "pct" ? (v) => `${v}%` : null));
  svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
    .attr("x", (m.l + W - m.r) / 2).attr("y", H - 8).text(spec.x.label);
  svg.append("text").attr("class", "axis-label").attr("text-anchor", "middle")
    .attr("transform", `translate(14,${(m.t + H - m.b) / 2}) rotate(-90)`).text(spec.y.label);

  const series = spec.series.map((s) => ({ s, cls: categoryClass(s.color) }));
  const weeks = spec.series.length ? spec.series[0].values.map((v) => date(v[0])) : [];
  const colG = svg.append("g"), lineG = svg.append("g"), markG = svg.append("g");
  const groups = colG.selectAll("g").data(series).join("g")
    .attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
  groups.selectAll("rect").data((o) => o.s.values.map((v, i) => ({ o, i }))).join("rect")
    .attr("class", "bar");

  const accent = (l) => `var(--${l.color.slice(4)})`;
  const lineSel = lineG.selectAll("g.line").data(spec.lines).join("g")
    .attr("class", "line").attr("data-name", (l) => l.name);
  lineSel.append("path").attr("fill", "none").style("stroke", accent).attr("stroke-width", 2.5)
    .attr("d", (l) => d3.line().x((d) => x(date(d[0]))).y((d) => y(d[1]))(l.points));
  lineSel.selectAll("circle").data((l) => l.points.map((pt) => ({ pt, l }))).join("circle")
    .attr("r", 3).style("fill", (o) => accent(o.l))
    .attr("cx", (o) => x(date(o.pt[0]))).attr("cy", (o) => y(o.pt[1]));
  const ruleSel = lineG.selectAll("g.rule").data(spec.rules).join("g").attr("class", "rule");
  ruleSel.append("line").attr("x1", (r) => x(date(r.value))).attr("x2", (r) => x(date(r.value)))
    .attr("y1", m.t).attr("y2", H - m.b);
  ruleSel.append("text").attr("x", (r) => x(date(r.value)) + 4).attr("y", m.t + 10).text((r) => r.label);

  let hidden = new Set(startHidden);
  function place() {
    groups.selectAll("rect.bar").each(function ({ o, i }) {
      const seg = stackAt(spec.series, i, hidden)[spec.series.indexOf(o.s)];
      const x0 = x(weeks[i]), x1 = x(new Date(weeks[i].getTime() + 7 * DAY));
      d3.select(this).attr("x", x0 + 0.5).attr("width", Math.max(1, x1 - x0 - 1))
        .attr("y", seg ? y(Math.min(seg[1], top)) : 0)
        .attr("height", seg ? Math.max(0, y(Math.min(seg[0], top)) - y(Math.min(seg[1], top))) : 0);
    });
    // A column cut off by the clipped axis says how tall it really is.
    const total = (i) => spec.series.reduce((a, s) => a + (hidden.has(s.name) ? 0 : s.values[i][1]), 0);
    const over = spec.y.clip == null ? []
      : weeks.map((w, i) => ({ w, i, total: total(i) })).filter((d) => d.total > top);
    markG.selectAll("text.clipped").data(over, (d) => d.i).join("text").attr("class", "clipped")
      .attr("text-anchor", "start").attr("x", (d) => x(d.w) + 4).attr("y", m.t + 2)
      .text((d) => `${fmt(d.total)} ↑ (axis cut at ${fmt(top)})`);
  }
  function visibility() {
    svg.selectAll("[data-name]").style("display", function () { return hidden.has(this.dataset.name) ? "none" : null; });
    place();
  }
  visibility();

  const items = [...series.map((o) => ({ name: o.s.name, cls: o.cls })),
                 ...spec.lines.map((l) => ({ name: l.name, accent: l.color.slice(4) }))];
  if (items.length > 1) legend(el.querySelector(".chart-legend"), items, (hs) => { hidden = hs; visibility(); }, hidden);

  // Tooltips: the week under the pointer (columns), or the nearest line point.
  const tip = tooltip(plotEl);
  svg.on("pointermove", (ev) => {
    const [px] = d3.pointer(ev);
    const [hx, hy] = d3.pointer(ev, plotEl);
    if (weeks.length) {
      const t = x.invert(px).getTime();
      const i = weeks.findIndex((w) => t >= w.getTime() && t < w.getTime() + 7 * DAY);
      if (i >= 0) return tip.show(weekTip(spec.series, i, hidden), hx, hy);
    }
    const pts = spec.lines.filter((l) => !hidden.has(l.name) && l.tips)
      .flatMap((l) => l.points.map((pt, i) => ({ d: Math.abs(x(date(pt[0])) - px), tip: l.tips[i] })));
    const hit = pts.sort((a, b) => a.d - b.d)[0];
    if (hit && hit.d < 24) tip.show(hit.tip, hx, hy); else tip.hide();
  }).on("pointerleave", () => tip.hide());

  return { svg: svg.node(), hidden: () => new Set(hidden), redraw: place };
}
