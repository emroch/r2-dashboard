// DOM-level tests for the timeseries template: draw small specs with the real
// vendored d3 into a linkedom document, then hide series the way the legend does,
// and check columns restack without adding elements, a clipped axis labels the
// columns it cuts, and the pure helpers stack and describe a week.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

import { draw, stackAt, valueAt, weekTip } from "../../src/web/charts/timeseries.js";

vm.runInThisContext(readFileSync(new URL("../../src/web/vendor/d3-7.9.0.min.js", import.meta.url), "utf8"));
const d3 = globalThis.d3;

const columns = {
  template: "timeseries", title: "t",
  x: { label: "week", type: "date", domain: ["2024-03-04", "2024-03-25"] },
  y: { label: "n", type: "linear", domain: [0, 20], clip: 20,
       cumulative: { domain: [0, 1750] } },
  series: [
    { name: "Ordered", color: "acc:timeline-ordered",
      values: [["2024-03-04", 400], ["2024-03-11", 5], ["2024-03-18", 3]] },
    { name: "Only", color: "acc:timeline-reserved",
      values: [["2024-03-04", 1266], ["2024-03-11", 10], ["2024-03-18", 0]] }],
  lines: [], rules: [{ axis: "x", value: "2024-03-20", label: "Today" }],
  toggles: { cumulative: true },
};

function mountPoint() {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="t"><div class="chart-legend"></div><div class="chart-plot"></div></div></body></html>');
  globalThis.document = document;
  globalThis.window = window;
  return document.querySelector("[data-chart]");
}

test("a week's stack and tooltip follow what the legend hides", () => {
  const none = new Set();
  assert.deepEqual(stackAt(columns.series, 1, none), [[0, 5], [5, 15]]);
  assert.deepEqual(stackAt(columns.series, 1, new Set(["Ordered"])), [null, [0, 10]]);
  assert.deepEqual(weekTip(columns.series, 1, none),
    ["Week of Mar 11, 2024", "Ordered: 5", "Only: 10", "Total: 15"]);
  assert.deepEqual(weekTip(columns.series, 1, new Set(["Only"])),
    ["Week of Mar 11, 2024", "Ordered: 5"]);
});

test("columns draw per series and week, and hiding restacks without adding any", () => {
  const el = mountPoint();
  const h = draw(d3, el, columns);
  const count = () => el.querySelectorAll("rect.bar").length;
  assert.equal(count(), 6, "two series × three weeks");
  assert.equal(el.querySelectorAll(".chart-legend .lg-item").length, 2);
  // The reveal week runs past the clipped axis: one label says its total.
  const label = el.querySelector("text.clipped");
  assert.ok(label && label.textContent.startsWith("1,666 ↑"), label && label.textContent);
  el.querySelector(".chart-legend .lg-item").dispatchEvent(new globalThis.window.Event("dblclick"));
  assert.equal(count(), 6, "isolating hides, never adds");
  assert.deepEqual([...h.hidden()], ["Only"]);
  assert.equal(el.querySelector("text.clipped").textContent.split(" ")[0], "400");
  h.redraw();
  assert.equal(count(), 6);
});

test("a lines-only chart (build cadence) draws its line and no legend", () => {
  const el = mountPoint();
  draw(d3, el, { ...columns, y: { label: "VINs/day", type: "linear", domain: [0, 60] },
                 series: [], rules: [],
                 lines: [{ name: "Cadence", color: "var:cadence-front",
                           points: [["2024-03-07", 20], ["2024-03-14", 40]], tips: [["a"], ["b"]] }] });
  assert.equal(el.querySelectorAll("rect.bar").length, 0);
  assert.equal(el.querySelectorAll("g.line circle").length, 2);
  assert.equal(el.querySelectorAll(".chart-legend .lg-item").length, 0, "one line needs no legend");
});

test("running totals stack and describe a week in either view", () => {
  const none = new Set();
  assert.equal(valueAt(columns.series[0], 2, true), 408);
  assert.deepEqual(stackAt(columns.series, 1, none, true), [[0, 405], [405, 1681]]);
  assert.equal(weekTip(columns.series, 2, none, true).at(-1), "Running total: 1,684");
});

test("the Weekly / Cumulative switch redraws in place, unclipped when cumulative", () => {
  const el = mountPoint();
  const h = draw(d3, el, columns);
  const views = [...el.querySelectorAll(".chart-controls button")].map((b) => b.textContent);
  assert.deepEqual(views, ["Weekly", "Cumulative"]);
  const count = () => el.querySelectorAll("rect.bar, text.clipped").length;
  const before = count();
  h.setView(true);
  assert.equal(h.cumulative(), true);
  assert.equal(el.querySelectorAll("text.clipped").length, 0, "a running total is drawn whole");
  assert.equal(el.querySelector('.chart-controls button[data-view="cumulative"]')
    .getAttribute("aria-pressed"), "true");
  // The last week's stack tops out at its running total, 1,684 on the fixed
  // 0–1,750 domain. linkedom has no layout, so the chart is its default 320
  // high: the plot runs from y=272 (0) up to y=22.
  const lastTop = [...el.querySelectorAll("rect.bar")].at(-1);
  assert.ok(Math.abs(Number(lastTop.getAttribute("y")) - (272 - (1684 / 1750) * 250)) < 0.01,
    lastTop.getAttribute("y"));
  h.setView(false);
  assert.equal(count(), before, "switching back adds nothing and restores the clip label");
});
