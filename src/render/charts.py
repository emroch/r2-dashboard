"""Plotly chart builders for the dashboard (the fig_* functions not yet moved to
presentation-layer components, plus their shared helpers). Pure figure
construction from the cleaned DataFrames.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .colors import COLOR_DISPLAY, REGION_WHISKER
from config import (AS_OF, CHART, CHART_UI, COLOR_ORDER, FACTORY,
                    INTERIOR_ORDER, INTERIOR_SHORT, REGION_COLOR,
                    WHEEL_ABBR, WHEEL_ORDER, WHEEL_SYMBOL)

# Theme-aware "today" reference line at the run date (AS_OF). Baked in the
# light-theme grey; the dashboard's theme toggle re-tints managed greys — in
# shapes and their labels too — so it flips with the rest of the chart chrome.
_TODAY = dict(line_width=1.5, line_dash="dash", line_color=CHART["edge"],
              annotation_text="Today", annotation_font_color=CHART["edge"],
              annotation_font_size=10)


def _add_today_vline(fig, **kw):
    fig.add_vline(x=AS_OF, annotation_position="top", **_TODAY, **kw)


def _num_range(vals, pad_frac=0.03, min_pad=1.0):
    """A padded [lo, hi] for a numeric axis (None if empty). Setting an explicit
    range fixes the axis so toggling series — or a custom zoom — never triggers
    an auto-rescale, keeping configs comparable across filter states."""
    v = pd.Series(vals).dropna()
    if v.empty:
        return None
    lo, hi = float(v.min()), float(v.max())
    pad = max((hi - lo) * pad_frac, min_pad)
    return [lo - pad, hi + pad]


def _date_range(series, pad_frac=0.03, min_days=3, include=None):
    """A padded [lo, hi] (as strings) for a date axis spanning every series in
    `series` plus `include` (e.g. the today line). None if all empty."""
    v = pd.concat([pd.Series(s) for s in series]).dropna()
    if v.empty:
        return None
    lo, hi = v.min(), v.max()
    if include is not None:
        inc = pd.Timestamp(include)
        lo, hi = min(lo, inc), max(hi, inc)
    pad = max((hi - lo) * pad_frac, pd.Timedelta(days=min_days))
    return [str(lo - pad), str(hi + pad)]


def _config_hover(df):
    """customdata + hovertemplate shared by the config scatter plots."""
    cd = np.stack([
        df["user"].values, df["color"].values, df["wheels_short"].values,
        df["interior"].values, df["buylease"].values, df["vin_display"].values,
        df["order_display"].values, df["est_display"].values,
        df["delivery_type"].values, df["state"].values,
    ], axis=-1)
    ht = ("<b>%{customdata[0]}</b><br>"
          "%{customdata[1]} · %{customdata[2]}<br>"
          "%{customdata[3]} · %{customdata[4]}<br>"
          "State: %{customdata[9]}<br>"
          "VIN seq: %{customdata[5]}<br>"
          "Ordered: %{customdata[6]}<br>"
          "Est. delivery: %{customdata[7]} (%{customdata[8]})"
          "<extra></extra>")
    return cd, ht


def _config_wheel_traces(d, colors):
    """Yield per-(color, wheel) subframes in legend order (`colors`, then wheel).
    Each becomes its own legend entry, so paint × wheel series toggle and isolate
    independently. `colors` comes from _paint_order, so the legend runs
    most-popular-paint first like every other paint chart. Yields
    (color, wheel, symbol, sub)."""
    for color in colors:
        cmask = (d["color"] == color).values
        if not cmask.any():
            continue
        for wheel, sym in WHEEL_SYMBOL.items():
            sub = d[cmask & (d["wheels_short"] == wheel).values]
            if not sub.empty:
                yield color, wheel, sym, sub


def _whisker_toggle_menu(whisker_idx, x=0.0):
    """A show/hide toggle for the (separate) whisker traces — a declutter
    control. Targets only the whisker trace indices, so it's independent of the
    legend's per-series toggling. Empty if there are no whiskers."""
    if not whisker_idx:
        return []
    idx = list(whisker_idx)
    return [dict(type="buttons", direction="right", showactive=True, x=x,
                 xanchor="left", y=1.02, yanchor="bottom", pad=dict(b=2),
                 bgcolor=CHART_UI["control_bg"], bordercolor=CHART_UI["control_border"],
                 font=dict(size=11, color=CHART_UI["control_fg"]),
                 buttons=[dict(label="Whiskers", method="restyle",
                              args=[{"visible": True}, idx]),
                          dict(label="No whiskers", method="restyle",
                              args=[{"visible": False}, idx])])]


def fig_dest_vs_delivery(df):
    """Destination (state, ordered by distance from factory) vs delivery.

    Per region: markers plus min-max delivery whiskers sharing a per-region
    legendgroup, so clicking a region toggles its points and whiskers together."""
    d = df[df["delivery_est"].notna() & df["dist_mi"].notna()].copy()
    order = (d.groupby("state")["dist_mi"].first().sort_values(ascending=True)
             .index.tolist())
    ypos = {s: i for i, s in enumerate(order)}
    fig = go.Figure()
    rng = np.random.RandomState(7)
    cap = 0.14  # whisker end-cap half-height, in y (state) units
    panels = []
    for region in ["Midwest", "South", "Northeast", "West", "Canada"]:
        sub = d[d["region"] == region]
        if sub.empty:
            continue
        jitter = (rng.rand(len(sub)) - 0.5) * 0.55
        y = [ypos[s] + j for s, j in zip(sub["state"], jitter)]
        panels.append((region, sub, y))
    # Whiskers first so they sit behind the markers; a tinted grey keyed to the
    # region, in its legendgroup so they hide/isolate with its points.
    whisk = []
    for region, sub, y in panels:
        xw, yw = [], []
        for mn, mx, yy in zip(sub["delivery_min"], sub["delivery_max"], y):
            if pd.notna(mn) and pd.notna(mx) and mx > mn:
                a, b = mn.strftime("%Y-%m-%d"), mx.strftime("%Y-%m-%d")
                xw += [a, b, None, a, a, None, b, b, None]
                yw += [yy, yy, None, yy - cap, yy + cap, None,
                       yy - cap, yy + cap, None]
        if xw:
            whisk.append(len(fig.data))
            fig.add_trace(go.Scatter(
                x=xw, y=yw, mode="lines", legendgroup=region, showlegend=False,
                hoverinfo="skip", opacity=0.7,
                line=dict(color=REGION_WHISKER[region], width=1)))
    for region, sub, y in panels:
        cd = np.stack([sub["user"].values, sub["state"].values,
                       sub["dist_mi"].round(0).values, sub["est_display"].values,
                       sub["delivery_type"].values, sub["color"].values], axis=-1)
        fig.add_trace(go.Scatter(
            x=np.asarray(sub["delivery_est"]), y=y, mode="markers", name=region,
            legendgroup=region,
            marker=dict(color=REGION_COLOR[region], size=9, opacity=0.8,
                        line=dict(color=CHART["edge"], width=0.5)),
            customdata=cd,
            hovertemplate=("<b>%{customdata[0]}</b> — %{customdata[1]}<br>"
                           "%{customdata[2]:.0f} mi from Normal, IL<br>"
                           "%{customdata[5]}<br>"
                           "Est. delivery: %{customdata[3]} "
                           "(%{customdata[4]})<extra></extra>")))
    labels = ["%s  (%.0f mi)" % (s, d[d["state"] == s]["dist_mi"].iloc[0])
              for s in order]
    menu = _whisker_toggle_menu(whisk, x=0.0)
    xax = dict(title_text="Estimated delivery date")
    xr = _date_range([d["delivery_est"], d["delivery_min"], d["delivery_max"]],
                     include=AS_OF)
    if xr:
        xax["range"] = xr
    fig.update_layout(
        template="plotly_white",
        xaxis=xax,
        yaxis=dict(title="Destination — nearest to factory at bottom",
                   tickmode="array", tickvals=list(range(len(order))),
                   ticktext=labels, range=[-0.7, len(order) - 0.3]),
        legend=dict(title_text="Region", groupclick="togglegroup", tracegroupgap=0),
        height=780, hovermode="closest", updatemenus=menu)
    if menu:
        fig.update_layout(margin=dict(t=54))
    _add_today_vline(fig)
    return fig


def fig_vin_vs_order(df):
    """VIN sequence vs R2 order date, coded by config. One legend entry per
    paint × wheel (marker shape encodes the wheel), each toggling/isolating that
    series independently."""
    d = _reported(df[df["vin_present"] & df["order_date"].notna()],
                  "color", "wheels_short")
    fig = go.Figure()
    for color, wheel, sym, s in _config_wheel_traces(d, _paint_order(df)):
        grp = "%s · %s" % (color, wheel.split()[0])   # e.g. "Launch Green · 21\""
        cd, ht = _config_hover(s)
        fig.add_trace(go.Scatter(
            x=np.asarray(s["order_date"]), y=np.asarray(s["vin_seq"]),
            mode="markers", name=grp, legendgroup=grp,
            marker=dict(color=_paint_fill(color), size=11,
                        symbol=sym, opacity=0.9,
                        line=dict(color=CHART["edge"], width=0.8)),
            customdata=cd, hovertemplate=ht))
    xax = dict(title_text="R2 order date", type="date")
    yax = dict(title_text="VIN sequence number", type="linear")
    xr = _date_range([d["order_date"]], include=AS_OF)
    yr = _num_range(d["vin_seq"])
    if xr:
        xax["range"] = xr
    if yr:
        yax["range"] = yr
    fig.update_layout(
        template="plotly_white", xaxis=xax, yaxis=yax,
        legend=dict(title_text="Paint · wheels", groupclick="togglegroup",
                    tracegroupgap=0),
        height=640, hovermode="closest")
    return fig


# A curated addition can leave paint / wheels / interior blank — a forum post often
# pins down an order date and location while the build itself is still unreported
# (see overrides.yaml); no sheet row does, the form requires them. Those orders are
# left OUT of the configuration charts rather than shown as an "Unknown" category:
# the charts are about what people chose, and a row that hasn't said carries no
# choice to plot. They are not dropped from the dataset — they count in the cohort,
# and the data-quality panel lists each one by the field it is missing.
#
# _reported is therefore applied to the FRAME, not just to the category list. Taking
# the category out while leaving the rows in would divide by a total that includes
# them, so every 100%-stacked row would quietly stop adding up to 100.


def _reported(df, *cols):
    """Rows that have actually reported every one of `cols`."""
    d = df
    for c in cols:
        if c in d.columns:
            d = d[d[c].astype(str).str.strip() != ""]
    return d


def _paint_fill(value):
    """Paint value -> its fill, muted for a paint the palette doesn't know."""
    return COLOR_DISPLAY.get(value, CHART_UI["muted"])


def _paint_order(df):
    """The paints present in `df`, most-ordered first — the page-wide paint order.

    Every paint chart reads this, so the ranking a reader picks up from the
    take-rate bars also holds in the combo heatmaps, both scatter legends and the
    location mix. These sites used to follow the curated paint list's order,
    which is a sensible showroom sequence but not a popularity one: it put Forest
    Green third on 25 orders while Catalina Cove's 186 landed mid-grid, so the
    heatmap had no legible gradient at all (issue #58).

    Ties break by the palette's order, then by name — NOT by count alone.
    value_counts() promises nothing among equal counts, so two paints on the same
    total would swap places between daily builds for no reason, the same trap
    _stable_counts documents. A paint missing from the palette sorts last rather
    than raising; palette coverage is verified separately.

    Derived from whatever frame it is handed, and every fig_* receives the same
    full cohort (each subsets internally), so all the charts agree without the
    order having to be threaded through them.
    """
    counts = _reported(df, "color")["color"].value_counts()
    rank = {c: i for i, c in enumerate(COLOR_ORDER)}
    return sorted(counts.index,
                  key=lambda c: (-counts[c], rank.get(c, len(rank)), c))


def _stable_counts(counts):
    """Counts ascending, ties broken alphabetically. Ascending so the biggest bar
    sits on top of a horizontal panel.

    The tie-break is the point. sort_values() is not a stable sort and
    value_counts/groupby promise no order among equal counts, so tied categories
    came out in a DIFFERENT ORDER ON EVERY RUN — the deployed charts' rows
    reshuffled between daily builds for no reason, and it made any before/after
    diff of a figure meaningless. sort_index first, then a stable sort by value,
    leaves ties alphabetical.
    """
    return counts.sort_index().sort_values(ascending=True, kind="mergesort")


def _geo_counts(frame):
    """Per-state bubble rows (count, lat, lon, region); drops unmapped states."""
    return (frame.groupby("state").agg(n=("user", "size"), lat=("lat", "first"),
                                       lon=("lon", "first"),
                                       region=("region", "first"))
            .reset_index().dropna(subset=["lat"]))


def _region_counts(frame):
    """Per-region totals for a panel, ascending so the biggest bar sits on top
    of a horizontal bar chart. Unmapped rows are excluded to stay consistent
    with the map bubbles, which can only plot located states."""
    g = frame.dropna(subset=["lat"])
    return (_stable_counts(g.groupby("region").size())
            if len(g) else pd.Series(dtype="int64"))


def fig_geo(df, resv=None):
    """Geographic demand: three stacked maps, each paired with its region totals.

    Rows are orders with a VIN, all orders, and total demand (orders + incomplete
    reservations). Bubble area = count; the bar beside each map gives that
    panel's per-region total, so the map's visual weight has exact numbers next
    to it.

    The VIN and all-orders panels share a bubble scale (comparable magnitudes);
    total demand is ~20x larger, so it scales to its own max."""
    panels = [("VIN assigned", df[df["vin_present"]]),
              ("All orders", df)]
    if resv is not None and len(resv):
        cols = ["user", "state", "lat", "lon", "region"]
        panels.append(("Total demand (orders + incomplete reservations)",
                       pd.concat([df[cols], resv[cols]], ignore_index=True)))
    maps = [(t, _geo_counts(f), _region_counts(f)) for t, f in panels]

    n = len(maps)
    vs = 0.05
    # Two columns per row: the map, then that panel's region totals. Subplot
    # titles are placed only on the maps (the bars are self-labeling).
    fig = make_subplots(
        rows=n, cols=2, column_widths=[0.74, 0.26], horizontal_spacing=0.08,
        specs=[[{"type": "scattergeo"}, {"type": "xy"}] for _ in range(n)],
        subplot_titles=[s for t, _, _ in maps for s in (t, "")],
        vertical_spacing=vs)

    order_max = max([g["n"].max() for t, g, _ in maps[:2] if len(g)] or [1])
    rowh = (1 - vs * (n - 1)) / n
    legends = {}
    for i, (title, g, reg) in enumerate(maps, start=1):
        legend_key = "legend" if i == 1 else "legend%d" % i
        y_top = 1 - (i - 1) * (rowh + vs)
        legends[legend_key] = dict(
            x=1.01, xanchor="left", y=y_top - rowh / 2, yanchor="middle",
            title=dict(text="Region"), font=dict(size=11), itemsizing="constant",
            bgcolor=CHART["legbg"], bordercolor=CHART["legbd"], borderwidth=1)
        # Region totals (col 2) — one bar per region, colored to match the map.
        if len(reg):
            fig.add_trace(go.Bar(
                x=np.asarray(reg.values), y=np.asarray(reg.index),
                orientation="h", showlegend=False,
                marker=dict(color=[REGION_COLOR.get(r, CHART_UI["muted"])
                                   for r in reg.index],
                            line=dict(color=CHART["edge"], width=0.5)),
                text=np.asarray(reg.values), textposition="outside",
                cliponaxis=False, textfont=dict(size=10),
                hovertemplate="%{y}: %{x}<extra></extra>"), i, 2)
        if not len(g):
            continue
        ref_max = g["n"].max() if title.startswith("Total") else order_max
        sref = 2.0 * float(ref_max) / (30.0 ** 2)
        for region in g["region"].unique():
            sub = g[g["region"] == region]
            fig.add_trace(go.Scattergeo(
                lat=np.asarray(sub["lat"]), lon=np.asarray(sub["lon"]),
                text=np.asarray(sub["state"]), name=region, legend=legend_key,
                mode="markers",
                marker=dict(size=np.asarray(sub["n"]), sizemode="area",
                            sizeref=sref, sizemin=3,
                            color=REGION_COLOR.get(region, CHART_UI["muted"]),
                            line=dict(color=CHART["edge"], width=0.5)),
                customdata=np.asarray(sub["n"]),
                hovertemplate="%{text}: %{customdata}<extra></extra>"), i, 1)
        fig.add_trace(go.Scattergeo(
            lat=[FACTORY[0]], lon=[FACTORY[1]], mode="markers", name="Factory",
            showlegend=False, marker=dict(size=11, symbol="star", color=CHART["star"]),
            hovertemplate="Rivian plant — Normal, IL<extra></extra>"), i, 1)
    fig.update_geos(scope="north america", resolution=50, showland=True,
                    landcolor=CHART["land"], showlakes=False,
                    showsubunits=True, subunitcolor=CHART["sub"], subunitwidth=0.5,
                    showcountries=True, countrycolor=CHART["country"], countrywidth=0.7)
    # Headroom for the outside count labels; no gridlines (the labels are exact).
    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False,
                     rangemode="tozero", automargin=True)
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    for i in range(1, n + 1):
        vals = maps[i - 1][2]
        if len(vals):
            fig.update_xaxes(range=[0, float(vals.max()) * 1.18], row=i, col=2)
    # dragmode is pinned to "pan" because adding the region-total bars put
    # cartesian axes in this figure, which silently flipped the figure-wide default
    # from "pan" (what a geo-only figure gets) to "zoom" (the cartesian default) and
    # broke wheel-zoom on the maps until you picked pan from the modebar.
    fig.update_layout(template="plotly_white", height=380 * n, bargap=0.35,
                      dragmode="pan",
                      margin=dict(l=0, r=140, t=30, b=0), **legends)
    return fig


def fig_vin_by_config(df):
    """VIN sequence per full configuration (trim · color · wheels · interior).

    Each VIN-assigned order sits at its production sequence (x); rows group
    orders by configuration. Clusters along a row hint at same-config cars built
    in a batch. Today everyone is Performance (Launch Edition); Premium and
    Standard rows will appear as those trims ship.

    Interior joins the row key rather than becoming a fourth visual channel —
    marker fill is already paint and shape is already wheels, and a third encoding
    on a 10px marker would be guesswork. With two interiors in the catalog per
    trim this at most doubles the row count, and it grows only as fast as VINs are
    assigned to the newer cabins.
    """
    # The row key is the whole configuration, so a row missing part of it has no
    # group to belong to.
    d = _reported(df[df["vin_present"]], "color", "wheels_short", "interior").copy()
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=420)
        return fig
    # Compact per-wheel tag: size alone is ambiguous now that two of the four
    # wheels are 20", so the abbreviation carries All-Season/All-Terrain too.
    wheel_abbr = d["wheels_short"].map(lambda w: WHEEL_ABBR.get(w, w))
    interior = d["interior"].map(lambda i: INTERIOR_SHORT.get(i, i))
    d["_combo"] = (d["trim"] + " · " + d["color"] + " · " + wheel_abbr
                   + " · " + interior)
    # Cohort-wide paint rank, not one derived from the VIN-assigned rows alone, so
    # the row groups follow the same paint order as the rest of the page.
    color_rank = {c: i for i, c in enumerate(_paint_order(df))}
    interior_rank = {INTERIOR_SHORT.get(i, i): n
                     for n, i in enumerate(INTERIOR_ORDER)}

    def _key(combo):
        trim, color, wheel, inter = combo.split(" · ")
        return (trim, color_rank.get(color, 99), wheel,
                interior_rank.get(inter, 99))

    combos = sorted(d["_combo"].unique(), key=_key)
    ypos = {c: i for i, c in enumerate(combos)}
    rng = np.random.RandomState(11)
    jit = (rng.rand(len(d)) - 0.5) * 0.36                  # separate overlaps
    y = [ypos[c] + j for c, j in zip(d["_combo"], jit)]
    cd, ht = _config_hover(d)
    # Markers keep the dashboard's config language: fill = paint, shape = wheels.
    fig.add_trace(go.Scatter(
        x=np.asarray(d["vin_seq"]), y=y, mode="markers", showlegend=False,
        marker=dict(color=[COLOR_DISPLAY.get(c, CHART_UI["muted"]) for c in d["color"]],
                    symbol=[WHEEL_SYMBOL.get(w, "circle") for w in d["wheels_short"]],
                    size=10, line=dict(color=CHART["edge"], width=0.6)),
        customdata=cd, hovertemplate=ht))
    # Symbol legend for the wheels actually present — the palette knows four, and
    # a phantom entry for a wheel no one has ordered reads as a missing series.
    for label in [w for w in WHEEL_ORDER if (d["wheels_short"] == w).any()]:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label,
            marker=dict(color=CHART_UI["key_marker"], size=10,
                        symbol=WHEEL_SYMBOL.get(label, "circle"),
                        line=dict(color=CHART["edge"], width=0.6))))
    fig.update_layout(
        template="plotly_white", height=max(420, 42 * len(combos) + 180),
        xaxis_title="VIN sequence number  (production order →)",
        yaxis=dict(tickmode="array", tickvals=list(range(len(combos))),
                   ticktext=combos, automargin=True, autorange="reversed"),
        legend_title="Wheels", hovermode="closest")
    return fig
