#!/usr/bin/env python3
"""Bring src/conf/overrides.yaml to curation_version 3 (issue #166), and keep it tidy.

Version 3 (conf/overrides.schema.json is the full reference):

  * every date is ISO, under `dates:`: resv_date, order_date (a day, a YYYY-MM
    month, or unknown), the milestones vin_assigned and delivery_scheduled, and
    the delivery estimate — a date, a month, unknown, {between: [a, b]}, or
    {weeks: [lo, hi]} / {days: …} with an optional `from:`;
  * the build is under `config:` (trim, launch, color, interior, wheels,
    autonomy, tow, spare), R1 ownership under `r1:` (owner, model);
  * vin_raw, loc_raw, buylease are vin, location, purchase;
  * deletion matches and `verified` fields use the same names;
  * a field with no value is dropped: in an addition a missing field is already
    unknown, and in an override a blank was ignored anyway.

Rerunnable, on a version-2 or an already-migrated file. Each run also puts the
file in its canonical form: entries sorted by username within each section
(case-insensitively, user#2 straight after user), fields in a fixed order, one
quoting style, and the schema line at the top for editors. Comments survive
the move: a comment above an entry travels with it, and one above or beside a
field travels with that field to its new place.

Text the old format accepted but v3 has no form for (a delivery estimate or a
date that doesn't parse) is listed and nothing is written; fix those entries by
hand and re-run.

Before writing, it checks that the rewritten file holds the same corrections as
the original: every value parses to the same thing, the provenance is unchanged.

  ./tools/migrate_curation.py            dry run: report what would change
  ./tools/migrate_curation.py --write    rewrite the file
  ./tools/migrate_curation.py --check    exit 1 if the file isn't canonical
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "src" / "conf" / "overrides.yaml"
SCHEMA_LINE = "# yaml-language-server: $schema=overrides.schema.json"

# The parsers read config, which reads overrides.yaml, which may not be v3 yet.
os.environ["R2_CURATION_MIGRATE"] = "1"
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd  # noqa: E402

from config import CURATION_SCHEMA, UNKNOWN_TOKENS  # noqa: E402
from ingest import curation, parsing  # noqa: E402

SECTIONS = ("overrides", "additions", "deletions", "verified")
# v2 field -> its v3 path. A v3 file's paths map to themselves.
V2_PATHS: dict[str, tuple[str, ...]] = {
    "vin_raw": ("vin",), "loc_raw": ("location",), "buylease": ("purchase",),
    "resv_raw": ("dates", "resv_date"), "order_raw": ("dates", "order_date"),
    "delivery_raw": ("dates", "delivery"),
    "r1_owner": ("r1", "owner"), "r1_model": ("r1", "model"),
    **{c: ("config", c) for c in curation.CONFIG_FIELDS},
}
# v3 match keys are flat: a config field or a date matches under its own name.
MATCH_NAMES = {"vin_raw": "vin", "loc_raw": "location", "buylease": "purchase",
               "resv_raw": "resv_date", "order_raw": "order_date",
               "delivery_raw": "delivery"}
VERIFIED_NAMES = {"vin_raw": "vin", "delivery_raw": "delivery"}
# The canonical order of an entry's keys.
ORDER = ("source", "as_of", "checked", "reason", "vin", "location", "purchase",
         "dates", "config", "r1", "match", "fields")
DATE_ORDER = ("resv_date", "order_date", "vin_assigned", "delivery_scheduled",
              "delivery")
R1_ORDER = ("owner", "model")
MATCH_ORDER = ("orig_num", "vin", "location", "purchase", "resv_date", "order_date",
               *curation.CONFIG_FIELDS)
# A comment block this migration retires: partly-reported orders are ordinary
# additions now (a blank charts as Unknown), so they need no section of their own.
RETIRED = re.compile(r"^\s*# Partly-reported orders\.")

_TOP = re.compile(r"^([a-z_]+):(.*)$")
_URL = re.compile(r"^https?://[^\s'\"#]+$")


class MigrationError(ValueError):
    pass


# --- Reading: entries, with their comments -----------------------------------

def _split_comment(line: str) -> tuple[str, str]:
    """A line -> (content, inline comment or ""), honouring quotes."""
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip(), line[i:].strip()
    return line.rstrip(), ""


class Block:
    """One entry as written: the comments above it, its key line, the comments
    inside it by the path of the line they belong to."""

    def __init__(self, key: str, above: list[str]):
        self.key = key                      # the username as written (unquoted)
        self.raw_key = key                  # the key's own text, quotes and all
        self.above = above                  # comment lines, stripped
        self.lead: dict[tuple, list[str]] = {}   # comments above a field
        self.inline: dict[tuple, str] = {}       # a comment beside a field
        self.loose: list[str] = []               # comments that lost their field


def _read_body(block: Block, lines: list[str], indent: int) -> None:
    stack: list[tuple[int, Any]] = []       # (indent, key or list index)
    counters: dict[tuple, int] = {}
    pending: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        content, comment = _split_comment(ln)
        if not content.strip():
            pending.append(comment)
            continue
        ind = len(content) - len(content.lstrip())
        while stack and stack[-1][0] >= ind:
            stack.pop()
        parent = tuple(k for _, k in stack)
        text = content.strip()
        if text.startswith("- "):
            n = counters.get(parent, 0)
            counters[parent] = n + 1
            path = parent + (n,)
            stack.append((ind, n))
        else:
            key = text.split(":", 1)[0].strip().strip("\"'")
            path = parent + (key,)
            stack.append((ind, key))
        if pending:
            block.lead.setdefault(path, []).extend(pending)
            pending = []
        if comment:
            block.inline[path] = comment
    block.loose.extend(pending)


def read(text: str) -> tuple[list[str], dict[str, Any]]:
    """The file -> (its header comment lines, {section: [Block] or for deletions
    {sub: [Block]}, plus "_above" comments above each section})."""
    lines = text.split("\n")
    header: list[str] = []
    i = 0
    # The header: everything up to the first section or curation_version line.
    while i < len(lines):
        m = _TOP.match(lines[i])
        if m and (m.group(1) in SECTIONS or m.group(1) == "curation_version"):
            break
        header.append(lines[i])
        i += 1
    # Comments directly above the first key belong to the header too.
    out: dict[str, Any] = {"_above": {}}
    pending: list[str] = []
    section: str | None = None
    sub: str | None = None
    retiring = False
    cur: Block | None = None
    body: list[str] = []
    entry_indent = 2

    def close():
        nonlocal cur, body
        if cur is not None and section is not None:
            _read_body(cur, body, entry_indent)
            target = out[section] if sub is None else out[section][sub]
            target.append(cur)
        cur, body = None, []

    for ln in lines[i:]:
        m = _TOP.match(ln)
        if m:
            close()
            if m.group(1) == "curation_version":
                continue
            section, sub = m.group(1), None
            if section not in SECTIONS:
                raise MigrationError("unknown top-level key %r" % section)
            out[section] = {} if section == "deletions" else []
            out["_above"][section] = [c.strip() for c in pending]
            pending, retiring = [], False
            continue
        if section is None:
            if ln.strip().startswith("#"):
                pending.append(ln)
            continue
        stripped = ln.strip()
        if ln.startswith("#"):
            # A comment in column 0 introduces the next section (or entry).
            close()
            pending.append(stripped)
            continue
        if section == "deletions" and re.match(r"^  (orders|reservations):\s*$", ln):
            close()
            sub = stripped[:-1]
            out[section][sub] = []
            pending = []
            continue
        entry_indent = 4 if section == "deletions" else 2
        own_level = ln.startswith(" " * entry_indent) and \
            not ln.startswith(" " * (entry_indent + 1))
        if not stripped:
            continue
        if own_level and stripped.startswith("#"):
            # A comment at entry level opens the comments above the NEXT entry.
            if cur is not None:
                close()
            if RETIRED.match(ln):
                retiring = True
            if retiring:
                if re.match(r"^\s*#\s*-{5,}\s*$", ln):
                    retiring = False
                continue
            pending.append(stripped)
            continue
        if own_level:
            close()
            content, comment = _split_comment(ln)
            raw_key = content.strip()
            raw_key = raw_key[:-1] if raw_key.endswith(":") else raw_key.split(":")[0]
            key = raw_key.strip().strip("\"'")
            cur = Block(key, pending + ([comment] if comment else []))
            cur.raw_key = raw_key.strip()
            pending = []
            continue
        body.append(ln)
    close()
    if pending:
        out["_trailing"] = pending
    return header, out


# --- Converting values -------------------------------------------------------

def _iso(v: Any) -> str:
    return v.date().isoformat() if isinstance(v, datetime) else \
        v.isoformat() if isinstance(v, date) else str(v).strip()


_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")


def v3_date(v: Any, where: str) -> str:
    """A reservation/order date as written in v2 (or already v3) -> v3 text."""
    s = _iso(v)
    if re.match(r"^\d{4}-\d{2}(-\d{2})?$", s) or s == "unknown":
        return s
    if s.lower() in UNKNOWN_TOKENS:
        return "unknown"
    m = _MONTH_YEAR.match(s)
    if m:
        for i, names in enumerate(zip(_MONTHS_LONG, _MONTHS_SHORT), start=1):
            if m.group(1).lower() in (names[0].lower(), names[1].lower()):
                return "%s-%02d" % (m.group(2), i)
    ts = parsing.parse_simple_date(s)
    if pd.isna(ts):
        raise MigrationError("%s: %r is not a date v3 can write" % (where, s))
    return ts.date().isoformat()


_MONTHS_LONG = ("January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December")
_MONTHS_SHORT = tuple(m[:3] for m in _MONTHS_LONG) + ("Sept",)


def v3_delivery(v: Any, where: str) -> Any:
    """A delivery estimate as written in v2 (or already v3) -> its v3 value."""
    if isinstance(v, dict):
        return v
    s = _iso(v)
    if re.match(r"^\d{4}-\d{2}(-\d{2})?$", s) or s == "unknown":
        return s
    low = s.lower()
    for _name, rule in parsing._DELIVERY_RULES:
        res = rule(s, low)
        if res is None:
            continue
        if isinstance(res, parsing._Veto):
            return "unknown"
        if isinstance(res, (parsing._Weeks, parsing._Days)):
            unit = "weeks" if isinstance(res, parsing._Weeks) else "days"
            return {unit: res.lo if res.lo == res.hi else [res.lo, res.hi]}
        break
    p = parsing.parse_delivery(s, pd.NaT)
    if p["type"] == "explicit":
        return p["est"].date().isoformat()
    if p["type"] == "month":
        return p["est"].strftime("%Y-%m")
    if p["type"] == "range":
        return {"between": [p["min"].date().isoformat(), p["max"].date().isoformat()]}
    raise MigrationError("%s: delivery %r has no v3 form (it doesn't parse) — "
                         "write what it means by hand" % (where, s))


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == {}


def convert_order(spec: dict, where: str) -> dict:
    """A v2 (or v3) override/addition -> v3, keys in no particular order."""
    out: dict[str, Any] = {}
    for k, v in spec.items():
        if _blank(v):
            continue
        if k in ("source", "as_of", "checked", "reason"):
            out[k] = v
        elif k == "dates":
            for dk, dv in v.items():
                if _blank(dv):
                    continue
                if dk in curation.MILESTONES:
                    out.setdefault("dates", {})[dk] = _iso(dv)
                elif dk == "delivery":
                    out.setdefault("dates", {})[dk] = v3_delivery(dv, where)
                else:
                    out.setdefault("dates", {})[dk] = v3_date(dv, where)
        elif k in ("config", "r1"):
            for sk, sv in v.items():
                if not _blank(sv):
                    out.setdefault(k, {})[sk] = str(sv)
        elif k in V2_PATHS:
            path = V2_PATHS[k]
            if path == ("dates", "delivery"):
                val: Any = v3_delivery(v, where)
            elif path[0] == "dates":
                val = v3_date(v, where)
            else:
                val = str(v).strip()
            if len(path) == 1:
                out[path[0]] = val
            else:
                out.setdefault(path[0], {})[path[1]] = val
        elif k in ("vin", "location", "purchase"):
            out[k] = str(v).strip()
        else:
            raise MigrationError("%s: unknown field %r" % (where, k))
    return out


def convert_deletion(spec: Any, where: str) -> dict:
    if not isinstance(spec, dict):
        raise MigrationError("%s: a deletion needs source/as_of/reason (v2 already "
                             "required them)" % where)
    out: dict[str, Any] = {k: v for k, v in spec.items()
                           if k in ("source", "as_of", "checked", "reason")
                           and not _blank(v)}
    for k, v in (spec.get("match") or {}).items():
        name = MATCH_NAMES.get(k, k)
        if name in ("resv_date", "order_date"):
            v = v3_date(v, where)
        out.setdefault("match", {})[name] = v if name.endswith("_date") else str(v)
    extra = set(spec) - {"source", "as_of", "checked", "reason", "match"}
    if extra:
        raise MigrationError("%s: unknown keys %s" % (where, sorted(extra)))
    return out


def convert_verified(spec: Any, where: str) -> dict:
    if not isinstance(spec, dict):
        raise MigrationError("%s: a verified entry needs source/as_of" % where)
    out = {k: v for k, v in spec.items() if k != "fields" and not _blank(v)}
    out["fields"] = [VERIFIED_NAMES.get(f, f) for f in spec.get("fields") or []]
    return out


# Where a comment written beside a v2 field lands in v3.
def v3_path(path: tuple) -> tuple:
    if not path:
        return path
    head = path[0]
    if head in V2_PATHS:
        return V2_PATHS[head] + path[1:]
    if head == "match" and len(path) > 1 and path[1] in MATCH_NAMES:
        return ("match", MATCH_NAMES[path[1]]) + path[2:]
    return path


# --- Writing -----------------------------------------------------------------

def scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = _iso(v)
    if re.match(r"^\d{4}-\d{2}(-\d{2})?$", s) or s == "unknown":
        return s            # a YAML date (or a v3 month, or unknown), unquoted
    if _URL.match(s):
        return s
    return json.dumps(s, ensure_ascii=False)


def flow(v: Any) -> str:
    if isinstance(v, dict):
        return "{%s}" % ", ".join("%s: %s" % (k, flow(x)) for k, x in v.items())
    if isinstance(v, list):
        return "[%s]" % ", ".join(flow(x) for x in v)
    return scalar(v)


def _ordered(d: dict, order: tuple) -> list:
    rank = {k: i for i, k in enumerate(order)}
    return sorted(d.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))


def emit(block: Block, data: dict, indent: int) -> list[str]:
    pad = " " * indent
    out = ["%s%s" % (pad, c) for c in block.above]
    out.append("%s%s:" % (pad, block.raw_key))
    used: set[tuple] = set()
    inner = " " * (indent + 2)

    def line(path: tuple, text: str, ind: str) -> None:
        out.extend(ind + c for c in block.lead.get(path, []))
        note = block.inline.get(path)
        out.append(ind + text + ("  " + note if note else ""))
        used.add(path)

    for k, v in _ordered(data, ORDER):
        if k == "source" and isinstance(v, list):
            line((k,), "source:", inner)
            for n, u in enumerate(v):
                line((k, n), "- " + scalar(u), inner + "  ")
        elif k in ("dates", "config", "r1", "match"):
            order = {"dates": DATE_ORDER, "config": curation.CONFIG_FIELDS,
                     "r1": R1_ORDER, "match": MATCH_ORDER}[k]
            line((k,), k + ":", inner)
            for sk, sv in _ordered(v, order):
                line((k, sk), "%s: %s" % (sk, flow(sv)), inner + "  ")
        elif k == "fields":
            line((k,), "fields: " + flow(v), inner)
        else:
            line((k,), "%s: %s" % (k, scalar(v)), inner)
    lost = [c for p, cs in block.lead.items() if p not in used for c in cs]
    lost += [c for p, c in block.inline.items() if p not in used]
    lost += block.loose
    if lost:
        # Their field is gone (a blank one, dropped): keep them on the entry.
        out[len(block.above) + 1:len(block.above) + 1] = [inner + c for c in lost]
    return out


def _sorted(blocks: list[Block]) -> list[Block]:
    return sorted(blocks, key=lambda b: curation.sort_key(b.key))


def migrate(text: str) -> tuple[str, dict]:
    """Return (the canonical v3 text, the loaded original)."""
    original = yaml.safe_load(text) or {}
    version = int(original.get("curation_version", 1))
    if version < 2:
        raise MigrationError("overrides.yaml is curation_version %d; migrate it to 2 "
                             "first (git show 9c37f57:tools/migrate_curation.py)"
                             % version)
    header, blocks = read(text)
    # Re-key the comments to their v3 paths.
    for sec in SECTIONS:
        group = blocks.get(sec)
        if group is None:
            continue
        for bl in (group if isinstance(group, list)
                   else [b for sub in group.values() for b in sub]):
            bl.lead = {v3_path(p): c for p, c in bl.lead.items()}
            bl.inline = {v3_path(p): c for p, c in bl.inline.items()}

    while header and not header[0].strip():
        header.pop(0)
    if not header or header[0] != SCHEMA_LINE:
        header.insert(0, SCHEMA_LINE)
    while header and not header[-1].strip():
        header.pop()
    out = header + ["", "curation_version: %d" % curation.VERSION]

    def section(name: str, entries: dict | None, blist: list[Block], indent: int,
                convert) -> list[str]:
        lines: list[str] = []
        entries = entries or {}
        if len(blist) != len(entries):
            raise MigrationError("%s: read %d entries from the text but YAML has %d "
                                 "— an unusual layout this tool can't follow"
                                 % (name, len(blist), len(entries)))
        for bl in _sorted(blist):
            if bl.key not in entries:
                raise MigrationError("%s: entry %r not found in the YAML"
                                     % (name, bl.key))
            lines += emit(bl, convert(entries[bl.key], "%s %s" % (name, bl.key)),
                          indent)
        return lines

    for sec in SECTIONS:
        if sec not in blocks:
            continue
        out.append("")
        out += blocks["_above"].get(sec, [])
        data = original.get(sec)
        if sec == "deletions":
            out.append("deletions:")
            for sub in ("orders", "reservations"):
                if sub not in blocks[sec]:
                    continue
                subdata = (data or {}).get(sub)
                if not subdata:
                    out.append("  %s: {}" % sub)
                    continue
                out.append("  %s:" % sub)
                out += section("deletions.%s" % sub, subdata, blocks[sec][sub], 4,
                               convert_deletion)
            continue
        if not data:
            out.append("%s: {}" % sec)
            continue
        out.append("%s:" % sec)
        out += section(sec, data, blocks[sec], 2,
                       convert_verified if sec == "verified" else convert_order)
    out += blocks.get("_trailing", [])
    return "\n".join(out) + "\n", original


# --- Checking the rewrite ----------------------------------------------------

def _internal(data: dict) -> dict:
    """Either version, as {section: {user: {sheet column: parsed value}}}, so the
    two can be compared by what they mean, not how they're written."""
    def parse(field: str, v: Any, frm: Any = None) -> Any:
        if field in ("resv_raw", "order_raw"):
            ts = parsing.parse_simple_date(str(v))
            return str(v).lower() if pd.isna(ts) else ts
        if field == "delivery_raw":
            anchor = parsing.parse_simple_date(frm) if frm else pd.NaT
            p = parsing.parse_delivery(str(v), anchor)
            return (p["type"], p["min"], p["max"]) if p["type"] != "unknown" else "?"
        return str(v)

    def meta(e: dict) -> dict:
        m = {k: (_iso(e[k]) if k in ("as_of", "checked") else e[k])
             for k in ("source", "as_of", "checked", "reason") if not _blank(e.get(k))}
        ds = {k: _iso(v) for k, v in (e.get("dates") or {}).items()
              if k in curation.MILESTONES and not _blank(v)}
        if ds:
            m["dates"] = ds
        return m

    if int(data.get("curation_version", 1)) >= 3:
        flat = curation.load(data, CURATION_SCHEMA)
        orders = {s: flat[s] for s in ("overrides", "additions")}
        dels = flat["deletions"]
        ver = flat["verified"]
    else:
        orders = {s: {u: e or {} for u, e in (data.get(s) or {}).items()}
                  for s in ("overrides", "additions")}
        d = data.get("deletions") or {}
        dels = {sub: d.get(sub) or {} for sub in ("orders", "reservations")}
        ver = data.get("verified") or {}
    out: dict = {}
    for s, entries in orders.items():
        out[s] = {}
        for u, e in entries.items():
            frm = e.get(curation.DELIVERY_FROM)
            vals = {k: parse(k, v, frm) for k, v in e.items()
                    if k not in curation.META and k != curation.DELIVERY_FROM
                    and not _blank(v)}
            out[s][u] = (meta(e), vals)
    for sub, entries in dels.items():
        out["deletions." + sub] = {
            u: (meta(e), {k: parse(k, v) for k, v in (e.get("match") or {}).items()})
            for u, e in entries.items()}
    out["verified"] = {u: (meta(e), sorted(e.get("fields") or []))
                       for u, e in ver.items()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="rewrite overrides.yaml")
    g.add_argument("--check", action="store_true",
                   help="exit 1 if overrides.yaml isn't in canonical v3 form")
    args = ap.parse_args()

    text = FILE.read_text()
    try:
        new, original = migrate(text)
        migrated = yaml.safe_load(new)
        problems = curation.validate(migrated, CURATION_SCHEMA)
        if problems:
            raise MigrationError("the rewrite doesn't match the schema:\n  "
                                 + "\n  ".join(problems))
        before, after = _internal(original), _internal(migrated)
    except (MigrationError, curation.CurationError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    diffs = ["%s %s" % (s, u) for s in sorted(set(before) | set(after))
             for u in sorted(set(before.get(s, {})) | set(after.get(s, {})))
             if before.get(s, {}).get(u) != after.get(s, {}).get(u)]
    if diffs:
        print("error: the rewrite changed what these entries say — not writing:\n  "
              + "\n  ".join(diffs), file=sys.stderr)
        return 1
    if new == text:
        print("overrides.yaml is already canonical curation_version %d"
              % curation.VERSION)
        return 0
    if args.check:
        print("overrides.yaml isn't canonical: run ./tools/migrate_curation.py --write",
              file=sys.stderr)
        return 1
    n = sum(len(v) for k, v in before.items())
    print("%d entries, same corrections; %d lines -> %d"
          % (n, text.count("\n"), new.count("\n")))
    if args.write:
        FILE.write_text(new)
        print("wrote %s" % FILE.relative_to(ROOT))
    else:
        print("dry run — pass --write to rewrite the file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
