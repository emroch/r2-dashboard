# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This is a small **Python data-analysis package** (`r2-orders`, src-layout) that parses, sanitizes, and visualizes crowd-sourced **Rivian R2 pre-order** data (compiled from owner/reservation-holder reports, one row per person). Work here is still primarily data analysis and cleaning, but it now lives in a proper package rather than a single script.

Structure:

```
src/r2_orders/
  config.py     paths, run timestamps (NOW/AS_OF) + loaders for the YAML config files below
  palette.yaml  colors & marker encodings — paints, interiors, wheels, regions, delivery-type colors/opacity
  schema.yaml   sheet sources (keys/gids/labels), column maps, sanitize bounds, option take-rate vocab
  geo.yaml      state/province -> region + coordinates, factory location, province-name aliases
  delivery.yaml delivery-estimate normalization — unknown tokens/substrings, explicit overrides, month names
  overrides.yaml manual curation applied after fetch — `overrides` (edit fields on existing rows) + `additions` (append forum-only orders)
  colors.py     color-transform helpers + derived display palettes (COLOR_DISPLAY / WHISKER_HEX)
  parsing.py    pure parsing / VIN / date / geo helpers
  loaders.py    load_and_clean, load_reservations
  charts.py     the nine fig_* chart builders + helpers
  dashboard.py  page CSS, HTML helpers, SECTIONS, build_dashboard
  fetch.py      live-sheet fetch with caching + change detection
  cli.py        main() orchestration + report printing
  __main__.py   python -m r2_orders entry point
data/raw/        timestamped live caches (auto change-detected)
data/processed/  cleaned CSV output
output/          dashboard HTML output
tests/           unit tests (test_parsing.py)
```

The package pulls **two live Google Sheets** (an orders/deliveries tracker and a separate reservations-only tracker) via their CSV export endpoints, cleans them (dedup, VIN recovery, date normalization, geo enrichment), drops reservation-holders who have already ordered, writes a tidy CSV, and builds a 9-chart interactive Plotly dashboard.

## Working with the data

Run the pipeline from the project root:

```sh
PYTHONPATH=src python -m r2_orders     # or `pip install -e .` then `r2-orders`
```

Outputs:
- `data/processed/r2_orders_clean.csv` — the cleaned, tidy dataset.
- `output/r2_orders_dashboard.html` — the interactive dashboard.
- `data/raw/r2_orders_live_*.csv`, `data/raw/r2_reservations_live_*.csv` — timestamped live caches. A new cache is written **only when the fetched content differs** from the newest cache (change detection, since the export sends no Last-Modified/ETag), so a cache's timestamp marks when the data last changed. If a live fetch fails, the newest cache is used.

Tests: `python tests/test_parsing.py` (no pytest required) or `pytest tests/`.

Dependencies (pandas, numpy, plotly) are expected to be available in the environment; there is no venv. Because the source sheets are hand-maintained spreadsheet exports, **always account for the quirks below before computing statistics.**

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
- Configuration lives in YAML files loaded by `config.py` at import — `palette.yaml` (colors/markers), `schema.yaml` (sources, column maps, sanitize bounds, option vocab), `geo.yaml` (states/provinces/factory), `delivery.yaml` (delivery-estimate normalization), and `overrides.yaml` (manual curation applied after fetch: `overrides` edit fields on rows already in the sheet, `additions` append forum-only orders not in the sheet). Adding a paint, changing a sheet key, adjusting a date bound, teaching a new delivery token, correcting a partial entry, or adding a forum-only order is a data edit in these files, not a code change.
- Free-text fields are self-reported and noisy; prefer reporting distributions with an explicit "unparseable/unknown" bucket over silently dropping rows.
