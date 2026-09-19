"""Pure parsing and geo-enrichment helpers.

VIN recovery, date normalization (simple dates + noisy free-text delivery
estimates), great-circle distance to the factory, and location->state mapping.
No I/O, no plotting — just transforms over the raw fields.
"""
import calendar
import re
from collections import namedtuple
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from config import (AS_OF, CA_PROVINCES, DELIVERY_OVERRIDES, DELIVERY_YEAR_MAX,
                     DELIVERY_YEAR_MIN, FACTORY, MONTHS, MONTH_MODIFIERS,
                     ORDER_ANCHOR_MIN, STATE_INFO, STATE_REFERENCE,
                     UNKNOWN_SUBSTRINGS, UNKNOWN_TOKENS, VIN_SEQ_MIN,
                     WHEEL_SHORT)


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
            dt = datetime.strptime(s, fmt)
            # A 4-digit year below 100 is a 2-digit year typed into a 4-digit
            # field: "3/7/0024" is 3/7/2024, the R2 reveal date, and 29 rows across
            # the two sheets are written that way. They used to be dropped whole —
            # %Y accepts year 24, then pandas cannot even represent it (its minimum
            # is 1677), and the OutOfBoundsDatetime (a ValueError subclass) fell
            # through to a coerced NaT. Reservations lost their date entirely.
            #
            # Only a year under 100 is adjusted. "3/7/0204" is transposed rather
            # than truncated, so 2024 would be a guess; a 3-digit year is rejected
            # outright instead. That also makes the result version-independent:
            # pandas 1.x cannot represent year 204 and raised (coercing to NaT),
            # while 2.x accepts it happily and would carry a year-204 timestamp
            # downstream — the same 1.x/2.x split the delivery year window exists
            # to close.
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            elif dt.year < 1000:
                return pd.NaT
            return pd.Timestamp(dt)
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
    # Dots join a date as readily as slashes or dashes ("9.12.2026").
    parts = [p for p in re.split(r"[/.-]", s) if p != ""]
    if not parts or not all(p.isdigit() for p in parts):
        return None
    try:
        if len(parts) == 3:
            # ISO first: a 4-digit LEADING part can only be a year, since no month
            # has four digits — so "2026-08-15" is unambiguous and needs no guess.
            # Read as M/D/Y it became date(15, 2026, 8), a ValueError swallowed into
            # "unparseable", so a perfectly good date was dropped from the charts.
            # Only the leading position is special-cased: "15-08-2026" stays a
            # non-US reading this deliberately does not accept (see the module's
            # m/d/y rule), and it has no valid US interpretation either.
            if len(parts[0]) == 4:
                yy, mm, dd = (int(p) for p in parts)
                return ("explicit", date(yy, mm, dd))
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
    """Named-month date -> ('explicit'|'month', date).

    Handles the day on either side of the month ("August 3", "3 Aug", "3rd
    August"), optional ordinal suffixes, dash separators, and 2- or 4-digit years
    ("31 Jul 26", "3 Aug 2026"). The month is spelled out, so there's no US-vs-non-
    US day/month ambiguity here — that only affects all-numeric dates elsewhere.
    """
    low = s.lower().replace(",", " ")
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", low)
    if not m:
        return None
    mn = MONTHS[m.group(1)]
    before, after = low[:m.start()], low[m.end():]

    # A 4-digit 20xx year anywhere wins and is stripped so it can't be read as a day.
    ym = re.search(r"\b(20\d{2})\b", low)
    year = int(ym.group(1)) if ym else 2026
    before = re.sub(r"\b20\d{2}\b", " ", before)
    after = re.sub(r"\b20\d{2}\b", " ", after)

    # Day: prefer a 1-2 digit number immediately BEFORE the month ("3 Aug",
    # "31 Jul 26"); else the first such number AFTER it ("Aug 3", "Aug 08").
    db = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-]*$", before)
    if db:
        day = int(db.group(1))
        # With a leading day, a trailing 2-digit number is the year, not the day.
        ty = re.search(r"^[\s\-]*(\d{2})\b", after)
        if ty and not ym:
            year = 2000 + int(ty.group(1))
    else:
        da = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", after)
        day = int(da.group(1)) if da else None

    if day is not None:
        try:
            return ("explicit", date(year, mn, day))
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


def _parse_week_of(s):
    """"Week of <date>" -> the calendar week (Mon-Sun) containing that date, as
    (start, end) dates, or None. The date part reuses the numeric / month-name
    single-date parsers, so "Week of 8/10" and "Week of August 3rd" both resolve;
    the given day is snapped back to its Monday and forward to that Sunday."""
    m = re.search(r"week\s+(?:of|beginning|starting|commencing)\s+(.+)$", s.lower())
    if not m:
        return None
    rest = m.group(1).strip()
    res = _parse_numeric(_fix_numeric_typos(rest)) or _parse_monthname(rest)
    if not res or res[0] != "explicit":   # need a specific day to locate the week
        return None
    d = res[1]
    monday = d - timedelta(days=d.weekday())   # weekday(): Mon=0 .. Sun=6
    return (monday, monday + timedelta(days=6))


def _anchor(order_date):
    """Anchor for relative windows: the order date, else the as-of date."""
    if pd.isna(order_date) or order_date < ORDER_ANCHOR_MIN:
        return AS_OF, True
    return order_date, False


def _plausible(*dates):
    """True if every date falls in the plausible delivery-year window.

    A typo can parse cleanly but land centuries away — "8/1326" (meant 8/13/26)
    reads as month 8 of year 1326. pandas 1.x raises OutOfBoundsDatetime on such
    a Timestamp (crashing the run) while pandas 2.x accepts it as a second-unit
    Timestamp and silently publishes the bad date, so guard here rather than
    relying on Timestamp construction to fail. Out-of-window values fall through
    to "unknown" and surface in the data-quality panel as unparseable.
    """
    return all(d is not None and DELIVERY_YEAR_MIN <= d.year <= DELIVERY_YEAR_MAX
               for d in dates)


# --- Delivery-estimate rules -------------------------------------------------
# parse_delivery is an ORDERED TABLE of small rules rather than one long chain of
# branches. Each rule looks at the text and returns one of:
#
#   None     no match — try the next rule
#   _VETO    the text says "no date given"; stop and report unknown
#   _Weeks   a RELATIVE window, lo..hi weeks after the anchor
#   _Span    an absolute min..max interval, with the type to report
#   _Fixed   like _Span, but exempt from the plausible-year check (see below)
#   _Point   a single date, "explicit" or "month" (a month expands to its span)
#
# The driver applies everything the rules share — the plausible-year guard, the
# month-span expansion, the est midpoint, and the anchor arithmetic — so a rule
# only has to recognise its own shape.
#
# A rule that MATCHES but whose dates are implausible falls through to the next
# rule rather than ending the search: "8/1326" is rejected as a numeric date and
# then gets its chance as a month name. Only running off the end means unknown.
#
# ORDER IS THE INTERFACE, and two positions are load-bearing:
#   * the unknown vocabulary runs FIRST, because it has to veto text that contains
#     a date it must not be read from — "Invited to Order on 8/11/2026" is an order
#     date, and the prose rule would otherwise harvest it;
#   * the prose rule runs LAST, so it only ever sees text that every structured
#     rule has already declined, and can only rescue what would be unparseable.
# test_delivery_rule_order_is_load_bearing pins both.

_VETO = object()
_Weeks = namedtuple("_Weeks", "lo hi")
_Span = namedtuple("_Span", "min max type")
_Fixed = namedtuple("_Fixed", "min max type")
_Point = namedtuple("_Point", "type date")

# Relative week windows. The range form is tried before the single form, so
# "2-4 weeks" is a span rather than "4 weeks" alone.
_WEEK_RANGE_RE = re.compile(r"(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*(?:week|wk)")
_WEEK_ONE_RE = re.compile(r"(?<!\d)(\d+)\s*(?:week|wk)")
# Numeric date range: "7/30-7/31", "7/30 - 8/2", same-month "7/30-31", or full
# dates with years "7/28/2026 - 8/3/2026".
_NUM_RANGE_RE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(?:-|–|—|to)\s*"
                           r"(\d{1,2})(?:/(\d{1,2}))?(?:/(\d{2,4}))?")
# A STANDALONE numeric date for the prose rule. The lookarounds matter: without
# them this reaches inside a malformed run of digits and "rescues" it by
# truncation — "8/1326" (a typo for 8/13/26) contains a leading "8/13", and
# reporting that as a confident 13 August is the guess the year window refuses.
_LOOSE_DATE_RE = re.compile(r"(?<![\d/.-])\d{1,4}[/.-]\d{1,2}(?:[/.-]\d{2,4})?"
                            r"(?![\d/.-])")


def _rule_unknown(raw, low):
    """Vocabulary that means "no date given" — see delivery.yaml."""
    if low in UNKNOWN_TOKENS or any(s in low for s in UNKNOWN_SUBSTRINGS):
        return _VETO
    return None


def _rule_override(raw, low):
    """A shape pinned by hand in delivery.yaml, matched exactly.

    _Fixed, not _Span: this is an explicit human decision, so the year window
    doesn't get to discard it. A typo'd override should surface as a wrong date to
    be corrected, not vanish into the unparseable bucket where nobody looks.
    """
    if raw in DELIVERY_OVERRIDES:
        mn, mx, typ = DELIVERY_OVERRIDES[raw]
        return _Fixed(pd.Timestamp(mn), pd.Timestamp(mx), typ)
    return None


def _rule_week_range(raw, low):
    """"2-4 weeks", "2 to 6 wk" — lo..hi weeks from the anchor."""
    m = _WEEK_RANGE_RE.search(low)
    return _Weeks(int(m.group(1)), int(m.group(2))) if m else None


def _rule_week_single(raw, low):
    """"2 weeks", "1 wk" — a single point, not a span."""
    m = _WEEK_ONE_RE.search(low)
    return _Weeks(int(m.group(1)), int(m.group(1))) if m else None


def _rule_week_of(raw, low):
    """"Week of 8/11" — the calendar week (Mon-Sun) containing that date."""
    wk = _parse_week_of(raw)
    return _Span(wk[0], wk[1], "range") if wk else None


def _rule_numeric_range(raw, low):
    """Numeric date range. Years are optional; a missing year defaults to 2026
    (matching the single M/D case), and a year on one side applies to both."""
    m = _NUM_RANGE_RE.search(low)
    if not m:
        return None
    m1, d1, y1, a, b, y2 = m.groups()
    m1, d1 = int(m1), int(d1)
    m2, d2 = (int(a), int(b)) if b else (m1, int(a))   # M/D-M/D vs M/D-D
    yr1 = int(y1) if y1 else (int(y2) if y2 else 2026)
    yr2 = int(y2) if y2 else yr1
    yr1 += 2000 if yr1 < 100 else 0
    yr2 += 2000 if yr2 < 100 else 0
    try:
        dmin, dmax = date(yr1, m1, d1), date(yr2, m2, d2)
    except ValueError:
        return None
    return _Span(dmin, dmax, "range") if dmax >= dmin else None


def _rule_monthname_range(raw, low):
    """"July 16-August 16", "June 29-30", "August - September", "Nov/Dec 2026"."""
    mr = _parse_monthname_range(raw)
    return _Span(mr[0], mr[1], "range") if mr else None


def _rule_month_modifier(raw, low):
    """"end of July", "early August", "mid-September" — a bounded ~week window,
    so more precise than a bare month and typed "range" rather than "month"."""
    mm = _parse_month_modifier(raw)
    return _Span(mm[0], mm[1], "range") if mm else None


def _rule_numeric_date(raw, low):
    """A single numeric date, after repairing concatenated typos."""
    res = _parse_numeric(_fix_numeric_typos(raw))
    return _Point(res[0], res[1]) if res else None


def _rule_monthname_date(raw, low):
    """A single named-month date ("Aug 3, 2026"), or a bare month ("August 2026")."""
    res = _parse_monthname(raw)
    return _Point(res[0], res[1]) if res else None


def _rule_prose_date(raw, low):
    """A date wrapped in a sentence ("Delivery Scheduled for 9/27/2026").

    ONLY when the text holds exactly one date. Two means the sentence is doing
    something this can't read — "7/28 pushed back 8/4/26" turns on which one won,
    and "moved up to 8/1 from 8/15" reverses the answer — so those stay unparseable
    for overrides.yaml to settle rather than being guessed at.
    """
    found = _LOOSE_DATE_RE.findall(raw)
    if len(found) != 1:
        return None
    res = _parse_numeric(_fix_numeric_typos(found[0]))
    return _Point(res[0], res[1]) if res else None


# The table. Names are for the report and the ordering test; the sequence is the
# behaviour. Weakest and most permissive last.
_DELIVERY_RULES = (
    ("unknown vocabulary", _rule_unknown),
    ("explicit override", _rule_override),
    ("relative week range", _rule_week_range),
    ("relative single week", _rule_week_single),
    ("week of <date>", _rule_week_of),
    ("numeric range", _rule_numeric_range),
    ("month-name range", _rule_monthname_range),
    ("within-month modifier", _rule_month_modifier),
    ("numeric date", _rule_numeric_date),
    ("month-name date", _rule_monthname_date),
    ("date in prose", _rule_prose_date),
)


def parse_delivery(raw, order_date):
    """Normalize a delivery estimate.

    Returns dict(est, min, max, type, anchor, anchor_fallback). Relative
    week-windows are measured from `anchor` — the customer's R2 order date, or
    the as-of date when that is missing/invalid (anchor_fallback=True). Absolute
    types (explicit / range / month) leave anchor as NaT.

    The shapes it understands, and the order they are tried in, are _DELIVERY_RULES
    above; this is just the driver.
    """
    raw = (raw or "").strip()
    low = raw.lower()
    out = {"est": pd.NaT, "min": pd.NaT, "max": pd.NaT, "type": "unknown",
           "anchor": pd.NaT, "anchor_fallback": False}

    for _name, rule in _DELIVERY_RULES:
        res = rule(raw, low)
        if res is None:
            continue
        if res is _VETO:
            return out

        if isinstance(res, _Weeks):
            anchor, fallback = _anchor(order_date)
            out.update(min=anchor + pd.Timedelta(weeks=res.lo),
                       max=anchor + pd.Timedelta(weeks=res.hi),
                       est=anchor + pd.Timedelta(weeks=(res.lo + res.hi) / 2.0),
                       type="window", anchor=anchor, anchor_fallback=fallback)
            return out

        if isinstance(res, _Point):
            if not _plausible(res.date):
                continue                      # implausible -> let the next rule try
            ts = pd.Timestamp(res.date)
            if res.type == "month":
                # A bare month is inherently a whole-month window — span it so the
                # uncertainty shows on the charts (est stays mid-month).
                out.update(est=ts, min=ts.replace(day=1),
                           max=ts + pd.offsets.MonthEnd(0), type="month")
            else:
                out.update(est=ts, min=ts, max=ts, type=res.type)
            return out

        # _Span (guarded) or _Fixed (trusted, from delivery.yaml).
        if isinstance(res, _Span) and not _plausible(res.min, res.max):
            continue
        dmin, dmax = pd.Timestamp(res.min), pd.Timestamp(res.max)
        out.update(min=dmin, max=dmax, est=dmin + (dmax - dmin) / 2, type=res.type)
        return out

    return out


def reconcile_r1_owner(owner, model):
    """Reconcile the R1-owner gate against its conditional model follow-up.

    "Are you a current R1 owner?" is a Yes/No gate; "which model?" is only meant
    for owners. When the gate says No but a specific model is named, trust the
    model: naming an R1S/R1T is concrete information a non-owner has no reason to
    supply, while the gate is one click and easy to get wrong. Both cases seen so
    far were confirmed owners (see overrides.yaml), so this is also what the
    evidence supports.

    The other conditional follow-up — "will you keep your R1?" — is deliberately
    NOT treated as an ownership signal: 10 non-owners have answered it, apparently
    reading it as "will you have an R1 too?", so it carries no weight.

    The coercion is reported, not silent, and a confirmed case should get an
    overrides.yaml entry rather than relying on it. Returns
    (effective_owner, issue|None).
    """
    o, m = str(owner or "").strip(), str(model or "").strip()
    if o.lower() == "no" and m:
        return "Yes", ("r1_owner 'No' but model %r named → Yes "
                       "(naming a model implies ownership)" % m)
    return o, None


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
    """Add state/region/lat/lon plus the per-state reference columns from
    `loc_raw`, in place. Elevation, temperature and percent-urban are
    published state averages (see geo.yaml), NaN wherever the state isn't
    covered — a missing value has to stay missing so the charts can show it as
    its own bar instead of implying a figure nobody published."""
    df["state"] = df["loc_raw"].apply(loc_to_state)
    df["region"] = df["state"].map(lambda s: STATE_INFO.get(s, ("Unknown",))[0])
    df["lat"] = df["state"].map(lambda s: STATE_INFO.get(s, (None, np.nan, np.nan))[1])
    df["lon"] = df["state"].map(lambda s: STATE_INFO.get(s, (None, np.nan, np.nan))[2])
    _nan3 = (np.nan, np.nan, np.nan)
    for i, col in enumerate(("elev_ft", "temp_f", "urban_pct")):
        df[col] = df["state"].map(lambda s, i=i: STATE_REFERENCE.get(s, _nan3)[i])
    return df


# Sheet wheel values are hand-typed, so match on a normalized key: the form uses
# curly quotes but a hand edit may not, and spacing/case drift either way.
_WHEEL_BY_KEY = {}


def _wheel_key(text):
    """Normalization key for a wheel value: straight quotes, single spaces, lower."""
    s = str(text or "").replace("”", '"').replace("“", '"').replace("’", "'")
    return " ".join(s.split()).lower()


for _raw, _short in WHEEL_SHORT.items():
    _WHEEL_BY_KEY[_wheel_key(_raw)] = _short


def wheel_label(raw):
    """Sheet wheel value -> display label, by identity rather than by size.

    Two of the four R2 wheels are 20", so a size test can't tell them apart — the
    old "contains 21" rule silently labelled every non-21" wheel as the 20"
    All-Terrain, which would have mislabelled Premium and Standard orders the
    moment those trims shipped. An unrecognized value keeps its own text so it
    shows up as its own category instead of being folded into a real wheel;
    pricing already flags it as not offered on the order's trim.
    """
    text = str(raw or "").strip()
    return _WHEEL_BY_KEY.get(_wheel_key(text), text)
