// Serves the R2 dashboard at emroch.com/r2-dashboard by proxying to its
// Cloudflare Pages project. The dashboard HTML is fully self-contained (Plotly,
// CSS, JS all inlined), so no link/asset rewriting is needed — we just strip the
// route prefix and forward. Worker routes take precedence over the Pages site
// for matching paths, so the rest of emroch.com is untouched.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/r2-dashboard(?=\/|$)/, "") || "/";
    const target = "https://r2-dashboard.pages.dev" + path + url.search;
    return fetch(target, { cf: { cacheEverything: true, cacheTtl: 3600 } });
  },
};
