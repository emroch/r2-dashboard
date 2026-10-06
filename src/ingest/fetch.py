"""Live-sheet fetching with timestamped local caching and change detection.

The Google Sheets CSV export sends no Last-Modified/ETag (and Cache-Control:
no-store), so "did the data change?" is detected by diffing each fetch against
the newest cache. Caches live under data/raw/.

"The newest cache" means the newest one known anywhere: on disk, or committed on
origin/main. A branch that hasn't merged main lately doesn't have main's latest
caches on disk, and comparing only against its own older ones made every local
build there "find" data main already had and write it again under a new
timestamp (six duplicate caches reached main in one day that way). Reading
main's caches through git needs no network: it uses whatever origin/main the
last `git fetch` saw, and does nothing when there is no git or no such ref.
"""
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime

from config import (CACHE_TS_FMT, DATA_RAW, EXPORT_URL, NOW, VIEW_URL)

# The ref whose committed caches count as already known.
KNOWN_REF = "origin/main"


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _norm_for_diff(text):
    """Content signature that ignores trailing whitespace and blank tail lines,
    so a cosmetic export difference is not mistaken for a real data change."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _cache_files(slug):
    """(timestamp, path) for a slug's caches, newest first."""
    raw_dir = str(DATA_RAW)
    pat = re.compile(re.escape(slug) + r"_(\d{8}-\d{6})\.csv$")
    out = [(m.group(1), os.path.join(raw_dir, fn))
           for fn in os.listdir(raw_dir) for m in [pat.match(fn)] if m]
    out.sort(reverse=True)
    return out


def _git(*args, cwd=None):
    """stdout of a git command in the repo, or None if git or the ref isn't there."""
    try:
        out = subprocess.run(["git", *args], cwd=cwd or str(DATA_RAW), timeout=15,
                             capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _committed_caches(slug, ref=KNOWN_REF):
    """(timestamp, "ref:path") for the slug's caches committed on `ref`, newest
    first. Empty without git or the ref."""
    root = _git("rev-parse", "--show-toplevel")
    if not root:
        return []
    # Both resolved: a symlinked path (macOS's /var -> /private/var) would
    # otherwise give a relative path that leaves the repo.
    raw = os.path.relpath(os.path.realpath(str(DATA_RAW)),
                          os.path.realpath(root.strip()))
    listing = _git("ls-tree", "--name-only", ref, raw + "/", cwd=root.strip())
    pat = re.compile(re.escape(slug) + r"_(\d{8}-\d{6})\.csv$")
    out = [(m.group(1), "%s:%s" % (ref, path))
           for path in (listing or "").split() for m in [pat.search(path)] if m]
    out.sort(reverse=True)
    return out


def known_caches(slug):
    """(timestamp, source) for every cache of a sheet known here, newest first:
    the files on disk, plus any committed on KNOWN_REF that aren't on disk (as
    "origin/main:<path>"). The fetch compares against the newest of these, and
    the history replay reads all of them, so both see the same snapshots."""
    local = _cache_files(slug)
    on_disk = {ts for ts, _ in local}
    out = local + [(ts, ref) for ts, ref in _committed_caches(slug)
                   if ts not in on_disk]
    out.sort(reverse=True)
    return out


def read_cache(source):
    """A cache's text, from a path on disk or a "ref:path" committed in git."""
    if os.path.exists(source):
        with open(source) as fh:
            return fh.read()
    root = (_git("rev-parse", "--show-toplevel") or "").strip()
    text = _git("show", source, cwd=root or None)
    if text is None:
        raise FileNotFoundError(source)
    return text


def fetch_sheet(key, gid, slug, label, offline=False):
    """Fetch a sheet's CSV export, with local caching and change detection.

    The export endpoint sends no Last-Modified/ETag (and Cache-Control:
    no-store), so we detect "did the data change?" by diffing the fetch against
    the newest known cache (known_caches). A new timestamped cache is written
    only when the content differs, so the newest cache's timestamp is when the
    data last updated. Falls back to the newest cache if the live fetch fails,
    and uses it without trying when `offline` (nothing is written either way).
    Returns (text, meta) with meta = live/offline/fetched_at/updated_at/changed/
    view_url/cache.
    """
    view = VIEW_URL % (key, gid)
    caches = known_caches(slug)
    meta = {"label": label, "view_url": view, "live": False, "offline": offline,
            "fetched_at": NOW, "updated_at": None, "changed": False,
            "cache": caches[0][1] if caches else None}

    def newest_cache(why):
        if not caches:
            raise SystemExit("no live data and no cache available for %s (%s)"
                             % (slug, why))
        ts, source = caches[0]
        meta["updated_at"] = datetime.strptime(ts, CACHE_TS_FMT)
        return read_cache(source), meta

    if offline:
        return newest_cache("offline")
    try:
        text = _http_get(EXPORT_URL % (key, gid))
        if not text.strip() or "Username" not in text:
            raise ValueError("unexpected sheet content")
    except Exception as exc:  # network blocked / offline / format change
        sys.stderr.write("! live fetch failed for %s (%s); using cache\n"
                         % (slug, exc))
        return newest_cache(str(exc))

    meta["live"] = True
    prev = read_cache(caches[0][1]) if caches else None
    if prev is not None and _norm_for_diff(prev) == _norm_for_diff(text):
        # Unchanged since the newest cache anywhere: nothing to write.
        meta["updated_at"] = datetime.strptime(caches[0][0], CACHE_TS_FMT)
    else:
        ts = NOW.strftime(CACHE_TS_FMT)
        path = os.path.join(str(DATA_RAW), "%s_%s.csv" % (slug, ts))
        with open(path, "w") as fh:
            fh.write(text)
        meta.update(updated_at=datetime.strptime(ts, CACHE_TS_FMT),
                    changed=True, cache=path)
    return text, meta
