"""Live-sheet fetching with timestamped local caching and change detection.

The Google Sheets CSV export sends no Last-Modified/ETag (and Cache-Control:
no-store), so "did the data change?" is detected by diffing each fetch against
the newest cache. Caches live under data/raw/.
"""
import os
import re
import sys
import urllib.request
from datetime import datetime

from .config import (CACHE_TS_FMT, DATA_RAW, EXPORT_URL, NOW, VIEW_URL)


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


def fetch_sheet(key, gid, slug, label):
    """Fetch a sheet's CSV export, with local caching and change detection.

    The export endpoint sends no Last-Modified/ETag (and Cache-Control:
    no-store), so we detect "did the data change?" by diffing the fetch against
    the newest cache. A new timestamped cache is written only when the content
    differs, so the newest cache's timestamp is when the data last updated.
    Falls back to the newest cache if the live fetch fails. Returns
    (text, meta) with meta = live/fetched_at/updated_at/changed/view_url/cache.
    """
    view = VIEW_URL % (key, gid)
    caches = _cache_files(slug)
    meta = {"label": label, "view_url": view, "live": False, "fetched_at": NOW,
            "updated_at": None, "changed": False,
            "cache": caches[0][1] if caches else None}
    try:
        text = _http_get(EXPORT_URL % (key, gid))
        if not text.strip() or "Username" not in text:
            raise ValueError("unexpected sheet content")
    except Exception as exc:  # network blocked / offline / format change
        sys.stderr.write("! live fetch failed for %s (%s); using cache\n"
                         % (slug, exc))
        if not caches:
            raise SystemExit("no live data and no cache available for %s" % slug)
        ts, path = caches[0]
        with open(path) as fh:
            text = fh.read()
        meta["updated_at"] = datetime.strptime(ts, CACHE_TS_FMT)
        return text, meta

    meta["live"] = True
    prev = None
    if caches:
        with open(caches[0][1]) as fh:
            prev = fh.read()
    if prev is not None and _norm_for_diff(prev) == _norm_for_diff(text):
        meta["updated_at"] = datetime.strptime(caches[0][0], CACHE_TS_FMT)
    else:
        ts = NOW.strftime(CACHE_TS_FMT)
        path = os.path.join(str(DATA_RAW), "%s_%s.csv" % (slug, ts))
        with open(path, "w") as fh:
            fh.write(text)
        meta.update(updated_at=datetime.strptime(ts, CACHE_TS_FMT),
                    changed=True, cache=path)
    return text, meta
