# Presentation layer design

Status: **proposed**. This is part of the dashboard revamp (#65), tracked in #102. It
follows the data layer (#80, `docs/data-layer.md`), whose published contract it builds on,
and turns the research in #66 into a plan. It is a design, not a commitment to an
implementation; each stage below becomes its own issue and PR.

## Why

Every chart on the page today is a Plotly figure, built in Python with its data and
styling baked in:

- **Weight.** About 19 `fig_*` builders (`src/render/charts.py`, 1,675 lines) put
  roughly 716 KB of figure JSON into an 860 KB page. `plotly.min.js` (4.85 MB decoded,
  1.37 MB on the wire) loads on every visit, before anything is on screen.
- **Fragile theming.** `theme.js` re-tints Plotly chrome and a few traces **by index**,
  matched on the `CHART.edge` grey. Anything that rebuilds a chart's traces breaks it,
  which blocks the reconfigurable charts in #51.
- **Compromise colors.** One hand-tuned hex per paint serves as both the swatch and the
  mark, so it has to balance accuracy against legibility on two surfaces. Whisker tints
  are derived in HLS, which isn't perceptual.
- **Prose, not structure.** Captions, caveats and sample sizes are hand-written HTML
  per section. There are no data tables (#29), and accessibility is whatever Plotly's
  SVG offers (#30).
- **An unread contract.** The data layer publishes `r2_orders_clean.csv`,
  `r2_dimensions.json` and `r2_series.json`, but the page reads none of them.

#66 surveyed two sites whose charts we like (SixColors, RivianRoamer). Both arrive at
the same shape from different stacks: **a page that is mostly HTML, a small JSON data
contract, declarative mount points, and a renderer that only does presentation.** Ours
is the inverse. This document describes how we get there.

## Ground rules

Agreed for the design:

- **Static hosting only.** Cloudflare Pages serves files; there is no server compute.
- **Hybrid rendering, by component.** Components that are fixed at build time
  (take-rates, mix bars, readouts, tables) are rendered to HTML **in Python**. Charts
  that need a library, and anything reconfigurable, are rendered **in JS** from
  published JSON.
- **Aggregation stays in Python.** JS formats, marginalizes a published cube, and
  draws; it never re-derives a business rule. This repo has twice shipped bugs where a
  derived label drifted from its source (#66), and a second aggregation codebase would
  repeat that with a wider blast radius.
- **Privacy, unchanged from the data layer.** Only the current rows and aggregates are
  published. No per-order history and no reservation rows.
- **Works without JS.** Python-rendered content reads correctly with scripts off, and
  every JS chart carries a Python-rendered data table as its fallback.
- **Redesign as we go.** Sections are rethought while they are migrated, not ported
  like-for-like, so correctness can't be "the same numbers as the old figure". It is
  guarded by reconciled aggregates instead (see *Correctness and tests*).
- **No build step for JS.** Plain ES modules served as-is, linted and unit-tested.
- **Python stays 3.9-compatible**, as today; CI runs 3.12.

## Components

Every section is made of components, and every component has the same frame:

```html
<figure class="r2c" id="c-takerate-color" role="group" aria-labelledby="c-takerate-color-t">
  <figcaption id="c-takerate-color-t">Paint</figcaption>
  <p class="r2c-summary">Launch Green leads with 31% of 674 orders.</p>
  …body…
  <p class="r2c-meta">n = 674 · <span class="caveat">…</span></p>
  <details class="r2c-data"><summary>Data</summary><table>…</table>
    <a download href="…">CSV</a></details>
</figure>
```

- **Summary sentence.** Written in Python from the aggregate, so the conclusion is
  stated in text before the chart supports it (the "headline → sentence → chart" shape
  #66 found on both sites).
- **Meta line.** The sample size, plus caveats **composed from dimension metadata**
  (`caveat`, `note`, `small_n`, `missing` in `dimensions.yaml`). The same caveat then
  appears everywhere its dimension does, which is the requirement #51 sets for
  reconfigurable views.
- **Data table and CSV.** The `<details>` table mirrors what is drawn, and the CSV link
  downloads that slice (#29). For a JS chart the table is also the no-JS fallback and
  the accessible form.

### Templates

| Kind | Template | Body | Rendered by |
|---|---|---|---|
| static | `readout` | big number, n, caveat | Python |
| static | `takerate` | rows: swatch, name, count/%, a bar segmented by delivery stage | Python |
| static | `mix` | 100%-stacked rows (by region, state, bin) | Python |
| static | `heatmap` | a `<table>` with shaded cells | Python |
| static | `range` | median / IQR strip | Python |
| mounted | `timeseries` | lines or stacked columns over dates | JS |
| mounted | `scatter` | points, plus `line`, `whisker` and `band` layers | JS |
| mounted | `geo` | bubble map | JS |

A mounted component is `<div data-chart="id">` inside the same frame. The page boots,
and when the mount nears the viewport the template module and its library are imported.

### Where each section starts

A starting point, not a spec: each section may be redesigned in its stage.

| Section | Today | Becomes |
|---|---|---|
| Summary stat cards | HTML cards with hover tables | `readout`s |
| §2 Configuration take-rates | 2×3 Plotly bar subplots | `takerate` rows |
| §3 Configuration combinations | two heatmaps | `heatmap` tables |
| §4 Configured price | bars, options bars, per-trim boxes | bars and `range` |
| §5 Reservation & order timeline | histograms | `timeseries` (can read `r2_series.json`) |
| §6 Estimated delivery timeline | stacked weekly histogram | `timeseries` |
| §7 Order-to-delivery time | scatter + weekly median | `scatter` with a `line` layer |
| §8 Certainty vs. VIN status | two donuts | stacked rows or `readout`s |
| §9 VIN vs. order date | scatter per paint × wheel | `scatter` |
| §10 Delivery vs. VIN | scatter, whiskers, build front, cadence | `scatter` with `whisker`, `line`, `band` |
| §11 VIN by configuration | scatter, one row per configuration | `scatter` |
| §12 Geographic demand | scattergeo maps + region bars | `geo`, with the bars as `mix` |
| §13 Orders by state | stacked bars | `mix` |
| §14–16 Preference by location | 100%-stacked bars | `mix` |
| §17 Destination vs. delivery | jittered scatter + whiskers | `scatter` |
| Data quality | HTML panel | stays as it is |

## Data contract additions

Building on the data layer's published set (`docs/data-layer.md`, *Data contract*):

- **`src/conf/sections.yaml`**: the page registry. Section order, title, prose and the
  component ids each section holds. The prose moves here out of `SECTIONS` in
  `page.py`, which makes editing it a data change.
- **`src/conf/charts.yaml`**: one entry per component, in a thin house schema:

  ```yaml
  delivery-vs-vin:
    template: scatter
    title: Delivery date vs. VIN sequence
    aggregate: delivery_vs_vin        # a function in render/aggregates.py
    encodings: {x: vin_seq, y: delivery_est, color: color, shape: wheels}
    layers: [whisker, build_front, band]
    toggles: {whiskers: false}
    lib: {}                           # passthrough: library-native options
  ```

  `lib` is the escape hatch RivianRoamer's schema has: the common cases stay
  declarative and library-agnostic, and a rare need doesn't grow the house schema.
- **`r2_view.json`**, published: for each mounted component, its spec plus the data
  its aggregate produced. Colors are **category references** (`"color:Launch Green"`),
  never hex, so CSS owns every actual color. The page fetches it once.
- **`r2_cube.json`**, published with the explore view (#51): a sparse cube of counts
  over the low-cardinality dimensions, indexed into `r2_dimensions.json` categories.
  The client only sums over dimensions it isn't showing. It reveals nothing the CSV
  doesn't.

## Theming

Today's policy stays: paint colors are identities, and only chrome changes with the
theme. What changes is the mechanism, from JS re-tinting to CSS that can't drift.

- **One variable per category.** `config.py` generates a class per category from
  `dimensions.yaml`, e.g. `.cat-color-launch-green { --paint: #… }`. Data names a
  category; CSS owns its color.
- **Swatch vs. mark.** A swatch (the chip beside a name) shows the true `--paint`. A
  mark (a bar, a point) uses a perceptual clamp that keeps it a minimum lightness
  distance from the surface, and otherwise leaves the paint alone:

  ```css
  --mark: oklch(from var(--paint) clamp(var(--mark-lmin), l, var(--mark-lmax)) c h);
  ```

  The bounds are per theme in `theme.yaml`, starting from what #66 measured (dark:
  0.70–0.92; light: at most 0.68). Glacier White and Midnight, the paints at either
  extreme, stay visible on both surfaces by construction.
- **Stages are alpha.** Delivered, VIN assigned and waiting share the paint and differ
  only in alpha (1, 0.65, 0.35), which reads correctly on either surface.
- **Fallback.** Browsers without relative color syntax (before Safari 18) get an
  `@supports not (color: oklch(from red l c h))` block of clamped colors that Python
  precomputes. `colors.py` moves from HLS to OKLCH to do it.
- **JS charts** resolve category colors through computed style, and re-render from
  their spec on an `r2:themechange` event fired by the theme toggle. Nothing is
  re-tinted by index.
- **Retired:** `CHART.edge` borders on near-surface fills, the HLS whisker tints, and
  most of `palette.yaml`. With legibility handled by the clamp, `dimensions.yaml` can
  record the **real** paint colors, as a separate, reviewable data edit.

## Accessibility and responsive baseline

Built into the components rather than added later (#30):

- **Page:** a `viewport` meta, and a `theme-color` meta per theme that `theme.js`
  keeps in step with the toggle. That gives Safari's tab bar a solid tint, the
  simplest fix for #41.
- **Charts:** each component is a labelled group; the drawn canvas or SVG is
  `aria-hidden`, and the data table is the accessible form. Tooltips are a
  `role="status"` live region. `prefers-reduced-motion` is honored.
- **Layout:** charts size with `ResizeObserver`, components re-flow with container
  queries, and every stage is checked at 390 px.
- **Navigation:** an ARIA-labelled nav, and touch targets of at least 44 px.

## URL state

- **Anchors** (`#sec-10`) keep working as they do today.
- **View state** lives in the query string through `src/web/state.js`
  (`URLSearchParams` and `replaceState`): today's whisker toggles (`?whiskers=1`), and
  later the explore view's picks. Every view is then a link that can be posted on the
  forum, which #66 found to be the single most useful detail on both sites.

## JS layout

Plain ES modules under `src/web/`, served as-is:

```
src/web/
  main.js              boot; lazy-imports each template when its mount nears the viewport
  data.js              fetches r2_view.json once
  state.js             URL view state
  theme.js  nav.js     page scripts (moved from src/templates/)
  lib/format.js        number/date/percent formatting           (pure, unit-tested)
  lib/cube.js          cube marginalization, small-n handling    (pure, unit-tested)
  charts/registry.js   template name -> () => import('./scatter.js')
  charts/adapter.js    house schema -> library options; the only file that knows the library
  charts/<template>.js one module per mounted template
  vendor/<lib>-<ver>.min.js   the chart library, committed; version and checksum recorded
tests/js/*.test.mjs    node --test
package.json, package-lock.json, eslint.config.js   at the repo root
```

## The chart library

The main open decision, made from a spike (stage 4) rather than from this note. The
candidates, each driven through the same `adapter.js` so the loser costs nothing:

- **Plotly, as a partial bundle.** It already draws everything we have, including
  scattergeo. But it is the heaviest, its theming stays JS-side, and its partial
  bundles have to be built (or downloaded per trace set), which runs against "no
  build step".
- **ECharts.** Canvas, lazy-loadable, and the library RivianRoamer uses. Maps need
  GeoJSON for the US and Canada supplied by us.
- **Observable Plot with d3-geo.** SVG, small, and naturally CSS-themable. Some layers
  (the build-front band) are ours to compose.

The spike builds §10 (the hardest scatter: whiskers, build front, band, toggle) and §12
(the map) in each, and judges wire size, CSS theming, accessibility, touch,
whisker/band expressiveness, and maps. The library is lazy-loaded either way: nothing
is fetched before a chart nears the viewport.

## What replaces `page.py` and `charts.py`

- **`src/render/aggregates.py`** (new): pure `DataFrame -> dict` functions, one per
  component. It absorbs the counting logic now spread through `charts.py`
  (`_paint_order`, `_ordered_counts`, `_stable_counts`, `delivery_progress`, the latency
  and geo counts). `cadence.py` stays as the model behind §10.
- **`src/render/components.py`** (new): the HTML renderers for the static templates.
- **`src/render/view.py`** (new): reads the registry, runs the aggregates, renders the
  static components, and writes `r2_view.json` (and later the cube).
- **`src/render/page.py`** shrinks to assembling the shell. It keeps the `slot()`
  mechanism and the data-quality panel.
- **`src/render/charts.py`** loses each `fig_*` builder in the stage that replaces it,
  and is deleted in the last library stage together with the plotly pin, the retint
  code in `theme.js`, and plotly's rules in `_headers` and `worker/worker.js`.

## Deploy and caching

- **Hashed assets.** The pipeline copies `src/web/` to `output/assets/<hash8>/`, and the
  page references it there. `_headers` serves `/assets/*` as
  `max-age=31536000, immutable` and the JSON files as `max-age=0, must-revalidate`.
  The published file URLs (`r2_orders_clean.csv`, the JSONs) don't move.
- **wrangler-action and npm.** Today the action installs wrangler into the checkout,
  creating `package.json` and `node_modules`, which `.gitignore` hides. Once the repo
  has a real `package.json`, wrangler is pinned as a devDependency, `npm ci` runs
  before the action, and the action's `wranglerVersion` matches the pin, so the action
  finds wrangler and installs nothing. Stage 1 verifies that the tree stays clean on a
  preview; if it doesn't, the JS tooling moves to a subdirectory instead.
- **The Worker.** `worker/worker.js` drops its plotly caching rule. It deploys on its
  own (`worker.yml`), so that change ships before the cutover.
- **Budgets.** The HTML page under 250 KB; no chart library before the first chart
  nears the viewport.

## Correctness and tests

Redesigning means the old figures can't be the reference. Instead:

- **Reconciliation.** Every aggregate returns `{cohort, excluded: {reason: n}, cells}`.
  `aggregates.reconcile()` checks that the cells plus the exclusions add back to the
  cohort the component declares (all orders, priced, VIN-assigned, state known), and
  the build stops on a mismatch, as `pipeline.py` already does for the series totals.
  An "answered-only" denominator then can't silently lose rows.
- **Cross-checks** between components that show the same thing: heatmap marginals
  equal the take-rate counts; state totals equal the state-known orders; the last
  point of `r2_series.json` equals the readouts.
- **Python tests.** The roughly 25 tests in `tests/test_parsing.py` that assert on
  Plotly figure internals move to `tests/test_aggregates.py`, keeping each test's
  intent (e.g. every paint chart uses the same paint order). A new `tests/test_view.py`
  parses the built page: every registry id has its component and data table, and every
  category reference resolves to a CSS class.
- **JS tests.** `node --test` covers formatting, cube marginalization and small-n
  handling, the adapter's output, and URL-state round trips.
- **Spot checks.** Where a redesigned section keeps a quantity the old figure showed,
  its stage PR records a one-off comparison with the old number.

## Stages

Each stage is one issue and one PR, from `presentation/<stage>` into `dev/presentation`,
tracked under **#102**. Issue numbers are added once this design is reviewed.

1. **Tooling** (`tooling`). `package.json` (eslint and wrangler pinned),
   `eslint.config.js`, `tests/js/`, a `js` job in `checks.yml`, the `.gitignore` and
   wrangler-action changes, the `src/web/` skeleton, the hashed asset copy and
   `_headers`.
   - *Acceptance:* the preview deploys from a clean tree.
   - *Acceptance:* the page is unchanged apart from its script tags.
   - *Acceptance:* the `js` check is added to the ruleset's required checks.
2. **Theming and scaffolding** (`scaffold`). Category CSS, the OKLCH mark rule and its
   fallback, `theme.js` reduced to the toggle and `r2:themechange`, `components.py`,
   the `aggregates.reconcile` skeleton, `sections.yaml`, and `r2_view.json`. Blocked
   by 1.
   - *Acceptance:* reconciliation runs in the pipeline.
   - *Acceptance:* Glacier White and Midnight marks stay visible in both themes.
3. **§2 HTML spike** (`takerate`). §2 as take-rate rows, shown beside the Plotly
   version on the preview. Blocked by 2.
   - *Acceptance:* the direction decision is recorded here, with evidence on payload,
     VoiceOver and theming.
   - *Acceptance:* `fig_config_dashboard` and its tests are migrated.
4. **Library spike** (`lib-spike`). §10 and §12 in each candidate library. Blocked by
   2; can run alongside 3.
   - *Acceptance:* the library decision is recorded here.
   - *Acceptance:* `adapter.js` and the `scatter` template are merged, and §10 is live
     with its whisker toggle in the URL.
   - *Acceptance:* the library is fetched only when a chart nears the viewport.
5. **Static group A** (`static-a`). §3, §4, §8 and the summary readouts. Blocked by 3.
6. **Static group B** (`static-b`). §13–16. Blocked by 3.
7. **Time charts** (`lib-time`). §5, §6, §7. Blocked by 4.
8. **Remaining library charts** (`lib-rest`). §9, §11, §12, §17; then delete
   `charts.py`, plotly and the retint code. Blocked by 4–7.
   - *Acceptance:* no plotly remains in the repo, and the budgets are met.
9. **Polish** (`polish`). Blocked by 5–8.
   - **#41:** header behavior on narrow screens.
   - **#46:** close the report menu when one of its links is clicked.
   - **#30:** the 390 px pass, ARIA, and a color-blind palette option.
   - **#29:** the remainder, a sortable table of the cleaned rows.
10. **Cutover.** `dev/presentation` into `main` in one PR, after the Worker change is
    deployed.
    - *Acceptance:* every reconciliation passes, and the preview is reviewed section by
      section.
11. **Explore view, #51** (`explore`), after the cutover. `r2_cube.json`, dimension
    pickers, caveats composed for the chosen dimensions, the small-n rule enforced by
    the renderer, and picks kept in the URL. Mostly UI, since stage 2 fixes the
    registry and the cube's shape.

After that, **#85** (#32 trends, #34 estimate accuracy, reservation → order conversion)
lands as new components on the registry.

## Risks and open questions

- **Relative color syntax** needs Safari 18+; older browsers rely on the precomputed
  fallback, which the theming stage must test.
- **Transition weight.** Old and new sections ship side by side until stage 8, so the
  page grows before it shrinks. Only previews and the cutover see it.
- **PNG export goes away** with Plotly's modebar. SVG export is cheap if the chosen
  library draws SVG; otherwise the data table and CSV cover the need.
- **Redesign creep.** One section group per PR, with its prose changes inside it.
- **Open: true paint colors.** Where do the real hexes come from (Rivian's
  configurator, owner photos)?
- **Open: color-blind palette.** How far should the alternate palette go, given that
  paint colors are identities?
- **Not planned: `as_of` link pinning.** SixColors pins a post to its period; for us
  that would need published history, which the privacy rule excludes.

## Execution

As with the data layer, all work happens on a long-lived branch, so `main` (which
deploys to the live site) never carries a half-migrated page.

- **Integration branch:** `dev/presentation`, cut from `main`.
- **Stage PRs:** each stage is developed on `presentation/<stage>` and merged by PR
  into `dev/presentation`. Previews and the static checks run on those PRs as usual,
  so every stage can be reviewed live.
- **Keeping up with `main`:** `main` keeps moving (cache refreshes every few hours,
  curation through `./curate`). Merge `main` into `dev/presentation` periodically and
  before each stage PR; merge rather than rebase, because the branch is shared.
  Conflicts should be rare, since `main` mostly changes `data/raw/` and
  `overrides.yaml` while this work changes `src/render/`, `src/web/` and the templates.
- **Into `main`:** one cutover PR once stages 1–9 are done (stage 10).
- **After the cutover:** the explore view (#51) and then #85.
