// DOM-level tests for the statemix template: draw a small spec into a linkedom
// document, then do what a reader does (switch the measure, pick a state, select
// one on the map).
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseHTML } from "linkedom";

const spec = {
  template: "statemix", title: "t", map: "g", default: "status", small_n: 5, n: 12,
  measures: [
    { key: "status", label: "Status", true: false, lean: "Delivered at 50% of West orders (40% across all orders)",
      cats: [{ label: "Delivered", color: "neutral", stage: "delivered" },
             { label: "Waiting for a VIN", color: "neutral", stage: "wait" }] },
    { key: "color", label: "Paint", true: true, lean: "Launch Green at 60% of West orders (50% across all orders)",
      cats: [{ label: "Launch Green", color: "color:Launch Green" },
             { label: "Esker Silver", color: "color:Esker Silver" }] },
  ],
  us: { status: [4, 8], color: [6, 6] },
  states: { CA: { n: 10, status: [4, 6], color: [6, 4] }, VT: { n: 2, status: [0, 2], color: [0, 2] } },
};
const names = { CA: "California", VT: "Vermont", NY: "New York" };

function mountPoint(search = "") {
  const { document, window } = parseHTML(
    '<html><body><div data-chart="g"></div><div data-chart="m"><div class="chart-legend"></div>'
    + '<div class="chart-plot"></div></div></body></html>');
  globalThis.document = document;
  globalThis.window = window;
  globalThis.location = { href: `https://example.test/${search}`, search };
  globalThis.history = { state: null, replaceState(_, __, url) { globalThis.location = { href: String(url), search: new URL(url).search }; } };
  return document.querySelector('[data-chart="m"]');
}
const rows = (el) => [...el.querySelectorAll("li.mx-row")];

test("stateNames maps the atlas's FIPS ids to postal codes, without Puerto Rico", async () => {
  const { stateNames } = await import("../../src/web/charts/statemix.js");
  const us = { objects: { states: { geometries: [
    { id: "06", properties: { name: "California" } }, { id: "72", properties: { name: "Puerto Rico" } }] } } };
  assert.deepEqual(stateNames(us), { CA: "California" });
});

test("with nothing selected, one US row; the key and lean follow the measure", async () => {
  const { draw } = await import("../../src/web/charts/statemix.js");
  const el = mountPoint();
  const h = draw(el, spec, names);
  assert.equal(rows(el).length, 1);
  assert.match(rows(el)[0].textContent, /Overall \(US\).*n = 12.*4 Delivered \(33%\) · 8 Waiting for a VIN \(67%\)/);
  assert.ok(el.querySelector(".mx-bar i.stage-delivered"));
  h.setMeasure("color");
  assert.ok(el.querySelector(".mx-bar i.mark-true.cat-color-launch-green"));
  assert.match(el.querySelector(".chart-legend").textContent, /Launch Green/);
  assert.match(el.textContent, /Launch Green at 60% of West orders/);
  assert.equal(globalThis.location.search, "?by=color");
});

test("a state selected on the map adds its row under the US baseline", async () => {
  const { draw } = await import("../../src/web/charts/statemix.js");
  const el = mountPoint();
  const h = draw(el, spec, names);
  const map = el.ownerDocument.querySelector('[data-chart="g"]');
  map.dispatchEvent(new globalThis.window.CustomEvent("r2:stateselect", { bubbles: true, detail: { code: "CA" } }));
  assert.equal(h.selected(), "CA");
  assert.ok(rows(el)[0].classList.contains("mx-base"));
  assert.match(rows(el)[1].textContent, /California.*n = 10/);
  assert.ok(el.querySelector(".mx-small").hidden, "10 orders isn't small");
  map.dispatchEvent(new globalThis.window.CustomEvent("r2:stateselect", { bubbles: true, detail: { code: null } }));
  assert.equal(rows(el).length, 1);
});

test("Show all lists the states with small_n orders or more, largest first", async () => {
  const { draw } = await import("../../src/web/charts/statemix.js");
  const el = mountPoint("?state=CA");
  const big = { ...spec, states: { ...spec.states, TX: { n: 6, status: [1, 5], color: [3, 3] } } };
  const h = draw(el, big, { ...names, TX: "Texas" });
  const got = [];
  el.ownerDocument.querySelector('[data-chart="g"]').addEventListener("r2:stateset", (ev) => got.push(ev.detail.code));
  h.toggleAll();
  assert.equal(h.selected(), null, "the list replaces the single state");
  assert.deepEqual(got, [null], "and clears it on the map");
  assert.equal(globalThis.location.search, "?state=all");
  assert.deepEqual(rows(el).map((r) => r.querySelector(".tr-name").textContent),
    ["Overall (US)", "California", "Texas"]);
  assert.match(el.querySelector(".mx-small").textContent, /1 state with fewer than 5 orders is left out/);
  assert.equal(el.querySelector(".mx-all").getAttribute("aria-pressed"), "true");
  h.select("VT");
  assert.equal(rows(el).length, 2, "selecting a state ends the list");
  assert.equal(el.querySelector(".mx-all").getAttribute("aria-pressed"), "false");
});

test("a small state carries the small-n note; a state with no orders says so", async () => {
  const { draw } = await import("../../src/web/charts/statemix.js");
  const el = mountPoint("?state=VT");
  const h = draw(el, spec, names);
  assert.equal(h.selected(), "VT", "read from the URL");
  assert.ok(!el.querySelector(".mx-small").hidden);
  assert.match(el.querySelector(".mx-small").textContent, /Only 2 orders from Vermont: one order moves its mix by 50 points/);
  h.select("NY");
  assert.match(rows(el)[1].textContent, /No orders from New York yet/);
});

test("the picker selects on the map too", async () => {
  const { draw } = await import("../../src/web/charts/statemix.js");
  const el = mountPoint();
  draw(el, spec, names);
  const got = [];
  el.ownerDocument.querySelector('[data-chart="g"]').addEventListener("r2:stateset", (ev) => got.push(ev.detail.code));
  const picker = el.querySelector("select.mx-picker");
  picker.querySelector('option[value="CA"]').selected = true;
  picker.dispatchEvent(new globalThis.window.Event("change"));
  assert.deepEqual(got, ["CA"]);
  assert.equal(globalThis.location.search, "?state=CA");
});
