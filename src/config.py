"""Configuration: paths, run timestamps, and the loaders for the externalized
data files (dimensions.yaml, palette.yaml, schema.yaml, geo.yaml, delivery.yaml, ...).

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
# The published data contract (ingest/contract.py), deployed beside the CSV.
DIMENSIONS_JSON = str(DATA_PROCESSED / "r2_dimensions.json")
SERIES_JSON = str(DATA_PROCESSED / "r2_series.json")
# The page's view data (render/view.py): spec + data for each browser-drawn
# component. Fetched by the page; deployed beside the contract files.
VIEW_JSON = str(DATA_PROCESSED / "r2_view.json")
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


_PALETTE = _load("palette.yaml")   # chart fills (category colors: dimensions.yaml)
_SCHEMA = _load("schema.yaml")     # sources, column maps, sanitize, option vocab
_GEO = _load("geo.yaml")           # state/province -> region + coords
_DELIV = _load("delivery.yaml")    # delivery-estimate normalization tables
_THEME = _load("theme.yaml")       # page & chart chrome (light/dark)
_PRICE = _load("pricing.yaml")     # trim/option prices for the configured price
# The page's section registry: order, title, prose, and what each section draws.
SECTIONS_CONF = _load("sections.yaml")["sections"]
# The presentation layer's components, by id (what each draws and says).
COMPONENTS = _load("charts.yaml")["components"]

# Manual curation (overrides.yaml), applied after fetch/dedup, before cleaning:
# OVERRIDES edit fields on rows already in the sheet; ADDITIONS append forum-only
# orders not in the sheet; DELETIONS drop entries the person has said no longer
# exist (a cancellation), per sheet; VERIFIED names values confirmed correct that
# the entry-error checks would otherwise set aside (ingest/outliers.py). All are
# username-keyed and empty by default.
_CURATION = _load("overrides.yaml")
OVERRIDES = _CURATION.get("overrides") or {}
ADDITIONS = _CURATION.get("additions") or {}
_DELETIONS = _CURATION.get("deletions") or {}
DELETIONS_ORDERS = _DELETIONS.get("orders") or {}
DELETIONS_RESV = _DELETIONS.get("reservations") or {}
# A verified entry is a list of fields, or (curation v2) a mapping with `fields`
# plus its source/as_of. Either way the checks only need the fields.
VERIFIED_RAW = _CURATION.get("verified") or {}
VERIFIED = {str(u).lower(): list((v.get("fields") if isinstance(v, dict) else v)
                                 or [])
            for u, v in VERIFIED_RAW.items()}
# 1 = the format before provenance fields; 2 = every entry carries source/as_of
# (set by tools/migrate_curation.py; see ingest/curation.py).
CURATION_VERSION = int(_CURATION.get("curation_version", 1))

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

# --- Category vocabulary (dimensions.yaml) --------------------------------
# Every categorical column's categories, labels and colors live in one file, which
# is also published as-is (r2_dimensions.json, ingest/contract.py). The constants
# below are views of it for the charts.
DIMENSIONS = _load("dimensions.yaml")["dimensions"]


def _cats(dim):
    return DIMENSIONS[dim]["categories"]


# Exterior paints: the display hex actually used. COLOR_ORDER is the curated
# sequence, which the charts use only to break ties when ranking paints by order
# count (see charts._paint_order) — it is not the display order.
COLOR_HEX = {c["value"]: c["color"] for c in _cats("color")}
COLOR_ORDER = [c["value"] for c in _cats("color")]
# Interiors, keyed by the exact sheet value: two of them share the "Black
# Crater" base name and differ only by the Signature suffix, so nothing may
# derive one label from the other. INTERIOR_ORDER is plainest-first, which the
# charts display in.
INTERIOR_ORDER = [c["value"] for c in _cats("interior")]
INTERIOR_SHORT = {c["value"]: c["short"] for c in _cats("interior")}
# Wheels. Each is identified by its exact sheet value; WHEEL_SHORT maps that to
# the display label, and every other table is keyed BY that label, since it's the
# label the DataFrame carries (wheels_short). WHEEL_ORDER is ascending size, the
# stack order the colors were validated in. Two of the four wheels are 20", so
# nothing here may infer identity from size.
WHEEL_SHORT = {c["sheet"]: c["value"] for c in _cats("wheels")}
WHEEL_ORDER = [c["value"] for c in _cats("wheels")]
WHEEL_ABBR = {c["value"]: c["abbr"] for c in _cats("wheels")}
WHEEL_SYMBOL = {c["value"]: c["symbol"] for c in _cats("wheels")}
REGION_COLOR = {c["value"]: c["color"] for c in _cats("region")}
# Delivery-estimate types, firm to vague. TYPE_ORDER leaves out the "no estimate"
# category, which the charts handle on its own.
TYPE_ORDER = [c["value"] for c in _cats("delivery_type")
              if c["value"] != DIMENSIONS["delivery_type"]["missing"]["value"]]

# --- Chart fills (palette.yaml) --------------------------------------------
# Single-series chart fills (bars/histograms).
TIMELINE_COLORS = dict(_PALETTE["timeline"])
# Configured-price charts: neutral bar + Compass Yellow accent.
PRICE_COLORS = dict(_PALETTE["price"])
# Order-to-delivery time: order markers, weekly median, coverage bars.
LATENCY_COLORS = dict(_PALETTE["latency"])
# Build front / projection overlay and the cadence companion chart.
CADENCE_COLORS = dict(_PALETTE["cadence"])

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
# Order -> delivery sanity window in days (see parsing.implausible_latency).
DELIVERY_LATENCY_MAX = int(_SAN.get("delivery_latency_max_days", 365))
# Likely-entry-error checks against each value's cohort (see ingest/outliers.py).
_OUT = _SAN.get("entry_errors") or {}
OUTLIER_COHORT = int(_OUT.get("cohort", 41))
OUTLIER_VIN_Z = float(_OUT.get("vin_z", 8))
OUTLIER_EARLY_DELIVERY_Z = float(_OUT.get("early_delivery_z", 4))

# Columns that identify a build, for collapsing repeat submissions (see
# schema.yaml). Rows sharing a username AND all of these are the same order.
DEDUPE_IDENTITY = list(_SCHEMA.get("dedupe_identity_columns") or [])

# --- Build cadence / projected build front (schema.yaml) ------------------
_CAD = _SCHEMA.get("cadence") or {}
CADENCE_FRONT_Q = float(_CAD.get("front_quantile", 0.9))
CADENCE_WINDOW_WEEKS = int(_CAD.get("window_weeks", 6))
CADENCE_MIN_WEEK_N = int(_CAD.get("min_week_n", 4))
CADENCE_HORIZON_WEEKS = int(_CAD.get("horizon_weeks", 4))
CADENCE_BACKTEST_CUTS = int(_CAD.get("backtest_cuts", 8))

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
# Bin edges by name, for a component that bins by one (charts.yaml `bins`).
REF_BINS = {k: [float(x) for x in (v or [])] for k, v in _REF_BINS.items()}

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
