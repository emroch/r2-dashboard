// A tooltip for drawn charts, positioned beside the pointer inside the chart's
// box. The first line is its heading; a null line is a rule between groups of
// lines.
//
// The tooltip itself is hidden from screen readers: as a live region it was
// announced on every move, so gliding across a chart queued a stream of stale
// readouts. Instead one shared, visually hidden live region gets the readout
// once the pointer has rested on an item (SPEAK_DELAY), worded for listening
// (spoken()), and moving off cancels it.

export const SPEAK_DELAY = 600;

// The readout as a listener hears it: "Label: number (extra)" lines turned
// to "number label (extra)" (the way a count is said aloud, rather than a
// label and a pause), and lines joined as sentences. A number that names
// something rather than counting it ("VIN seq: 1930") keeps its label first.
const IDENTIFIER = /^VIN\b/;
export function spoken(lines) {
  return lines.filter((l) => l).map((l) => {
    const m = /^(.+?): (\d[\d,.]*(?: of [\d,.]+)?%?)(?: (\(.*\)))?$/.exec(l);
    return m && !IDENTIFIER.test(m[1]) ? [m[2], m[1], m[3]].filter(Boolean).join(" ") : l;
  }).join(". ");
}

let live = null, timer = null;
function liveRegion(doc) {
  if (!live || live.ownerDocument !== doc || !live.isConnected) {
    live = doc.createElement("div");
    live.className = "sr-only";
    live.setAttribute("role", "status");
    doc.body.append(live);
  }
  return live;
}

export function tooltip(host) {
  const doc = host.ownerDocument;
  const tip = doc.createElement("div");
  tip.className = "chart-tip";
  tip.setAttribute("aria-hidden", "true");
  tip.hidden = true;
  host.append(tip);
  return {
    show(lines, x, y) {
      tip.replaceChildren(...lines.map((l, i) => {
        if (l === null) return Object.assign(doc.createElement("hr"), { className: "tip-rule" });
        const d = doc.createElement(i ? "div" : "b");
        d.textContent = l;
        return d;
      }));
      // Keep it inside the chart: flip to the pointer's left near the edge.
      tip.hidden = false;
      const w = tip.offsetWidth, room = host.clientWidth - x - 16;
      tip.style.left = (room < w ? Math.max(0, x - w - 12) : x + 14) + "px";
      tip.style.top = y + 14 + "px";
      // Spoken once the pointer settles; a new item restarts the wait.
      const text = spoken(lines);
      clearTimeout(timer);
      timer = setTimeout(() => { liveRegion(doc).textContent = text; }, SPEAK_DELAY);
    },
    hide() {
      tip.hidden = true;
      clearTimeout(timer);
    },
  };
}
