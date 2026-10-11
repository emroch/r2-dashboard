// The `statemix` template: one US state's orders, or the whole US's, split by a
// measure the reader picks (status, paint, wheels, interior), as 100% rows in
// the mix panels' markup (css/05-components.css .mx-*). It follows the state
// selected on the map above it (spec.map, a `geo` mount: its r2:stateselect),
// and its own state picker selects on the map in turn (r2:stateset), so the
// two always agree. "Show all" lists every state with spec.small_n orders or
// more instead, largest first, to compare states side by side. The counts are
// render/specs.py state_mix; this only draws.
//
// URL state: ?state=CA (shared with the map; ?state=all for the list) and
// ?by=paint (the measure).

import { view } from "../data.js";
import { loadAtlas } from "../lib/load.js";
import { get as getState, set as setState } from "../state.js";
import { FIPS } from "./geo.js";
import { categoryClass } from "./scatter.js";

export async function mount(el) {
  const [atlas, data] = await Promise.all([loadAtlas(), view()]);
  const spec = data.components[el.dataset.chart];
  if (!spec) throw new Error(`no spec for ${el.dataset.chart} in r2_view.json`);
  return draw(el, spec, stateNames(atlas.us));
}

// Postal code -> state name, from the atlas the map draws (50 states and DC).
export function stateNames(us) {
  const names = {};
  for (const g of us.objects.states.geometries) {
    const code = FIPS[g.id];
    if (code && code !== "PR") names[code] = g.properties.name;
  }
  return names;
}

// A row's segments, as "count label (share)" text and the bar's marks.
export function split(counts, cats) {
  const n = counts.reduce((a, b) => a + b, 0);
  const parts = cats.map((c, i) => ({ c, k: counts[i], pct: n ? (100 * counts[i]) / n : 0 }))
    .filter((p) => p.k);
  return { n, parts };
}

const fmt = (n) => n.toLocaleString("en-US");

// Draw `spec` into the mount `el`. Returns a handle for tests: select(code),
// selected(), setMeasure(key).
export function draw(el, spec, names) {
  const doc = el.ownerDocument;
  const plotEl = el.querySelector(".chart-plot");
  const legendEl = el.querySelector(".chart-legend");
  plotEl.replaceChildren();
  const keys = spec.measures.map((m) => m.key);
  let measure = keys.includes(getState("by")) ? getState("by") : spec.default;
  const known = (code) => Boolean(code && names[code]);
  let selected = known(getState("state")) ? getState("state") : null;
  let showAll = getState("state") === "all";
  const make = (tag, className, text) => {
    const e = doc.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  // Controls, above the key: the measure switch (the timeseries view switch's
  // look), then a state picker (also the keyboard's way to select a state) and
  // the Show all toggle.
  const controls = make("div", "chart-controls mx-controls");
  const sw = make("div", "chart-switch");
  sw.setAttribute("role", "group");
  sw.setAttribute("aria-label", "Split by");
  const buttons = spec.measures.map((m) => {
    const b = make("button", "lg-item", m.label);
    b.type = "button";
    b.dataset.key = m.key;
    b.addEventListener("click", () => setMeasure(m.key));
    sw.append(b);
    return b;
  });
  const picker = make("select", "mx-picker");
  picker.setAttribute("aria-label", "State");
  const all = make("option", "", "All US");
  all.value = "";
  picker.append(all);
  for (const code of Object.keys(names).sort((a, b) => names[a].localeCompare(names[b]))) {
    const o = make("option", "", names[code]);
    o.value = code;
    picker.append(o);
  }
  const tellMap = () => {
    const map = doc.querySelector(`[data-chart="${spec.map}"]`);
    map?.dispatchEvent(new (doc.defaultView?.CustomEvent ?? CustomEvent)("r2:stateset",
      { detail: { code: selected } }));
  };
  picker.addEventListener("change", () => {
    select(picker.value || null);
    tellMap();
  });
  const allBtn = make("button", "lg-item mx-all", "Show all");
  allBtn.type = "button";
  allBtn.addEventListener("click", () => {
    showAll = !showAll;
    selected = null;
    setState("state", showAll ? "all" : null);
    tellMap();
    render();
  });
  const pick = make("div", "chart-switch mx-pick");
  pick.append(picker, allBtn);
  controls.append(sw, pick);
  const list = make("ol", "tr mx");
  const small = make("p", "mx-note mx-small");
  const leanNote = make("p", "mx-note");
  plotEl.append(list, small, leanNote);

  function row(label, counts, m, cls) {
    const { n, parts } = split(counts, m.cats);
    const li = make("li", cls);
    li.append(make("span", "tr-name", label), make("span", "tr-n", `n = ${fmt(n)}`));
    const bar = make("span", "mx-bar");
    bar.setAttribute("aria-hidden", "true");
    for (const { c, pct } of parts) {
      const seg = make("i", c.stage ? `mark tr-neutral stage-${c.stage}`
        : `mark${m.true ? " mark-true" : ""} ${categoryClass(c.color)}`);
      seg.style.width = `${pct.toFixed(2)}%`;
      bar.append(seg);
    }
    li.append(bar, make("span", "tr-split",
      parts.map((p) => `${fmt(p.k)} ${p.c.label} (${Math.round(p.pct)}%)`).join(" · ")));
    return li;
  }

  function render() {
    const m = spec.measures.find((x) => x.key === measure);
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === measure)));
    allBtn.setAttribute("aria-pressed", String(showAll));
    for (const o of picker.querySelectorAll("option")) o.selected = o.value === (selected || "");
    // The key: every category of the measure, in the mix panels' style.
    const key = make("p", "mx-key");
    key.setAttribute("aria-hidden", "true");
    for (const c of m.cats) {
      const s = make("span");
      const sw_ = make("i", c.stage ? `mark tr-neutral stage-${c.stage} mx-chip`
        : `swatch ${categoryClass(c.color)}`);
      s.append(sw_, doc.createTextNode(c.label));
      key.append(s);
    }
    legendEl.replaceChildren(controls, key);
    const st = selected && spec.states[selected];
    const base = selected || showAll ? "mx-row mx-base" : "mx-row";
    const rows = [row("Overall (US)", spec.us[m.key], m, base)];
    let note = "";
    if (showAll) {
      // spec.states runs largest first.
      const big = Object.keys(spec.states).filter((c) => spec.states[c].n >= spec.small_n);
      rows.push(...big.map((c) => row(names[c] || c, spec.states[c][m.key], m, "mx-row")));
      const left = Object.keys(spec.states).length - big.length;
      if (left) {
        note = `${left} state${left === 1 ? "" : "s"} with fewer than ${spec.small_n} orders ${left === 1 ? "is" : "are"} left out; pick one to see it.`;
      }
    } else if (selected) {
      rows.push(st ? row(names[selected], st[m.key], m, "mx-row")
        : make("li", "mx-row mx-empty", `No orders from ${names[selected]} yet.`));
      if (st && st.n < spec.small_n) {
        note = `Only ${st.n} order${st.n === 1 ? "" : "s"} from ${names[selected]}: one order moves its mix by ${Math.round(100 / st.n)} points.`;
      }
    }
    list.replaceChildren(...rows);
    small.hidden = !note;
    small.textContent = note;
    leanNote.textContent = `By region, the biggest lean: ${m.lean}.`;
  }

  function select(code) {
    selected = known(code) ? code : null;
    showAll = false;
    setState("state", selected);
    render();
  }
  function setMeasure(k) {
    if (!keys.includes(k) || k === measure) return;
    measure = k;
    setState("by", k === spec.default ? null : k);
    render();
  }

  // Follow the map: its selection events bubble up from its mount.
  if (el.r2Follow) doc.removeEventListener("r2:stateselect", el.r2Follow);
  el.r2Follow = (ev) => {
    if (ev.target?.dataset?.chart === spec.map) select(ev.detail.code);
  };
  doc.addEventListener("r2:stateselect", el.r2Follow);

  render();
  return { select, selected: () => selected, setMeasure, toggleAll: () => allBtn.click() };
}
