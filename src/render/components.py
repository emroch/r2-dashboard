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

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from config import DIMENSIONS


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
