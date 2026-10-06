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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import COMPONENTS, DIMENSIONS

from .aggregates import Aggregate, cohort_sizes, counts, r1_models, reconcile
from .components import takerate
from .specs import delivery_vs_vin, geo_orders

VIEW_VERSION = 1


@dataclass
class View:
    # component id -> its house-schema spec and data (mounted components only)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    # component id -> its aggregate (static components, drawn as HTML)
    static: dict[str, Aggregate] = field(default_factory=dict)
    aggregates: list[Aggregate] = field(default_factory=list)

    def render(self, cid: str, shared: Sequence[str] = ()) -> str:
        """A static component's HTML. `shared` caveats are said once by the
        component's group (components.shared_caveats), so its frame drops them."""
        spec = COMPONENTS[cid]
        return _STATIC[spec["template"]]("c-" + cid, spec, self.static[cid], shared)


# charts.yaml `aggregate` -> how to count it. The default is the first
# dimension's counts.
_AGGREGATES = {"r1_models": lambda df, spec: r1_models(df, by_stage=True)}

# charts.yaml `template` -> renderer, for the templates drawn as HTML here.
_STATIC = {"takerate": takerate}

# charts.yaml `aggregate` -> spec builder, for the browser-drawn templates.
_SPECS = {"delivery_vs_vin": delivery_vs_vin, "geo_orders": geo_orders}


def _aggregate(df: pd.DataFrame, spec: dict[str, Any]) -> Aggregate:
    how = spec.get("aggregate")
    if how is None:
        return counts(df, spec["dims"][0], by_stage=spec["template"] == "takerate")
    return _AGGREGATES[how](df, spec)


def build(df: pd.DataFrame) -> View:
    """Compute and reconcile the page's aggregates, and render its static
    components. Raises ReconcileError."""
    view = View()
    view.aggregates += [counts(df, dim) for dim in DIMENSIONS]
    for cid, spec in COMPONENTS.items():
        if spec["template"] in _STATIC:
            agg = _aggregate(df, spec)
            view.static[cid] = agg
        else:
            mounted, agg = _SPECS[spec["aggregate"]](df)
            view.components[cid] = mounted
        agg.name = "%s (%s)" % (cid, agg.name)
        view.aggregates.append(agg)
    reconcile(view.aggregates, cohort_sizes(df))
    return view


def unknown_categories(view: View) -> list[str]:
    """"<dimension>: <value>" for values counted that dimensions.yaml doesn't
    list, for the cleaning report."""
    return list(dict.fromkeys("%s: %s" % (a.dim, c["value"])
                                for a in view.aggregates for c in a.cells
                                if not c["known"]))


def view_json(view: View) -> dict[str, Any]:
    return {"version": VIEW_VERSION, "components": view.components}
