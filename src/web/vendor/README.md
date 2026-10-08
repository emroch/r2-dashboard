# Vendored libraries

Committed as-is and served from the hashed asset directory with the rest of
`src/web/` (no build step, no CDN at run time). Loaded only when a chart that
needs it nears the viewport (`lib/load.js`). eslint skips this directory.

| File | Library | Version | From | SHA-256 | Licence |
|---|---|---|---|---|---|
| `d3-7.9.0.min.js` | [d3](https://d3js.org) | 7.9.0 | npm `d3@7.9.0`, `dist/d3.min.js` | `f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539` | ISC, `LICENSE-d3` |
| `topojson-client-3.1.0.min.js` | [topojson-client](https://github.com/topojson/topojson-client) | 3.1.0 | npm `topojson-client@3.1.0`, `dist/topojson-client.min.js` | `25cd02ae486cc5063e0215a4e4cfb15de83700c87ac48bac4d57dc6aaf3ebb89` | ISC, `LICENSE-topojson-client` |
| `us-atlas-3.0.1-states-10m.json` | [us-atlas](https://github.com/topojson/us-atlas) | 3.0.1 | npm `us-atlas@3.0.1`, `states-10m.json` (Census cartographic boundaries, 1:10m) | `d76b391ccfa8bff601d51e3e3da5d43a89fa46cd5caca72ce731b383be5596d0` | ISC, `LICENSE-us-atlas` |

The map (§12) loads topojson-client and the us-atlas states with d3; state
geometries are keyed by FIPS code, which `charts/geo.js` maps to postal codes.

To update: install the new version from the public registry, copy its file
(`dist/d3.min.js`, say) here under the new versioned name, update `lib/load.js` and
this table (`shasum -a 256 <file>`), and check the charts on a preview.
`tests/js/charts.test.mjs` checks every file listed here against its checksum.
