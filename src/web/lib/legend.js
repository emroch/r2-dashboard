// The house legend: HTML buttons, so it reads and works the same whatever the
// chart is drawn with, and is reachable by keyboard and screen readers. Click
// (or Enter/Space) hides or shows an entry; double-click isolates it, and
// double-clicking the isolated entry again shows everything.

// The next hidden set after a click or a double-click on `name`. Pure.
export function toggle(hidden, name) {
  const next = new Set(hidden);
  if (next.has(name)) next.delete(name); else next.add(name);
  return next;
}

export function isolate(hidden, name, names) {
  const others = names.filter((n) => n !== name);
  const alreadyAlone = !hidden.has(name) && others.every((n) => hidden.has(n));
  return alreadyAlone ? new Set() : new Set(others);
}

// Render the legend into `el` and call onChange(hidden) after each change.
// items: [{name, cls?, accent?}], where cls is a category class for the swatch
// and accent a CSS variable name (for layers that aren't a category).
export function legend(el, items, onChange, hidden = new Set()) {
  const doc = el.ownerDocument;
  const names = items.map((it) => it.name);
  el.replaceChildren();
  const buttons = items.map((it) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "lg-item";
    const sw = doc.createElement("i");
    sw.className = "swatch " + (it.cls || "");
    if (it.accent) sw.style.background = `var(--${it.accent})`;
    b.append(sw, doc.createTextNode(it.name));
    // A click waits a moment so a double-click isn't also two toggles.
    let timer = null;
    b.addEventListener("click", () => {
      clearTimeout(timer);
      timer = setTimeout(() => update(toggle(hidden, it.name)), 220);
    });
    b.addEventListener("dblclick", () => {
      clearTimeout(timer);
      update(isolate(hidden, it.name, names));
    });
    el.append(b);
    return b;
  });
  function sync() {
    buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(!hidden.has(names[i]))));
  }
  function update(next) {
    hidden = next;
    sync();
    onChange(hidden);
  }
  sync();
  return { get hidden() { return hidden; } };
}
