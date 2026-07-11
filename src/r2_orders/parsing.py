"""Pure parsing and geo-enrichment helpers.

VIN recovery, date normalization (simple dates + noisy free-text delivery
estimates), great-circle distance to the factory, and location->state mapping.
No I/O, no plotting — just transforms over the raw fields.
"""
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

from .config import (AS_OF, CA_PROVINCES, DELIVERY_OVERRIDES, FACTORY, MONTHS,
                     ORDER_ANCHOR_MIN, STATE_INFO, UNKNOWN_SUBSTRINGS,
                     UNKNOWN_TOKENS, VIN_SEQ_MIN)


def clean_vin(token):
    """Return (seq:int|None, present:bool, obfuscated:bool).

    VIN Assigned holds the last 3-4 digits of the VIN (production sequence
    number, ~700-2900). Some are obfuscated with leading X's (X1435, XX816).
    Fully redacted values like XXXX0 are unrecoverable.
    """
    token = (token or "").strip()
    if token == "":
        return (None, False, False)
    had_x = "x" in token.lower()
    digits = re.sub(r"\D", "", token)
    if digits == "":
        return (None, False, had_x)
    val = int(digits)
    # Implausible as a sequence number -> treat as unusable (e.g. XXXX0 -> 0).
    if val < VIN_SEQ_MIN:
        return (None, False, had_x)
    return (val, True, had_x)


def parse_simple_date(s):
    """Parse M/D/YYYY-style reservation & order dates. Return Timestamp|NaT."""
    s = (s or "").strip()
    if s == "":
        return pd.NaT
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return pd.to_datetime(s, errors="coerce")


def _fix_numeric_typos(s):
    """Repair concatenated numeric dates: 6302026, 7/72026, 07/282026."""
    s = s.strip()
    if re.fullmatch(r"\d{7}", s):        # M DD YYYY  -> 6302026 => 6/30/2026
        return "%s/%s/%s" % (s[0], s[1:3], s[3:])
    if re.fullmatch(r"\d{8}", s):        # MM DD YYYY
        return "%s/%s/%s" % (s[0:2], s[2:4], s[4:])
    m = re.fullmatch(r"(\d{1,2})/(\d)(\d{4})", s)     # 7/72026 => 7/7/2026
    if m:
        return "%s/%s/%s" % m.groups()
    m = re.fullmatch(r"(\d{1,2})/(\d{2})(\d{4})", s)  # 07/282026 => 07/28/2026
    if m:
        return "%s/%s/%s" % m.groups()
    return s


def _parse_numeric(s):
    """Numeric / ddMMMyyyy date. Return ('explicit'|'month', date) or None."""
    s = s.strip()
    m = re.fullmatch(r"(\d{1,2})([A-Za-z]{3,})(\d{4})", s)   # 23JUN2026
    if m:
        mn = MONTHS.get(m.group(2)[:3].lower())
        if mn:
            return ("explicit", date(int(m.group(3)), mn, int(m.group(1))))
        return None
    parts = [p for p in re.split(r"[/-]", s) if p != ""]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    try:
        if len(parts) == 3:
            mm, dd, yy = (int(p) for p in parts)
            if yy < 100:
                yy += 2000
            return ("explicit", date(yy, mm, dd))
        if len(parts) == 2:
            a, b = parts
            if len(b) == 4:                    # 08/2026 -> month/year
                return ("month", date(int(b), int(a), 15))
            return ("explicit", date(2026, int(a), int(b)))  # M/D, assume 2026
    except ValueError:
        return None
    return None


def _parse_monthname(s):
    """Month-name date, optional day/year. Return ('explicit'|'month', date)."""
    low = s.lower().replace(",", " ")
    year_m = re.search(r"(20\d{2})", low)
    year = int(year_m.group(1)) if year_m else 2026
    low = re.sub(r"20\d{2}", " ", low)  # drop year so it isn't read as a day
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", low)
    if not m:
        return None
    mn = MONTHS[m.group(1)]
    day_m = re.search(r"\b(\d{1,2})\b", low[m.end():])
    if day_m:
        try:
            return ("explicit", date(year, mn, int(day_m.group(1))))
        except ValueError:
            pass
    return ("month", date(year, mn, 15))


def _anchor(order_date):
    """Anchor for relative windows: the order date, else the as-of date."""
    if pd.isna(order_date) or order_date < ORDER_ANCHOR_MIN:
        return AS_OF, True
    return order_date, False


def parse_delivery(raw, order_date):
    """Normalize a delivery estimate.

    Returns dict(est, min, max, type, anchor_fallback). Relative week-windows
    are measured from the customer's R2 order date (per requirement).
    """
    raw = (raw or "").strip()
    low = raw.lower()
    out = {"est": pd.NaT, "min": pd.NaT, "max": pd.NaT, "type": "unknown",
           "anchor_fallback": False}
    if low in UNKNOWN_TOKENS or any(s in low for s in UNKNOWN_SUBSTRINGS):
        return out

    if raw in DELIVERY_OVERRIDES:
        mn, mx, typ = DELIVERY_OVERRIDES[raw]
        dmin, dmax = pd.Timestamp(mn), pd.Timestamp(mx)
        out.update(est=dmin + (dmax - dmin) / 2, min=dmin, max=dmax, type=typ)
        return out

    # Relative week windows (anchored to order date).
    win = re.search(r"(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*(?:week|wk)", low)
    single = re.search(r"(?<!\d)(\d+)\s*(?:week|wk)", low)
    if win:
        lo, hi = int(win.group(1)), int(win.group(2))
        anchor, fb = _anchor(order_date)
        out.update(min=anchor + pd.Timedelta(weeks=lo),
                   max=anchor + pd.Timedelta(weeks=hi),
                   est=anchor + pd.Timedelta(weeks=(lo + hi) / 2.0),
                   type="window", anchor_fallback=fb)
        return out
    if ("week" in low or "wk" in low) and single:
        w = int(single.group(1))
        anchor, fb = _anchor(order_date)
        est = anchor + pd.Timedelta(weeks=w)
        out.update(est=est, min=est, max=est, type="window", anchor_fallback=fb)
        return out

    # Single explicit / month date.
    for parser, arg in ((_parse_numeric, _fix_numeric_typos(raw)),
                        (_parse_monthname, raw)):
        res = parser(arg)
        if res:
            typ, dt = res
            ts = pd.Timestamp(dt)
            out.update(est=ts, min=ts, max=ts, type=typ)
            return out
    return out


def haversine_mi(lat, lon, ref=FACTORY):
    """Great-circle miles from (lat,lon) to the factory."""
    if lat is None or (isinstance(lat, float) and np.isnan(lat)):
        return np.nan
    r = 3958.8
    la1, lo1, la2, lo2 = map(np.radians, [ref[0], ref[1], lat, lon])
    d = (np.sin((la2 - la1) / 2) ** 2
         + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    return 2 * r * np.arcsin(np.sqrt(d))


def loc_to_state(loc):
    """Normalize a free-text Location to a 2-letter state/province key. Handles
    the sheet conventions 'Canada - <province>' (mapped to that province) and
    'DC - District of Columbia' -> DC; otherwise takes the leading 2 letters."""
    loc = (loc or "").strip()
    if loc.startswith("Canada"):
        _, _, prov = loc.partition("-")
        return CA_PROVINCES.get(prov.strip().lower(), "BC")
    if loc.startswith("DC"):
        return "DC"
    return loc.upper()[:2]


def geo_enrich(df):
    """Add state/region/lat/lon columns from a `loc_raw` column, in place."""
    df["state"] = df["loc_raw"].apply(loc_to_state)
    df["region"] = df["state"].map(lambda s: STATE_INFO.get(s, ("Unknown",))[0])
    df["lat"] = df["state"].map(lambda s: STATE_INFO.get(s, (None, np.nan, np.nan))[1])
    df["lon"] = df["state"].map(lambda s: STATE_INFO.get(s, (None, np.nan, np.nan))[2])
    return df
