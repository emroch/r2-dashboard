"""Schema-drift detection for the two hand-maintained source sheets.

Both loaders anchor columns by content rather than absolute position: the header
row is the record carrying a "Username" cell, and the orders sheet is then a
fixed block sliced from the "#" column. That survives columns appearing at the
edges, but it cannot survive a reorder or a rename — the slice would slide and
every downstream number would be wrong with nothing raised anywhere. The sheets
are hand-maintained forms, so that edit is realistic.

So the observed header row is verified against schema.yaml on every run:

* **Fatal** (raises SchemaDrift and stops the pipeline): the header row is
  missing, the "#" anchor is gone, or a mapped column was renamed, reordered,
  inserted, or removed. Failing means CI keeps serving the last good deploy,
  which beats publishing numbers that are confidently wrong.
* **Reported** (a notice in the cleaning report and the data-quality panel): a
  column that nothing maps and that schema.yaml hasn't listed as ignored —
  usually the form gained a question no chart reads yet.

Header text is compared with case folded and whitespace runs collapsed, so
re-capitalizing or re-spacing a question doesn't stop the build; anything beyond
that is treated as drift, since a rename can't be told apart from a repurpose.
"""


class SchemaDrift(RuntimeError):
    """A source sheet's header row no longer matches schema.yaml."""


def _key(text):
    """Comparison key for a header cell: case-folded, whitespace collapsed."""
    return " ".join(str(text).split()).lower()


def _col_letter(idx):
    """0-based CSV column index -> spreadsheet column letter (0 -> A), so a
    reported position matches what you see when you open the sheet."""
    out, n = "", idx + 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _unmapped(header, ignored, label, mapped):
    """Notices for header cells nothing maps that aren't listed in
    ignored_columns. (#, sheet, detail) triples, matching the QA panel's table."""
    known = {_key(c) for c in ignored}
    return [("—", label, "column %s %r is present but not mapped — nothing "
                         "reads it" % (_col_letter(j), cell))
            for j, cell in enumerate(header)
            if j not in mapped and cell and _key(cell) not in known]


def find_header(records, anchor, label):
    """Locate a sheet's header row: the first record containing `anchor`.

    Returns (row_index, [stripped cells]). Fatal when absent — the previous
    fallback was record 0, which on these exports is the blank spacer above the
    title rows, so every column would have mapped to an empty name.
    """
    want = _key(anchor)
    for i, row in enumerate(records):
        if any(_key(c) == want for c in row):
            return i, [str(c).strip() for c in row]
    raise SchemaDrift(
        "%s: no header row found — expected a cell reading %r.\n"
        "The export changed shape, or the sheet is no longer published."
        % (label, anchor))


def check_orders_header(header, expected, ignored, label):
    """Verify the orders sheet's positional block; return (start, notices).

    `expected` is the field -> header map in sheet order; the block runs
    len(expected) columns from its first entry ("#"). Compared element-wise:
    any mismatch is fatal, because the mapping is positional. Unmapped non-empty
    columns outside the block are only reported — they're skipped by design.
    """
    fields, heads = list(expected), list(expected.values())
    anchor = heads[0]
    keys = [_key(c) for c in header]
    if _key(anchor) not in keys:
        raise SchemaDrift(
            "%s: the %r anchor column is missing from the header row.\n"
            "The column block is sliced from it, so without it every field "
            "shifts.\nObserved header: %r" % (label, anchor, header))
    start = keys.index(_key(anchor))
    block = (list(header) + [""] * len(heads))[start:start + len(heads)]
    bad = [(start + j, field, want, got)
           for j, (field, want, got) in enumerate(zip(fields, heads, block))
           if _key(want) != _key(got)]
    if bad:
        lines = "\n".join(
            "  column %-3s %-16s expected %r, found %s"
            % (_col_letter(i), "(%s)" % field, want,
               repr(got) if got else "nothing")
            for i, field, want, got in bad)
        raise SchemaDrift(
            "%s: the header row no longer matches schema.yaml "
            "(orders_columns).\nThose columns are read BY POSITION, so a "
            "rename, reorder, insertion, or removal\nmis-maps every field it "
            "shifts — the numbers would all be wrong with no other error.\n"
            "Update conf/schema.yaml to match the sheet; %d of %d mapped "
            "columns differ:\n%s\nObserved header: %r"
            % (label, len(bad), len(heads), lines, header))
    mapped = set(range(start, start + len(heads)))
    return start, _unmapped(header, ignored, label, mapped)


def check_reservations_header(header, expected, ignored, label):
    """Verify the reservations sheet; return (field -> column index, notices).

    Mapped by header name, so a reorder here is harmless. But a header that went
    missing would read as empty for every row, and one appearing twice makes the
    lookup silently pick the last — both fatal.
    """
    by_key = {}
    for j, cell in enumerate(header):
        if cell:
            by_key.setdefault(_key(cell), []).append(j)
    idx, problems = {}, []
    for field, want in expected.items():
        hits = by_key.get(_key(want), [])
        if not hits:
            problems.append("  %-9s expected %r, not found" % (field, want))
        elif len(hits) > 1:
            problems.append("  %-9s %r appears in %d columns (%s) — ambiguous"
                            % (field, want, len(hits),
                               ", ".join(_col_letter(j) for j in hits)))
        else:
            idx[field] = hits[0]
    if problems:
        raise SchemaDrift(
            "%s: the header row no longer matches schema.yaml "
            "(reservations_columns).\nA missing column reads as empty for every "
            "row; a repeated one is ambiguous.\nUpdate conf/schema.yaml to match "
            "the sheet:\n%s\nObserved header: %r"
            % (label, "\n".join(problems), header))
    return idx, _unmapped(header, ignored, label, set(idx.values()))
