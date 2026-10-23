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
vm.runInThisContext(
  readFileSync(new URL("../../src/web/vendor/d3-7.9.0.min.js", import.meta.url), "utf8"),
);
const d3 = globalThis.d3;

const spec = {
  template: "scatter",
  title: "t",
  x: { label: "date", type: "date", domain: ["2026-06-01", "2026-12-31"] },
  y: { label: "VIN", type: "linear", domain: [0, 20000] },
  series: [
    {
      name: 'Midnight · 21"',
      color: "color:Midnight",
      symbol: "circle",
      points: [
        { x: "2026-07-01", y: 1000, lo: "2026-06-24", hi: "2026-07-08", tip: ["a"] },
        { x: "2026-08-01", y: 5000, lo: null, hi: null, tip: ["b"] },
      ],
    },
    {
      name: 'Borealis · 20"',
      color: "color:Borealis",
      symbol: "diamond",
      points: [{ x: "2026-09-01", y: 9000, lo: null, hi: null, tip: ["c"] }],
    },
  ],
  layers: [
    {
      type: "line",
      name: "Front",
      group: "Build front",
      color: "var:highlight",
      points: [
        ["2026-07-01", 900],
        ["2026-08-01", 4800],
      ],
      tips: [["f1"], ["f2"]],
    },
    {
      type: "band",
      name: "Range",
      group: "Build front",
      color: "var:highlight-band",
      points: [
        ["2026-10-01", 10000, 12000],
        ["2026-11-01", 11000, 15000],
      ],
    },
    { type: "rule", axis: "x", value: "2026-10-05", label: "Today" },
  ],
  toggles: { whiskers: true },
};

function mountPoint() {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="t"><div class="chart-legend"></div><div class="chart-plot"></div></div></body></html>',
  );
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
test(
  "redrawing never adds elements: pan, zoom, redraw in place, reset",
  { timeout: 5000 },
  async () => {
    const { draw } = await import("../../src/web/charts/scatter.js");
    const el = mountPoint();
    const h = draw(d3, el, spec);
    const count = () => h.svg.querySelectorAll("*").length;
    // Gridlines however they are drawn: lines in a grid axis, or lines classed grid.
    const grid = () => h.svg.querySelectorAll(".grid line, line.grid").length;
    const ticks = () => h.svg.querySelectorAll(".axis .tick").length;
    const first = count(),
      firstGrid = grid();
    assert.ok(first > 20 && firstGrid > 0, `drew ${first} elements, ${firstGrid} gridlines`);
    const check = (what) => {
      assert.equal(grid(), ticks(), `${what}: gridlines no longer match the ticks`);
      assert.ok(count() < first + 2 * ticks(), `${what}: ${count()} elements, from ${first}`);
    };

    h.zoomTo(3); // room to pan in every direction
    for (let i = 0; i < 20; i++) {
      h.panBy(4, 0);
      check(`horizontal drag ${i + 1}`);
    }
    for (let i = 0; i < 20; i++) {
      h.panBy(0, 4);
      check(`vertical drag ${i + 1}`);
    }
    for (let i = 0; i < 20; i++) {
      h.redraw();
      check(`redraw in place ${i + 1}`);
    }
    for (let i = 0; i < 20; i++) {
      h.zoomTo(1 + (i % 5));
      check(`zoom event ${i + 1}`);
    }
    h.reset();
    assert.equal(count(), first, "back at the full view, the chart is what it was");
    assert.equal(grid(), firstGrid);
  },
);

test("legend changes show and hide series without adding elements", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const h = draw(d3, el, spec);
  const first = h.svg.querySelectorAll("*").length;
  const shown = () =>
    [...h.svg.querySelectorAll("g[data-name]")].filter((g) => g.style.display !== "none").length;
  const all = shown();
  const entry = el.querySelector(".chart-legend .lg-item");
  entry.dispatchEvent(new globalThis.window.Event("dblclick")); // isolate it
  assert.ok(shown() < all, "isolating hid the other series");
  entry.dispatchEvent(new globalThis.window.Event("dblclick")); // and back
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
  assert.equal(
    el.querySelectorAll(".chart-legend .lg-item").length,
    2 + 1,
    "the series, then one entry for the grouped build-front layers",
  );
  // Series groups carry their category class, so CSS colors them.
  assert.ok(h.svg.querySelector("g.cat-color-midnight path.pt"));
  // The layers draw above the points, so the build front stays visible.
  const order = [...h.svg.querySelectorAll("path.pt, path.band")].map((n) =>
    n.getAttribute("class"),
  );
  assert.equal(order.at(-1), "band", order.join(" "));
  // The diamond is turned, the circle isn't.
  const diamond = h.svg.querySelector("g.cat-color-borealis path.pt").getAttribute("transform");
  const circle = h.svg.querySelector("g.cat-color-midnight path.pt").getAttribute("transform");
  assert.match(diamond, /rotate\(45\)$/);
  assert.doesNotMatch(circle, /rotate/);
});

test(
  "the grouped layers hide together, and a redraw keeps what is hidden",
  { timeout: 5000 },
  async () => {
    const { draw } = await import("../../src/web/charts/scatter.js");
    const el = mountPoint();
    let h = draw(d3, el, spec);
    const group = [...el.querySelectorAll(".chart-legend .lg-item")].at(-1);
    assert.equal(group.textContent, "Build front");
    const hiddenLayers = () =>
      [...h.svg.querySelectorAll('[data-name="Build front"]')].filter(
        (n) => n.style.display === "none",
      ).length;
    group.dispatchEvent(new globalThis.window.Event("dblclick")); // isolate: hide the rest
    group.dispatchEvent(new globalThis.window.Event("dblclick")); // show all again
    assert.equal(hiddenLayers(), 0);
    // As the resize redraw does: start from the current hidden set.
    h = draw(d3, el, spec, { hidden: new Set(["Build front"]) });
    assert.equal(hiddenLayers(), 2, "the front's line and band both stay hidden");
    assert.equal(h.hidden().has("Build front"), true);
  },
);

// §vin-by-config: a number line on x (VIN sequence) and labelled rows on y, row 0
// at the top. Panning rows out of view drops their labels instead of stacking
// them at the plot's edge.
test("a rows axis labels each row, top to bottom, over a linear x", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const r = (short) => ({ label: short, short, mark: "color:Midnight", symbol: "circle" });
  const rows = {
    template: "scatter",
    title: "t",
    x: { label: "VIN", type: "linear", domain: [0, 2000] },
    y: {
      label: "Configuration",
      type: "rows",
      rows: [r("A"), r("B"), r("C")],
      domain: [-0.6, 2.6],
    },
    series: [
      {
        name: "s",
        color: "color:Midnight",
        symbol: "circle",
        points: [
          { x: 100, y: 0.1, tip: ["a"] },
          { x: 1500, y: 2, tip: ["c"] },
        ],
      },
    ],
    layers: [],
  };
  const h = draw(d3, el, rows);
  const labels = () => h.svg.querySelectorAll(".rows-axis g.slot");
  assert.equal(labels().length, 3, "a mark per row, and no headings without groups");
  const pts = () => [...h.svg.querySelectorAll("g[data-name] path.pt")];
  const ys = pts().map((p) => Number(/,([\d.]+)\)/.exec(p.getAttribute("transform"))[1]));
  assert.ok(ys[0] < ys[1], "row 0 draws above row 2");
  const xs = pts().map((p) => Number(/translate\(([\d.]+)/.exec(p.getAttribute("transform"))[1]));
  assert.ok(xs[0] < xs[1], "x is a number line");
  h.zoomTo(3);
  assert.ok(labels().length < 3, "rows outside the zoomed view lose their labels");
});

test("a box's quartiles, median and whiskers, the furthest values within 1.5 box-lengths", async () => {
  const { boxStats } = await import("../../src/web/charts/scatter.js");
  const st = boxStats(d3, [40, 10, 30, 200, 20, 30]);
  assert.deepEqual(
    [st.q1, st.med, st.q3, st.lo, st.hi, st.min, st.max],
    [22.5, 30, 37.5, 10, 40, 10, 200],
  );
});

test("box view: a box per week of min_n+, the rest as points, the median through the boxes", async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const latency = {
    template: "scatter",
    title: "l",
    x: { label: "Order date", type: "date", domain: ["2026-06-01", "2026-08-31"] },
    y: { label: "days", type: "linear", domain: [0, 250] },
    series: [
      {
        name: "Passed",
        color: "acc:primary",
        points: [10, 20, 40, 200]
          .map((y) => ({ x: "2026-06-02", y, tip: [`p${y}`] }))
          .concat([50, 60].map((y) => ({ x: "2026-06-09", y, tip: [`q${y}`] }))),
      },
      {
        name: "Scheduled",
        color: "acc:primary",
        open: true,
        points: [{ x: "2026-06-03", y: 30, tip: ["s"] }],
      },
    ],
    layers: [
      {
        type: "line",
        name: "Median",
        color: "var:highlight",
        curve: true,
        median: true,
        points: [["2026-06-04", 30]],
        tips: [["m"]],
      },
    ],
    toggles: { boxes: { min_n: 3, unit: "days" } },
  };
  // Boxes by default, at any width.
  const h = draw(d3, el, latency);
  const boxes = h.boxes();
  assert.equal(boxes.length, 1, "the second week has two orders: points, not a box");
  assert.deepEqual([boxes[0].st.med, boxes[0].st.lo, boxes[0].st.hi], [30, 10, 40]);
  assert.deepEqual(boxes[0].tip, [
    "Week of Jun 1, 2026",
    "5 orders",
    "Median: 30 days",
    "Middle half: 20–40 days",
    "Range: 10–200 days",
  ]);
  const shown = () =>
    [...el.querySelectorAll("path.pt")].filter((p) => p.style.display !== "none").length;
  assert.equal(shown(), 4, "the outlier, the scheduled order and the small week's two");
  assert.equal(el.querySelectorAll("g.box").length, 1);
  assert.equal(
    el.querySelector("g.line circle").style.display,
    "none",
    "the box's tick marks the median",
  );
  // Points: every point back, the boxes hidden; and back, nothing added.
  el.querySelector('[data-view="points"]').dispatchEvent(new globalThis.window.Event("click"));
  assert.equal(h.boxes(), null);
  assert.equal(shown(), 7);
  el.querySelector('[data-view="boxes"]').dispatchEvent(new globalThis.window.Event("click"));
  assert.equal(el.querySelectorAll("g.box").length, 1);
  // Paint colors only in the points view: boxes and their leftover points stay
  // the series' color.
  assert.equal(el.querySelectorAll("path.pt-cat").length, 0, "box view: no paint colors");
  assert.equal(
    el.querySelector('.fl-group[data-dim="cat"]'),
    null,
    "no paint filter without point_filter",
  );
  // Isolating the passed series recomputes the box from what's left.
  el.querySelector(".chart-legend .lg-item").dispatchEvent(new globalThis.window.Event("dblclick"));
  assert.equal(h.boxes()[0].st.n, 4);
});

// §vin-by-config's rows: two groups (trim · interior), filterable by paint and interior.
const row = (color, interior, symbol = "circle") => ({
  label: `Performance · ${color} · 21" AS · ${interior}`,
  short: `${color} · 21" AS`,
  group: `Performance · ${interior}`,
  trim: "Performance",
  color,
  wheels: '21" Liquid Tungsten',
  interior,
  mark: `color:${color}`,
  symbol,
});
const configs = {
  template: "scatter",
  title: "c",
  x: { label: "VIN", type: "linear", domain: [0, 100] },
  y: {
    label: "Configuration",
    type: "rows",
    domain: [-0.6, 3.6],
    rows: [
      row("Midnight", "Black Crater Sig"),
      row("Borealis", "Black Crater Sig"),
      row("Midnight", "Coastal Cloud Sig"),
      row("Borealis", "Coastal Cloud Sig"),
    ],
  },
  series: [
    {
      name: 'Midnight · 21"',
      color: "color:Midnight",
      symbol: "circle",
      points: [
        { x: 10, y: 0.1, tip: ["a"] },
        { x: 20, y: 2, tip: ["b"] },
      ],
    },
    {
      name: 'Borealis · 21"',
      color: "color:Borealis",
      symbol: "circle",
      points: [
        { x: 30, y: 1, tip: ["c"] },
        { x: 40, y: 2.9, tip: ["d"] },
      ],
    },
  ],
  layers: [],
  filters: [
    {
      dim: "color",
      label: "Paint",
      values: [
        { value: "Midnight", label: "Midnight" },
        { value: "Borealis", label: "Borealis" },
      ],
    },
    {
      dim: "wheels",
      label: "Wheels",
      values: [{ value: '21" Liquid Tungsten', label: '21" AS', symbol: "circle" }],
    },
    {
      dim: "interior",
      label: "Interior",
      values: [
        { value: "Black Crater Sig", label: "Black Crater Sig" },
        { value: "Coastal Cloud Sig", label: "Coastal Cloud Sig" },
      ],
    },
  ],
};

test("rows lay out in slots: a heading where the group changes, then its rows", async () => {
  const { rowLayout } = await import("../../src/web/charts/scatter.js");
  const all = rowLayout(configs.y.rows);
  assert.deepEqual(
    all.slots.map((s) => s.heading || s.row.short),
    [
      "Performance · Black Crater Sig",
      'Midnight · 21" AS',
      'Borealis · 21" AS',
      "Performance · Coastal Cloud Sig",
      'Midnight · 21" AS',
      'Borealis · 21" AS',
    ],
  );
  assert.deepEqual(
    [...all.slotOf],
    [
      [0, 1],
      [1, 2],
      [2, 4],
      [3, 5],
    ],
  );
  const some = rowLayout(configs.y.rows, (r) => r.color === "Borealis");
  assert.deepEqual(
    some.slots.map((s) => s.heading || s.row.short),
    [
      "Performance · Black Crater Sig",
      'Borealis · 21" AS',
      "Performance · Coastal Cloud Sig",
      'Borealis · 21" AS',
    ],
  );
});

test("filters: a chip group per dimension with a choice; hiding drops rows and redraws whole", async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  draw(d3, el, configs);
  const groups = [...el.querySelectorAll(".fl-group")].map((g) => g.dataset.dim);
  assert.deepEqual(groups, ["color", "interior"], "one wheel, so no wheel chips");
  assert.equal(el.querySelectorAll(".rows-axis .row-head").length, 2);
  assert.equal(el.querySelectorAll(".rows-axis .row-label").length, 0, "narrow: marks only");
  assert.equal(el.querySelectorAll(".rows-axis .pt").length, 4);
  assert.equal(el.querySelector(".fl-sum").textContent, "Filters (all shown)");
  assert.equal(el.querySelectorAll("g[data-name] path.pt").length, 4);
  // Isolating Coastal Cloud leaves its group: one heading, two rows, two points.
  const cc = [...el.querySelectorAll('.fl-group[data-dim="interior"] .lg-item')].find(
    (b) => b.textContent === "Coastal Cloud Sig",
  );
  cc.dispatchEvent(new globalThis.window.Event("dblclick"));
  assert.deepEqual([...el.r2sc.hidden()], ["interior:Black Crater Sig"]);
  assert.equal(el.querySelectorAll(".rows-axis .row-head").length, 1);
  assert.equal(el.querySelectorAll(".rows-axis .pt").length, 2);
  const ys = [...el.querySelectorAll("g[data-name] path.pt")].map((p) =>
    p.getAttribute("transform"),
  );
  assert.equal(ys.length, 2, "Black Crater's points are gone");
  assert.equal(el.querySelectorAll(".fl-group").length, 2, "redrawn, not added to");
  assert.equal(
    [...el.querySelectorAll('.fl-group[data-dim="interior"] .lg-item')]
      .find((b) => b.textContent === "Black Crater Sig")
      .getAttribute("aria-pressed"),
    "false",
  );
  // The phone's disclosure says how many values are hidden (open here: no media
  // queries, so not a phone).
  assert.equal(el.querySelector(".fl-sum").textContent, "Filters (1 hidden)");
  assert.equal(el.querySelector(".fl-box").open, true);
});

test("filters on points: a series hides by its paint or wheels; layers get an Overlays group", async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const parts = (s, color, wheels) => ({ ...s, parts: { color, wheels }, true: true });
  const pts = {
    ...spec,
    series: [
      parts(spec.series[0], "Midnight", '21" Liquid Tungsten'),
      parts(spec.series[1], "Borealis", '20" Black Sand'),
    ],
    filters: [
      {
        dim: "color",
        label: "Paint",
        values: [
          { value: "Midnight", label: "Midnight" },
          { value: "Borealis", label: "Borealis" },
        ],
      },
      {
        dim: "wheels",
        label: "Wheels",
        values: [
          { value: '20" Black Sand', label: '20" AT', symbol: "diamond" },
          { value: '21" Liquid Tungsten', label: '21" AS', symbol: "circle" },
        ],
      },
    ],
  };
  const h = draw(d3, el, pts);
  assert.deepEqual(
    [...el.querySelectorAll('.fl-group[data-dim="layers"] .lg-item')].map((b) => b.textContent),
    ["Build front"],
  );
  assert.equal(el.querySelector('.fl-group[data-dim="layers"] .fl-label').textContent, "Overlays");
  assert.ok(el.querySelector("g.pt-true"), "true-color points");
  const svgBefore = h.svg;
  const at = [...el.querySelectorAll('.fl-group[data-dim="wheels"] .lg-item')].find(
    (b) => b.textContent === '20" AT',
  );
  at.dispatchEvent(new globalThis.window.Event("dblclick"));
  const shown = (name) =>
    el.querySelector(`g.pt-true[data-name='${name}']`).style.display !== "none";
  assert.equal(shown('Borealis · 20"'), true);
  assert.equal(shown('Midnight · 21"'), false, "its wheels are filtered out");
  assert.equal(el.querySelector(".fl-sum").textContent, "Filters (1 hidden)");
  assert.equal(el.r2sc.svg, svgBefore, "points hide in place: no redraw");
});

test("points with their own category: colored in the points view, filterable, plain in boxes", async () => {
  const { draw } = await import("../../src/web/charts/scatter.js");
  const el = mountPoint();
  const pts = [
    [10, "Midnight"],
    [20, "Midnight"],
    [30, "Borealis"],
    [40, null],
  ];
  const spec = {
    template: "scatter",
    title: "l",
    x: { label: "Order date", type: "date", domain: ["2026-06-01", "2026-08-31"] },
    y: { label: "days", type: "linear", domain: [0, 100] },
    series: [
      {
        name: "Passed",
        color: "acc:primary",
        points: pts.map(([y, c]) => ({
          x: "2026-06-02",
          y,
          tip: ["t"],
          ...(c ? { cat: `color:${c}` } : {}),
        })),
      },
    ],
    layers: [
      {
        type: "line",
        name: "Median",
        color: "var:highlight",
        curve: true,
        median: true,
        points: [["2026-06-04", 25]],
        tips: [["m"]],
      },
    ],
    toggles: { boxes: { min_n: 3 } },
    point_filter: {
      label: "Paint",
      values: [
        { ref: "color:Midnight", label: "Midnight" },
        { ref: "color:Borealis", label: "Borealis" },
      ],
    },
  };
  globalThis.location = { href: "http://x/?t=points", search: "?t=points" }; // the mount is "t"
  const h = draw(d3, el, spec);
  assert.equal(el.querySelectorAll("path.pt-cat.cat-color-midnight").length, 2);
  const shown = () =>
    [...el.querySelectorAll("g[data-name] path.pt")].filter((p) => p.style.display !== "none")
      .length;
  assert.equal(shown(), 4);
  // Hiding Borealis hides its point, says so, and the median follows what's left.
  const bor = [...el.querySelectorAll('.fl-group[data-dim="cat"] .lg-item')].find(
    (b) => b.textContent === "Borealis",
  );
  bor.dispatchEvent(new globalThis.window.Event("dblclick")); // isolate Borealis …
  bor.dispatchEvent(new globalThis.window.Event("dblclick")); // … and back to all
  const mid = [...el.querySelectorAll('.fl-group[data-dim="cat"] .lg-item')].find(
    (b) => b.textContent === "Midnight",
  );
  mid.dispatchEvent(new globalThis.window.Event("dblclick")); // Midnight alone
  assert.equal(shown(), 2, "only Midnight's two: Borealis and the unpainted one are filtered");
  assert.equal(el.querySelector(".fl-sum").textContent, "Filters (1 hidden)");
  assert.equal(
    el.querySelector("g.line circle").style.display,
    "none",
    "the median follows the boxes once filtered",
  );
  assert.ok(h.hidden().has("color:Borealis"));
  // The series legend is a labelled row beside the paints, and toggling it
  // leaves the paint filters alone.
  const series = el.querySelector('.fl-group[data-dim="series"]');
  assert.equal(series.querySelector(".fl-label").textContent, "Series");
  series.querySelector(".lg-item").dispatchEvent(new globalThis.window.Event("dblclick"));
  assert.ok(h.hidden().has("color:Borealis") && h.hidden().has("Median"));
  el.querySelector('[data-view="boxes"]').dispatchEvent(new globalThis.window.Event("click"));
  assert.equal(el.querySelectorAll("path.pt-cat").length, 0, "boxes: the series' color again");
  assert.equal(h.boxes().length, 0, "two Midnight orders are too few for a box");
});
