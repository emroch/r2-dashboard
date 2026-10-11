// DOM-level tests for the scatter template: draw a small spec with the real
// vendored d3 into a linkedom document, then redraw it the ways a reader does
// (pan, zoom, whisker toggle, legend) and check nothing accumulates. A redraw
// that added elements instead of updating them hung the page.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

// The vendored UMD bundle, run as the page runs it: a classic script that
// defines the d3 global.
vm.runInThisContext(readFileSync(new URL("../../src/web/vendor/d3-7.9.0.min.js", import.meta.url), "utf8"));
const d3 = globalThis.d3;

const spec = {
  template: "scatter", title: "t",
  x: { label: "date", type: "date", domain: ["2026-06-01", "2026-12-31"] },
  y: { label: "VIN", type: "linear", domain: [0, 20000] },
  series: [
    { name: "Midnight · 21\"", color: "color:Midnight", symbol: "circle", points: [
      { x: "2026-07-01", y: 1000, lo: "2026-06-24", hi: "2026-07-08", tip: ["a"] },
      { x: "2026-08-01", y: 5000, lo: null, hi: null, tip: ["b"] }] },
    { name: "Borealis · 20\"", color: "color:Borealis", symbol: "diamond", points: [
      { x: "2026-09-01", y: 9000, lo: null, hi: null, tip: ["c"] }] }],
  layers: [
    { type: "line", name: "Front", group: "Build front", color: "var:cadence-front",
      points: [["2026-07-01", 900], ["2026-08-01", 4800]], tips: [["f1"], ["f2"]] },
    { type: "band", name: "Range", group: "Build front", color: "var:cadence-band",
      points: [["2026-10-01", 10000, 12000], ["2026-11-01", 11000, 15000]] },
    { type: "rule", axis: "x", value: "2026-10-05", label: "Today" }],
  toggles: { whiskers: true },
};

function mountPoint() {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="t"><div class="chart-legend"></div><div class="chart-plot"></div></div></body></html>');
  globalThis.document = document;
  globalThis.window = window;
  globalThis.location = { href: "https://example.test/", search: "" };
  globalThis.history = { state: null, replaceState() {} };
  return document.querySelector("[data-chart]");
}

// Each redraw is checked as it happens, so a leak fails on its first repeat
// instead of compounding (a doubling leak run for long would hang the test the
// way it hung the page). The timeout is only a backstop.
//
// The redraws that matter are the ones that leave an axis's ticks where they
// were: d3's axis keys ticks by position, so a tick that doesn't move survives
// the redraw along with anything added to it. A horizontal drag leaves the y
// ticks in place, a vertical drag the x ticks, and a whisker toggle both. The
// old gridlines (tick lines cloned on each redraw) doubled on exactly those.
test("redrawing never adds elements: pan, zoom, redraw in place, reset", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const h = draw(d3, el, spec);
  const count = () => h.svg.querySelectorAll("*").length;
  // Gridlines however they are drawn: lines in a grid axis, or lines classed grid.
  const grid = () => h.svg.querySelectorAll(".grid line, line.grid").length;
  const ticks = () => h.svg.querySelectorAll(".axis .tick").length;
  const first = count(), firstGrid = grid();
  assert.ok(first > 20 && firstGrid > 0, `drew ${first} elements, ${firstGrid} gridlines`);
  const check = (what) => {
    assert.equal(grid(), ticks(), `${what}: gridlines no longer match the ticks`);
    assert.ok(count() < first + 2 * ticks(), `${what}: ${count()} elements, from ${first}`);
  };

  h.zoomTo(3);                                    // room to pan in every direction
  for (let i = 0; i < 20; i++) { h.panBy(4, 0); check(`horizontal drag ${i + 1}`); }
  for (let i = 0; i < 20; i++) { h.panBy(0, 4); check(`vertical drag ${i + 1}`); }
  for (let i = 0; i < 20; i++) { h.redraw(); check(`redraw in place ${i + 1}`); }
  for (let i = 0; i < 20; i++) { h.zoomTo(1 + (i % 5)); check(`zoom event ${i + 1}`); }
  h.reset();
  assert.equal(count(), first, "back at the full view, the chart is what it was");
  assert.equal(grid(), firstGrid);
});

test("legend changes show and hide series without adding elements", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const h = draw(d3, el, spec);
  const first = h.svg.querySelectorAll("*").length;
  const shown = () => [...h.svg.querySelectorAll("g[data-name]")]
    .filter((g) => g.style.display !== "none").length;
  const all = shown();
  const entry = el.querySelector(".chart-legend .lg-item");
  entry.dispatchEvent(new globalThis.window.Event("dblclick"));   // isolate it
  assert.ok(shown() < all, "isolating hid the other series");
  entry.dispatchEvent(new globalThis.window.Event("dblclick"));   // and back
  assert.equal(shown(), all);
  assert.equal(h.svg.querySelectorAll("*").length, first);
});

test("the drawn chart has every point, whisker and layer", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const h = draw(d3, el, spec);
  assert.equal(h.svg.querySelectorAll("path.pt").length, 3);
  assert.equal(h.svg.querySelectorAll("path.whisker").length, 1, "only the windowed point");
  assert.equal(h.svg.querySelectorAll("path.band").length, 1);
  assert.equal(h.svg.querySelectorAll("g.line").length, 1);
  assert.equal(h.svg.querySelectorAll("g.rule").length, 1);
  assert.equal(el.querySelectorAll(".chart-legend .lg-item").length, 2 + 1,
               "the series, then one entry for the grouped build-front layers");
  // Series groups carry their category class, so CSS colors them.
  assert.ok(h.svg.querySelector("g.cat-color-midnight path.pt"));
  // The layers draw above the points, so the build front stays visible.
  const order = [...h.svg.querySelectorAll("path.pt, path.band")].map((n) => n.getAttribute("class"));
  assert.equal(order.at(-1), "band", order.join(" "));
  // The diamond is turned, the circle isn't.
  const diamond = h.svg.querySelector("g.cat-color-borealis path.pt").getAttribute("transform");
  const circle = h.svg.querySelector("g.cat-color-midnight path.pt").getAttribute("transform");
  assert.match(diamond, /rotate\(45\)$/);
  assert.doesNotMatch(circle, /rotate/);
});

test("the grouped layers hide together, and a redraw keeps what is hidden", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  let h = draw(d3, el, spec);
  const group = [...el.querySelectorAll(".chart-legend .lg-item")].at(-1);
  assert.equal(group.textContent, "Build front");
  const hiddenLayers = () => [...h.svg.querySelectorAll('[data-name="Build front"]')]
    .filter((n) => n.style.display === "none").length;
  group.dispatchEvent(new globalThis.window.Event("dblclick"));     // isolate: hide the rest
  group.dispatchEvent(new globalThis.window.Event("dblclick"));     // show all again
  assert.equal(hiddenLayers(), 0);
  // As the resize redraw does: start from the current hidden set.
  h = draw(d3, el, spec, { hidden: new Set(["Build front"]) });
  assert.equal(hiddenLayers(), 2, "the front's line and band both stay hidden");
  assert.equal(h.hidden().has("Build front"), true);
});

// §10 and §13: a number line on x (VIN sequence) and labelled rows on y, row 0
// at the top. Panning rows out of view drops their labels instead of stacking
// them at the plot's edge.
test("a rows axis labels each row, top to bottom, over a linear x", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const rows = { template: "scatter", title: "t",
    x: { label: "VIN", type: "linear", domain: [0, 2000] },
    y: { label: "Configuration", type: "rows", rows: ["A", "B", "C"], domain: [-0.6, 2.6] },
    series: [{ name: "s", color: "color:Midnight", symbol: "circle",
               points: [{ x: 100, y: 0.1, tip: ["a"] }, { x: 1500, y: 2, tip: ["c"] }] }],
    layers: [] };
  const h = draw(d3, el, rows);
  const labels = () => [...h.svg.querySelectorAll("g.axis")][1].querySelectorAll(".tick text");
  assert.deepEqual([...labels()].map((t) => t.textContent), ["A", "B", "C"]);
  const ys = [...h.svg.querySelectorAll("path.pt")].map((p) => Number(/,([\d.]+)\)/.exec(p.getAttribute("transform"))[1]));
  assert.ok(ys[0] < ys[1], "row 0 draws above row 2");
  const xs = [...h.svg.querySelectorAll("path.pt")].map((p) => Number(/translate\(([\d.]+)/.exec(p.getAttribute("transform"))[1]));
  assert.ok(xs[0] < xs[1], "x is a number line");
  h.zoomTo(3);
  assert.ok(labels().length < 3, "rows outside the zoomed view lose their labels");
});
