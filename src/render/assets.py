"""The page's browser code, published as content-hashed static assets.

Everything under src/web/ (the page scripts, the boot module, and later the chart
templates and the vendored chart library) is copied into the output as
assets/<hash>/, where <hash> covers every file's path and bytes. The page refers
to its scripts through that prefix, so a build that changes any of them changes
every URL. That is what lets _headers cache assets/* as immutable: a browser
never holds a stale copy under a current name.

Only head.js is not here. It sets the theme before first paint, so it has to be
inlined into <head> (see page.py).
"""
# Lets the hints use `X | None` while the code still runs on the system 3.9.
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

# Under the output directory, and under dist/ once deployed.
ASSETS = "assets"


def _files(src: Path) -> list[Path]:
    # Dotfiles are skipped: they are local litter (.DS_Store), not page code,
    # and would make a local build hash differently from CI's.
    return sorted(p for p in src.rglob("*")
                  if p.is_file() and not any(part.startswith(".")
                                             for part in p.relative_to(src).parts))


def asset_hash(src: Path = WEB_DIR) -> str:
    """8 hex digits over every asset's relative path and contents."""
    h = hashlib.sha256()
    for p in _files(src):
        h.update(p.relative_to(src).as_posix().encode() + b"\0")
        h.update(p.read_bytes() + b"\0")
    return h.hexdigest()[:8]


def publish_assets(out_dir: Path, src: Path = WEB_DIR) -> str:
    """Copy the assets to out_dir/assets/<hash>/ and return the page-relative
    prefix ("assets/<hash>/"). Earlier builds' directories are removed, so the
    output only ever holds the set this page refers to."""
    digest = asset_hash(src)
    root = Path(out_dir) / ASSETS
    if root.exists():
        for old in root.iterdir():
            if old.name == digest:
                continue
            if old.is_dir():
                shutil.rmtree(old)
            else:
                old.unlink()
    dest = root / digest
    if dest.exists():
        shutil.rmtree(dest)
    for p in _files(src):
        target = dest / p.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    return "%s/%s/" % (ASSETS, digest)
