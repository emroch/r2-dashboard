"""The page's view data: what each component shows, and the checks behind it.

docs/presentation.md, "Data contract additions". build() computes every
aggregate the page's components use, reconciles them against their cohorts
(render/aggregates.py), keeps the static components' aggregates for page.py to render
(View.render, render/components.py), and collects the spec + data of each browser-drawn
component for r2_view.json, which the page fetches (none yet).

The components are declared in src/conf/charts.yaml. The build also counts every
dimension in dimensions.yaml and reconciles those counts, so a value the
vocabulary doesn't cover, or a blank-handling rule that loses rows, fails the
build rather than showing up wrong in a chart.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import COMPONENTS, DIMENSIONS, REF_BINS

from .aggregates import (Aggregate, binned, cohort_sizes, counts, crosstab,
                         price_by_trim,
                         price_distribution, price_options, r1_models, reconcile,
                         stage_counts)
from .components import bars, heatmap, mix, mount, range_strip, takerate
from .specs import (build_cadence, deliveries_by_week, delivery_latency,
                    delivery_vs_vin, dest_vs_delivery, fulfilment_by_week, geo_demand,
                    latency_coverage, orders_by_week, reservations_by_week,
                    vin_by_config, vin_vs_order)

VIEW_VERSION = 1


@dataclass
class View:
    # component id -> its house-schema spec and data (mounted components only)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    # component id -> its aggregate (static components, drawn as HTML)
    static: dict[str, Aggregate] = field(default_factory=dict)
    # component id -> the aggregate behind a browser-drawn component's spec
    mounted: dict[str, Aggregate] = field(default_factory=dict)
    aggregates: list[Aggregate] = field(default_factory=list)
    # the summary's readout groups that are counts (Delivery progress)
    readouts: dict[str, Aggregate] = field(default_factory=dict)
    # component id -> a browser-drawn component's no-JS table: (columns, rows)
    tables: dict[str, tuple[list[str], list[list[Any]]]] = field(default_factory=dict)

    def render(self, cid: str, shared: Sequence[str] = ()) -> str:
        """A component's HTML: a static one drawn here, or a browser-drawn one's
        frame, mount point and no-JS table. `shared` caveats are said once by
        the component's group (components.shared_caveats), so its frame drops
        them."""
        spec = COMPONENTS[cid]
        if cid in self.mounted:
            return mount("c-" + cid, cid, spec, self.components[cid],
                         self.tables[cid], self.mounted[cid], shared)
        return _STATIC[spec["template"]]("c-" + cid, spec, self.static[cid], shared)


# charts.yaml `aggregate` -> how to count it. The default is the first
# dimension's counts.
_AGGREGATES = {
    "r1_models": lambda df, spec: r1_models(df, by_stage=True),
    "crosstab": lambda df, spec: _crosstab(df, spec),
    "price_distribution": lambda df, spec: price_distribution(df),
    "price_options": lambda df, spec: price_options(df),
    "price_by_trim": lambda df, spec: price_by_trim(df),
}

# charts.yaml `template` -> renderer, for the templates drawn as HTML here.
_STATIC = {"takerate": takerate, "heatmap": heatmap, "mix": mix, "bars": bars,
           "range": range_strip}

# charts.yaml `aggregate` -> spec builder, for the browser-drawn templates.
# Each takes (orders, reservations) and returns (spec, Aggregate, table).
_SPECS: dict[str, Callable[[pd.DataFrame, pd.DataFrame], tuple]] = {
    "delivery_vs_vin": lambda df, resv: delivery_vs_vin(df),
    "vin_vs_order": lambda df, resv: vin_vs_order(df),
    "geo_demand": geo_demand,
    "vin_by_config": lambda df, resv: vin_by_config(df),
    "dest_vs_delivery": lambda df, resv: dest_vs_delivery(df),
    "reservations_by_week": reservations_by_week,
    "orders_by_week": lambda df, resv: orders_by_week(df),
    "deliveries_by_week": lambda df, resv: deliveries_by_week(df),
    "delivery_latency": lambda df, resv: delivery_latency(df),
    "latency_coverage": lambda df, resv: latency_coverage(df),
    "build_cadence": lambda df, resv: build_cadence(df),
    "fulfilment_by_week": lambda df, resv: fulfilment_by_week(df),
}


def _crosstab(df: pd.DataFrame, spec: dict[str, Any]) -> Aggregate:
    """charts.yaml crosstab: dims [row, column] over `cohort` (default orders),
    with `small_n` (the row dimension's rule); or dims [column] grouped by
    `bins` {column, edges (geo.yaml state_reference_bins), unit} instead."""
    cohort = spec.get("cohort", "orders")
    b = spec.get("bins")
    if b:
        rows = binned(df[b["column"]], REF_BINS[b["edges"]], b["unit"])
        return crosstab(df, None, spec["dims"][0], cohort, rows=rows)
    return crosstab(df, spec["dims"][0], spec["dims"][1], cohort,
                    small_n=bool(spec.get("small_n")))


def _aggregate(df: pd.DataFrame, spec: dict[str, Any]) -> Aggregate:
    how = spec.get("aggregate")
    if how is None:
        return counts(df, spec["dims"][0], cohort=spec.get("cohort", "orders"),
                      by_stage=spec["template"] == "takerate")
    return _AGGREGATES[how](df, spec)


def build(df: pd.DataFrame, resv: pd.DataFrame | None = None) -> View:
    """Compute and reconcile the page's aggregates, and render its static
    components. `resv` is the outstanding reservations (§5 counts them).
    Raises ReconcileError."""
    if resv is None:
        resv = pd.DataFrame({"resv_date": pd.Series([], dtype="datetime64[ns]")})
    view = View()
    view.aggregates += [counts(df, dim) for dim in DIMENSIONS]
    for cid, spec in COMPONENTS.items():
        if spec["template"] in _STATIC:
            agg = _aggregate(df, spec)
            view.static[cid] = agg
        else:
            spec_data, agg, view.tables[cid] = _SPECS[spec["aggregate"]](df, resv)
            view.components[cid] = spec_data
            view.mounted[cid] = agg
        agg.name = "%s (%s)" % (cid, agg.name)
        view.aggregates.append(agg)
    view.readouts["progress"] = stage_counts(df)
    view.readouts["progress"].name = "summary progress (orders by delivery stage)"
    view.aggregates.append(view.readouts["progress"])
    sizes = cohort_sizes(df)
    sizes["orders+reservations"] = len(df) + len(resv)
    reconcile(view.aggregates, sizes)
    return view


def unknown_categories(view: View) -> list[str]:
    """"<dimension>: <value>" for values counted that dimensions.yaml doesn't
    list, for the cleaning report."""
    return list(dict.fromkeys("%s: %s" % (a.dim, c["value"])
                                for a in view.aggregates for c in a.cells
                                if not c["known"]))


def view_json(view: View) -> dict[str, Any]:
    return {"version": VIEW_VERSION, "components": view.components}
