"""Pure parsing and geo-enrichment helpers.

VIN recovery, date normalization (simple dates + noisy free-text delivery
estimates), great-circle distance to the factory, and location->state mapping.
No I/O, no plotting — just transforms over the raw fields.
"""
import calendar
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

from config import (AS_OF, CA_PROVINCES, DELIVERY_OVERRIDES, FACTORY, MONTHS,
                     MONTH_MODIFIERS, ORDER_ANCHOR_MIN, STATE_INFO,
                     UNKNOWN_SUBSTRINGS, UNKNOWN_TOKENS, VIN_SEQ_MIN)


def clean_vin(token):
    """Return (seq:int|None, present:bool, obfuscated:bool).

    VIN Assigned holds the last 3-4 digits of the VIN (production sequence
    number, ~700-2900). LEADING X's redact high-order digits, so the remaining
    digits are the full sequence and recover cleanly (X1435 -> 1435, XX816 ->
    816). A TRAILING X redacts the low-order digit(s), so the value is unknown
    within a factor of ten (218X is 2180-2189, not 218) — rather than understate
    it, treat it as unrecoverable and drop it. Fully redacted values like XXXX0
    are unrecoverable too.
    """
    token = (token or "").strip()
    if token == "":
        return (None, False, False)
    had_x = "x" in token.lower()
    # Trailing X redacts the low-order digit(s): magnitude unknown -> drop.
    if token.lower().endswith("x"):
        return (None, False, True)
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
    # Accept an optional ordinal suffix so "July 18th" -> explicit, not a bare month.
    day_m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", low[m.end():])
    if day_m:
        try:
            return ("explicit", date(year, mn, int(day_m.group(1))))
        except ValueError:
            pass
    return ("month", date(year, mn, 15))


# Month-name alternation (captures the 3-letter key; trailing letters are the
# rest of the word). Shared by the range/modifier parsers below.
_MONTHS_ALT = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
# Two named-month (or same-month day) endpoints joined by a range separator.
# Groups: (month1, day1, month2, day2); day1/day2 and month2 are optional.
_MONTHRANGE_RE = re.compile(
    _MONTHS_ALT + r"\.?\s*(?:(\d{1,2})(?:st|nd|rd|th)?)?\s*"
    r"(?:-|–|—|/|to|thru|through|&|and)\s*"
    r"(?:" + _MONTHS_ALT + r"\.?\s*)?(?:(\d{1,2})(?:st|nd|rd|th)?)?")


def _parse_monthname_range(s):
    """Named-month range -> (start, end) dates, or None.

    Covers two named-month endpoints ("July 16-August 16", "June 30-July 28"), a
    same-month day range ("June 29-30", "July 11th-17th"), whole-month spans
    ("August - September", "Nov/Dec 2026"), and Dec->Jan year rollover. A missing
    start day is the 1st; a missing end day is that month's last day.
    """
    low = s.lower().replace(",", " ")
    year_m = re.search(r"(20\d{2})", low)
    year = int(year_m.group(1)) if year_m else 2026
    low = re.sub(r"20\d{2}", " ", low)  # drop year so it isn't read as a day
    m = _MONTHRANGE_RE.search(low)
    if not m:
        return None
    mon1, d1, mon2, d2 = m.groups()
    if not (mon2 or d2):            # need a real second endpoint to be a range
        return None
    mo1 = MONTHS[mon1]
    mo2 = MONTHS[mon2] if mon2 else mo1
    y2 = year + 1 if mo2 < mo1 else year   # Dec -> Jan rolls into the next year
    d1 = int(d1) if d1 else 1
    d2 = int(d2) if d2 else calendar.monthrange(y2, mo2)[1]
    try:
        start, end = date(year, mo1, d1), date(y2, mo2, d2)
    except ValueError:
        return None
    return (start, end) if end >= start else None


# A within-month modifier bound to the month it qualifies ("end of July",
# "mid-September", "first week August"). Built from the MONTH_MODIFIERS keys,
# longest first so "middle of" wins over "mid". Group 1 = keyword, 2 = month.
_MODIFIER_RE = (re.compile(
    r"(" + "|".join(re.escape(k) for k in
                    sorted(MONTH_MODIFIERS, key=len, reverse=True)) + r")"
    r"[\s\-]*" + _MONTHS_ALT) if MONTH_MODIFIERS else None)


def _parse_month_modifier(s):
    """Within-month modifier -> (start, end) dates, or None. Maps a fuzzy phrase
    ("end of July", "early August", "mid-September") to a ~week window inside the
    month it is attached to, via MONTH_MODIFIERS (keyword -> [start_day, end_day],
    -1 = month end). The keyword must sit immediately before its month, so
    "end of July or early August" resolves as end-of-July, not early-July."""
    if _MODIFIER_RE is None:
        return None
    low = s.lower().replace(",", " ")
    year_m = re.search(r"(20\d{2})", low)
    year = int(year_m.group(1)) if year_m else 2026
    low = re.sub(r"20\d{2}", " ", low)
    m = _MODIFIER_RE.search(low)
    if not m:
        return None
    d1, d2 = MONTH_MODIFIERS[m.group(1)]
    mo = MONTHS[m.group(2)]
    last = calendar.monthrange(year, mo)[1]
    s1 = last if d1 == -1 else min(d1, last)
    s2 = last if d2 == -1 else min(d2, last)
    s1, s2 = min(s1, s2), max(s1, s2)
    try:
        return (date(year, mo, s1), date(year, mo, s2))
    except ValueError:
        return None


def _anchor(order_date):
    """Anchor for relative windows: the order date, else the as-of date."""
    if pd.isna(order_date) or order_date < ORDER_ANCHOR_MIN:
        return AS_OF, True
    return order_date, False


def parse_delivery(raw, order_date):
    """Normalize a delivery estimate.

    Returns dict(est, min, max, type, anchor, anchor_fallback). Relative
    week-windows are measured from `anchor` — the customer's R2 order date, or
    the as-of date when that is missing/invalid (anchor_fallback=True). Absolute
    types (explicit / range / month) leave anchor as NaT.
    """
    raw = (raw or "").strip()
    low = raw.lower()
    out = {"est": pd.NaT, "min": pd.NaT, "max": pd.NaT, "type": "unknown",
           "anchor": pd.NaT, "anchor_fallback": False}
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
                   type="window", anchor=anchor, anchor_fallback=fb)
        return out
    if ("week" in low or "wk" in low) and single:
        w = int(single.group(1))
        anchor, fb = _anchor(order_date)
        est = anchor + pd.Timedelta(weeks=w)
        out.update(est=est, min=est, max=est, type="window",
                   anchor=anchor, anchor_fallback=fb)
        return out

    # Numeric date ranges: "7/30-7/31", "7/30 - 8/2", same-month "7/30-31", or
    # full dates with years "7/28/2026 - 8/3/2026". Years are optional; a missing
    # year defaults to 2026 (matching the single M/D case below), and a year given
    # on only one side applies to both.
    md = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(?:-|–|—|to)\s*"
                   r"(\d{1,2})(?:/(\d{1,2}))?(?:/(\d{2,4}))?", low)
    if md:
        m1, d1, y1, a, b, y2 = md.groups()
        m1, d1 = int(m1), int(d1)
        m2, d2 = (int(a), int(b)) if b else (m1, int(a))  # M/D-M/D vs M/D-D
        yr1 = int(y1) if y1 else (int(y2) if y2 else 2026)
        yr2 = int(y2) if y2 else yr1
        yr1 += 2000 if yr1 < 100 else 0
        yr2 += 2000 if yr2 < 100 else 0
        try:
            dmin, dmax = (pd.Timestamp(date(yr1, m1, d1)),
                          pd.Timestamp(date(yr2, m2, d2)))
        except ValueError:
            dmin = dmax = None
        if dmin is not None and dmax >= dmin:
            out.update(min=dmin, max=dmax, est=dmin + (dmax - dmin) / 2,
                       type="range")
            return out

    # Named-month ranges: "July 16-August 16", "June 29-30", "August - September",
    # "Nov/Dec 2026" — two named-month (or same-month day) endpoints.
    mr = _parse_monthname_range(raw)
    if mr:
        dmin, dmax = pd.Timestamp(mr[0]), pd.Timestamp(mr[1])
        out.update(min=dmin, max=dmax, est=dmin + (dmax - dmin) / 2, type="range")
        return out

    # Within-month modifiers: "end of July", "early August", "mid-September" — a
    # bounded ~week window (more precise than a bare month, hence type "range").
    mm = _parse_month_modifier(raw)
    if mm:
        dmin, dmax = pd.Timestamp(mm[0]), pd.Timestamp(mm[1])
        out.update(min=dmin, max=dmax, est=dmin + (dmax - dmin) / 2, type="range")
        return out

    # Single explicit / month date.
    for parser, arg in ((_parse_numeric, _fix_numeric_typos(raw)),
                        (_parse_monthname, raw)):
        res = parser(arg)
        if res:
            typ, dt = res
            ts = pd.Timestamp(dt)
            if typ == "month":
                # A bare month is inherently a whole-month window — span it so
                # the uncertainty shows on the charts (est stays mid-month).
                out.update(est=ts, min=ts.replace(day=1),
                           max=ts + pd.offsets.MonthEnd(0), type=typ)
            else:
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
