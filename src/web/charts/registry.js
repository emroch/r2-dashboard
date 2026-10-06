// Template name -> loader of its module. Each template module exports
// mount(el) and is imported only when one of its charts nears the viewport.
export const templates = {
  scatter: () => import("./scatter.js"),
};
