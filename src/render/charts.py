"""Plotly chart builders for the dashboard (the nine fig_* functions plus their
shared helpers). Pure figure construction from the cleaned DataFrames.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .colors import COLOR_DISPLAY, REGION_WHISKER, WHISKER_HEX
from config import (AS_OF, CHART, CHART_UI, COLOR_ORDER, FACTORY,
                     HEATMAP_COLORSCALE, INTERIOR_COLOR, PRICE_TRIMS,
                     REGION_COLOR, STATE_TOTALS_COLORS, TAKE_RATE,
                     TIMELINE_COLORS, TYPE_COLOR, TYPE_OPACITY, TYPE_ORDER,
                     WHEEL_SYMBOL)

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


def fig_config_dashboard(df):
    """Config take-rate small-multiples."""
    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=("Exterior color", "Wheels", "Interior",
                        "Purchase vs. lease", "Compact spare tire",
                        "Current R1 owner?"))

    cc = df["color"].value_counts()  # descending by popularity
    fig.add_trace(go.Bar(x=list(cc.index), y=np.asarray(cc.values),
                         marker_color=[COLOR_DISPLAY[c] for c in cc.index],
                         marker_line=dict(color=CHART["edge"], width=1),
                         showlegend=False), 1, 1)

    wc = df["wheels_short"].value_counts()
    fig.add_trace(go.Bar(x=list(wc.index), y=np.asarray(wc.values),
                         marker_color=TAKE_RATE["wheels"], showlegend=False), 1, 2)

    ic = df["interior"].value_counts()
    ic_names = [s.replace(" Signature", "") for s in ic.index]
    fig.add_trace(go.Bar(x=ic_names, y=np.asarray(ic.values),
                         marker_color=[INTERIOR_COLOR.get(n, TAKE_RATE["interior_fallback"])
                                       for n in ic_names],
                         marker_line=dict(color=CHART["edge"], width=1),
                         showlegend=False), 1, 3)

    bc = df["buylease"].value_counts()
    fig.add_trace(go.Bar(x=list(bc.index), y=np.asarray(bc.values),
                         marker_color=TAKE_RATE["buylease"], showlegend=False), 2, 1)

    sc = df["opted_spare"].map({True: "Yes", False: "No"}).value_counts()
    fig.add_trace(go.Bar(x=list(sc.index), y=np.asarray(sc.values),
                         marker_color=TAKE_RATE["spare"], showlegend=False), 2, 2)

    rc = df["r1_owner"].replace("", "Blank").value_counts()
    fig.add_trace(go.Bar(x=list(rc.index), y=np.asarray(rc.values),
                         marker_color=TAKE_RATE["r1_owner"], showlegend=False), 2, 3)

    fig.update_layout(template="plotly_white", height=680,
                      title_text=None, bargap=0.25)
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


def fig_price(df):
    """Configured price in three panels: the distribution, what the average
    dollar buys, and a box per trim.

    Panel 1 is one bar per distinct price (the cohort lands on a small set of
    exact totals, so a binned histogram would blur real structure), with median
    and mean reference lines. Panel 2 decomposes the cohort's average price into
    base plus each option category, which is where the interesting variation
    lives while everyone is on one trim. Panel 3 is the per-trim box-and-whisker,
    which fills in as Premium and Standard ship.

    Orders whose configuration hit an unpublished price are excluded here and
    counted separately in the report, never folded in as zero.
    """
    d = df[df["price"].notna()]
    fig = make_subplots(
        rows=3, cols=1, vertical_spacing=0.11, row_heights=[0.42, 0.31, 0.27],
        subplot_titles=("Price distribution", "Where the money goes (cohort average)",
                        "By trim"))
    if d.empty:
        fig.update_layout(template="plotly_white", height=640)
        return fig

    money = "$%{x:,.0f}"
    # --- Panel 1: one bar per exact price ---
    counts = d["price"].value_counts().sort_index()
    fig.add_trace(go.Bar(
        x=np.asarray(counts.values),
        y=[format(round(p), ",") for p in counts.index],
        orientation="h", showlegend=False,
        marker=dict(color=TAKE_RATE["wheels"],
                    line=dict(color=CHART["edge"], width=0.5)),
        text=np.asarray(counts.values), textposition="outside", cliponaxis=False,
        textfont=dict(size=10),
        hovertemplate="$%{y} — %{x} orders<extra></extra>"), 1, 1)

    # --- Panel 2: average price decomposition ---
    # Base first, then each option category, largest contribution downward.
    labels, values = ["Base"], [float(d["price_base"].fillna(0).mean())]
    cats = [("price_drive", "Drive system"), ("price_package", "Package"),
            ("price_paint", "Paint"), ("price_wheels", "Wheels"),
            ("price_interior", "Interior"), ("price_spare", "Compact spare"),
            ("price_autonomy_tow", "Autonomy+ / Tow")]
    for col, label in cats:
        v = float(d[col].fillna(0).mean())
        if v:                                   # skip categories nobody paid for
            labels.append(label)
            values.append(v)
    fig.add_trace(go.Bar(
        x=values[::-1], y=labels[::-1], orientation="h", showlegend=False,
        marker=dict(color=[TAKE_RATE["buylease"] if l != "Base"
                           else CHART_UI["muted"] for l in labels[::-1]],
                    line=dict(color=CHART["edge"], width=0.5)),
        text=["$%s" % format(round(v), ",") for v in values[::-1]],
        textposition="outside", cliponaxis=False, textfont=dict(size=10),
        hovertemplate="%{y}: " + money + " avg<extra></extra>"), 2, 1)

    # --- Panel 3: box per trim, in the pricing.yaml order ---
    order = [t for t in PRICE_TRIMS if (d["price_trim"] == t).any()]
    for trim in order:
        sub = d[d["price_trim"] == trim]
        fig.add_trace(go.Box(
            x=np.asarray(sub["price"]), name="%s  n=%d" % (trim, len(sub)),
            orientation="h", showlegend=False, boxmean=True,
            marker=dict(color=TAKE_RATE["wheels"], outliercolor=CHART["edge"]),
            line=dict(color=CHART["edge"], width=1.2),
            fillcolor=TAKE_RATE["wheels"],
            hovertemplate=money + "<extra></extra>"), 3, 1)
    # Name the trims that exist in the catalog but have no orders yet, so the
    # panel reads as "not ordered yet" rather than looking incomplete.
    missing = [t for t in PRICE_TRIMS if t not in order]
    if missing:
        fig.add_annotation(
            row=3, col=1, x=0, xref="x domain", y=-0.35, yref="y domain",
            xanchor="left", showarrow=False, font=dict(size=10, color=CHART["edge"]),
            text="no orders yet: " + ", ".join(missing))

    med, mean = float(d["price"].median()), float(d["price"].mean())
    for val, dash, label in ((med, "solid", "median"), (mean, "dash", "mean")):
        fig.add_vline(x=val, row=1, col=1, line_width=1.4, line_dash=dash,
                      line_color=CHART["edge"], annotation_position="top",
                      annotation_text="%s $%s" % (label, format(round(val), ",")),
                      annotation_font_size=10,
                      annotation_font_color=CHART["edge"])

    fig.update_xaxes(title_text="Orders", row=1, col=1, rangemode="tozero")
    fig.update_xaxes(title_text="Average dollars", row=2, col=1,
                     rangemode="tozero")
    fig.update_xaxes(title_text="Configured price", row=3, col=1, tickprefix="$",
                     tickformat=",")
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    fig.update_yaxes(tickprefix="$", row=1, col=1)
    fig.update_layout(template="plotly_white", bargap=0.3,
                      height=420 + 26 * len(counts) + 30 * len(order),
                      margin=dict(l=0, r=30, t=60, b=40))
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
    fig.update_layout(template="plotly_white", height=380 * n, bargap=0.35,
                      margin=dict(l=0, r=140, t=30, b=0), **legends)
    return fig


def fig_state_totals(df):
    """Per-state order counts, split into VIN-assigned vs. not.

    Every state that has ordered, sorted by total. The two segments stack to the
    state's full order count, so the bar length is the state total while the
    split shows how far along production is for that state. Complements the maps
    above, where the long tail of one- and two-order states is hard to compare
    by bubble area."""
    d = df.dropna(subset=["lat"])
    fig = go.Figure()
    if d.empty:
        fig.update_layout(template="plotly_white", height=420)
        return fig
    tot = d.groupby("state").size().sort_values(ascending=True)
    vin = d[d["vin_present"]].groupby("state").size().reindex(tot.index, fill_value=0)
    novin = tot - vin
    states = np.asarray(tot.index)
    for name, vals, color in (("VIN assigned", vin, STATE_TOTALS_COLORS["vin"]),
                              ("No VIN yet", novin, STATE_TOTALS_COLORS["no_vin"])):
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
        margin=dict(l=0, r=30, t=10, b=40),
        xaxis=dict(title="Orders", rangemode="tozero",
                   range=[0, float(tot.max()) * 1.08]),
        yaxis=dict(ticksuffix="  ", automargin=True),
        legend=dict(title=dict(text="VIN status"), orientation="h",
                    yanchor="bottom", y=1.01, xanchor="right", x=1,
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
    wheel_abbr = d["wheels_short"].str.split().str[0]      # 21" / 20"
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
    for label, sym in WHEEL_SYMBOL.items():                # wheel-symbol legend
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label,
            marker=dict(color=CHART_UI["key_marker"], size=10, symbol=sym,
                        line=dict(color=CHART["edge"], width=0.6))))
    fig.update_layout(
        template="plotly_white", height=max(420, 42 * len(combos) + 180),
        xaxis_title="VIN sequence number  (production order →)",
        yaxis=dict(tickmode="array", tickvals=list(range(len(combos))),
                   ticktext=combos, automargin=True, autorange="reversed"),
        legend_title="Wheels", hovermode="closest")
    return fig
