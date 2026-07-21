// Serves the R2 dashboard at emroch.com/r2-dashboard by proxying to its
// Cloudflare Pages project. The page loads Plotly from a sibling plotly.min.js,
// so we (1) enforce a trailing slash so that relative URL resolves under
// /r2-dashboard/, and (2) let browsers cache the bundle. Worker routes take
// precedence over the Pages site, so the rest of emroch.com is untouched.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    // Without the trailing slash, the page's relative "plotly.min.js" would
    // resolve to emroch.com/plotly.min.js (off the route) and 404.
    if (url.pathname === "/r2-dashboard") {
      return Response.redirect(url.origin + "/r2-dashboard/" + url.search, 301);
    }
    const path = url.pathname.replace(/^\/r2-dashboard(?=\/|$)/, "") || "/";
    const target = "https://r2-dashboard.pages.dev" + path + url.search;
    const resp = await fetch(target, { cf: { cacheEverything: true, cacheTtl: 3600 } });
    if (resp.ok && path === "/plotly.min.js") {
      const cached = new Response(resp.body, resp);
      cached.headers.set("Cache-Control", "public, max-age=86400");
      return cached;
    }
    return resp;
  },
};
