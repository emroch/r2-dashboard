# Roadmap

Tracked improvements for the `r2-orders` dashboard. Items marked **(requested)**
were asked for directly; the rest are proposed. Rough effort: **S** ≈ hours,
**M** ≈ a day, **L** ≈ multi-day. Unchecked = not started.

---

## Presentation & UX

- [ ] **Dark / light theme toggle** — **(requested)** · S–M
  Drive the page CSS from CSS custom properties, add a toggle that persists the
  choice (`localStorage`) and respects `prefers-color-scheme`. Swap the Plotly
  template per theme (`plotly_white` ↔ `plotly_dark`) and re-tint the whisker /
  bubble / near-white-bar colors so they stay legible on a dark background.

- [ ] **Interactive filters** · M
  Client-side filtering by state/region, config (color, wheels, interior),
  purchase vs. lease, and "VIN-assigned only" — updates all charts at once.

- [ ] **Per-chart export & data table** · S
  PNG export (Plotly already supports it) plus a "download this chart's data as
  CSV" and a raw sortable data-table view of the cleaned dataset.

- [ ] **Accessibility & responsive layout** · M
  Color-blind-safe palette option, ARIA labels, and a layout that reflows for
  narrow/mobile screens (the 3 stacked geo maps and wide charts especially).

## Data pipeline & correctness

- [ ] **Manual fix-ups / overrides layer** — **(requested)** · M
  A version-controlled patch file (YAML/JSON, keyed by username) applied
  immediately after fetch, to correct or fill in partial entries when someone
  posted more detail in the forum but didn't update the source sheet. Should be:
  idempotent, non-destructive to the raw cache, validated against the schema,
  and surfaced in the sanitization report + stat-card hovers (like the existing
  dedup/de-obfuscation records) so every override is auditable. Natural home:
  `data/overrides.yaml` (tracked in git, unlike the ignored caches).

- [ ] **Externalize schema & enum config** · S–M
  Move the column map, known paint colors (+ measured RGB), interiors, and
  option vocab into a config file so adding a new option (e.g. a future
  "Forest Green" or a new interior) is a data edit, not a code change. Reduces
  the risk of a `KeyError` when the sheet gains a value.

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
