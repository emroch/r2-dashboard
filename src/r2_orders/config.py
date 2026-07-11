"""Configuration: paths, live-source endpoints, run timestamps, and all the
static data tables (colors, symbols, geo, delivery-normalization rules).

Kept import-light on purpose so every other module can pull constants from here
without a circular dependency. NOW/AS_OF are evaluated at import time, exactly
as in the original single-file script.
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

# Live sources: two shared Google Sheets pulled via the CSV export endpoint —
# the orders/deliveries tracker and a separate reservations-only tracker.
# EXPORT_URL is the machine endpoint; VIEW_URL is the human sheet linked from
# the dashboard header.
EXPORT_URL = "https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s"
VIEW_URL = "https://docs.google.com/spreadsheets/d/%s/preview?gid=%s"
ORDERS_KEY = "13dsTsw06i7C-pEfqGxh3e9Bl1EYxS4pIelrHrCaLZYk"
ORDERS_GID = "0"
RESV_KEY = "1Z_TSfn1eR580_ZBrTMGvO60-iKnEP8ZMKKC4q2Yv9Po"
RESV_GID = "0"

# Timestamped local caches (last good pulls, one dated file per data change).
# The export sends no Last-Modified/ETag and Cache-Control: no-store, so change
# detection diffs each fetch against the newest cache; a new cache is written
# only when the content differs, so a cache's timestamp marks the last update.
ORDERS_SLUG = "r2_orders_live"
RESV_SLUG = "r2_reservations_live"
CACHE_TS_FMT = "%Y%m%d-%H%M%S"

# Wall-clock of this run: NOW timestamps caches/fetches; AS_OF (date only)
# labels the dashboard and anchors relative delivery windows when a row's order
# date is missing or implausible.
NOW = datetime.now()
AS_OF = pd.Timestamp(NOW.date())

# Bloomington-Normal, IL assembly plant.
FACTORY = (40.5142, -88.9906)

# --------------------------------------------------------------------------
# Colors & marker encodings — loaded from palette.yaml so the whole color/marker
# vocabulary (paints, interiors, wheels, regions, delivery types) is editable as
# data. Adding a new paint is a one-entry edit there, not a code change.
# --------------------------------------------------------------------------
with open(Path(__file__).parent / "palette.yaml") as _fh:
    _PALETTE = yaml.safe_load(_fh)

# Exterior paints. COLOR_ORDER drives legend/axis ordering.
COLOR_HEX = dict(_PALETTE["paints"])
COLOR_ORDER = list(_PALETTE["paint_order"])

# Interior bar colors and wheels -> Plotly marker symbol.
INTERIOR_COLOR = dict(_PALETTE["interiors"])
WHEEL_SYMBOL = dict(_PALETTE["wheels"])

# Region -> color (geographic + destination charts).
REGION_COLOR = dict(_PALETTE["regions"])

# Delivery-estimate certainty: color, marker opacity, and firm->vague order.
TYPE_COLOR = {t: d["color"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_OPACITY = {t: d["opacity"] for t, d in _PALETTE["delivery_types"].items()}
TYPE_ORDER = list(_PALETTE["delivery_type_order"])

# State -> (region, lat, lon). Coords are rough state centroids; BC uses
# metro Vancouver since that is where the reservation-holder is.
STATE_INFO = {
    "AL": ("South", 32.81, -86.79), "AK": ("West", 64.20, -149.49),
    "AR": ("South", 34.97, -92.37), "AZ": ("West", 33.73, -111.43),
    "CA": ("West", 36.78, -119.42), "CO": ("West", 39.06, -105.31),
    "CT": ("Northeast", 41.60, -72.76), "DE": ("South", 39.32, -75.51),
    "FL": ("South", 27.77, -81.69), "GA": ("South", 33.04, -83.64),
    "HI": ("West", 21.09, -157.50), "ID": ("West", 44.24, -114.48),
    "IL": ("Midwest", 40.35, -88.99), "IN": ("Midwest", 39.85, -86.26),
    "IA": ("Midwest", 42.01, -93.21), "KS": ("Midwest", 38.53, -96.73),
    "KY": ("South", 37.67, -84.67), "LA": ("South", 31.17, -91.87),
    "MA": ("Northeast", 42.23, -71.53), "MD": ("South", 39.06, -76.80),
    "ME": ("Northeast", 44.69, -69.38), "MI": ("Midwest", 43.33, -84.54),
    "MN": ("Midwest", 45.69, -93.90), "MO": ("Midwest", 38.46, -92.29),
    "MS": ("South", 32.74, -89.68), "MT": ("West", 46.92, -110.45),
    "NC": ("South", 35.63, -79.81), "ND": ("Midwest", 47.53, -99.78),
    "NE": ("Midwest", 41.13, -98.27), "NH": ("Northeast", 43.45, -71.56),
    "NJ": ("Northeast", 40.30, -74.52), "NM": ("West", 34.84, -106.25),
    "NV": ("West", 38.31, -117.06), "NY": ("Northeast", 42.17, -74.95),
    "OH": ("Midwest", 40.39, -82.76), "OK": ("South", 35.57, -96.93),
    "OR": ("West", 44.57, -122.07), "PA": ("Northeast", 40.59, -77.21),
    "RI": ("Northeast", 41.68, -71.51), "SC": ("South", 33.86, -80.95),
    "SD": ("Midwest", 44.30, -99.44), "TN": ("South", 35.75, -86.69),
    "TX": ("South", 31.05, -97.56), "UT": ("West", 40.15, -111.86),
    "VA": ("South", 37.77, -78.17), "VT": ("Northeast", 44.05, -72.71),
    "WA": ("West", 47.40, -121.49), "WI": ("Midwest", 44.27, -89.62),
    "WV": ("South", 38.49, -80.95), "WY": ("West", 42.76, -107.30),
    "DC": ("South", 38.90, -77.03),
    # Canadian provinces/territories (all under the "Canada" region for the
    # legend; positioned at each unit's approximate geographic centroid, to
    # match the US-state convention).
    "AB": ("Canada", 54.5, -114.4), "BC": ("Canada", 54.5, -125.0),
    "MB": ("Canada", 55.0, -97.0), "NB": ("Canada", 46.5, -66.4),
    "NL": ("Canada", 53.5, -60.0), "NS": ("Canada", 45.0, -63.0),
    "ON": ("Canada", 50.0, -85.3), "PE": ("Canada", 46.4, -63.2),
    "QC": ("Canada", 53.0, -71.5), "SK": ("Canada", 54.5, -106.0),
    "YT": ("Canada", 63.7, -135.5), "NT": ("Canada", 64.8, -119.0),
    "NU": ("Canada", 70.2, -90.7),
}
# Tokens that mean "no date given".
UNKNOWN_TOKENS = {
    "", "0", "n/a", "na", "none", "none given yet", "not given",
    "not provided", "tbd", "unknown", "dont have one", "in pre-production",
    "waiting for coastal cloud release", "not yet", "n/a yet",
}

# Multi-endpoint / ambiguous delivery strings resolved explicitly.
# raw -> (min_iso, max_iso, type)
DELIVERY_OVERRIDES = {
    "July 16-August 16": ("2026-07-16", "2026-08-16", "range"),
    "June 30-July 28": ("2026-06-30", "2026-07-28", "range"),
    "June 29-30": ("2026-06-29", "2026-06-30", "range"),
    "July 11th-17th": ("2026-07-11", "2026-07-17", "range"),
    "August - September": ("2026-08-01", "2026-09-30", "range"),
    "Nov/Dec 2026": ("2026-11-01", "2026-12-31", "range"),
    "7-13-26/8-10-26": ("2026-07-13", "2026-08-10", "range"),
    "End of July": ("2026-07-25", "2026-07-31", "month"),
}

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

CA_PROVINCES = {
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB",
    "new brunswick": "NB", "newfoundland and labrador": "NL",
    "newfoundland": "NL", "labrador": "NL", "nova scotia": "NS",
    "ontario": "ON", "prince edward island": "PE", "quebec": "QC",
    "québec": "QC", "saskatchewan": "SK", "yukon": "YT",
    "northwest territories": "NT", "nunavut": "NU",
}
