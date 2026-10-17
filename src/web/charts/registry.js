// Template name -> loader of its module. Each template module exports
// mount(el) and is imported only when one of its charts nears the viewport.
export const templates = {
  geo: () => import("./geo.js"),
  scatter: () => import("./scatter.js"),
  statemix: () => import("./statemix.js"),
  timeseries: () => import("./timeseries.js"),
};
