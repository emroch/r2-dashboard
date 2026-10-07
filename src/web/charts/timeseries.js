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
// grain there is. Hovering a week lists its counts. With `toggles.cumulative`,
// Weekly / Cumulative buttons switch the columns to running totals, animating to
// the other view's fixed domain (y.cumulative), kept in the URL as
// ?<chart>=cumulative. The chart redraws when its width changes, keeping what the
// legend hides and the view.

import { view } from "../data.js";
import { legend } from "../lib/legend.js";
import { loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { get as getState, set as setState } from "../state.js";
import { categoryClass } from "./scatter.js";

const DAY = 864e5;
const date = (iso) => new Date(`${iso}T00:00:00Z`);
const fmt = (n) => n.toLocaleString("en-US");

// A series' value at week i: the week's count, or with `cumulative` its running
// total through that week.
const runs = new WeakMap();
export function valueAt(s, i, cumulative = false) {
  if (!cumulative) return s.values[i][1];
  if (!runs.has(s)) {
    let t = 0;
    runs.set(s, s.values.map((v) => (t += v[1])));
  }
  return runs.get(s)[i];
}

// The columns of week i, bottom to top: each visible series' [y0, y1]. Pure, for
// the tests.
export function stackAt(series, i, hidden, cumulative = false) {
  let base = 0;
  return series.map((s) => {
    if (hidden.has(s.name)) return null;
    const v = valueAt(s, i, cumulative);
    const seg = [base, base + v];
    base += v;
    return seg;
  });
}

// What a week's tooltip says, after its label. Weekly: each visible series'
// count (or its own tip), the total when more than one is stacked, and with
// `running` the running total through that week. Cumulative: what the column
// shows, each series' running total with the week's change ("Converted: 1,276
// (+10)"), then the same for the total.
export function weekTip(series, i, hidden, running = false, cumulative = false) {
  const shown = series.filter((s) => !hidden.has(s.name));
  const week = new Date(date(series[0].values[i][0]).getTime());
  const lines = [`Week of ${week.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}`];
  const sum = (f) => shown.reduce((a, s) => a + f(s), 0);
  const week_ = (s) => s.values[i][1], run = (s) => valueAt(s, i, true);
  if (cumulative) {
    for (const s of shown) lines.push(`${s.name}: ${fmt(run(s))} (+${fmt(week_(s))})`);
    if (shown.length > 1) lines.push(`Total: ${fmt(sum(run))} (+${fmt(sum(week_))})`);
    return lines;
  }
  for (const s of shown) lines.push(s.tips ? s.tips[i] : `${s.name}: ${fmt(week_(s))}`);
  if (shown.length > 1) lines.push(`Total: ${fmt(sum(week_))}`);
  if (running) lines.push(`Running total: ${fmt(sum(run))}`);
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
  const toggled = Boolean(spec.toggles?.cumulative);
  let cumulative = toggled && getState(el.dataset.chart) === "cumulative";
  const domainOf = (cum) => (cum ? spec.y.cumulative.domain : spec.y.domain);
  const y = d3.scaleLinear().domain(domainOf(cumulative)).range([H - m.b, m.t]);
  // The clip is the weekly view's; a running total is drawn whole.
  const top = () => (cumulative || spec.y.clip == null ? Infinity : spec.y.domain[1]);

  const svg = d3.select(plotEl).append("svg").attr("class", "chart-svg")
    .attr("viewBox", [0, 0, W, H]).attr("aria-hidden", "true");
  // Ticks on Mondays, where the columns start, while the span is short enough
  // to label weeks; past half a year, d3's months and years read better.
  const xt = Math.max(3, W / 120);
  const span = (x.domain()[1] - x.domain()[0]) / (7 * DAY);
  const xTicks = span <= 27 ? d3.utcMonday.every(Math.max(1, Math.ceil(span / xt))) : xt;
  const gridY = svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`);
  svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
    .call(d3.axisBottom(x).ticks(xTicks).tickFormat(span <= 27 ? d3.utcFormat("%b %d") : null));
  const gy = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
  const yAxes = (t) => {
    gridY.call((g) => (t ? g.transition(t) : g).call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat("")));
    gy.call((g) => (t ? g.transition(t) : g).call(d3.axisLeft(y).ticks(5)
      .tickFormat(spec.y.format === "pct" ? (v) => `${v}%` : d3.format(",~f"))));
  };
  yAxes(null);
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
  // Place every column; with a transition `t` (a view switch), they grow or
  // shrink to their new heights as the axis rescales.
  function place(t = null) {
    const cap = top();
    groups.selectAll("rect.bar").each(function ({ o, i }) {
      const seg = stackAt(spec.series, i, hidden, cumulative)[spec.series.indexOf(o.s)];
      const x0 = x(weeks[i]), x1 = x(new Date(weeks[i].getTime() + 7 * DAY));
      const r = d3.select(this).attr("x", x0 + 0.5).attr("width", Math.max(1, x1 - x0 - 1));
      (t ? r.transition(t) : r)
        .attr("y", seg ? y(Math.min(seg[1], cap)) : y(0))
        .attr("height", seg ? Math.max(0, y(Math.min(seg[0], cap)) - y(Math.min(seg[1], cap))) : 0);
    });
    // A column cut off by the clipped axis says how tall it really is.
    const total = (i) => spec.series.reduce((a, s) => a + (hidden.has(s.name) ? 0 : s.values[i][1]), 0);
    const over = cap === Infinity ? []
      : weeks.map((w, i) => ({ w, i, total: total(i) })).filter((d) => d.total > cap);
    markG.selectAll("text.clipped").data(over, (d) => d.i).join("text").attr("class", "clipped")
      .attr("text-anchor", "start").attr("x", (d) => x(d.w) + 4).attr("y", m.t + 2)
      .text((d) => `${fmt(d.total)} ↑ (axis cut at ${fmt(cap)})`);
  }
  function visibility() {
    svg.selectAll("[data-name]").style("display", function () { return hidden.has(this.dataset.name) ? "none" : null; });
    place();
  }
  visibility();

  const items = [...series.map((o) => ({ name: o.s.name, cls: o.cls })),
                 ...spec.lines.map((l) => ({ name: l.name, accent: l.color.slice(4) }))];
  if (items.length > 1) legend(el.querySelector(".chart-legend"), items, (hs) => { hidden = hs; visibility(); }, hidden);

  // Weekly / Cumulative: switch the view, animating the columns and the axis.
  const buttons = [];
  function setView(cum, animate = true) {
    cumulative = cum;
    for (const b of buttons) b.setAttribute("aria-pressed", String(b.dataset.view === (cum ? "cumulative" : "weekly")));
    y.domain(domainOf(cum));
    const t = animate ? svg.transition().duration(600) : null;
    yAxes(t);
    place(t);
  }
  if (toggled) {
    const controls = el.ownerDocument.createElement("div");
    controls.className = "chart-controls chart-switch";
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "View");
    for (const [view_, label] of [["weekly", "Weekly"], ["cumulative", "Cumulative"]]) {
      const b = Object.assign(el.ownerDocument.createElement("button"),
        { type: "button", className: "lg-item", textContent: label });
      b.dataset.view = view_;
      b.setAttribute("aria-pressed", String((view_ === "cumulative") === cumulative));
      b.addEventListener("click", () => {
        if ((view_ === "cumulative") === cumulative) return;
        setState(el.dataset.chart, view_ === "cumulative" ? "cumulative" : null);
        setView(view_ === "cumulative");
      });
      buttons.push(b);
      controls.append(b);
    }
    plotEl.prepend(controls);
  }

  // Tooltips: the week under the pointer (columns), or the nearest line point.
  const tip = tooltip(plotEl);
  svg.on("pointermove", (ev) => {
    const [px] = d3.pointer(ev);
    const [hx, hy] = d3.pointer(ev, plotEl);
    if (weeks.length) {
      const t = x.invert(px).getTime();
      const i = weeks.findIndex((w) => t >= w.getTime() && t < w.getTime() + 7 * DAY);
      if (i >= 0) return tip.show(weekTip(spec.series, i, hidden, toggled, cumulative), hx, hy);
    }
    const pts = spec.lines.filter((l) => !hidden.has(l.name) && l.tips)
      .flatMap((l) => l.points.map((pt, i) => ({ d: Math.abs(x(date(pt[0])) - px), tip: l.tips[i] })));
    const hit = pts.sort((a, b) => a.d - b.d)[0];
    if (hit && hit.d < 24) tip.show(hit.tip, hx, hy); else tip.hide();
  }).on("pointerleave", () => tip.hide());

  return { svg: svg.node(), hidden: () => new Set(hidden), redraw: () => place(),
           setView: (cum) => setView(cum, false), cumulative: () => cumulative };
}
