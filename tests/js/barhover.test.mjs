// The bar hover popovers (lib/barhover.js) in a linkedom document: a segment's
// data-tip lines show in its frame's tooltip, and leaving the bars hides it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseHTML } from "linkedom";

import { tipLines, wireBarHover } from "../../src/web/lib/barhover.js";

function page() {
  const { document, window } = parseHTML(
    '<html><body><figure class="r2c"><span class="tr-bar">'
    + '<i class="mark" data-tip="Catalina Cove\nDelivered: 52 of 236 (22%)"></i></span>'
    + '<p class="other">x</p></figure></body></html>');
  globalThis.window = window;
  return document;
}
const fire = (doc, type, target, related = null) => {
  const ev = new doc.defaultView.Event(type, { bubbles: true });
  Object.assign(ev, { clientX: 10, clientY: 5, relatedTarget: related });
  target.dispatchEvent(ev);
};

test("tipLines splits a segment's popover into lines, and ignores the rest", () => {
  const doc = page();
  assert.deepEqual(tipLines(doc.querySelector("i")), ["Catalina Cove", "Delivered: 52 of 236 (22%)"]);
  assert.equal(tipLines(doc.querySelector(".other")), null);
  assert.equal(tipLines(null), null);
});

test("hovering a segment shows its popover in the frame; leaving hides it", () => {
  const doc = page();
  wireBarHover(doc);
  const seg = doc.querySelector("i");
  fire(doc, "pointermove", seg);
  const tip = doc.querySelector("figure .chart-tip");
  assert.ok(tip && !tip.hidden);
  assert.equal(tip.querySelector("b").textContent, "Catalina Cove");
  assert.match(tip.textContent, /Delivered: 52 of 236 \(22%\)/);
  fire(doc, "pointerout", seg, doc.querySelector(".other"));
  assert.ok(tip.hidden);
});

test("a readout is spoken as counts first, in sentences, and only once the pointer rests", async () => {
  const { spoken, tooltip, SPEAK_DELAY } = await import("../../src/web/lib/tooltip.js");
  assert.equal(spoken(["Week of Jun 15, 2026", "Waiting: 4 (+1)", null, "Total: 9 (+4)"]),
    "Week of Jun 15, 2026. 4 Waiting (+1). 9 Total (+4)");
  assert.equal(spoken(["Catalina Cove", "Delivered: 146 of 236 (62%)", "With a VIN: 1 (50%)"]),
    "Catalina Cove. 146 of 236 Delivered (62%). 1 With a VIN (50%)");
  assert.equal(spoken(["u1", "VIN seq: 1930", "Est. delivery: Jul 2 (window)"]),
    "u1. VIN seq: 1930. Est. delivery: Jul 2 (window)", "identifiers and words stay");
  const doc = page();
  const host = doc.querySelector("figure");
  const t = tooltip(host);
  assert.equal(host.querySelector(".chart-tip").getAttribute("aria-hidden"), "true");
  t.show(["A", "Orders: 3"], 0, 0);
  t.show(["B", "Orders: 5"], 0, 0);
  const live = () => doc.querySelector('[role="status"]');
  assert.ok(!live() || live().textContent === "", "nothing spoken while moving");
  await new Promise((r) => setTimeout(r, SPEAK_DELAY + 50));
  assert.equal(live().textContent, "B. 5 Orders", "only the item it rested on");
  t.show(["C", "Orders: 7"], 0, 0);
  t.hide();
  await new Promise((r) => setTimeout(r, SPEAK_DELAY + 50));
  assert.equal(live().textContent, "B. 5 Orders", "moving off cancels");
});
