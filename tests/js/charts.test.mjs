// Unit tests for the browser-drawn chart pieces: the scatter template's pure
// helpers, the house legend's logic, URL state, the view-data fetch, the lazy
// library loader, and the vendored library's checksum.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { categoryClass, layerEntries, nearest, ROTATE, SYMBOLS, whiskerPath, zoomAllowed }
  from "../../src/web/charts/scatter.js";
import { isolate, toggle } from "../../src/web/lib/legend.js";
import { D3_FILE, loadD3 } from "../../src/web/lib/load.js";
import { get, set, whiskersShown } from "../../src/web/state.js";

test("category references map to the classes render/categories.py writes", () => {
  assert.equal(categoryClass("color:Launch Green"), "cat-color-launch-green");
  assert.equal(categoryClass('wheels:20" Black Sand'), "cat-wheels-20-black-sand");
  assert.equal(categoryClass("r1_model:No R1"), "cat-r1_model-no-r1");
});

test("every wheel symbol in dimensions.yaml has a d3 symbol", () => {
  const dims = readFileSync(new URL("../../src/conf/dimensions.yaml", import.meta.url), "utf8");
  const used = [...dims.matchAll(/^\s+symbol: (\S+)/gm)].map((m) => m[1]);
  assert.ok(used.length >= 4);
  for (const s of used) assert.ok(SYMBOLS[s], `no d3 symbol for ${s}`);
});

test("a diamond is a square turned 45°, so it keeps a 1:1 shape", () => {
  assert.equal(SYMBOLS.diamond, "symbolSquare");
  assert.equal(ROTATE.diamond, 45);
  assert.equal(ROTATE.circle, undefined);
});

test("the chart zooms only on purpose, so the page keeps scrolling", () => {
  assert.equal(zoomAllowed({ type: "wheel" }), false, "a plain wheel scrolls the page");
  assert.equal(zoomAllowed({ type: "wheel", ctrlKey: true }), true, "a trackpad pinch");
  assert.equal(zoomAllowed({ type: "wheel", metaKey: true }), true, "⌘ + wheel");
  assert.equal(zoomAllowed({ type: "touchstart", touches: [1] }), false, "one finger scrolls");
  assert.equal(zoomAllowed({ type: "touchstart", touches: [1, 2] }), true, "two fingers zoom");
  assert.equal(zoomAllowed({ type: "mousedown", button: 0 }), true, "a mouse drag pans");
  assert.equal(zoomAllowed({ type: "mousedown", button: 2 }), false);
});

test("grouped layers are one legend entry, in order", () => {
  const entries = layerEntries([
    { type: "line", name: "Front", group: "Build front", color: "var:a" },
    { type: "band", name: "Range", group: "Build front", color: "var:b" },
    { type: "line", name: "Other", color: "var:c" },
    { type: "rule", label: "Today" }]);
  assert.deepEqual(entries, [{ name: "Build front", accent: "a" }, { name: "Other", accent: "c" }]);
});

test("a whisker is the window's line plus a cap at each end", () => {
  assert.equal(whiskerPath(10, 50, 100), "M10,100H50M10,96V104M50,96V104");
});

test("nearest finds the closest candidate within the radius, else null", () => {
  const c = [{ x: 0, y: 0, id: "a" }, { x: 10, y: 0, id: "b" }];
  assert.equal(nearest(c, 8, 1).id, "b");
  assert.equal(nearest(c, 2, 2).id, "a");
  assert.equal(nearest(c, 100, 100), null);
});

test("legend: click toggles one entry; double-click isolates, then restores", () => {
  const names = ["a", "b", "c"];
  assert.deepEqual([...toggle(new Set(), "b")], ["b"]);
  assert.deepEqual([...toggle(new Set(["b"]), "b")], []);
  const alone = isolate(new Set(), "a", names);
  assert.deepEqual([...alone].sort(), ["b", "c"]);
  assert.deepEqual([...isolate(alone, "a", names)], [], "isolating it again shows all");
  assert.deepEqual([...isolate(alone, "b", names)].sort(), ["a", "c"], "or moves to another");
});

test("URL state: read, set and clear a parameter, keeping the rest", () => {
  assert.equal(get("whiskers", "?whiskers=0&x=1"), "0");
  assert.equal(whiskersShown("?whiskers=0"), false);
  assert.equal(whiskersShown(""), true);
  const calls = [];
  const hist = { state: null, replaceState: (s, t, u) => calls.push(String(u)) };
  const loc = { href: "https://example.test/r2/?x=1#sec-10" };
  set("whiskers", "0", loc, hist);
  assert.equal(calls[0], "https://example.test/r2/?x=1&whiskers=0#sec-10");
  set("x", null, { href: calls[0] }, hist);
  assert.equal(calls[1], "https://example.test/r2/?whiskers=0#sec-10");
});

test("the view data is fetched once and shared", async () => {
  const { view } = await import("../../src/web/data.js");
  let n = 0;
  const fake = async () => { n++; return { ok: true, json: async () => ({ version: 1, components: {} }) }; };
  const [a, b] = await Promise.all([view("x.json", fake), view("x.json", fake)]);
  assert.equal(n, 1);
  assert.equal(a, b);
});

test("d3 loads from the hashed asset directory, once", async () => {
  delete globalThis.d3;
  const appended = [];
  const doc = { head: { append: (s) => { appended.push(s); setTimeout(() => { globalThis.d3 = { ok: 1 }; s.onload(); }); } },
                createElement: () => ({}) };
  const base = "https://example.test/assets/abcd1234/lib/load.js";
  const [a, b] = await Promise.all([loadD3(doc, base), loadD3(doc, base)]);
  assert.equal(appended.length, 1);
  assert.equal(appended[0].src, "https://example.test/assets/abcd1234/" + D3_FILE);
  assert.equal(a, b);
  delete globalThis.d3;
});

test("vendored files match the checksums in vendor/README.md", () => {
  const dir = new URL("../../src/web/vendor/", import.meta.url);
  const readme = readFileSync(new URL("README.md", dir), "utf8");
  const rows = [...readme.matchAll(/^\| `([^`]+)` \|.*\| `([0-9a-f]{64})` \|/gm)];
  assert.ok(rows.length >= 1, "no vendored files listed");
  for (const [, file, sum] of rows) {
    const got = createHash("sha256").update(readFileSync(new URL(file, dir))).digest("hex");
    assert.equal(got, sum, file);
  }
  assert.ok(rows.some(([, f]) => f === D3_FILE.replace("vendor/", "")), "load.js's d3 is listed");
});
