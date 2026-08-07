"""Column location and schema-drift detection for the source sheets.

Both sheets are hand-maintained forms, so their layout can change without notice.
Columns are therefore located by NAME: the header row is the record carrying a
"Username" cell, and every field named in schema.yaml is looked up in it. Only
mapped columns are read, so the sheets can be reordered, and can grow new
questions at any position, with no effect here.

What can still go wrong is a mapped column disappearing — renamed, removed, or
duplicated. Left unchecked, a lookup miss reads as empty for every row and a
duplicate silently picks one of the candidates, so a whole field would go blank
or wrong while the run reported success. That is the one failure mode worth
stopping for:

* **Fatal** (raises SchemaDrift): the header row is missing, or a mapped header
  isn't found exactly once. Failing means CI keeps serving the last good deploy,
  which beats publishing numbers that are confidently wrong. The message lists
  the unmapped headers that ARE present, so a rename diagnoses itself.
* **Reported** (a notice in the cleaning report and the data-quality panel): a
  header that nothing maps and schema.yaml hasn't listed as ignored — usually the
  form gained a question no chart reads yet.

Header text is compared with case folded and whitespace runs collapsed, so
re-capitalizing or re-spacing a question doesn't stop the build.
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


def map_columns(header, expected, ignored, label):
    """Resolve schema.yaml's field -> header map against an observed header row.

    Returns (field -> column index, notices). Fatal if any mapped header isn't
    present exactly once; `notices` are (#, sheet, detail) triples — matching the
    data-quality panel's table — for present headers that nothing maps and
    `ignored` doesn't list.
    """
    if len(set(_key(h) for h in expected.values())) != len(expected):
        raise SchemaDrift(
            "%s: two fields in schema.yaml claim the same sheet header, so one "
            "of them\nwould read the wrong column. Mapped headers: %r"
            % (label, list(expected.values())))

    found = {}
    for j, cell in enumerate(header):
        if cell:
            found.setdefault(_key(cell), []).append(j)

    idx, problems = {}, []
    for field, want in expected.items():
        hits = found.get(_key(want), [])
        if len(hits) == 1:
            idx[field] = hits[0]
        elif not hits:
            problems.append("  %-13s expected %r — not found" % (field, want))
        else:
            problems.append("  %-13s %r appears in %d columns (%s) — ambiguous"
                            % (field, want, len(hits),
                               ", ".join(_col_letter(j) for j in hits)))

    # Present, unmapped, and not listed as a known extra: the columns worth
    # telling someone about, and the candidates for a rename.
    mapped, known = set(idx.values()), {_key(c) for c in ignored}
    extra = [(j, cell) for j, cell in enumerate(header)
             if cell and j not in mapped and _key(cell) not in known]
    notices = [("—", label, "column %s %r is present but not mapped — nothing "
                            "reads it" % (_col_letter(j), cell))
               for j, cell in extra]
    if problems:
        # Naming the unmapped columns that ARE present turns a rename from a
        # puzzle into a one-line schema.yaml edit. If they're all accounted for
        # as known extras, fall back to listing those too.
        hint = extra or [(j, c) for j, c in enumerate(header)
                         if c and j not in mapped]
        raise SchemaDrift(
            "%s: the header row no longer matches schema.yaml.\nA column that "
            "can't be found reads as empty for every row, and an ambiguous one "
            "picks\nwhichever it likes — so the field would silently go blank or "
            "wrong. Update\nconf/schema.yaml to match the sheet:\n%s\n"
            "Unmapped columns present (a renamed one is probably here): %s"
            % (label, "\n".join(problems),
               ", ".join("%s %r" % (_col_letter(j), c) for j, c in hint)
               or "none"))
    return idx, notices
