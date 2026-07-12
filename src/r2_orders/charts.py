"""Plotly chart builders for the dashboard (the nine fig_* functions plus their
shared helpers). Pure figure construction from the cleaned DataFrames.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .colors import COLOR_DISPLAY, REGION_WHISKER, WHISKER_HEX
from .config import (AS_OF, COLOR_ORDER, FACTORY, INTERIOR_COLOR, REGION_COLOR,
                     TYPE_COLOR, TYPE_OPACITY, TYPE_ORDER, WHEEL_SYMBOL)

# Theme-aware "today" reference line at the run date (AS_OF). Baked in the
# light-theme grey; the dashboard's theme toggle re-tints managed greys — in
# shapes and their labels too — so it flips with the rest of the chart chrome.
_TODAY = dict(line_width=1.5, line_dash="dash", line_color="#2b2b2b",
              annotation_text="Today", annotation_font_color="#2b2b2b",
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
                 bgcolor="rgba(255,255,255,0.9)", bordercolor="#cccccc",
                 font=dict(size=11, color="#2b2b2b"),
                 buttons=[dict(label="Whiskers", method="restyle",
                              args=[{"visible": True}, idx]),
                          dict(label="No whiskers", method="restyle",
                              args=[{"visible": False}, idx])])]


def fig_delivery_vs_vin(df):
    """#1 Estimated delivery date vs VIN sequence, coded by config.

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
                        line=dict(color="#2b2b2b", width=0.8)),
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
    """#2 Destination (state, ordered by distance from factory) vs delivery.

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
                        line=dict(color="#2b2b2b", width=0.5)),
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
    """#3 VIN sequence vs R2 order date, coded by config. One legend entry per
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
                        line=dict(color="#2b2b2b", width=0.8)),
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
    """#4 Config take-rate small-multiples."""
    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=("Exterior color", "Wheels", "Interior",
                        "Purchase vs. lease", "Compact spare tire",
                        "Current R1 owner?"))

    cc = df["color"].value_counts()  # descending by popularity
    fig.add_trace(go.Bar(x=list(cc.index), y=np.asarray(cc.values),
                         marker_color=[COLOR_DISPLAY[c] for c in cc.index],
                         marker_line=dict(color="#2b2b2b", width=1),
                         showlegend=False), 1, 1)

    wc = df["wheels_short"].value_counts()
    fig.add_trace(go.Bar(x=list(wc.index), y=np.asarray(wc.values),
                         marker_color="#4c78a8", showlegend=False), 1, 2)

    ic = df["interior"].value_counts()
    ic_names = [s.replace(" Signature", "") for s in ic.index]
    fig.add_trace(go.Bar(x=ic_names, y=np.asarray(ic.values),
                         marker_color=[INTERIOR_COLOR.get(n, "#8899a6")
                                       for n in ic_names],
                         marker_line=dict(color="#2b2b2b", width=1),
                         showlegend=False), 1, 3)

    bc = df["buylease"].value_counts()
    fig.add_trace(go.Bar(x=list(bc.index), y=np.asarray(bc.values),
                         marker_color="#f58518", showlegend=False), 2, 1)

    sc = df["opted_spare"].map({True: "Yes", False: "No"}).value_counts()
    fig.add_trace(go.Bar(x=list(sc.index), y=np.asarray(sc.values),
                         marker_color="#e45756", showlegend=False), 2, 2)

    rc = df["r1_owner"].replace("", "Blank").value_counts()
    fig.add_trace(go.Bar(x=list(rc.index), y=np.asarray(rc.values),
                         marker_color="#54a24b", showlegend=False), 2, 3)

    fig.update_layout(template="plotly_white", height=680,
                      title_text=None, bargap=0.25)
    return fig


def fig_color_wheel_heatmap(df):
    """#5 Color x wheels config-combo counts."""
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
        textfont=dict(size=14), colorscale="Blues", showscale=True,
        hovertemplate="%{y} + %{x}<br>%{z} orders<extra></extra>"))
    fig.update_layout(template="plotly_white", height=520,
                      xaxis_title="Wheels", yaxis_title="Exterior color",
                      yaxis=dict(autorange="reversed"))
    return fig


def fig_order_timeline(df, resv=None):
    """#6 Reservation vs. order timeline. The reservation panel stacks two
    series: holders who have since ordered vs. reservation-only (incomplete)."""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Reservation dates — ordered vs. still incomplete",
                        "R2 order (config-lock) dates"))
    week = 86400000 * 7  # ms
    fig.add_trace(go.Histogram(
        x=np.asarray(df["resv_date"].dropna()), name="Reserved & ordered",
        legendgroup="r", marker_color="#f58518",
        xbins=dict(size=week)), 1, 1)
    if resv is not None and len(resv):
        fig.add_trace(go.Histogram(
            x=np.asarray(resv["resv_date"].dropna()),
            name="Reserved only (incomplete)", legendgroup="r",
            marker_color="#4c78a8", xbins=dict(size=week)), 1, 1)
    fig.add_trace(go.Histogram(x=np.asarray(df["order_date"].dropna()),
                               marker_color="#f58518", showlegend=False,
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
                showarrow=True, arrowhead=2, arrowwidth=1.3, arrowcolor="#4c78a8",
                ax=120, ay=-6, align="left", font=dict(size=11, color="#33475a"),
                bgcolor="rgba(255,255,255,0.9)", bordercolor="#cdd", borderwidth=1)

    fig.update_layout(template="plotly_white", height=720, bargap=0.05,
                      barmode="stack",
                      legend=dict(orientation="h", yanchor="bottom", y=1.10,
                                  xanchor="left", x=0, groupclick="toggleitem"),
                      margin=dict(t=90))
    fig.update_yaxes(title_text="Reservations", row=1, col=1)
    fig.update_yaxes(title_text="Orders", row=2, col=1)
    return fig


def fig_delivery_timeline(df):
    """#7 Estimated delivery timeline, stacked by estimate certainty."""
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


def fig_geo(df, resv=None):
    """#8 Geographic demand in three stacked maps, each with its own legend:
    orders with a VIN, all orders, and total demand (orders + incomplete
    reservations). Bubble area = count.

    The VIN and all-orders panels share a bubble scale (comparable magnitudes);
    total demand is ~20x larger, so it scales to its own max."""
    panels = [("VIN assigned", _geo_counts(df[df["vin_present"]])),
              ("All orders", _geo_counts(df))]
    if resv is not None and len(resv):
        cols = ["user", "state", "lat", "lon", "region"]
        combined = pd.concat([df[cols], resv[cols]], ignore_index=True)
        panels.append(("Total demand (orders + incomplete reservations)",
                       _geo_counts(combined)))

    n = len(panels)
    vs = 0.05
    fig = make_subplots(
        rows=n, cols=1, specs=[[{"type": "scattergeo"}] for _ in range(n)],
        subplot_titles=[t for t, _ in panels], vertical_spacing=vs)

    order_max = max([g["n"].max() for t, g in panels[:2] if len(g)] or [1])
    rowh = (1 - vs * (n - 1)) / n
    legends = {}
    for i, (title, g) in enumerate(panels, start=1):
        geo_key = "geo" if i == 1 else "geo%d" % i
        legend_key = "legend" if i == 1 else "legend%d" % i
        y_top = 1 - (i - 1) * (rowh + vs)
        legends[legend_key] = dict(
            x=1.01, xanchor="left", y=y_top - rowh / 2, yanchor="middle",
            title=dict(text="Region"), font=dict(size=11), itemsizing="constant",
            bgcolor="rgba(255,255,255,0.75)", bordercolor="#ddd", borderwidth=1)
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
                            color=REGION_COLOR.get(region, "#888"),
                            line=dict(color="#2b2b2b", width=0.5)),
                customdata=np.asarray(sub["n"]),
                hovertemplate="%{text}: %{customdata}<extra></extra>"), i, 1)
        fig.add_trace(go.Scattergeo(
            lat=[FACTORY[0]], lon=[FACTORY[1]], mode="markers", name="Factory",
            showlegend=False, marker=dict(size=11, symbol="star", color="#111"),
            hovertemplate="Rivian plant — Normal, IL<extra></extra>"), i, 1)
    fig.update_geos(scope="north america", resolution=50, showland=True,
                    landcolor="#f2f2f0", showlakes=False,
                    showsubunits=True, subunitcolor="#c4c4c4", subunitwidth=0.5,
                    showcountries=True, countrycolor="#9e9e9e", countrywidth=0.7)
    fig.update_layout(template="plotly_white", height=380 * n,
                      margin=dict(l=0, r=140, t=30, b=0), **legends)
    return fig


def fig_certainty_by_vin(df):
    """#9 Delivery-estimate certainty for VIN-assigned vs. not, as donut charts
    so the type mix reads as percentages within each group."""
    groups = [("VIN assigned", df[df["vin_present"]]),
              ("No VIN yet", df[~df["vin_present"]])]
    all_types = TYPE_ORDER + ["unknown"]
    tcolor = dict(TYPE_COLOR, unknown="#bbbbbb")
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
                        line=dict(color="#fff", width=1)),
            texttemplate="%{percent}", textposition="inside",
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"), 1, i)
    fig.update_layout(template="plotly_white", height=460,
                      legend_title="Estimate type")
    return fig


def fig_vin_by_config(df):
    """#10 VIN sequence per full configuration (trim · color · wheels).

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
        marker=dict(color=[COLOR_DISPLAY.get(c, "#888888") for c in d["color"]],
                    symbol=[WHEEL_SYMBOL.get(w, "circle") for w in d["wheels_short"]],
                    size=10, line=dict(color="#2b2b2b", width=0.6)),
        customdata=cd, hovertemplate=ht))
    for label, sym in WHEEL_SYMBOL.items():                # wheel-symbol legend
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label,
            marker=dict(color="#999", size=10, symbol=sym,
                        line=dict(color="#2b2b2b", width=0.6))))
    fig.update_layout(
        template="plotly_white", height=max(420, 42 * len(combos) + 180),
        xaxis_title="VIN sequence number  (production order →)",
        yaxis=dict(tickmode="array", tickvals=list(range(len(combos))),
                   ticktext=combos, automargin=True, autorange="reversed"),
        legend_title="Wheels", hovermode="closest")
    return fig
