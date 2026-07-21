"""Unit tests for ingest.parsing.

Runs under pytest, but also standalone without it:

    python tests/test_parsing.py

The standalone runner discovers every test_* function, executes it, and prints
PASS/FAIL per test plus a summary (exit code 1 if anything fails).
"""
import os
import sys
from datetime import date

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
    assert len(added) == 2 and add_df.loc[add_df["user"] == "Bob", "loc_raw"].iloc[0] == "CA"
    assert any("already in orders sheet" in d for _, _, d in issues)
    assert any("unknown field" in d for _, _, d in issues)


def _run_all():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report any failure
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        else:
            passed += 1
            print("PASS %s" % name)
    print("-" * 40)
    print("%d passed, %d failed (of %d)" % (passed, failed, len(tests)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
