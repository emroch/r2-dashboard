# Vendored libraries

Committed as-is and served from the hashed asset directory with the rest of
`src/web/` (no build step, no CDN at run time). Loaded only when a chart that
needs it nears the viewport (`lib/load.js`). eslint skips this directory.

| File | Library | Version | From | SHA-256 | Licence |
|---|---|---|---|---|---|
| `d3-7.9.0.min.js` | [d3](https://d3js.org) | 7.9.0 | npm `d3@7.9.0`, `dist/d3.min.js` | `f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539` | ISC, `LICENSE-d3` |

To update: install the new version from the public registry, copy its
`dist/d3.min.js` here under the new versioned name, update `lib/load.js` and
this table (`shasum -a 256 <file>`), and check the charts on a preview.
`tests/js/vendor.test.mjs` checks every file listed here against its checksum.
