"""Provenance and timing for the manual curation in overrides.yaml.

Data layer stage 2 and #99 (docs/data-layer.md). Every entry, in every section,
may carry these META keys alongside what it edits:

  source   where the information came from: a forum URL (or a list of them), or
           text starting with "inferred" for a judgment made from the data itself
  as_of    when we LEARNED it (the post, or the curation date). It anchors the
           stale-override check: a sheet change after it may mean the override
           is out of date. Not needed on a dates-only entry, which overrides
           nothing
  checked  optional, a later date on which someone confirmed the override still
           holds; the stale check then counts sheet changes after this instead
  reason   a short note, shown with the entry in the report
  dates    (after load()) optional milestone dates for the order's FINAL values (#99):
           vin_assigned, delivery_scheduled. May stand alone, with no value
           overridden, to date values the sheet already has (ingest/milestones.py)

They are never sheet fields, so they are split off here before anything is
applied. Every entry must have a source and an as_of, and a missing one stops the
build: a correction nobody can trace, published on the dashboard, is the thing
this exists to prevent.

The file itself is curation_version 3: load() validates it against
conf/overrides.schema.json, the field-by-field reference, then converts each entry
into the shape everything downstream reads. Each value becomes the raw sheet cell
it stands for (vin -> vin_raw, dates.order_date -> order_raw as M/D/YYYY, config
fields as-is, ...), so a curated value flows through the same cleaning as the
sheet's, and the milestone dates (vin_assigned, delivery_scheduled) stay under
`dates`, as the META split below expects.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import calendar
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Mapping, NamedTuple

import jsonschema

VERSION = 3

META = ("source", "as_of", "checked", "reason", "dates")
MILESTONES = ("vin_assigned", "delivery_scheduled")


class CurationError(ValueError):
    """overrides.yaml doesn't validate, or is missing provenance."""


# --- The v3 file -> the internal (raw sheet row) shape -----------------------
# v3 field -> the sheet column it sets. Config fields keep their names.
TOP_FIELDS = {"vin": "vin_raw", "location": "loc_raw", "purchase": "buylease"}
DATE_FIELDS = {"resv_date": "resv_raw", "order_date": "order_raw",
               "delivery": "delivery_raw"}
CONFIG_FIELDS = ("trim", "launch", "color", "interior", "wheels", "autonomy",
                 "tow", "spare")
R1_FIELDS = {"owner": "r1_owner", "model": "r1_model"}
# Not a sheet column: the date a curated `weeks`/`days` window counts from, when
# it isn't the order date. Carried beside the row until the delivery is parsed.
DELIVERY_FROM = "delivery_from"
# Sheet column -> its v3 name, for messages about curation.
NAMES = {**{v: k for k, v in TOP_FIELDS.items()},
         **{v: "dates." + k for k, v in DATE_FIELDS.items()},
         **{c: "config." + c for c in CONFIG_FIELDS},
         **{v: "r1." + k for k, v in R1_FIELDS.items()},
         DELIVERY_FROM: "dates.delivery.from"}
# The fields `verified` may name, as their sheet columns.
VERIFIABLE = {"vin": "vin_raw", "delivery": "delivery_raw"}


def name(field: str) -> str:
    """A sheet column as overrides.yaml names it."""
    return NAMES.get(field, field)


def _iso(v: Any) -> str:
    """A YAML date (PyYAML reads unquoted YYYY-MM-DD as one) back to its text."""
    return v.isoformat() if isinstance(v, date) else str(v)


def _day_text(v: Any) -> str:
    """YYYY-MM-DD -> M/D/YYYY, the sheet's own way of writing a date."""
    d = _as_date(v)
    assert d is not None
    return "%d/%d/%d" % (d.month, d.day, d.year)


def date_text(v: Any) -> str:
    """A v3 date (a day, a YYYY-MM month, or unknown) as a sheet cell."""
    s = _iso(v)
    if s == "unknown":
        return s
    if len(s) == 7:                              # YYYY-MM
        return "%s %s" % (calendar.month_name[int(s[5:])], s[:4])
    return _day_text(s)


def _span_text(span: Any, unit: str) -> str:
    lo, hi = (span, span) if isinstance(span, int) else span
    return ("%d %s" % (lo, unit) if lo == hi
            else "%d-%d %s" % (lo, hi, unit))


def delivery_text(v: Any) -> tuple[str, str | None]:
    """A v3 delivery estimate -> (the sheet text the delivery parser reads the
    same way, the M/D/YYYY date a window counts from or None)."""
    if not isinstance(v, dict):
        return date_text(v), None
    if "between" in v:
        a, b = (_as_date(x) for x in v["between"])
        if a is None or b is None or b < a:
            raise CurationError("delivery between %s and %s: the end is before "
                                "the start" % (a, b))
        return "%s - %s" % (_day_text(a), _day_text(b)), None
    unit = "weeks" if "weeks" in v else "days"
    frm = _day_text(v["from"]) if v.get("from") else None
    return _span_text(v[unit], unit), frm


def _flat_fields(spec: dict) -> dict[str, Any]:
    """An order entry's values (vin, location, purchase, dates, config, r1) as
    sheet column -> cell text."""
    out: dict[str, Any] = {}
    for k, col in TOP_FIELDS.items():
        if k in spec:
            out[col] = str(spec[k])
    dates = spec.get("dates") or {}
    for k in ("resv_date", "order_date"):
        if k in dates:
            out[DATE_FIELDS[k]] = date_text(dates[k])
    if "delivery" in dates:
        out["delivery_raw"], frm = delivery_text(dates["delivery"])
        if frm:
            out[DELIVERY_FROM] = frm
    for k, v in (spec.get("config") or {}).items():
        out[k] = str(v)
    for k, v in (spec.get("r1") or {}).items():
        out[R1_FIELDS[k]] = str(v)
    return out


def _meta(spec: dict) -> dict[str, Any]:
    out = {k: spec[k] for k in ("source", "as_of", "checked", "reason") if k in spec}
    ms = {k: v for k, v in (spec.get("dates") or {}).items() if k in MILESTONES}
    if ms:
        out["dates"] = ms
    return out


def _order(spec: dict) -> dict:
    return {**_meta(spec), **_flat_fields(spec)}


def _match(m: dict) -> dict[str, str]:
    """A deletion's match, as sheet column -> cell text."""
    out = {}
    for k, v in m.items():
        if k in DATE_FIELDS:
            out[DATE_FIELDS[k]] = date_text(v)
        else:
            out[TOP_FIELDS.get(k, k)] = str(v)
    return out


def _jsonable(v: Any) -> Any:
    """The loaded YAML with its dates as ISO text, which is what the schema
    describes: JSON (and so JSON Schema) has no date type."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def validate(data: Any, schema: dict) -> list[str]:
    """Every way `data` (the loaded overrides.yaml) breaks the schema, one line
    each, naming where."""
    v = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    out = []
    for err in sorted(v.iter_errors(_jsonable(data)), key=lambda e: list(e.path)):
        where = ".".join(str(p) for p in err.absolute_path) or "(top level)"
        # A value that fits none of a field's forms: the forms are in the schema
        # description, which says more than jsonschema's "not valid under any".
        hint = ""
        if err.validator == "oneOf" and isinstance(err.schema, dict):
            desc = err.schema.get("description")
            if desc:
                hint = " — expected " + desc[0].lower() + desc[1:]
        out.append("%s: %s%s" % (where, err.message, hint))
    return out


def load(data: Any, schema: dict) -> dict:
    """overrides.yaml (as loaded) -> its sections in the internal shape:
    {curation_version, overrides, additions, deletions: {orders, reservations},
    verified}. Raises CurationError if it is not a valid version-3 file."""
    data = data or {}
    version = data.get("curation_version", 1)
    if version != VERSION:
        raise CurationError(
            "overrides.yaml is curation_version %s; the build reads %d. Run "
            "./tools/migrate_curation.py --write to convert it." % (version, VERSION))
    problems = validate(data, schema)
    if problems:
        raise CurationError("overrides.yaml doesn't match overrides.schema.json:\n  "
                            + "\n  ".join(problems))
    dels = data.get("deletions") or {}
    return {
        "curation_version": version,
        "overrides": {u: _order(e) for u, e in (data.get("overrides") or {}).items()},
        "additions": {u: _order(e) for u, e in (data.get("additions") or {}).items()},
        "deletions": {
            sub: {u: {**_meta(e), **({"match": _match(e["match"])} if "match" in e
                                     else {})}
                  for u, e in (dels.get(sub) or {}).items()}
            for sub in ("orders", "reservations")},
        "verified": {u: {**_meta(e), "fields": [VERIFIABLE[f] for f in e["fields"]]}
                     for u, e in (data.get("verified") or {}).items()},
    }


def sort_key(target: Any) -> tuple[str, int]:
    """Where an entry's key sorts in its section: by username, case-insensitively
    (they match that way), and user#2 straight after user."""
    user, _, n = str(target).partition("#")
    return (user.lower(), int(n) if n.isdigit() else 0)


class Entry(NamedTuple):
    target: str           # username, or username#n for one of several orders
    body: Any             # what the entry does, with the META keys removed
    source: list[str]
    as_of: date | None
    reason: str
    checked: date | None = None
    dates: Mapping[str, date | None] = MappingProxyType({})

    @property
    def reviewed(self) -> date | None:
        """The latest date this entry is known to hold: as_of, or checked."""
        known = [d for d in (self.as_of, self.checked) if d is not None]
        return max(known) if known else None


def _as_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()


def split(target: Any, spec: Any) -> Entry:
    """One YAML entry -> Entry. Non-mapping values (a deletion's plain reason
    string, a verified entry's list of fields) carry no meta."""
    if not isinstance(spec, dict):
        return Entry(str(target), spec, [], None, "")
    src = spec.get("source")
    sources = ([str(s).strip() for s in src] if isinstance(src, list)
               else [str(src).strip()] if src else [])
    body = {k: v for k, v in spec.items() if k not in META}
    dates = {k: _as_date(v) for k, v in (spec.get("dates") or {}).items()}
    return Entry(str(target), body, sources, _as_date(spec.get("as_of")),
                 str(spec.get("reason") or "").strip(),
                 _as_date(spec.get("checked")), dates)


def entries(section: dict | None) -> list[Entry]:
    return [split(t, s) for t, s in (section or {}).items()]


def _valid_source(s: str) -> bool:
    return s.startswith(("http://", "https://")) or s.lower().startswith("inferred")


def provenance_problems(section_label: str, items: list[Entry],
                        today: date) -> list[str]:
    """Why each entry's provenance is incomplete or wrong (empty when fine)."""
    out = []
    for e in items:
        if not e.source:
            out.append("%s %s: no source" % (section_label, e.target))
        for s in e.source:
            if not _valid_source(s):
                out.append("%s %s: source %r is neither a URL nor 'inferred …'"
                           % (section_label, e.target, s))
        # A dates-only entry overrides nothing, so as_of has no job there: it
        # anchors the stale check for overridden fields, and dates a final value
        # that only curation supplied. The milestone dates carry the timing.
        dates_only = bool(e.dates) and not e.body
        if e.as_of is None and not dates_only:
            out.append("%s %s: no as_of date" % (section_label, e.target))
        elif e.as_of is not None and e.as_of > today:
            out.append("%s %s: as_of %s is in the future"
                       % (section_label, e.target, e.as_of))
        if e.checked and e.as_of and e.checked < e.as_of:
            out.append("%s %s: checked %s is before as_of %s"
                       % (section_label, e.target, e.checked, e.as_of))
        for k in e.dates:
            if k not in MILESTONES:
                out.append("%s %s: unknown milestone '%s' (known: %s)"
                           % (section_label, e.target, k, ", ".join(MILESTONES)))
    return out


def check(version: int, sections: dict[str, dict | None], today: date) -> None:
    """Raise CurationError listing every entry without a valid source and as_of.
    (The schema requires a source; the rest — as_of except on a dates-only entry,
    dates that aren't in the future — is checked here.)"""
    problems = [p for label, sec in sections.items()
                for p in provenance_problems(label, entries(sec), today)]
    if problems:
        raise CurationError(
            "overrides.yaml has entries without provenance:\n  "
            + "\n  ".join(problems))
