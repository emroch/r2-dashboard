# R2 Orders

Parses, sanitizes, and visualizes crowd-sourced **Rivian R2 pre-order** data into
an interactive Plotly dashboard. It pulls two live Google Sheets (an
orders/deliveries tracker and a separate reservations-only tracker) via their CSV
export endpoints, cleans them (dedup, VIN recovery, date normalization, geo
enrichment), removes reservation-holders who have already ordered, and produces a
tidy CSV plus a 9-chart HTML dashboard.

## Project layout

```
src/r2_orders/
  __init__.py         package docstring + __version__
  __main__.py         python -m r2_orders entry point
  config.py           paths, live-source endpoints, run timestamps, data tables
  colors.py           color-transform functions + derived display palettes
  parsing.py          pure parsing / VIN / date / geo helpers
  loaders.py          load_and_clean, load_reservations
  charts.py           the nine fig_* chart builders + helpers
  dashboard.py        page CSS, HTML helpers, SECTIONS, build_dashboard
  fetch.py            live-sheet fetch with caching + change detection
  cli.py              main() orchestration + report printing
data/
  raw/                timestamped live caches (git-ignored)
  processed/          cleaned CSV output
output/               dashboard HTML output
tests/
  test_parsing.py     unit tests (run via pytest OR plain python)
pyproject.toml
```

## Running

From the project root, either:

```sh
PYTHONPATH=src python -m r2_orders
```

or install the package (which registers an `r2-orders` console command):

```sh
pip install -e .
r2-orders
```

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
python tests/test_parsing.py     # no pytest required
# or
pytest tests/
```
