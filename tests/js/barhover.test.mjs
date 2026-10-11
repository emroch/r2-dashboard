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
