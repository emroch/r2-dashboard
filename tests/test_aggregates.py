"""Tests for the presentation layer's aggregates and the take-rate component
(#105, #106): counts and their blank policies, delivery stages, R1 ownership,
reconciliation, summary sentences, and the take-rate rows.

The take-rate tests carry over what the Plotly take-rate figure's tests checked
(test_parsing.py, before #106): one paint order everywhere, blanks left out
rather than drawn, a fixed reading order for yes/no answers, and an R1 owner who
named no model staying an owner.

Run with `python3 tests/test_aggregates.py` (no pytest needed) or `pytest tests/`.
"""
import os
import sys

import pandas as pd

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from config import COLOR_ORDER, COMPONENTS

# --- Aggregates (render/aggregates.py) -----------------------------------------

def _orders(**cols):
    n = len(next(iter(cols.values())))
    base = {"vin_present": [False] * n, "delivered_inferred": [False] * n,
            "price": [None] * n, "lat": [None] * n}
    base.update(cols)
    return pd.DataFrame(base)


def test_counts_omit_excludes_blanks_and_orders_by_count_then_list():
    from render.aggregates import counts
    df = _orders(color=["Midnight", "Launch Green", None, "Midnight", "",
                        "Catalina Cove", "Launch Green"])
    a = counts(df, "color")
    assert [(c["value"], c["n"]) for c in a.cells] == [
        ("Launch Green", 2), ("Midnight", 2), ("Catalina Cove", 1)]
    assert a.excluded == {"not reported": 2} and a.counted == 5
    assert a.cells[0]["ref"] == "color:Launch Green" and a.cells[0]["known"]


def test_counts_bucket_and_category_policies_keep_blanks_as_cells():
    from render.aggregates import counts
    a = counts(_orders(region=["West", None, "West"]), "region")
    assert [(c["label"], c["n"]) for c in a.cells] == [("West", 2), ("Unknown", 1)]
    assert a.excluded == {}
    b = counts(_orders(delivery_type=["window", None, "explicit"]), "delivery_type")
    # fixed order, and the blank became the `unknown` category with its label.
    assert [(c["label"], c["n"]) for c in b.cells] == [
        ("Firm date", 1), ("Relative window", 1), ("No date given", 1)]


def test_counts_keeps_an_unlisted_value_and_marks_it_unknown():
    from render.aggregates import counts
    from render.view import View, unknown_categories
    a = counts(_orders(color=["Launch Green", "Compass Yellow"]), "color")
    new = [c for c in a.cells if not c["known"]]
    assert [(c["value"], c["ref"]) for c in new] == [("Compass Yellow", None)]
    assert unknown_categories(View(aggregates=[a])) == ["color: Compass Yellow"]


def test_counts_over_a_cohort_and_boolean_dimensions():
    from render.aggregates import cohort_sizes, counts
    df = _orders(delivered_inferred=[True, False, True],
                 vin_present=[True, True, False])
    a = counts(df, "delivered", cohort="vin_assigned")
    assert [(c["label"], c["n"]) for c in a.cells] == [
        ("Delivered (est.)", 1), ("Awaiting delivery", 1)]
    assert cohort_sizes(df)["vin_assigned"] == 2


def test_reconcile_passes_when_cells_and_exclusions_add_up():
    from render.aggregates import cohort_sizes, counts, reconcile
    df = _orders(color=["Midnight", None, "Borealis"], region=["West", None, None])
    reconcile([counts(df, "color"), counts(df, "region")], cohort_sizes(df))


def test_reconcile_fails_on_an_aggregate_that_loses_rows():
    from render.aggregates import Aggregate, ReconcileError, reconcile
    lossy = Aggregate("answered only", "orders",
                      [{"value": "a", "label": "a", "n": 2, "ref": None,
                        "known": True}])
    stray = Aggregate("stray", "no such cohort", [])
    try:
        reconcile([lossy, stray], {"orders": 3})
    except ReconcileError as exc:
        msg = str(exc)
        assert "answered only: 2 counted + 0 excluded = 2" in msg and "is 3" in msg
        assert "unknown cohort 'no such cohort'" in msg
    else:
        raise AssertionError("a lossy aggregate reconciled")


# --- Delivery stages ------------------------------------------------------------

def test_stages_follow_delivery_then_vin():
    from render.aggregates import stages
    df = _orders(delivered_inferred=[True, False, False, True, None],
                 vin_present=[False, True, False, True, None])
    assert list(stages(df)) == ["delivered", "vin", "wait", "delivered", "wait"]


def test_stage_split_always_sums_to_the_cell():
    from render.aggregates import STAGES, counts
    df = _orders(color=["Midnight", "Midnight", "Borealis", None, "Midnight"],
                 delivered_inferred=[True, False, False, True, False],
                 vin_present=[True, True, False, True, False])
    a = counts(df, "color", by_stage=True)
    for c in a.cells:
        assert sum(c["stages"].values()) == c["n"], c
        assert list(c["stages"]) == list(STAGES)
    midnight = a.cells[0]
    assert midnight["stages"] == {"delivered": 1, "vin": 1, "wait": 1}
    # The blank is excluded, whatever its stage.
    assert a.excluded == {"not reported": 1}


# --- Carried over from the Plotly take-rate tests -------------------------------

def _paint_rank_frame():
    """Paints at unequal counts with a tie: popularity orders them, and the
    palette's curated sequence only breaks the tie. Forest Green is third in the
    palette but leads on count, so the two orders can't be confused."""
    plan = [(COLOR_ORDER[2], 5), (COLOR_ORDER[1], 3),
            (COLOR_ORDER[0], 1), (COLOR_ORDER[3], 1)]
    return _orders(color=[p for p, k in plan for _ in range(k)])


def test_paint_rows_follow_the_page_wide_paint_order():
    # Issue #58: every paint chart shows one popularity ranking, palette order
    # breaking ties, stable across builds. The take-rate rows are one of them.
    from render.aggregates import counts
    from render.charts import _paint_order
    df = _paint_rank_frame()
    want = [COLOR_ORDER[2], COLOR_ORDER[1], COLOR_ORDER[0], COLOR_ORDER[3]]
    assert [c["value"] for c in counts(df, "color").cells] == want
    assert _paint_order(df) == want
    for n in range(5):
        shuffled = df.sample(frac=1.0, random_state=n)
        assert [c["value"] for c in counts(shuffled, "color").cells] == want


def test_an_unreported_build_is_left_out_not_drawn():
    # An order that never reported its build has no choice to show: it is
    # excluded (and said so), never a blank or "Unknown" row, and the rows' shares
    # are of the orders that did answer.
    from render.aggregates import counts
    df = _paint_rank_frame()
    df.loc[len(df)] = dict(df.iloc[0], color="")
    a = counts(df, "color")
    assert "" not in [c["value"] for c in a.cells]
    assert "Unknown" not in [c["label"] for c in a.cells]
    assert a.counted == len(df) - 1 and a.excluded == {"not reported": 1}


def test_yes_no_answers_keep_a_fixed_order_and_drop_blanks():
    # Purchase before Lease reads as a sequence; which is larger shouldn't decide
    # it, or the rows would swap between builds as the counts move.
    from render.aggregates import counts
    df = _orders(buylease=["Purchase"] * 3 + ["Lease"] * 5 + ["", None])
    a = counts(df, "buylease")
    assert [(c["value"], c["n"]) for c in a.cells] == [("Purchase", 3), ("Lease", 5)]
    assert a.excluded == {"not reported": 2}
    spare = counts(_orders(opted_spare=[False, True, False]), "opted_spare")
    assert [(c["label"], c["n"]) for c in spare.cells] == [("Yes", 1), ("No", 2)]


def test_an_owner_who_named_no_model_still_counts_as_an_owner():
    # A blank model means "unspecified" for an owner and "no R1" for a
    # non-owner; the two must not share a row, and every owner counts as one.
    from render.aggregates import r1_models
    df = _orders(r1_owner_effective=["Yes"] * 4 + ["Yes"] * 3 + ["No"] * 9 + [""],
                 r1_model=["R1T"] * 4 + [""] * 3 + [""] * 9 + [""])
    a = r1_models(df)
    got = {c["label"]: c["n"] for c in a.cells}
    assert got == {"R1T": 4, "Unspecified": 3, "No R1": 9}, got
    assert [c["label"] for c in a.cells] == ["R1T", "Unspecified", "No R1"]
    assert a.excluded == {"not reported": 1}, "no answer to the owner question"
    assert all(c["ref"] for c in a.cells), "each row has its R1 model color"


# --- Summary sentences and the take-rate component -----------------------------

def test_share_rounds_and_keeps_a_sliver_visible():
    from render.components import share
    assert share(1, 3) == "33%" and share(2, 3) == "67%"
    assert share(1, 400) == "<1%" and share(0, 5) == "0%" and share(0, 0) == "0%"


def test_summary_placeholders_fill_from_the_cells():
    from render.components import summarize
    cells = [{"label": "Purchase", "n": 608}, {"label": "Lease", "n": 39}]
    assert summarize("{share:Purchase} of {n} orders are purchases.", cells) == \
        "94% of 647 orders are purchases."
    assert summarize("{top} leads with {top_share}; {count:Lease} lease.", cells) == \
        "Purchase leads with 94%; 39 lease."
    assert summarize("{share_except:Lease} not leasing", cells) == "94% not leasing"
    # A category with no orders yet reads as 0%; a label that isn't one fails.
    assert summarize("{share:Lease}", cells[:1], ["Purchase", "Lease"]) == "0%"
    for bad in ("{share:Nope}", "{whatever}"):
        try:
            summarize(bad, cells)
        except KeyError:
            continue
        raise AssertionError("%s filled" % bad)


def test_every_registered_summary_fills_on_real_categories():
    # A charts.yaml summary naming a label that can't occur would fail every
    # build; catch it here with the vocabulary's own labels.
    from render.components import summarize
    from config import DIMENSIONS
    for spec in COMPONENTS.values():
        if not spec.get("summary"):
            continue
        dim = "r1_model" if spec.get("aggregate") == "r1_models" else spec["dims"][0]
        labels = [c.get("label") or c.get("short") or str(c["value"])
                  for c in DIMENSIONS[dim]["categories"]]
        summarize(spec["summary"], [{"label": labels[0], "n": 1}], labels)


def test_takerate_rows_carry_swatch_counts_bar_and_stage_text():
    from render.aggregates import counts
    from render.components import takerate
    df = _orders(color=["Midnight"] * 3 + ["Borealis"] + [None],
                 delivered_inferred=[True, False, False, False, False],
                 vin_present=[True, True, False, False, False])
    html = takerate("c-t", COMPONENTS["takerate-color"],
                    counts(df, "color", by_stage=True))
    assert '<li class="tr-row cat-color-midnight">' in html
    assert '<span class="swatch"></span>Midnight' in html
    assert "3 <span class=\"tr-pct\">75%</span>" in html
    # The widest row fills the track; its segments are thirds of it.
    # The widest row (Midnight, 3) fills the track, so each of its three stages is
    # a third of it, and Borealis's single waiting order is a third too.
    assert html.count('style="width:33.33%"') == 4
    assert "1 delivered (est.) · 1 with a VIN · 1 waiting for a VIN" in html
    assert '<span class="tr-bar" aria-hidden="true">' in html
    assert "Midnight leads, with 75% of 4 orders." in html
    assert "1 not reported, left out." in html
    assert "Inferred, not reported." in html, "the stage split's own caveat"
    assert "<th scope=\"col\">Delivered (est.)</th>" in html
    assert "<th scope=\"col\">With a VIN</th>" in html, "VIN keeps its capitals"


def test_rows_without_a_category_color_are_neutral():
    from render.aggregates import counts
    from render.components import takerate
    html = takerate("c-b", COMPONENTS["takerate-buylease"],
                    counts(_orders(buylease=["Purchase", "Lease"]), "buylease",
                           by_stage=True))
    assert html.count('class="tr-row tr-neutral"') == 2
    assert "swatch" not in html


def _run_all():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        else:
            print("PASS %s" % name)
    print("-" * 40)
    print("%d passed, %d failed (of %d)" % (len(tests) - failed, failed, len(tests)))
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
