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
  // Cumulative: what the column shows, with the week's change beside it.
  assert.deepEqual(weekTip(columns.series, 1, none, true, true),
    ["Week of Mar 11, 2024", "Ordered: 405 (+5)", "Only: 1,276 (+10)", "Total: 1,681 (+15)"]);
  assert.deepEqual(weekTip(columns.series, 1, new Set(["Only"]), true, true),
    ["Week of Mar 11, 2024", "Ordered: 405 (+5)"]);
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

test("a view's own series and lines: levels when cumulative, event lines weekly", () => {
  const el = mountPoint();
  const pipe = {
    template: "timeseries", title: "f",
    x: { label: "week", type: "date", domain: ["2026-06-01", "2026-06-22"] },
    y: { label: "n", type: "linear", domain: [0, 5], cumulative: { domain: [0, 10] } },
    series: [
      { name: "Delivered", color: "acc:timeline-ordered", stage: "delivered", view: "cumulative",
        values: [["2026-06-01", 0], ["2026-06-08", 2], ["2026-06-15", 5]] },
      { name: "Waiting", color: "acc:timeline-ordered", stage: "wait", view: "cumulative",
        values: [["2026-06-01", 3], ["2026-06-08", 3], ["2026-06-15", 4]] }],
    lines: [
      { name: "Placed", color: "var:fulfil-placed", view: "weekly",
        points: [["2026-06-04", 3], ["2026-06-11", 2], ["2026-06-18", 4]] },
      { name: "Delivered events", color: "var:fulfil-delivered", view: "weekly",
        points: [["2026-06-04", 0], ["2026-06-11", 2], ["2026-06-18", 3]] }],
    rules: [], toggles: { cumulative: true, default: "cumulative" },
  };
  const h = draw(d3, el, pipe);
  assert.equal(h.cumulative(), true, "toggles.default picks the first view");
  const legendNames = () => [...el.querySelectorAll(".chart-legend .lg-item")].map((b) => b.textContent);
  assert.deepEqual(legendNames(), ["Delivered", "Waiting"]);
  // A level's change is from the week before, and can fall.
  assert.deepEqual(weekTip(pipe.series, 2, new Set(), true, true, "2026-06-15"),
    ["Week of Jun 15, 2026 (so far)", "Delivered: 5 (+3)", "Waiting: 4 (+1)", "Total: 9 (+4)"]);
  assert.deepEqual(weekTip(pipe.series, 1, new Set(["Delivered"]), true, true).slice(1), ["Waiting: 3 (+0)"]);
  pipe.series[1].values[2][1] = 2;
  assert.equal(weekTip(pipe.series, 2, new Set(["Delivered"]), true, true)[1], "Waiting: 2 (−1)");
  pipe.series[1].values[2][1] = 4;
  // Stage series step in tone, not opacity.
  assert.ok(el.querySelector("g.tone-wait rect.bar"), "a stage series carries its tone class");
  // Levels are drawn as given, not summed: week 3 stacks 5 + 4.
  assert.deepEqual(stackAt(pipe.series, 2, new Set(), true), [[0, 5], [5, 9]]);
  const shownLines = () => [...el.querySelectorAll("g.line")].filter((g) => g.style.display !== "none").length;
  assert.equal(shownLines(), 0, "no event lines in the cumulative view");
  const rects = el.querySelectorAll("rect.bar").length;
  h.setView(false);
  assert.deepEqual(legendNames(), ["Placed", "Delivered events"]);
  assert.equal(shownLines(), 2);
  assert.ok([...el.querySelectorAll("rect.bar")].every((r) => Number(r.getAttribute("height")) === 0),
    "the levels drop away in the weekly view");
  assert.equal(el.querySelectorAll("rect.bar").length, rects, "and nothing is added");
});
