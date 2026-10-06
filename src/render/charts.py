"""Plotly chart builders for the dashboard (the fig_* functions not yet moved to
presentation-layer components, plus their shared helpers). Pure figure
construction from the cleaned DataFrames.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .colors import COLOR_DISPLAY, REGION_WHISKER
from config import (AS_OF, CADENCE_COLORS, CADENCE_WINDOW_WEEKS, CHART, CHART_UI,
                    COLOR_ORDER, ELEV_BINS, FACTORY,
                    INTERIOR_COLOR, INTERIOR_ORDER, INTERIOR_SHORT, LATENCY_COLORS,
                    REGION_COLOR,
                    STATE_MIN_ORDERS, STATE_TOTALS_COLORS, TEMP_BINS,
                    TIMELINE_COLORS, TYPE_COLOR, TYPE_ORDER,
                    URBAN_BINS, WHEEL_ABBR, WHEEL_COLOR, WHEEL_ORDER, WHEEL_SYMBOL)

from .cadence import rate_history

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


def fig_vin_cadence(df):
    """Build cadence over time: the rolling robust rate behind the projected front.

    Each point is the VINs/day rate as it would have been fitted at the end of that
    week, over the preceding window of front weeks. Shows that cadence is ramping,
    which is why a single rate through all of history understates the current one.
    """
    hist = rate_history(df)
    fig = go.Figure()
    if hist.empty:
        fig.update_layout(template="plotly_white", height=300)
        return fig
    mid = hist.index + pd.Timedelta(days=3)
    fig.add_trace(go.Scatter(
        x=np.asarray(mid), y=np.asarray(hist.values), mode="lines+markers",
        name="VINs per day", showlegend=False,
        line=dict(color=CADENCE_COLORS["front"], width=2.5),
        marker=dict(color=CADENCE_COLORS["front"], size=7,
                    line=dict(color=CHART["edge"], width=0.8)),
        hovertemplate=("Week of %{x|%b %d}: ≈ %{y:.0f} VINs/day"
                       "<extra></extra>")))
    fig.update_layout(
        template="plotly_white", height=300, margin=dict(t=40),
        title=_chart_title("Build cadence (rate over the previous %d weeks of front)"
                           % CADENCE_WINDOW_WEEKS),
        xaxis=dict(title_text="Delivery week", type="date"),
        yaxis=dict(title_text="VINs per day", rangemode="tozero"))
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


def _by_volume(series):
    """_stable_counts as a plain list of categories, for panel bar orders."""
    return list(_stable_counts(series.value_counts()).index)


def _mix_panels(fig, panels, series_col, series, colors, series_label=None,
                line_width=0.5):
    """Fill a subplot stack with 100%-stacked horizontal composition rows.

    `panels` is [(frame, column, ordered_keys)] — one row per entry, in order.
    Each panel carries its own frame, so a panel can restrict the cohort (the
    state row drops thin states) without touching the others. `ordered_keys` is
    used as given and never re-sorted here: some panels order by volume and some
    by value, and only the caller knows which.

    `series_col` is the column holding the stacked category, `series` its stack
    order, and `colors` maps a value to its fill. `series_label` renames a value
    for the legend and hover where the raw value is too long; grouping still keys
    on the raw value. Only the first row contributes legend entries, so a series
    isn't listed once per panel.

    `line_width` is the segment border, drawn in CHART.edge, which the theme flips
    so it always contrasts the surface. Raise it where a fill sits close to one of
    the two chart backgrounds and would otherwise dissolve into it.
    """
    label = series_label or {}
    for row, (sub, col, keys) in enumerate(panels, start=1):
        tot = sub[col].value_counts()
        # "NAME  n=" keeps the sample size beside every bar, so a 100% split off a
        # handful of orders can't be mistaken for a solid trend.
        bars = ["%s  n=%d" % (k, tot[k]) for k in keys]
        for s in series:
            name = label.get(s, s)
            n = [int(((sub[col] == k) & (sub[series_col] == s)).sum())
                 for k in keys]
            pct = [100.0 * v / tot[k] for v, k in zip(n, keys)]
            fig.add_trace(go.Bar(
                x=pct, y=bars, orientation="h", name=name, legendgroup=name,
                showlegend=(row == 1), customdata=np.array(n),
                marker=dict(color=colors.get(s, CHART_UI["muted"]),
                            line=dict(color=CHART["edge"], width=line_width)),
                hovertemplate=("%{y}<br>" + name
                               + ": %{customdata} orders (%{x:.0f}%)<extra></extra>")),
                row, 1)


def _mix_layout(fig, legend_title, height):
    """Shared chrome for the 100%-stacked composition charts: a fixed 0-100 axis
    so panels are visually comparable, and one legend for the whole stack."""
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=True)
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    fig.update_layout(
        template="plotly_white", barmode="stack", bargap=0.28, height=height,
        margin=dict(l=0, r=20, t=52, b=40),
        legend=dict(title=dict(text=legend_title), traceorder="normal",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"],
                    borderwidth=1))


def fig_paint_by_location(df, min_state_orders=STATE_MIN_ORDERS):
    """Paint mix overall, by region, and by the states with enough orders.

    All three panels are 100% stacked, so a region/state's color preference is
    comparable regardless of how many orders it placed. The overall row on top is
    the baseline to read the rest against — whether a region over- or
    under-indexes on a paint. Absolute counts ride along in the hover and as an
    "n=" suffix. Segments use the real paint colors, most-ordered first
    (_paint_order), matching every other paint chart — so the widest segment of the
    baseline row leads, and a region's row is read against it left to right.

    Paint x state is mostly empty and many states have 1-3 orders, where a single
    order swings the mix by 100 points — so the state panel is limited to states
    with at least `min_state_orders`, and the rest stay summarized by region.
    """
    d = _reported(df.dropna(subset=["lat"]), "color").copy()
    counts = d["state"].value_counts()
    states = [s for s in _by_volume(d["state"]) if counts[s] >= min_state_orders]
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

    # Cohort-wide paint order, filtered to what this geo subset actually holds: the
    # ranking stays the page-wide one rather than being re-derived from the mapped
    # rows, so a paint doesn't sit in a different stack position here than in §2/§3.
    colors = [c for c in _paint_order(df) if (d["color"] == c).any()]
    thick = d[d["state"].isin(set(states))]
    regions = _by_volume(d["region"])
    # A constant column lets the overall row reuse the same grouping code path.
    d["_all"] = "All orders"
    _mix_panels(fig, [(d, "_all", ["All orders"]), (d, "region", regions),
                      (thick, "state", states)],
                "color", colors, COLOR_DISPLAY)
    _mix_layout(fig, "Exterior paint", 380 + 24 * len(states))
    return fig


def fig_interior_by_location(df):
    """Interior mix overall and by region.

    Reads like the paint and wheel location panels: each row is 100% stacked so a
    region's mix is comparable regardless of volume, the overall row on top is the
    baseline, and n= sits beside every bar.

    Region only, no per-state row. The non-default cabins are a small share of
    orders, and split by state most rows would hold one or two of them, where a
    single order swings the mix by 100 points — the paint chart hides states under
    five orders for that reason, and interior is thinner still. A state panel is
    worth adding once the newer interiors carry enough volume to survive the split.
    """
    d = _reported(df.dropna(subset=["lat"]), "interior").copy()
    regions = _by_volume(d["region"])
    weights = [1.8, max(len(regions), 1)]
    fig = make_subplots(
        rows=2, cols=1, vertical_spacing=0.12,
        row_heights=[w / sum(weights) for w in weights],
        subplot_titles=("All orders", "By region"))
    if d.empty:
        fig.update_layout(template="plotly_white", height=360)
        return fig

    interiors = [i for i in INTERIOR_ORDER if (d["interior"] == i).any()]
    d["_all"] = "All orders"
    # Heavier border than the other mix charts: these fills are the real cabin
    # colors, so each one nearly matches one of the two chart surfaces.
    _mix_panels(fig, [(d, "_all", ["All orders"]), (d, "region", regions)],
                "interior", interiors, INTERIOR_COLOR, INTERIOR_SHORT,
                line_width=1.3)
    _mix_layout(fig, "Interior", 260 + 30 * (1 + len(regions)))
    return fig


_NO_STATE_DATA = "No state data"


def _numeric_bins(values, edges, unit):
    """Bin a numeric Series into ordered bar labels; NaN becomes _NO_STATE_DATA.

    `unit` is appended verbatim, so it carries its own leading space where one is
    wanted (" ft" -> "< 500 ft", "% urban" -> "< 70% urban"). The top bar reads
    "&ge; X" rather than "X+" so the unit can't land between the number and the sign
    ("\u2265 91% urban", not "91+% urban").

    Returns (labels, ordered_keys). Keys stay in NUMERIC order, never sorted by
    volume: the only question these panels ask is whether the mix shifts as the
    value rises, and reordering the bars by count would destroy that reading.
    Empty bins are dropped, so widening an edge in geo.yaml can't leave a gap.
    """
    def fmt(v):
        # int(): round() of a numpy float can stay a float on older numpy.
        return format(int(round(v)), ",")  # noqa: RUF046

    names = ["< %s%s" % (fmt(edges[0]), unit)]
    names += ["%s–%s%s" % (fmt(lo), fmt(hi), unit)
              for lo, hi in zip(edges, edges[1:])]
    names.append("\u2265 %s%s" % (fmt(edges[-1]), unit))

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
    orders a row holds — regional volumes differ by several times over. The "All
    orders" row on top is the baseline: read a row against it to see which way that
    group leans. Absolute counts ride along in the hover and as an "n=" suffix on
    every label, because a share off a dozen orders and a share off a hundred are
    not the same claim.

    The bottom three panels are ordered by VALUE, not by volume — the question is
    whether the mix shifts as you go higher, colder or more urban, which only reads
    if the bars stay in numeric order.

    All three are per-state averages (geo.yaml), and the dashboard only knows an
    order's state, so each is a weak proxy with its own specific failure. Elevation
    is terrain, not where people live: a California order is charted at that state's
    ~2,900 ft mean whether it came from San Diego or Tahoe, and California is
    consistently the largest single share of the cohort. Percent urban replaced raw
    population density, which mis-sorted exactly the states that matter — Nevada is
    28/sq mi but ~94% urban, so density filed a metro Las Vegas
    order as rural; what percent urban still can't do is tell a dense-city resident
    from a small-town one. Temperature flattens season and altitude together. They
    can suggest a lean; none of them is evidence of one. States with no published
    figures (every Canadian province) get their own bar rather than being dropped
    or guessed at.
    """
    d = _reported(df.dropna(subset=["lat"]), "wheels_short").copy()
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
    regions = _by_volume(d["region"])
    d["_elev"], elev_keys = _numeric_bins(d["elev_ft"], ELEV_BINS, " ft")
    d["_temp"], temp_keys = _numeric_bins(d["temp_f"], TEMP_BINS, " °F")
    d["_urban"], urban_keys = _numeric_bins(d["urban_pct"], URBAN_BINS,
                                            "% urban")

    panels = [("_all", ["All orders"]), ("region", regions),
              ("_elev", elev_keys), ("_temp", temp_keys),
              ("_urban", urban_keys)]
    # Give each row roughly the height its bar count needs, so no panel looks
    # stretched or crushed; the single-bar top row still needs room for its title.
    weights = [1.8] + [len(keys) for _, keys in panels[1:]]
    fig = make_subplots(
        rows=len(panels), cols=1, vertical_spacing=0.055,
        row_heights=[w / sum(weights) for w in weights],
        subplot_titles=("All orders", "By region",
                        "By mean terrain elevation of the order's state",
                        "By average annual temperature of the order's state",
                        "By the urban share of the order's state population"))

    bars = sum(len(keys) for _, keys in panels)
    _mix_panels(fig, [(d, col, keys) for col, keys in panels],
                "wheels_short", wheels, WHEEL_COLOR)
    _mix_layout(fig, "Wheels", 300 + 30 * bars)
    return fig


def _chart_title(text):
    """Layout title for a chart that shares a section with others, so each plot
    keeps its own heading. No explicit font color — it inherits layout.font, which
    THEME_JS re-tints, so the title follows the light/dark toggle."""
    return dict(text=text, x=0, xanchor="left", y=0.99, yanchor="top",
                font=dict(size=14))


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
                               marker_color=TIMELINE_COLORS["ordered"],
                               showlegend=False,
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


# The delivery pipeline's three stages, in stacking order, for the §13 state
# totals chart. The summary readouts and take-rate bars use the four stages of
# aggregates.stages() instead; Delivered agrees, and §13 moves onto stages() when
# it becomes a component (#109).
DELIVERY_STAGES = ("Delivered (est.)", "Awaiting delivery · VIN",
                   "Awaiting delivery · no VIN")


def delivery_progress(df):
    """Split orders into the three delivery-pipeline stages, as boolean masks.

    A strict partition: every order lands in exactly one stage, so counts always
    sum to len(df). "Delivered" is subtracted from whichever VIN bucket it came
    from, and deliveries are counted whether or not a VIN is known — someone may
    post about taking delivery without ever updating (or while obfuscating) their
    VIN, and dropping those would undercount. Delivery is INFERRED from a passed
    estimate, not reported; see the §12 description for what that does and doesn't
    support.

    Returns {stage name: mask} in DELIVERY_STAGES order.
    """
    delivered = (df["delivered_inferred"].astype(bool)
                 if "delivered_inferred" in df.columns
                 else pd.Series(False, index=df.index))
    vin = df["vin_present"].astype(bool)
    return dict(zip(DELIVERY_STAGES,
                    (delivered, vin & ~delivered, ~vin & ~delivered)))


def fig_state_totals(df):
    """Per-state order counts as a delivery pipeline, under an all-orders total.

    Every state that has ordered, sorted by total. Three segments stack to the
    state's full order count, so the bar length is the state total while the split
    shows how far along that state is: assumed delivered, then still awaiting
    delivery with a VIN known, then no VIN yet. Complements the maps above, where
    the long tail of one- and two-order states is hard to compare by bubble area.

    The top row is the same split summed over every state, on its OWN axis: at the
    shared scale it would be several times the width of the largest state and
    squash every other bar into the left edge. It carries each stage's count and
    share as text, since that row exists to be read rather than compared.
    """
    d = df.dropna(subset=["lat"])
    if d.empty:
        fig = go.Figure()
        fig.update_layout(template="plotly_white", height=420)
        return fig
    tot = _stable_counts(d.groupby("state").size())
    stages = delivery_progress(d)
    colors = dict(zip(DELIVERY_STAGES, (STATE_TOTALS_COLORS["delivered"],
                                        STATE_TOTALS_COLORS["vin"],
                                        STATE_TOTALS_COLORS["no_vin"])))

    per_state_px = 18
    states_px = max(386, per_state_px * len(tot))
    total_px, gap_px = 52, 22
    plot_px = total_px + gap_px + states_px
    # A visible gap, so the total reads as a summary rather than as the first state.
    fig = make_subplots(rows=2, cols=1, vertical_spacing=gap_px / plot_px,
                        row_heights=[total_px / plot_px, states_px / plot_px])

    n = len(d)
    for name in DELIVERY_STAGES:
        count = int(stages[name].sum())
        fig.add_trace(go.Bar(
            x=[count], y=["All states"], orientation="h", name=name,
            legendgroup=name, showlegend=False,
            marker=dict(color=colors[name], line=dict(color=CHART["edge"], width=0.5)),
            text=["%d · %.0f%%" % (count, 100.0 * count / n)] if count else [""],
            textposition="inside", insidetextanchor="middle",
            textfont=dict(size=11),
            hovertemplate="All states — %s: %%{x} (%.0f%%)<extra></extra>"
                          % (name, 100.0 * count / n)), 1, 1)

    states = np.asarray(tot.index)
    for name in DELIVERY_STAGES:
        vals = (d[stages[name]].groupby("state").size()
                .reindex(tot.index, fill_value=0))
        fig.add_trace(go.Bar(
            x=np.asarray(vals.values), y=states, orientation="h", name=name,
            legendgroup=name,
            marker=dict(color=colors[name], line=dict(color=CHART["edge"], width=0.5)),
            hovertemplate="%%{y} — %s: %%{x}<extra></extra>" % name), 2, 1)
    # Total at the end of each stacked bar (an invisible bar carrying the label).
    fig.add_trace(go.Bar(
        x=np.zeros(len(states)), y=states, orientation="h", showlegend=False,
        marker=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        text=np.asarray(tot.values), textposition="outside", cliponaxis=False,
        textfont=dict(size=10)), 2, 1)

    fig.update_layout(
        template="plotly_white", barmode="stack", bargap=0.25,
        height=34 + plot_px + 40,
        # t=34 leaves room for the 22px modebar to sit in the margin instead of
        # over the longest bar. Every other chart on the page already has 30-100px
        # here (mostly Plotly's default), so this one was the outlier at t=10 —
        # matching them keeps the toolbar horizontal everywhere.
        margin=dict(l=0, r=30, t=34, b=40),
        # Floated into the bottom-right of the plot rather than sitting above it:
        # the top-right is where Plotly puts its modebar, which covered the legend.
        # Bars are sorted ascending, so the smallest states leave that corner
        # empty. traceorder="normal" makes the legend read top-down in the same
        # pipeline order the bars stack (it reverses by default).
        legend=dict(title=dict(text="Status"), traceorder="normal",
                    x=0.98, xanchor="right", y=0.02, yanchor="bottom",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"],
                    borderwidth=1))
    # The total row's own axis: full width = every order, no ticks needed since
    # each segment states its count.
    fig.update_xaxes(range=[0, n], showticklabels=False, showgrid=False,
                     zeroline=False, row=1, col=1)
    fig.update_xaxes(title="Orders", rangemode="tozero",
                     range=[0, float(tot.max()) * 1.08], row=2, col=1)
    fig.update_yaxes(ticksuffix="  ", automargin=True)
    return fig


# A weekly median is only drawn for weeks with at least this many firm dates; below
# it, one fast or slow delivery would swing the line by weeks.
_LATENCY_MIN_WEEK_N = 3


def latency_frame(df):
    """Orders whose wait from order to delivery can be measured, with `days`.

    Firm ("explicit") delivery dates only: a range or window is a guess at when the
    car will come, so its midpoint would plot a precision the data doesn't have.
    An estimate that contradicts the order date never gets here: cleaning sets it
    aside as unknown and lists it (ingest/outliers.py).
    """
    d = df[(df["delivery_type"] == "explicit") & df["order_date"].notna()
           & df["delivery_est"].notna()].copy()
    d["days"] = (d["delivery_est"] - d["order_date"]).dt.days
    # Monday-start week the order was placed in, for the median and coverage.
    d["order_week"] = d["order_date"].dt.to_period("W-SUN").dt.start_time
    return d


def fig_delivery_latency(df):
    """Days from order to firm delivery date, by order date, with the weekly median
    and how much of each week's cohort is visible at all.

    Y is the WAIT in days rather than the delivery date: days stay on one scale, so
    a trend reads as a slope, where a delivery-date axis climbs up and to the right
    regardless and hides it. Filled markers are dates that have passed (presumed
    delivered); open ones are scheduled in the future.

    The bottom panel is the point of the chart as much as the top one. A firm date
    only appears once a delivery is close, so the most recent order weeks are
    represented mainly by their FAST deliveries — their slow orders haven't been
    scheduled yet. The weekly median therefore drifts down toward the present partly
    as an artifact. Showing the share of each week's orders that appear above makes
    that visible instead of leaving it to be mistaken for a trend.
    """
    d = latency_frame(df)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        row_heights=[0.74, 0.26])
    if d.empty:
        fig.update_layout(template="plotly_white", height=560)
        return fig

    passed = d["delivery_est"] <= AS_OF
    # An open symbol is drawn as an outline in marker.color at the marker's opacity,
    # so the translucency that keeps the filled points from clumping made the open
    # ones (and their legend icon) all but vanish on the dark card. They get a full-
    # opacity, heavier outline instead; they are few, so overlap isn't a concern.
    styles = (("Delivery date passed", passed,
               dict(symbol="circle", opacity=0.65,
                    line=dict(color=CHART["edge"], width=0.6))),
              ("Scheduled (future date)", ~passed,
               dict(symbol="circle-open", opacity=1.0, line=dict(width=1.8))))
    for label, mask, style in styles:
        sub = d[mask]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=np.asarray(sub["order_date"]), y=np.asarray(sub["days"]), mode="markers",
            name=label, legendgroup=label,
            marker=dict(color=LATENCY_COLORS["order"], size=8, **style),
            customdata=np.column_stack(
                [sub["user"], sub["delivery_est"].dt.strftime("%b %d, %Y")]),
            hovertemplate=("%{customdata[0]}<br>ordered %{x|%b %d, %Y}"
                           "<br>delivery %{customdata[1]}<br>%{y} days"
                           "<extra></extra>")),
            1, 1)

    weeks = d.groupby("order_week")["days"].agg(["median", "count"])
    weeks = weeks[weeks["count"] >= _LATENCY_MIN_WEEK_N]
    if not weeks.empty:
        # Plotted at mid-week so the line sits among the points it summarizes.
        mid = weeks.index + pd.Timedelta(days=3)
        fig.add_trace(go.Scatter(
            x=np.asarray(mid), y=np.asarray(weeks["median"]), mode="lines+markers",
            name="Weekly median (%d+ orders)" % _LATENCY_MIN_WEEK_N,
            line=dict(color=LATENCY_COLORS["median"], width=2.5),
            marker=dict(color=LATENCY_COLORS["median"], size=7,
                        line=dict(color=CHART["edge"], width=0.6)),
            customdata=np.column_stack([weeks.index.strftime("%b %d"), weeks["count"]]),
            hovertemplate=("Week of %{customdata[0]}: median %{y:.0f} days"
                           "<br>%{customdata[1]} orders<extra></extra>")), 1, 1)

    # Coverage: of all orders placed each week, how many appear in the top panel.
    placed = df[df["order_date"].notna()].copy()
    placed["order_week"] = placed["order_date"].dt.to_period("W-SUN").dt.start_time
    denom = placed.groupby("order_week").size()
    numer = d.groupby("order_week").size().reindex(denom.index, fill_value=0)
    share = 100.0 * numer / denom
    fig.add_trace(go.Bar(
        x=np.asarray(denom.index + pd.Timedelta(days=3)), y=np.asarray(share),
        name="Orders with a firm date", showlegend=False,
        marker=dict(color=LATENCY_COLORS["coverage"],
                    line=dict(color=CHART["edge"], width=0.5)),
        customdata=np.column_stack([denom.index.strftime("%b %d"), numer, denom]),
        hovertemplate=("Week of %{customdata[0]}: %{customdata[1]} of %{customdata[2]} "
                       "orders have a firm date (%{y:.0f}%)<extra></extra>")), 2, 1)

    fig.update_yaxes(title_text="Days from order to delivery", rangemode="tozero",
                     row=1, col=1)
    fig.update_yaxes(title_text="With a firm date", range=[0, 100], ticksuffix="%",
                     row=2, col=1)
    fig.update_xaxes(title_text="R2 order date", type="date", row=2, col=1)
    fig.update_layout(
        template="plotly_white", height=620, hovermode="closest", bargap=0.15,
        margin=dict(t=40),
        legend=dict(orientation="h", x=0, y=1.06, xanchor="left", yanchor="bottom",
                    bgcolor=CHART["legbg"], bordercolor=CHART["legbd"], borderwidth=1))
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
