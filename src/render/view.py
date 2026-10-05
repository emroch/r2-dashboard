"""The page's view data: what each component shows, and the checks behind it.

docs/presentation.md, "Data contract additions". build() computes every
aggregate the page's components use, reconciles them against their cohorts
(render/aggregates.py), renders the static components (render/components.py) to
HTML for page.py to place, and collects the spec + data of each browser-drawn
component for r2_view.json, which the page fetches (none yet).

The components are declared in src/conf/charts.yaml. The build also counts every
dimension in dimensions.yaml and reconciles those counts, so a value the
vocabulary doesn't cover, or a blank-handling rule that loses rows, fails the
build rather than showing up wrong in a chart.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import COMPONENTS, DIMENSIONS

from .aggregates import Aggregate, cohort_sizes, counts, r1_models, reconcile
from .components import takerate

VIEW_VERSION = 1


@dataclass
class View:
    # component id -> its house-schema spec and data (mounted components only)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    # component id -> its rendered HTML (static components)
    html: dict[str, str] = field(default_factory=dict)
    aggregates: list[Aggregate] = field(default_factory=list)


# charts.yaml `aggregate` -> how to count it. The default is the first
# dimension's counts.
_AGGREGATES = {"r1_models": lambda df, spec: r1_models(df, by_stage=True)}

# charts.yaml `template` -> renderer, for the templates drawn as HTML here.
_STATIC = {"takerate": takerate}


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
        agg = _aggregate(df, spec)
        agg.name = "%s (%s)" % (cid, agg.name)
        view.aggregates.append(agg)
        view.html[cid] = _STATIC[spec["template"]]("c-" + cid, spec, agg)
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
