// Lazy loading of the vendored chart library (vendor/README.md).
//
// d3 ships as a UMD bundle, not an ES module, so it is loaded with a <script>
// tag the first time a chart needs it, and every later caller shares that one
// load. The URL is resolved against this module's own URL, so it stays inside
// the hashed asset directory the page was built with.

export const D3_FILE = "vendor/d3-7.9.0.min.js";

let pending = null;

export function loadD3(doc = document, base = import.meta.url) {
  if (globalThis.d3) return Promise.resolve(globalThis.d3);
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const s = doc.createElement("script");
      s.src = new URL("../" + D3_FILE, base).href;
      s.onload = () => resolve(globalThis.d3);
      s.onerror = () => { pending = null; reject(new Error("could not load " + D3_FILE)); };
      doc.head.append(s);
    });
  }
  return pending;
}
