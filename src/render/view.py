"""The page's view data: what the browser draws, and the checks behind it.

docs/presentation.md, "Data contract additions". build() computes every
aggregate the page's components use and reconciles them against their cohorts
(render/aggregates.py), and collects the spec + data of each browser-drawn
component for r2_view.json, which the page fetches.

No section is a component yet, so the view has no components. The build still
counts every dimension in dimensions.yaml and reconciles those counts, so the
building block the components will share is exercised on the real data from the
start: a value the vocabulary doesn't cover, or a blank-handling rule that loses
rows, shows up as a failed build rather than in a chart.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import DIMENSIONS

from .aggregates import Aggregate, cohort_sizes, counts, reconcile

VIEW_VERSION = 1


@dataclass
class View:
    # component id -> its house-schema spec and data (mounted components only)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    aggregates: list[Aggregate] = field(default_factory=list)


def build(df: pd.DataFrame) -> View:
    """Compute and reconcile the page's aggregates. Raises ReconcileError."""
    view = View()
    view.aggregates += [counts(df, dim) for dim in DIMENSIONS]
    reconcile(view.aggregates, cohort_sizes(df))
    return view


def unknown_categories(view: View) -> list[str]:
    """"<dimension>: <value>" for values counted that dimensions.yaml doesn't
    list, for the cleaning report."""
    return ["%s: %s" % (a.dim, c["value"])
            for a in view.aggregates for c in a.cells if not c["known"]]


def view_json(view: View) -> dict[str, Any]:
    return {"version": VIEW_VERSION, "components": view.components}
