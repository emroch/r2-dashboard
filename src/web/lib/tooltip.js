// A tooltip for drawn charts: a live region (role="status"), so its text is
// announced, positioned beside the pointer inside the chart's box.
export function tooltip(host) {
  const doc = host.ownerDocument;
  const tip = doc.createElement("div");
  tip.className = "chart-tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  host.append(tip);
  return {
    show(lines, x, y) {
      tip.replaceChildren(...lines.map((l, i) => {
        const d = doc.createElement(i ? "div" : "b");
        d.textContent = l;
        return d;
      }));
      // Keep it inside the chart: flip to the pointer's left near the edge.
      tip.hidden = false;
      const w = tip.offsetWidth, room = host.clientWidth - x - 16;
      tip.style.left = (room < w ? Math.max(0, x - w - 12) : x + 14) + "px";
      tip.style.top = y + 14 + "px";
    },
    hide() { tip.hidden = true; },
  };
}
