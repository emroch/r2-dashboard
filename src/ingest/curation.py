"""Provenance and timing for the manual curation in overrides.yaml.

Data layer stage 2 and #99 (docs/data-layer.md). Every entry, in every section,
may carry these META keys alongside what it edits:

  source   where the information came from: a forum URL (or a list of them), or
           text starting with "inferred" for a judgment made from the data itself
  as_of    when we LEARNED it (the post, or the curation date). It anchors the
           stale-override check: a sheet change after it may mean the override
           is out of date
  checked  optional, a later date on which someone confirmed the override still
           holds; the stale check then counts sheet changes after this instead
  reason   a short note, shown with the entry in the report
  dates    optional milestone dates for the order's FINAL values (#99):
           vin_assigned, delivery_scheduled. May stand alone, with no value
           overridden, to date values the sheet already has (ingest/milestones.py)

They are never sheet fields, so they are split off here before anything is
applied. While the file is at curation_version 1 (the format before this stage)
they are optional. At version 2, set by tools/migrate_curation.py, every entry
must have a source and an as_of, and a missing one stops the build: a correction
nobody can trace, published on the dashboard, is the thing this exists to prevent.
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Mapping, NamedTuple

META = ("source", "as_of", "checked", "reason", "dates")
MILESTONES = ("vin_assigned", "delivery_scheduled")


class CurationError(ValueError):
    """overrides.yaml is missing provenance that its version requires."""


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
        if e.as_of is None:
            out.append("%s %s: no as_of date" % (section_label, e.target))
        elif e.as_of > today:
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
    """At version 2, raise CurationError listing every entry without a valid
    source and as_of. Version 1 files predate the fields, so nothing is checked."""
    if version < 2:
        return
    problems = [p for label, sec in sections.items()
                for p in provenance_problems(label, entries(sec), today)]
    if problems:
        raise CurationError(
            "overrides.yaml (curation_version 2) has entries without provenance:\n  "
            + "\n  ".join(problems))
