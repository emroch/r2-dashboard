// The `geo` template (docs/presentation.md, "Components"): the US states map,
// drawn with d3 on the us-atlas states (vendor/README.md) in d3's standard US
// layout (geoAlbersUsa: Alaska and Hawaii inset at the bottom left, on a
// background of their own so their land reads against it).
//
// The spec counts each state (render/specs.py geo_demand); the reader picks the
// measure (all orders, VIN assigned, orders + reservations), kept in the URL, and
// each state is filled by it on a square-root scale: a choropleth. Fills are CSS:
// a state's share of the scale is --v, which styles.css mixes into the land, as
// the heatmap does, so a theme change needs no redraw. States under the spec's
// small_n are hatched instead of filled: too few to compare.
//
// A state is a path keyed by its postal code (data-state). Clicking one selects
// it (Escape or a second click clears) and fires `r2:stateselect` on the mount,
// {detail: {code}} (null when cleared), for a companion component to follow
// (#112: per-state views under a shared map).

import { view } from "../data.js";
import { loadAtlas, loadD3 } from "../lib/load.js";
import { tooltip } from "../lib/tooltip.js";
import { get as getState, set as setState } from "../state.js";

// us-atlas keys states by FIPS code; the page keys them by postal code.
export const FIPS = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
  "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
  "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
  "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
  "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
  "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
  "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
  "55": "WI", "56": "WY", "72": "PR",
};

// A value's share of the scale's top, on a square-root scale (so a state with a
// quarter of the leader's orders reads half as strong): 0..1.
export function share(n, max) {
  return max > 0 && n > 0 ? Math.sqrt(n / max) : 0;
}

export async function mount(el) {
  const [d3, atlas, data] = await Promise.all([loadD3(), loadAtlas(), view()]);
  const spec = data.components[el.dataset.chart];
  if (!spec) throw new Error(`no spec for ${el.dataset.chart} in r2_view.json`);
  let h = draw(d3, atlas, el, spec);
  const plotEl = el.querySelector(".chart-plot");
  let width = plotEl.clientWidth, timer = null;
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      if (Math.abs(plotEl.clientWidth - width) < 2) return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        width = plotEl.clientWidth;
        h = draw(d3, atlas, el, spec, { selected: h.selected() });
      }, 150);
    }).observe(plotEl);
  }
}

// Draw `spec` into the mount `el`. Returns a handle for tests: select(code),
// selected(), and setMeasure(key) as the switch does.
export function draw(d3, { topojson, us }, el, spec, { selected: startSelected = null } = {}) {
  const doc = el.ownerDocument;
  const plotEl = el.querySelector(".chart-plot");
  plotEl.replaceChildren();
  const W = Math.max(320, plotEl.clientWidth || 0), H = Math.round(W * 0.62);
  const id = el.dataset.chart;
  const keys = spec.measures.map((m) => m.key);
  let measure = keys.includes(getState(`${id}-m`)) ? getState(`${id}-m`) : spec.default;
  let selected = startSelected;

  const nation = topojson.feature(us, us.objects.nation);
  const features = topojson.feature(us, us.objects.states).features
    .map((f) => ({ f, code: FIPS[f.id] }))
    .filter((o) => o.code && o.code !== "PR");
  const projection = d3.geoAlbersUsa().fitExtent([[8, 8], [W - 8, H - 8]], nation);
  const path = d3.geoPath(projection);

  const svg = d3.select(plotEl).append("svg").attr("class", "chart-svg map-svg")
    .attr("viewBox", [0, 0, W, H]).attr("aria-hidden", "true");
  const hatch = svg.append("defs").append("pattern").attr("id", `${id}-hatch`)
    .attr("patternUnits", "userSpaceOnUse").attr("width", 5).attr("height", 5)
    .attr("patternTransform", "rotate(45)");
  hatch.append("rect").attr("class", "map-hatch-bg").attr("width", 5).attr("height", 5);
  hatch.append("line").attr("class", "map-hatch").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", 5);
  // The insets' backgrounds: the bounds of each inset state, padded.
  for (const code of ["AK", "HI"]) {
    const o = features.find((s) => s.code === code);
    if (!o) continue;
    const [[x0, y0], [x1, y1]] = path.bounds(o.f);
    svg.append("rect").attr("class", "map-inset").attr("rx", 4)
      .attr("x", x0 - 6).attr("y", y0 - 6).attr("width", x1 - x0 + 12).attr("height", y1 - y0 + 12);
  }
  const statesG = svg.append("g");
  const statePaths = statesG.selectAll("path").data(features).join("path")
    .attr("class", "map-state").attr("data-state", (o) => o.code).attr("d", (o) => path(o.f));
  svg.append("path").attr("class", "map-border")
    .attr("d", path(topojson.mesh(us, us.objects.states, (a, b) => a !== b)));
  const [fx, fy] = projection([spec.factory[1], spec.factory[0]]) || [null, null];
  if (fx !== null) {
    svg.append("path").attr("class", "map-factory").attr("d", d3.symbol(d3.symbolStar, 90)())
      .attr("transform", `translate(${fx},${fy})`);
  }

  const val = (code) => spec.states[code]?.[measure] ?? 0;
  // The orders measure is what small_n counts; total demand is never small.
  const small = (code) => measure !== "demand" && (spec.states[code]?.orders ?? 0) < spec.small_n;

  function paint() {
    const top = Math.max(0, ...Object.keys(spec.states).map(val));
    statePaths
      .classed("map-filled", (o) => val(o.code) > 0 && !small(o.code))
      .classed("map-small", (o) => val(o.code) > 0 && small(o.code))
      .style("--v", (o) => share(val(o.code), top).toFixed(3))
      .style("fill", (o) => (val(o.code) > 0 && small(o.code) ? `url(#${id}-hatch)` : null))
      .classed("selected", (o) => o.code === selected);
    legendFor(top);
  }

  // Legend: the fill's ramp (0 to the top), and the hatch, as plain HTML.
  const legendEl = el.querySelector(".chart-legend");
  const span = (className, textContent) => Object.assign(doc.createElement("span"), { className, textContent });
  function legendFor(top) {
    const ramp = span("map-key", "");
    ramp.append(span("", "0"), span("map-ramp", ""), span("", d3.format(",")(top)));
    legendEl.replaceChildren(ramp);
    if (measure !== "demand") {
      const hatch = span("map-key", "");
      hatch.append(span("map-swatch-small", ""), span("", `Under ${spec.small_n} orders`));
      legendEl.append(hatch);
    }
  }

  function select(code) {
    selected = code && code !== selected ? code : null;
    paint();
    el.dispatchEvent(new (doc.defaultView?.CustomEvent ?? CustomEvent)("r2:stateselect",
      { bubbles: true, detail: { code: selected } }));
  }

  // The measure switch, kept in the URL.
  const controls = doc.createElement("div");
  controls.className = "chart-controls chart-switch";
  controls.setAttribute("role", "group");
  controls.setAttribute("aria-label", "Measure");
  const buttons = spec.measures.map((m) => {
    const b = Object.assign(doc.createElement("button"), { type: "button", className: "lg-item", textContent: m.label });
    b.dataset.key = m.key;
    b.setAttribute("aria-pressed", String(m.key === measure));
    b.addEventListener("click", () => {
      measure = m.key;
      setState(`${id}-m`, m.key === spec.default ? null : m.key);
      for (const o of buttons) o.setAttribute("aria-pressed", String(o === b));
      paint();
    });
    return b;
  });
  controls.append(...buttons);
  plotEl.prepend(controls);

  // Hover: the state under the pointer, named and counted.
  const tip = tooltip(plotEl);
  const name = Object.fromEntries(features.map((o) => [o.code, o.f.properties.name]));
  let hovered = null;
  const hover = (code) => {
    if (code === hovered) return;
    hovered = code;
    svg.selectAll("[data-state]").classed("hover", function () { return this.dataset.state === code; });
  };
  svg.on("pointermove", (ev) => {
    const code = ev.target?.dataset?.state;
    if (!code) { hover(null); tip.hide(); return; }
    hover(code);
    const [hx, hy] = d3.pointer(ev, plotEl);
    tip.show([`${name[code]} (${code})`, ...(spec.states[code]?.tip ?? ["No orders or reservations"])], hx, hy);
  }).on("pointerleave", () => { hover(null); tip.hide(); })
    .on("click", (ev) => { const code = ev.target?.dataset?.state; if (code) select(code); });
  // One Escape listener per mount, replaced on each redraw.
  if (el.r2Escape) doc.removeEventListener("keydown", el.r2Escape);
  el.r2Escape = (ev) => { if (ev.key === "Escape" && selected) select(null); };
  doc.addEventListener("keydown", el.r2Escape);

  paint();
  return {
    svg: svg.node(),
    select,
    selected: () => selected,
    setMeasure: (k) => { measure = k; paint(); },
  };
}
