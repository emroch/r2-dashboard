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


def caveats(dims: Sequence[str], extra: Sequence[str] = (),
            small_n: Sequence[str] = ()) -> list[str]:
    """The caveat texts for a component showing these dimensions, in order and
    without repeats: each dimension's `caveat`, then its `small_n` note where
    the component applies that rule (`small_n`: those dimensions), then any
    component-specific `extra`. A group of components says the caveats they
    all share once (shared_caveats), so each frame drops those."""
    out: list[str] = []
    for d in dims:
        spec = DIMENSIONS[d]
        note = (spec.get("small_n") or {}).get("note") if d in small_n else None
        for text in (spec.get("caveat"), note):
            if text and text not in out:
                out.append(text)
    out += [t for t in extra if t not in out]
    return out


def csv_button(cid: str) -> str:
    """The CSV download for the table with id "<cid>-data" (main.js reveals it)."""
    return ('<button type="button" class="r2c-csv" data-table="%s-data" '
            'data-file="%s.csv" hidden>Download CSV</button>' % (cid, cid))


def _table(cid: str, table: Table) -> str:
    head = "".join('<th scope="col">%s</th>' % escape(str(c)) for c in table.columns)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % escape(str(v)) for v in r)
                   for r in table.rows)
    return ('<details class="r2c-data"><summary>Data</summary>'
            '<div class="r2c-scroll"><table id="%s-data"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>%s</details>'
            % (cid, head, body, csv_button(cid)))


def frame(cid: str, title: str, body: str, *, summary: str | None = None,
          n: int | None = None, dims: Sequence[str] = (),
          notes: Sequence[str] = (), table: Table | None = None,
          shared: Sequence[str] = (), wide: bool = False,
          small_n: Sequence[str] = ()) -> str:
    """One component's HTML. `cid` is the element id ("c-..."); `body` is trusted
    HTML (a component renderer's output); every other text is escaped.
    `shared` caveats are said by the component's group, so they're left out.
    `wide` spans the whole component grid (a chart, rather than a panel).
    `small_n`: the dimensions whose small-n rule it applies (caveats())."""
    meta = ([] if n is None else ["n = %s" % format(n, ",")]) + [
        '<span class="caveat">%s</span>' % escape(c)
        for c in caveats(dims, notes, small_n)
        if c not in shared]
    return "".join([
        '<figure class="r2c%s" id="%s" role="group" aria-labelledby="%s-t">'
        % (" r2c-wide" if wide else "", cid, cid),
        '<figcaption id="%s-t">%s</figcaption>' % (cid, escape(title)),
        '<p class="r2c-summary">%s</p>' % escape(summary) if summary else "",
        body,
        '<p class="r2c-meta">%s</p>' % " · ".join(meta) if meta else "",
        _table(cid, table) if table is not None else "",
        "</figure>"])


def component_dims(spec: dict) -> list[str]:
    """The dimensions whose caveats a component carries: its own, plus what its
    template adds (a take-rate's stage split is inferred delivery status)."""
    return list(spec.get("dims", [])) + (
        ["delivered"] if spec.get("template") == "takerate" else [])


def component_small_n(spec: dict) -> list[str]:
    """The dimension whose small-n rule a component applies (charts.yaml
    `small_n: true`: its row dimension), for its caveats."""
    return list(spec["dims"][:1]) if spec.get("small_n") else []


def shared_caveats(specs: Sequence[dict]) -> list[str]:
    """The caveats every one of these components carries, in order: said once
    for the group instead of in each frame."""
    if not specs:
        return []
    each = [caveats(component_dims(sp), small_n=component_small_n(sp))
            for sp in specs]
    return [c for c in each[0] if all(c in e for e in each[1:])]


def notes_html(texts: Sequence[str]) -> str:
    return ('<p class="r2c-notes">%s</p>' % " ".join(escape(t) for t in texts)
            if texts else "")


# --- Summary sentences ----------------------------------------------------------

def share(n: int, total: int) -> str:
    """A whole percentage, "<1%" for a sliver; for prose and the rows."""
    if not total:
        return "0%"
    p = 100.0 * n / total
    return "<1%" if 0 < p < 0.5 else "%d%%" % round(p)


_PLACEHOLDER = re.compile(r"\{(\w+)(?::([^}]*))?\}")


def summarize(template: str, cells: Sequence[dict],
              labels: Sequence[str] = (), meta: dict | None = None) -> str:
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
        if key == "meta" and meta and arg in meta:
            return str(meta[arg])      # a value the aggregate computed (a median)
        if key == "share_in" and arg and "|" in arg:
            # A crosstab's column share within one row: {share_in:ROW|COL}. A
            # real category with no orders (absent from the grid) reads 0%.
            row, col = arg.split("|", 1)
            in_row = [c for c in cells if c.get("row_label") == row]
            hit = [c for c in in_row if c.get("col_label") == col]
            if in_row and hit:
                return share(int(hit[0]["n"]), sum(int(c["n"]) for c in in_row))
            if row in by_label and col in by_label:
                return share(0, 1)
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


def takerate(cid: str, spec: dict, agg: Aggregate,
             shared: Sequence[str] = ()) -> str:
    """A take-rate component: one row per category, largest bar full width.

    Each row has a swatch (when the category has a color), its name, the count
    and share, and a bar split by delivery stage, with the stage counts written
    out beside it, so nothing is legible only from the bar. The bar is hidden
    from assistive technology: the row text and the data table say the same.
    """
    cells = agg.cells
    total = agg.counted
    widest = max((int(c["n"]) for c in cells), default=0) or 1
    # charts.yaml `total`: a first row summing every row, on its own scale (at
    # the shared one it would flatten the rest), for a long list (§13's states).
    tot = ([{"label": spec["total"], "n": total, "ref": None, "total": True,
             "stages": {st: sum(c["stages"][st] for c in cells) for st in STAGES}}]
           if spec.get("total") and cells else [])
    rows = []
    for c in tot + cells:
        cls = category_class(c["ref"]) if c["ref"] else "tr-neutral"
        if c.get("total"):
            cls += " tr-total"
        scale = (int(c["n"]) or 1) if c.get("total") else widest
        segs = "".join(
            '<i class="mark stage-%s" style="width:%.2f%%"></i>'
            % (st, 100.0 * c["stages"][st] / scale)
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
    table = Table([spec.get("row_label", "Option"), "Orders", "Share"]
                  + [STAGE_LABELS[s][:1].upper() + STAGE_LABELS[s][1:] for s in STAGES],
                  [[c["label"], c["n"], share(int(c["n"]), total)]
                   + [c["stages"][s] for s in STAGES] for c in tot + cells])
    # No "n =" line: the summary sentence already gives the cohort size.
    labels = [c.get("label") or c.get("short") or str(c["value"])
              for c in DIMENSIONS[agg.dim]["categories"]] if agg.dim else []
    summary = (summarize(spec["summary"], cells, labels)
               if spec.get("summary") and cells else None)
    return frame(cid, spec["title"], '<ol class="tr">%s</ol>' % "".join(rows),
                 summary=summary,
                 dims=component_dims(spec), table=table, shared=shared)


# --- Browser-drawn components: the frame, the mount point and a no-JS table ------

def mount(cid: str, view_id: str, spec: dict, data: dict, agg: Aggregate,
          shared: Sequence[str] = ()) -> str:
    """A component the browser draws (src/web/charts/<template>.js): its frame,
    an empty legend and the mount point main.js fills from r2_view.json, and a
    data table of every point, which is what a reader without scripts (or with a
    screen reader) gets instead of the chart."""
    rows = [[s_["name"], p["tip"][0], format(p["y"], ","), p["x"],
             "%s – %s" % (p["lo"], p["hi"]) if p.get("lo") else "",
             "firm" if p.get("firm") else ""]
            for s_ in data.get("series", []) for p in s_["points"]]
    table = Table(["Paint · wheels", "Order", "VIN", "Est. delivery",
                   "Quoted window", "Date"], rows)
    body = ('<div class="r2c-chart" data-chart="%s" data-template="%s">'
            '<div class="chart-legend" role="group" aria-label="Series"></div>'
            '<div class="chart-plot"><p class="chart-loading">The chart draws when '
            'scripts run; the data table below has every point.</p></div></div>'
            % (escape(view_id), escape(spec["template"])))
    summary = (summarize(spec["summary"], agg.cells) if spec.get("summary")
               and agg.cells else None)
    return frame(cid, spec["title"], body, summary=summary,
                 dims=component_dims(spec), table=table, shared=shared, wide=True)


def vocabulary(dim: str) -> list[str]:
    """A dimension's category labels, as cells label them."""
    return [c.get("label") or c.get("short") or str(c["value"])
            for c in DIMENSIONS[dim].get("categories") or []]


def crosstab_labels(agg: Aggregate) -> list[str]:
    """Both dimensions' labels, so a summary may name a category with no orders."""
    rows = vocabulary(agg.meta["row_dim"]) if agg.meta["row_dim"] else [
        r["label"] for r in agg.meta["rows"]]          # binned rows: their labels
    return rows + vocabulary(agg.meta["col_dim"])


# --- heatmap: a crosstab as a table with shaded cells ---------------------------

def heatmap(cid: str, spec: dict, agg: Aggregate, shared: Sequence[str] = ()) -> str:
    """A crosstab as a real table: a row per row category (with its swatch),
    a column per column category, each cell's count written in it and shaded by
    count across the grid, and the totals at the edges. The table is the data,
    so it carries the CSV button itself rather than a second copy below."""
    rows, cols = agg.meta["rows"], agg.meta["cols"]
    peak = max((int(c["n"]) for c in agg.cells), default=0) or 1
    by = {(c["row"], c["col"]): int(c["n"]) for c in agg.cells}
    # Every category column gets the width of the longest heading, so no option
    # looks heavier than another. Under pressure the headings wrap (CSS) before
    # the panel overflows, down to a shared floor of the longest single word, so
    # the columns stay equal when squeezed too.
    wide = max((len(str(c["label"])) for c in cols), default=0)
    word = max((len(w) for c in cols for w in str(c["label"]).split()), default=0)
    head = "".join('<th scope="col" class="hm-ch">%s</th>' % escape(str(c["label"]))
                   for c in cols)
    body = []
    for r in rows:
        cls = ' class="%s"' % category_class(r["ref"]) if r["ref"] else ""
        sw = '<span class="swatch"></span>' if r["ref"] else ""
        counts = [by[(r["value"], c["value"])] for c in cols]
        # Dark cells (over 55% of the peak) switch to light text.
        cells = "".join('<td class="hm-cell%s" style="--hm:%.3f">%s</td>'
                        % (" hm-hi" if k / peak > 0.55 else "", k / peak,
                           format(k, ",")) for k in counts)
        body.append('<tr><th scope="row"%s>%s%s</th>%s<td class="hm-tot">%s</td></tr>'
                    % (cls, sw, escape(str(r["label"])), cells,
                       format(int(r["n"]), ",")))
    foot = "".join('<td class="hm-tot">%s</td>' % format(int(c["n"]), ",")
                   for c in cols)
    table = ('<div class="r2c-scroll"><table class="hm" id="%s-data" '
             'style="--hm-w:%dch;--hm-min:%dch"><thead><tr>'
             '<th scope="col">%s</th>%s<th scope="col" class="hm-tot">Total</th>'
             '</tr></thead><tbody>%s</tbody><tfoot><tr><th scope="row">Total</th>%s'
             '<td class="hm-tot">%s</td></tr></tfoot></table></div>%s'
             % (cid, wide, word, escape(DIMENSIONS[agg.meta["row_dim"]]["label"]), head,
                "".join(body), foot, format(agg.counted, ","), csv_button(cid)))
    summary = (summarize(spec["summary"], agg.cells, crosstab_labels(agg))
               if spec.get("summary") and agg.counted else None)
    return frame(cid, spec["title"], table, summary=summary,
                 dims=component_dims(spec), shared=shared)


# --- mix: 100% rows, each split by a second dimension's categories --------------

def mix(cid: str, spec: dict, agg: Aggregate, shared: Sequence[str] = ()) -> str:
    """A crosstab as 100%-stacked rows: one row per row category, its bar split
    by the column categories (their marks), with the counts written beside it,
    and a key of the column categories above. Rows of different sizes compare
    by share; each row's n is on it. charts.yaml `baseline` (its label) puts
    the column mix of every cohort order that reported the column first, set
    apart, as the row the others are read against."""
    rows, cols = agg.meta["rows"], agg.meta["cols"]
    by = {(c["row"], c["col"]): int(c["n"]) for c in agg.cells}
    base = agg.meta.get("baseline") if spec.get("baseline") else None
    # The key lists every column category drawn, the baseline's included.
    keyed = cols + [c for c in base or () if c["value"] not in
                    {k["value"] for k in cols}]

    # Paints and cabins compare in their true colors here (dimensions.yaml
    # true_color); the bar's border keeps white and black legible on the card.
    true = " mark-true" if DIMENSIONS[agg.meta["col_dim"]].get("true_color") else ""

    def row(label: str, n: int, parts: Sequence[tuple[dict, int]], cls: str) -> str:
        segs = "".join('<i class="mark%s %s" style="width:%.2f%%"></i>'
                       % (true if c["ref"] else "",
                          category_class(c["ref"]) if c["ref"] else "tr-neutral",
                          100.0 * k / (n or 1)) for c, k in parts if k)
        split = " · ".join("%s %s" % (format(k, ","), escape(str(c["label"])))
                           for c, k in parts if k)
        return ('<li class="%s"><span class="tr-name">%s</span>'
                '<span class="tr-n">n = %s</span>'
                '<span class="mx-bar" aria-hidden="true">%s</span>'
                '<span class="tr-split">%s</span></li>'
                % (cls, escape(label), format(n, ","), segs, split))
    out = ([row(spec["baseline"], sum(int(c["n"]) for c in base),
                [(c, int(c["n"])) for c in base], "mx-row mx-base")] if base else [])
    out += [row(str(r["label"]), int(r["n"]),
                [(c, by[(r["value"], c["value"])]) for c in cols], "mx-row")
            for r in rows]
    key = "".join('<span><i class="swatch %s"></i>%s</span>'
                  % (category_class(c["ref"]) if c["ref"] else "",
                     escape(str(c["label"]))) for c in keyed)
    head = spec.get("row_label") or DIMENSIONS[agg.meta["row_dim"]]["label"]
    bv = {c["value"]: int(c["n"]) for c in base or ()}
    table = Table([head] + [c["label"] for c in keyed] + ["Total"],
                  ([[spec["baseline"]] + [bv.get(c["value"], 0) for c in keyed]
                    + [sum(bv.values())]] if base else [])
                  + [[r["label"]] + [by.get((r["value"], c["value"]), 0) for c in keyed]
                     + [r["n"]] for r in rows])
    summary = (summarize(spec["summary"], agg.cells, crosstab_labels(agg), agg.meta)
               if spec.get("summary") and agg.counted else None)
    body = ('<p class="mx-key" aria-hidden="true">%s</p><ol class="tr mx">%s</ol>'
            % (key, "".join(out)))
    return frame(cid, spec["title"], body, summary=summary,
                 dims=component_dims(spec), table=table, shared=shared,
                 small_n=component_small_n(spec))


# --- bars: one bar per row, its length a value; an optional highlighted row ------

def bars(cid: str, spec: dict, agg: Aggregate, shared: Sequence[str] = ()) -> str:
    """Rows with a single bar each, longest full width: the row label, the value
    as text (`display`, else the count), an optional note, and the bar. A cell
    flagged `highlight` (the median price) draws in the accent and carries its
    note in bold. The bar is decoration; the text and the data table carry it.
    charts.yaml `amount` names the cell field the bar measures (default: n)."""
    field = spec.get("amount", "n")
    cells = agg.cells
    widest = max((float(c[field]) for c in cells), default=0.0) or 1.0
    rows = []
    for c in cells:
        hi = c.get("highlight")
        rows.append(
            '<li class="tr-row br-row%s"><span class="tr-name">%s%s</span>'
            '<span class="tr-n">%s</span>'
            '<span class="tr-bar" aria-hidden="true"><i class="mark %s" '
            'style="width:%.2f%%"></i></span>%s</li>'
            % (" br-hi" if hi else "", escape(str(c["label"])),
               ' <b class="br-tag">%s</b>' % escape(c["note"]) if hi and c.get("note")
               else "",
               escape(str(c.get("display", format(int(c["n"]), ",")))),
               "acc-price-accent" if hi or spec.get("accent") else "acc-price-bar",
               100.0 * float(c[field]) / widest,
               '<span class="tr-split">%s</span>' % escape(c["note"])
               if c.get("note") and not hi else ""))
    columns = spec.get("table", ["Option", "Value", "Note"])
    table = Table(columns, [[c["label"], c.get("display", c["n"]), c.get("note", "")]
                            for c in cells])
    summary = (summarize(spec["summary"], cells, meta=agg.meta)
               if spec.get("summary") and cells else None)
    return frame(cid, spec["title"], '<ol class="tr">%s</ol>' % "".join(rows),
                 summary=summary, dims=component_dims(spec), table=table,
                 shared=shared)


# --- range: a min..max strip per row, with the middle half, median and mean ------

_STAT_NAMES = (("min", "min"), ("q1", "Q1"), ("median", "median"), ("q3", "Q3"),
               ("max", "max"))


def stat_labels(stats: dict[str, float]) -> list[tuple[str, int]]:
    """The five-number summary as (name, value) labels, stats that round to the
    same dollar merged ("Q1 / median") so a clustered cohort reads once."""
    groups: dict[int, list[str]] = {}
    for key, name in _STAT_NAMES:
        groups.setdefault(round(stats[key]), []).append(name)
    return [(" / ".join(names), val) for val, names in sorted(groups.items())]


def range_strip(cid: str, spec: dict, agg: Aggregate,
                shared: Sequence[str] = ()) -> str:
    """One row per category (a trim): a whisker from min to max, a box over the
    middle half, the median as a line and the mean as a diamond, on an axis
    shared by every row (meta lo..hi), with every value written below. A
    category with no orders keeps its row and says so."""
    lo, hi = agg.meta.get("lo", 0.0), agg.meta.get("hi", 1.0)
    span = (hi - lo) or 1.0

    def at(v: float) -> str:
        return "%.2f%%" % (100.0 * (v - lo) / span)

    rows = []
    for c in agg.cells:
        st = c["stats"]
        if not st:
            rows.append('<li class="tr-row rg-row rg-empty"><span class="tr-name">'
                        '%s</span><span class="tr-n">n = 0</span><span class='
                        '"tr-split">no orders yet</span></li>'
                        % escape(str(c["label"])))
            continue
        strip = ('<span class="rg-strip" aria-hidden="true">'
                 '<i class="rg-whisker" style="left:%s;right:calc(100%% - %s)"></i>'
                 '<i class="rg-box mark acc-price-bar" style="left:%s;'
                 'right:calc(100%% - %s)"></i><i class="rg-median" style="left:%s"></i>'
                 '<i class="rg-mean" style="left:%s"></i></span>'
                 % (at(st["min"]), at(st["max"]), at(st["q1"]), at(st["q3"]),
                    at(st["median"]), at(st["mean"])))
        text = " · ".join("%s $%s" % (name, format(val, ","))
                          for name, val in stat_labels(st))
        rows.append('<li class="tr-row rg-row"><span class="tr-name">%s</span>'
                    '<span class="tr-n">n = %s</span>%s<span class="tr-split">%s · '
                    'mean $%s</span></li>'
                    % (escape(str(c["label"])), format(int(c["n"]), ","), strip,
                       escape(text), format(round(st["mean"]), ",")))
    cols = ("min", "q1", "median", "q3", "max", "mean")
    table = Table(["Trim", "Orders", "Min", "Q1", "Median", "Q3", "Max", "Mean"],
                  [[c["label"], c["n"]] + ([round(c["stats"][k]) for k in cols]
                                           if c["stats"] else [""] * 6)
                   for c in agg.cells])
    summary = (summarize(spec["summary"], agg.cells, meta=agg.meta)
               if spec.get("summary") and agg.counted else None)
    key = ('<p class="mx-key" aria-hidden="true"><span><i class="rg-key-box '
           'acc-price-bar"></i>middle half</span><span><i class="rg-key-median">'
           '</i>median</span><span><i class="rg-key-mean"></i>mean</span>'
           '<span>whiskers: min–max</span></p>')
    return frame(cid, spec["title"], key + '<ol class="tr">%s</ol>' % "".join(rows),
                 summary=summary, dims=component_dims(spec), table=table,
                 shared=shared)


# --- readout: a big number and its label; a list behind a disclosure ------------

def readout(value: object, label: str, rows: Sequence[Sequence[object]] = (),
            caption: str = "") -> str:
    """One summary number. With `rows` (the entries behind it: (#, user,
    detail)) it is a disclosure, marked ⓘ: clicking opens the list inline,
    under a caption naming the readout and saying what the list holds (the
    list can land rows below its chip)."""
    chip = '<b class="ro-v">%s</b><span class="ro-l">%s%s</span>' % (
        escape(str(value)), escape(label),
        '<span class="ro-i" aria-hidden="true">&#9432;</span>' if rows else "")
    if not rows:
        return '<div class="ro-chip">%s</div>' % chip
    body = "".join("<tr><td>#%s</td><td>%s</td><td>%s</td></tr>"
                   % tuple(escape(str(v)) for v in r) for r in rows)
    return ('<details class="ro-more"><summary class="ro-chip">%s</summary>'
            '<div class="ro-rows">%s<div class="r2c-scroll"><table><thead><tr>'
            '<th scope="col">#</th><th scope="col">User</th><th scope="col">Detail'
            '</th></tr></thead><tbody>%s</tbody></table></div></div></details>'
            % (chip, '<p class="ro-cap"><b>%s</b>%s</p>'
               % (escape(label), " — " + escape(caption) if caption else ""), body))


def readout_group(title: str, readouts: Sequence[str], note: str = "",
                  key: str = "") -> str:
    """A titled row of readouts, with an optional note under them (a caveat
    they share) and `key`, trusted HTML above them (the stage legend)."""
    return ('<div class="ro-group" role="group" aria-label="%s"><span class="ro-title">'
            '%s</span>%s<div class="ro-row">%s</div>%s</div>'
            % (escape(title), escape(title), key, "".join(readouts),
               '<p class="ro-note">%s</p>' % escape(note) if note else ""))


def stage_readouts(agg: Aggregate) -> list[str]:
    """The Delivery progress readouts: one per stage, named as in the take-rate
    bars' stage key."""
    return [readout(format(int(c["n"]), ","), c["label"][:1].upper() + c["label"][1:])
            for c in agg.cells]
