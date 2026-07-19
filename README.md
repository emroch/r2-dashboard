# R2 Orders

Parses, sanitizes, and visualizes crowd-sourced **Rivian R2 pre-order** data into
an interactive Plotly dashboard. It pulls two live Google Sheets (an
orders/deliveries tracker and a separate reservations-only tracker) via their CSV
export endpoints, cleans them (dedup, VIN recovery, date normalization, geo
enrichment), removes reservation-holders who have already ordered, and produces a
tidy CSV plus a 10-chart HTML dashboard.

## Project layout

```
r2_dashboard          run-in-place launcher (./r2_dashboard); also `python3 src/pipeline.py`
requirements.txt      pandas, numpy, plotly, PyYAML
src/
  config.py           paths, run timestamps + loaders for the conf/ YAML files
  pipeline.py         main() orchestration + report printing (fetch -> clean -> render)
  ingest/             get + clean the data
    fetch.py          live-sheet fetch with caching + change detection
    parsing.py        pure parsing / VIN / date / geo helpers
    loaders.py        load_and_clean, load_reservations
  render/             build the webpage
    colors.py         color-transform functions + derived display palettes
    charts.py         the ten fig_* chart builders + helpers
    page.py           template loading, HTML helpers, SECTIONS, build_dashboard
  templates/          page shell + assets filled at render time
    page.html         HTML shell ({{token}} placeholders)
    styles.css        page stylesheet (generated theme vars prepended)
    head.js           pre-paint theme set (no flash)
    theme.js          re-tint chart chrome on light/dark toggle
    nav.js            sidebar hamburger + scroll-spy
  conf/               data/config YAML (loaded by config.py)
    palette.yaml      data-encoding colors & markers (paints, interiors, wheels, regions, types, chart fills)
    theme.yaml        page & chart chrome for light/dark (CSS variables + chart retint colors)
    schema.yaml       sheet sources, column maps, sanitize bounds, option vocab
    geo.yaml          state/province -> region + coordinates, factory, province aliases
    delivery.yaml     delivery-estimate normalization (tokens, overrides, month names)
    overrides.yaml    manual curation: overrides (edit existing rows) + additions (forum-only orders)
data/
  raw/                timestamped live caches (git-ignored)
  processed/          cleaned CSV output
output/               dashboard HTML output
tests/
  test_parsing.py     unit tests (run via pytest OR plain python3)
```

## Running

From the project root:

```sh
./r2_dashboard          # or: python3 src/pipeline.py
```

It's a run-in-place project (no install step). Dependencies are listed in
`requirements.txt` (pandas, numpy, plotly, PyYAML).

## Outputs

- `data/processed/r2_orders_clean.csv` — the cleaned, tidy dataset.
- `output/r2_orders_dashboard.html` — the interactive dashboard.
- `data/raw/r2_orders_live_*.csv`, `data/raw/r2_reservations_live_*.csv` — timestamped
  live caches. A new cache is written only when the fetched content differs from
  the newest cache (change detection), so a cache's timestamp marks when the data
  last changed. If a live fetch fails, the newest cache is used.

## Data source

Two live Google Sheets, pulled on demand via their CSV export endpoint:

- **Orders & Deliveries** tracker (one row per person; VIN, config, delivery estimate).
- **Reservations** tracker (reservation-only holders — no order/VIN/config).

The data is self-reported and noisy; treat all figures as indicative. It is
always pulled live and cached under `data/raw/`; there are no hand-maintained
snapshots.

## Tests

```sh
python3 tests/test_parsing.py     # no pytest required
# or
pytest tests/
```

## Roadmap

Planned improvements are tracked in [ROADMAP.md](ROADMAP.md).
