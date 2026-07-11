# Roadmap

Tracked improvements for the `r2-orders` dashboard. Items marked **(requested)**
were asked for directly; the rest are proposed. Rough effort: **S** ≈ hours,
**M** ≈ a day, **L** ≈ multi-day. Unchecked = not started.

---

## Presentation & UX

- [x] **Dark / light theme toggle** — **(requested)** · S–M · *done*
  Page chrome is driven by CSS custom properties (`:root` / `html[data-theme="dark"]`);
  a header toggle persists the choice (`localStorage`) and respects
  `prefers-color-scheme`, set before first paint to avoid a flash. Charts use
  transparent backgrounds so the themed card shows through, and a `Plotly.relayout`
  /`restyle` pass re-tints chart chrome on toggle — text, gridlines, geo land/borders,
  legend boxes, marker/bar borders (dark-grey ↔ light-grey), and the factory ★
  marker. Data-encoding colors (paints/bars/regions) are deliberately left fixed.

- [ ] **Interactive filters** · M
  Client-side filtering by state/region, config (color, wheels, interior),
  purchase vs. lease, and "VIN-assigned only" — updates all charts at once.

- [ ] **Per-chart export & data table** · S
  PNG export (Plotly already supports it) plus a "download this chart's data as
  CSV" and a raw sortable data-table view of the cleaned dataset.

- [ ] **Accessibility & responsive layout** · M
  Color-blind-safe palette option, ARIA labels, and a layout that reflows for
  narrow/mobile screens (the 3 stacked geo maps and wide charts especially).

- [x] **"Today" reference line on delivery-date charts** · S · *done*
  Theme-aware dashed "Today" marker at the run date (`AS_OF`): horizontal on
  delivery-vs-VIN (#1, where delivery date is the y-axis), vertical on
  destination-vs-delivery (#2) and the delivery timeline (#7). Line + label
  re-tint with the theme toggle. Skipped the reservation/order timeline (#6) —
  its axes are historical, so "today" would just pin to the right edge.

- [ ] **Sticky top bar (title, theme toggle, disclaimer)** — **(requested)** · M
  Pin the page title, the light/dark toggle, and the self-reported disclaimer to
  the top so they stay visible while scrolling; the source links and stat cards
  scroll away with the page. Splits the current single header into a pinned bar
  and a scrollable intro block (CSS `position: sticky`).

- [ ] **Chart-navigation sidebar with scroll-spy** — **(requested)** · M
  A sidebar listing the chart headings that highlights the section currently in
  view (scroll-spy via `IntersectionObserver`) and lets you jump to any chart.
  Collapses to a menu (hamburger) button when the viewport is too narrow.

- [x] **Range/uncertainty whiskers on destination-vs-delivery (#2)** — **(requested)** · S–M · *done*
  Show delivery-window uncertainty on the destination-vs-delivery chart (#2) as
  horizontal whiskers spanning min–max (mirroring chart 1's vertical whiskers).
  Also make other inherently-ranged estimate types show their span — in
  particular `month` estimates (currently a single mid-month point) span the
  whole month, so they read as uncertain on charts 1 and 2 alike.

## Data pipeline & correctness

- [ ] **Manual fix-ups / overrides layer** — **(requested)** · M
  A version-controlled patch file (YAML/JSON, keyed by username) applied
  immediately after fetch, to correct or fill in partial entries when someone
  posted more detail in the forum but didn't update the source sheet. Should be:
  idempotent, non-destructive to the raw cache, validated against the schema,
  and surfaced in the sanitization report + stat-card hovers (like the existing
  dedup/de-obfuscation records) so every override is auditable. Natural home:
  `data/overrides.yaml` (tracked in git, unlike the ignored caches).

- [x] **Externalize schema & enum config** · S–M · *done*
  The full color/marker vocabulary, sheet sources, column maps, sanitize bounds,
  option vocab, geo tables, and delivery-normalization rules now live in four
  YAML files (`palette.yaml`, `schema.yaml`, `geo.yaml`, `delivery.yaml`) loaded
  by `config.py`. Adding a paint, changing a sheet key, adjusting a date bound,
  or teaching a new delivery token is a data edit — not a code change.

- [ ] **Schema-drift detection** · S
  Warn (and fail loudly, not silently mis-map) when the sheet's header row
  changes shape or column names — the loaders currently assume a fixed layout.

- [ ] **Data-quality / anomaly panel** · S–M
  Surface a QA summary: impossible/malformed dates, out-of-range VINs, likely
  duplicate usernames not auto-merged, and unparseable delivery strings — so the
  "unknown" buckets are inspectable rather than just counted.

## Fetch & hosting

- [ ] **Web app with a "Fetch new data" button** — **(requested)** · L
  Goal: refresh the data from the UI instead of re-running the CLI. Bonus goal:
  host statically (e.g. Cloudflare Pages). Architecture notes / options:
  - **CORS:** the browser can't fetch the Google Sheets CSV export directly
    (no permissive CORS headers). A tiny **Cloudflare Worker** proxy solves this
    cleanly and keeps the front end static.
  - **Where the cleaning runs:** (a) port `parsing`/`loaders` to JS, (b) reuse
    the existing Python in-browser via **Pyodide** (WASM), or (c) keep Python
    server-side and have the button trigger a rebuild.
  - **Recommended path:** start with a **scheduled rebuild + Worker proxy**
    (below) so the "button" just kicks a rebuild/refresh; move to full
    client-side (Pyodide) only if we want true on-demand, backend-free fetches.

- [ ] **Scheduled auto-refresh** · S–M
  A GitHub Action (or cron) that re-runs the pipeline on a schedule, commits the
  refreshed cache/outputs (or deploys them), so the published dashboard stays
  current without anyone running the CLI. Pairs naturally with the web app.

- [ ] **Historical trend tracking** · M
  The timestamped, change-detected caches in `data/raw/` are already a dated
  history — mine them to chart how metrics evolve over time (order volume,
  VIN-assignment rate, delivery-estimate firmness) and add a "what changed since
  last fetch" feed (new orders, newly-assigned VINs).

## Analytics depth

- [x] **VIN-by-configuration chart** · S · *done*
  Chart #10: VIN sequence (x) against one row per `trim · color · wheels` config
  (marker fill = paint, shape = wheels), to reveal whether production batches
  within a config. Rows are sorted trim → color → wheel and auto-extend as
  Premium / Standard trims ship (everyone is Performance / Launch Edition today).

- [ ] **VIN-velocity / production-cadence estimate** · M
  Model VIN-sequence issuance over time to project build cadence and rough
  delivery ordering.

- [ ] **Delivery-estimate accuracy tracking** · M
  As actual deliveries are reported, compare them against the earlier quoted
  windows to score how optimistic the self-reported estimates were.

## Engineering / project health

- [ ] **CI** · S
  GitHub Actions to run the tests (and a lint pass) on every push.

- [ ] **Expand test coverage** · M
  Beyond `parsing`: loaders (dedup, matched-reservation removal, date bounds),
  fetch (change detection + newest-cache selection), and chart smoke tests
  (every `fig_*` builds without error on a small fixture).

- [ ] **Lint / format / types** · S
  ruff + a formatter + pre-commit hooks; add type hints and a mypy pass.

- [ ] **Dependency hygiene** · S
  Declare/pin runtime versions and add a `dev` extra (pytest, ruff, mypy) in
  `pyproject.toml`.
