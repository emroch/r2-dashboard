"""Unit tests for ingest.parsing.

Runs under pytest, but also standalone without it:

    python tests/test_parsing.py

The standalone runner discovers every test_* function, executes it, and prints
PASS/FAIL per test plus a summary (exit code 1 if anything fails).
"""
import csv
import io
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
    assert len(added) == 2 and add_df.loc[add_df["user"] == "Bob", "loc_raw"].iloc[0] == "CA"
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
    named = [t for t in fig.data if t.name]
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
    field_ids = set(b["id"] for b in form["body"] if "id" in b)

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
    paints = [c for c in COLOR_ORDER[:2]]
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
    from config import COLOR_ORDER, INTERIOR_ORDER, INTERIOR_SHORT
    from render.charts import fig_vin_by_config
    df = _interior_frame()
    rows = list(fig_vin_by_config(df).layout.yaxis.ticktext)
    assert len(rows) == len(df), "one row per distinct configuration"
    for r in rows:
        assert len(r.split(" · ")) == 4, r
    # Rows sort by paint (COLOR_ORDER) then wheel then interior (INTERIOR_ORDER),
    # so a reader scanning down sees a stable, meaningful sequence.
    rank = {INTERIOR_SHORT[i]: n for n, i in enumerate(INTERIOR_ORDER)}
    keys = [(COLOR_ORDER.index(r.split(" · ")[1]), r.split(" · ")[2],
             rank[r.split(" · ")[3]]) for r in rows]
    assert keys == sorted(keys)


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
