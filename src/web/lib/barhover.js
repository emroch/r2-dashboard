// Hover popovers for the HTML bars (take-rate and mix rows, render/components.py,
// and the state mix): a segment with `data-tip` (lines separated by "\n": the
// row, then the segment's count and share) shows it in the charts' tooltip,
// placed in the segment's component frame. One delegated listener for the
// whole page, so bars drawn later (the state mix) need no wiring of their own.
// A tap shows it on touch screens; the next tap elsewhere hides it. The bars
// are aria-hidden: the row text beside them says the same for assistive tech.

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
    const host = lines && ev.target.closest(".r2c");
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
