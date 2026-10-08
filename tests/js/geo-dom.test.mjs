// DOM-level tests for the geo template: draw a small spec on the real vendored
// atlas with the real d3 and topojson-client into a linkedom document, then do
// what a reader does (switch the measure and style, select a state).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

import { parseHTML } from "linkedom";

const vendor = (f) => new URL(`../../src/web/vendor/${f}`, import.meta.url);
vm.runInThisContext(readFileSync(vendor("d3-7.9.0.min.js"), "utf8"));
vm.runInThisContext(readFileSync(vendor("topojson-client-3.1.0.min.js"), "utf8"));
const d3 = globalThis.d3;
const atlas = { topojson: globalThis.topojson,
                us: JSON.parse(readFileSync(vendor("us-atlas-3.0.1-states-10m.json"), "utf8")) };

const spec = {
  template: "geo", title: "t", default: "orders", factory: [40.51, -88.99],
  measures: [{ key: "orders", label: "All orders" }, { key: "vin", label: "VIN assigned" },
             { key: "demand", label: "Orders + reservations" }],
  states: {
    CA: { region: "West", orders: 100, vin: 40, demand: 400, tip: ["100 orders"] },
    TX: { region: "South", orders: 25, vin: 50, demand: 90, tip: ["25 orders"] },
    VT: { region: "Northeast", orders: 2, vin: 0, demand: 9, tip: ["2 orders"] },
  },
};

function mountPoint() {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="g"><div class="chart-legend"></div><div class="chart-plot"></div></div></body></html>');
  globalThis.document = document;
  globalThis.window = window;
  globalThis.location = { href: "https://example.test/", search: "" };
  globalThis.history = { state: null, replaceState() {} };
  return document.querySelector("[data-chart]");
}

const state = (h, code) => h.svg.querySelector(`path.map-state[data-state="${code}"]`);

test("FIPS codes cover the 50 states and DC, and shares run on a square root", async () => {
  const { FIPS, share } = await import("../../src/web/charts/geo.js");
  assert.equal(Object.values(FIPS).filter((c) => c !== "PR").length, 51);
  assert.equal(share(25, 100), 0.5);
  assert.equal(share(0, 100), 0);
});

test("every state draws, keyed by postal code; a state with none is hatched", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/geo.js");
  const h = draw(d3, atlas, mountPoint(), spec);
  assert.equal(h.svg.querySelectorAll("path.map-state").length, 51);
  assert.ok(state(h, "CA").getAttribute("d").length > 100);
  assert.equal(h.svg.querySelectorAll("rect").length, 1, "only the hatch's own background");
  assert.ok(state(h, "CA").classList.contains("map-filled"));
  assert.equal(state(h, "TX").style.getPropertyValue("--v"), "0.500");
  assert.ok(state(h, "VT").classList.contains("map-filled"), "two orders still fill");
  assert.ok(state(h, "NY").classList.contains("map-none"));
  assert.match(state(h, "NY").style.getPropertyValue("fill"), /url\(#g-hatch\)/);
});

test("the measure switch refills in place", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/geo.js");
  const el = mountPoint();
  const h = draw(d3, atlas, el, spec);
  const count = () => h.svg.querySelectorAll("*").length;
  const before = count();
  el.querySelector('.chart-switch [data-key="vin"]').dispatchEvent(new globalThis.window.Event("click"));
  assert.equal(state(h, "TX").style.getPropertyValue("--v"), "1.000", "TX leads on VINs");
  assert.equal(el.querySelector('[data-key="vin"]').getAttribute("aria-pressed"), "true");
  assert.ok(state(h, "VT").classList.contains("map-none"), "VT has no VINs");
  h.setMeasure("demand");
  assert.ok(state(h, "VT").classList.contains("map-filled"));
  assert.equal(count(), before, "switching refills rather than adds");
});

test("selecting a state outlines it and fires r2:stateselect; again clears", { timeout: 5000 }, async () => {
  const { draw } = await import("../../src/web/charts/geo.js");
  const el = mountPoint();
  const h = draw(d3, atlas, el, spec);
  const got = [];
  el.addEventListener("r2:stateselect", (ev) => got.push(ev.detail.code));
  const outline = () => h.svg.querySelector("path.map-selected").getAttribute("d");
  h.select("TX");
  assert.ok(state(h, "TX").classList.contains("selected"));
  assert.equal(outline(), state(h, "TX").getAttribute("d"), "drawn above the rest");
  h.select("TX");
  assert.ok(!state(h, "TX").classList.contains("selected"));
  assert.ok(!outline());
  assert.deepEqual(got, ["TX", null]);
});
