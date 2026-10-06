// The page's view data (r2_view.json, written by render/view.py), fetched once
// and shared by every mounted component.
let pending = null;

export function view(url = "r2_view.json", fetchImpl = globalThis.fetch) {
  if (!pending) {
    pending = fetchImpl(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
      return r.json();
    });
    pending.catch(() => { pending = null; });
  }
  return pending;
}
