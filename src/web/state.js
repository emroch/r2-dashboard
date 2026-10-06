// View state in the URL's query string (docs/presentation.md, "URL state"), so
// any view is a link someone can post. Anchors (#sec-10) are left alone.
//
//   whiskers  "0" hides the delivery-window whiskers; shown otherwise

export function get(name, search = globalThis.location?.search ?? "") {
  return new URLSearchParams(search).get(name);
}

// Set (or, with null, remove) one parameter, keeping the rest and the anchor,
// without adding a history entry.
export function set(name, value, loc = globalThis.location, hist = globalThis.history) {
  const url = new URL(loc.href);
  if (value === null || value === undefined) url.searchParams.delete(name);
  else url.searchParams.set(name, String(value));
  hist.replaceState(hist.state, "", url);
  return url;
}

export const whiskersShown = (search) => get("whiskers", search) !== "0";
