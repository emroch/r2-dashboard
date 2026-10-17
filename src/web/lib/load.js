// Lazy loading of the vendored chart libraries (vendor/README.md).
//
// d3 and topojson-client ship as UMD bundles, not ES modules, so each is loaded
// with a <script> tag the first time a chart needs it, and every later caller
// shares that one load. URLs are resolved against this module's own URL, so
// they stay inside the hashed asset directory the page was built with.

export const D3_FILE = "vendor/d3-7.9.0.min.js";
export const TOPOJSON_FILE = "vendor/topojson-client-3.1.0.min.js";
export const ATLAS_FILE = "vendor/us-atlas-3.0.1-states-10m.json";

const pending = new Map();

function loadScript(file, global, doc, base) {
  if (globalThis[global]) return Promise.resolve(globalThis[global]);
  if (!pending.has(file)) {
    pending.set(file, new Promise((resolve, reject) => {
      const s = doc.createElement("script");
      s.src = new URL("../" + file, base).href;
      s.onload = () => resolve(globalThis[global]);
      s.onerror = () => { pending.delete(file); reject(new Error("could not load " + file)); };
      doc.head.append(s);
    }));
  }
  return pending.get(file);
}

export function loadD3(doc = document, base = import.meta.url) {
  return loadScript(D3_FILE, "d3", doc, base);
}

// The US states map: topojson-client and the atlas, fetched together.
let atlas = null;
export function loadAtlas(doc = document, base = import.meta.url) {
  if (!atlas) {
    atlas = Promise.all([
      loadScript(TOPOJSON_FILE, "topojson", doc, base),
      fetch(new URL("../" + ATLAS_FILE, base)).then((r) => {
        if (!r.ok) throw new Error("could not load " + ATLAS_FILE);
        return r.json();
      }),
    ]).then(([topojson, us]) => ({ topojson, us }), (e) => { atlas = null; throw e; });
  }
  return atlas;
}
