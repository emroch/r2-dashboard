# Roadmap

Tracked improvements for the `r2_dashboard` project. Items marked **(requested)**
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

- [x] **Interactive filters** · M · *done (v2: per-series legend)*
  Legend-driven filtering with pinned axes (fixed type + range) so toggling or
  zooming never rescales the view, keeping configs comparable. Charts 1 & 3 split
  each config into per-(paint × wheel) legend entries (marker shape = wheels),
  each toggling / double-click-isolating on its own; on chart 1 each series'
  delivery-window whiskers ride its legendgroup, and a whisker on/off button
  declutters. Chart 2's whiskers are region-paired (tinted grey) with the same
  toggle; chart 6 uses `toggleitem` so its stacked reservation series toggle
  independently. A full cross-chart filter — re-aggregating every chart in JS by
  state/config/buy-lease/VIN-status — was considered and deferred as a larger build.

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

- [x] **Sticky top bar (title, theme toggle, disclaimer)** — **(requested)** · M · *done*
  Pins the page title, the light/dark toggle, and the self-reported disclaimer to
  the top (`position: sticky`) so they stay visible while scrolling; the source
  links and stat cards live in a scrollable intro block that scrolls away. (Also
  fixed the geographic-demand legends to use constant-size swatches.)

- [x] **Chart-navigation sidebar with scroll-spy** — **(requested)** · M · *done*
  Launch-Green left rail listing every section; an `IntersectionObserver`
  scroll-spy highlights the one in view, and links smooth-scroll to their chart.
  A top-left hamburger toggles it at any width (pushes content on wide, overlays
  with a backdrop on narrow). Header/sidebar greens are sourced from the palette
  (Forest Green header, Launch Green rail) as a nod to the Rivian paints.

- [x] **Range/uncertainty whiskers on destination-vs-delivery (#2)** — **(requested)** · S–M · *done*
  Show delivery-window uncertainty on the destination-vs-delivery chart (#2) as
  horizontal whiskers spanning min–max (mirroring chart 1's vertical whiskers).
  Also make other inherently-ranged estimate types show their span — in
  particular `month` estimates (currently a single mid-month point) span the
  whole month, so they read as uncertain on charts 1 and 2 alike.

## Data pipeline & correctness

- [x] **Manual fix-ups / overrides layer** — **(requested)** · M · *done*
  `src/conf/overrides.yaml` (username → raw-field corrections) is applied
  right after dedup, so fixes flow through normal cleaning. Case-insensitive,
  schema-validated, idempotent, and non-destructive to the cache. Applied changes
  show in a "Manual fix-ups" stat card + the report; bad field names / unknown
  usernames surface as "Override issues" in the QA panel. (Lives in the package
  with the other tracked YAMLs, since `data/` is git-ignored.)

- [x] **Externalize schema & enum config** · S–M · *done*
  The full color/marker vocabulary, sheet sources, column maps, sanitize bounds,
  option vocab, geo tables, and delivery-normalization rules now live in four
  YAML files (`palette.yaml`, `schema.yaml`, `geo.yaml`, `delivery.yaml`) loaded
  by `config.py`. Adding a paint, changing a sheet key, adjusting a date bound,
  or teaching a new delivery token is a data edit — not a code change.

- [ ] **Schema-drift detection** · S
  Warn (and fail loudly, not silently mis-map) when the sheet's header row
  changes shape or column names — the loaders currently assume a fixed layout.

- [x] **Data-quality / anomaly panel** · S–M · *done*
  Section 11 surfaces a QA summary — unparseable delivery strings, possible
  duplicate usernames not auto-merged, unrecoverable VINs, and dropped invalid
  dates — plus a delivery-string→parsed-date conversion table for sanity-checking
  the normalization. The header delivery-estimate cards now partition every order
  (firm + range/window + no-date + unparseable = total).

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
  - **Shipped:** static hosting + the scheduled rebuild + the Worker proxy are
    live (dashboard at emroch.com/r2-dashboard); only the in-page "Fetch" button
    remains — a Worker `POST` → GitHub `repository_dispatch` to kick the workflow.

- [x] **Scheduled auto-refresh** · S–M · *done*
  A daily GitHub Actions workflow (`.github/workflows/deploy.yml`) re-runs the
  pipeline, deploys the static output to Cloudflare Pages, and commits the
  refreshed `data/raw/` caches back — the published dashboard stays current and
  the fetch history accrues without any manual CLI runs.

- [ ] **Historical trend tracking** · M
  `data/raw/` is now committed on every refresh, so the timestamped,
  change-detected caches are accruing as a dated history in git — mine them to
  chart how metrics evolve over time (order volume,
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
  Pin runtime versions in `requirements.txt` and add a dev requirements set
  (pytest, ruff, mypy).
