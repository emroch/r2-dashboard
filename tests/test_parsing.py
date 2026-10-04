"""Unit tests for ingest.parsing.

Runs under pytest, but also standalone without it:

    python tests/test_parsing.py

The standalone runner discovers every test_* function, executes it, and prints
PASS/FAIL per test plus a summary (exit code 1 if anything fails).
"""
import csv
import io
import os
import re
import sys
from datetime import date

import numpy as np
import pandas as pd

# Self-path: put the repo's src/ dir on sys.path so the source modules import
# whether run via pytest or directly.
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from ingest.parsing import (
    clean_vin, haversine_mi, loc_to_state, parse_delivery,
    _fix_numeric_typos, _parse_monthname)
from config import FACTORY


def test_clean_vin_obfuscated_recoverable():
    assert clean_vin("X1435") == (1435, True, True)


def test_clean_vin_fully_redacted():
    assert clean_vin("XXXX0") == (None, False, True)


def test_clean_vin_empty():
    assert clean_vin("") == (None, False, False)


def test_clean_vin_below_threshold():
    # "50" has no X and is < 100, so it is unusable and not obfuscated.
    assert clean_vin("50") == (None, False, False)


def test_clean_vin_trailing_x_dropped():
    # A trailing X redacts the low-order digit(s), so the magnitude is unknown
    # (218X is 2180-2189) — dropped, not understated to 218. Leading X still
    # recovers the full sequence.
    assert clean_vin("218X") == (None, False, True)
    assert clean_vin("226X") == (None, False, True)
    assert clean_vin("00426X") == (None, False, True)
    assert clean_vin("15XX") == (None, False, True)
    assert clean_vin("XX816") == (816, True, True)


def test_fix_numeric_typos_concatenated():
    assert _fix_numeric_typos("6302026") == "6/30/2026"


def test_parse_monthname_month_only_uses_day_15():
    # Regression guard: month-name with a year (no explicit day) must resolve to
    # the 15th of the month, NOT day 20 (i.e. the year must not be read as a day).
    assert _parse_monthname("August 2026") == ("month", date(2026, 8, 15))


def test_loc_to_state_canada_ontario():
    assert loc_to_state("Canada - Ontario") == "ON"


def test_loc_to_state_canada_quebec():
    assert loc_to_state("Canada - Quebec") == "QC"


def test_loc_to_state_dc():
    assert loc_to_state("DC - District of Columbia") == "DC"


def test_loc_to_state_plain_state():
    assert loc_to_state("CA") == "CA"


def test_haversine_factory_to_itself_zero():
    d = haversine_mi(FACTORY[0], FACTORY[1])
    assert abs(d) < 1e-6


def test_haversine_ca_to_factory_hundreds_of_miles():
    # California centroid to the Normal, IL plant is well over a few hundred miles.
    d = haversine_mi(36.78, -119.42)
    assert d > 300


def test_parse_delivery_numeric_range():
    # "M/D-M/D" ranges (e.g. "7/30-7/31") parse to a range spanning both dates.
    out = parse_delivery("7/30-7/31", pd.Timestamp("2026-06-15"))
    assert out["type"] == "range"
    assert out["min"] == pd.Timestamp("2026-07-30")
    assert out["max"] == pd.Timestamp("2026-07-31")


def test_parse_delivery_full_date_range_with_years():
    # Full "M/D/YYYY - M/D/YYYY" ranges (regression: huebetcha's
    # "7/28/2026 - 8/3/2026" used to fall through to "unknown" because the
    # 4-digit years broke the M/D range regex).
    out = parse_delivery("7/28/2026 - 8/3/2026", pd.Timestamp("2026-07-14"))
    assert out["type"] == "range"
    assert out["min"] == pd.Timestamp("2026-07-28")
    assert out["max"] == pd.Timestamp("2026-08-03")
    # A year on only one side still applies to both.
    one = parse_delivery("7/28 - 8/3/2026", pd.Timestamp("2026-07-14"))
    assert one["type"] == "range" and one["min"] == pd.Timestamp("2026-07-28")


def test_parse_delivery_monthname_range():
    # Named-month ranges span both endpoints; whole-month spans fill to month end.
    cases = [
        ("July 16-August 16", "2026-07-16", "2026-08-16"),
        ("June 30-July 28",   "2026-06-30", "2026-07-28"),
        ("June 29-30",        "2026-06-29", "2026-06-30"),  # same-month day range
        ("July 11th-17th",    "2026-07-11", "2026-07-17"),  # ordinals
        ("August - September", "2026-08-01", "2026-09-30"),  # whole-month span
        ("Nov/Dec 2026",      "2026-11-01", "2026-12-31"),  # slash + trailing year
    ]
    for s, mn, mx in cases:
        out = parse_delivery(s, pd.NaT)
        assert out["type"] == "range", s
        assert out["min"] == pd.Timestamp(mn), s
        assert out["max"] == pd.Timestamp(mx), s
    # A single month name is NOT a range — it stays a whole-month estimate.
    assert parse_delivery("August 2026", pd.NaT)["type"] == "month"


def test_parse_delivery_month_modifier():
    # Within-month phrases resolve to a bounded ~week window (type "range").
    end = parse_delivery("End of July", pd.NaT)
    assert end["type"] == "range"
    assert end["min"] == pd.Timestamp("2026-07-25")
    assert end["max"] == pd.Timestamp("2026-07-31")
    early = parse_delivery("early August 2026", pd.NaT)
    assert early["min"] == pd.Timestamp("2026-08-01")
    assert early["max"] == pd.Timestamp("2026-08-07")
    mid = parse_delivery("mid-September", pd.NaT)
    assert mid["min"] == pd.Timestamp("2026-09-12")
    assert mid["max"] == pd.Timestamp("2026-09-18")
    week = parse_delivery("first week August 2026", pd.NaT)
    assert week["min"] == pd.Timestamp("2026-08-01")
    assert week["max"] == pd.Timestamp("2026-08-07")
    # A modifier binds to its ADJACENT month: "end of July or early August" is
    # end-of-July (the leading phrase), not early-July from mismatching "early".
    both = parse_delivery("end of July or early August", pd.NaT)
    assert both["min"] == pd.Timestamp("2026-07-25")
    assert both["max"] == pd.Timestamp("2026-07-31")


def test_parse_delivery_monthname_ordinal_single():
    # A single month-name date with an ordinal suffix is explicit, not a bare month.
    out = parse_delivery("July 18th, 2026", pd.NaT)
    assert out["type"] == "explicit"
    assert out["est"] == pd.Timestamp("2026-07-18")


def test_parse_delivery_day_first_monthname():
    # "dd Month yyyy" and related (day BEFORE a named month), incl. 2-digit years
    # and dash separators. The month is named, so there is no dd/mm ambiguity.
    cases = [
        ("3 Aug 2026",      "2026-08-03"),
        ("31 Jul 26",       "2026-07-31"),   # 2-digit trailing year, not the day
        ("23 June 2026",    "2026-06-23"),
        ("3-Aug-2026",      "2026-08-03"),   # dash separators
        ("3rd August 2026", "2026-08-03"),   # ordinal + day-first
    ]
    for s, d in cases:
        out = parse_delivery(s, pd.NaT)
        assert out["type"] == "explicit", s
        assert out["est"] == pd.Timestamp(d), s
    # Day-after still works; a bare month + year stays a whole-month estimate.
    assert parse_delivery("Aug 3, 2026", pd.NaT)["est"] == pd.Timestamp("2026-08-03")
    assert parse_delivery("August 2026", pd.NaT)["type"] == "month"


def test_parse_delivery_non_us_numeric_dropped():
    # All-numeric dates are read as US m/d/y; an impossible-as-US date is dropped
    # (unknown), NOT reinterpreted as d/m/y. "31/8/2026" has no valid US reading.
    assert parse_delivery("31/8/2026", pd.NaT)["type"] == "unknown"


def test_parse_simple_date_recovers_a_zero_padded_year():
    # "3/7/0024" is 3/7/2024 — the R2 reveal date — typed into a 4-digit year field;
    # 29 rows across the two sheets are written that way and used to lose their date
    # entirely. %Y accepts year 24, then pandas cannot represent it (its floor is
    # 1677) and the OutOfBoundsDatetime fell through to a coerced NaT.
    from ingest.parsing import parse_simple_date
    assert parse_simple_date("3/7/0024") == pd.Timestamp("2024-03-07")
    assert parse_simple_date("10/7/0025") == pd.Timestamp("2025-10-07")
    assert parse_simple_date("11/14/0024") == pd.Timestamp("2024-11-14")
    # A transposed year is NOT guessed at: "3/7/0204" is not read as 2024. It is
    # rejected outright, which also pins the behaviour across pandas versions — 1.x
    # cannot represent year 204 and coerced to NaT, while 2.x accepts it and would
    # otherwise carry a year-204 timestamp downstream.
    assert pd.isna(parse_simple_date("3/7/0204"))
    assert pd.isna(parse_simple_date("3/7/0999"))
    # Ordinary formats are untouched, including the 2-digit year path.
    for s, want in (("3/7/2024", "2024-03-07"), ("3/7/24", "2024-03-07"),
                    ("03-07-2024", "2024-03-07"), ("2026-08-15", "2026-08-15")):
        assert parse_simple_date(s) == pd.Timestamp(want), s
    assert pd.isna(parse_simple_date("")) and pd.isna(parse_simple_date("garbage"))


# --- One test per delivery rule ----------------------------------------------
# The driver is covered end-to-end above; these pin each rule in isolation, so a
# failure says which shape broke instead of just "some date is wrong". Each checks
# a positive case AND that the rule declines text belonging to another rule —
# over-claiming is how a rule breaks the ones after it in the table.


def test_rule_unknown_vocabulary():
    from ingest.parsing import _VETO, _rule_unknown
    assert _rule_unknown("TBD", "tbd") is _VETO                  # exact token
    assert _rule_unknown("Not sure", "not sure") is _VETO
    assert _rule_unknown("x", "demo this saturday x") is _VETO   # substring
    assert _rule_unknown("8/15/2026", "8/15/2026") is None


def test_rule_explicit_override():
    # The one shape pinned by hand in delivery.yaml: two dash-dates joined by a
    # slash, which the range rule misreads as an M/D separator.
    from ingest.parsing import _Fixed, _rule_override
    raw = "7-13-26/8-10-26"
    res = _rule_override(raw, raw.lower())
    assert isinstance(res, _Fixed), res
    assert (res.min, res.max, res.type) == (pd.Timestamp("2026-07-13"),
                                            pd.Timestamp("2026-08-10"), "range")
    # _Fixed, not _Span: an override is an explicit human decision, so the driver
    # does NOT put it through the plausible-year window. Verified through the
    # driver, since that exemption lives there.
    out = parse_delivery(raw, pd.NaT)
    assert out["type"] == "range"
    assert (out["min"], out["max"]) == (pd.Timestamp("2026-07-13"),
                                        pd.Timestamp("2026-08-10"))
    assert _rule_override("7/13/26", "7/13/26") is None, "matched exactly, not fuzzily"


def test_rule_relative_week_range():
    from ingest.parsing import _Weeks, _rule_week_range
    for text, lo, hi in (("2-4 weeks", 2, 4), ("2 to 6 wk", 2, 6),
                         ("4 - 8 Weeks", 4, 8), ("2–6 weeks", 2, 6)):
        assert _rule_week_range(text, text.lower()) == _Weeks(lo, hi), text
    assert _rule_week_range("2 weeks", "2 weeks") is None, "one number is not a range"
    assert _rule_week_range("7/30-7/31", "7/30-7/31") is None


def test_rule_relative_single_week():
    from ingest.parsing import _Weeks, _rule_week_single
    assert _rule_week_single("2 weeks", "2 weeks") == _Weeks(2, 2)
    assert _rule_week_single("1 wk", "1 wk") == _Weeks(1, 1)
    # lo == hi, so the driver produces a POINT rather than a span.
    out = parse_delivery("2 weeks", pd.Timestamp("2026-06-20"))
    assert out["type"] == "window"
    assert out["min"] == out["max"] == out["est"] == pd.Timestamp("2026-07-04")
    assert out["anchor"] == pd.Timestamp("2026-06-20")
    assert _rule_week_single("August 2026", "august 2026") is None


def test_rule_relative_days():
    from ingest.parsing import _Days, _rule_days
    assert _rule_days("7-10 days", "7-10 days") == _Days(7, 10)
    assert _rule_days("5 days", "5 days") == _Days(5, 5)
    assert _rule_days("2 weeks", "2 weeks") is None
    assert _rule_days("today", "today") is None
    # It exists to beat the numeric-date rule, which read "7-10 days" as 10 July.
    out = parse_delivery("7-10 days", pd.Timestamp("2026-09-01"))
    assert out["type"] == "window", out
    assert (out["min"], out["max"]) == (pd.Timestamp("2026-09-08"),
                                        pd.Timestamp("2026-09-11"))


def test_rule_week_of():
    from ingest.parsing import _Span, _rule_week_of
    res = _rule_week_of("week of 8/11", "week of 8/11")
    assert isinstance(res, _Span) and res.type == "range"
    assert (res.min, res.max) == (date(2026, 8, 10), date(2026, 8, 16))
    assert _rule_week_of("8/11", "8/11") is None, "needs the 'week of' phrasing"


def test_rule_numeric_range():
    from ingest.parsing import _Span, _rule_numeric_range
    cases = [("7/30-7/31", date(2026, 7, 30), date(2026, 7, 31)),
             ("7/30 - 8/2", date(2026, 7, 30), date(2026, 8, 2)),
             ("7/30-31", date(2026, 7, 30), date(2026, 7, 31)),   # M/D-D
             ("7/28/2026 - 8/3/2026", date(2026, 7, 28), date(2026, 8, 3)),
             ("7/28 - 8/3/2026", date(2026, 7, 28), date(2026, 8, 3))]  # year one side
    for text, lo, hi in cases:
        res = _rule_numeric_range(text, text.lower())
        assert isinstance(res, _Span), text
        assert (res.min, res.max, res.type) == (lo, hi, "range"), text
    # Reversed and impossible endpoints are declined rather than "fixed".
    assert _rule_numeric_range("8/3-7/28", "8/3-7/28") is None
    assert _rule_numeric_range("7/32-7/33", "7/32-7/33") is None
    assert _rule_numeric_range("8/15/2026", "8/15/2026") is None


def test_rule_monthname_range():
    from ingest.parsing import _Span, _rule_monthname_range
    res = _rule_monthname_range("July 16-August 16", "july 16-august 16")
    assert isinstance(res, _Span) and res.type == "range"
    assert (res.min, res.max) == (date(2026, 7, 16), date(2026, 8, 16))
    # A whole-month span fills to the month end; Dec->Jan rolls the year.
    whole = _rule_monthname_range("August - September", "august - september")
    assert (whole.min, whole.max) == (date(2026, 8, 1), date(2026, 9, 30))
    roll = _rule_monthname_range("Dec-Jan", "dec-jan")
    assert roll.max.year == 2027, roll
    # Two bare month names are a span too; a month and a day are not.
    bare = _rule_monthname_range("August September", "august september")
    assert (bare.min, bare.max) == (date(2026, 8, 1), date(2026, 9, 30))
    assert _rule_monthname_range("Aug 3", "aug 3") is None
    assert _rule_monthname_range("August 2026", "august 2026") is None, (
        "a single month is not a range")


def test_rule_within_month_modifier():
    from ingest.parsing import _Span, _rule_month_modifier
    res = _rule_month_modifier("end of July", "end of july")
    assert isinstance(res, _Span) and res.type == "range"
    assert (res.min, res.max) == (date(2026, 7, 25), date(2026, 7, 31))
    mid = _rule_month_modifier("mid-September", "mid-september")
    assert (mid.min, mid.max) == (date(2026, 9, 12), date(2026, 9, 18))
    assert _rule_month_modifier("August 2026", "august 2026") is None


def test_rule_numeric_date():
    from ingest.parsing import _Point, _rule_numeric_date
    assert _rule_numeric_date("8/15/2026", "") == _Point("explicit", date(2026, 8, 15))
    assert _rule_numeric_date("2026-08-15", "") == _Point("explicit", date(2026, 8, 15))
    # Concatenated typos are repaired before parsing.
    assert _rule_numeric_date("6302026", "") == _Point("explicit", date(2026, 6, 30))
    # A bare month/year is a "month" point, which the driver expands to a span.
    assert _rule_numeric_date("08/2026", "") == _Point("month", date(2026, 8, 15))
    assert _rule_numeric_date("Not sure", "") is None


def test_rule_monthname_date():
    from ingest.parsing import _Point, _rule_monthname_date
    assert _rule_monthname_date("Aug 3, 2026", "") == _Point("explicit",
                                                             date(2026, 8, 3))
    assert _rule_monthname_date("3 Aug 2026", "") == _Point("explicit",
                                                            date(2026, 8, 3))
    assert _rule_monthname_date("August 2026", "") == _Point("month",
                                                             date(2026, 8, 15))
    assert _rule_monthname_date("8/15/2026", "") is None, "no month name present"


def test_rule_prose_date():
    from ingest.parsing import _Point, _rule_prose_date
    assert _rule_prose_date("Delivery Scheduled for 9/27/2026", "") == _Point(
        "explicit", date(2026, 9, 27))
    assert _rule_prose_date("9/12 Delivered", "") == _Point("explicit",
                                                            date(2026, 9, 12))
    # Two dates: declined, because which one won depends on the wording.
    assert _rule_prose_date("7/28 pushed back 8/4/26", "") is None
    # Must not reach inside a malformed digit run and truncate it.
    assert _rule_prose_date("8/1326", "") is None
    assert _rule_prose_date("no dates here", "") is None


def test_every_delivery_rule_has_its_own_test():
    # Guard against the table growing a rule that only the driver ever exercises.
    # Measuring coverage showed two rules ("explicit override", "relative single
    # week") that never matched anywhere in the suite before these tests existed —
    # including the override path, whose year-window exemption is deliberate.
    import inspect
    from ingest import parsing
    src = inspect.getsource(inspect.getmodule(test_rule_prose_date))
    missing = [name for name, rule in parsing._DELIVERY_RULES
               if rule.__name__ + "(" not in src]
    assert not missing, "rules with no direct test: %s" % missing


def test_delivery_rule_order_is_load_bearing():
    # parse_delivery is an ordered rule table, and two positions carry behaviour
    # rather than style — this pins them so a future reordering fails here instead
    # of quietly changing what the dashboard publishes.
    from ingest.parsing import _DELIVERY_RULES, _rule_prose_date, _rule_unknown
    names = [n for n, _ in _DELIVERY_RULES]

    # FIRST: the unknown vocabulary has to veto text that CONTAINS a date it must
    # not be read from. "Invited to Order on 8/11/2026" is an order date, and the
    # prose rule harvests it happily when given the chance.
    assert _DELIVERY_RULES[0][1] is _rule_unknown, names
    assert _rule_prose_date("Invited to Order on 8/11/2026",
                            "invited to order on 8/11/2026") is not None, (
        "the prose rule DOES match this — which is why the veto must precede it")
    assert parse_delivery("Invited to Order on 8/11/2026",
                          pd.NaT)["type"] == "unknown"

    # LAST: the prose rule is the most permissive, so every structured rule must
    # get its turn first. Given "7/30-7/31" it would return a single date; the
    # range rule ahead of it returns the span that is actually correct.
    assert _DELIVERY_RULES[-1][1] is _rule_prose_date, names
    span = parse_delivery("7/30-7/31", pd.NaT)
    assert span["type"] == "range"
    assert (span["min"], span["max"]) == (pd.Timestamp("2026-07-30"),
                                          pd.Timestamp("2026-07-31"))

    # The week rules must precede the numeric ones, or "2-4 weeks" reads as a date.
    assert names.index("relative week range") < names.index("numeric range")
    assert parse_delivery("2-4 weeks", pd.Timestamp("2026-07-01"))["type"] == "window"

    # Every rule is reachable and returns None rather than raising on text it does
    # not recognise — the driver relies on that to fall through.
    for name, rule in _DELIVERY_RULES:
        assert rule("something else entirely", "something else entirely") is None, name


def test_a_matching_rule_with_implausible_dates_falls_through():
    # A rule that matches but yields an out-of-window date must let the NEXT rule
    # try, not end the search. "8/1326" is rejected as a numeric date and then gets
    # its chance as a month name; both decline, so it ends up unknown.
    from ingest.parsing import _rule_numeric_date
    assert _rule_numeric_date("8/1326", "8/1326") is not None, (
        "the numeric rule matches — the year window is what rejects it")
    assert parse_delivery("8/1326", pd.NaT)["type"] == "unknown"
    # And a shape only the later rule understands still resolves, proving the
    # fall-through is real rather than incidental.
    assert parse_delivery("Aug 3, 2026", pd.NaT)["est"] == pd.Timestamp("2026-08-03")


def test_parse_delivery_iso_and_dotted_dates():
    # ISO was dropped outright: the numeric parser read every 3-part date as M/D/Y,
    # so "2026-08-15" became date(15, 2026, 8) — a ValueError swallowed into
    # "unparseable", losing a perfectly good date (reported for dustlesswalnut).
    # A 4-digit LEADING part can only be a year, so this needs no guesswork.
    for s in ("2026-08-15", "2026/08/15", "2026.08.15"):
        out = parse_delivery(s, pd.NaT)
        assert out["type"] == "explicit", s
        assert out["est"] == pd.Timestamp("2026-08-15"), s
    # Dots join a date as readily as slashes.
    assert parse_delivery("9.12.2026", pd.NaT)["est"] == pd.Timestamp("2026-09-12")
    # A 4-digit year in the LAST position keeps its m/d/y reading.
    assert parse_delivery("08/15/2026", pd.NaT)["est"] == pd.Timestamp("2026-08-15")
    # Day-first is still NOT accepted — ISO support must not open that door, since
    # "15-08-2026" has no valid US reading and guessing would be a coin flip.
    assert parse_delivery("15-08-2026", pd.NaT)["type"] == "unknown"


def test_parse_delivery_date_wrapped_in_prose():
    # People write a sentence: "Delivery Scheduled for 9/27/2026", "9/12 Delivered".
    for s, want in (("Delivery Scheduled for 9/27/2026", "2026-09-27"),
                    ("9/12 Delivered", "2026-09-12"),
                    ("Delivery 9/5", "2026-09-05"),
                    ("Delivered 9.12.2026", "2026-09-12")):
        out = parse_delivery(s, pd.NaT)
        assert out["type"] == "explicit", s
        assert out["est"] == pd.Timestamp(want), s

    # TWO dates means the sentence is doing something this can't read: which one
    # won depends on the wording ("pushed back" vs "moved up from"), so it stays
    # unparseable for overrides.yaml to settle rather than being guessed.
    assert parse_delivery("7/28 pushed back 8/4/26", pd.NaT)["type"] == "unknown"

    # A date that is not a DELIVERY date must not be harvested. "Invited to Order
    # on 8/11/2026" is an order date; delivery.yaml vetoes it by substring, and that
    # check runs before any parsing.
    assert parse_delivery("Invited to Order on 8/11/2026",
                          pd.NaT)["type"] == "unknown"

    # The prose fallback must not reach INSIDE a malformed run of digits and
    # "rescue" it by truncation: "8/1326" holds a leading "8/13", and reporting
    # that as a confident 13 August is the guess the year window exists to refuse.
    assert parse_delivery("8/1326", pd.NaT)["type"] == "unknown"


def test_a_no_date_phrase_does_not_veto_a_real_estimate():
    # The "I don't know" phrasings are EXACT tokens, not substrings, and this is
    # why: people combine "no VIN yet" with a genuine estimate. As a substring,
    # "not assigned" matched "Not assigned yet/2-4 weeks" and returned unknown
    # before the window parser ran, discarding the only information in the field.
    out = parse_delivery("Not assigned yet/2-4 weeks", pd.Timestamp("2026-07-01"))
    assert out["type"] == "window", out
    assert out["min"] == pd.Timestamp("2026-07-15")
    assert out["max"] == pd.Timestamp("2026-07-29")
    # On its own it is still a "no date" answer, reported as such rather than as
    # text we failed to read.
    for s in ("Not assigned", "Not sure yet", "None yet", "?", "Soon", "Unsure",
              "Don’t know", "No date yet", "No estimate"):
        assert parse_delivery(s, pd.NaT)["type"] == "unknown", s


def test_parse_delivery_implausible_year_is_unknown():
    # A typo can parse cleanly but land centuries away: "8/1326" (meant 8/13/26)
    # reads as month 8 of year 1326. pandas 1.x raises OutOfBoundsDatetime on that
    # Timestamp (crashing the run) while pandas 2.x accepts it and would silently
    # publish the bad date, so parse_delivery must reject it outright.
    for s in ("8/1326", "7/1/1900", "1/1/1970", "12/25/2099"):
        out = parse_delivery(s, pd.NaT)
        assert out["type"] == "unknown", s
        assert pd.isna(out["est"]), s
    # Plausible years still parse normally.
    assert parse_delivery("8/13/26", pd.NaT)["est"] == pd.Timestamp("2026-08-13")


def test_parse_delivery_week_of():
    # "Week of <date>" -> the Mon-Sun week containing that date. Aug 3, 2026 is a
    # Monday, so its week is 8/3 (Mon) .. 8/9 (Sun).
    out = parse_delivery("Week of August 3rd", pd.NaT)
    assert out["type"] == "range"
    assert out["min"] == pd.Timestamp("2026-08-03")
    assert out["max"] == pd.Timestamp("2026-08-09")
    # A mid-week date snaps back to the same Monday (Aug 5 is a Wednesday).
    mid = parse_delivery("week of August 5", pd.NaT)
    assert mid["min"] == pd.Timestamp("2026-08-03")
    assert mid["max"] == pd.Timestamp("2026-08-09")
    # Numeric date form works too (8/10/2026 is a Monday).
    num = parse_delivery("week of 8/10/2026", pd.NaT)
    assert num["min"] == pd.Timestamp("2026-08-10")
    assert num["max"] == pd.Timestamp("2026-08-16")


def test_parse_delivery_window_anchor():
    # A week-window is measured from the order date and records that anchor;
    # absolute types (explicit/range/month) leave the anchor unset.
    order = pd.Timestamp("2026-06-20")
    win = parse_delivery("4-8 weeks", order)
    assert win["type"] == "window" and win["anchor_fallback"] is False
    assert win["anchor"] == order
    assert win["min"] == order + pd.Timedelta(weeks=4)
    assert win["max"] == order + pd.Timedelta(weeks=8)
    exp = parse_delivery("07/14/2026", order)
    assert exp["type"] == "explicit" and pd.isna(exp["anchor"])


def test_apply_additions_appends_new_and_flags_conflicts():
    # Additions append forum-only rows; a name already in the sheet or an unknown
    # field is flagged (the latter still adds the row, minus the bad field).
    from ingest.loaders import _apply_additions
    df = pd.DataFrame({"orig_num": ["1"], "user": ["Alice"], "vin_raw": ["1200"]})
    add_df, added, issues = _apply_additions(df, {
        "Bob": {"vin_raw": "1500", "loc_raw": "CA"},   # new -> appended
        "alice": {"vin_raw": "9"},                     # already in sheet -> issue
        "Carol": {"bogus": "x"},                       # unknown field -> issue
    })
    users = list(add_df["user"])
    assert "Bob" in users and "Carol" in users and "Alice" not in users
    assert len(added) == 2
    assert add_df.loc[add_df["user"] == "Bob", "loc_raw"].iloc[0] == "CA"
    assert any("already in orders sheet" in d for _, _, d in issues)
    assert any("unknown field" in d for _, _, d in issues)


def test_price_launch_edition_bundles_autonomy_and_tow():
    # The Launch Package carries no upcharge and includes Autonomy+ and Tow, so a
    # base Launch Edition is exactly the Performance base price even though the
    # sheet marks both options as taken.
    from ingest.pricing import price_order
    parts, issues = price_order(
        trim="Performance", launch="Yes", color="Esker Silver",
        interior="Black Crater Signature", wheels="21” Liquid Tungsten All-Season",
        autonomy="Included", tow="Included", spare="No")
    assert parts["price"] == 57990, parts
    assert parts["price_autonomy_tow"] == 0
    assert issues == []


def test_price_without_launch_package_charges_options():
    # Same car without the package: Autonomy+ ($2,500) and Tow ($900) are billed.
    # This is the future state once Rivian stops offering the Launch Package.
    from ingest.pricing import price_order
    parts, _ = price_order(
        trim="Performance", launch="No", color="Esker Silver",
        interior="Black Crater Signature", wheels="21” Liquid Tungsten All-Season",
        autonomy="Yes", tow="Yes", spare="No")
    assert parts["price"] == 57990 + 2500 + 900
    assert parts["price_autonomy_tow"] == 3400


def test_price_wheels_are_per_trim():
    # The 21" Liquid Tungsten is standard on Performance but a $2,000 upgrade on
    # Premium — the whole reason wheels are priced inside each trim.
    from ingest.pricing import price_order
    wheel = "21” Liquid Tungsten All-Season"
    perf, _ = price_order(trim="Performance", launch="Yes", color="Esker Silver",
                          interior="Black Crater Signature", wheels=wheel)
    prem, _ = price_order(trim="Premium", color="Esker Silver",
                          interior="Black Crater Signature", wheels=wheel)
    assert perf["price_wheels"] == 0
    assert prem["price_wheels"] == 2000
    assert prem["price"] == 53990 + 2000


def test_price_trim_alias_adds_drive_system_and_never_prefix_matches():
    # "Standard RWD LR" must resolve to Standard + the $3,500 long-range drive,
    # NOT to the base "Standard RWD" that is a prefix of it.
    from ingest.pricing import price_order, resolve_trim
    name, _, drive = resolve_trim("Standard RWD LR")
    assert (name, drive) == ("Standard", "Rear-Wheel Drive Long Range")
    lr, _ = price_order(trim="Standard RWD LR", color="Esker Silver",
                        interior="Black Crater",
                        wheels="19” Machined Graphite All-Season")
    base, _ = price_order(trim="Standard RWD", color="Esker Silver",
                          interior="Black Crater",
                          wheels="19” Machined Graphite All-Season")
    assert base["price"] == 44990
    assert lr["price"] == 44990 + 3500


def test_price_flags_option_not_offered_on_trim():
    # Borealis is Performance-only. On Premium it's still priced (best effort) but
    # reported as a configuration issue rather than silently accepted.
    from ingest.pricing import price_order
    parts, issues = price_order(trim="Premium", color="Borealis",
                                interior="Black Crater Signature",
                                wheels="20” Bicolor Carbon All-Season")
    assert parts["price"] == 53990 + 2000
    assert any("not offered on Premium" in m for m in issues), issues


def test_price_unknown_trim_is_unpriced():
    # An unrecognized trim can't be priced at all -> None, so the order lands in
    # the explicit "unpriced" bucket instead of being counted as $0.
    from ingest.pricing import price_order
    parts, issues = price_order(trim="Sport Turbo", color="Esker Silver")
    assert parts["price"] is None
    assert any("unknown trim" in m for m in issues)


def test_reconcile_launch_bundles_and_flags_only_contradictions():
    # The Launch Package column is authoritative. "Yes" vs "Included" is just a
    # wording difference, so normalizing it is silent; the two real
    # contradictions get reported.
    from ingest.pricing import reconcile_launch_options
    # Launch order saying "Yes" -> Included, no issue (the common sloppiness).
    vals, issues = reconcile_launch_options("Yes", autonomy="Yes", tow="Included")
    assert vals == {"autonomy": "Included", "tow": "Included"}
    assert issues == []
    # Launch order saying "No" -> Included, and flagged: the package bundles it.
    vals, issues = reconcile_launch_options("Yes", autonomy="No", tow="Included")
    assert vals["autonomy"] == "Included"
    assert len(issues) == 1 and "autonomy" in issues[0]
    # No package but "Included" -> Yes, flagged as added separately.
    vals, issues = reconcile_launch_options("No", autonomy="Included", tow="No")
    assert vals == {"autonomy": "Yes", "tow": "No"}
    assert len(issues) == 1 and "added separately" in issues[0]
    # No package, plain answers pass straight through.
    vals, issues = reconcile_launch_options("No", autonomy="Yes", tow="No")
    assert vals == {"autonomy": "Yes", "tow": "No"} and issues == []
    # A blank answer on a Launch order is filled in, not flagged — nothing was
    # contradicted, the reporter just didn't answer.
    vals, issues = reconcile_launch_options("Yes", autonomy="", tow="")
    assert vals == {"autonomy": "Included", "tow": "Included"} and issues == []


def test_reconcile_launch_does_not_change_price():
    # Reconciliation feeds pricing, so confirm it's price-neutral: a Launch order
    # never pays for the bundled options however it answered, and a non-Launch
    # "Included" pays exactly as an explicit "Yes" would.
    from ingest.pricing import price_order, reconcile_launch_options
    base = dict(trim="Performance", color="Esker Silver",
                interior="Black Crater Signature",
                wheels="21” Liquid Tungsten All-Season")
    for raw in ("Yes", "Included", "No", ""):
        v, _ = reconcile_launch_options("Yes", autonomy=raw, tow=raw)
        parts, _ = price_order(launch="Yes", autonomy=v["autonomy"],
                               tow=v["tow"], **base)
        assert parts["price"] == 57990, (raw, parts["price"])
    v, _ = reconcile_launch_options("No", autonomy="Included", tow="Included")
    parts, _ = price_order(launch="No", autonomy=v["autonomy"], tow=v["tow"],
                           **base)
    assert parts["price"] == 57990 + 2500 + 900


def test_config_panel_stacks_only_when_split_has_two_values():
    # The stack is conditional: one trim renders plain bars and no legend, two
    # trims split each bar and add the trim legend. Uses synthetic rows so the
    # multi-trim path is covered before Premium/Standard actually ship.
    import pandas as pd
    from render.charts import fig_config_dashboard
    cols = dict(color="Esker Silver", interior="Black Crater Signature",
                wheels_short='21" Liquid Tungsten', buylease="Purchase",
                opted_spare=True, r1_owner="No", r1_model="")
    one = pd.DataFrame([dict(cols, trim="Performance") for _ in range(3)])
    two = pd.DataFrame([dict(cols, trim="Performance") for _ in range(3)]
                       + [dict(cols, trim="Premium") for _ in range(2)])
    f1, f2 = fig_config_dashboard(one), fig_config_dashboard(two)
    assert not any(t.showlegend for t in f1.data), "single trim should add no legend"
    names = {t.name for t in f2.data if t.name}
    assert {"Performance", "Premium"} <= names, names
    # The wheels panel should now be two stacked traces summing to the 5 rows.
    wheels = [t for t in f2.data if t.name in ("Performance", "Premium")
              and t.x and t.x[0] == '21" Liquid Tungsten']
    assert sum(int(v) for t in wheels for v in t.y) == 5


def test_reconcile_r1_owner_trusts_a_named_model():
    # "Are you a current R1 owner?" is one click; naming R1S/R1T is concrete
    # information a non-owner has no reason to give, so the model wins and the
    # coercion is reported rather than silent.
    from ingest.parsing import reconcile_r1_owner
    owner, issue = reconcile_r1_owner("No", "R1S")
    assert owner == "Yes"
    assert issue and "R1S" in issue
    # Consistent answers and plain non-owners pass through untouched.
    assert reconcile_r1_owner("Yes", "R1T") == ("Yes", None)
    assert reconcile_r1_owner("No", "") == ("No", None)
    assert reconcile_r1_owner("", "") == ("", None)
    # An owner who skipped the model question is incomplete, not contradictory.
    assert reconcile_r1_owner("Yes", "") == ("Yes", None)


# --- Order-to-delivery time (#19) ------------------------------------------


def test_implausible_latency_flags_only_contradictions():
    from ingest.parsing import implausible_latency
    T = pd.Timestamp
    order = T("2026-08-18")
    # The real case: a bare "8-12" meant weeks, read as 12 August.
    assert "before the order" in implausible_latency(order, T("2026-08-12"),
                                                     T("2026-08-12"))
    # A typo'd year: more than DELIVERY_LATENCY_MAX days out.
    assert "days after" in implausible_latency(T("2026-09-25"), T("2027-09-27"),
                                               T("2027-09-27"))
    # Ordinary waits are fine, including same-day and a range that STARTS before the
    # order but ends after it — only an estimate wholly before the order is impossible.
    assert implausible_latency(order, T("2026-09-20"), T("2026-09-20")) is None
    assert implausible_latency(order, order, order) is None
    assert implausible_latency(order, T("2026-08-01"), T("2026-09-30")) is None
    # Nothing to compare when either side is missing.
    assert implausible_latency(pd.NaT, T("2026-09-20"), T("2026-09-20")) is None
    assert implausible_latency(order, pd.NaT, pd.NaT) is None


def _latency_frame_input():
    T = pd.Timestamp
    rows = []
    def add(user, order, est, typ="explicit"):
        rows.append(dict(user=user, order_date=T(order) if order else pd.NaT,
                         delivery_est=T(est) if est else pd.NaT,
                         delivery_min=T(est) if est else pd.NaT,
                         delivery_max=T(est) if est else pd.NaT, delivery_type=typ))
    # Week of Mon 2026-08-03: three firm dates -> a median is drawn.
    add("a", "2026-08-03", "2026-09-02")     # 30 days
    add("b", "2026-08-04", "2026-09-13")     # 40 days
    add("c", "2026-08-05", "2026-08-25")     # 20 days
    add("d", "2026-08-06", None, "unknown")  # same week, no firm date -> coverage 3/4
    # Week of Mon 2026-08-10: two firm dates -> too few for a median.
    add("e", "2026-08-10", "2026-08-20")
    add("f", "2026-08-11", "2026-08-31")
    # Excluded: a window (not firm), an impossible estimate, a missing order date.
    add("g", "2026-08-12", "2026-09-30", "window")
    # Delivery before order: cleaning sets such an estimate aside (outliers.py),
    # so it arrives here as unknown — counted as an order, never plotted.
    add("h", "2026-08-18", None, "unknown")
    add("i", None, "2026-09-01")
    return pd.DataFrame(rows)


def test_latency_frame_keeps_only_measurable_firm_dates():
    from render.charts import latency_frame
    d = latency_frame(_latency_frame_input())
    assert sorted(d["user"]) == ["a", "b", "c", "e", "f"], sorted(d["user"])
    assert dict(zip(d["user"], d["days"]))["a"] == 30
    # Monday-start weeks.
    weeks = {u: str(w.date()) for u, w in zip(d["user"], d["order_week"])}
    assert weeks["a"] == weeks["c"] == "2026-08-03" and weeks["e"] == "2026-08-10"


def test_latency_chart_median_needs_enough_orders_and_coverage_is_honest():
    from render.charts import fig_delivery_latency
    fig = fig_delivery_latency(_latency_frame_input())
    med = [t for t in fig.data if (t.name or "").startswith("Weekly median")]
    assert len(med) == 1
    # Only the week with 3 firm dates gets a point, at its median (30 days).
    assert list(med[0].y) == [30.0], list(med[0].y)
    cov = next(t for t in fig.data if t.type == "bar")
    # Coverage = shown / ALL orders placed that week, so the unknown-estimate,
    # windowed and impossible orders count against it rather than vanishing.
    # Week of 8/3: a,b,c of a,b,c,d = 75%. Week of 8/10: e,f of e,f,g = 67% (the
    # window doesn't count as shown). Week of 8/17: h's impossible estimate leaves
    # it 0 of 1 — not in the scatter, but still counted as an order placed.
    assert [round(v) for v in cov.y] == [75, 67, 0], list(cov.y)
    assert [int(n) for n in cov.customdata[:, 2]] == [4, 3, 1]


# --- Build cadence (#33) ----------------------------------------------------


def _cadence_input(rate=150.0, weeks=12, per_week=8, start="2026-06-29",
                   as_of="2026-10-02", jitter=0.0, seed=0):
    """Synthetic firm-dated deliveries whose build front rises at `rate` VINs/day."""
    rng = np.random.default_rng(seed)
    T = pd.Timestamp
    rows = []
    for w in range(weeks):
        week = T(start) + pd.Timedelta(weeks=w)
        for k in range(per_week):
            day = week + pd.Timedelta(days=int(k % 7))
            # A spread of VINs below the front, like held-back cars, plus the front.
            vin = 1000 + rate * (day - T(start)).days - rng.uniform(0, 2000) * (k % 3)
            vin += rng.normal(0, jitter)
            rows.append(dict(vin_present=True, vin_seq=float(vin),
                             delivery_type="explicit",
                             delivery_est=day, delivery_min=day, delivery_max=day,
                             order_date=day - pd.Timedelta(days=30)))
    return pd.DataFrame(rows)


def test_theil_sen_is_exact_on_a_line_and_ignores_an_outlier():
    from render.cadence import theil_sen
    x = np.arange(10.0)
    assert theil_sen(x, 3 * x + 7) == (3.0, 7.0)
    y = 3 * x + 7
    y[4] = 99999.0                          # a typo'd VIN must not drag the rate
    slope, _ = theil_sen(x, y)
    assert abs(slope - 3.0) < 0.5, slope
    assert theil_sen([1.0], [2.0]) is None


def test_build_front_uses_only_finished_weeks_with_enough_dates():
    from render.cadence import build_front, cadence_frame
    d = cadence_frame(_cadence_input(weeks=16))
    front = build_front(d, as_of=pd.Timestamp("2026-10-02"))
    # Weeks starting 9/28 and later haven't finished by 10/2 — a scheduled week holds
    # only the few people with a date, so its high percentile would sit low.
    assert front.index.max() == pd.Timestamp("2026-09-21"), front.index.max()
    thin = build_front(d, min_n=50, as_of=pd.Timestamp("2026-10-02"))
    assert thin.empty, "weeks below min_n contribute no front point"


def test_projection_recovers_the_rate_and_measures_its_own_error():
    from render.cadence import projection
    p = projection(_cadence_input(rate=150.0, weeks=13))
    assert p is not None
    assert abs(p["rate"] - 150.0) < 15, p["rate"]
    # On a steady synthetic ramp the back-test should find the projection accurate
    # in both directions, and neither side may narrow with the horizon.
    assert p["ahead_days"][0] < 3 and p["behind_days"][0] < 3, (
        p["ahead_days"], p["behind_days"])
    for side in (p["ahead_days"], p["behind_days"]):
        assert all(b >= a for a, b in zip(side, side[1:])), side
    # Zero width at the last observed week; each side then comes from its own
    # misses.
    assert p["lo"][0] == p["hi"][0] == p["center"][0]
    assert np.allclose(p["hi"][1:] - p["center"][1:],
                       np.array(p["ahead_days"]) * p["rate"])
    assert np.allclose(p["center"][1:] - p["lo"][1:],
                       np.array(p["behind_days"]) * p["rate"])


def test_band_leans_ahead_when_the_rate_steps_up():
    # The live situation: production ramps in STEPS, so projections fall behind and
    # the band's upper side must be the wider one. A symmetric band would put as much
    # room below the line as above, where the back-test found no misses.
    from render.cadence import projection
    slow = _cadence_input(rate=60.0, weeks=8)
    fast = _cadence_input(rate=150.0, weeks=6, start="2026-08-24")
    fast["vin_seq"] += slow["vin_seq"].max() - 1000
    p = projection(pd.concat([slow, fast], ignore_index=True))
    assert p is not None
    assert p["ahead_days"][-1] > 2 * p["behind_days"][-1], (
        p["ahead_days"], p["behind_days"])
    assert (p["hi"][-1] - p["center"][-1]) > (p["center"][-1] - p["lo"][-1])


def test_projection_is_withheld_without_history_to_measure_it():
    from render.cadence import projection
    assert projection(_cadence_input(weeks=3)) is None, (
        "an unmeasured band would be a guess presented as a forecast")


def test_backtest_sign_shows_when_reality_ran_ahead():
    # Cadence doubles halfway through: projections made before the jump fall behind,
    # which the back-test reports as POSITIVE error (reality ran ahead).
    from render.cadence import backtest, cadence_frame
    slow, fast = _cadence_input(rate=60.0, weeks=8), _cadence_input(
        rate=150.0, weeks=8, start="2026-08-24")
    fast["vin_seq"] += slow["vin_seq"].max() - 1000
    bt = backtest(cadence_frame(pd.concat([slow, fast], ignore_index=True)), cuts=8)
    assert not bt.empty and bt["err_days"].mean() > 0, bt["err_days"].mean()


def test_vin_scatter_keeps_whisker_indices():
    # The overlay is appended AFTER the series, because the whisker toggle addresses
    # traces by index.
    from render.charts import fig_delivery_vs_vin
    df = _cadence_input(weeks=13)
    df["color"], df["wheels_short"] = "Esker Silver", '21" Liquid Tungsten'
    df["interior"], df["trim"] = "Black Crater Signature", "Performance"
    df["user"] = "u"
    for c, v in (("vin_display", ""), ("order_display", ""), ("est_display", ""),
                 ("buylease", "Purchase"), ("state", "IL")):
        df[c] = v
    # A windowed estimate, so whiskers (and the toggle that targets them) exist —
    # without one the index check below would pass vacuously.
    win = df.iloc[[5]].copy()
    win["delivery_type"] = "window"
    win["delivery_min"] = win["delivery_est"] - pd.Timedelta(days=7)
    win["delivery_max"] = win["delivery_est"] + pd.Timedelta(days=7)
    fig = fig_delivery_vs_vin(pd.concat([df, win], ignore_index=True))
    names = [t.name for t in fig.data]
    assert names[-3] == "Observed" and names[-1].startswith("Projected · ≈ ")
    # The overlay sits in its own legend, separate from the paint · wheels series.
    overlay = [t for t in fig.data if t.legend == "legend2"]
    assert [t.name for t in overlay] == names[-3:], [t.name for t in overlay]
    assert fig.layout.legend2.title.text == "Build front"
    # The projection's hover quotes VINs (its own axis), rounded to the hundred.
    proj = fig.data[-1]
    assert "days" not in proj.hovertemplate and "likely VIN" in proj.hovertemplate
    assert all(v % 100 == 0 for v in np.asarray(proj.customdata, dtype=float).ravel())
    assert fig.layout.updatemenus, "the fixture must produce whiskers to test against"
    whisk = set(fig.layout.updatemenus[0].buttons[0].args[1])
    assert whisk and all(fig.data[i].mode == "lines" and not fig.data[i].fill
                         for i in whisk), "toggle targets exactly the whisker traces"
    assert not any(fig.data[i].legend == "legend2" for i in whisk), (
        "the whisker toggle must not reach the overlay")
    # Date on x, VIN on y (transposed to match §9).
    assert fig.layout.xaxis.type == "date" and fig.layout.yaxis.type == "linear"


def test_state_totals_segments_partition_each_state():
    # The three segments must sum to each state's order count: a delivery has to be
    # deducted from whichever VIN bucket it came from, or the bar overstates the
    # state. Covers all four delivered x VIN combinations, including a delivered
    # order with no VIN (which still counts as delivered).
    import pandas as pd
    from render.charts import fig_state_totals
    def row(state, vin, delivered):
        return dict(state=state, lat=1.0, vin_present=vin,
                    delivered_inferred=delivered)
    df = pd.DataFrame([
        row("CA", True, True), row("CA", True, False), row("CA", False, True),
        row("CA", False, False), row("TX", False, True), row("TX", True, False),
        # Unmapped states are excluded from the chart entirely.
        dict(state="ZZ", lat=float("nan"), vin_present=True,
             delivered_inferred=True),
    ])
    fig = fig_state_totals(df)
    # Per-state segments; the "All states" summary row is checked separately below.
    named = [t for t in fig.data if t.name and list(t.y) != ["All states"]]
    assert len(named) == 3, [t.name for t in named]
    per_state = {}
    for t in named:
        for s, v in zip(t.y, t.x):
            per_state[s] = per_state.get(s, 0) + int(v)
    assert per_state == {"CA": 4, "TX": 2}, per_state
    seg = {t.name: dict(zip(t.y, [int(v) for v in t.x])) for t in named}
    assert seg["Delivered (est.)"] == {"CA": 2, "TX": 1}
    assert seg["Awaiting delivery · VIN"] == {"CA": 1, "TX": 1}
    assert seg["Awaiting delivery · no VIN"] == {"CA": 1, "TX": 0}


def test_state_totals_summary_row_matches_the_shared_split():
    # #53: the all-states row and the summary-page cards come from ONE helper, so
    # they can't drift. The row covers orders with a known state (an unmapped order
    # is excluded from the chart), while the cards cover every order — so the two
    # agree exactly when every order is located, and differ by the unmapped ones.
    import pandas as pd
    from render.charts import DELIVERY_STAGES, delivery_progress, fig_state_totals
    def row(state, vin, delivered, lat=1.0):
        return dict(state=state, lat=lat, vin_present=vin, delivered_inferred=delivered)
    df = pd.DataFrame([
        row("CA", True, True), row("CA", True, False), row("CA", False, True),
        row("CA", False, False), row("TX", False, True), row("TX", True, False),
        row("ZZ", True, True, lat=float("nan")),
    ])
    stages = delivery_progress(df)
    # A strict partition: every order lands in exactly one stage.
    assert list(stages) == list(DELIVERY_STAGES)
    hits = sum(m.astype(int) for m in stages.values())
    assert (hits == 1).all(), hits.tolist()
    assert {k: int(m.sum()) for k, m in stages.items()} == {
        "Delivered (est.)": 4, "Awaiting delivery · VIN": 2,
        "Awaiting delivery · no VIN": 1}

    top = {t.name: int(t.x[0]) for t in fig_state_totals(df).data
           if t.name and list(t.y) == ["All states"]}
    located = delivery_progress(df.dropna(subset=["lat"]))
    assert top == {k: int(m.sum()) for k, m in located.items()}, top
    assert sum(top.values()) == 6, "the unmapped ZZ order is not in the chart"
    # Each segment states its count and share, since the row has no tick labels.
    texts = [t.text[0] for t in fig_state_totals(df).data
             if t.name and list(t.y) == ["All states"]]
    assert texts == ["3 · 50%", "2 · 33%", "1 · 17%"], texts


def test_delivered_inferred_only_for_a_passed_upper_bound():
    # The rule reads delivery_max: strictly past counts, today or later doesn't,
    # and a missing bound never does.
    import pandas as pd
    from ingest.loaders import load_and_clean  # noqa: F401  (import path check)
    from config import AS_OF
    mx = pd.to_datetime(pd.Series([
        AS_OF - pd.Timedelta(days=1),   # yesterday -> delivered
        AS_OF,                          # today -> not yet
        AS_OF + pd.Timedelta(days=30),  # future -> no
        None,                           # no estimate -> no
    ]))
    delivered = mx.notna() & (mx < AS_OF)
    assert list(delivered) == [True, False, False, False]


# --- Column mapping and schema-drift detection ------------------------------
# Columns are located by NAME, so these tests pin both halves of that contract:
# what the sheets are free to change (order, new questions, wording) and what
# still has to stop the build (a mapped column that can't be found exactly once,
# which would otherwise read as empty for every row).


def _orders_header():
    """A stand-in orders header row: a blank column A, every mapped column, then
    the unread extras. The order here is deliberately not the sheet's — that it
    doesn't have to be is the point of mapping by name."""
    from config import ORDERS_HEADERS, ORDERS_IGNORED
    return [""] + list(ORDERS_HEADERS.values()) + list(ORDERS_IGNORED)


def _reservations_header():
    """Likewise for the reservations export, which also has a blank spacer
    column in the middle of its header row."""
    from config import RESERVATIONS_COLUMNS, RESV_IGNORED
    return ([""] + list(RESERVATIONS_COLUMNS.values()) + [""]
            + list(RESV_IGNORED))


def _map_orders(header):
    from config import ORDERS_HEADERS, ORDERS_IGNORED
    from ingest.schema_check import map_columns
    return map_columns(header, ORDERS_HEADERS, ORDERS_IGNORED,
                       "test orders sheet")


def _map_resv(header):
    from config import RESERVATIONS_COLUMNS, RESV_IGNORED
    from ingest.schema_check import map_columns
    return map_columns(header, RESERVATIONS_COLUMNS, RESV_IGNORED,
                       "test reservations sheet")


def _drift(fn, *args):
    """Return the SchemaDrift message fn raises; fail if it raises nothing."""
    from ingest.schema_check import SchemaDrift
    try:
        fn(*args)
    except SchemaDrift as exc:
        return str(exc)
    raise AssertionError("expected SchemaDrift, none was raised")


def test_schema_matches_the_cached_live_headers():
    # The schema has to match the real exports, not just a fixture. data/raw is
    # committed, so this runs in CI too; it no-ops if no cache is present.
    import glob
    from config import (DATA_RAW, ORDERS_HEADERS, ORDERS_IGNORED, ORDERS_SLUG,
                        RESERVATIONS_COLUMNS, RESV_IGNORED, RESV_SLUG)
    from ingest.schema_check import find_header, map_columns
    sheets = ((ORDERS_SLUG, ORDERS_HEADERS, ORDERS_IGNORED),
              (RESV_SLUG, RESERVATIONS_COLUMNS, RESV_IGNORED))
    for slug, expected, ignored in sheets:
        caches = sorted(glob.glob(os.path.join(str(DATA_RAW), slug + "_*.csv")))
        if not caches:
            continue
        with open(caches[-1]) as fh:
            records = list(csv.reader(fh))
        _, header = find_header(records, expected["user"], slug)
        idx, notices = map_columns(header, expected, ignored, slug)
        assert len(idx) == len(expected)
        assert notices == [], "%s: unmapped column — %s" % (slug, notices)


def test_mapped_columns_may_be_reordered():
    # The whole reason for mapping by name: the sheets are hand-maintained, so
    # someone dragging a column must not change a single number.
    from config import ORDERS_HEADERS
    header = list(reversed(_orders_header()))
    idx, notices = _map_orders(header)
    assert notices == []
    for field, want in ORDERS_HEADERS.items():
        assert header[idx[field]] == want
    header = list(reversed(_reservations_header()))
    idx, notices = _map_resv(header)
    assert notices == [] and len(idx) == 4


def test_a_column_inserted_anywhere_is_harmless():
    header = _orders_header()
    header.insert(header.index("Color"), "Roof")
    idx, notices = _map_orders(header)
    assert header[idx["color"]] == "Color"     # nothing shifted
    assert len(notices) == 1 and "Roof" in notices[0][2]


def test_cosmetic_header_edits_are_tolerated():
    # Case and spacing carry no meaning, so re-wording a question that way must
    # not stop the daily build.
    header = _orders_header()
    header[header.index("Trim")] = "  TRIM  "
    header[header.index("Purchase or Lease?")] = "Purchase  or  Lease?"
    idx, notices = _map_orders(header)
    assert notices == [] and header[idx["trim"]] == "  TRIM  "


def test_renamed_column_is_fatal_and_names_the_suspect():
    # A rename can't be told apart from a repurpose, so it has to stop — but the
    # message should point straight at the likely new name.
    header = _orders_header()
    header[header.index("Color")] = "Paint"
    msg = _drift(_map_orders, header)
    assert "color" in msg and "'Color'" in msg and "not found" in msg
    assert "'Paint'" in msg.split("Unmapped columns present")[1]


def test_removed_column_is_fatal():
    # Would otherwise read as empty for every row.
    header = [c for c in _orders_header() if c != "Compact Spare Tire Added"]
    msg = _drift(_map_orders, header)
    assert "spare" in msg and "not found" in msg


def test_missing_number_column_is_fatal():
    # "#" is no longer a positional anchor, but orig_num still maps to it and it
    # labels every row in the reports.
    header = [c for c in _orders_header() if c != "#"]
    assert "orig_num" in _drift(_map_orders, header)


def test_duplicated_column_is_ambiguous_not_a_silent_pick():
    header = _orders_header() + ["Location"]
    msg = _drift(_map_orders, header)
    assert "ambiguous" in msg and "loc_raw" in msg


def test_schema_mapping_two_fields_to_one_header_is_fatal():
    # A copy-paste slip in schema.yaml would otherwise read one column twice and
    # leave the other field wrong — same silent mis-map, sourced from the config.
    from ingest.schema_check import map_columns
    bad = {"user": "Username", "trim": "Trim", "color": "Trim"}
    msg = _drift(map_columns, _orders_header(), bad, [], "test sheet")
    assert "same sheet header" in msg


def test_new_column_is_reported_but_not_fatal():
    # It can't mis-map anything, but it must be reported — it means new data
    # exists that nothing charts yet.
    idx, notices = _map_orders(_orders_header() + ["Home charger?"])
    assert len(idx) == 18 and len(notices) == 1
    assert "Home charger?" in notices[0][2]


def test_known_extras_are_not_reported():
    # The R1-keep and other-vehicles questions are listed in ignored_columns, so
    # a notice always means something genuinely new.
    assert _map_orders(_orders_header())[1] == []
    assert _map_resv(_reservations_header())[1] == []
    _, notices = _map_resv(_reservations_header() + ["Which trim?"])
    assert len(notices) == 1 and "Which trim?" in notices[0][2]


def test_find_header_skips_the_title_rows():
    from ingest.schema_check import find_header
    records = [[""] * 4, ["", "", "Tracker Form  <-- link to submit"],
               _orders_header(), ["", "1", "someone"]]
    i, header = find_header(records, "Username", "test sheet")
    assert i == 2 and "Username" in header


def test_find_header_fails_when_there_is_no_header_row():
    from ingest.schema_check import find_header
    msg = _drift(find_header, [[""] * 4, ["", "junk"]], "Username", "test sheet")
    assert "no header row" in msg


def _orders_csv(header):
    """A minimal orders export: blank + title rows, the given header row, then
    one order whose cells sit under their own headers — so reordering `header`
    carries the data with it, exactly as dragging a column in the sheet would."""
    from config import ORDERS_HEADERS
    order = {"orig_num": "1", "user": "tester", "order_raw": "6/15/2026",
             "loc_raw": "IL", "trim": "Performance", "launch": "Yes",
             "color": "Midnight", "interior": "Black Crater Signature",
             "wheels": '21" Liquid Tungsten All-Season'}
    by_header = {ORDERS_HEADERS[f]: v for f, v in order.items()}
    out = io.StringIO()
    csv.writer(out).writerows([
        [""] * len(header),
        ["", "", "R2 Orders & Deliveries Tracker Form  <-- link to submit"],
        header,
        [by_header.get(h, "") for h in header],
    ])
    return out.getvalue()


def _one_order(text):
    from ingest.loaders import load_and_clean
    df, _, _ = load_and_clean(text, {"label": "test orders sheet"})
    return df[df["user"] == "tester"].iloc[0]


def test_load_and_clean_reads_a_reordered_sheet_correctly():
    # End to end, not just in the checker: a shuffled sheet has to produce the
    # same row, since that is what the by-name mapping buys.
    row = _one_order(_orders_csv(_orders_header()))
    assert row["color"] == "Midnight"
    assert row["interior"] == "Black Crater Signature"

    shuffled = list(reversed(_orders_header()))
    row = _one_order(_orders_csv(shuffled))
    assert row["color"] == "Midnight"
    assert row["interior"] == "Black Crater Signature"
    assert row["trim"] == "Performance"


def test_load_and_clean_refuses_a_sheet_missing_a_mapped_column():
    # The guard has to be wired into the loader, not merely importable.
    from ingest.loaders import load_and_clean
    header = _orders_header()
    header[header.index("Interior")] = "Cabin"
    msg = _drift(load_and_clean, _orders_csv(header),
                 {"label": "test orders sheet"})
    assert "schema.yaml" in msg and "interior" in msg


def test_load_and_clean_ignores_unmapped_columns_entirely():
    # Dropping the two unread questions from the schema must not change what a
    # row parses to, and the sheet keeping them must not produce a notice.
    from ingest.loaders import load_and_clean
    df, report, _ = load_and_clean(_orders_csv(_orders_header()),
                                   {"label": "test orders sheet"})
    assert "other_vehicles" not in df.columns and "r1_keep" not in df.columns
    assert report["quality"]["schema_notices"] == []


def test_column_letters_match_spreadsheet_labels():
    from ingest.schema_check import _col_letter
    assert [_col_letter(i) for i in (0, 1, 25, 26, 27)] == \
        ["A", "B", "Z", "AA", "AB"]

# --- "Report issue" button ---------------------------------------------------


def test_report_button_prefill_matches_the_issue_form():
    # The button's query keys have to be the issue form's field ids: GitHub
    # silently ignores one that isn't, and a dropped prefill is invisible until
    # someone files a report with no build info in it.
    import yaml
    from datetime import datetime
    from urllib.parse import parse_qs, urlparse
    from render.page import ISSUE_FORM_URL, _report_url
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    form_file = "dashboard-report.yml"
    with open(os.path.join(root, ".github", "ISSUE_TEMPLATE", form_file)) as fh:
        form = yaml.safe_load(fh)
    field_ids = {b["id"] for b in form["body"] if "id" in b}

    url = _report_url({"orders_meta": {"updated_at": datetime(2026, 8, 6, 22, 24)},
                       "resv_meta": {"updated_at": None}})
    assert url.startswith(ISSUE_FORM_URL + "?")
    query = parse_qs(urlparse(url).query)
    assert query["template"] == [form_file]
    assert set(query) - {"template"} <= field_ids
    # The build stamp is the whole point: it must carry the sheet's timestamp,
    # and say so plainly when a sheet has never reported one.
    assert "2026-08-06 22:24" in query["build"][0]
    assert "unknown" in query["build"][0]


# --- Wheel identity and the wheel-by-location panels -------------------------
# Two of the four R2 wheels are 20", so nothing may infer a wheel from its size.
# The old rule ("contains 21" -> the 21", else the 20" All-Terrain) was correct
# only while Performance was the sole shipping trim; these pin the replacement.


def test_wheel_label_identifies_all_four_wheels():
    from config import WHEEL_SHORT
    from ingest.parsing import wheel_label
    for raw, short in WHEEL_SHORT.items():
        assert wheel_label(raw) == short, raw
    # The distinguishing case: two different 20" wheels must not collide.
    twenties = [s for s in WHEEL_SHORT.values() if s.startswith('20"')]
    assert len(twenties) == len(set(twenties)) == 2


def test_wheel_label_tolerates_quote_and_spacing_drift():
    # The form emits a curly ”, but the sheet is hand-maintained, so a straight
    # quote, doubled space, or different case must still land on the same wheel.
    from config import WHEEL_SHORT
    from ingest.parsing import wheel_label
    raw = next(r for r in WHEEL_SHORT if "”" in r)
    want = WHEEL_SHORT[raw]
    assert wheel_label(raw.replace("”", '"')) == want
    assert wheel_label("  " + raw.upper() + " ") == want
    assert wheel_label(raw.replace(" ", "  ")) == want


def test_wheel_label_keeps_an_unknown_value_visible():
    # An unrecognized wheel keeps its own text rather than being folded into a
    # real one — a wrong-but-plausible label is worse than an obvious stranger.
    from ingest.parsing import wheel_label
    assert wheel_label("22” Moon Boots All-Weather") == "22” Moon Boots All-Weather"
    assert wheel_label("") == ""


def test_numeric_bins_order_by_value_and_bucket_missing():
    from render.charts import _NO_STATE_DATA, _numeric_bins
    vals = pd.Series([100.0, 900.0, 2000.0, 9000.0, float("nan")])
    labels, keys = _numeric_bins(vals, [500, 1500, 3500], " ft")
    # Ascending by value, never by volume, with the no-data bar last.
    assert keys == ["< 500 ft", "500–1,500 ft", "1,500–3,500 ft", "\u2265 3,500 ft",
                    _NO_STATE_DATA]
    assert list(labels) == keys[:4] + [_NO_STATE_DATA]
    # An empty bin is dropped rather than drawn as a gap.
    _, sparse = _numeric_bins(pd.Series([100.0, 9000.0]), [500, 1500, 3500], " ft")
    assert sparse == ["< 500 ft", "\u2265 3,500 ft"]


def test_wheels_by_location_panels_partition_the_cohort():
    # Every panel is a 100% stack over the same orders, so each bar's segments
    # must total 100% and each panel's n= must total the cohort. A row that
    # double-counts or drops an order would still look like a plausible chart.
    from collections import defaultdict
    from config import WHEEL_ORDER
    from render.charts import fig_wheels_by_location
    w21, w20 = WHEEL_ORDER[-1], WHEEL_ORDER[-2]
    df = pd.DataFrame({
        "lat": [40.0, 41.0, 42.0, 43.0, 44.0],
        "region": ["West", "West", "South", "Northeast", "Canada"],
        "wheels_short": [w21, w20, w20, w21, w20],
        "elev_ft": [6800.0, 100.0, 350.0, 1000.0, float("nan")],
        "temp_f": [45.1, 70.7, 62.4, 45.4, float("nan")],
        "urban_pct": [86.3, 91.1, 62.5, 93.9, float("nan")],
    })
    fig = fig_wheels_by_location(df)
    pct = defaultdict(lambda: defaultdict(float))
    n = defaultdict(lambda: defaultdict(int))
    for tr in fig.data:
        axis = tr.yaxis or "y"
        for y, x, cd in zip(tr.y, tr.x, tr.customdata):
            pct[axis][y] += x
            n[axis][y] += int(cd)
    assert len(pct) == 5, "expected five panels"
    for axis in pct:
        assert all(abs(v - 100.0) < 1e-6 for v in pct[axis].values()), axis
        assert sum(n[axis].values()) == len(df), axis
    # The row with no reference figures gets its own bar, not a dropped order.
    assert any("No state data" in y for y in n["y3"])


# --- Interior identity and the config-combination heatmaps -------------------
# "Black Crater" (Standard) and "Black Crater Signature" (Performance / Premium)
# are different interiors in pricing.yaml. Labels used to be built by stripping
# " Signature" off the sheet value, which merges them — the same failure the wheel
# size test had. These pin the replacement.


def _interior_frame():
    """A frame covering every catalogued interior against two paints, so a label
    collision between the two Black Craters would show up as a missing column.
    Carries the hover columns the VIN scatter reads, not just the grouping keys."""
    from config import COLOR_ORDER, INTERIOR_ORDER, WHEEL_ORDER
    paints = list(COLOR_ORDER[:2])
    rows = []
    for i, interior in enumerate(INTERIOR_ORDER):
        for j, paint in enumerate(paints):
            rows.append({"color": paint, "interior": interior,
                         "wheels_short": WHEEL_ORDER[-1 if j else -2],
                         "trim": "Performance", "vin_present": True,
                         "vin_seq": 1000 + 10 * i + j,
                         "user": "u%d%d" % (i, j), "buylease": "Purchase",
                         "vin_display": str(1000 + 10 * i + j),
                         "order_display": "Jun 15, 2026",
                         "est_display": "Aug 01, 2026",
                         "delivery_type": "explicit", "state": "IL"})
    return pd.DataFrame(rows)


def test_interior_labels_keep_the_two_black_craters_apart():
    from config import INTERIOR_ORDER, INTERIOR_SHORT
    plain = [i for i in INTERIOR_ORDER if i == "Black Crater"]
    sig = [i for i in INTERIOR_ORDER if i == "Black Crater Signature"]
    assert plain and sig, "both Black Crater variants should be catalogued"
    labels = [INTERIOR_SHORT[i] for i in INTERIOR_ORDER]
    assert len(labels) == len(set(labels)), "interior labels collide: %s" % labels


def test_interior_heatmap_columns_are_distinct_and_present_only():
    # One column per interior that has an order, labelled distinctly, and every
    # order counted exactly once.
    from config import INTERIOR_ORDER, INTERIOR_SHORT
    from render.charts import fig_color_interior_heatmap
    df = _interior_frame()
    h = fig_color_interior_heatmap(df).data[0]
    assert list(h.x) == [INTERIOR_SHORT[i] for i in INTERIOR_ORDER]
    assert len(set(h.x)) == len(h.x)
    assert sum(sum(r) for r in h.z) == len(df)
    # An interior nobody ordered gets no column at all.
    one = df[df["interior"] == INTERIOR_ORDER[0]]
    assert list(fig_color_interior_heatmap(one).data[0].x) == \
        [INTERIOR_SHORT[INTERIOR_ORDER[0]]]


def test_wheel_heatmap_covers_every_ordered_wheel():
    # This grid used to hardcode the two Performance wheels, so the other two
    # would have gone missing once Premium and Standard shipped.
    from render.charts import fig_color_wheel_heatmap
    df = _interior_frame()
    h = fig_color_wheel_heatmap(df).data[0]
    assert set(h.x) == set(df["wheels_short"].unique())
    assert sum(sum(r) for r in h.z) == len(df)


def test_vin_by_config_rows_carry_interior_and_stay_ordered():
    from config import INTERIOR_ORDER, INTERIOR_SHORT
    from render.charts import _paint_order, fig_vin_by_config
    df = _interior_frame()
    rows = list(fig_vin_by_config(df).layout.yaxis.ticktext)
    assert len(rows) == len(df), "one row per distinct configuration"
    for r in rows:
        assert len(r.split(" · ")) == 4, r
    # Rows sort by paint (most-ordered first) then wheel then interior, so a reader
    # scanning down sees a stable, meaningful sequence.
    paints = _paint_order(df)
    rank = {INTERIOR_SHORT[i]: n for n, i in enumerate(INTERIOR_ORDER)}
    keys = [(paints.index(r.split(" · ")[1]), r.split(" · ")[2],
             rank[r.split(" · ")[3]]) for r in rows]
    assert keys == sorted(keys)


def _paint_rank_frame():
    """Paints at deliberately unequal counts, including a tie, so both halves of the
    ranking rule are observable: popularity drives the order, and the palette's
    curated sequence only breaks ties.

    Counts are chosen so the popularity order CANNOT be mistaken for the palette
    order — Forest Green sits third in the palette but leads on count here.
    """
    from config import COLOR_ORDER
    plan = [(COLOR_ORDER[2], 5), (COLOR_ORDER[1], 3),
            (COLOR_ORDER[0], 1), (COLOR_ORDER[3], 1)]   # last two tie
    rows, n = [], 0
    for paint, count in plan:
        for _ in range(count):
            n += 1
            rows.append({
                "color": paint, "interior": "Black Crater Signature",
                "wheels_short": '21" Liquid Tungsten', "trim": "Performance",
                "buylease": "Purchase", "opted_spare": True,
                "r1_owner": "No", "r1_model": "",
                "vin_present": True, "vin_seq": 1000 + n,
                "order_date": pd.Timestamp("2026-06-%02d" % (10 + n % 15)),
                "delivery_est": pd.Timestamp("2026-08-%02d" % (1 + n % 20)),
                "delivery_min": pd.Timestamp("2026-08-%02d" % (1 + n % 20)),
                "delivery_max": pd.Timestamp("2026-08-%02d" % (3 + n % 20)),
                "user": "u%d" % n, "vin_display": str(1000 + n),
                "order_display": "Jun 15, 2026", "est_display": "Aug 01, 2026",
                "delivery_type": "explicit", "state": "IL", "region": "Midwest",
                "lat": 40.5, "lon": -89.0,
            })
    return pd.DataFrame(rows)


# The paints in _paint_rank_frame, ranked: by count (5, 3, 1, 1), then the palette
# order for the pair that ties. Deliberately NOT the palette's own sequence.
def _expected_paint_rank():
    from config import COLOR_ORDER
    return [COLOR_ORDER[2], COLOR_ORDER[1], COLOR_ORDER[0], COLOR_ORDER[3]]


def test_paint_order_ranks_by_count_then_palette_for_ties():
    from config import COLOR_ORDER
    from render.charts import _paint_order
    df = _paint_rank_frame()
    got = _paint_order(df)
    assert got == _expected_paint_rank(), got
    assert got != [c for c in COLOR_ORDER if c in got], (
        "the fixture must prove popularity beats the palette order")
    # The tie (1 vs 1) resolves to the palette's relative order, not by chance.
    tied = got[2:]
    assert tied == sorted(tied, key=COLOR_ORDER.index)
    # Repeated calls agree regardless of row order — what the daily build needs.
    assert all(_paint_order(df.sample(frac=1.0, random_state=n)) == got
               for n in range(5))


def test_every_paint_chart_uses_the_same_order():
    # Issue #58: the heatmap followed the palette's curated sequence, so Forest
    # Green sat near the top on 25 orders while Catalina Cove's 186 landed
    # mid-grid. Each of these read that sequence independently; they must now all
    # follow one popularity ranking, or a reader learns an order in §2 that fails
    # them in §3.
    from render.charts import (_paint_order, fig_color_wheel_heatmap,
                               fig_config_dashboard, fig_delivery_vs_vin,
                               fig_paint_by_location, fig_vin_vs_order)
    df = _paint_rank_frame()
    want = _paint_order(df)
    assert want == _expected_paint_rank()

    # §2 take-rate bars, and §3 heatmap rows (top-down: the y axis is reversed).
    assert list(fig_config_dashboard(df).data[0].x) == want
    assert list(fig_color_wheel_heatmap(df).data[0].y) == want

    # §8 / §9 scatter legends: one entry per paint × wheel, paints in rank order.
    for fig in (fig_vin_vs_order(df), fig_delivery_vs_vin(df)):
        seen = []
        for t in fig.data:
            paint = (t.name or "").split(" · ")[0]
            if paint in want and paint not in seen:
                seen.append(paint)
        assert seen == want, (fig.layout.title, seen)

    # §13 stack order — legend entries are the paints, first panel only.
    stacked = [t.name for t in fig_paint_by_location(df).data if t.showlegend]
    assert stacked == want, stacked


def test_stable_counts_breaks_ties_alphabetically():
    # The regression that matters: sort_values is not stable and value_counts
    # promises no order among equal counts, so tied categories used to come out
    # differently on every run and the deployed charts' rows reshuffled between
    # daily builds. Order must be (count, then name), repeatably.
    from render.charts import _by_volume, _stable_counts
    s = pd.Series(list("aaa") + ["zz", "mm", "bb"] * 2 + ["q"])
    got = _stable_counts(s.value_counts())
    assert list(got.index) == ["q", "bb", "mm", "zz", "a"]
    assert list(got.values) == [1, 2, 2, 2, 3]
    assert _by_volume(s) == list(got.index)
    # Repeated calls agree — the property the daily build depends on.
    assert all(_by_volume(s) == _by_volume(s.sample(frac=1.0, random_state=n))
               for n in range(5))


def test_interior_by_location_panels_partition_the_cohort():
    from config import INTERIOR_SHORT
    from render.charts import fig_interior_by_location
    df = _interior_frame().assign(
        lat=[40.0, 41.0, 42.0, 43.0, 44.0, 45.0],
        region=["West", "West", "South", "South", "Northeast", "Canada"])
    fig = fig_interior_by_location(df)
    from collections import defaultdict
    pct = defaultdict(lambda: defaultdict(float))
    n = defaultdict(lambda: defaultdict(int))
    for tr in fig.data:
        axis = tr.yaxis or "y"
        for y, x, cd in zip(tr.y, tr.x, tr.customdata):
            pct[axis][y] += x
            n[axis][y] += int(cd)
    assert len(pct) == 2, "all-orders row plus a region row, no state panel"
    for axis in pct:
        assert all(abs(v - 100.0) < 1e-6 for v in pct[axis].values()), axis
        assert sum(n[axis].values()) == len(df), axis
    # Legend carries the short labels, one entry per interior, no duplicates.
    names = [tr.name for tr in fig.data if tr.showlegend]
    assert names == [INTERIOR_SHORT[i] for i in _interior_frame()["interior"].unique()]
    assert len(names) == len(set(names))


# --- Cancellations (overrides.yaml deletions) --------------------------------
# These rows are otherwise valid — nothing in the data marks a cancellation — so
# the only evidence is the recorded reason. That makes silent failure the risk:
# a name that stops matching, or a cancelled order drifting back in via the
# reservations sheet.


def test_deletion_scoped_by_matcher_spares_a_replacement_order():
    # A username is not a stable key for an ORDER. Cancel, then order again under
    # the same name, and an unscoped deletion silently removes the NEW order —
    # the name still matches, so nothing is reported. The matcher is what turns
    # that silent suppression into a visible stale-entry report.
    from ingest.loaders import _apply_deletions
    replacement = pd.DataFrame({"orig_num": ["7"], "user": ["again"],
                                "order_raw": ["8/20/2026"]})
    spec = {"again": {"reason": "cancelled",
                      "match": {"order_raw": "6/20/2026"}}}
    mask, records, issues = _apply_deletions(replacement, spec, "order",
                                             ("order_raw",))
    assert not mask.any(), "the replacement order must survive"
    assert records == []
    assert len(issues) == 1 and "no longer matches" in issues[0][2]
    # The same entry still deletes the order it was written for.
    original = pd.DataFrame({"orig_num": ["7"], "user": ["again"],
                             "order_raw": ["6/20/2026"]})
    mask, records, issues = _apply_deletions(original, spec, "order",
                                             ("order_raw",))
    assert list(mask) == [True] and len(records) == 1 and issues == []


def test_deletion_matcher_requires_all_fields_and_fails_closed():
    # Several fields are ANDed, so a matcher narrows rather than widens. And a
    # field the frame doesn't carry counts as a non-match, not a skipped
    # condition — skipping would silently make the deletion broader than written.
    from ingest.loaders import _apply_deletions
    df = pd.DataFrame({"orig_num": ["1", "2"], "user": ["u", "u"],
                       "order_raw": ["6/1/2026", "6/1/2026"],
                       "vin_raw": ["1000", "2000"]})
    fields = ("order_raw", "vin_raw", "absent_col")
    spec = {"u": {"reason": "x",
                  "match": {"order_raw": "6/1/2026", "vin_raw": "2000"}}}
    mask, records, _ = _apply_deletions(df, spec, "order", fields)
    assert [r[0] for r in records] == ["2"], "both fields must match"
    # A valid-but-absent column spares every row instead of being ignored.
    spec = {"u": {"reason": "x", "match": {"absent_col": "anything"}}}
    mask, records, issues = _apply_deletions(df, spec, "order", fields)
    assert not mask.any() and records == []
    assert any("no longer matches" in d for _, _, d in issues)


def test_deletion_matcher_field_is_validated():
    from ingest.loaders import _apply_deletions
    df = pd.DataFrame({"orig_num": ["1"], "user": ["u"], "order_raw": ["6/1/2026"]})
    _, _, issues = _apply_deletions(
        df, {"u": {"reason": "x", "match": {"nope": "1"}}}, "order", ("order_raw",))
    assert any("unknown field 'nope'" in d for _, _, d in issues)


def test_cancelling_a_duplicated_name_takes_every_row():
    # Deletions run BEFORE the dedup. Run them after and the duplicates audit
    # reports "duplicate of #1 (kept)" about a row that was then cancelled —
    # an audit trail claiming a row survived when it didn't.
    from ingest.loaders import _apply_deletions
    df = pd.DataFrame({"orig_num": ["1", "2"], "user": ["dup", "dup"],
                       "order_raw": ["6/15/2026", "6/15/2026"]})
    mask, records, issues = _apply_deletions(df, {"dup": "cancelled"}, "order")
    assert list(mask) == [True, True], "a cancelled name can't half-survive"
    assert [r[0] for r in records] == ["1", "2"] and issues == []


def test_deletions_drop_every_matching_row_and_carry_the_reason():
    from ingest.loaders import _apply_deletions
    df = pd.DataFrame({"orig_num": ["1", "2", "3"],
                       "user": ["Alice", "BOB", "Carol"]})
    mask, records, issues = _apply_deletions(
        df, {"alice": "cancelled — https://example/1"}, "order")
    assert list(mask) == [True, False, False]
    assert records == [("1", "Alice", "order: cancelled — https://example/1")]
    assert issues == []
    # Case-insensitive both ways, and a duplicated name loses every row rather
    # than half-surviving.
    dupes = pd.DataFrame({"orig_num": ["1", "2"], "user": ["bob", "Bob"]})
    mask, records, _ = _apply_deletions(dupes, {"BOB": "gone"}, "order")
    assert list(mask) == [True, True] and len(records) == 2


def test_deletion_with_no_matching_row_is_reported():
    # Once the sheet drops the row itself the entry is dead weight; staying quiet
    # would keep it in the file forever.
    from ingest.loaders import _apply_deletions
    df = pd.DataFrame({"orig_num": ["1"], "user": ["Alice"]})
    mask, records, issues = _apply_deletions(df, {"Nobody": "cancelled"}, "order")
    assert not mask.any() and records == []
    assert len(issues) == 1 and "no matching order row" in issues[0][2]


def test_cancelled_order_does_not_resurface_as_a_reservation():
    # The subtle one: dropping someone from the orders cohort removes them from
    # `order_users`, which is exactly what the reservations sheet uses to exclude
    # people who have already ordered. Without the cancelled-users list they would
    # reappear as an outstanding reservation — a cancellation would ADD demand.
    import io as _io
    from config import RESERVATIONS_COLUMNS
    from ingest.loaders import load_reservations
    hdr = ["", "#", "Username", RESERVATIONS_COLUMNS["resv_raw"], "Location"]
    rows = [hdr, ["", "1", "quitter", "3/7/2024", "CA"],
            ["", "2", "holder", "3/7/2024", "TX"]]
    out = _io.StringIO()
    csv.writer(out).writerows([[""] * 5, ["", "", "Tracker Form"]] + rows)
    text = out.getvalue()

    # Baseline: nobody ordered, so both are outstanding reservations.
    resv, rep = load_reservations(text, set())
    assert set(resv["user"]) == {"quitter", "holder"}

    # With the order cancelled, the holder stays and the quitter does not return.
    resv, rep = load_reservations(text, set(), ["quitter"])
    assert set(resv["user"]) == {"holder"}
    assert rep["n_order_cancelled"] == 1
    assert any("order was cancelled" in d for _, _, d in rep["deletion_records"])


def test_reservation_deletions_are_labelled_by_their_own_sheet():
    # The two sheets have separate maps, and the record text names which sheet a
    # cancellation came from — one panel category serves both, so without the
    # label an order and a reservation cancellation would be indistinguishable.
    from config import DELETIONS_ORDERS, DELETIONS_RESV
    from ingest.loaders import _apply_deletions
    assert isinstance(DELETIONS_ORDERS, dict) and isinstance(DELETIONS_RESV, dict)
    frame = pd.DataFrame({"orig_num": ["1"], "user": ["Gone"]})
    _, as_resv, _ = _apply_deletions(frame, {"gone": "x"}, "reservation")
    _, as_order, _ = _apply_deletions(frame, {"gone": "x"}, "order")
    assert as_resv[0][2].startswith("reservation: ")
    assert as_order[0][2].startswith("order: ")
    assert as_resv[0][2] != as_order[0][2]


# --- Repeat-submission handling (dedup) --------------------------------------


def _dedupe_frame(rows):
    cols = ["orig_num", "user", "trim", "color", "wheels", "interior",
            "vin_raw", "delivery_raw", "order_raw"]
    return pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows])


IDENT = ("trim", "color", "wheels", "interior")
BUILD = dict(trim="Performance", color="Midnight", wheels='21" LT',
             interior="Black Crater Sig")


def test_same_build_merges_and_recovers_blank_fields():
    # The old rule kept whichever row had more cells filled and dropped the rest,
    # so a row holding the only copy of a VIN lost it. Blanks are now filled from
    # siblings instead.
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([
        dict(BUILD, orig_num="1", user="u", vin_raw="1500"),
        dict(BUILD, orig_num="2", user="u", delivery_raw="8/1/2026",
             order_raw="6/1/2026"),
    ])
    out, merged, builds, values = _dedupe_by_user(df, IDENT)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["vin_raw"] == "1500", "VIN from the sparser row must survive"
    assert row["delivery_raw"] == "8/1/2026"
    assert len(merged) == 1 and builds == [] and values == []


def test_conflicting_field_takes_the_latest_submission_and_is_flagged():
    # A later resubmission is a correction, so it wins — and the disagreement is
    # reported rather than resolved silently.
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([
        dict(BUILD, orig_num="10", user="u", delivery_raw="N/A", vin_raw="X7156"),
        dict(BUILD, orig_num="20", user="u", delivery_raw="Aug 28, 2026",
             vin_raw="07156"),
    ])
    out, _merged, _builds, values = _dedupe_by_user(df, IDENT)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["delivery_raw"] == "Aug 28, 2026", "the real date must beat N/A"
    assert row["vin_raw"] == "07156"
    assert row["orig_num"] == "10", "the earliest row survives as the entry"
    flagged = " ".join(d for _, _, d in values)
    assert "delivery_raw" in flagged and "vin_raw" in flagged
    assert "#20" in flagged


def test_different_build_under_one_username_is_kept_and_flagged():
    # A reconfigured order and a genuine second order are indistinguishable here,
    # so neither is guessed away.
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([
        dict(BUILD, orig_num="1", user="u"),
        dict(BUILD, orig_num="2", user="u", wheels='20" BS'),
    ])
    out, merged, builds, _values = _dedupe_by_user(df, IDENT)
    assert len(out) == 2, "two builds means two orders"
    assert merged == [] and len(builds) == 2
    assert all("different build" in d for _, _, d in builds)


def test_identical_rows_still_collapse():
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="u", vin_raw="9"),
                        dict(BUILD, orig_num="2", user="u", vin_raw="9")])
    out, merged, _builds, values = _dedupe_by_user(df, IDENT)
    assert len(out) == 1 and len(merged) == 1 and values == []


def test_username_case_differences_are_not_a_disagreement():
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="Bob", vin_raw="9"),
                        dict(BUILD, orig_num="2", user="bob")])
    out, _merged, _builds, values = _dedupe_by_user(df, IDENT)
    assert len(out) == 1 and values == [], "case is the grouping key, not a clash"


# --- Manual fix-ups (overrides) ----------------------------------------------


def test_override_on_one_row_applies_without_complaint():
    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([dict(BUILD, orig_num="7", user="solo",
                             order_raw="8/18/2026")])
    applied, issues = _apply_overrides(df, {"SOLO": {"order_raw": "9/15/2026"}})
    assert df.at[0, "order_raw"] == "9/15/2026", "username match is case-insensitive"
    assert len(applied) == 1 and issues == []


def test_override_targets_the_latest_of_several_orders_and_flags_it():
    # Dedup keeps differing builds under one username as separate orders, so an
    # override's target is ambiguous. It used to land on whichever row a dict
    # comprehension happened to keep, with nothing reported — a correction meant
    # for one order could silently edit the other.
    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([
        dict(BUILD, orig_num="201", user="FL5guy", order_raw="7/23/2026"),
        dict(BUILD, orig_num="296", user="FL5Guy", order_raw="8/18/2026",
             wheels='20" BS'),
    ])
    applied, issues = _apply_overrides(df, {"FL5Guy": {"order_raw": "9/15/2026"}})
    assert df.at[1, "order_raw"] == "9/15/2026", "latest submission gets the fix-up"
    assert df.at[0, "order_raw"] == "7/23/2026", "the earlier order is left alone"
    assert len(applied) == 1
    flagged = " ".join(d for _, _, d in issues)
    assert "2 separate orders" in flagged
    assert "#201" in flagged and "#296" in flagged, "both rows must be named"


def test_override_for_an_absent_username_is_reported():
    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="present")])
    applied, issues = _apply_overrides(df, {"ghost": {"order_raw": "9/1/2026"}})
    assert applied == [] and len(issues) == 1
    assert "no matching order row" in issues[0][2]


# --- Blank curation fields (issue #49) ---------------------------------------
# A key written with no value is null in YAML, and str(None) is the word "None".
# These entries used to land in the data as that literal string.


def test_blank_addition_fields_become_empty_not_the_word_none():
    from ingest.loaders import _apply_additions
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="insheet")])
    add, records, issues = _apply_additions(df, {
        "forumonly": {"order_raw": "9/15/2026", "loc_raw": "TX",
                      "color": None, "wheels": None, "r1_model": None},
    })
    row = add.iloc[0]
    for field in ("color", "wheels", "r1_model"):
        assert row[field] == "", (field, repr(row[field]))
    assert row["order_raw"] == "9/15/2026"
    assert issues == [], "blanks are normal in an addition, not a problem"
    # The audit line lists what was actually supplied, not the empty placeholders.
    detail = records[0][2]
    assert "loc_raw" in detail and "order_raw" in detail
    assert "color" not in detail and "wheels" not in detail


def test_blank_r1_model_does_not_flip_a_self_reported_no_to_yes():
    # The symptom that made #49 visible on the dashboard: reconcile_r1_owner trusts
    # a named model over the Yes/No gate, and the literal "None" looked like a named
    # model — so "No" became "Yes" and the R1 panel grew a "Yes"/"None" segment.
    from ingest.loaders import _apply_additions
    from ingest.parsing import reconcile_r1_owner
    coerced, why = reconcile_r1_owner("No", "None")
    assert coerced == "Yes" and why is not None, (
        "guard: a literal 'None' does read as a named model — which is exactly why "
        "the curation layer must never produce one")
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="insheet")])
    add, _, _ = _apply_additions(df, {
        "partialguy": {"r1_owner": "No", "r1_model": None},
    })
    owner, issue = reconcile_r1_owner(add.iloc[0]["r1_owner"],
                                      add.iloc[0]["r1_model"])
    assert owner == "No", owner
    assert issue is None


def test_blank_override_field_is_ignored_rather_than_clearing_the_sheet():
    # An override EDITS an existing row, so honouring a blank would erase what the
    # sheet says on the strength of an empty line. It is skipped and reported.
    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([dict(BUILD, orig_num="9", user="u",
                             delivery_raw="8/1/2026", vin_raw="1234")])
    applied, issues = _apply_overrides(df, {
        "u": {"delivery_raw": None, "vin_raw": "5678"},
    })
    assert df.at[0, "delivery_raw"] == "8/1/2026", "must not be cleared"
    assert df.at[0, "vin_raw"] == "5678", "the real value still applies"
    assert len(applied) == 1
    assert any("left blank" in d for _, _, d in issues), issues


def test_blank_deletion_reason_is_reported():
    from ingest.loaders import _apply_deletions
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="gone")])
    mask, records, issues = _apply_deletions(df, {"gone": None}, "order",
                                             ("orig_num", "user"))
    assert bool(mask.iloc[0]) is True, "the row is still deleted"
    assert "None" not in records[0][2], records[0][2]
    assert any("no reason recorded" in d for _, _, d in issues), issues


def test_an_owner_who_named_no_model_still_counts_as_an_owner():
    # "No model given" means two different things depending on the gate, and they
    # used to share one "No / unspecified" segment — which inside the Yes bar read
    # as a "No" contradicting its own bar. The owner is trusted either way, so the
    # Yes bar's total must be every owner.
    from render.charts import _MODEL_UNSPECIFIED, _NO_R1, fig_config_dashboard
    cols = dict(color="Esker Silver", interior="Black Crater Signature",
                wheels_short='21" Liquid Tungsten', trim="Performance",
                buylease="Purchase", opted_spare=True)
    df = pd.DataFrame(
        [dict(cols, r1_owner="Yes", r1_model="R1T") for _ in range(4)]
        + [dict(cols, r1_owner="Yes", r1_model="") for _ in range(3)]
        + [dict(cols, r1_owner="No", r1_model="") for _ in range(9)])
    seg = {t.name: list(t.y) for t in fig_config_dashboard(df).data
           if getattr(t, "x", None) and tuple(t.x) == ("Yes", "No") and t.name}
    assert seg["R1T"] == [4, 0]
    assert seg[_MODEL_UNSPECIFIED] == [3, 0], "an owner with no model stays an owner"
    assert seg[_NO_R1] == [0, 9], "a non-owner is not 'unspecified'"
    # The two non-answers must not collapse into one segment again.
    assert _MODEL_UNSPECIFIED != _NO_R1
    owners = sum(v[0] for v in seg.values())
    assert owners == 7, "the Yes bar totals every owner, model named or not"


def test_yes_no_panels_keep_a_fixed_order_and_drop_blanks():
    # Purchase before Lease and Yes before No read as a sequence, so which is larger
    # shouldn't decide the order — by count they'd also swap places between builds as
    # the numbers move. Unanswered rows sit out rather than forming a blank bar (41
    # of 565 never answered purchase-vs-lease, which outnumbered Lease itself).
    from render.charts import _ordered_counts, fig_config_dashboard
    s = pd.Series(["Lease"] * 9 + ["Purchase"] * 2 + ["Weird"])
    got = _ordered_counts(s, ("Purchase", "Lease"))
    assert list(got.index) == ["Purchase", "Lease", "Weird"], list(got.index)
    assert list(got.values) == [2, 9, 1], "counts follow the labels, not the order"
    # An unanticipated answer is appended, never silently dropped.
    assert "Weird" in got.index

    cols = dict(color="Esker Silver", interior="Black Crater Signature",
                wheels_short='21" Liquid Tungsten', trim="Performance",
                opted_spare=True, r1_owner="Yes", r1_model="R1T")
    df = pd.DataFrame(
        [dict(cols, buylease="Purchase") for _ in range(3)]
        + [dict(cols, buylease="Lease") for _ in range(5)]
        + [dict(cols, buylease="", r1_owner="") for _ in range(2)])
    panels = {tuple(t.x): t for t in fig_config_dashboard(df).data
              if getattr(t, "x", None) and isinstance(t.x, tuple)}
    assert ("Purchase", "Lease") in panels, list(panels)
    buylease = panels[("Purchase", "Lease")]
    assert list(buylease.y) == [3, 5], "Purchase leads despite Lease being larger"
    assert not any("" in k or "Blank" in k for k in panels), list(panels)


def test_an_unreported_build_is_left_out_of_the_config_charts():
    # An order whose build was never reported carries no choice to plot, so the
    # configuration charts cover the orders that did report the option they chart.
    # Taking the CATEGORY out while leaving the ROWS in would be the subtle bug: the
    # 100%-stacked panels divide by each bar's own total, so the stack would quietly
    # stop adding up to 100.
    from render.charts import (_paint_order, fig_color_wheel_heatmap,
                               fig_config_dashboard, fig_paint_by_location)
    df = _paint_rank_frame()
    blank = df.iloc[[0]].copy()
    blank["user"] = "unreported"
    blank["color"] = ""
    blank["wheels_short"] = ""
    blank["interior"] = ""
    df = pd.concat([df, blank], ignore_index=True)

    assert "" not in _paint_order(df), "a blank is not a paint"
    bars = fig_config_dashboard(df).data[0]
    assert "" not in list(bars.x) and "Unknown" not in list(bars.x)
    assert sum(int(v) for v in bars.y) == len(df) - 1, "the blank row is not counted"

    h = fig_color_wheel_heatmap(df).data[0]
    assert "" not in list(h.y) and "Unknown" not in list(h.y)
    assert sum(sum(r) for r in h.z) == len(df) - 1

    # Every 100%-stacked bar must still reach 100 after the exclusion.
    for t in [t for t in fig_paint_by_location(df).data if t.orientation == "h"]:
        assert "" != t.name and t.name != "Unknown"
    totals = {}
    for t in [t for t in fig_paint_by_location(df).data if t.orientation == "h"]:
        for label, pct in zip(t.y, t.x):
            totals[label] = totals.get(label, 0) + pct
    assert all(abs(v - 100) < 0.51 for v in totals.values()), totals


def test_an_unreported_build_is_unpriced_not_priced_at_base():
    # Excluded from the charts, but NOT quietly priced: skipping the upcharge for a
    # blank paint/wheel/interior priced the order as though the no-cost option had
    # been chosen, i.e. at base — a confidently wrong number feeding the price stats.
    from ingest.pricing import price_order
    full, _ = price_order(trim="Performance", launch="Yes",
                          color="Catalina Cove", wheels='21” Liquid Tungsten '
                          'All-Season', interior="Coastal Cloud Signature")
    assert full["price"] is not None
    partial, issues = price_order(trim="Performance", launch="Yes",
                                  color="", wheels="", interior="")
    assert partial["price"] is None, partial["price"]
    assert len(issues) == 3, issues
    assert all("not reported" in i for i in issues), issues


def _run_all():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        else:
            passed += 1
            print("PASS %s" % name)
    print("-" * 40)
    print("%d passed, %d failed (of %d)" % (passed, failed, len(tests)))
    return failed


# --- Likely entry errors (#68) -----------------------------------------------


def test_trend_z_scores_against_a_local_trend():
    from ingest.outliers import trend_z
    x = np.arange(100.0)
    y = 100 * x + np.random.default_rng(1).normal(0, 50, 100)   # a climbing trend
    y[50] = 100 * 50 - 2000                                     # far below its cohort
    z, med = trend_z(x, y, cohort=21)
    assert z[50] < -10, z[50]
    # Everything else is near its cohort, however far up the trend it sits: the
    # check follows the climb rather than comparing with one global median.
    assert np.nanmax(np.abs(np.delete(z, 50))) < 4, np.nanmax(np.abs(np.delete(z, 50)))
    assert abs(med[90] - 9000) < 300
    # Fewer points than one cohort: nothing to compare against.
    z, med = trend_z(x[:10], y[:10], cohort=21)
    assert np.isnan(z).all() and np.isnan(med).all()


def _suspects_input():
    """Orders on a trend: VIN climbs 100/day with order date, delivery ~30 days
    after order. The VIN scatter (sd 800) is about the real data's, so the held-back
    case below scores like the real ones do. Tests append the odd rows."""
    T = pd.Timestamp
    rng = np.random.default_rng(7)
    rows = []
    for k in range(80):
        order = T("2026-07-01") + pd.Timedelta(days=k)
        est = order + pd.Timedelta(days=30 + (k % 5))
        rows.append(dict(user="u%d" % k, vin_present=True,
                         vin_seq=float(round(1000 + 100 * k + rng.normal(0, 800))),
                         order_date=order, delivery_type="explicit",
                         delivery_est=est, delivery_min=est, delivery_max=est))
    return pd.DataFrame(rows)


def _with(df, **row):
    T = pd.Timestamp
    base = dict(vin_present=True, delivery_type="explicit")
    base.update(row)
    for c in ("order_date", "delivery_est"):
        base[c] = T(base[c]) if base.get(c) else pd.NaT
    base["delivery_min"] = base["delivery_max"] = base["delivery_est"]
    return pd.concat([df, pd.DataFrame([base])], ignore_index=True)


def test_find_suspects_flags_only_the_implausible_direction():
    from ingest.outliers import find_suspects
    df = _suspects_input()
    # A misread date: VIN 6,000 (cars delivered around 9/20), but a firm date of
    # 8/1, before cars with nearby VINs were built.
    df = _with(df, user="early", vin_seq=6000.0, order_date="2026-07-28",
               delivery_est="2026-08-01")
    # A held-back car: low VIN, late order, late delivery. Innocent, not flagged.
    df = _with(df, user="heldback", vin_seq=3000.0, order_date="2026-09-10",
               delivery_est="2026-10-10")
    # A VIN with an extra digit.
    df = _with(df, user="digit", vin_seq=55000.0, order_date="2026-08-10",
               delivery_est="2026-09-12")
    # An estimate before its own order date: no cohort needed.
    df = _with(df, user="before", vin_seq=np.nan, vin_present=False,
               order_date="2026-08-18", delivery_est="2026-08-01")
    vin, delivery = find_suspects(df)
    def who(found):
        return sorted(df.loc[list(found), "user"])
    assert who(vin) == ["digit"], who(vin)
    assert who(delivery) == ["before", "early"], who(delivery)
    early = df.index[df["user"] == "early"][0]
    assert "nearby VINs" in delivery[early]
    # The extra-digit VIN is judged first and left out of the delivery check, so
    # its (fine) delivery date isn't flagged for sitting next to the wrong VINs.
    assert df.index[df["user"] == "digit"][0] not in delivery


def test_find_suspects_honours_verified_values():
    from ingest.outliers import find_suspects
    df = _with(_suspects_input(), user="Early", vin_seq=6000.0,
               order_date="2026-07-28", delivery_est="2026-08-01")
    vin, delivery = find_suspects(df, {"early": ["delivery_raw"]})
    assert not delivery and not vin
    # Verifying the VIN doesn't vouch for the date.
    _, delivery = find_suspects(df, {"early": ["vin_raw"]})
    assert len(delivery) == 1


def test_find_suspects_with_no_firm_dated_vins():
    # Nothing to compare: the cohort checks must find nothing rather than fail.
    # An empty frame indexed with an empty LIST loses its columns in pandas, which
    # broke cleaning as of an early date once curation was dated (#82).
    from ingest.outliers import find_suspects
    df = _suspects_input()
    df["vin_present"] = False
    assert find_suspects(df) == ({}, {})
    assert find_suspects(df.iloc[0:0]) == ({}, {})


def test_find_suspects_needs_a_cohort():
    from ingest.outliers import find_suspects
    df = _with(_suspects_input().head(10), user="early", vin_seq=5000.0,
               order_date="2026-07-05", delivery_est="2026-07-06")
    assert find_suspects(df) == ({}, {}), "too few orders to judge against"


def test_a_set_aside_estimate_is_unknown_everywhere():
    # End to end: a contradicted estimate must not count as delivered (the misread
    # "8-12" did), must be listed once as set aside, and must not ALSO be reported
    # as unparseable just because it now reads as unknown.
    from config import ORDERS_HEADERS
    from ingest.loaders import load_and_clean
    header = _orders_header()
    text = _orders_csv(header)
    lines = text.splitlines()
    row = next(csv.reader([lines[-1]]))
    row[header.index(ORDERS_HEADERS["delivery_raw"])] = "6/1/2026"   # before 6/15
    out = io.StringIO()
    csv.writer(out).writerow(row)
    text = "\n".join(lines[:-1]) + "\n" + out.getvalue()
    df, report, _ = load_and_clean(text, {"label": "test orders sheet"})
    r = df[df["user"] == "tester"].iloc[0]
    assert r["delivery_type"] == "unknown" and pd.isna(r["delivery_est"])
    assert not r["delivered_inferred"]
    listed = [m for _, u, m in report["quality"]["entry_errors"] if u == "tester"]
    assert len(listed) == 1 and "before the order date" in listed[0], listed
    aside = report["sanitized"]["Likely entry errors set aside"]
    assert listed == [m for _, u, m in aside if u == "tester"]
    assert not [u for _, u, _ in report["quality"]["unparseable"] if u == "tester"]
    assert report["n_set_aside_delivery"] >= 1


# --- Snapshot replay (#81) -----------------------------------------------------

_HF = ["orig_num", "user", "order_raw", "color", "delivery_raw"]


def _snap(day, *rows):
    """A synthetic orders snapshot: (timestamp, fields, rows), "#" numbered in order."""
    from datetime import datetime
    return (datetime(2026, 9, day), _HF,
            [[str(n)] + list(r) for n, r in enumerate(rows, start=1)])


def test_replay_keys_follow_the_order_not_the_row_number():
    from ingest.history import replay
    a = ("Alice", "8/1/2026", "Midnight", "")
    b = ("Bob", "8/2/2026", "Borealis", "")
    b2 = ("bob", "8/20/2026", "Launch Green", "")       # Bob's second order
    h = replay([_snap(1, a, b), _snap(2, a, b, b2),
                _snap(3, b, b2)], "orders")                  # Alice's row deleted
    keys = dict(zip(h.orders["key"], h.orders["user"]))
    assert sorted(keys) == ["alice", "bob", "bob#2"], keys
    # Deleting Alice renumbered Bob's rows, but keys are by order, not by "#".
    o = h.orders.set_index("key")
    assert o.at["bob", "orig_num"] == "1" and o.at["bob#2", "orig_num"] == "2"
    assert str(o.at["alice", "gone_after"].date()) == "2026-09-03"
    assert o["gone_after"].isna().sum() == 2


def test_replay_matches_a_users_rows_by_content_after_a_deletion():
    # A user with two rows loses the first: the survivor keeps ITS key rather
    # than sliding into the deleted one's, which is what "#" did.
    from ingest.history import replay
    first = ("u", "8/1/2026", "Midnight", "")
    second = ("u", "9/1/2026", "Borealis", "")
    h = replay([_snap(1, first, second), _snap(2, second)], "orders")
    o = h.orders.set_index("key")
    assert pd.notna(o.at["u", "gone_after"]) and pd.isna(o.at["u#2", "gone_after"])


def test_replay_starts_a_new_order_when_nothing_agrees():
    # Same username, one row swapped for an unrelated one in the same snapshot:
    # below the agreement floor, so it is a new order, not an edit of the old.
    from ingest.history import replay
    h = replay([_snap(1, ("u", "8/1/2026", "Midnight", "4-8 weeks")),
                _snap(2, ("u", "9/15/2026", "Borealis", "Nov"))], "orders")
    assert sorted(h.orders["key"]) == ["u", "u#2"]


def test_replay_folds_case_variants_and_records_time_bounds():
    from ingest.history import field_changes, replay, summary
    h = replay([_snap(1, ("Kim", "8/1/2026", "Midnight", "4-8 weeks")),
                _snap(2, ("Kim", "8/1/2026", "Midnight", "4-8 weeks")),
                _snap(3, ("kim", "8/1/2026", "Midnight", "9/30/2026"))], "orders")
    assert list(h.orders["key"]) == ["kim"], "case is not a new person"
    runs = h.events[(h.events["field"] == "delivery_raw")]
    got = [(v, f.day, last.day, None if pd.isna(a) else a.day)
           for v, f, last, a in zip(runs["value"], runs["first_seen"],
                                    runs["last_seen"], runs["after"])]
    # The first value held on or before 9/1 (left-censored); the change happened
    # after the 9/2 snapshot and by the 9/3 one — that interval is all we know.
    assert got == [("4-8 weeks", 1, 2, None), ("9/30/2026", 3, 3, 2)], got
    ch = field_changes(h)
    assert list(ch["field"]) == ["delivery_raw"]
    sm = summary(h)
    assert (sm["orders"], sm["changed_orders"], sm["change_events"],
            sm["field_changes"]) == (1, 1, 1, 1)


def test_replay_counts_one_event_when_several_fields_change_together():
    from ingest.history import replay, summary
    h = replay([_snap(1, ("u", "8/1/2026", "Midnight", "")),
                _snap(2, ("u", "8/1/2026", "Borealis", "9/30/2026"))], "orders")
    sm = summary(h)
    assert (sm["change_events"], sm["field_changes"]) == (1, 2), sm


def test_a_new_order_is_bounded_by_the_snapshot_before_it():
    from ingest.history import replay
    h = replay([_snap(1, ("a", "8/1/2026", "Midnight", "")),
                _snap(5, ("a", "8/1/2026", "Midnight", ""),
                      ("b", "9/3/2026", "Borealis", ""))], "orders")
    o = h.orders.set_index("key")
    assert pd.isna(o.at["a", "after"]) and o.at["b", "after"].day == 1
    assert o.at["b", "first_seen"].day == 5


def test_snapshot_history_reads_caches_like_the_loader(tmp_dir=None):
    # End to end over real files: the replay reads a cache exactly as
    # load_and_clean does (same header location and by-name mapping).
    import tempfile

    from config import ORDERS_HEADERS, ORDERS_SLUG
    from ingest.history import orders_history, snapshot_files
    from ingest.schema_check import read_sheet
    text = _orders_csv(_orders_header())
    fields, rows = read_sheet(text, ORDERS_HEADERS, [], "test")
    assert fields == list(ORDERS_HEADERS)
    assert [r[fields.index("user")] for r in rows] == ["tester"]
    with tempfile.TemporaryDirectory() as d:
        for ts in ("20260901-120000", "20260902-120000"):
            with open(os.path.join(d, "%s_%s.csv" % (ORDERS_SLUG, ts)), "w") as fh:
                fh.write(text)
        with open(os.path.join(d, "unrelated.csv"), "w") as fh:
            fh.write("x")
        assert len(snapshot_files(ORDERS_SLUG, d)) == 2
        h = orders_history(d)
    assert list(h.orders["key"]) == ["tester"] and len(h.snapshots) == 2
    assert h.events["last_seen"].dt.day.eq(2).all(), "unchanged values extend their run"


# --- Curation v2: provenance, effective dates, order keys (#82) ----------------


def test_curation_meta_is_split_from_what_an_entry_edits():
    from ingest.curation import split
    e = split("u", {"source": ["https://a", "https://b"], "as_of": "2026-09-01",
                    "reason": "posted", "delivery_raw": "9/30/2026"})
    assert e.body == {"delivery_raw": "9/30/2026"}
    assert e.source == ["https://a", "https://b"] and str(e.as_of) == "2026-09-01"
    # A YAML date and a plain string read the same.
    assert split("u", {"as_of": date(2026, 9, 1)}).as_of == e.as_of
    # Non-mapping entries (a plain deletion reason, a verified list) carry none.
    assert split("u", "cancelled").body == "cancelled"
    # #99: checked and dates are meta too, never sheet fields.
    e = split("u", {"as_of": "2026-08-03", "checked": "2026-08-23",
                    "dates": {"vin_assigned": "2026-08-12"}, "vin_raw": "1500"})
    assert e.body == {"vin_raw": "1500"}
    assert str(e.reviewed) == "2026-08-23"
    assert str(e.dates["vin_assigned"]) == "2026-08-12"
    assert str(split("u", {"as_of": "2026-08-03"}).reviewed) == "2026-08-03"


def test_curation_v2_requires_provenance_and_v1_does_not():
    from ingest.curation import CurationError, check
    today = date(2026, 10, 3)
    bare = {"overrides": {"u": {"vin_raw": "1"}}}
    check(1, bare, today)                         # the old format: nothing required
    try:
        check(2, bare, today)
        raise AssertionError("v2 must refuse an entry without provenance")
    except CurationError as exc:
        assert "no source" in str(exc) and "no as_of" in str(exc)
    ok = {"overrides": {"u": {"source": "https://x", "as_of": "2026-09-01",
                              "vin_raw": "1"},
                        "v": {"source": "inferred — typo'd year", "as_of": "2026-09-01",
                              "vin_raw": "2"}}}
    check(2, ok, today)
    for bad, why in (({"source": "a forum post", "as_of": "2026-09-01"}, "neither"),
                     ({"source": "https://x", "as_of": "2026-12-01"}, "future")):
        try:
            check(2, {"additions": {"w": bad}}, today)
            raise AssertionError(why)
        except CurationError as exc:
            assert why in str(exc), exc


def test_a_dates_only_entry_needs_no_as_of():
    # It overrides nothing, so there is nothing for as_of to anchor.
    from ingest.curation import CurationError, check
    today = date(2026, 10, 4)
    dates_only = {"overrides": {"jediknight": {
        "source": "https://x", "dates": {"delivery_scheduled": "2026-08-04"}}}}
    check(2, dates_only, today)
    # An entry that overrides a field still needs one.
    try:
        check(2, {"overrides": {"u": {"source": "https://x", "vin_raw": "1500",
                                      "dates": {"vin_assigned": "2026-08-04"}}}},
              today)
        raise AssertionError("an override without as_of must be refused")
    except CurationError as exc:
        assert "no as_of" in str(exc)
    # A source is still required.
    try:
        check(2, {"overrides": {"u": {"dates": {"vin_assigned": "2026-08-04"}}}},
              today)
        raise AssertionError("a dates-only entry still needs a source")
    except CurationError as exc:
        assert "no source" in str(exc)


def test_override_by_order_key_targets_one_of_several_orders():
    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([
        dict(BUILD, orig_num="201", user="FL5guy", order_raw="7/23/2026"),
        dict(BUILD, orig_num="296", user="FL5Guy", order_raw="8/18/2026",
             wheels='20" BS'),
    ])
    df["key"] = ["fl5guy", "fl5guy#2"]
    applied, issues = _apply_overrides(df, {"fl5guy#2": {"order_raw": "9/15/2026"}})
    assert df.at[1, "order_raw"] == "9/15/2026" and len(applied) == 1
    assert issues == [], "a key is exact, so there is no ambiguity to report"
    # The plain username still works, and its warning now names the keys.
    _, issues = _apply_overrides(df, {"FL5Guy": {"order_raw": "9/16/2026"}})
    assert "fl5guy, fl5guy#2" in issues[0][2], issues
    _, issues = _apply_overrides(df, {"fl5guy#3": {"order_raw": "9/1/2026"}})
    assert "no order with key fl5guy#3" in issues[0][2]


def test_override_flags_redundant_and_outdated_entries():
    from datetime import datetime

    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="a", vin_raw="1500",
                             delivery_raw="9/30/2026")])
    df["key"] = ["a"]
    # The sheet now says what the override says: nothing to apply, and it can go.
    applied, issues = _apply_overrides(df, {"a": {"vin_raw": "1500"}})
    assert applied == [] and "can be removed" in issues[0][2]
    # The sheet changed AFTER the override was written: it may be out of date.
    changed = {("a", "delivery_raw"): ("9/30/2026", datetime(2026, 9, 20),
                                       datetime(2026, 9, 19))}
    entry = {"a": {"as_of": "2026-09-10", "delivery_raw": "9/25/2026"}}
    applied, issues = _apply_overrides(df, entry, changed=changed)
    assert len(applied) == 1 and "after this override" in issues[0][2], issues
    assert "between 2026-09-19 and 2026-09-20" in issues[0][2]
    # A change on the override's own day is not flagged: it may be what the
    # override was responding to.
    df.at[0, "delivery_raw"] = "9/30/2026"
    same_day = {"a": {"as_of": "2026-09-19", "delivery_raw": "9/25/2026"}}
    _, issues = _apply_overrides(df, same_day, changed=changed)
    assert issues == [], issues


def test_dedupe_ignores_order_keys():
    # Two submissions of one build are one order; their row keys differ by
    # construction and are not a disagreement.
    from ingest.loaders import _dedupe_by_user
    df = _dedupe_frame([dict(BUILD, orig_num="1", user="u", vin_raw="9"),
                        dict(BUILD, orig_num="2", user="u", vin_raw="9")])
    df["key"] = ["u", "u#2"]
    out, _merged, _builds, values = _dedupe_by_user(df, IDENT)
    assert len(out) == 1 and values == [], values


def test_load_and_clean_keys_rows_without_a_history():
    # Without keys from the history, one snapshot is replayed on its own.
    row = _one_order(_orders_csv(_orders_header()))
    assert row["key"] == "tester"


def _migrate(text):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migrate_curation", os.path.join(os.path.dirname(_SRC), "tools",
                                         "migrate_curation.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dates = {n: date(2026, 9, n % 28 + 1) for n in range(1, 200)}
    return mod, mod.migrate(text, dates)


_MIGRATE_SAMPLE = """# header comment
overrides:
  # delivery update
  # https://example.com/post-1
  alice:
    delivery_raw: "9/30/2026"
  # probable typo, no link
  bob:
    vin_raw: "1500"
additions:
  # order: https://example.com/post-2
  # https://example.com/post-3
  carol:
    loc_raw: "CA"
deletions:
  orders:
    # https://example.com/post-4
    dave:
      reason: "cancelled"
      match:
        order_raw: "8/1/2026"
verified:
  erin: [vin_raw]
"""


def test_migration_lifts_urls_and_keeps_everything_else():
    import yaml
    mod, (new, migrated, unresolved) = _migrate(_MIGRATE_SAMPLE)
    data = yaml.safe_load(new)
    assert data["overrides"]["alice"]["source"] == "https://example.com/post-1"
    assert data["additions"]["carol"]["source"] == ["https://example.com/post-2",
                                                    "https://example.com/post-3"]
    assert data["deletions"]["orders"]["dave"]["source"] == "https://example.com/post-4"
    assert data["verified"]["erin"]["fields"] == ["vin_raw"]
    assert all("as_of" in e for sec in ("overrides", "additions")
               for e in data[sec].values())
    assert "source" not in data["overrides"]["bob"]
    assert unresolved == [("overrides", "bob"), ("verified", "erin")], unresolved
    assert len(migrated) == 3
    # The URL comments are lifted, every other comment and label survives.
    assert "# delivery update" in new and "# probable typo, no link" in new
    assert "# https://example.com/post-1" not in new
    assert "post-2  # order" in new
    # Semantics unchanged, and a second run adds nothing.
    assert mod._strip_meta(data) == mod._strip_meta(yaml.safe_load(_MIGRATE_SAMPLE))
    again, _, _ = mod.migrate(new, {})
    assert again == new


# --- Cross-snapshot sanity checks (#83) ---------------------------------------

# A fixed configuration rides along, as in the real sheet, so a row whose date
# changes still clearly matches its order.
_TF = ["orig_num", "user", "order_raw", "vin_raw", "delivery_raw", "trim", "color",
       "wheels", "interior"]
_TCONF = ["Performance", "Midnight", '21" LT', "Black Crater Signature"]


def _tsnap(day, *rows):
    from datetime import datetime
    return (datetime(2026, 9, day), _TF,
            [[str(n), *r, *_TCONF] for n, r in enumerate(rows, start=1)])


def _timeline(*snaps, curated=None):
    from ingest.history import replay
    from ingest.timeline import timeline_issues
    return timeline_issues(replay(list(snaps), "orders"), curated)


def test_vin_changes_ignore_formatting_and_flag_reverts():
    out = _timeline(
        _tsnap(1, ("a", "8/1/2026", "", ""), ("b", "8/1/2026", "X1500", ""),
               ("c", "8/1/2026", "2000", "")),
        _tsnap(2, ("a", "8/1/2026", "1200", ""), ("b", "8/1/2026", "01500", ""),
               ("c", "8/1/2026", "2100", "")),
        _tsnap(3, ("a", "8/1/2026", "1200", ""), ("b", "8/1/2026", "01500", ""),
               ("c", "8/1/2026", "2000", "")))["vin_changes"]
    # a: first VIN set (not a change). b: X1500 -> 01500 is de-obfuscation.
    assert [u for _, u, _ in out] == ["c"], out
    assert "2000 → 2100 → 2000" in out[0][2] and "wrong row" in out[0][2]
    assert "between 2026-09-02 and 2026-09-03" in out[0][2], out[0][2]


def test_order_date_changes_compare_dates_not_text():
    out = _timeline(
        _tsnap(1, ("a", "8/19/2024", "", ""), ("b", "7/7/2026", "", "")),
        _tsnap(2, ("a", "8/19/2026", "", ""), ("b", "07/07/2026", "", "")))
    recs = out["order_date_changes"]
    assert [u for _, u, _ in recs] == ["a"], "07/07/2026 is the same date"
    assert "8/19/2024 → 8/19/2026" in recs[0][2]


def test_firm_to_vague_lists_only_estimates_still_vague():
    out = _timeline(
        _tsnap(1, ("a", "8/1/2026", "", "9/20/2026"),
               ("b", "8/1/2026", "", "9/20/2026")),
        _tsnap(2, ("a", "8/1/2026", "", "TBD"), ("b", "8/1/2026", "", "Delayed")),
        _tsnap(3, ("a", "8/1/2026", "", "TBD"), ("b", "8/1/2026", "", "10/5/2026")))
    recs = out["firm_to_vague"]
    assert [u for _, u, _ in recs] == ["a"], "b got a new firm date: resolved"
    assert "'9/20/2026' → 'TBD'" in recs[0][2]


def test_left_sheet_and_curated_fields():
    out = _timeline(
        _tsnap(1, ("a", "8/1/2026", "1000", ""), ("b", "8/1/2026", "1100", "")),
        _tsnap(2, ("b", "8/1/2026", "1150", "")), curated={("b", "vin_raw")})
    assert [u for _, u, _ in out["left_sheet"]] == ["a"]
    assert "gone by 2026-09-02" in out["left_sheet"][0][2]
    assert out["vin_changes"] == [], "an override already sets b's VIN"


# --- Published data contract (#84) --------------------------------------------


def test_dimensions_are_the_yaml_published_as_is():
    import json

    import yaml

    from config import _CONF
    from ingest.contract import dimensions
    with open(_CONF / "dimensions.yaml") as fh:
        raw = yaml.safe_load(fh)["dimensions"]
    d = dimensions()
    assert d["dimensions"] == raw, "published unchanged, nothing assembled"
    json.dumps(d)                                   # publishable as-is
    csv_cols = {"state", "region", "buylease", "trim", "color", "wheels_short",
                "interior", "opted_autonomy", "opted_tow", "opted_spare",
                "delivery_type", "delivered_inferred", "r1_owner", "r1_model"}
    assert {x["column"] for x in raw.values()} == csv_cols
    for name, dim in raw.items():
        assert dim["label"] and dim["order"] in ("count", "fixed"), name
        miss = dim.get("missing")
        if miss and miss["policy"] == "category":
            assert miss["value"] in [c["value"] for c in dim["categories"]], name
        for c in dim["categories"]:
            if "color" in c:
                assert re.fullmatch(r"#[0-9a-fA-F]{6}", c["color"]), (name, c)


def test_chart_constants_are_views_of_dimensions():
    from config import (COLOR_HEX, COLOR_ORDER, DIMENSIONS, STATE_MIN_ORDERS,
                        TYPE_ORDER, WHEEL_SHORT)
    assert COLOR_ORDER[0] == "Catalina Cove" and COLOR_HEX["Midnight"] == "#000009"
    assert TYPE_ORDER == ["explicit", "window", "range", "month"], "unknown is apart"
    assert WHEEL_SHORT['21” Liquid Tungsten All-Season'] == '21" Liquid Tungsten'
    assert STATE_MIN_ORDERS == DIMENSIONS["state"]["small_n"]["min_orders"] == 5


# --- Curation timing: checked, milestone dates, event-dated series (#99) -------


def test_checked_confirms_an_override_after_a_sheet_change():
    # KCP's case: the sheet's new text agrees with the override but doesn't
    # parse. Once someone re-checks it, the outdated warning should stop.
    from datetime import datetime

    from ingest.loaders import _apply_overrides
    df = _dedupe_frame([dict(BUILD, orig_num="72", user="KCP",
                             delivery_raw="4-8 weeks(org), 9 weeks (act) 8/19")])
    df["key"] = ["kcp"]
    changed = {("kcp", "delivery_raw"): ("…", datetime(2026, 8, 23),
                                         datetime(2026, 8, 23))}
    entry = {"KCP": {"as_of": "2026-08-03", "delivery_raw": "8/19/2026"}}
    _, issues = _apply_overrides(df, entry, changed=changed)
    assert "after this override (as_of 2026-08-03)" in issues[0][2], issues
    df.at[0, "delivery_raw"] = "4-8 weeks(org), 9 weeks (act) 8/19"
    entry["KCP"]["checked"] = "2026-08-23"
    applied, issues = _apply_overrides(df, entry, changed=changed)
    assert len(applied) == 1 and issues == [], issues
    assert df.at[0, "delivery_raw"] == "8/19/2026", "the override still applies"


def _ms_frame(**row):
    """One cleaned order with the columns milestones() reads."""
    base = dict(orig_num="1", user="u", key="u",
                order_date=pd.Timestamp("2026-08-01"), vin_present=True,
                vin_seq=1500.0, delivery_type="explicit",
                delivery_est=pd.Timestamp("2026-09-30"))
    base.update(row)
    return pd.DataFrame([base])


def _ms_history(*snaps):
    from datetime import datetime

    from ingest.history import replay
    fields = ["orig_num", "user", "vin_raw", "delivery_raw", "trim", "color"]
    return replay([(datetime(2026, 9, d), fields,
                    [[str(n), u, v, dl, "Performance", "Midnight"]
                     for n, (u, v, dl) in enumerate(rows, start=1)])
                   for d, rows in snaps], "orders")


def _with_curation(overrides, fn):
    import ingest.milestones as ms
    old = (ms.OVERRIDES, ms.ADDITIONS)
    ms.OVERRIDES, ms.ADDITIONS = overrides, {}
    try:
        return fn(ms)
    finally:
        ms.OVERRIDES, ms.ADDITIONS = old


def test_milestones_date_the_final_value_not_the_transients():
    h = _ms_history((1, [("u", "", "4-8 weeks")]),
                    (3, [("u", "1200", "4-8 weeks")]),        # a transient VIN
                    (5, [("u", "", "9/20/2026")]),
                    (8, [("u", "X1500", "9/30/2026")]),       # the final VIN
                    (9, [("u", "01500", "9/30/2026")]))       # reformatted only
    df, issues = _with_curation({}, lambda ms: ms.milestones(_ms_frame(), h))
    assert issues == []
    # The final VIN dates from 9/8, its first appearance; 1200 earlier doesn't
    # count, and reformatting X1500 -> 01500 isn't a new value.
    assert str(df.at[0, "vin_assigned"].date()) == "2026-09-08"
    assert str(df.at[0, "delivery_scheduled"].date()) == "2026-09-08"


def test_milestones_use_a_curated_date_only_when_it_fits():
    h = _ms_history((8, [("u", "1500", "9/30/2026")]))
    cur = {"u": {"as_of": "2026-09-08", "dates": {
        "vin_assigned": "2026-08-12", "delivery_scheduled": "2026-09-10"}}}
    df, issues = _with_curation(cur, lambda ms: ms.milestones(_ms_frame(), h))
    # The VIN date fits: after the order, before the sheet showed it.
    assert str(df.at[0, "vin_assigned"].date()) == "2026-08-12"
    # The schedule date is after the sheet already showed the date: not used.
    assert str(df.at[0, "delivery_scheduled"].date()) == "2026-09-08"
    assert "already showed" in issues[0][2], issues
    early = {"u": {"as_of": "2026-09-08", "dates": {"vin_assigned": "2026-07-01"}}}
    _, issues = _with_curation(early, lambda ms: ms.milestones(_ms_frame(), h))
    assert "before the order date" in issues[0][2], issues
    _, issues = _with_curation(early, lambda ms: ms.milestones(
        _ms_frame(vin_present=False), h))
    assert "no final VIN" in issues[0][2], issues


def test_milestones_search_merged_duplicates_and_curation():
    # The surviving row (key "u") never showed a VIN; its merged duplicate did.
    h = _ms_history((4, [("u", "", ""), ("u", "1500", "")]))
    df, _ = _with_curation({}, lambda ms: ms.milestones(
        _ms_frame(delivery_type="window"), h))
    assert str(df.at[0, "vin_assigned"].date()) == "2026-09-04"
    assert pd.isna(df.at[0, "delivery_scheduled"]), "no firm date, no milestone"
    # A final value that never reached the sheet dates from its curation as_of.
    cur = {"u": {"as_of": "2026-09-20", "vin_raw": "1500"}}
    df, _ = _with_curation(cur, lambda ms: ms.milestones(
        _ms_frame(), _ms_history((4, [("u", "", "")]))))
    assert str(df.at[0, "vin_assigned"].date()) == "2026-09-20"


def test_series_counts_what_was_true_by_each_date():
    from ingest.contract import series
    T = pd.Timestamp
    df = pd.DataFrame([
        dict(user="a", order_date=T("2026-08-01"), vin_present=True,
             vin_assigned=T("2026-08-10"), delivery_type="explicit",
             delivery_scheduled=T("2026-08-15"), delivery_est=T("2026-08-20"),
             delivered_inferred=True),
        dict(user="b", order_date=T("2026-08-03"), vin_present=False,
             vin_assigned=pd.NaT, delivery_type="window",
             delivery_scheduled=pd.NaT, delivery_est=T("2026-10-30"),
             delivered_inferred=False),
        dict(user="c", order_date=pd.NaT, vin_present=False, vin_assigned=pd.NaT,
             delivery_type="unknown", delivery_scheduled=pd.NaT,
             delivery_est=pd.NaT, delivered_inferred=False),
    ])
    resv = pd.DataFrame({"resv_date": [T("2024-03-07"), T("2026-08-02"), pd.NaT]})
    s = series(df, resv, {"a"}, T("2026-08-05"), T("2026-08-01"),
               end=T("2026-08-21"))
    at = {d: {k: v[i] for k, v in s["values"].items()}
          for i, d in enumerate(s["dates"])}
    assert len(s["dates"]) == 21 and s["dates"][0] == "2026-08-01"
    # b, ordered 8/3, counts from 8/3: what was true then, not when reported.
    assert at["2026-08-02"]["orders"] == 1 and at["2026-08-03"]["orders"] == 2
    assert at["2026-08-09"]["vin_assigned"] == 0
    assert at["2026-08-10"]["vin_assigned"] == 1
    assert at["2026-08-14"]["delivery_scheduled"] == 0
    assert at["2026-08-20"]["delivered"] == 1
    # A 2024 reservation counts from the first point; one has no date at all.
    assert at["2026-08-01"]["reservations_outstanding"] == 1
    assert at["2026-08-02"]["reservations_outstanding"] == 2
    assert s["undated"]["orders"] == 1
    assert s["undated"]["reservations_outstanding"] == 1
    assert at["2026-08-21"]["reservations_converted"] == 1
    assert s["history_start"] == "2026-08-05"
    assert set(s["metrics"]) == set(s["values"])


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
