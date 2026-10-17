# R2 Orders

Parses, sanitizes, and visualizes crowd-sourced **Rivian R2 pre-order** data into
an interactive dashboard (HTML, with charts drawn in d3). It pulls two live Google Sheets (an
orders/deliveries tracker and a separate reservations-only tracker) via their CSV
export endpoints, cleans them (dedup, VIN recovery, date normalization, geo
enrichment), removes reservation-holders who have already ordered, and produces a
tidy CSV plus the HTML dashboard.

## Project layout

```
r2_dashboard          run-in-place launcher (./r2_dashboard); also `python3 src/pipeline.py`
serve                 build offline and serve the page locally, as deployed (--watch rebuilds)
curate                ship a curation edit to main via an auto-checked, auto-merged PR
ci_env                run lint, types, tests and the build under the CI stack (pinned venv)
requirements.txt      pandas, numpy, PyYAML, beautifulsoup4
requirements-dev.txt  + pytest, ruff, mypy (what ./ci_env installs)
package.json          JS dev tools (eslint, pinned wrangler); Node version in .nvmrc
src/
  config.py           paths, run timestamps + loaders for the conf/ YAML files
  pipeline.py         main() orchestration + report printing (fetch -> clean -> render)
  ingest/             get + clean the data
    fetch.py          live-sheet fetch with caching + change detection
    parsing.py        pure parsing / VIN / date / geo helpers
    schema_check.py   locates columns by name; verifies them against schema.yaml
    outliers.py       likely entry errors, set aside rather than corrected
    loaders.py        load_and_clean, load_reservations
    pricing.py        configured price from an order's configuration (pricing.yaml)
    history.py        snapshot replay: every raw cache -> order keys + field history
    curation.py       overrides.yaml provenance and effective dates
    timeline.py       cross-snapshot checks (VIN/order-date changes, rows that left)
    milestones.py     when each order's final VIN and delivery date took hold
    contract.py       the published data contract (r2_dimensions.json, r2_series.json)
  render/             build the webpage
    colors.py         color transforms (OKLCH, for marks and contrast)
    categories.py     category colors as CSS classes (true swatch + theme-clamped mark)
    aggregates.py     reconciled counts behind the components
    components.py     the component frame (summary, n, caveats, data table) + HTML templates
    view.py           builds and reconciles the aggregates; builds r2_view.json
    specs.py          specs for the browser-drawn charts (points, layers, map and state counts)
    cadence.py        the build-front model behind §delivery-vs-vin (rate, projection, back-tested band)
    page.py           BeautifulSoup DOM population, HTML helpers, SECTIONS, build_dashboard
    assets.py         publishes src/web/ as content-hashed static assets
  templates/          valid standalone page shell, filled at render time
    page.html         valid HTML shell (empty id'd slots, populated via the DOM)
    css/              page stylesheet, one file per area (01-base … 08-access), joined in order
    head.js           pre-paint theme set (no flash), inlined
  web/                browser code, served as static files (no build step)
    main.js           boots browser-drawn components (ES module), lazily; CSV buttons, bar popovers
    data.js           fetches r2_view.json once
    state.js          view state in the URL query (whiskers, a chart's view and grain, state)
    charts/           d3 chart templates (scatter, timeseries, geo, statemix) + registry.js
    lib/              csv.js, legend.js, tooltip.js, load.js (lazy d3), barhover.js, grain.js
    vendor/           d3 7.9.0, topojson-client, us-atlas (versions + checksums in its README)
    img/              the header logo
    theme.js          theme menu (Light/Dark/System; fires r2:themechange)
    nav.js            sidebar overlay (under 1072px) + scroll-spy, header menus, local times
  conf/               data/config YAML (loaded by config.py)
    dimensions.yaml   category vocabulary: each column's label, order, blank handling, caveat, and
                      per-category label/color/marker (paints, wheels, interiors, regions, ...);
                      published as r2_dimensions.json
    palette.yaml      chart colors that name no category: roles (primary, highlight,
                      highlight_band) and the fulfilment event lines
    theme.yaml        page & chart chrome for light/dark (CSS variables)
    sections.yaml     the page's sections: order, title, prose, components
    charts.yaml       the presentation-layer components (template, title, summary)
    schema.yaml       sheet sources, column maps, sanitize bounds, option vocab
    geo.yaml          state/province -> region + coordinates, factory, province aliases
    delivery.yaml     delivery-estimate normalization (tokens, overrides, month names)
    pricing.yaml      configured-price tables (trims, options, paints, wheels)
    overrides.yaml    manual curation: overrides, additions (forum-only orders),
                      deletions, verified
data/
  raw/                timestamped live caches (committed as dated fetch history)
  processed/          cleaned CSV, data contract and the page's view data
output/               dashboard HTML output
tests/
  test_parsing.py     unit tests (run via pytest OR plain python3)
  test_aggregates.py  presentation-layer aggregates + take-rate component
  test_specs.py       specs for the browser-drawn charts
  test_view.py        presentation-layer registries, category CSS + contrast, view build
  js/                 browser-code unit tests (node --test)
```

## Running

From the project root:

```sh
./r2_dashboard          # or: python3 src/pipeline.py
./r2_dashboard --offline   # skip the live fetch: newest known cache, no new cache written
```

It's a run-in-place project (no install step). Dependencies are listed in
`requirements.txt` (pandas, numpy, PyYAML, beautifulsoup4).

## Outputs

- `data/processed/r2_orders_clean.csv` — the cleaned, tidy dataset.
- `data/processed/r2_dimensions.json` — `src/conf/dimensions.yaml` as JSON: each CSV
  column's label, category order, blank handling, small-n rule, caveat/note text,
  and per-category colors and markers.
- `data/processed/r2_series.json` — daily counts of what was true by each date:
  orders, final VINs assigned, final delivery dates set, deliveries, outstanding and
  converted reservations, each counted on its own event date from today's data, so
  late reports revise past points. Aggregates only; no per-order history.
- `data/processed/r2_view.json` — the specs and data of the browser-drawn charts,
  fetched by the page.
- `output/r2_orders_dashboard.html` — the interactive dashboard.
- `data/raw/r2_orders_live_*.csv`, `data/raw/r2_reservations_live_*.csv` — timestamped
  live caches. A new cache is written only when the fetched content differs from
  the newest known cache, on disk or committed on `origin/main` (change detection),
  so a cache's timestamp marks when the data last changed. If a live fetch fails,
  or with `--offline`, the newest known cache is used and nothing is written. Caches from local
  builds are worth committing too: each one can only add a change the scheduled
  deploy missed, and a duplicate is harmless. Why the history is kept as separate
  snapshots and not a single tracked file or a database is recorded in
  `docs/data-layer.md` (*Snapshot storage*) and #89.

## Data source

Two live Google Sheets, pulled on demand via their CSV export endpoint:

- **Orders & Deliveries** tracker (one row per person; VIN, config, delivery estimate).
- **Reservations** tracker (reservation-only holders — no order/VIN/config).

The data is self-reported and noisy; treat all figures as indicative. It is
always pulled live and cached under `data/raw/`; there are no hand-maintained
snapshots — the raw caches are committed, so `data/raw/` is a dated,
change-detected history of the sheets (useful for trend analysis).

Because both sheets are hand-maintained forms, columns are located by **name**
rather than position, and only the columns actually used are read. So the sheets
can be reordered, or grow new questions anywhere, with no effect. What is checked
on every run is that each column named in `src/conf/schema.yaml` is present
exactly once: a mapped column that has been **renamed, removed, or duplicated
stops the pipeline**, since it would otherwise read as empty (or ambiguously) for
every row and quietly skew every figure. Failing means the deployed dashboard
stays on its last good build until `schema.yaml` is updated to match. A merely
*new* column can't affect anything, so it's listed in the dashboard's
data-quality panel instead, as a nudge that new data is available.

## Deployment

The dashboard is published at **https://emroch.com/r2-dashboard** on Cloudflare's
free tier, refreshed automatically:

- **GitHub Actions** (`.github/workflows/deploy.yml`) runs the pipeline every 6
  hours (and on demand / on push), deploys the static output to a **Cloudflare Pages** project
  via Wrangler, and commits any refreshed `data/raw/` caches back so the fetch
  history accrues.
- A small **Cloudflare Worker** (`worker/`) routes `emroch.com/r2-dashboard*` to
  that Pages project, adding the trailing slash the page's relative asset and data
  URLs need, and caching only the content-hashed assets at the edge.
  `.github/workflows/worker.yml` deploys it whenever anything under `worker/`
  lands on `main` — validating the bundle on PRs first, and smoke-testing the live
  route afterwards, since the Worker has no preview environment.

The Python build runs only in Actions — Cloudflare serves and routes but can't run
pandas. One-time setup (API token, secrets, Pages project) is noted in the
workflow files. The API token needs **Workers Scripts · Edit** and **Workers
Routes · Edit** on the `emroch.com` zone in addition to **Pages · Edit**, since the
same token deploys both.

## Tests

```sh
for f in tests/test_*.py; do python3 "$f"; done   # no pytest required
# or
pytest tests/

npm ci --ignore-scripts           # once: the pinned JS tools
npx eslint . && npm test          # JS lint + node --test
```

`./ci_env check` runs all of it, plus the pipeline, under the CI stack.

To view a local build, run `./serve`: it builds offline, stages what the deploy
publishes into `output/site/`, and serves it on http://127.0.0.1:8000/ (`--watch`
rebuilds on edits). Opened as a `file://` page the charts never draw: browsers
don't load ES modules from `file://`, and the charts fetch `r2_view.json`.

## Reporting a problem

The dashboard's **⚑ Report issue** menu offers three routes, because they lead
different places:

- **Your own order data is wrong** → the forum thread the tracker is compiled
  from, which carries the form for updating your entry. This pipeline only
  *reads* those sheets, so fixing the data at the source is what reaches everyone
  using it — not just this page. Each sheet's thread is set as `thread_url` in
  `src/conf/schema.yaml` and also linked beside that sheet in the page header.
- **Something's wrong with this page** → the
  [dashboard-report issue form](.github/ISSUE_TEMPLATE/dashboard-report.yml),
  prefilled with the build it was opened from (as-of date, each sheet's
  last-updated time, and the deployed commit), so a report is reproducible
  without the reader having to describe their build. Lands labelled
  `from-dashboard`.
- **Message @emroch on the forum** → for anyone without a GitHub account, since
  filing an issue requires signing in.

## Roadmap

Planned improvements are tracked as
[GitHub issues](https://github.com/emroch/r2-dashboard/issues).

## License

[MIT](LICENSE) © 2026 Eric Roch
