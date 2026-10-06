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
    { type: "line", name: "Front", color: "var:cadence-front", points: [["2026-07-01", 900], ["2026-08-01", 4800]],
      tips: [["f1"], ["f2"]] },
    { type: "band", name: "Range", color: "var:cadence-band", points: [["2026-10-01", 10000, 12000], ["2026-11-01", 11000, 15000]] },
    { type: "rule", axis: "x", value: "2026-10-05", label: "Today" }],
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
  assert.equal(el.querySelectorAll(".chart-legend .lg-item").length, 2 + 2, "series + accent layers");
  // Series groups carry their category class, so CSS colors them.
  assert.ok(h.svg.querySelector("g.cat-color-midnight path.pt"));
});
