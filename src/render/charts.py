"""Plotly chart builders for the dashboard (the nine fig_* functions plus their
shared helpers). Pure figure construction from the cleaned DataFrames.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .colors import COLOR_DISPLAY, REGION_WHISKER, WHISKER_HEX
from config import (AS_OF, CHART, CHART_UI, COLOR_ORDER, DENSITY_BINS, ELEV_BINS,
                     FACTORY, HEATMAP_COLORSCALE, INTERIOR_COLOR, PRICE_COLORS,
                     PRICE_TRIMS, R1_MODEL_COLORS, REGION_COLOR,
                     STATE_TOTALS_COLORS, TAKE_RATE, TEMP_BINS, TIMELINE_COLORS,
                     TRIM_COLORS, TYPE_COLOR, TYPE_OPACITY, TYPE_ORDER,
                     WHEEL_ABBR, WHEEL_COLOR, WHEEL_ORDER, WHEEL_SYMBOL)

# Theme-aware "today" reference line at the run date (AS_OF). Baked in the
# light-theme grey; the dashboard's theme toggle re-tints managed greys — in
# shapes and their labels too — so it flips with the rest of the chart chrome.
_TODAY = dict(line_width=1.5, line_dash="dash", line_color=CHART["edge"],
              annotation_text="Today", annotation_font_color=CHART["edge"],
              annotation_font_size=10)


def _add_today_vline(fig, **kw):
    fig.add_vline(x=AS_OF, annotation_position="top", **_TODAY, **kw)


def _add_today_hline(fig, **kw):
    fig.add_hline(y=AS_OF, annotation_position="top right", **_TODAY, **kw)


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


def _config_wheel_traces(d):
    """Yield per-(color, wheel) subframes in legend order (COLOR_ORDER, then
    wheel). Each becomes its own legend entry, so paint × wheel series toggle
    and isolate independently. Yields (color, wheel, symbol, sub)."""
    for color in COLOR_ORDER:
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


def fig_delivery_vs_vin(df):
    """Estimated delivery date vs VIN sequence, coded by config.

    One legend entry per paint × wheel (marker shape encodes the wheel), each
    toggling/isolating that series — its markers and whiskers share a
    legendgroup, so hiding a series takes its whiskers with it (no strays). A
    whisker on/off button declutters. Window/range estimates get whiskers
    spanning their min-max delivery span.
    """
    d = df[df["vin_present"] & df["delivery_est"].notna()]
    fig = go.Figure()
    xs = d["vin_seq"].astype(float)
    cap = (xs.max() - xs.min()) * 0.006 if len(xs) else 5.0
    whisk = []
    for color, wheel, sym, s in _config_wheel_traces(d):
        grp = "%s · %s" % (color, wheel.split()[0])   # e.g. "Launch Green · 21\""
        # Whiskers (min-max span + caps) for window/range estimates, in the
        # series' legendgroup so they toggle/isolate with its markers.
        xw, yw = [], []
        for x, mn, mx in zip(s["vin_seq"], s["delivery_min"], s["delivery_max"]):
            if pd.notna(mn) and pd.notna(mx) and mx > mn:
                a, b = mn.strftime("%Y-%m-%d"), mx.strftime("%Y-%m-%d")
                xw += [x, x, None, x - cap, x + cap, None, x - cap, x + cap, None]
                yw += [a, b, None, b, b, None, a, a, None]
        if xw:
            whisk.append(len(fig.data))
            fig.add_trace(go.Scatter(
                x=xw, y=yw, mode="lines", legendgroup=grp, showlegend=False,
                hoverinfo="skip", opacity=0.7,
                line=dict(color=WHISKER_HEX[color], width=1.4)))
        cd, ht = _config_hover(s)
        opac = [TYPE_OPACITY.get(t, 0.4) for t in s["delivery_type"]]
        fig.add_trace(go.Scatter(
            x=np.asarray(s["vin_seq"]), y=np.asarray(s["delivery_est"]),
            mode="markers", name=grp, legendgroup=grp,
            marker=dict(color=COLOR_DISPLAY[color], size=11,
                        symbol=sym, opacity=opac,
                        line=dict(color=CHART["edge"], width=0.8)),
            customdata=cd, hovertemplate=ht))
    menu = _whisker_toggle_menu(whisk, x=0.0)
    # Fixed ranges + pinned axis types so toggling series or zooming never
    # rescales the view; span the today line too.
    xax = dict(title_text="VIN sequence number  (production order →)", type="linear")
    yax = dict(title_text="Estimated delivery date  (whiskers = quoted window)",
               type="date")
    xr = _num_range(d["vin_seq"], min_pad=cap * 1.5)
    yr = _date_range([d["delivery_est"], d["delivery_min"], d["delivery_max"]],
                     include=AS_OF)
    if xr:
        xax["range"] = xr
    if yr:
        yax["range"] = yr
    fig.update_layout(
        template="plotly_white", xaxis=xax, yaxis=yax,
        legend=dict(title_text="Paint · wheels", groupclick="togglegroup",
                    tracegroupgap=0),
        height=640, hovermode="closest", updatemenus=menu)
    if menu:
        fig.update_layout(margin=dict(t=54))
    _add_today_hline(fig)  # horizontal — delivery date is the y-axis here
    return fig


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
    d = df[df["vin_present"] & df["order_date"].notna()]
    fig = go.Figure()
    for color, wheel, sym, s in _config_wheel_traces(d):
        grp = "%s · %s" % (color, wheel.split()[0])   # e.g. "Launch Green · 21\""
        cd, ht = _config_hover(s)
        fig.add_trace(go.Scatter(
            x=np.asarray(s["order_date"]), y=np.asarray(s["vin_seq"]),
            mode="markers", name=grp, legendgroup=grp,
            marker=dict(color=COLOR_DISPLAY[color], size=11,
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


# Legend label for a blank answer to a conditional follow-up question. On the R1
# panel this segment is almost entirely non-owners — the model question only
# applies to owners — so it names that case rather than reading as a bare gap.
_UNSPECIFIED = "No / unspecified"


def _split_values(df, col, palette):
    """Distinct values of a split column, in palette order then any extras. Blanks
    collapse to the sentinel label so a conditional follow-up question
    (which R1 do you own?) gets one labelled segment instead of an empty name."""
    seen = set(df[col].replace("", _UNSPECIFIED).unique())
    ordered = [k for k in palette if k in seen]
    return ordered + sorted(seen - set(ordered))


def _take_rate_panel(fig, row, col, df, cat_col, counts, labels, fill,
                     split_col=None, palette=None, legend_key=None,
                     show_legend=False):
    """One take-rate panel, stacked by `split_col` when that column actually holds
    more than one value.

    With a single value there's nothing to compare, so it renders as a plain bar
    and adds no legend entry — today's cohort is 100% Performance, and a legend
    reading "Trim: Performance" would be noise. The stacks appear on their own as
    Premium and Standard ship. Returns True if it drew a stack.
    """
    splits = _split_values(df, split_col, palette or {}) if split_col else []
    if len(splits) < 2:
        fig.add_trace(go.Bar(x=labels, y=np.asarray(counts), marker_color=fill,
                             marker_line=dict(color=CHART["edge"], width=1),
                             showlegend=False,
                             hovertemplate="%{x}: %{y}<extra></extra>"), row, col)
        return False
    sv = df[split_col].replace("", _UNSPECIFIED)
    for s in splits:
        vals = [int(((df[cat_col] == c) & (sv == s)).sum()) for c in counts.index]
        fig.add_trace(go.Bar(
            x=labels, y=np.asarray(vals), name=s, legendgroup=s,
            showlegend=show_legend, legend=legend_key or "legend",
            marker_color=(palette or {}).get(s, CHART_UI["muted"]),
            marker_line=dict(color=CHART["edge"], width=1),
            hovertemplate="%{x} · " + str(s) + ": %{y}<extra></extra>"), row, col)
    return True


def fig_config_dashboard(df):
    """Config take-rate small-multiples.

    Panels whose mix should differ by trim once the lineup fills out — wheels,
    interior, purchase vs. lease — stack by trim, and the R1-owner panel stacks by
    which R1 the owner has. Each split is only drawn when the data holds more than
    one value in it, so a single-trim cohort still renders plain bars instead of a
    one-entry legend (see _take_rate_panel).

    Autonomy+ and Tow have no panel here: the Launch Package bundles both, so they
    sit at ~100% across the cohort. They'll be worth adding, split by trim, once
    the package is discontinued and the answers fragment.
    """
    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=("Exterior color", "Wheels", "Interior",
                        "Purchase vs. lease", "Compact spare tire",
                        "Current R1 owner?"))

    cc = df["color"].value_counts()  # descending by popularity
    fig.add_trace(go.Bar(x=list(cc.index), y=np.asarray(cc.values),
                         marker_color=[COLOR_DISPLAY[c] for c in cc.index],
                         marker_line=dict(color=CHART["edge"], width=1),
                         showlegend=False,
                         hovertemplate="%{x}: %{y}<extra></extra>"), 1, 1)

    # Trim-split panels share one legend; `shown` makes only the first contribute
    # entries so the trim colors aren't listed three times.
    shown = False
    wc = df["wheels_short"].value_counts()
    shown |= _take_rate_panel(fig, 1, 2, df, "wheels_short", wc, list(wc.index),
                              TAKE_RATE["wheels"], "trim", TRIM_COLORS,
                              "legend", not shown)

    ic = df["interior"].value_counts()
    ic_names = [s.replace(" Signature", "") for s in ic.index]
    shown |= _take_rate_panel(
        fig, 1, 3, df, "interior", ic, ic_names,
        [INTERIOR_COLOR.get(n, TAKE_RATE["interior_fallback"]) for n in ic_names],
        "trim", TRIM_COLORS, "legend", not shown)

    bc = df["buylease"].replace("", "Blank").value_counts()
    bl = df.assign(buylease=df["buylease"].replace("", "Blank"))
    shown |= _take_rate_panel(fig, 2, 1, bl, "buylease", bc, list(bc.index),
                              TAKE_RATE["buylease"], "trim", TRIM_COLORS,
                              "legend", not shown)

    sc = df["opted_spare"].map({True: "Yes", False: "No"}).value_counts()
    fig.add_trace(go.Bar(x=list(sc.index), y=np.asarray(sc.values),
                         marker_color=TAKE_RATE["spare"], showlegend=False,
                         marker_line=dict(color=CHART["edge"], width=1),
                         hovertemplate="%{x}: %{y}<extra></extra>"), 2, 2)

    # Uses the reconciled owner flag, so a row that named a model counts as an
    # owner (see parsing.reconcile_r1_owner) instead of contradicting its own stack.
    owner = df.get("r1_owner_effective", df["r1_owner"]).replace("", "Blank")
    rc = owner.value_counts()
    r1 = df.assign(r1_owner=owner)
    stacked_r1 = _take_rate_panel(fig, 2, 3, r1, "r1_owner", rc, list(rc.index),
                                  TAKE_RATE["r1_owner"], "r1_model",
                                  R1_MODEL_COLORS, "legend2", True)

    legends = {}
    if shown:
        legends["legend"] = dict(
            title=dict(text="Trim"), x=1.01, xanchor="left", y=0.99,
            yanchor="top", font=dict(size=11), bgcolor=CHART["legbg"],
            bordercolor=CHART["legbd"], borderwidth=1)
    if stacked_r1:
        legends["legend2"] = dict(
            title=dict(text="R1 owned"), x=1.01, xanchor="left", y=0.42,
            yanchor="top", font=dict(size=11), bgcolor=CHART["legbg"],
            bordercolor=CHART["legbd"], borderwidth=1)
    fig.update_layout(template="plotly_white", height=680, title_text=None,
                      bargap=0.25, barmode="stack",
                      margin=dict(r=150 if legends else 40), **legends)
    return fig


def fig_color_wheel_heatmap(df):
    """Color x wheels config-combo counts."""
    wheels = ['20" Black Sand', '21" Liquid Tungsten']
    colors = [c for c in COLOR_ORDER if (df["color"] == c).any()]
    z, text = [], []
    for c in colors:
        row, trow = [], []
        for w in wheels:
            n = int(((df["color"] == c) & (df["wheels_short"] == w)).sum())
            row.append(n)
            trow.append(str(n))
        z.append(row)
        text.append(trow)
    fig = go.Figure(go.Heatmap(
        z=z, x=wheels, y=colors, text=text, texttemplate="%{text}",
        textfont=dict(size=14), colorscale=HEATMAP_COLORSCALE, showscale=True,
        hovertemplate="%{y} + %{x}<br>%{z} orders<extra></extra>"))
    fig.update_layout(template="plotly_white", height=520,
                      xaxis_title="Wheels", yaxis_title="Exterior color",
                      yaxis=dict(autorange="reversed"))
    return fig


def fig_paint_by_location(df, min_state_orders=5):
    """Paint mix overall, by region, and by the states with enough orders.

    All three panels are 100% stacked, so a region/state's color preference is
    comparable regardless of how many orders it placed (the West has ~70x
    Canada's volume). The overall row on top is the baseline to read the rest
    against — whether a region over- or under-indexes on a paint. Absolute counts
    ride along in the hover and as an "n=" tick suffix. Segments use the real
    paint colors, in the shared COLOR_ORDER.

    Paint x state is ~45% empty and most states have 1-3 orders, where a single
    order swings the mix by 100 points — so the state panel is limited to states
    with at least `min_state_orders`, and the rest stay summarized by region.
    """
    d = df.dropna(subset=["lat"]).copy()
    counts = d["state"].value_counts()
    states = counts[counts >= min_state_orders].sort_values(ascending=True).index
    fig = make_subplots(
        rows=3, cols=1, vertical_spacing=0.09,
        # The overall row is a single bar; give the panels roughly the height
        # their bar counts need so no row looks stretched or crushed.
        row_heights=[0.1, 0.28, 0.62],
        subplot_titles=("All orders", "By region",
                        "By state (%d+ orders)" % min_state_orders))
    if d.empty:
        fig.update_layout(template="plotly_white", height=560)
        return fig

    colors = [c for c in COLOR_ORDER if (d["color"] == c).any()]
    keep = set(states)
    # Ascending so the biggest sits on top in each horizontal panel.
    regions = d["region"].value_counts().sort_values(ascending=True).index
    # A constant column lets the overall row reuse the same grouping code path.
    d["_all"] = "All orders"

    panels = [("_all", ["All orders"]), ("region", regions), ("state", states)]
    for row, (col, keys) in enumerate(panels, start=1):
        sub = d[d["state"].isin(keep)] if col == "state" else d
        tot = sub[col].value_counts()
        # "NAME  n=" labels keep the sample size visible next to every bar, so a
        # 100% split off a handful of orders can't be mistaken for a solid trend.
        labels = ["%s  n=%d" % (k, tot[k]) for k in keys]
        for c in colors:
            n = [int(((sub[col] == k) & (sub["color"] == c)).sum()) for k in keys]
            pct = [100.0 * v / tot[k] for v, k in zip(n, keys)]
            fig.add_trace(go.Bar(
                x=pct, y=labels, orientation="h", name=c, legendgroup=c,
                showlegend=(row == 1), customdata=np.array(n),
                marker=dict(color=COLOR_DISPLAY[c],
                            line=dict(color=CHART["edge"], width=0.5)),
                hovertemplate=("%{y}<br>" + c
                               + ": %{customdata} orders (%{x:.0f}%)<extra></extra>")),
                row, 1)

    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=True)
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    fig.update_layout(
        template="plotly_white", barmode="stack", bargap=0.28,
        height=380 + 24 * len(states),
        margin=dict(l=0, r=20, t=52, b=40),
        legend=dict(title=dict(text="Exterior paint"), traceorder="normal",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"],
                    borderwidth=1))
    return fig


_NO_STATE_DATA = "No state data"


def _numeric_bins(values, edges, unit):
    """Bin a numeric Series into ordered bar labels; NaN becomes _NO_STATE_DATA.

    Returns (labels, ordered_keys). Keys stay in NUMERIC order, never sorted by
    volume: the only question these panels ask is whether the mix shifts as the
    value rises, and reordering the bars by count would destroy that reading.
    Empty bins are dropped, so widening an edge in geo.yaml can't leave a gap.
    """
    def fmt(v):
        return format(int(round(v)), ",")

    names = ["< %s %s" % (fmt(edges[0]), unit)]
    names += ["%s–%s %s" % (fmt(lo), fmt(hi), unit)
              for lo, hi in zip(edges, edges[1:])]
    names.append("%s+ %s" % (fmt(edges[-1]), unit))

    def label(v):
        if pd.isna(v):
            return _NO_STATE_DATA
        return next((n for n, e in zip(names, edges) if v < e), names[-1])

    out = pd.Series([label(v) for v in values], index=values.index)
    keys = [n for n in names if (out == n).any()]
    if (out == _NO_STATE_DATA).any():
        keys.append(_NO_STATE_DATA)
    return out, keys


def fig_wheels_by_location(df):
    """Wheel mix overall, by region, and across the order state's reference figures.

    Every panel is 100% stacked, so the mix is comparable regardless of how many
    orders a row holds (the West has ~3x the Northeast). The "All orders" row on
    top is the baseline: read a row against it to see which way that group leans.
    Absolute counts ride along in the hover and as an "n=" suffix on every label,
    because a share off 18 orders and a share off 89 are not the same claim.

    The bottom three panels are ordered by VALUE, not by volume — the question is
    whether the mix shifts as you go higher, colder or denser, which only reads if
    the bars stay in numeric order.

    All three are per-state averages (geo.yaml), and the dashboard only knows an
    order's state, so each is a weak proxy with its own specific failure. Elevation
    is terrain, not where people live: a California order is charted at ~2,900 ft
    from San Diego or Tahoe alike, and California is a fifth of the cohort. Density
    divides by the whole state, so a big one-metro state reads rural — Nevada lands
    in the sparsest bar at 28/sq mi while roughly 94% of Nevadans are urban, and
    Utah, Idaho and Oregon sit beside it. Temperature flattens season and altitude
    together. They can suggest a lean; none of them is evidence of one. States with
    no published figures (every Canadian province) get their own bar rather than
    being dropped or guessed at.
    """
    d = df.dropna(subset=["lat"]).copy()
    if d.empty:
        fig = make_subplots(rows=5, cols=1)
        fig.update_layout(template="plotly_white", height=720)
        return fig

    # Wheels in the palette's ascending-size order (the order its colors were
    # validated in), then any value the palette doesn't know, which keeps an
    # unrecognized entry visible instead of silently folded into a real wheel.
    known = [w for w in WHEEL_ORDER if (d["wheels_short"] == w).any()]
    wheels = known + sorted(set(d["wheels_short"]) - set(WHEEL_ORDER))

    d["_all"] = "All orders"
    # Ascending so the biggest sits on top in the volume-ordered panels.
    regions = list(d["region"].value_counts().sort_values(ascending=True).index)
    d["_elev"], elev_keys = _numeric_bins(d["elev_ft"], ELEV_BINS, "ft")
    d["_temp"], temp_keys = _numeric_bins(d["temp_f"], TEMP_BINS, "°F")
    d["_dens"], dens_keys = _numeric_bins(d["pop_density"], DENSITY_BINS,
                                          "per sq mi")

    panels = [("_all", ["All orders"]), ("region", regions),
              ("_elev", elev_keys), ("_temp", temp_keys), ("_dens", dens_keys)]
    # Give each row roughly the height its bar count needs, so no panel looks
    # stretched or crushed; the single-bar top row still needs room for its title.
    weights = [1.8] + [len(keys) for _, keys in panels[1:]]
    fig = make_subplots(
        rows=len(panels), cols=1, vertical_spacing=0.055,
        row_heights=[w / sum(weights) for w in weights],
        subplot_titles=("All orders", "By region",
                        "By mean terrain elevation of the order's state",
                        "By average annual temperature of the order's state",
                        "By population density of the order's state"))

    for row, (col, keys) in enumerate(panels, start=1):
        tot = d[col].value_counts()
        labels = ["%s  n=%d" % (k, tot[k]) for k in keys]
        for w in wheels:
            n = [int(((d[col] == k) & (d["wheels_short"] == w)).sum())
                 for k in keys]
            pct = [100.0 * v / tot[k] for v, k in zip(n, keys)]
            fig.add_trace(go.Bar(
                x=pct, y=labels, orientation="h", name=w, legendgroup=w,
                showlegend=(row == 1), customdata=np.array(n),
                marker=dict(color=WHEEL_COLOR.get(w, CHART_UI["muted"]),
                            line=dict(color=CHART["edge"], width=0.5)),
                hovertemplate=("%{y}<br>" + w
                               + ": %{customdata} orders (%{x:.0f}%)<extra></extra>")),
                row, 1)

    bars = sum(len(keys) for _, keys in panels)
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=True)
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    fig.update_layout(
        template="plotly_white", barmode="stack", bargap=0.28,
        height=300 + 30 * bars,
        margin=dict(l=0, r=20, t=52, b=40),
        legend=dict(title=dict(text="Wheels"), traceorder="normal",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"],
                    borderwidth=1))
    return fig


def _priced(df):
    """Orders with a computable configured price. Anything that hit an unpublished
    price is left out here and counted separately in the report, never as zero."""
    return df[df["price"].notna()]


def _chart_title(text):
    """Layout title for a chart that shares a section with others, so each plot
    keeps its own heading. No explicit font color — it inherits layout.font, which
    THEME_JS re-tints, so the title follows the light/dark toggle."""
    return dict(text=text, x=0, xanchor="left", y=0.99, yanchor="top",
                font=dict(size=14))


# Label priority when two of a box's summary stats are too close to print side by
# side: the median matters most, the quartiles least.
_BOX_STATS = (("median", 0.50, 0), ("min", 0.0, 1), ("max", 1.0, 2),
              ("Q1", 0.25, 3), ("Q3", 0.75, 4))


def _label_box_stats(fig, values, y_label, span):
    """Label a box's summary statistics around it instead of in a hover tooltip.

    Plotly's default box hover stacks every stat and repeats the trace name on
    each line, which is noise when the series is already labelled on the axis.
    Printing the numbers next to the box makes them readable at a glance.

    The five-number summary goes BELOW the box; the mean goes ABOVE, directly over
    the dashed mean line that boxmean=True draws. Splitting them by side is what
    makes the mean printable at all: it usually sits within a few hundred dollars
    of the median, well inside the collision threshold used below, so sharing a row
    would just get it dropped. Its own side also ties it to the dashed line.

    Below the box, stats sharing a value are merged (Q1 == median happens whenever
    the cohort clusters on one price), and where two distinct stats still sit
    closer than ~8% of the axis span, the lower-priority one is dropped rather than
    overprinted.
    """
    v = pd.Series(list(values)).astype(float)
    groups = {}
    for name, q, pri in _BOX_STATS:
        val = round(float(v.quantile(q)))
        groups.setdefault(val, []).append((pri, name))
    merged = [(min(p for p, _ in g), val, " · ".join(n for _, n in sorted(g)))
              for val, g in groups.items()]
    kept = []
    for pri, val, name in sorted(merged):                 # most important first
        if all(abs(val - k[0]) >= span * 0.08 for k in kept):
            kept.append((val, name))
    for val, name in kept:
        fig.add_annotation(
            x=val, y=y_label, yshift=-30, showarrow=False, align="center",
            text="%s<br>$%s" % (name, format(val, ",")),
            font=dict(size=9, color=CHART["edge"]))
    # The mean, above the box and over its dashed line. Per-trim rather than the
    # cohort-wide mean on the distribution chart, which gets diluted as cheaper
    # trims arrive and stops describing any single trim.
    mean_val = round(float(v.mean()))
    fig.add_annotation(
        x=mean_val, y=y_label, yshift=24, showarrow=False, align="center",
        text="mean $%s" % format(mean_val, ","),
        font=dict(size=9, color=CHART["edge"]))


def fig_price_distribution(df):
    """How many orders landed on each exact configured price.

    One bar per distinct total rather than a binned histogram: the cohort lands on
    a small set of exact prices (options are fixed amounts), so binning would blur
    real structure. The median is marked by bolding its own tick label — this axis
    counts ORDERS, so a price-valued reference line would sit thousands of units
    off-scale and flatten every bar. The label prefix goes on the left of the
    right-aligned tick text, which keeps the dollar figures in a column.
    """
    d = _priced(df)
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=420)
        return fig
    counts = d["price"].value_counts().sort_index()
    prices = list(counts.index)
    med, mean = float(d["price"].median()), float(d["price"].mean())
    # An even n can put the median between two observed prices, so mark the
    # nearest bar rather than requiring an exact match.
    mi = min(range(len(prices)), key=lambda i: abs(prices[i] - med))
    labels = ["$%s" % format(round(p), ",") for p in prices]
    labels[mi] = "<b>median ► %s</b>" % labels[mi]
    fig.add_trace(go.Bar(
        x=np.asarray(counts.values), y=labels, orientation="h", showlegend=False,
        marker=dict(color=[PRICE_COLORS["accent"] if i == mi
                           else PRICE_COLORS["bar"] for i in range(len(prices))],
                    line=dict(color=CHART["edge"], width=0.5)),
        text=np.asarray(counts.values), textposition="outside", cliponaxis=False,
        textfont=dict(size=10), customdata=np.asarray(prices),
        hovertemplate="$%{customdata:,.0f} — %{x} orders<extra></extra>"))
    fig.add_annotation(
        x=0.99, xref="x domain", y=0.99, yref="y domain", xanchor="right",
        yanchor="top", showarrow=False,
        font=dict(size=11, color=CHART["edge"]),
        text="mean $%s   ·   range $%s – $%s"
             % (format(round(mean), ","), format(round(d["price"].min()), ","),
                format(round(d["price"].max()), ",")))
    fig.update_layout(
        template="plotly_white", bargap=0.3, height=210 + 26 * len(counts),
        title=_chart_title("Price distribution"),
        margin=dict(l=0, r=30, t=46, b=45),
        xaxis=dict(title_text="Orders", rangemode="tozero",
                   range=[0, float(counts.max()) * 1.14]),
        yaxis=dict(ticksuffix="  ", automargin=True))
    return fig


def fig_price_options(df):
    """Average spend per option category, with each category's take rate.

    The trim base is deliberately excluded: it's a constant per trim and ~140x the
    largest option, so including it would flatten every other bar to nothing. What
    varies — and what buyers actually choose — is the options. The take rate rides
    along because a large average means something different when everyone pays a
    little than when a few pay a lot.
    """
    d = _priced(df)
    n = len(d)
    fig = go.Figure()
    if not n:
        fig.update_layout(template="plotly_white", height=300)
        return fig
    cats = [("price_drive", "Drive system", None),
            ("price_paint", "Paint", None),
            ("price_wheels", "Wheels", None),
            # A zero row is kept only with a note explaining WHY it's zero,
            # because "nobody bought the upgrade" and "everybody gets it free"
            # look identical at $0 and mean opposite things.
            ("price_interior", "Interior", "none paid yet"),
            ("price_spare", "Compact spare", None),
            ("price_autonomy_tow", "Autonomy+ / Tow", "bundled")]
    # How many hold a bundled option without paying — the count behind that note.
    held = 0
    if {"opted_autonomy", "opted_tow"} <= set(d.columns):
        held = int((d["opted_autonomy"] | d["opted_tow"]).sum())
    rows = []
    for col, label, zero_note in cats:
        v = d[col].fillna(0)
        avg, paid = float(v.mean()), v[v > 0]
        if not avg and zero_note is None:
            continue            # structurally inapplicable — don't list an empty row
        if len(paid):
            pct = 100.0 * len(paid) / n
            # A handful of orders rounds to "0% chose", which reads as nobody —
            # give the raw count instead when the share is under a percent.
            note = ("%d of %d paid · $%s" % (len(paid), n,
                                             format(round(paid.mean()), ","))
                    if pct < 1 else
                    "%.0f%% chose · $%s avg" % (pct,
                                                format(round(paid.mean()), ",")))
        elif zero_note == "bundled":
            note = "included free for %d of %d" % (held, n)
        else:
            note = zero_note
        rows.append((label, avg, note, len(paid)))
    rows.sort(key=lambda r: r[1])       # biggest spend on top of a horizontal bar
    opt_mean = float((d["price"] - d["price_base"].fillna(0)).mean())
    fig.add_trace(go.Bar(
        x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h",
        showlegend=False,
        marker=dict(color=PRICE_COLORS["accent"],
                    line=dict(color=CHART["edge"], width=0.5)),
        # Amount and take-rate on separate lines: as one line this ran off the
        # right edge on a phone-width viewport, and stacking roughly halves the
        # label's width without costing any row height.
        text=["$%s<br>%s" % (format(round(r[1]), ","), r[2]) for r in rows],
        textposition="outside", cliponaxis=False, textfont=dict(size=10),
        customdata=np.array([r[3] for r in rows]),
        hovertemplate="%{y}: $%{x:,.0f} avg across all orders"
                      "<br>%{customdata} orders paid for it<extra></extra>"))
    fig.add_annotation(
        x=0.99, xref="paper", y=0.02, yref="paper", xanchor="right",
        yanchor="bottom", showarrow=False,
        font=dict(size=11, color=CHART["edge"]),
        text="options add $%s per order on average  ·  %.1f%% of the price"
             % (format(round(opt_mean), ","),
                100.0 * opt_mean / float(d["price"].mean())))
    fig.update_layout(
        template="plotly_white", bargap=0.34, height=180 + 42 * len(rows),
        title=_chart_title("Where the option money goes"),
        margin=dict(l=0, r=30, t=46, b=45),
        # Headroom for the outside labels, which carry the take-rate text. Sized
        # from the longest label rather than a round multiple: the take-rate text
        # runs to roughly 1.4x the largest bar, and anything beyond that is dead
        # width (2.1x left a third of the panel empty).
        xaxis=dict(title_text="Average dollars per order", rangemode="tozero",
                   tickprefix="$", tickformat=",",
                   range=[0, max(r[1] for r in rows) * 1.5] if rows else None),
        yaxis=dict(ticksuffix="  ", automargin=True))
    return fig


def fig_price_by_trim(df):
    """Configured-price spread per trim.

    Trims with no orders yet still get a row, labelled in the plot area, so the
    chart shows the whole lineup and it's obvious which ones simply haven't been
    ordered rather than leaving the reader to wonder what's missing.
    """
    d = _priced(df)
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=260)
        return fig
    have = [t for t in PRICE_TRIMS if (d["price_trim"] == t).any()]
    missing = [t for t in PRICE_TRIMS if t not in have]
    labels = {t: "%s  n=%d" % (t, int((d["price_trim"] == t).sum()))
              for t in have}
    labels.update({t: "%s  n=0" % t for t in missing})

    for trim in have:
        sub = d[d["price_trim"] == trim]
        fig.add_trace(go.Box(
            x=np.asarray(sub["price"]), name=labels[trim], orientation="h",
            showlegend=False, boxmean=True,
            marker=dict(color=PRICE_COLORS["bar"], outliercolor=CHART["edge"]),
            # CHART["edge"] is theme-managed: THEME_JS re-tints box line colors,
            # so the outline and whiskers stay legible in dark mode.
            line=dict(color=CHART["edge"], width=1.2),
            fillcolor=PRICE_COLORS["bar"],
            # Hover only the outlier points. The box's own five-number summary is
            # printed beneath it instead — Plotly's box tooltip stacks all five
            # stats and repeats the series name on each line.
            hoveron="points", hovertemplate="$%{x:,.0f}<extra></extra>"))

    lo, hi = float(d["price"].min()), float(d["price"].max())
    pad = max((hi - lo) * 0.08, 500.0)
    span = (hi + pad) - (lo - pad)
    for trim in have:
        _label_box_stats(fig, d.loc[d["price_trim"] == trim, "price"],
                         labels[trim], span)
    # A transparent point per empty trim creates its category on the axis; the
    # note then sits in the plot area at that row, like the option panel's
    # "none paid yet", instead of a floating caption the margin could clip.
    for trim in missing:
        fig.add_trace(go.Scatter(
            x=[lo - pad], y=[labels[trim]], mode="markers", showlegend=False,
            marker=dict(size=1, opacity=0), hoverinfo="skip"))
        fig.add_annotation(
            x=lo - pad * 0.8, y=labels[trim], text="no orders yet",
            showarrow=False, xanchor="left", yanchor="middle",
            font=dict(size=10, color=CHART["edge"]))
    fig.update_layout(
        template="plotly_white",
        # A tall band per trim left ~60px of dead space under each row. Keep the
        # band just deep enough for the box plus its labels — the summary below and
        # the mean above — and thin the box (boxgap) so both clear its edges.
        boxgap=0.66, height=112 + 82 * len(PRICE_TRIMS),
        title=_chart_title("Configured price by trim"),
        margin=dict(l=0, r=30, t=46, b=45),
        xaxis=dict(title_text="Configured price", tickprefix="$", tickformat=",",
                   range=[lo - pad, hi + pad]),
        # Keep the lineup in pricing.yaml order, top-down, whether or not a trim
        # has any orders.
        yaxis=dict(ticksuffix="  ", automargin=True, categoryorder="array",
                   categoryarray=[labels[t] for t in reversed(list(PRICE_TRIMS))]))
    return fig


def fig_order_timeline(df, resv=None):
    """Reservation vs. order timeline. The reservation panel stacks two
    series: holders who have since ordered vs. reservation-only (incomplete)."""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Reservation dates — ordered vs. still incomplete",
                        "R2 order (config-lock) dates"))
    week = 86400000 * 7  # ms
    fig.add_trace(go.Histogram(
        x=np.asarray(df["resv_date"].dropna()), name="Reserved & ordered",
        legendgroup="r", marker_color=TIMELINE_COLORS["ordered"],
        xbins=dict(size=week)), 1, 1)
    if resv is not None and len(resv):
        fig.add_trace(go.Histogram(
            x=np.asarray(resv["resv_date"].dropna()),
            name="Reserved only (incomplete)", legendgroup="r",
            marker_color=TIMELINE_COLORS["reserved_only"], xbins=dict(size=week)), 1, 1)
    fig.add_trace(go.Histogram(x=np.asarray(df["order_date"].dropna()),
                               marker_color=TIMELINE_COLORS["ordered"], showlegend=False,
                               xbins=dict(size=86400000 * 3)), 2, 1)  # 3-day bins

    # The 3/7/2024 reveal week (~20x the next-biggest week) flattens everything
    # else, so clip the reservation panel's y-axis just above the tail and
    # annotate the reveal bar with its true height.
    dated = df["resv_date"].dropna()
    if resv is not None and len(resv):
        dated = pd.concat([dated, resv["resv_date"].dropna()])
    if len(dated):
        wk = dated.dt.to_period("W-SUN").value_counts()
        spike = int(wk.max())
        spike_start = wk.idxmax().start_time
        cap = 50  # clip the reveal week (and its immediate aftermath) so the tail reads
        if spike > cap:
            fig.update_yaxes(range=[0, cap], row=1, col=1)
            fig.add_annotation(
                x=spike_start + pd.Timedelta(days=3), y=cap, xref="x", yref="y",
                text=("Reveal week (Mar 2024): %s reservations —<br>"
                      "y-axis clipped at %d to show the tail"
                      % (format(spike, ","), cap)),
                showarrow=True, arrowhead=2, arrowwidth=1.3,
                arrowcolor=CHART_UI["annotation_arrow"],
                ax=120, ay=-6, align="left",
                font=dict(size=11, color=CHART_UI["annotation_text"]),
                bgcolor=CHART_UI["annotation_bg"],
                bordercolor=CHART_UI["annotation_border"], borderwidth=1)

    fig.update_layout(template="plotly_white", height=720, bargap=0.05,
                      barmode="stack",
                      legend=dict(orientation="h", yanchor="bottom", y=1.10,
                                  xanchor="left", x=0, groupclick="toggleitem"),
                      margin=dict(t=90))
    fig.update_yaxes(title_text="Reservations", row=1, col=1)
    fig.update_yaxes(title_text="Orders", row=2, col=1)
    return fig


def fig_delivery_timeline(df):
    """Estimated delivery timeline, stacked by estimate certainty."""
    fig = go.Figure()
    for t in TYPE_ORDER:
        s = df[(df["delivery_type"] == t) & df["delivery_est"].notna()]
        if s.empty:
            continue
        fig.add_trace(go.Histogram(
            x=np.asarray(s["delivery_est"]), name=t, marker_color=TYPE_COLOR[t],
            xbins=dict(size=86400000 * 7)))  # weekly bins
    fig.update_layout(template="plotly_white", barmode="stack", height=560,
                      xaxis_title="Estimated delivery date",
                      yaxis_title="Orders", legend_title="Estimate type",
                      bargap=0.05)
    _add_today_vline(fig)
    return fig


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
    return (g.groupby("region").size().sort_values(ascending=True)
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
    panels = [(t, _geo_counts(f), _region_counts(f)) for t, f in panels]

    n = len(panels)
    vs = 0.05
    # Two columns per row: the map, then that panel's region totals. Subplot
    # titles are placed only on the maps (the bars are self-labeling).
    fig = make_subplots(
        rows=n, cols=2, column_widths=[0.74, 0.26], horizontal_spacing=0.08,
        specs=[[{"type": "scattergeo"}, {"type": "xy"}] for _ in range(n)],
        subplot_titles=[s for t, _, _ in panels for s in (t, "")],
        vertical_spacing=vs)

    order_max = max([g["n"].max() for t, g, _ in panels[:2] if len(g)] or [1])
    rowh = (1 - vs * (n - 1)) / n
    legends = {}
    for i, (title, g, reg) in enumerate(panels, start=1):
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
        vals = panels[i - 1][2]
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


def fig_state_totals(df):
    """Per-state order counts as a delivery pipeline.

    Every state that has ordered, sorted by total. Three segments stack to the
    state's full order count, so the bar length is the state total while the split
    shows how far along that state is: assumed delivered, then still awaiting
    delivery with a VIN known, then no VIN yet. Complements the maps above, where
    the long tail of one- and two-order states is hard to compare by bubble area.

    The three are a strict partition of the state's orders — "delivered" is
    subtracted from whichever VIN bucket it came from, so the segments always sum
    to the total. Deliveries are counted whether or not a VIN is known: someone may
    have posted about taking delivery without ever updating (or while obfuscating)
    their VIN, and dropping those would undercount.
    """
    d = df.dropna(subset=["lat"])
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=420)
        return fig
    tot = d.groupby("state").size().sort_values(ascending=True)

    def per_state(mask):
        return d[mask].groupby("state").size().reindex(tot.index, fill_value=0)

    delivered_mask = (d["delivered_inferred"]
                      if "delivered_inferred" in d.columns
                      else pd.Series(False, index=d.index))
    delivered = per_state(delivered_mask)
    # Pending, split by VIN. Deducting delivered from each bucket is what keeps the
    # stack summing to the state total.
    vin = per_state(d["vin_present"] & ~delivered_mask)
    novin = per_state(~d["vin_present"] & ~delivered_mask)

    states = np.asarray(tot.index)
    series = (("Delivered (est.)", delivered, STATE_TOTALS_COLORS["delivered"]),
              ("Awaiting delivery · VIN", vin, STATE_TOTALS_COLORS["vin"]),
              ("Awaiting delivery · no VIN", novin, STATE_TOTALS_COLORS["no_vin"]))
    for name, vals, color in series:
        fig.add_trace(go.Bar(
            x=np.asarray(vals.values), y=states, orientation="h", name=name,
            marker=dict(color=color, line=dict(color=CHART["edge"], width=0.5)),
            hovertemplate="%%{y} — %s: %%{x}<extra></extra>" % name))
    # Total at the end of each stacked bar (an invisible bar carrying the label).
    fig.add_trace(go.Bar(
        x=np.zeros(len(states)), y=states, orientation="h", showlegend=False,
        marker=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        text=np.asarray(tot.values), textposition="outside", cliponaxis=False,
        textfont=dict(size=10)))
    # ~18px per state keeps the labels legible as the tail grows.
    fig.update_layout(
        template="plotly_white", barmode="stack", bargap=0.25,
        height=max(420, 34 + 18 * len(states)),
        # t=34 leaves room for the 22px modebar to sit in the margin instead of
        # over the longest bar. Every other chart on the page already has 30-100px
        # here (mostly Plotly's default), so this one was the outlier at t=10 —
        # matching them keeps the toolbar horizontal everywhere.
        margin=dict(l=0, r=30, t=34, b=40),
        xaxis=dict(title="Orders", rangemode="tozero",
                   range=[0, float(tot.max()) * 1.08]),
        yaxis=dict(ticksuffix="  ", automargin=True),
        # Floated into the bottom-right of the plot rather than sitting above it:
        # the top-right is where Plotly puts its modebar, which covered the legend.
        # Bars are sorted ascending, so the smallest states leave that corner
        # empty. traceorder="normal" makes the legend read top-down in the same
        # pipeline order the bars stack (it reverses by default).
        legend=dict(title=dict(text="Status"), traceorder="normal",
                    x=0.98, xanchor="right", y=0.02, yanchor="bottom",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"],
                    borderwidth=1))
    return fig


def fig_certainty_by_vin(df):
    """Delivery-estimate certainty for VIN-assigned vs. not, as donut charts
    so the type mix reads as percentages within each group."""
    groups = [("VIN assigned", df[df["vin_present"]]),
              ("No VIN yet", df[~df["vin_present"]])]
    all_types = TYPE_ORDER + ["unknown"]
    tcolor = TYPE_COLOR  # includes "unknown" (from palette.yaml delivery_types)
    fig = make_subplots(
        rows=1, cols=len(groups),
        specs=[[{"type": "domain"} for _ in groups]],
        subplot_titles=["%s  (n=%d)" % (label, len(sub)) for label, sub in groups])
    for i, (label, sub) in enumerate(groups, start=1):
        counts = [int((sub["delivery_type"] == t).sum()) for t in all_types]
        fig.add_trace(go.Pie(
            labels=all_types, values=counts, hole=0.5, sort=False,
            direction="clockwise", showlegend=(i == 1),
            marker=dict(colors=[tcolor[t] for t in all_types],
                        line=dict(color=CHART_UI["pie_gap"], width=1)),
            texttemplate="%{percent}", textposition="inside",
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"), 1, i)
    fig.update_layout(template="plotly_white", height=460,
                      legend_title="Estimate type")
    return fig


def fig_vin_by_config(df):
    """VIN sequence per full configuration (trim · color · wheels).

    Each VIN-assigned order sits at its production sequence (x); rows group
    orders by configuration. Clusters along a row hint at same-config cars built
    in a batch. Today everyone is Performance (Launch Edition); Premium and
    Standard rows will appear as those trims ship.
    """
    d = df[df["vin_present"]].copy()
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=420)
        return fig
    # Compact per-wheel tag: size alone is ambiguous now that two of the four
    # wheels are 20", so the abbreviation carries All-Season/All-Terrain too.
    wheel_abbr = d["wheels_short"].map(lambda w: WHEEL_ABBR.get(w, w))
    d["_combo"] = d["trim"] + " · " + d["color"] + " · " + wheel_abbr
    color_rank = {c: i for i, c in enumerate(COLOR_ORDER)}

    def _key(combo):
        trim, color, wheel = combo.split(" · ")
        return (trim, color_rank.get(color, 99), wheel)

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
