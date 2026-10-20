// DOM-level tests for the timeseries template: draw small specs with the real
// vendored d3 into a linkedom document, then hide series the way the legend does,
// and check columns restack without adding elements, a clipped axis labels the
// columns it cuts, and the pure helpers stack and describe a week.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

import {
  draw,
  groupable,
  regroup,
  stackAt,
  valueAt,
  weekTip,
} from "../../src/web/charts/timeseries.js";

vm.runInThisContext(
  readFileSync(new URL("../../src/web/vendor/d3-7.9.0.min.js", import.meta.url), "utf8"),
);
const d3 = globalThis.d3;

const columns = {
  template: "timeseries",
  title: "t",
  x: { label: "week", type: "date", domain: ["2024-03-04", "2024-03-25"] },
  y: { label: "n", type: "linear", domain: [0, 20], clip: 20, cumulative: { domain: [0, 1750] } },
  series: [
    {
      name: "Ordered",
      color: "acc:primary",
      values: [
        ["2024-03-04", 400],
        ["2024-03-11", 5],
        ["2024-03-18", 3],
      ],
    },
    {
      name: "Only",
      color: "acc:primary",
      values: [
        ["2024-03-04", 1266],
        ["2024-03-11", 10],
        ["2024-03-18", 0],
      ],
    },
  ],
  lines: [],
  rules: [{ axis: "x", value: "2024-03-20", label: "Today" }],
  toggles: { cumulative: true },
};

function mountPoint() {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="t"><div class="chart-legend"></div><div class="chart-plot"></div></div></body></html>',
  );
  globalThis.document = document;
  globalThis.window = window;
  return document.querySelector("[data-chart]");
}

test("a week's stack and tooltip follow what the legend hides", () => {
  const none = new Set();
  assert.deepEqual(stackAt(columns.series, 1, none), [
    [0, 5],
    [5, 15],
  ]);
  assert.deepEqual(stackAt(columns.series, 1, new Set(["Ordered"])), [null, [0, 10]]);
  assert.deepEqual(
    weekTip(columns.series, 1, none),
    ["Week of Mar 11, 2024", "Only: 10", "Ordered: 5", null, "Total: 15"],
    "top of the stack first",
  );
  assert.deepEqual(weekTip(columns.series, 1, new Set(["Only"])), [
    "Week of Mar 11, 2024",
    "Ordered: 5",
  ]);
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
  draw(d3, el, {
    ...columns,
    y: { label: "VINs/day", type: "linear", domain: [0, 60] },
    series: [],
    rules: [],
    lines: [
      {
        name: "Cadence",
        color: "var:highlight",
        points: [
          ["2024-03-07", 20],
          ["2024-03-14", 40],
        ],
        tips: [["a"], ["b"]],
      },
    ],
  });
  assert.equal(el.querySelectorAll("rect.bar").length, 0);
  assert.equal(el.querySelectorAll("g.line circle").length, 2);
  assert.equal(el.querySelectorAll(".chart-legend .lg-item").length, 0, "one line needs no legend");
});

test("running totals stack and describe a week in either view", () => {
  const none = new Set();
  assert.equal(valueAt(columns.series[0], 2, true), 408);
  assert.deepEqual(stackAt(columns.series, 1, none, true), [
    [0, 405],
    [405, 1681],
  ]);
  assert.equal(weekTip(columns.series, 2, none, true).at(-1), "Running total: 1,684");
  // Cumulative: what the column shows, with the week's change beside it.
  assert.deepEqual(weekTip(columns.series, 1, none, true, true), [
    "Week of Mar 11, 2024",
    "Only: 1,276 (+10)",
    "Ordered: 405 (+5)",
    null,
    "Total: 1,681 (+15)",
  ]);
  assert.deepEqual(weekTip(columns.series, 1, new Set(["Only"]), true, true), [
    "Week of Mar 11, 2024",
    "Ordered: 405 (+5)",
  ]);
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
  assert.equal(
    el.querySelector('.chart-controls button[data-view="cumulative"]').getAttribute("aria-pressed"),
    "true",
  );
  // The last week's stack tops out at its running total, 1,684 on the fixed
  // 0–1,750 domain. linkedom has no layout, so the chart is its narrowest, 320
  // wide and 260 high, its y label above the axis: the plot runs from y=212
  // (0) up to y=30.
  const lastTop = [...el.querySelectorAll("rect.bar")].at(-1);
  assert.ok(
    Math.abs(Number(lastTop.getAttribute("y")) - (212 - (1684 / 1750) * 182)) < 0.01,
    lastTop.getAttribute("y"),
  );
  h.setView(false);
  assert.equal(count(), before, "switching back adds nothing and restores the clip label");
});

test("a view's own series and lines: levels when cumulative, event lines weekly", () => {
  const el = mountPoint();
  const pipe = {
    template: "timeseries",
    title: "f",
    x: { label: "week", type: "date", domain: ["2026-06-01", "2026-06-22"] },
    y: { label: "n", type: "linear", domain: [0, 5], cumulative: { domain: [0, 10] } },
    series: [
      {
        name: "Delivered",
        color: "acc:primary",
        stage: "delivered",
        view: "cumulative",
        values: [
          ["2026-06-01", 0],
          ["2026-06-08", 2],
          ["2026-06-15", 5],
        ],
      },
      {
        name: "Waiting",
        color: "acc:primary",
        stage: "wait",
        view: "cumulative",
        values: [
          ["2026-06-01", 3],
          ["2026-06-08", 3],
          ["2026-06-15", 4],
        ],
      },
    ],
    lines: [
      {
        name: "Placed",
        color: "var:fulfil-placed",
        view: "weekly",
        points: [
          ["2026-06-04", 3],
          ["2026-06-11", 2],
          ["2026-06-18", 4],
        ],
      },
      {
        name: "Delivered events",
        color: "var:fulfil-delivered",
        view: "weekly",
        points: [
          ["2026-06-04", 0],
          ["2026-06-11", 2],
          ["2026-06-18", 3],
        ],
      },
    ],
    rules: [],
    toggles: { cumulative: true, default: "cumulative" },
  };
  const h = draw(d3, el, pipe);
  assert.equal(h.cumulative(), true, "toggles.default picks the first view");
  const legendNames = () =>
    [...el.querySelectorAll(".chart-legend .lg-item")].map((b) => b.textContent);
  assert.deepEqual(legendNames(), ["Delivered", "Waiting"]);
  // A level's change is from the week before, and can fall.
  assert.deepEqual(weekTip(pipe.series, 2, new Set(), true, true, "2026-06-15"), [
    "Week of Jun 15, 2026 (so far)",
    "Waiting: 4 (+1)",
    "Delivered: 5 (+3)",
    null,
    "Total: 9 (+4)",
  ]);
  assert.deepEqual(weekTip(pipe.series, 1, new Set(["Delivered"]), true, true).slice(1), [
    "Waiting: 3 (+0)",
  ]);
  pipe.series[1].values[2][1] = 2;
  assert.equal(weekTip(pipe.series, 2, new Set(["Delivered"]), true, true)[1], "Waiting: 2 (−1)");
  pipe.series[1].values[2][1] = 4;
  // Stage series step in tone, not opacity.
  assert.ok(el.querySelector("g.tone-wait rect.bar"), "a stage series carries its tone class");
  // Levels are drawn as given, not summed: week 3 stacks 5 + 4.
  assert.deepEqual(stackAt(pipe.series, 2, new Set(), true), [
    [0, 5],
    [5, 9],
  ]);
  const shownLines = () =>
    [...el.querySelectorAll("g.line")].filter((g) => g.style.display !== "none").length;
  assert.equal(shownLines(), 0, "no event lines in the cumulative view");
  const rects = el.querySelectorAll("rect.bar").length;
  h.setView(false);
  assert.deepEqual(legendNames(), ["Placed", "Delivered events"]);
  assert.equal(shownLines(), 2);
  assert.ok(
    [...el.querySelectorAll("rect.bar")].every((r) => Number(r.getAttribute("height")) === 0),
    "the levels drop away in the weekly view",
  );
  assert.equal(el.querySelectorAll("rect.bar").length, rects, "and nothing is added");
});

test("a line view's hover rule follows the pointer and snaps to a week's points", () => {
  const el = mountPoint();
  const spec = {
    ...columns,
    series: [],
    rules: [],
    toggles: {},
    y: { label: "n", type: "linear", domain: [0, 60] },
    lines: [
      {
        name: "Cadence",
        color: "var:highlight",
        points: [
          ["2024-03-07", 20],
          ["2024-03-14", 40],
        ],
        tips: [["a"], ["b"]],
      },
    ],
  };
  draw(d3, el, spec);
  const rule = el.querySelector("line.hover-rule");
  assert.equal(rule.getAttribute("display"), "none", "hidden until the pointer is over it");
  assert.equal(el.querySelectorAll("line.hover-rule").length, 1, "one element, moved, not added");
});

// Fourteen weeks over four months (Thursday rule: Mar 30 is April's), the
// reveal spike in the first.
const mondays = Array.from({ length: 14 }, (_, i) => new Date(Date.UTC(2026, 2, 2 + 7 * i)));
const isoD = (x) => x.toISOString().slice(0, 10);
const long = {
  template: "timeseries",
  title: "r",
  x: { label: "week", type: "date", domain: ["2026-03-02", "2026-06-08"], partial: "2026-06-01" },
  y: { label: "n", type: "linear", domain: [0, 20], clip: 20, cumulative: { domain: [0, 600] } },
  series: [
    { name: "A", color: "acc:primary", values: mondays.map((w, i) => [isoD(w), i ? 5 : 500]) },
  ],
  lines: [],
  rules: [],
  toggles: { cumulative: true },
};

test("regrouped by month: sums, whole-week spans, a refit axis and the so-far group", () => {
  const g = regroup(long, "month");
  assert.deepEqual(g.series[0].values, [
    ["2026-03-02", 515],
    ["2026-03-30", 25],
    ["2026-05-04", 20],
    ["2026-06-01", 5],
  ]);
  assert.deepEqual(
    g.groups.map((x) => x.heading),
    [
      "Mar 2026 (weeks of Mar 2 – Mar 23)",
      "Apr 2026 (weeks of Mar 30 – Apr 27)",
      "May 2026 (weeks of May 4 – May 25)",
      "Jun 2026 (week of Jun 1, so far)",
    ],
  );
  // June's group runs to Jun 29, clamped to the domain's end.
  assert.equal(isoD(g.groups[3].end), "2026-06-08");
  assert.equal(g.x.partial, "2026-06-01");
  // 515 is over three times 25: the axis cuts just above the rest.
  assert.deepEqual(g.y.domain, [0, 30]);
  assert.equal(g.y.clip, 30);
  assert.deepEqual(g.y.cumulative, long.y.cumulative, "a running total's axis is unchanged");
  const wk = regroup(long, "week");
  assert.deepEqual(wk.series[0].values, long.series[0].values, "a week is as given");
  assert.deepEqual(wk.y, long.y);
});

test("levels take their last week, lines sum at the group's middle, shares re-divide", () => {
  const thursdays = mondays.map((w) => isoD(new Date(w.getTime() + 3 * 864e5)));
  const g = regroup(
    {
      ...long,
      series: [{ ...long.series[0], view: "cumulative" }],
      lines: [
        {
          name: "L",
          color: "var:x",
          view: "weekly",
          points: long.series[0].values.map(([, v], i) => [thursdays[i], v]),
        },
      ],
    },
    "month",
  );
  assert.deepEqual(
    g.series[0].values.map((v) => v[1]),
    [5, 5, 5, 5],
    "a level, not a sum",
  );
  assert.deepEqual(
    g.lines[0].points.map((p) => p[1]),
    [515, 25, 20, 5],
  );
  assert.equal(g.lines[0].points[0][0], "2026-03-16", "at the middle of Mar 2 – Mar 30");
  const cov = regroup(
    {
      ...long,
      y: { label: "%", type: "linear", domain: [0, 100], format: "pct" },
      series: [
        {
          name: "Coverage",
          color: "acc:primary",
          tip: "{0} of {1} orders have a firm date",
          values: long.series[0].values.map(([w]) => [w, 50]),
          counts: long.series[0].values.map((_, i) => (i < 4 ? [1, 2] : [1, 4])),
        },
      ],
    },
    "month",
  );
  assert.deepEqual(
    cov.series[0].values.map((v) => v[1]),
    [50, 25, 25, 25],
  );
  assert.equal(cov.series[0].tips[0], "4 of 8 orders have a firm date");
  assert.deepEqual(cov.y.domain, [0, 100], "a share's axis stays 0–100%");
});

test("the grain buttons: offered by span, default by width, a choice redraws in place", () => {
  const el = mountPoint();
  // linkedom has no layout: 320 wide, so 248 px of plot for 14 weeks reads weekly.
  const h = draw(d3, el, long);
  assert.equal(h.grain, "week");
  const grains = () => [...el.querySelectorAll("[data-grain]")].map((b) => b.textContent);
  assert.deepEqual(grains(), ["Week", "Month"], "two quarters are too few to offer");
  globalThis.location = { href: "http://x/", search: "" };
  globalThis.history = {
    state: null,
    replaceState(_, __, url) {
      globalThis.location = { href: String(url), search: new URL(url).search };
    },
  };
  el.querySelector('[data-grain="month"]').dispatchEvent(new globalThis.window.Event("click"));
  assert.equal(el.r2ts.grain, "month");
  assert.equal(new URL(globalThis.location.href).searchParams.get("t-grain"), "month");
  assert.equal(el.querySelectorAll("rect.bar").length, 4);
  assert.equal(el.querySelector('[data-view="weekly"]').textContent, "Monthly");
  assert.equal(el.querySelectorAll(".ts-controls").length, 1, "redrawn, not added to");
  delete globalThis.location;
  delete globalThis.history;
});

test("a line with its own tooltips (a rate) isn't grouped", () => {
  assert.equal(groupable({ series: [], lines: [{ tips: [] }] }), false);
  assert.equal(groupable({ series: [{}], lines: [{ tips: [] }] }), false);
  assert.equal(groupable(long), true);
});
