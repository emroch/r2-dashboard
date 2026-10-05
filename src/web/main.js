// Page boot for the presentation layer (docs/presentation.md, "JS layout").
//
// A component that is drawn in the browser is a mount point in the page,
// <div data-chart="id" data-template="scatter">, and its template is a module
// loaded only when needed. This file finds the mounts and hands each one to its
// template's loader. No section is mounted yet (the first is #107), so for now
// it finds nothing and does nothing.
//
// Importing this module must not touch the DOM: tests import it under Node,
// where there is no document. Only boot() reads the page, and it runs on its
// own only in a browser.

// template name -> () => import("./charts/<template>.js"). Filled as templates land.
export const templates = {};

// Mount every [data-chart] element under `root` whose template is known. An
// unknown template is a build/registry mismatch: it is marked rather than
// thrown, so one bad mount can't stop the rest of the page.
export function boot(root, registry = templates) {
  const mounted = [];
  for (const el of root.querySelectorAll("[data-chart]")) {
    const load = registry[el.dataset.template];
    if (!load) {
      el.dataset.chartState = "unsupported";
      continue;
    }
    el.dataset.chartState = "loading";
    mounted.push(Promise.resolve()
      .then(load)
      .then((mod) => mod.mount(el))
      .then(() => { el.dataset.chartState = "ready"; },
            (err) => {
              el.dataset.chartState = "failed";
              console.error("chart %s failed to load", el.dataset.chart, err);
            }));
  }
  return Promise.all(mounted);
}

if (typeof document !== "undefined") boot(document);
