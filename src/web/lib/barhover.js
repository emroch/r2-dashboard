// Hover popovers for anything with `data-tip` (lines separated by "\n"): the HTML
// bars (take-rate and mix rows, render/components.py, and the state mix: the
// row, then the segment's count and share), and the summary's source times and
// failed-fetch warning (nav.js, page.py). It shows in the charts' tooltip, placed
// in the element's component frame or the summary. One delegated listener for
// the whole page, so things drawn later need no wiring of their own. A tap shows
// it on touch screens; the next tap elsewhere hides it. Each carries the same
// text for assistive tech another way (the row text, a label, hidden text).

import { tooltip } from "./tooltip.js";

// The lines a segment's popover shows, or null for anything that isn't one.
export function tipLines(target) {
  const seg = target?.closest?.("[data-tip]");
  return seg ? seg.dataset.tip.split("\n") : null;
}

export function wireBarHover(root) {
  const tips = new WeakMap();
  let shown = null;
  const tipFor = (host) => {
    if (!tips.has(host)) tips.set(host, tooltip(host));
    return tips.get(host);
  };
  const hide = () => {
    if (shown) shown.hide();
    shown = null;
  };
  const show = (ev) => {
    const lines = tipLines(ev.target);
    const host = lines && ev.target.closest(".r2c, .intro");
    if (!host) { hide(); return; }
    const t = tipFor(host);
    if (shown && shown !== t) shown.hide();
    const box = host.getBoundingClientRect();
    t.show(lines, ev.clientX - box.left, ev.clientY - box.top);
    shown = t;
  };
  root.addEventListener("pointermove", show);
  root.addEventListener("pointerdown", show);
  root.addEventListener("pointerout", (ev) => {
    if (tipLines(ev.target) && !tipLines(ev.relatedTarget)) hide();
  });
}
