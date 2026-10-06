#!/usr/bin/env python3
"""Build the chart-library spike page (#107): output/spike/index.html.

Temporary. Draws §10's scatter and §12's map, from the same specs the pipeline
writes to r2_view.json, in each candidate library (Observable Plot, ECharts,
Plotly's geo bundle), so they can be compared side by side on a PR preview.
The libraries load from pinned jsDelivr URLs, so none is committed. Deleted,
with tools/spike/, once the library is chosen.

Run after the pipeline: python3 tools/build_spike.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import OUTPUT_DIR, VIEW_JSON  # noqa: E402
from render.categories import category_css  # noqa: E402
from render.page import _THEME_VARS_CSS, _tpl  # noqa: E402

SRC = Path(__file__).resolve().parent / "spike"
LIBS = [("plot", "Observable Plot 0.6 + d3 7 (SVG)"),
        ("echarts", "ECharts 6.1 (canvas)"),
        ("plotly", "Plotly 4.1, geo partial bundle (SVG + WebGL-free)")]

CSS = """
body{max-width:1180px;margin:0 auto;padding:16px 24px 60px}
.lib{background:var(--card-bg);border:1px solid var(--card-bd);border-radius:10px;
 padding:14px 18px;margin:18px 0}
.lib h2{margin:0;font-size:18px;color:var(--sec-title)}
.cost{font-size:12px;color:var(--desc);margin:2px 0 8px}
.legend{display:flex;flex-wrap:wrap;gap:4px 6px;margin:6px 0}
.lg-item{font:inherit;font-size:12px;display:inline-flex;align-items:center;gap:5px;
 background:none;color:var(--fg);border:1px solid var(--card-bd);border-radius:12px;
 padding:2px 8px;cursor:pointer}
.lg-item[aria-pressed=false]{opacity:.35}
.lg-item .swatch{width:.75em;height:.75em}
.scatter{min-height:560px}.map{min-height:300px;margin-top:10px}
.controls{display:flex;gap:16px;align-items:center;font-size:13px}
"""


def main():
    view = json.loads(Path(VIEW_JSON).read_text())
    out = Path(OUTPUT_DIR) / "spike"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in ("common.js", "plot.js", "echarts.js", "plotly.js", "spike.js"):
        shutil.copyfile(SRC / f, out / f)
    data = {"components": {k: view["components"][k]
                           for k in ("delivery-vs-vin", "geo-orders")}}
    cards = "".join(
        '<section class="lib" id="lib-%s" data-lib="%s"><h2>%s</h2>'
        '<p class="cost">loads when scrolled near…</p><div class="legend"></div>'
        '<div class="scatter"></div><div class="map"></div></section>'
        % (k, k, name) for k, name in LIBS)
    html = """<!doctype html><html data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chart-library spike (#107)</title>
<style>%s</style><style>%s</style><style>%s</style><style>%s</style></head><body>
<h1>Chart-library spike (#107)</h1>
<p>§10 (delivery vs. VIN) and §12 (all orders by state) drawn from the same specs
(r2_view.json) by each candidate. Legend: click hides a series, double-click
isolates it. Each library loads from jsDelivr when its card nears the viewport;
the line under its name is what that cost.</p>
<p class="controls"><button type="button" id="spikeTheme">Toggle theme</button>
<label><input type="checkbox" id="spikeWhiskers"> Whiskers (?whiskers=)</label></p>
%s
<script id="spike-data" type="application/json">%s</script>
<script src="common.js"></script><script src="plot.js"></script>
<script src="echarts.js"></script><script src="plotly.js"></script>
<script src="spike.js"></script></body></html>""" % (
        _THEME_VARS_CSS, _tpl("styles.css"), category_css(), CSS, cards,
        json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    (out / "index.html").write_text(html, encoding="utf-8")
    print("Wrote: %s" % (out / "index.html"))


if __name__ == "__main__":
    main()
