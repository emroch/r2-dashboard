"""The component frame: the structure every presentation-layer component shares.

docs/presentation.md, "Components". Every component, whether drawn as HTML here
or mounted for a chart library in the browser, sits in the same frame:

    <figure class="r2c" id="c-<id>" role="group" aria-labelledby="c-<id>-t">
      <figcaption id="c-<id>-t">title</figcaption>
      <p class="r2c-summary">the finding, in one sentence</p>
      ...body...
      <p class="r2c-meta">n = 674 · caveats</p>
      <details class="r2c-data"><summary>Data</summary><table>...</table>
        <button class="r2c-csv" ...>Download CSV</button></details>
    </figure>

The caveats come from the dimensions the component shows (dimensions.yaml
`caveat` and `small_n` notes), so the same caveat appears wherever its dimension
does. The data table mirrors what is drawn; for a browser-drawn chart it is also
the fallback with scripts off, and the accessible form of the chart. The CSV
button is hidden until main.js wires it to the table, since it needs a script.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from config import DIMENSIONS

from .aggregates import STAGE_LABELS, STAGES, Aggregate
from .categories import category_class


@dataclass(frozen=True)
class Table:
    """A data table: column headings and rows of cell values (shown as text)."""
    columns: Sequence[str]
    rows: Sequence[Sequence[object]]


def caveats(dims: Sequence[str], extra: Sequence[str] = ()) -> list[str]:
    """The caveat texts for a component showing these dimensions, in order and
    without repeats: each dimension's `caveat`, then its `small_n` note, then
    any component-specific `extra`."""
    out: list[str] = []
    for d in dims:
        spec = DIMENSIONS[d]
        for text in (spec.get("caveat"), (spec.get("small_n") or {}).get("note")):
            if text and text not in out:
                out.append(text)
    out += [t for t in extra if t not in out]
    return out


def _table(cid: str, table: Table) -> str:
    head = "".join('<th scope="col">%s</th>' % escape(str(c)) for c in table.columns)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % escape(str(v)) for v in r)
                   for r in table.rows)
    return ('<details class="r2c-data"><summary>Data</summary>'
            '<table id="%s-data"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            '<button type="button" class="r2c-csv" data-table="%s-data" '
            'data-file="%s.csv" hidden>Download CSV</button></details>'
            % (cid, head, body, cid, cid))


def frame(cid: str, title: str, body: str, *, summary: str | None = None,
          n: int | None = None, dims: Sequence[str] = (),
          notes: Sequence[str] = (), table: Table | None = None) -> str:
    """One component's HTML. `cid` is the element id ("c-..."); `body` is trusted
    HTML (a component renderer's output); every other text is escaped."""
    meta = ([] if n is None else ["n = %s" % format(n, ",")]) + [
        '<span class="caveat">%s</span>' % escape(c) for c in caveats(dims, notes)]
    return "".join([
        '<figure class="r2c" id="%s" role="group" aria-labelledby="%s-t">' % (cid, cid),
        '<figcaption id="%s-t">%s</figcaption>' % (cid, escape(title)),
        '<p class="r2c-summary">%s</p>' % escape(summary) if summary else "",
        body,
        '<p class="r2c-meta">%s</p>' % " · ".join(meta) if meta else "",
        _table(cid, table) if table is not None else "",
        "</figure>"])


# --- Summary sentences ----------------------------------------------------------

def share(n: int, total: int) -> str:
    """A whole percentage, "<1%" for a sliver; for prose and the rows."""
    if not total:
        return "0%"
    p = 100.0 * n / total
    return "<1%" if 0 < p < 0.5 else "%d%%" % round(p)


_PLACEHOLDER = re.compile(r"\{(\w+)(?::([^}]*))?\}")


def summarize(template: str, cells: Sequence[dict],
              labels: Sequence[str] = ()) -> str:
    """Fill a charts.yaml summary template from an aggregate's cells (see the
    placeholders documented there). `labels` are the dimension's category
    labels: one with no orders yet counts as 0. An unknown placeholder or label
    raises, so a typo in the YAML fails the build instead of printing a wrong
    sentence."""
    total = sum(int(c["n"]) for c in cells)
    by_label = dict.fromkeys(labels, 0)
    by_label.update({c["label"]: int(c["n"]) for c in cells})
    top = max(cells, key=lambda c: int(c["n"])) if cells else None

    def fill(m: re.Match) -> str:
        key, arg = m.group(1), m.group(2)
        if key == "n":
            return format(total, ",")
        if key in ("top", "top_share") and top is not None:
            return top["label"] if key == "top" else share(int(top["n"]), total)
        if arg is not None and arg in by_label:
            n = by_label[arg]
            return {"share": share(n, total), "count": format(n, ","),
                    "share_except": share(total - n, total)}[key]
        raise KeyError("summary placeholder %r has nothing to fill it"
                       % m.group(0))
    return _PLACEHOLDER.sub(fill, template)


# --- takerate: rows with a bar split by delivery stage --------------------------

def stage_key() -> str:
    """The legend for the stage split, shown once above a group of take-rates."""
    return ('<p class="stage-key" aria-hidden="true">%s</p>' % "".join(
        '<span><i class="mark tr-neutral stage-%s"></i>%s</span>'
        % (st, escape(STAGE_LABELS[st])) for st in STAGES))


def takerate(cid: str, spec: dict, agg: Aggregate) -> str:
    """A take-rate component: one row per category, largest bar full width.

    Each row has a swatch (when the category has a color), its name, the count
    and share, and a bar split by delivery stage, with the stage counts written
    out beside it, so nothing is legible only from the bar. The bar is hidden
    from assistive technology: the row text and the data table say the same.
    """
    cells = agg.cells
    total = agg.counted
    widest = max((int(c["n"]) for c in cells), default=0) or 1
    rows = []
    for c in cells:
        cls = category_class(c["ref"]) if c["ref"] else "tr-neutral"
        segs = "".join(
            '<i class="mark stage-%s" style="width:%.2f%%"></i>'
            % (st, 100.0 * c["stages"][st] / widest)
            for st in STAGES if c["stages"][st])
        split = " · ".join("%s %s" % (format(c["stages"][st], ","), STAGE_LABELS[st])
                           for st in STAGES if c["stages"][st])
        rows.append(
            '<li class="tr-row %s">'
            '<span class="tr-name">%s%s</span>'
            '<span class="tr-n">%s <span class="tr-pct">%s</span></span>'
            '<span class="tr-bar" aria-hidden="true">%s</span>'
            '<span class="tr-split">%s</span></li>'
            % (cls, '<span class="swatch"></span>' if c["ref"] else "",
               escape(str(c["label"])), format(int(c["n"]), ","),
               share(int(c["n"]), total), segs, escape(split)))
    # Only the first letter is raised: str.capitalize() would lower "VIN".
    table = Table(["Option", "Orders", "Share"] + [STAGE_LABELS[s][:1].upper()
                                                   + STAGE_LABELS[s][1:]
                                                   for s in STAGES],
                  [[c["label"], c["n"], share(int(c["n"]), total)]
                   + [c["stages"][s] for s in STAGES] for c in cells])
    excluded = sum(agg.excluded.values())
    notes = (["%s not reported, left out." % format(excluded, ",")]
             if excluded else [])
    labels = [c.get("label") or c.get("short") or str(c["value"])
              for c in DIMENSIONS[agg.dim]["categories"]] if agg.dim else []
    summary = (summarize(spec["summary"], cells, labels)
               if spec.get("summary") and cells else None)
    return frame(cid, spec["title"], '<ol class="tr">%s</ol>' % "".join(rows),
                 summary=summary,
                 n=total, dims=list(spec.get("dims", [])) + ["delivered"],
                 notes=notes, table=table)
