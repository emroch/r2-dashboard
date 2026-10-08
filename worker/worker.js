// Serves the R2 dashboard at emroch.com/r2-dashboard by proxying to its
// Cloudflare Pages project. The page loads its scripts and data by relative URL
// (assets/<hash>/..., r2_view.json), so we enforce a trailing slash so those
// resolve under /r2-dashboard/. Worker routes take precedence over the Pages
// site, so the rest of emroch.com is untouched.
//
// Only the content-hashed assets are cached at the edge: a new build is a new
// assets/<hash>/ path, so a cached copy is never stale, and Pages marks them
// immutable (_headers). The page and its data are fetched through each time,
// as Pages' headers ask (max-age=0, revalidated by ETag), so a page can never
// outlive a deploy and refer to an assets/<hash>/ that is gone.
export default {
  async fetch(request) {
    const url = new URL(request.url);
    // Without the trailing slash, the page's relative URLs would resolve to
    // emroch.com/assets/... (off the route) and 404.
    if (url.pathname === "/r2-dashboard") {
      return Response.redirect(url.origin + "/r2-dashboard/" + url.search, 301);
    }
    const path = url.pathname.replace(/^\/r2-dashboard(?=\/|$)/, "") || "/";
    const target = "https://r2-dashboard.pages.dev" + path + url.search;
    const init = path.startsWith("/assets/") ? { cf: { cacheEverything: true } } : {};
    return fetch(target, init);
  },
};
