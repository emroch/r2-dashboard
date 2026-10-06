# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This is a small **Python data pipeline** (`r2_dashboard`) that parses, sanitizes, and visualizes crowd-sourced **Rivian R2 pre-order** data (compiled from owner/reservation-holder reports, one row per person) into a single interactive HTML dashboard. Work here is still primarily data analysis and cleaning; the code is a **run-in-place project** (not an installable package), organized as two pipeline stages — `ingest/` (get + clean the data) and `render/` (build the webpage).

Structure:

```
r2_dashboard        run-in-place launcher (./r2_dashboard); also `python3 src/pipeline.py`
curate              ship a curation edit to main via an auto-checked, auto-merged PR
requirements.txt    pandas, numpy, plotly, PyYAML, beautifulsoup4 (runtime pins; all the deploy installs)
requirements-dev.txt  -r requirements.txt + dev tools (pytest, ruff, mypy + stubs); ./ci_env installs it
package.json        JS dev tools only (eslint, the wrangler the deploys use), pinned in package-lock.json; Node version in .nvmrc
eslint.config.js    JS lint settings (src/web/, tests/js/, worker/)
src/
  config.py         paths, run timestamps (NOW/AS_OF) + loaders for the conf/ YAML files below
  pipeline.py       main() orchestration + report printing (fetch -> clean -> render)
  ingest/           GET + CLEAN THE DATA
    fetch.py        live-sheet fetch with caching + change detection (against caches on disk and on origin/main); --offline
    parsing.py      pure parsing / VIN / date / geo helpers
    schema_check.py column location by name + verification against schema.yaml
    outliers.py     likely entry errors (values that contradict the order date or their cohort) — set aside, not corrected
    loaders.py      load_and_clean, load_reservations
    history.py      snapshot replay: every data/raw cache -> order keys + field history (internal; docs/data-layer.md)
    curation.py     overrides.yaml provenance: source/as_of/reason, effective dates, v2 enforcement
    timeline.py     cross-snapshot QA checks (VIN/order-date changes, firm->vague, rows that left the sheet)
    milestones.py   when each order's final VIN / final delivery date took hold (curated `dates:` or first snapshot showing it); internal
    contract.py     published data contract: dimension metadata + event-dated daily series (r2_dimensions.json / r2_series.json)
  render/           BUILD THE WEBPAGE
    colors.py       color transforms: HLS display palettes for Plotly (COLOR_DISPLAY / WHISKER_HEX) + OKLCH math (marks, contrast)
    categories.py   category colors as CSS: a .cat-<dim>-<slug> class per colored category (--paint true color, --mark theme-clamped) + fallback
    aggregates.py   counts for components, each reconciled against its cohort (cells + excluded == cohort, or the build stops)
    components.py   the component frame (title, summary, n + composed caveats, <details> table + CSV button) + HTML templates (takerate)
    view.py         builds + reconciles the page's aggregates, renders the components; writes r2_view.json (browser-drawn components' specs)
    specs.py        house-schema specs for the browser-drawn components (§10's scatter): points, layers, fixed domains; no colors
    charts.py       the Plotly fig_* chart builders not yet moved to components + helpers
    page.py         BeautifulSoup DOM population, HTML helpers, SECTIONS (from sections.yaml), build_dashboard
    assets.py       publishes src/web/ as content-hashed output/assets/<hash>/ (immutable-cached)
  templates/        valid standalone page shell, filled at render time
    page.html       valid HTML shell — empty id'd slots, populated via the DOM
    styles.css      the page stylesheet (its own <style> slot; theme vars separate)
    head.js         pre-paint theme set (no flash) — inlined, since it must run before first paint
    _headers        Cloudflare Pages cache headers (copied into the deploy)
  web/              the page's browser code, served as static files (docs/presentation.md, "JS layout")
    main.js         ES module: boots browser-drawn components at [data-chart] mounts, each when it nears the viewport; wires CSV buttons
    charts/         d3 templates (scatter.js) + registry.js (template -> lazy import)
    lib/            csv.js (table -> CSV), legend.js (house legend), tooltip.js, load.js (lazy d3)
    state.js        view state in the URL query (?whiskers=0)
    data.js         fetches r2_view.json once
    vendor/         d3 7.9.0, committed; README records version + SHA-256 (a test checks it)
    theme.js        theme toggle; fires r2:themechange, keeps the theme-color meta in step (classic script)
    plotly-theme.js re-tints the Plotly charts' chrome on r2:themechange; goes with Plotly (classic script)
    nav.js          sidebar scroll-spy, report-menu dismissal, local times (classic script)
    scrollzoom.js   map wheel-zoom vs. page-scroll arbitration (classic script)
  conf/             the data/config YAML (loaded by config.py at import)
    dimensions.yaml category vocabulary — per column: label, order, blank handling, caveat/note text, and per-category label/color/marker; published verbatim as r2_dimensions.json
    palette.yaml    chart fills that don't name a category (take-rate/timeline tints, accents, heatmap scale)
    theme.yaml      page & chart chrome for light/dark — CSS custom properties (incl. mark lightness bounds, stage opacities) + chart retint colors + static chart accents
    sections.yaml   the page's sections in order: title, prose (HTML), and what each draws (components, then Plotly charts)
    charts.yaml     the presentation-layer components by id: template, title, dims, aggregate, summary sentence
    schema.yaml     sheet sources (keys/gids/labels), column maps (field -> exact sheet header, verified each run), sanitize bounds, option take-rate vocab
    geo.yaml        state/province -> region + coordinates, factory location, province-name aliases
    delivery.yaml   delivery-estimate normalization — unknown tokens/substrings, explicit overrides, month names
    overrides.yaml  manual curation applied after fetch — `overrides` (edit fields on existing rows) + `additions` (append forum-only orders)
data/raw/           timestamped live caches (auto change-detected)
data/processed/     cleaned CSV output
output/             dashboard HTML output
tests/              unit tests: test_parsing.py, test_aggregates.py, test_specs.py, test_view.py (Python); js/*.test.mjs (node --test)
tools/              one-off maintenance scripts (migrate_curation.py)
```

The package pulls **two live Google Sheets** (an orders/deliveries tracker and a separate reservations-only tracker) via their CSV export endpoints, cleans them (dedup, VIN recovery, date normalization, geo enrichment), drops reservation-holders who have already ordered, writes a tidy CSV, and builds a 10-chart interactive Plotly dashboard.

## Working with the data

Run the pipeline from the project root:

```sh
./r2_dashboard          # or: python3 src/pipeline.py
./r2_dashboard --offline   # no live fetch: build from the newest known cache, write none
```

Outputs:
- `data/processed/r2_orders_clean.csv` — the cleaned, tidy dataset.
- `data/processed/r2_view.json` — the page's view data (`render/view.py`): spec + data of each browser-drawn component. Fetched by the page.
- `data/processed/r2_dimensions.json`, `r2_series.json` — the published data contract (`ingest/contract.py`): `dimensions.yaml` as JSON, and daily counts of what was true by each date (event-dated, from today's data). Aggregates only.
- `output/r2_orders_dashboard.html` — the interactive dashboard.
- `data/raw/r2_orders_live_*.csv`, `data/raw/r2_reservations_live_*.csv` — timestamped live caches. A new cache is written **only when the fetched content differs** from the newest known cache (change detection, since the export sends no Last-Modified/ETag), so a cache's timestamp marks when the data last changed. "Known" means on disk **or committed on `origin/main`** (read through git, no network): a branch that hasn't merged `main` lately would otherwise re-write data `main` already has, and the history replay reads the same set, so the newest snapshot it replays is the one being cleaned. If a live fetch fails, or with `--offline` (`R2_OFFLINE=1`), the newest known cache is used and nothing is written.

Shipping a curation edit (`src/conf/*.yaml`, new `data/raw` caches): `./curate "message"` runs `./ci_env check`, then branches, commits, opens a PR, waits for its checks and squash-merges it (one linear data commit, no merge commit; rebase merges are refused because `main` requires signed commits) — `main`'s ruleset blocks direct pushes. It refuses changes outside those paths.

Tests: each `tests/test_*.py` runs on its own with `python3` (no pytest required) or `pytest tests/` (pytest is in `requirements-dev.txt`; `./ci_env python -m pytest tests` runs it under the CI stack).

### Matching CI locally (`./ci_env`)

The system Python here is 3.9 + pandas 1.x, but CI runs Python 3.12 + the pinned
`requirements.txt` (pandas 2.x). That gap hides real bugs — a delivery typo parsing to
year 1326 raises `OutOfBoundsDatetime` on pandas 1.x but coerces to `NaT` on 2.x, so
"works locally" proves nothing about the deploy. `./ci_env` builds a venv (`.venv-ci/`,
gitignored) from the pinned requirements via `uv` and runs against it:

```sh
./ci_env check          # lint + types + tests (Python and JS) + full pipeline under the CI stack (what CI does)
./ci_env lint           # ruff check + mypy (pyproject.toml) + eslint (eslint.config.js); lint, not format
./ci_env js             # just the JS: eslint + the node --test suite
./ci_env test --both    # run the suite under BOTH stacks — catches version-dependent behavior
./ci_env build          # just the pipeline (add --offline: no live fetch, no new cache)
./ci_env python …       # any command under the CI stack
```

It re-creates the venv automatically when `requirements.txt` changes, so the local stack
can't drift from the pins. It prefers the exact CI interpreter and falls back to the
newest local `python3.x` if that download is unavailable (the library versions are what
matter for parity). **Run `./ci_env check` before pushing** anything that touches parsing
or rendering.

Dependencies (`requirements.txt`: pandas, numpy, plotly, PyYAML, beautifulsoup4) are expected to be available in the environment for the plain `python3` path. Because the source sheets are hand-maintained spreadsheet exports, **always account for the quirks below before computing statistics.**

## CSV structure and quirks

- **Row 1 is the header; row 2 is entirely blank** (a spacer). Real records start at row 3. Skip blank rows before aggregating.
- **Three trailing empty columns**: the header ends with a real column (`Other vehicles currently owned`) followed by empty column names, and every row has trailing commas. Ignore the empty tail columns.
- Free-text fields contain **commas inside quotes** (e.g. multiple owned vehicles, delivery windows) — use a real CSV parser, not a naive comma split.
- The first column (`#`) is a sequential row number, not a stable ID.

### Notable columns and their conventions

- **Original Reservation Date** vs **R2 Order Date** — reservation is the early/refundable hold; order date is when the configuration was finalized. Either may be blank.
- **VIN Assigned** — blank for most; a short code (e.g. `X1435`, `1930`) when assigned. Not a full 17-char VIN.
- **Estimated Delivery Date / Window** — highly inconsistent free text: exact dates in mixed formats (`10/20/26`, `07/14/2026`, `6302026`), ranges (`4-8 weeks`), months (`July`, `August 2026`), and placeholders (`unknown`, `TBD`, `N/A`, `None`, `Dont have one`). **Do not parse as dates without heavy normalization.**
- **Purchase or Lease?** — `Purchase` or `Lease`.
- **Location** — US state abbreviations, plus long-form entries for non-states (`Canada - British Columbia`, `DC - District of Columbia`).
- Option columns (**Autonomy+**, **Tow Package**, **Compact Spare Tire**) use **both** `Yes`/`No` **and** `Included`/`Included` — some report their explicit choice, others report what the Launch Package bundles. Treat `Included` and `Yes` as equivalent (opted-in) when counting take rates.
- The three **R1 owner** columns are conditional: the follow-up questions ("keeping your R1", "which model?") are blank for non-owners.

## Guidance

- Data is always pulled live from the source sheets and cached under `data/raw/` (timestamped, change-detected) — there are **no hand-maintained snapshots**, so do not add or rely on manual CSV copies. Write cleaned/derived data to `data/processed/`; never mutate the raw caches.
- Configuration lives in YAML files under `src/conf/`, loaded by `config.py` at import — `dimensions.yaml` (the category vocabulary: labels, order, colors/markers, caveats; published verbatim as `r2_dimensions.json`), `palette.yaml` (chart fills), `theme.yaml` (page & chart chrome for light/dark), `schema.yaml` (sources, column maps, sanitize bounds, option vocab), `geo.yaml` (states/provinces/factory), `delivery.yaml` (delivery-estimate normalization), and `overrides.yaml` (manual curation applied after fetch: `overrides` edit fields on rows already in the sheet, `additions` append forum-only orders not in the sheet, `deletions` drop cancellations, `verified` keeps a confirmed value the entry-error checks would set aside). Adding a paint, tweaking a theme/chart color, changing a sheet key, adjusting a date bound, teaching a new delivery token, correcting a partial entry, or adding a forum-only order is a data edit in these files, not a code change.
- Free-text fields are self-reported and noisy; prefer reporting distributions with an explicit "unparseable/unknown" bucket over silently dropping rows.
- Both sheets' columns are located **by name** (`ingest/schema_check.py`), and only the columns listed in `schema.yaml` are read at all — so reordering a sheet or adding a question to the form changes nothing here. Every run verifies each mapped column is present exactly once; a renamed/removed/duplicated one raises `SchemaDrift` and **stops the pipeline**, because it would otherwise read as empty (or ambiguously) for every row. The fix is to edit `orders_columns` / `reservations_columns` to match the sheet. A new *unmapped* column is only reported in the data-quality panel; add it to `ignored_columns` once it's knowingly unused, or map it to use it.
- **JS tooling.** The browser code under `src/web/` is plain ES modules and classic scripts, served as-is with no build step. `package.json` exists only for the dev tools: eslint (correctness rules, no formatter), `node --test` for `tests/js/`, and a pinned `wrangler` that the deploy workflows install with `npm ci --ignore-scripts` before `cloudflare/wrangler-action`, which then uses it instead of installing its own (that used to rewrite `package.json` in the checkout). Both files are tracked; `node_modules/` is not. The `js` job in `checks.yml` runs eslint and the tests; `./ci_env js` / `lint` / `check` run them locally. A module imported by a test must not touch the DOM at import time. `package-lock.json` must resolve every package from the public registry (`https://registry.npmjs.org/`); `tests/js/lockfile.test.mjs` fails otherwise, since an `npm install` on a machine configured with a private npm mirror records that mirror's URLs, which CI can't reach.
- **Category colors and marks.** A component never writes a hex color: it refers to a category as `"<dimension>:<value>"`, and `render/categories.py` turns that into a CSS class (`category_class`, which fails on a category without a color). The swatch that identifies a category uses `var(--paint)` (the true color); a data mark uses `var(--mark)`, the same hue and chroma with lightness clamped to the theme's `mark-lmin`/`mark-lmax` (theme.yaml), so every category holds 3:1 against the card in both themes (`tests/test_view.py` checks it). Changing a category color or the bounds: rerun the tests.
- **Reconciled aggregates.** Numbers a component shows come from `render/aggregates.py`, and each declares the cohort it counts; `cells + excluded` must equal that cohort or the build stops (`ReconcileError`), the same rule as the series totals check. Leave a row out on purpose by putting it in `excluded` with a reason, never by dropping it.
- **Viewing a local build.** The page's scripts are files under `output/assets/<hash>/`. The classic scripts work when `output/r2_orders_dashboard.html` is opened as a `file://` URL, but browsers refuse ES modules from `file://`, so anything `main.js` mounts needs a local server: `python3 -m http.server -d output`.
- Lint is `ruff check` (no `ruff format`, no import sorting — the hand-aligned continuation style is deliberate) and types are `mypy` with `check_untyped_defs`, both via `./ci_env lint` and the `Static checks` PR workflow. The code must still run on the system 3.9, so a module using `X | None` hints needs `from __future__ import annotations`, and names used only in hints (e.g. pandas' `NaTType`) are imported under `TYPE_CHECKING`.
