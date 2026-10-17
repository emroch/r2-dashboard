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
// grain there is. Hovering a week lists its counts. A long span groups its
// weeks into months or quarters (lib/grain.js) so the columns stay readable:
// Week / Month / Quarter buttons, defaulting to the finest grain whose columns
// are wide enough at the chart's width, and a choice kept in the URL as
// ?<chart>-grain=month, where it holds at any width. With `toggles.cumulative`,
// Weekly / Cumulative buttons switch the columns to running totals, animating to
// the other view's fixed domain (y.cumulative), kept in the URL as
// ?<chart>=cumulative. A series or line with `view` belongs to that view only
// (§fulfilment: the pipeline's stacked levels when cumulative, its event lines weekly);
// a series in the cumulative view is already levels, not summed; the legend
// lists the current view's entries; toggles.default picks the first view. The
// chart redraws when its width changes, keeping what the legend hides and the
// view.

import { view } from "../data.js";
import { legend } from "../lib/legend.js";
import { GRAINS, groupOf, heading, offered, pick } from "../lib/grain.js";
import { loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { get as getState, set as setState } from "../state.js";
import { categoryClass, NARROW, yAxisLabel } from "./scatter.js";

const DAY = 864e5;
const date = (iso) => new Date(`${iso}T00:00:00Z`);
const isoOf = (d) => d.toISOString().slice(0, 10);
const fmt = (n) => n.toLocaleString("en-US");
const signed = (n) => (n < 0 ? `−${fmt(-n)}` : `+${fmt(n)}`);

// A series' value at week i: the week's count, or with `cumulative` its running
// total through that week.
const runs = new WeakMap();
export function valueAt(s, i, cumulative = false) {
  if (!cumulative || s.view === "cumulative") return s.values[i][1];
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
export function weekTip(series, i, hidden, running = false, cumulative = false, partial = null, head = null) {
  const shown = series.filter((s) => !hidden.has(s.name));
  const iso = series[0].values[i][0];
  const lines = [head ?? heading("week", date(iso), date(iso), iso === partial)];
  const sum = (f) => shown.reduce((a, s) => a + f(s), 0);
  const week_ = (s) => s.values[i][1], run = (s) => valueAt(s, i, true);
  if (cumulative) {
    // A cumulative-view series is already a level (§fulfilment's pipeline), so its change
    // is from the week before, and can fall (waiting shrinks as orders move on).
    const delta = (s) => (s.view === "cumulative" ? s.values[i][1] - (i ? s.values[i - 1][1] : 0) : week_(s));
    // Listed as the column stacks, top first; the total below a rule.
    for (const s of [...shown].reverse()) lines.push(`${s.name}: ${fmt(run(s))} (${signed(delta(s))})`);
    if (shown.length > 1) lines.push(null, `Total: ${fmt(sum(run))} (${signed(sum(delta))})`);
    return lines;
  }
  for (const s of [...shown].reverse()) lines.push(s.tips ? s.tips[i] : `${s.name}: ${fmt(week_(s))}`);
  const totals = [];
  if (shown.length > 1) totals.push(`Total: ${fmt(sum(week_))}`);
  if (running) totals.push(`Running total: ${fmt(sum(run))}`);
  if (totals.length) lines.push(null, ...totals);
  return lines;
}

// Can the chart be grouped coarser than a week? Not with a line that carries
// its own tooltips (§delivery-vs-vin's cadence, a rate over a trailing window: summing it
// means nothing), nor with no columns to group.
export const groupable = (spec) => spec.series.length > 0 && !spec.lines.some((l) => l.tips);

// The y axis for grouped columns, as render/specs.py _columns fits a weekly
// one: 5% headroom over the tallest stack (10% over a line's peak), clipped
// just above the rest when one stack is more than three times the next.
export function axisFor(totals, peaks = []) {
  const top = Math.max(1, Math.max(0, ...totals) * 1.05, Math.max(0, ...peaks) * 1.1);
  const ranked = [...totals].sort((a, b) => b - a);
  if (ranked.length > 1 && ranked[0] > 3 * Math.max(ranked[1], 1)) {
    const cut = ranked[1] * 1.15, step = 10 ** Math.max(Math.floor(Math.log10(cut)), 0);
    const clip = Math.ceil(cut / step) * step;
    return { domain: [0, clip], clip };
  }
  return { domain: [0, top] };
}

// `spec` at `grain`: each group's bounds and tooltip heading (`groups`), and its
// series and lines summed into the groups. A cumulative view's levels take
// their last week instead, and a series with `counts` ([part, whole] a week, a
// percentage) re-divides its summed counts and words its tips from `tip`
// ("{0} of {1} …"). A group is clamped to the x domain, so the first and last
// columns span only the weeks there are. Coarser than a week, the y axis is
// refit (axisFor); the cumulative view's never needs it. Pure, for the tests.
export function regroup(spec, grain) {
  const [lo, hi] = spec.x.domain.map(date);
  const partial = spec.x.partial ? date(spec.x.partial) : null;
  const regroupLines = grain !== "week";
  const weeksOf = (pts) => pts.map((p) => groupOf(date(p[0]), "week").start);
  const all = [...spec.series.flatMap((s) => weeksOf(s.values)),
               ...(regroupLines ? spec.lines.flatMap((l) => weeksOf(l.points)) : [])];
  const raw = new Map();
  for (const w of all.sort((a, b) => a - b)) {
    const g = groupOf(w, grain);
    if (!raw.has(g.key)) raw.set(g.key, { ...g, first: w, last: w });
    else if (w > raw.get(g.key).last) raw.get(g.key).last = w;
  }
  const keys = [...raw.keys()], at = new Map(keys.map((k, i) => [k, i]));
  const groups = [...raw.values()].map((g) => {
    const start = new Date(Math.max(g.start, lo)), end = new Date(Math.min(g.end, hi));
    const sofar = Boolean(partial && g.last.getTime() === partial.getTime());
    return { start, end, sofar, heading: heading(grain, g.first, g.last, sofar) };
  });
  const fold = (pts, last = false) => {
    const out = groups.map(() => 0);
    for (const [iso, v] of pts) {
      const i = at.get(groupOf(date(iso), grain).key);
      out[i] = last ? v : out[i] + v;
    }
    return out;
  };
  const starts = groups.map((g) => isoOf(g.start));
  const series = spec.series.map((s) => {
    if (!s.counts) {
      return { ...s, values: fold(s.values, s.view === "cumulative").map((v, i) => [starts[i], v]) };
    }
    const part = fold(s.values.map((v, i) => [v[0], s.counts[i][0]]));
    const whole = fold(s.values.map((v, i) => [v[0], s.counts[i][1]]));
    return { ...s,
      values: part.map((p, i) => [starts[i], whole[i] ? Math.round((1000 * p) / whole[i]) / 10 : 0]),
      tips: part.map((p, i) => s.tip.replace("{0}", fmt(p)).replace("{1}", fmt(whole[i]))) };
  });
  const lines = !regroupLines ? spec.lines : spec.lines.map((l) => ({ ...l,
    points: fold(l.points).map((v, i) => [isoOf(new Date((groups[i].start.getTime() + groups[i].end.getTime()) / 2)), v]) }));
  const last = groups.at(-1);
  const x = { ...spec.x, partial: last?.sofar ? isoOf(last.start) : null };
  let y = spec.y;
  if (grain !== "week" && spec.y.format !== "pct") {
    const cols = series.filter((s) => s.view !== "cumulative");
    const totals = cols.length ? groups.map((_, i) => cols.reduce((a, s) => a + s.values[i][1], 0)) : [];
    const peaks = lines.filter((l) => l.view !== "cumulative").flatMap((l) => l.points.map((p) => p[1]));
    const fit = axisFor(totals, peaks);
    y = { ...spec.y, ...fit };
    if (fit.clip == null) delete y.clip;
  }
  return { ...spec, x, y, series, lines, groups };
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
        h = draw(d3, el, spec, { hidden: (el.r2ts || h).hidden() });
      }, 150);
    }).observe(plotEl);
  }
}

// Draw `spec` into the mount `el`. Returns a handle for tests.
export function draw(d3, el, weekly, { hidden: startHidden = new Set() } = {}) {
  const plotEl = el.querySelector(".chart-plot");
  plotEl.replaceChildren();
  const W = Math.max(320, plotEl.clientWidth || 0), H = W < 600 ? 260 : 320;   // 0 before layout (and in tests)
  const narrow = W < NARROW;
  const m = { t: narrow ? 30 : 22, r: 16, b: 48, l: narrow ? 42 : 56 };
  // The grain: the reader's choice, else the finest that reads at this width.
  const [lo, hi] = weekly.x.domain.map(date);
  const grains = groupable(weekly) ? offered(lo, hi) : ["week"];
  const grainKey = `${el.dataset.chart}-grain`;
  const grain = grains.includes(getState(grainKey)) ? getState(grainKey) : pick(lo, hi, W - m.l - m.r, grains);
  const spec = regroup(weekly, grain);
  const x = d3.scaleUtc().domain(spec.x.domain.map(date)).range([m.l, W - m.r]);
  const toggled = Boolean(spec.toggles?.cumulative);
  const initial = spec.toggles?.default || "weekly";
  let cumulative = toggled && (getState(el.dataset.chart) || initial) === "cumulative";
  // What the current view leaves out: series and lines that belong to the other.
  const offView = () => new Set([...spec.series, ...spec.lines]
    .filter((s) => s.view && s.view !== (cumulative ? "cumulative" : "weekly")).map((s) => s.name));
  const omitted = () => new Set([...hidden, ...offView()]);
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
  yAxisLabel(svg, spec.y.label, narrow, m, H);

  // A series with `stage` draws at that delivery stage's tone (.tone-*): its
  // color stepped toward white (or black on the dark card), since a faded color
  // turns muddy. The hovered week (.active) lights up in Compass Yellow at the
  // same steps.
  const stageCls = (s) => ` tone-${s.stage}`;
  const series = spec.series.map((s) => ({
    s, cls: categoryClass(s.color) + (s.stage ? stageCls(s) : "") }));
  // Each column's span: a week, or a group of weeks.
  const spans = spec.groups;
  const colG = svg.append("g"), lineG = svg.append("g"), markG = svg.append("g");
  const groups = colG.selectAll("g").data(series).join("g")
    .attr("class", (o) => o.cls).attr("data-name", (o) => o.s.name);
  groups.selectAll("rect").data((o) => o.s.values.map((v, i) => ({ o, i }))).join("rect")
    .attr("class", "bar");
  // The current week's column, in the weekly view, is crosshatched over: a week
  // so far reads short. (A running total so far isn't misleading, so it isn't.)
  const hatchId = `${el.dataset.chart}-hatch`;
  const hatch = svg.append("defs").append("pattern").attr("id", hatchId)
    .attr("patternUnits", "userSpaceOnUse").attr("width", 6).attr("height", 6);
  hatch.append("path").attr("class", "hatch").attr("d", "M0,6 L6,0 M-1,1 L1,-1 M5,7 L7,5");
  const pi = spec.x.partial ? (spec.series[0]?.values || []).findIndex((v) => v[0] === spec.x.partial) : -1;
  const hatchRect = colG.append("rect").attr("class", "bar-partial").style("fill", `url(#${hatchId})`);

  const accent = (l) => `var(--${l.color.slice(4)})`;
  const lineSel = lineG.selectAll("g.line").data(spec.lines).join("g")
    .attr("class", "line").attr("data-name", (l) => l.name);
  // Smooth (monotone, so a line never overshoots a week's value). The current
  // week (x.partial) is still under way: its segment is dashed and its point
  // hollow.
  const partial = spec.x.partial || null;
  const inWeek = (iso) => partial && date(iso) >= date(partial);
  // One smooth path per line, drawn twice: solid up to the last complete week's
  // point, dashed after it, split by two clips, so the dashed part continues the
  // very same curve rather than a curve of its own.
  const curve = d3.line().curve(d3.curveMonotoneX).x((d) => x(date(d[0]))).y((d) => y(d[1]));
  const cut = () => {
    const pts = (spec.lines[0] || { points: [] }).points.filter((pt) => !inWeek(pt[0]));
    return partial && pts.length ? x(date(pts[pts.length - 1][0])) : W;
  };
  const clipId = `${el.dataset.chart}-done`;
  const defs = svg.append("defs");
  const doneClip = defs.append("clipPath").attr("id", clipId).append("rect");
  const tailClip = defs.append("clipPath").attr("id", `${clipId}-tail`).append("rect");
  const drawLines = () => {
    const c = cut();
    doneClip.attr("x", 0).attr("y", 0).attr("width", c).attr("height", H);
    tailClip.attr("x", c).attr("y", 0).attr("width", Math.max(0, W - c)).attr("height", H);
    lineSel.selectAll("path").attr("d", (l) => curve(l.points));
    lineSel.selectAll("circle").attr("cx", (o) => x(date(o.pt[0]))).attr("cy", (o) => y(o.pt[1]));
  };
  lineSel.append("path").attr("class", "done").attr("fill", "none").style("stroke", accent)
    .attr("stroke-width", 2.5).attr("clip-path", `url(#${clipId})`);
  lineSel.append("path").attr("class", "partial").attr("fill", "none").style("stroke", accent)
    .attr("stroke-width", 2.5).attr("stroke-dasharray", "5,4").attr("clip-path", `url(#${clipId}-tail)`);
  lineSel.selectAll("circle").data((l) => l.points.map((pt) => ({ pt, l }))).join("circle")
    .attr("r", 3).attr("class", (o) => (inWeek(o.pt[0]) ? "pt-partial" : null))
    .style("fill", (o) => (inWeek(o.pt[0]) ? "var(--card-bg)" : accent(o.l)))
    .style("stroke", (o) => accent(o.l));
  drawLines();
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
      const seg = stackAt(spec.series, i, omitted(), cumulative)[spec.series.indexOf(o.s)];
      const x0 = x(spans[i].start), x1 = x(spans[i].end);
      const r = d3.select(this).attr("x", x0 + 0.5).attr("width", Math.max(1, x1 - x0 - 1));
      (t ? r.transition(t) : r)
        .attr("y", seg ? y(Math.min(seg[1], cap)) : y(0))
        .attr("height", seg ? Math.max(0, y(Math.min(seg[0], cap)) - y(Math.min(seg[1], cap))) : 0);
    });
    if (pi >= 0 && !cumulative) {
      const x0 = x(spans[pi].start), x1 = x(spans[pi].end);
      const tot = stackAt(spec.series, pi, omitted(), false).filter(Boolean).reduce((a, s) => Math.max(a, s[1]), 0);
      hatchRect.attr("display", null).attr("x", x0 + 0.5).attr("width", Math.max(1, x1 - x0 - 1))
        .attr("y", y(Math.min(tot, cap))).attr("height", Math.max(0, y(0) - y(Math.min(tot, cap))));
    } else hatchRect.attr("display", "none");
    // A column cut off by the clipped axis says how tall it really is.
    const total = (i) => spec.series.reduce((a, s) => a + (hidden.has(s.name) ? 0 : s.values[i][1]), 0);
    const over = cap === Infinity ? []
      : spans.map((g, i) => ({ w: g.start, i, total: total(i) })).filter((d) => d.total > cap);
    // Beside its column, under the top gridline: to the right, or to the left
    // where the text (about 5.6px a character) would run out of the plot.
    const label = (d) => `${fmt(d.total)} ↑ (axis cut at ${fmt(cap)})`;
    const right = (d) => x(spans[d.i].end) + 4 + label(d).length * 5.6 <= W - m.r;
    markG.selectAll("text.clipped").data(over, (d) => d.i).join("text").attr("class", "clipped")
      .attr("text-anchor", (d) => (right(d) ? "start" : "end"))
      .attr("x", (d) => (right(d) ? x(spans[d.i].end) + 4 : x(spans[d.i].start) - 4)).attr("y", m.t + 12)
      .text(label);
  }
  function visibility(t = null) {
    const off = omitted();
    lineSel.style("display", (l) => (off.has(l.name) ? "none" : null));
    groups.style("display", (o) => (hidden.has(o.s.name) ? "none" : null));
    place(t);
  }

  // The legend lists the current view's series and lines.
  function legendFor() {
    const off = offView();
    const items = [...series.filter((o) => !off.has(o.s.name)).map((o) => ({ name: o.s.name, cls: o.cls })),
                   ...spec.lines.filter((l) => !off.has(l.name)).map((l) => ({ name: l.name, accent: l.color.slice(4) }))];
    const host = el.querySelector(".chart-legend");
    if (items.length > 1) legend(host, items, (hs) => { hidden = hs; visibility(); }, hidden);
    else host.replaceChildren();
  }
  visibility();
  legendFor();

  // Weekly / Cumulative: switch the view, animating the columns and the axis.
  const buttons = [];
  function setView(cum, animate = true) {
    cumulative = cum;
    for (const b of buttons) b.setAttribute("aria-pressed", String(b.dataset.view === (cum ? "cumulative" : "weekly")));
    y.domain(domainOf(cum));
    const t = animate ? svg.transition().duration(600) : null;
    yAxes(t);
    drawLines();
    visibility(t);
    legendFor();
  }
  // Controls, in a row above the plot: the grain (when there's a choice), then
  // the view, its first choice named for the grain ("Monthly").
  const doc = el.ownerDocument;
  const controls = doc.createElement("div");
  controls.className = "chart-controls ts-controls";
  const group = (label) => {
    const g = Object.assign(doc.createElement("div"), { className: "chart-switch seg" });
    g.setAttribute("role", "group");
    g.setAttribute("aria-label", label);
    controls.append(g);
    return g;
  };
  if (grains.length > 1) {
    const g = group("Group by");
    for (const k of grains) {
      const b = Object.assign(doc.createElement("button"),
        { type: "button", className: "lg-item", textContent: GRAINS.find((x_) => x_.key === k).label });
      b.dataset.grain = k;
      b.setAttribute("aria-pressed", String(k === grain));
      b.addEventListener("click", () => {
        if (k === grain) return;
        setState(grainKey, k);
        // Redrawn whole at the new grain, keeping what the legend hides; focus
        // stays on the button that was pressed.
        draw(d3, el, weekly, { hidden });
        el.querySelector(`[data-grain="${k}"]`)?.focus();
      });
      g.append(b);
    }
  }
  if (toggled) {
    const g = group("View");
    const every = GRAINS.find((x_) => x_.key === grain).every;
    for (const [view_, label] of [["weekly", every], ["cumulative", "Cumulative"]]) {
      const b = Object.assign(doc.createElement("button"),
        { type: "button", className: "lg-item", textContent: label });
      b.dataset.view = view_;
      b.setAttribute("aria-pressed", String((view_ === "cumulative") === cumulative));
      b.addEventListener("click", () => {
        if ((view_ === "cumulative") === cumulative) return;
        setState(el.dataset.chart, view_ === initial ? null : view_);
        setView(view_ === "cumulative");
      });
      buttons.push(b);
      g.append(b);
    }
  }
  if (controls.childElementCount) plotEl.prepend(controls);

  // Tooltips: the week under the pointer (columns), or the nearest line point.
  const tip = tooltip(plotEl);
  // The hovered week's column is highlighted (.active), the rest left as they are.
  let active = -1;
  const activate = (i) => {
    if (i === active) return;
    active = i;
    groups.selectAll("rect.bar").classed("active", (d) => d.i === i);
  };
  // Over a view drawn as lines, a vertical rule marks where the pointer is: one
  // element, made once and moved, hidden unless lines are showing. It follows
  // the pointer and snaps to a set of points while their tooltip is up.
  const rule = lineG.append("line").attr("class", "hover-rule").attr("y1", m.t).attr("y2", H - m.b)
    .attr("display", "none");
  const ruleAt = (px) => (px == null ? rule.attr("display", "none")
    : rule.attr("display", null).attr("x1", px).attr("x2", px));
  svg.on("pointermove", (ev) => {
    const [px] = d3.pointer(ev);
    const [hx, hy] = d3.pointer(ev, plotEl);
    const off = omitted();
    const shownLines = spec.lines.filter((l) => !off.has(l.name));
    const inPlot = px >= m.l && px <= W - m.r;
    if (spans.length) {
      const t = x.invert(px).getTime();
      const i = spans.findIndex((g) => t >= g.start.getTime() && t < g.end.getTime());
      // A view drawn as weekly lines (§fulfilment's events) lists each line's week.
      const weekLines = shownLines.filter((l) => l.view);
      if (weekLines.length) {
        if (i < 0) { tip.hide(); return ruleAt(inPlot ? px : null); }
        ruleAt(x(date(weekLines[0].points[i][0])));
        return tip.show([spans[i].heading,
          ...weekLines.map((l) => `${l.name}: ${fmt(l.points[i][1])}`)], hx, hy);
      }
      ruleAt(null);
      activate(i);
      if (i >= 0) return tip.show(weekTip(spec.series, i, off, toggled, cumulative, partial, spans[i].heading), hx, hy);
    }
    const pts = shownLines.filter((l) => l.tips)
      .flatMap((l) => l.points.map((pt, i) => ({ px: x(date(pt[0])), tip: l.tips[i] })));
    const hit = pts.sort((a, b) => Math.abs(a.px - px) - Math.abs(b.px - px))[0];
    if (hit && Math.abs(hit.px - px) < 24) { ruleAt(hit.px); tip.show(hit.tip, hx, hy); }
    else { ruleAt(pts.length && inPlot ? px : null); tip.hide(); }
  }).on("pointerleave", () => { tip.hide(); activate(-1); ruleAt(null); });

  const handle = { svg: svg.node(), hidden: () => new Set(hidden), redraw: () => place(), grain,
                   setView: (cum, animate = false) => setView(cum, animate), cumulative: () => cumulative };
  el.r2ts = handle;
  return handle;
}
