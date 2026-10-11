// Page boot for the presentation layer (docs/presentation.md, "JS layout").
//
// A component that is drawn in the browser is a mount point in the page,
// <div data-chart="id" data-template="scatter">, and its template is a module
// (charts/registry.js) loaded only when the mount nears the viewport, together
// with the chart library it uses (lib/load.js). So a reader who never scrolls
// to a chart never downloads d3.
//
// It also wires each component's "Download CSV" button (lib/csv.js).
//
// Importing this module must not touch the DOM: tests import it under Node,
// where there is no document. Only boot() reads the page, and it runs on its
// own only in a browser.

import { templates } from "./charts/registry.js";
import { wireBarHover } from "./lib/barhover.js";
import { wireCsv } from "./lib/csv.js";

export { templates };

// Run `fn` once `el` is within `margin` of the viewport (now, without an
// IntersectionObserver).
export function whenNear(el, fn, margin = "600px") {
  if (typeof IntersectionObserver === "undefined") return fn();
  const obs = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { obs.disconnect(); fn(); }
  }, { rootMargin: margin });
  obs.observe(el);
}

// Mount every [data-chart] element under `root` whose template is known, each
// when `schedule` says (by default, when it nears the viewport). An unknown
// template is a build/registry mismatch: it is marked rather than thrown, so
// one bad mount can't stop the rest of the page. Resolves when all have run.
export function boot(root, registry = templates, schedule = (el, fn) => fn()) {
  const mounted = [];
  for (const el of root.querySelectorAll("[data-chart]")) {
    const load = registry[el.dataset.template];
    if (!load) {
      el.dataset.chartState = "unsupported";
      continue;
    }
    el.dataset.chartState = "waiting";
    mounted.push(new Promise((done) => schedule(el, () => {
      el.dataset.chartState = "loading";
      Promise.resolve()
        .then(load)
        .then((mod) => mod.mount(el))
        .then(() => { el.dataset.chartState = "ready"; },
              (err) => {
                el.dataset.chartState = "failed";
                console.error("chart %s failed to load", el.dataset.chart, err);
              })
        .then(done);
    })));
  }
  return Promise.all(mounted);
}

if (typeof document !== "undefined") {
  wireCsv(document);
  wireBarHover(document);
  boot(document, templates, whenNear);
}
