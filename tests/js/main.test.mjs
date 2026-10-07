// Unit tests for src/web/main.js (run with `npm test`, i.e. node --test).
// A fake root stands in for the document: boot() only needs querySelectorAll,
// and each element only a dataset.
import assert from "node:assert/strict";
import { test } from "node:test";

import { boot, templates } from "../../src/web/main.js";

function page(...mounts) {
  const els = mounts.map(([chart, template]) => ({ dataset: { chart, template } }));
  return { els, root: { querySelectorAll: () => els } };
}

test("importing main.js touches no DOM, and the chart templates are registered", () => {
  assert.deepEqual(Object.keys(templates), ["scatter", "timeseries"]);
});

test("a mount waits for its schedule before loading anything", async () => {
  let loads = 0, release;
  const registry = { scatter: async () => { loads++; return { mount() {} }; } };
  const { els, root } = page(["a", "scatter"]);
  const done = boot(root, registry, (el, fn) => { release = fn; });
  assert.equal(els[0].dataset.chartState, "waiting");
  assert.equal(loads, 0, "nothing loads before the chart nears the viewport");
  release();
  await done;
  assert.equal(loads, 1);
  assert.equal(els[0].dataset.chartState, "ready");
});

test("a page with no mounts boots to nothing", async () => {
  const { root } = page();
  assert.deepEqual(await boot(root), []);
});

test("each mount is handed to its template's module", async () => {
  const seen = [];
  const registry = { scatter: async () => ({ mount: (el) => seen.push(el.dataset.chart) }) };
  const { els, root } = page(["delivery-vs-vin", "scatter"], ["vin-vs-order", "scatter"]);
  await boot(root, registry);
  assert.deepEqual(seen, ["delivery-vs-vin", "vin-vs-order"]);
  assert.deepEqual(els.map((e) => e.dataset.chartState), ["ready", "ready"]);
});

test("an unknown template is marked, not thrown, and the rest still mount", async () => {
  const registry = { geo: async () => ({ mount() {} }) };
  const { els, root } = page(["a", "nope"], ["b", "geo"]);
  await boot(root, registry);
  assert.deepEqual(els.map((e) => e.dataset.chartState), ["unsupported", "ready"]);
});

test("a template that fails to load or mount is marked failed", async (t) => {
  t.mock.method(console, "error", () => {});
  const registry = {
    broken: async () => { throw new Error("404"); },
    throws: async () => ({ mount() { throw new Error("bad spec"); } }),
  };
  const { els, root } = page(["a", "broken"], ["b", "throws"]);
  await boot(root, registry);
  assert.deepEqual(els.map((e) => e.dataset.chartState), ["failed", "failed"]);
  assert.equal(console.error.mock.callCount(), 2);
});
