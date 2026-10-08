// The `geo` template (docs/presentation.md, "Components"): the US states map,
// drawn with d3 on the us-atlas states (vendor/README.md) in d3's standard US
// layout (geoAlbersUsa: Alaska and Hawaii inset at the bottom left).
//
// The spec counts each state (render/specs.py geo_demand); the reader picks the
// measure on a slider, from total demand (orders + reservations) down through
// orders, with a VIN, scheduled and delivered, and each state is filled by it on
// a square-root scale: a choropleth. Fills are CSS:
// a state's share of the scale is --v, which styles.css mixes into the land, as
// the heatmap does, so a theme change needs no redraw. A state with none of the
// measure is hatched rather than filled, so "none" never reads as "a few". Every
// state keeps an outline in the mark-edge grey, so pale states hold against the
// card; hover and selection draw their own outline above the rest.
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
  const statesG = svg.append("g");
  const statePaths = statesG.selectAll("path").data(features).join("path")
    .attr("class", "map-state").attr("data-state", (o) => o.code).attr("d", (o) => path(o.f));
  // Hover and selection outlines, above every state's own, so a neighbor never
  // paints over them.
  const outline = (cls) => svg.append("path").attr("class", `map-outline ${cls}`);
  const hoverLine = outline("map-hover"), selectLine = outline("map-selected");
  const shape = (code) => {
    const o = code && features.find((s) => s.code === code);
    return o ? path(o.f) : null;
  };
  const [fx, fy] = projection([spec.factory[1], spec.factory[0]]) || [null, null];
  if (fx !== null) {
    svg.append("path").attr("class", "map-factory").attr("d", d3.symbol(d3.symbolStar, 90)())
      .attr("transform", `translate(${fx},${fy})`);
  }

  const val = (code) => spec.states[code]?.[measure] ?? 0;

  function paint() {
    const top = Math.max(0, ...Object.keys(spec.states).map(val));
    statePaths
      .classed("map-filled", (o) => val(o.code) > 0)
      .classed("map-none", (o) => val(o.code) === 0)
      .style("--v", (o) => share(val(o.code), top).toFixed(3))
      .style("fill", (o) => (val(o.code) === 0 ? `url(#${id}-hatch)` : null))
      .classed("selected", (o) => o.code === selected);
    selectLine.attr("d", shape(selected));
    legendFor(top);
  }

  // Legend: the fill's ramp (1 to the top), and the hatch for none, as plain HTML.
  const legendEl = el.querySelector(".chart-legend");
  const span = (className, textContent) => Object.assign(doc.createElement("span"), { className, textContent });
  function legendFor(top) {
    const ramp = span("map-key", "");
    ramp.append(span("", "1"), span("map-ramp", ""), span("", d3.format(",")(top)));
    const none = span("map-key", "");
    none.append(span("map-swatch-none", ""), span("", "None"));
    legendEl.replaceChildren(ramp, none);
  }

  function select(code) {
    selected = code && code !== selected ? code : null;
    paint();
    el.dispatchEvent(new (doc.defaultView?.CustomEvent ?? CustomEvent)("r2:stateselect",
      { bubbles: true, detail: { code: selected } }));
  }

  // The measure, a stepped slider: the measures nest (each a subset of the one
  // before), so their order is a continuum, and the thumb's place says how far
  // down it the map is. A native range input, so keys and assistive tech work;
  // a label under each stop picks it too. Kept in the URL.
  const keyAt = (i) => spec.measures[i].key;
  const controls = doc.createElement("div");
  controls.className = "map-stage";
  controls.style.setProperty("--stops", spec.measures.length);
  const slider = Object.assign(doc.createElement("input"), { type: "range", min: "0", step: "1",
    max: String(spec.measures.length - 1), className: "map-slider" });
  slider.setAttribute("aria-label", "Orders to map");
  const stops = doc.createElement("div");
  stops.className = "map-stops";
  const labels = spec.measures.map((m, i) => {
    const b = Object.assign(doc.createElement("button"), { type: "button", textContent: m.label });
    b.dataset.key = m.key;
    b.addEventListener("click", () => pick(i));
    return b;
  });
  stops.append(...labels);
  controls.append(slider, stops);
  function sync() {
    const i = keys.indexOf(measure);
    slider.value = String(i);
    slider.setAttribute("aria-valuetext", spec.measures[i].label);
    labels.forEach((b, j) => b.setAttribute("aria-pressed", String(j === i)));
  }
  function pick(i) {
    if (keyAt(i) === measure) return;
    measure = keyAt(i);
    setState(`${id}-m`, measure === spec.default ? null : measure);
    sync();
    paint();
  }
  slider.addEventListener("input", () => pick(Number(slider.value)));
  sync();
  plotEl.prepend(controls);

  // Hover: the state under the pointer, named and counted.
  const tip = tooltip(plotEl);
  const name = Object.fromEntries(features.map((o) => [o.code, o.f.properties.name]));
  let hovered = null;
  const hover = (code) => {
    if (code === hovered) return;
    hovered = code;
    hoverLine.attr("d", shape(code));
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
    setMeasure: (k) => pick(keys.indexOf(k)),
  };
}
