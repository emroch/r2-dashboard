"""Configuration: paths, run timestamps, and the loaders for the externalized
data files (palette.yaml, schema.yaml, geo.yaml, delivery.yaml).

Kept import-light on purpose so every other module can pull constants from here
without a circular dependency. NOW/AS_OF are evaluated at import time. The
color/marker, schema, geo, and delivery tables all live in the YAML files under
conf/ — editing those is a data change, not a code change.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# Project root is one level above this file: src/config.py -> ROOT (repo root).
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"
for d in (DATA_RAW, DATA_PROCESSED, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)
CLEAN_CSV = str(DATA_PROCESSED / "r2_orders_clean.csv")
DASHBOARD = str(OUTPUT_DIR / "r2_orders_dashboard.html")

# Local cache filename timestamp format (see fetch.py change detection).
CACHE_TS_FMT = "%Y%m%d-%H%M%S"

# Wall-clock of this run: NOW timestamps caches/fetches; AS_OF (date only) labels
# the dashboard and anchors relative delivery windows / bounds sanitization.
NOW = datetime.now()
AS_OF = pd.Timestamp(NOW.date())

# --------------------------------------------------------------------------
# Externalized config files (src/conf/*.yaml) — edit these (data), not the code.
# --------------------------------------------------------------------------
_CONF = Path(__file__).parent / "conf"


def _load(name):
    with open(_CONF / name) as fh:
        return yaml.safe_load(fh)


_PALETTE = _load("palette.yaml")   # colors & marker encodings
_SCHEMA = _load("schema.yaml")     # sources, column maps, sanitize, option vocab
_GEO = _load("geo.yaml")           # state/province -> region + coords
_DELIV = _load("delivery.yaml")    # delivery-estimate normalization tables
_THEME = _load("theme.yaml")       # page & chart chrome (light/dark)
_PRICE = _load("pricing.yaml")     # trim/option prices for the configured price

# Manual curation (overrides.yaml), applied after fetch/dedup, before cleaning:
# OVERRIDES edit fields on rows already in the sheet; ADDITIONS append forum-only
# orders not in the sheet. Both are username-keyed and empty by default.
_CURATION = _load("overrides.yaml")
OVERRIDES = _CURATION.get("overrides") or {}
ADDITIONS = _CURATION.get("additions") or {}

# --- Live sources (schema.yaml) -------------------------------------------
# EXPORT_URL is the CSV endpoint; VIEW_URL is the human sheet linked in the header.
EXPORT_URL = _SCHEMA["export_url"]
VIEW_URL = _SCHEMA["view_url"]
_ORDERS_SRC = _SCHEMA["sources"]["orders"]
_RESV_SRC = _SCHEMA["sources"]["reservations"]
ORDERS_KEY, ORDERS_GID = _ORDERS_SRC["key"], _ORDERS_SRC["gid"]
ORDERS_LABEL, ORDERS_SLUG = _ORDERS_SRC["label"], _ORDERS_SRC["slug"]
RESV_KEY, RESV_GID = _RESV_SRC["key"], _RESV_SRC["gid"]
RESV_LABEL, RESV_SLUG = _RESV_SRC["label"], _RESV_SRC["slug"]
# Forum thread behind each tracker — where an entry is submitted or corrected.
ORDERS_THREAD = _ORDERS_SRC["thread_url"]
RESV_THREAD = _RESV_SRC["thread_url"]

# --- Colors & marker encodings (palette.yaml) -----------------------------
# Exterior paints: the display hex actually used. COLOR_ORDER drives ordering.
COLOR_HEX = dict(_PALETTE["paints"])
COLOR_ORDER = list(_PALETTE["paint_order"])
# Interiors, keyed by the exact sheet value for the same reason as wheels: two of
# them share the "Black Crater" base name and differ only by the Signature
# suffix, so nothing may derive one label from the other. INTERIOR_ORDER is the
# palette's plainest-first order, which the charts display in.
_INTERIORS = _PALETTE["interiors"]
INTERIOR_ORDER = list(_INTERIORS)
INTERIOR_SHORT = {k: v["short"] for k, v in _INTERIORS.items()}
INTERIOR_COLOR = {k: v["color"] for k, v in _INTERIORS.items()}
# Wheels. The palette is keyed by the exact sheet value; WHEEL_SHORT maps that to
# the display label, and every other table is keyed BY that label, since it's the
# label the DataFrame carries (wheels_short). WHEEL_ORDER preserves the palette's
# ascending-size order, which is the stack order the colors were validated in.
# Two of the four wheels are 20", so nothing here may infer identity from size.
_WHEELS = _PALETTE["wheels"]
WHEEL_SHORT = {raw: w["short"] for raw, w in _WHEELS.items()}
WHEEL_ORDER = [w["short"] for w in _WHEELS.values()]
WHEEL_ABBR = {w["short"]: w["abbr"] for w in _WHEELS.values()}
WHEEL_SYMBOL = {w["short"]: w["symbol"] for w in _WHEELS.values()}
WHEEL_COLOR = {w["short"]: w["color"] for w in _WHEELS.values()}
REGION_COLOR = dict(_PALETTE["regions"])
TYPE_COLOR = {t: d["color"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_OPACITY = {t: d["opacity"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_ORDER = list(_PALETTE["delivery_type_order"])
# Single-series chart fills (bars/histograms) + the heatmap colorscale name.
TAKE_RATE = dict(_PALETTE["take_rate"])
TIMELINE_COLORS = dict(_PALETTE["timeline"])
HEATMAP_COLORSCALE = str(_PALETTE["heatmap_colorscale"])
# Per-state totals bars: VIN-assigned vs. not (stacked to each state's total).
STATE_TOTALS_COLORS = dict(_PALETTE["state_totals"])
# Configured-price charts: neutral bar + Compass Yellow accent.
PRICE_COLORS = dict(_PALETTE["price"])
# Stacked take-rate panels: trim ramp, and which R1 an owner has.
TRIM_COLORS = dict(_PALETTE["trims"])
R1_MODEL_COLORS = dict(_PALETTE["r1_models"])

# --- Column maps (schema.yaml) --------------------------------------------
# Both maps are field -> exact sheet header text, and both sheets are read the
# same way: columns are located BY NAME, so only what's mapped is read and the
# sheets may reorder or grow columns freely (see ingest/schema_check.py). Field
# order is cosmetic — it sets the cleaned CSV's column order. IGNORED lists the
# columns each sheet has that we knowingly skip, so only a NEW unmapped column
# gets reported.
_ORDERS_COLS = dict(_SCHEMA["orders_columns"])
ORDERS_COLUMNS = list(_ORDERS_COLS)   # field names, in sheet order
ORDERS_HEADERS = _ORDERS_COLS         # field -> expected sheet header text
RESERVATIONS_COLUMNS = dict(_SCHEMA["reservations_columns"])
_IGNORED = _SCHEMA.get("ignored_columns") or {}
ORDERS_IGNORED = list(_IGNORED.get("orders") or [])
RESV_IGNORED = list(_IGNORED.get("reservations") or [])

# --- Sanitization bounds (schema.yaml) ------------------------------------
_SAN = _SCHEMA["sanitize"]
ORDER_DATE_MIN = pd.Timestamp(_SAN["order_date_min"])
RESV_DATE_MIN = pd.Timestamp(_SAN["reservation_date_min"])
ORDER_ANCHOR_MIN = pd.Timestamp(_SAN["order_anchor_min"])
VIN_SEQ_MIN = int(_SAN["vin_seq_min"])
# Plausible year window for a parsed delivery estimate (typo guard).
DELIVERY_YEAR_MIN = int(_SAN["delivery_year_min"])
DELIVERY_YEAR_MAX = int(_SAN["delivery_year_max"])

# --- Option take-rate vocabulary (schema.yaml) ----------------------------
_OPT = _SCHEMA["options"]
OPTED_IN_TOKENS = list(_OPT["opted_in_tokens"])
SPARE_TOKENS = list(_OPT["spare_tokens"])

# --- Option availability (schema.yaml) ------------------------------------
# {column: [(prefix_lower, available_from | None)]}: the earliest date each
# not-yet-released trim/paint/interior could be ordered. None == "unreleased"
# (no order for it is valid yet). The loader drops any order selecting an option
# before its available_from — the config wasn't buildable at order time.
def _avail_date(value):
    if pd.isna(value):
        return None
    if str(value).strip().lower() in ("", "unreleased", "tbd", "none", "n/a"):
        return None
    return pd.Timestamp(value)


AVAILABILITY = {
    col: [(str(opt).strip().lower(), _avail_date(when))
          for opt, when in (opts or {}).items()]
    for col, opts in (_SCHEMA.get("availability") or {}).items()
}

# --- Configured-vehicle pricing (pricing.yaml) ----------------------------
# Catalogs shared across trims (paints/interiors/add-ons cost the same wherever
# they're offered) plus per-trim data. Wheels live INSIDE each trim, since the
# same wheel can be standard on one trim and a paid upgrade on the next. A price
# of None means "not published yet" -> the order's price is unknown, reported in
# an explicit bucket rather than dropped. See pricing.yaml's header.
PRICE_PAINTS = dict(_PRICE["paints"])
PRICE_INTERIORS = dict(_PRICE["interiors"])
PRICE_DRIVE_SYSTEMS = dict(_PRICE["drive_systems"])
PRICE_OPTIONS = dict(_PRICE["options"])
PRICE_PACKAGES = {k: dict(v) for k, v in _PRICE["packages"].items()}
PRICE_TRIMS = {k: dict(v) for k, v in _PRICE["trims"].items()}
# Sheet trim label -> {trim, drive_system}: a Standard order encodes both in one
# label because the sheet has no drive-system column.
PRICE_TRIM_ALIASES = {k: dict(v)
                      for k, v in (_PRICE.get("trim_aliases") or {}).items()}

# --- Geo (geo.yaml) -------------------------------------------------------
# Bloomington-Normal, IL assembly plant + state/province lookup tables.
FACTORY = tuple(_GEO["factory"])
STATE_INFO = {k: tuple(v) for k, v in _GEO["states"].items()}
CA_PROVINCES = dict(_GEO["provinces"])
# Per-state reference figures for the wheel-by-location panels:
# state -> (mean_elevation_ft, mean_annual_temp_f, percent_urban). Approximate
# published figures, US states only — see geo.yaml's header for each one's source
# and the specific way it is weak. A state absent here (every Canadian province)
# yields NaN and lands in an explicit "no data" bar, never guessed at or dropped.
STATE_REFERENCE = {k: tuple(v)
                   for k, v in (_GEO.get("state_reference") or {}).items()}
_REF_BINS = _GEO.get("state_reference_bins") or {}
ELEV_BINS = [float(x) for x in (_REF_BINS.get("elevation_ft") or [])]
TEMP_BINS = [float(x) for x in (_REF_BINS.get("temperature_f") or [])]
URBAN_BINS = [float(x) for x in (_REF_BINS.get("urban_pct") or [])]

# --- Delivery-estimate normalization (delivery.yaml) ----------------------
UNKNOWN_TOKENS = set(_DELIV["unknown_tokens"])
UNKNOWN_SUBSTRINGS = list(_DELIV["unknown_substrings"])
DELIVERY_OVERRIDES = {raw: (v["min"], v["max"], v["type"])
                      for raw, v in _DELIV["overrides"].items()}
MONTHS = dict(_DELIV["months"])
# Fuzzy within-month modifiers: lowercased keyword -> (start_day, end_day), where
# end_day == -1 means that month's last day. Used by parse_delivery for phrases
# like "end of July" / "early August".
MONTH_MODIFIERS = {str(k).lower(): tuple(v)
                   for k, v in (_DELIV.get("month_modifiers") or {}).items()}

# --- Page & chart chrome (theme.yaml) -------------------------------------
# THEME_CSS drives the CSS custom properties (light / dark / theme-independent
# fixed); CHART_CHROME is the chart chrome the theme toggle swaps, and CHART is
# the light half baked into the server-rendered charts; CHART_UI holds static
# (non-swapped) chart accents.
THEME_CSS = _THEME["css"]
CHART_CHROME = _THEME["chart"]
CHART = _THEME["chart"]["light"]
CHART_UI = _THEME["chart_ui"]
