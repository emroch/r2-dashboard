"""Configuration: paths, run timestamps, and the loaders for the externalized
data files (palette.yaml, schema.yaml, geo.yaml, delivery.yaml).

Kept import-light on purpose so every other module can pull constants from here
without a circular dependency. NOW/AS_OF are evaluated at import time. The
color/marker, schema, geo, and delivery tables all live in the sibling YAML
files — editing those is a data change, not a code change.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
# Project root is two levels above this file: src/r2_orders/config.py -> ROOT.
ROOT = Path(__file__).resolve().parents[2]
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
# Externalized config files — edit these (data), not the code below.
# --------------------------------------------------------------------------
_HERE = Path(__file__).parent


def _load(name):
    with open(_HERE / name) as fh:
        return yaml.safe_load(fh)


_PALETTE = _load("palette.yaml")   # colors & marker encodings
_SCHEMA = _load("schema.yaml")     # sources, column maps, sanitize, option vocab
_GEO = _load("geo.yaml")           # state/province -> region + coords
_DELIV = _load("delivery.yaml")    # delivery-estimate normalization tables

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

# --- Colors & marker encodings (palette.yaml) -----------------------------
# Exterior paints: the display hex actually used. COLOR_ORDER drives ordering.
COLOR_HEX = dict(_PALETTE["paints"])
COLOR_ORDER = list(_PALETTE["paint_order"])
INTERIOR_COLOR = dict(_PALETTE["interiors"])
WHEEL_SYMBOL = dict(_PALETTE["wheels"])
REGION_COLOR = dict(_PALETTE["regions"])
TYPE_COLOR = {t: d["color"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_OPACITY = {t: d["opacity"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_ORDER = list(_PALETTE["delivery_type_order"])

# --- Column maps (schema.yaml) --------------------------------------------
# Orders: positional field names for the block starting at "#". Reservations:
# field -> header-name lookup (its sheet layout differs).
ORDERS_COLUMNS = list(_SCHEMA["orders_columns"])
RESERVATIONS_COLUMNS = dict(_SCHEMA["reservations_columns"])

# --- Sanitization bounds (schema.yaml) ------------------------------------
_SAN = _SCHEMA["sanitize"]
ORDER_DATE_MIN = pd.Timestamp(_SAN["order_date_min"])
RESV_DATE_MIN = pd.Timestamp(_SAN["reservation_date_min"])
ORDER_ANCHOR_MIN = pd.Timestamp(_SAN["order_anchor_min"])
VIN_SEQ_MIN = int(_SAN["vin_seq_min"])

# --- Option take-rate vocabulary (schema.yaml) ----------------------------
_OPT = _SCHEMA["options"]
OPTED_IN_TOKENS = list(_OPT["opted_in_tokens"])
SPARE_TOKENS = list(_OPT["spare_tokens"])
WHEELS_21_CONTAINS = str(_OPT["wheels_21_contains"])
# The two wheel labels come from the palette (single source of truth); classify
# by which one contains the 21" marker so we never duplicate the label strings.
WHEELS_LABEL_21 = next(k for k in WHEEL_SYMBOL if WHEELS_21_CONTAINS in k)
WHEELS_LABEL_20 = next(k for k in WHEEL_SYMBOL if WHEELS_21_CONTAINS not in k)

# --- Geo (geo.yaml) -------------------------------------------------------
# Bloomington-Normal, IL assembly plant + state/province lookup tables.
FACTORY = tuple(_GEO["factory"])
STATE_INFO = {k: tuple(v) for k, v in _GEO["states"].items()}
CA_PROVINCES = dict(_GEO["provinces"])

# --- Delivery-estimate normalization (delivery.yaml) ----------------------
UNKNOWN_TOKENS = set(_DELIV["unknown_tokens"])
UNKNOWN_SUBSTRINGS = list(_DELIV["unknown_substrings"])
DELIVERY_OVERRIDES = {raw: (v["min"], v["max"], v["type"])
                      for raw, v in _DELIV["overrides"].items()}
MONTHS = dict(_DELIV["months"])
