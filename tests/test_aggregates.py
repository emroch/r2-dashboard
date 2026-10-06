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

def test_stages_follow_delivery_then_schedule_then_vin():
    from render.aggregates import stages
    df = _orders(delivered_inferred=[True, False, False, False, True, None, False],
                 delivery_type=["explicit", "explicit", "window", None, "unknown",
                                None, "explicit"],
                 vin_present=[False, True, True, False, True, None, False])
    assert list(stages(df)) == ["delivered", "scheduled", "vin", "wait",
                                "delivered", "wait", "scheduled"]
    # The last order: a firm date but no VIN reported. Delivery is only scheduled
    # after a VIN is assigned, so the missing VIN is incomplete data and the
    # order counts as scheduled, not as waiting for a VIN.


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
    assert midnight["stages"] == {"delivered": 1, "scheduled": 0, "vin": 1,
                                  "wait": 1}
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

    def labels(dim):
        return [c.get("label") or c.get("short") or str(c["value"])
                for c in DIMENSIONS[dim]["categories"]]
    for spec in COMPONENTS.values():
        if not spec.get("summary"):
            continue
        if spec.get("aggregate") == "crosstab":
            # Every pairing of the two vocabularies, as a crosstab's cells are.
            rows, cols = labels(spec["dims"][0]), labels(spec["dims"][1])
            cells = [{"row_label": r, "col_label": c, "label": "%s · %s" % (r, c),
                      "n": 1} for r in rows for c in cols]
            summarize(spec["summary"], cells)
            continue
        dim = "r1_model" if spec.get("aggregate") == "r1_models" else spec["dims"][0]
        if spec.get("template") == "takerate" or dim in DIMENSIONS:
            names = labels(dim)
            summarize(spec["summary"], [{"label": names[0], "n": 1}], names)


def test_every_takerate_summary_states_its_cohort_size():
    # Take-rates have no "n =" line: the summary sentence says how many orders
    # the panel counts, so each one must use {n}.
    for cid, spec in COMPONENTS.items():
        if spec["template"] == "takerate":
            assert "{n}" in spec.get("summary", ""), cid


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
    assert "1 delivered · 1 with a VIN · 1 waiting for a VIN" in html
    assert '<span class="tr-bar" aria-hidden="true">' in html
    assert "Midnight leads, with 75% of 4 orders." in html
    assert "not reported" not in html, "the n and the summary already say it"
    assert "Delivery status is inferred" in html, "the stage split's own caveat"
    assert "<th scope=\"col\">Delivered</th>" in html
    assert "<th scope=\"col\">With a VIN</th>" in html, "VIN keeps its capitals"


def test_a_group_says_its_shared_caveats_once():
    # Every take-rate carries the delivery-status caveat; the R1 panel also
    # carries R1 ownership's. A group of them says the shared one once.
    from render.aggregates import counts, r1_models
    from render.components import notes_html, shared_caveats, takerate
    specs = [COMPONENTS["takerate-color"], COMPONENTS["takerate-r1"]]
    shared = shared_caveats(specs)
    assert len(shared) == 1 and shared[0].startswith("Delivery status is inferred")
    df = _orders(color=["Midnight"], r1_owner_effective=["Yes"], r1_model=["R1T"])
    paint = takerate("c-p", specs[0], counts(df, "color", by_stage=True), shared)
    r1 = takerate("c-r", specs[1], r1_models(df, by_stage=True), shared)
    assert "Delivery status" not in paint and "Delivery status" not in r1
    assert "Naming an R1 model counts as owning one" in r1
    assert "Delivery status is inferred" in notes_html(shared)
    assert notes_html([]) == ""


def test_rows_without_a_category_color_are_neutral():
    from render.aggregates import counts
    from render.components import takerate
    html = takerate("c-b", COMPONENTS["takerate-buylease"],
                    counts(_orders(buylease=["Purchase", "Lease"]), "buylease",
                           by_stage=True))
    assert html.count('class="tr-row tr-neutral"') == 2
    assert "swatch" not in html


# --- Crosstabs, heatmap and mix (#108) -------------------------------------------

def test_crosstab_counts_every_pairing_of_the_orders_that_reported_both():
    from render.aggregates import cohort_sizes, crosstab, reconcile
    df = _orders(color=["Midnight", "Midnight", "Borealis", "", "Midnight"],
                 wheels_short=['21" Liquid Tungsten', '20" Black Sand',
                               '20" Black Sand', '20" Black Sand', None])
    a = crosstab(df, "color", "wheels")
    # Rows in the page-wide paint order, columns in wheel (size) order, present only.
    assert [r["value"] for r in a.meta["rows"]] == ["Midnight", "Borealis"]
    assert [c["value"] for c in a.meta["cols"]] == ['20" Black Sand',
                                                  '21" Liquid Tungsten']
    grid = {(c["row"], c["col"]): c["n"] for c in a.cells}
    bs, lt = '20" Black Sand', '21" Liquid Tungsten'
    assert grid == {("Midnight", bs): 1, ("Midnight", lt): 1,
                    ("Borealis", bs): 1, ("Borealis", lt): 0}
    assert a.excluded == {"not reported": 2}, "a blank on either side sits out"
    reconcile([a], cohort_sizes(df))
    # The margins are the counts of each dimension over the same orders.
    assert [r["n"] for r in a.meta["rows"]] == [2, 1]
    assert [c["n"] for c in a.meta["cols"]] == [2, 1]


def test_crosstab_follows_a_category_blank_policy():
    # delivery_type maps a blank to `unknown`, so those orders stay in the grid.
    from render.aggregates import crosstab
    df = _orders(vin_present=[True, False, False],
                 delivery_type=["explicit", None, "window"])
    a = crosstab(df, "vin", "delivery_type")
    assert a.excluded == {}
    grid = {(c["row_label"], c["col_label"]): c["n"] for c in a.cells if c["n"]}
    assert grid == {("VIN assigned", "Firm date"): 1,
                    ("No VIN yet", "Relative window"): 1,
                    ("No VIN yet", "No date given"): 1}


def test_heatmap_marginals_equal_the_take_rate_counts_over_the_same_orders():
    # The cross-check #108 asks for: a heatmap's row totals are the paint
    # take-rate over the orders that reported both halves of the pairing.
    from render.aggregates import counts, crosstab
    df = _paint_rank_frame()
    df["wheels_short"] = ['21" Liquid Tungsten', '20" Black Sand'] * 5
    a = crosstab(df, "color", "wheels")
    take = {c["value"]: c["n"] for c in counts(df, "color").cells}
    assert {r["value"]: r["n"] for r in a.meta["rows"]} == take
    assert sum(take.values()) == a.counted


def test_heatmap_table_has_counts_shading_totals_and_csv():
    from render.aggregates import crosstab
    from render.components import heatmap
    bs, lt = '20" Black Sand', '21" Liquid Tungsten'
    df = _orders(color=["Midnight", "Midnight", "Borealis"], wheels_short=[bs, bs, lt])
    html = heatmap("c-h", COMPONENTS["combo-wheels"], crosstab(df, "color", "wheels"))
    assert '<table class="hm" id="c-h-data">' in html
    assert 'data-table="c-h-data"' in html
    assert ('<th scope="row" class="cat-color-midnight"><span class="swatch"></span>'
            'Midnight') in html
    assert 'class="hm-cell hm-hi" style="--hm:1.000">2</td>' in html, "the peak cell"
    assert 'style="--hm:0.000">0</td>' in html, "an empty pairing still has its cell"
    assert '<td class="hm-tot">3</td></tr></tfoot>' in html, "the grand total"
    assert "is the most common pairing, at 67% of 3 orders." in html


def test_mix_rows_split_each_row_by_the_column_categories():
    from render.aggregates import crosstab
    from render.components import mix
    df = _orders(vin_present=[True, True, False],
                 delivery_type=["explicit", "window", "window"])
    html = mix("c-m", COMPONENTS["certainty-by-vin"],
               crosstab(df, "vin", "delivery_type"))
    assert html.count('<li class="mx-row">') == 2
    assert 'class="mark cat-delivery_type-explicit" style="width:50.00%"' in html
    assert 'class="mark cat-delivery_type-window" style="width:100.00%"' in html
    assert "1 firm date · 1 relative window" in html
    assert "50% of orders with a VIN have a firm" in html
    assert "against 0% of those" in html


def test_share_in_reads_a_column_share_within_a_row():
    from render.components import summarize
    cells = [{"row_label": "A", "col_label": "x", "label": "A · x", "n": 3},
             {"row_label": "A", "col_label": "y", "label": "A · y", "n": 1},
             {"row_label": "B", "col_label": "x", "label": "B · x", "n": 0}]
    assert summarize("{share_in:A|x}", cells) == "75%"
    assert summarize("{share_in:B|x}", cells) == "0%"
    # A category with no orders yet (no cells at all) reads 0% when it's real.
    assert summarize("{share_in:A|z}", cells, ["A", "B", "x", "y", "z"]) == "0%"
    try:
        summarize("{share_in:C|x}", cells)
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown row filled")


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
