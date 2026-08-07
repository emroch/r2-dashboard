"""Dashboard assembly: the section registry, template loading, HTML helpers,
and the build_dashboard entry point that renders every chart into one HTML file.

The page's static assets live as real files under templates/ — page.html (a
valid, standalone HTML shell with id'd slots) plus styles.css and the
head/theme/nav scripts. build_dashboard parses the shell with BeautifulSoup and
populates it by element id (theme vars, stat cards, nav links, chart sections),
then splices Plotly's fragments into their <!--PLOT:n--> placeholders verbatim.
"""
import json
import os
import pandas as pd
from pathlib import Path
from textwrap import dedent
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from plotly.offline import get_plotlyjs

from .charts import (fig_certainty_by_vin, fig_color_wheel_heatmap,
                     fig_config_dashboard, fig_delivery_timeline,
                     fig_delivery_vs_vin, fig_dest_vs_delivery, fig_geo,
                     fig_order_timeline, fig_paint_by_location,
                     fig_price_by_trim, fig_price_distribution,
                     fig_price_options, fig_state_totals, fig_vin_by_config,
                     fig_vin_vs_order)
from config import CHART_CHROME, COLOR_HEX, DASHBOARD, THEME_CSS, AS_OF

# templates/ sits alongside this render/ package, under the src/ root.
_TPL_DIR = Path(__file__).resolve().parents[1] / "templates"

# Where the "Report issue" button points. The repo is the tracker of record for
# dashboard problems; corrections to a person's own order belong in the source
# sheet instead, which the issue form says up front.
ISSUE_FORM_URL = "https://github.com/emroch/r2-dashboard/issues/new"


def _tpl(name):
    """Read a template file (CSS/JS/HTML shell) from templates/."""
    return (_TPL_DIR / name).read_text(encoding="utf-8")


# Display order = list order. Section numbers (chart titles + sidebar links) are
# assigned from position at render time, so reordering this list is all it takes;
# grouped here as build -> timing -> production/VIN -> geography.
SECTIONS = [
    ("Configuration take-rates",
     dedent("""What this cohort ordered. (Trim, Launch Package, Autonomy+ and Tow are ~100% uniform across the cohort,
               so they are omitted here.)"""),
     fig_config_dashboard),
    ("Color × wheels combinations",
     dedent("""Most common full builds — the combos that would form the clusters in the delivery-vs-VIN chart."""),
     fig_color_wheel_heatmap),
    ("Configured price",
     dedent("""What this cohort is paying, from published trim and option prices — the configured vehicle only, with no
               destination, doc fees, taxes, or incentives. The top panel gives one bar per exact price (the cohort lands
               on a small set of totals, so binning would hide real structure), with the median's own label highlighted
               and the mean shown as a stat. The middle panel covers the option spend alone — the base is a constant per
               trim, so the choices are the interesting part — with each category's take rate alongside, since a big
               average means something different when everyone pays a little rather than a few paying a lot. The bottom
               panel is a box per trim, and fills in as Premium and Standard ship. Orders whose configuration hits a
               price Rivian hasn't published are excluded rather than counted as zero — see the data-quality panel."""),
     (fig_price_distribution, fig_price_options, fig_price_by_trim)),
    ("Reservation & order timeline",
     dedent("""The top panel stacks reservation-only holders (incomplete orders, from the separate reservations sheet)
               above those who have since locked an order. The 3/7/2024 reveal week is ~20x the next-biggest week, so
               the y-axis is clipped just above the tail to keep the 2-year trickle readable. The bottom shows when
               orders were finalized."""),
     fig_order_timeline),
    ("Estimated delivery timeline",
     dedent("""When the cohort expects delivery, stacked by how firm the estimate is."""),
     fig_delivery_timeline),
    ("Estimate certainty vs. VIN status",
     dedent("""Share of orders with known delivery dates."""),
     fig_certainty_by_vin),
    ("VIN sequence vs. order date",
     dedent("""Does ordering earlier win a lower (earlier-built) VIN? Slope/scatter shows how tightly production
               sequence tracks order timing. Click a config in the legend to hide it, or double-click to isolate
               one."""),
     fig_vin_vs_order),
    ("Delivery date vs. VIN sequence",
     dedent("""Each point is an order with both a VIN and a delivery estimate. Color = paint, marker shape = wheels;
               whiskers span the quoted delivery window. Clusters of one color across a VIN range hint at same-config
               cars built in sequence. Click a config in the legend to hide it, or double-click to isolate one."""),
     fig_delivery_vs_vin),
    ("VIN sequence by configuration",
     dedent("""Each VIN-assigned order at its production sequence (x), grouped into rows by full configuration (trim ·
               color · wheels); marker fill = paint, shape = wheels. Clusters along a row suggest same-config cars were
               built in a batch."""),
     fig_vin_by_config),
    ("Geographic demand",
     dedent("""Three stacked maps of demand around the Normal, IL plant: orders with an assigned VIN, all orders, and
               total demand (orders + incomplete reservations). Bubble area = count; the first two share a scale, while
               total demand (~20x larger) scales to its own. The bars beside each map give that panel's per-region
               total."""),
     fig_geo),
    ("Orders by state",
     dedent("""Every state that has ordered, sorted by total, as a delivery pipeline: assumed delivered, then awaiting
               delivery with a VIN known, then no VIN yet. The three stack to the state's full count, so bar length is
               the state total. Deliveries are <em>inferred</em>, not reported — an order whose whole delivery estimate
               has passed is assumed to have arrived, on the theory that people rarely come back to update the sheet
               afterwards. That is rough and errs both ways: a delayed car still looks delivered, and one that arrived
               early against a vague estimate does not. Any estimate with a known end date counts, including a relative
               window that finished a while ago; orders with no estimate never do. Deliveries count whether or not a VIN
               is known, since some people post about taking delivery without ever updating their VIN."""),
     fig_state_totals),
    ("Paint preference by location",
     dedent("""Does color taste vary geographically? All three panels are 100% stacked, so each row's paint mix is
               comparable regardless of order volume — the West has ~70x Canada's. The overall row on top is the
               baseline: read a region against it to see which paints it over- or under-indexes on. Bar labels carry the
               sample size (n=), and hover gives the underlying counts. The state panel is limited to states with enough
               orders to be meaningful; below that a single order swings the mix by 100 points, so the rest stay
               summarized in the region panel."""),
     fig_paint_by_location),
    ("Destination vs. delivery date",
     dedent("""States ordered by distance from the Normal, IL plant (closest at bottom). An upward-right tilt would mean
               farther destinations deliver later. Whiskers span each order's quoted delivery window. Click a region in
               the legend to hide it, or double-click to isolate one."""),
     fig_dest_vs_delivery),
]

def _css_block(sel, vars_):
    """One CSS rule of `--name:value;` custom properties from a {name: value} map."""
    return "%s{%s}" % (sel, "".join("--%s:%s;" % (k, v) for k, v in vars_.items()))


# :root carries the light theme plus the theme-independent `fixed` chrome (the
# always-green header/sidebar/disclaimer); the dark block overrides only what
# changes. Every value lives in theme.yaml — see config.THEME_CSS.
_THEME_VARS_CSS = "\n%s\n%s\n" % (
    _css_block(":root", dict(THEME_CSS["light"], **THEME_CSS["fixed"])),
    _css_block('html[data-theme="dark"]', THEME_CSS["dark"]))

# Runs in <head> before first paint: set the theme (saved > OS preference) so
# the page chrome never flashes the wrong colors.
HEAD_JS = _tpl("head.js")

# The light/dark chart-chrome objects come from theme.yaml (config.CHART_CHROME),
# injected into the script below so THEME_JS and the baked-in chart colors agree.
_CHROME_JS = "var LIGHT=%s;var DARK=%s;" % (
    json.dumps(CHART_CHROME["light"], separators=(",", ":")),
    json.dumps(CHART_CHROME["dark"], separators=(",", ":")))

# Runs at end of <body>: wire the toggle and re-theme the (already-rendered)
# Plotly charts. Data-encoding colors (markers/bars/paints) are left untouched;
# only chart chrome — text, gridlines, geo land/borders, legend boxes, and the
# transparent backgrounds that let the themed card show through — is swapped.
THEME_JS = _tpl("theme.js").replace("/*__CHROME_JS__*/", _CHROME_JS)

# Chart-navigation sidebar: hamburger toggle (narrow screens) + scroll-spy that
# highlights the section currently in view via IntersectionObserver.
NAV_JS = _tpl("nav.js")

# Plotly toolbar, applied to every figure. Box- and lasso-select mark points for
# a selection this dashboard never reads, so they only add width to a bar that
# has to fit in a chart's top margin; dropping them takes it from 272px to 200px.
# The logo goes too — it links off-site and earns none of that space. Zoom, pan
# and reset stay, since they're the ones worth having on the denser charts.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}

# Arbitrates the scroll wheel between zooming a map and scrolling the page
# (see scrollzoom.js). Separate from nav.js so the scroll-spy and the wheel
# arbitration stay independently readable.
ZOOM_JS = _tpl("scrollzoom.js")


def _report_url(report):
    """The "Report issue" button's target: the repo's dashboard-report issue form
    with the build it was opened from prefilled.

    Reports about a static page are hard to act on without knowing which build
    the reader saw, and nobody pastes that by hand — so the button carries it.
    The query key is the form field's `id`; GitHub silently ignores one that
    doesn't match, hence the note in dashboard-report.yml.
    """
    parts = ["dashboard built %s" % AS_OF.date(),
             "orders sheet %s" % _stamp(report["orders_meta"]["updated_at"]),
             "reservations sheet %s" % _stamp(report["resv_meta"]["updated_at"])]
    # Actions sets GITHUB_SHA on every run, which pins the exact deployed build;
    # a local render just omits it.
    sha = os.environ.get("GITHUB_SHA", "")
    if sha:
        parts.append("commit %s" % sha[:8])
    return "%s?%s" % (ISSUE_FORM_URL,
                      urlencode({"template": "dashboard-report.yml",
                                 "build": ", ".join(parts)}))


def _stamp(dt):
    """A timestamp for the report prefill — plain text, not a <time> element."""
    return dt.strftime("%Y-%m-%d %H:%M") if dt is not None else "unknown"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _stat_card(label, value, rows=None, caption="", cap=60):
    """A header stat card; with `rows` it gains a hover tooltip listing the
    affected entries (original #, username, what changed). Long lists are
    truncated to `cap` rows with a '… and N more' footer."""
    if not rows:
        return '<div class="stat"><b>%s</b>%s</div>' % (_esc(value), _esc(label))
    body = "".join("<tr><td>#%s</td><td>%s</td><td>%s</td></tr>"
                   % (_esc(i), _esc(u), _esc(d)) for i, u, d in rows[:cap])
    if len(rows) > cap:
        body += ('<tr><td></td><td></td><td>&hellip; and %d more</td></tr>'
                 % (len(rows) - cap))
    tip = ('<div class="tip"><div class="tipcap">%s</div><table>'
           "<tr><th>#</th><th>user</th><th>detail</th></tr>%s</table></div>"
           % (_esc(caption), body))
    return ('<div class="stat has-tip"><b>%s</b>%s<span class="i">&#9432;</span>%s</div>'
            % (_esc(value), _esc(label), tip))


def _money(v):
    """Whole-dollar money for the stat cards; em dash when there's nothing to show."""
    return "—" if v is None else "$%s" % format(round(v), ",")


def _fmt_time(dt):
    """Render a timestamp as a <time> carrying the absolute instant (ISO 8601 with
    offset) so client JS can localize it to the viewer's timezone; the server text
    is the build-timezone fallback shown when JS is off."""
    if dt is None:
        return "—"
    aware = dt.astimezone()  # naive build-local datetime -> attach local offset
    return ('<time datetime="%s" data-r2time>%s</time>'
            % (aware.isoformat(timespec="minutes"),
               aware.strftime("%Y-%m-%d %H:%M %Z")))


def _src_line(name, meta, extra):
    """One header line: linked sheet name, count, fetched + last-updated times
    (viewer-localized via <time>), and the offline badge."""
    live = ("" if meta["live"]
            else ' <span class="warn">(offline — showing cached copy)</span>')
    return ('<p class="src"><a href="%s" target="_blank" rel="noopener">%s</a> — %s '
            '<span class="dim">·</span> fetched %s%s '
            '<span class="dim">·</span> last updated %s</p>'
            % (meta["view_url"], _esc(name), _esc(extra),
               _fmt_time(meta["fetched_at"]), live, _fmt_time(meta["updated_at"])))


# Data-quality categories: (report["quality"] key, heading, one-line note).
_QA_CATS = [
    ("schema_notices", "Unmapped source columns",
     "Columns a source sheet has that nothing here reads. The sheets are "
     "hand-maintained forms, so their columns are located by name and only the "
     "ones listed in the schema are read at all — reordering a sheet, or adding "
     "a question to the form, changes nothing. What is checked on every run is "
     "that each column the schema names is present exactly once: a renamed, "
     "removed, or duplicated one stops the build outright, since it would "
     "otherwise read as empty for every row and quietly skew every figure. A new "
     "column can't do any harm, so it is only listed here — nothing is charted "
     "from it until the schema maps it."),
    ("unparseable", "Unparseable delivery estimates",
     "Non-empty delivery text that didn't normalize to a date, range, or window."),
    ("fuzzy_dups", "Possible duplicate usernames",
     "Usernames that normalize alike (case/space/punctuation) but weren't merged "
     "by the exact-duplicate dedup."),
    ("vin_unrec", "Unrecoverable VINs",
     "VIN tokens too redacted to recover a sequence number."),
    ("bad_dates", "Invalid dates dropped",
     "Order/reservation dates outside the plausible window, cleared."),
    ("availability_drops", "Premature-config orders dropped",
     "Orders whose selected trim, paint, or interior wasn't orderable yet on the "
     "order date — removed entirely, not counted as orders."),
    ("price_issues", "Configuration pricing issues",
     "Options the sheet reports that aren't offered on that order's trim, or that "
     "have no published price. Flagged for review, not corrected: the order keeps "
     "a best-effort price unless a price is genuinely unknown."),
    ("answer_conflicts", "Contradictory answers (reconciled)",
     "Rows where two fields can't both be right, shown with the reading that was "
     "assumed. Autonomy+ / Tow lose to the Launch Package column, which is "
     "authoritative — a Launch order answering “No” still gets the bundled "
     "option, and a non-Launch “Included” is read as added separately. A “not an "
     "R1 owner” answer loses to a specific R1 model, since naming one is concrete "
     "information a non-owner has no reason to give. “Yes” and “Included” mean the "
     "same thing, so that wording difference is not listed. A confirmed case "
     "should get an overrides.yaml entry rather than relying on these."),
    ("override_issues", "Override issues",
     "Manual fix-ups or additions in overrides.yaml that referenced an unknown "
     "field, a username with no matching order, or an addition already in the "
     "sheet."),
]

# Categories whose middle column names something other than a user (the table
# markup is shared across every category).
_QA_MID = {"schema_notices": "sheet"}


def _qa_id(num):
    """A flagged row's sheet number, as "#12". Some entries have no number — a
    whole-sheet notice, or an overrides.yaml key matching no row — and the
    loaders mark those "—", which shouldn't come out as "#—"."""
    text = _esc(num)
    return text if text == "—" else "#" + text


def _quality_section(quality, num, cap=40):
    """The data-quality / anomaly panel: things flagged for human review rather
    than auto-corrected. Each category lists the affected (#, user, detail)."""
    blocks = []
    for key, name, note in _QA_CATS:
        rows = quality.get(key, [])
        if rows:
            body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                           % (_qa_id(i), _esc(u), _esc(d)) for i, u, d in rows[:cap])
            if len(rows) > cap:
                body += ('<tr><td></td><td></td><td>&hellip; and %d more</td></tr>'
                         % (len(rows) - cap))
            content = ('<table><tr><th>#</th><th>%s</th><th>detail</th></tr>'
                       '%s</table>' % (_QA_MID.get(key, "user"), body))
        else:
            content = '<p class="qa-none">None &#10003;</p>'
        blocks.append('<div class="qa-cat"><h3>%s<span class="qa-n">%d</span></h3>'
                      '<p class="qa-note">%s</p>%s</div>'
                      % (_esc(name), len(rows), _esc(note), content))
    conv = quality.get("conversions", [])
    conv_body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                        % (_esc(r), _esc(t), _esc(anc), _esc(res))
                        for r, t, res, anc in conv)
    conv_html = (
        '<div class="qa-conv"><h3>Delivery date parsing'
        '<span class="qa-n">%d</span></h3>'
        '<p class="qa-note">Every distinct delivery string that parsed, and the '
        'date or range it became — for sanity-checking the normalization. Window '
        'estimates are relative, so the anchor they were measured from (the order '
        'date, or the as-of date as a fallback) is shown.</p>'
        '<table><tr><th>raw</th><th>type</th><th>anchor</th><th>parsed</th></tr>'
        '%s</table></div>'
        % (len(conv), conv_body))
    return ('<section id="sec-%d"><h2>%d · Data quality &amp; anomalies</h2>'
            '<p class="desc">Rows flagged for human review — surfaced here, not '
            'auto-corrected. An empty category means nothing tripped that '
            'check.</p><div class="qa">%s</div>%s</section>'
            % (num, num, "".join(blocks), conv_html))


def build_dashboard(df, report, resv):
    # Each chart section wraps one <!--PLOT:n--> comment placeholder per figure;
    # the Plotly fragments are spliced in verbatim after the DOM is serialized
    # (never re-parsed). Plotly.js is emitted as a separate plotly.min.js (not
    # inlined) so browsers cache it — see the first figure below + the write at
    # the end. Numbering (DOM order): summary card is 1, charts 2..N+1, QA N+2.
    #
    # A section's builder may be a TUPLE of builders, which renders as several
    # separate plots under one heading. Separate figures (rather than subplot rows
    # of one figure) give each chart its own zoom/pan and modebar, so panning one
    # doesn't drag the others, and let CSS space them apart.
    plots, sections = {}, []
    pid = 0
    for i, (title, desc, builder) in enumerate(SECTIONS):
        builders = builder if isinstance(builder, tuple) else (builder,)
        frags = []
        for b in builders:
            fig = (b(df, resv) if b in (fig_geo, fig_order_timeline) else b(df))
            # Transparent backgrounds let the themed section card show through, so
            # the charts adapt to light/dark (chrome is re-tinted by THEME_JS).
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)")
            pid += 1
            # The first figure on the page references an external plotly.min.js
            # (written next to the page below) instead of inlining ~5 MB; the rest
            # reuse window.Plotly.
            plots[pid] = fig.to_html(
                full_html=False,
                include_plotlyjs=("directory" if pid == 1 else False),
                default_width="100%", config=PLOTLY_CONFIG)
            frags.append('<div class="plot"><!--PLOT:%d--></div>' % pid)
        n = i + 2
        sections.append(
            '<section id="sec-%d"><h2>%d · %s</h2><p class="desc">%s</p>'
            '%s</section>' % (n, n, _esc(title), desc, "".join(frags)))
    sections.append(_quality_section(report["quality"], len(SECTIONS) + 2))

    dc = report["delivery_counts"]
    firm = dc.get("explicit", 0)
    rangewin = dc.get("window", 0) + dc.get("range", 0) + dc.get("month", 0)
    unparseable = report["quality"]["unparseable"]
    # unknown = "no date given" (missing/placeholder) + unparseable; split them.
    no_date = dc.get("unknown", 0) - len(unparseable)
    san = report["sanitized"]
    pz = report["price"]
    rr, om, rm = report["resv"], report["orders_meta"], report["resv_meta"]
    captions = {
        "Order duplicates": "Rows removed as duplicates in the orders sheet",
        "Reservation duplicates": "Repeat usernames in the reservations sheet (kept first)",
        "Reservations already ordered": "Reservation-holders already counted in the orders sheet",
        "VINs de-obfuscated": "Obfuscated VINs recovered (original → value)",
        "VINs recovered": "VINs that could not be recovered (dropped)",
        "Invalid dates dropped": "Order/reservation dates cleared as out-of-range (original → dropped)",
        "Premature configs dropped": "Orders for a trim/paint/interior not yet orderable on the order date (row removed)",
        "Unparseable": "Non-empty delivery text that didn't parse to a date/range",
        "Unpriced": "Orders whose configuration hit a price that isn't published yet (excluded from the price stats)",
        "Manual fix-ups": "Fields set or corrected via overrides.yaml (field: old → new)",
        "Manual additions": "Forum-only orders appended via overrides.yaml (not in the sheet)",
    }
    stat_groups = [
        ("Cohort", [
            ("Unique orders", report["n_dedup"], None),
            ("Manual additions", report["n_added"], san["Manual additions"]),
            ("Incomplete reservations", rr["n_incomplete"], None),
            ("Total demand", report["n_dedup"] + rr["n_incomplete"], None),
        ]),
        ("Cleaned / removed", [
            ("Order duplicates", len(san["Duplicates removed"]),
             san["Duplicates removed"]),
            ("Reservation duplicates", rr["n_self_dupes"], rr["self_dupe_records"]),
            ("Reservations already ordered", rr["n_matched"], rr["matched_records"]),
            ("Invalid dates dropped", report["bad_order"] + report["bad_resv"],
             san["Invalid dates dropped"]),
            ("Premature configs dropped", report["n_premature"],
             san["Premature configs dropped"]),
            ("Manual fix-ups", len(san["Manual fix-ups"]), san["Manual fix-ups"]),
        ]),
        ("VIN recovery", [
            ("VINs recovered", report["vin_present"], san["VINs recovered"]),
            ("VINs de-obfuscated", report["vin_obfuscated"], san["VINs de-obfuscated"]),
        ]),
        # Partitions all orders: firm + range/window + no date + unparseable = total.
        ("Delivery estimate (of %d orders)" % report["n_dedup"], [
            ("Firm date", firm, None),
            ("Range / window", rangewin, None),
            ("No date given", no_date, None),
            ("Unparseable", len(unparseable), unparseable),
        ]),
        # Configured vehicle price (no destination/doc/taxes). "Unpriced" keeps the
        # mean/median honest by showing what they were NOT computed over.
        ("Configured price (of %d priced)" % pz["n_priced"], [
            ("Mean", _money(pz["mean"]), None),
            ("Median", _money(pz["median"]), None),
            ("Range", "%s–%s" % (_money(pz["min"]), _money(pz["max"])), None),
            ("Unpriced", pz["n_unpriced"], report["quality"]["price_issues"]),
        ]),
    ]
    stat_html = "".join(
        '<div class="statgroup"><span class="sglabel">%s</span>'
        '<div class="stats">%s</div></div>'
        % (_esc(gtitle), "".join(_stat_card(k, v, rows, captions.get(k, ""))
                                 for k, v, rows in cards))
        for gtitle, cards in stat_groups)

    intro_html = (
        '<h2>1 · Sources &amp; summary</h2>'
        + _src_line("Orders & Deliveries sheet", om,
                    "%d unique orders" % report["n_dedup"])
        + _src_line("Reservations sheet", rm,
                    "%d incomplete reservations (of %d rows)"
                    % (rr["n_incomplete"], rr["n_raw"]))
        + '<p class="src"><a href="https://www.rivianforums.com/forum/forums/r2-forum.8/"'
          ' target="_blank" rel="noopener">Rivian R2 forum</a> — the community these'
          ' owner/reservation trackers are compiled from</p>'
        + '<p class="meth">Delivery windows are measured from each customer&#8217;s '
          'R2 order date. Order dates before 2026-06-09 and reservations before '
          '2024-03-07 are treated as invalid; reservations already present in the '
          'orders sheet are dropped as duplicates. &#8220;Last updated&#8221; is '
          'when a sheet&#8217;s contents last changed between fetches. Hover the '
          'highlighted stat cards (&#9432;) for the sanitized entries. Charts with '
          'a legend are interactive &mdash; click an entry to hide that series, '
          'double-click to isolate one; see each chart&#8217;s note for its '
          'paint, region, and wheel filters.</p>')

    # Chart-navigation sidebar: the summary card (1), each chart (2..N+1), and
    # the QA panel (N+2), numbered by position to match the section headings.
    nav_items = [("sec-1", "1 · Sources & summary")]
    nav_items += [("sec-%d" % (i + 2), "%d · %s" % (i + 2, t))
                  for i, (t, _, _) in enumerate(SECTIONS)]
    qa_num = len(SECTIONS) + 2
    nav_items.append(("sec-%d" % qa_num, "%d · Data quality & anomalies" % qa_num))
    nav_links = "".join('<a href="#%s" data-sec="%s">%s</a>' % (sid, sid, _esc(t))
                        for sid, t in nav_items)
    # Header/sidebar chrome takes its greens from the palette (a nod to the
    # Rivian paints): Forest Green for the header, Launch Green for the sidebar.
    chrome_css = ":root{--header-bg:%s;--side-bg:%s;}" % (
        COLOR_HEX.get("Forest Green", "#226222"),
        COLOR_HEX.get("Launch Green", "#91aa81"))

    # Populate the (valid, standalone) template's DOM by element id, then splice
    # the Plotly fragments into their placeholders. Script/style content is set
    # via .string, which bs4 emits raw (no entity-escaping of < > &).
    soup = BeautifulSoup(_tpl("page.html"), "html.parser")
    soup.find(id="theme-vars").string = _THEME_VARS_CSS
    soup.find(id="page-style").string = _tpl("styles.css")
    soup.find(id="chrome-vars").string = chrome_css
    soup.find(id="head-init").string = HEAD_JS
    soup.find(id="theme-script").string = THEME_JS
    soup.find(id="nav-script").string = NAV_JS
    soup.find(id="zoom-script").string = ZOOM_JS
    soup.find(id="reportLink")["href"] = _report_url(report)
    soup.find(id="sidebar").append(BeautifulSoup(nav_links, "html.parser"))
    soup.find(id="sec-1").append(BeautifulSoup(
        intro_html + '<div class="statwrap">%s</div>' % stat_html, "html.parser"))
    soup.find("div", class_="wrap").append(
        BeautifulSoup("".join(sections), "html.parser"))

    html = str(soup)
    for n, frag in plots.items():
        html = html.replace("<!--PLOT:%d-->" % n, frag, 1)
    # to_html's "directory" mode references plotly.min.js but doesn't write it.
    out_dir = Path(DASHBOARD).parent
    (out_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    with open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)
