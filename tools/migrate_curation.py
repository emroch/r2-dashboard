#!/usr/bin/env python3
"""Migrate src/conf/overrides.yaml to curation_version 2 (issue #82).

Version 2 gives every entry a `source` and an `as_of` (see ingest/curation.py).
This script fills them in from what the file already records, editing the text
so every other comment and the layout survive. PyYAML would drop them.

  source  the forum URL comment lines directly above an entry are lifted into
          `source:` (a list when there are several). The rest of the comment
          stays as written.
  as_of   the date git first committed the entry's key line (git blame).
          Uncommitted lines get today's date.

An entry with no URL is left without a source and listed at the end, so a person
can fill it in. Nothing is guessed. The script only writes `curation_version: 2`
once every entry has both fields, because version 2 makes a missing one a build
error.

  ./tools/migrate_curation.py            dry run: report what would change
  ./tools/migrate_curation.py --write    rewrite the file

Before writing, it checks that the rewritten YAML holds exactly the same
corrections as the original once the new fields are set aside.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "src" / "conf" / "overrides.yaml"
META = ("source", "as_of", "reason")

# A URL alone on a comment line, optionally after a short label ("order: https://…").
_URL_LINE = re.compile(r"^\s*#\s*(?:([\w ]{1,20}):\s*)?(https?://\S+)\s*$")
_TOP = re.compile(r"^([a-z_]+):")
_SUB = re.compile(r"^  (orders|reservations):\s*$")


def _blame_dates(path: Path) -> dict[int, date]:
    """1-based line number -> date that line was first committed."""
    out = subprocess.run(["git", "blame", "--porcelain", str(path)], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    dates, commit_time, line = {}, {}, None
    cur = None
    for ln in out.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            cur, line = m.group(1), int(m.group(2))
            continue
        if ln.startswith("author-time ") and cur:
            commit_time[cur] = int(ln.split()[1])
        if ln.startswith("\t") and line is not None and cur:
            t = commit_time.get(cur)
            # The all-zero hash is "not committed yet".
            dates[line] = (date.today() if cur == "0" * 40 or t is None
                           else datetime.fromtimestamp(t).date())
            line = None
    return dates


def _strip_meta(data):
    """The corrections themselves, with the provenance fields set aside."""
    def clean(v):
        if isinstance(v, dict):
            body = {k: x for k, x in v.items() if k not in META}
            # A verified entry migrates from a list to {fields: [...]}.
            if set(body) == {"fields"}:
                return body["fields"]
            return body
        return v
    out = {}
    for sec, body in (data or {}).items():
        if sec == "curation_version":
            continue
        if sec == "deletions":
            out[sec] = {k: {u: clean(e) for u, e in (v or {}).items()}
                        for k, v in (body or {}).items()}
        elif isinstance(body, dict):
            out[sec] = {u: clean(e) for u, e in body.items()}
        else:
            out[sec] = body
    return out


def migrate(text: str, dates: dict[int, date]):
    """Return (new_text, migrated, unresolved), where each list holds
    (section, user) pairs."""
    lines = text.split("\n")
    out: list[str] = []
    migrated, unresolved = [], []
    section, sub = None, None
    pending: list[int] = []        # indices in `out` of comment lines above an entry
    for n, ln in enumerate(lines, start=1):
        m = _TOP.match(ln)
        if m:
            section, sub, pending = m.group(1), None, []
            out.append(ln)
            continue
        m = _SUB.match(ln)
        if m and section == "deletions":
            sub, pending = m.group(1), []
            out.append(ln)
            continue
        indent = 4 if section == "deletions" else 2
        stripped = ln.strip()
        if stripped.startswith("#") and ln.startswith(" " * indent) \
                and not ln.startswith(" " * (indent + 2)):
            pending.append(len(out))
            out.append(ln)
            continue
        is_key = (section in ("overrides", "additions", "verified")
                  or (section == "deletions" and sub)) \
            and re.match(r"^ {%d}[^ #].*:\s*(\S.*)?$" % indent, ln)
        if not is_key:
            if stripped:
                pending = []
            out.append(ln)
            continue
        user = ln.strip().split(":")[0].strip().strip('"\'')
        label = "%s.%s" % (section, sub) if sub else section
        # The entry's own lines, to keep a re-run from adding the fields twice
        # (it is re-run after unresolved entries are filled in by hand).
        body = []
        for later in lines[n:]:
            if later.strip() and not later.startswith(" " * (indent + 1)):
                break
            body.append(later)
        has_source = any(re.match(r"^\s+source:", b) for b in body)
        has_as_of = any(re.match(r"^\s+as_of:", b) for b in body)
        # (url, label) — a label like "order" is kept as a comment on its URL.
        urls = [(m.group(2), m.group(1)) for i in pending
                for m in [_URL_LINE.match(out[i])] if m]
        if not has_source:
            # Lift the URL lines out of the comment; keep the rest of it.
            for i in sorted((i for i in pending if _URL_LINE.match(out[i])),
                            reverse=True):
                del out[i]
        pending = []
        pad = " " * (indent + 2)
        head, _, rest = ln.partition(":")
        rest = rest.strip()
        if section == "verified" and rest.startswith("["):
            # `user: [vin_raw]` -> a mapping with the list under `fields`.
            out.append(head + ":")
            out.append("%sfields: %s" % (pad, rest))
        else:
            out.append(ln)
        if has_source:
            migrated.append((label, user))
        elif urls:
            def tag(label):
                return "  # %s" % label if label else ""
            if len(urls) == 1:
                out.append("%ssource: %s%s" % (pad, urls[0][0], tag(urls[0][1])))
            else:
                out.append("%ssource:" % pad)
                out.extend("%s  - %s%s" % (pad, u, tag(lb)) for u, lb in urls)
            migrated.append((label, user))
        else:
            unresolved.append((label, user))
        if not has_as_of:
            out.append('%sas_of: "%s"'
                       % (pad, dates.get(n, date.today()).isoformat()))
    return "\n".join(out), migrated, unresolved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite overrides.yaml")
    args = ap.parse_args()

    text = FILE.read_text()
    original = yaml.safe_load(text)
    if int(original.get("curation_version", 1)) >= 2:
        print("overrides.yaml is already at curation_version 2")
        return 0
    new, migrated, unresolved = migrate(text, _blame_dates(FILE))
    if _strip_meta(yaml.safe_load(new)) != _strip_meta(original):
        print("error: the rewrite changed what the corrections say — not writing",
              file=sys.stderr)
        return 1
    if not unresolved:
        new = new.replace("\noverrides:\n", "\ncuration_version: 2\n\noverrides:\n", 1)

    print("migrated with a source: %d" % len(migrated))
    print("no URL found:           %d" % len(unresolved))
    for label, user in unresolved:
        print("  %-24s %s" % (label, user))
    if unresolved:
        print("Give these a `source:` (a URL, or 'inferred — <why>'), then re-run;"
              " curation_version 2 is set once none are left.")
    if args.write:
        FILE.write_text(new)
        print("wrote %s" % FILE.relative_to(ROOT))
    else:
        print("dry run — pass --write to rewrite the file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
