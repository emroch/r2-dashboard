"""Dashboard assembly: the section registry, template loading, HTML helpers,
and the build_dashboard entry point that renders every chart into one HTML file.

The page shell lives under templates/ — page.html (a valid, standalone HTML
shell with id'd slots) plus styles.css and the inlined head.js. The page scripts
live under web/ and are published as hashed static assets (render/assets.py).
build_dashboard parses the shell with BeautifulSoup and populates it by element
id (theme vars, stat cards, nav links, chart sections, script URLs), then splices
Plotly's fragments into their <!--PLOT:n--> placeholders verbatim.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag
from plotly.offline import get_plotlyjs

from .assets import publish_assets
from .categories import category_css
from .components import (notes_html, readout, readout_group, shared_caveats,
                         stage_key, stage_readouts)
from .charts import (fig_delivery_timeline,
                     fig_delivery_latency,
                     fig_dest_vs_delivery, fig_geo,
                     fig_order_timeline, fig_vin_by_config,
                     fig_vin_cadence,
                     fig_vin_vs_order)
from config import (CHART_CHROME, COLOR_HEX, DASHBOARD, DIMENSIONS, ORDERS_THREAD,
                    RESV_THREAD, SECTIONS_CONF, THEME_CSS, AS_OF, COMPONENTS)

# templates/ sits alongside this render/ package, under the src/ root.
_TPL_DIR = Path(__file__).resolve().parents[1] / "templates"

# The "Report issue" menu's two destinations. GitHub is the tracker of record;
# the forum DM is the no-account path, since filing an issue needs a sign-in.
# The forum is XenForo, whose compose URL takes the recipient and a subject
# (this exact link confirmed working).
ISSUE_FORM_URL = "https://github.com/emroch/r2-dashboard/issues/new"
FORUM_DM_URL = ("https://www.rivianforums.com/forum/conversations/add?"
                + urlencode({"to": "emroch", "title": "R2 Dashboard Feedback"}))


def _tpl(name):
    """Read a template file (CSS/JS/HTML shell) from templates/."""
    return (_TPL_DIR / name).read_text(encoding="utf-8")


# The Plotly figure builders a section can name in sections.yaml (`charts:`).
# Each moves to a presentation-layer component as its section migrates
# (docs/presentation.md, Stages).
_BUILDERS = {f.__name__: f for f in (
    fig_order_timeline, fig_delivery_timeline, fig_delivery_latency,
    fig_vin_vs_order, fig_vin_cadence,
    fig_vin_by_config, fig_geo, fig_dest_vs_delivery)}


def _section(entry):
    """(title, desc_html, builder or tuple of builders) from a sections.yaml entry."""
    unknown = [n for n in entry.get("charts", []) if n not in _BUILDERS]
    unknown += [c for c in entry.get("components", []) if c not in COMPONENTS]
    if unknown:
        raise LookupError("sections.yaml: %r names unknown charts/components %s"
                          % (entry["title"], unknown))
    builders = tuple(_BUILDERS[n] for n in entry.get("charts", []))
    return (entry["title"], entry["desc"],
            builders[0] if len(builders) == 1 else builders)


# sections.yaml `layout` -> the component grid's extra class (styles.css).
_LAYOUTS = {"grid": "", "fit": " r2c-fit", "single": " r2c-single"}


def _components_html(cids, view, layout="grid"):
    """A section's components, in a grid. Take-rates get the stage key once, and
    the caveats every component in the group carries are said once, under the
    key (for take-rates that is the delivery-status note the key needs)."""
    if not cids:
        return ""
    key = (stage_key() if any(COMPONENTS[c]["template"] == "takerate" for c in cids)
           else "")
    shared = shared_caveats([COMPONENTS[c] for c in cids]) if len(cids) > 1 else []
    return '<div class="r2c-group">%s%s<div class="r2c-grid%s">%s</div></div>' % (
        key, notes_html(shared), _LAYOUTS[layout],
        "".join(view.render(c, shared) for c in cids))


# Display order = list order (src/conf/sections.yaml). Section numbers (chart
# titles + sidebar links) are assigned from position at render time.
SECTIONS = [_section(e) for e in SECTIONS_CONF]
# Each section's presentation-layer component ids (charts.yaml), by position.
SECTION_COMPONENTS = [list(e.get("components", [])) for e in SECTIONS_CONF]
SECTION_LAYOUTS = [e.get("layout", "grid") for e in SECTIONS_CONF]
_bad = sorted(set(SECTION_LAYOUTS) - set(_LAYOUTS))
if _bad:
    raise LookupError("sections.yaml: unknown layout %s (one of %s)"
                      % (_bad, sorted(_LAYOUTS)))


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
# written into the page as a JSON island that theme.js reads, so its retint and
# the baked-in chart colors agree. "</" is escaped so the JSON can't close the
# <script> element it sits in.
CHROME_JSON = json.dumps({"light": CHART_CHROME["light"],
                          "dark": CHART_CHROME["dark"]},
                         separators=(",", ":")).replace("</", "<\\/")

# The page scripts are static assets under src/web/, published content-hashed by
# render/assets.py and loaded at the end of <body> in page.html's order:
#   plotly-theme.js  re-tints the (already-rendered) Plotly charts' chrome on each
#                    r2:themechange. Data colors are left untouched. Goes with
#                    the last Plotly chart (#111).
#   theme.js         the toggle; fires r2:themechange, keeps theme-color in step
#   nav.js           sidebar toggle + scroll-spy, report-menu dismissal, local times
#   scrollzoom.js    wheel arbitration between zooming a map and scrolling the page
#   main.js          the module that boots browser-drawn components (none yet)
PAGE_SCRIPTS = {"plotly-theme-script": "plotly-theme.js",
                "theme-script": "theme.js", "nav-script": "nav.js",
                "zoom-script": "scrollzoom.js", "main-script": "main.js"}

# Plotly toolbar, applied to every figure. Box- and lasso-select mark points for
# a selection this dashboard never reads, so they only add width to a bar that
# has to fit in a chart's top margin; dropping them takes it from 272px to 200px.
# The logo goes too — it links off-site and earns none of that space. Zoom, pan
# and reset stay, since they're the ones worth having on the denser charts.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
}

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


def _src_line(name, meta, extra, thread_url):
    """One header line: linked sheet name, count, fetched + last-updated times
    (viewer-localized via <time>), the offline badge, and a link to the forum
    thread where an entry is submitted or corrected — the sheet is the source of
    truth, so that thread is the only route to changing any of these numbers."""
    live = ("" if meta["live"]
            else ' <span class="warn">(offline — showing cached copy)</span>')
    return ('<p class="src"><a href="%s" target="_blank" rel="noopener">%s</a> — %s '
            '<span class="dim">·</span> fetched %s%s '
            '<span class="dim">·</span> last updated %s '
            '<span class="dim">·</span> <a href="%s" target="_blank" '
            'rel="noopener">add or correct your entry</a></p>'
            % (meta["view_url"], _esc(name), _esc(extra),
               _fmt_time(meta["fetched_at"]), live, _fmt_time(meta["updated_at"]),
               thread_url))


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
    ("entry_errors", "Likely entry errors set aside",
     "Values that parse fine on their own but can't be right against the rest of "
     "the data. Each one is set aside as unknown, so it isn't charted or counted. "
     "Nothing is corrected, because the data can't say what the right value is. "
     "Three checks: a delivery estimate that ends before the order was placed, or "
     "starts more than a year after it (usually a typo'd year); a firm delivery "
     "date well before cars with nearby VINs, since a car can't arrive before it "
     "is built (a bare \"8-12\" meant as weeks reads as 12 August); and a VIN "
     "far outside the range of orders placed around the same date (a missing or "
     "extra digit). A late delivery or a low VIN is never flagged on its own, "
     "because a held-back car explains both. A value confirmed correct can be "
     "kept with overrides.yaml's verified list."),
    ("vin_changes", "VINs that changed after being set",
     "From the sheet's history (every committed snapshot): a VIN replaced by a "
     "DIFFERENT VIN after one was recorded. Reformatting and de-obfuscation don't "
     "count. Often a typo fix, but a change that goes back to an earlier value "
     "usually means someone edited the wrong row and then put it back. Fields an "
     "override already sets are left out."),
    ("order_date_changes", "Order dates that changed after submission",
     "An order date replaced by a different date. Most are year-typo fixes, but a "
     "date that moves by weeks shifts every delivery window measured from it."),
    ("firm_to_vague", "Firm delivery dates that went vague",
     "A firm delivery date replaced by something vaguer (\"TBD\", \"Delayed\") "
     "and still vague. Usually a real delay; worth asking for an update."),
    ("milestone_issues", "Milestone dates that don't fit",
     "When each order's final VIN was assigned and its final delivery date set: "
     "from a post (a `dates:` entry in overrides.yaml), else the first snapshot "
     "that showed the final value. A posted date is only used if it fits: not in "
     "the future, not before the order, not after the sheet already showed the "
     "value, and a scheduling date not after the delivery itself. Listed here: "
     "posted dates that didn't fit, and sheets that showed a final value before "
     "the order date, where one of the two dates must be wrong."),
    ("left_sheet", "Orders that left the sheet",
     "An order that disappeared from the sheet without a curated deletion: a "
     "silent cancellation, or a row removed by mistake. If it was a cancellation, "
     "a deletion in overrides.yaml records why."),
    ("merge_conflicts", "Repeat submissions that disagreed",
     "Fields where a person's repeat submissions of the SAME build contradicted "
     "each other. The rows are merged into one order, taking each field from the "
     "latest submission that filled it \u2014 people resubmit in order to correct "
     "themselves \u2014 and every contradiction is listed here rather than resolved "
     "silently, since self-reported data disagreeing with itself is worth a look."),
    ("dup_conflicts", "Repeat usernames kept as separate entries",
     "One username appearing on more than one row where the rows disagree, so "
     "neither can be dropped without guessing. A repeat submission is only "
     "collapsed when it adds nothing \u2014 every field it fills, another row fills "
     "identically. Rows that conflict are either a data-entry error or the same "
     "person placing a second, genuinely different order, and choosing between "
     "those would either double-count someone or discard a real order, so both "
     "are kept and listed here with the fields they differ on."),
    ("fuzzy_dups", "Possible duplicate usernames",
     "Usernames that normalize alike (case/space/punctuation) but weren't merged "
     "by the exact-duplicate dedup."),
    ("vin_unrec", "Unrecoverable VINs",
     "VIN tokens too redacted to recover a sequence number."),
    ("bad_dates", "Invalid dates dropped",
     "Order/reservation dates outside the plausible window, cleared."),
    ("deletions", "Removed by curation",
     "Orders and reservations dropped because something outside the sheet says "
     "they shouldn't be counted \u2014 the person posted that they cancelled, or the "
     "row is a superseded resubmission that dedup can't merge on its own. These "
     "rows are otherwise valid \u2014 nothing in the data marks either case \u2014 so each "
     "one is a manual entry in overrides.yaml carrying its own reason and source, "
     "listed here individually for that reason. Cancelling an order also keeps "
     "that person out of the reservation count, rather than letting them resurface "
     "as an outstanding reservation."),
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


def build_dashboard(df, report, resv, view):
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
            # the charts adapt to light/dark (chrome is re-tinted by plotly-theme.js).
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
        comps = _components_html(SECTION_COMPONENTS[i], view, SECTION_LAYOUTS[i])
        sections.append(
            '<section id="sec-%d"><h2>%d · %s</h2><p class="desc">%s</p>'
            '%s%s</section>' % (n, n, _esc(title), desc, comps, "".join(frags)))
    sections.append(_quality_section(report["quality"], len(SECTIONS) + 2))

    dc = report["delivery_counts"]
    firm = dc.get("explicit", 0)
    rangewin = dc.get("window", 0) + dc.get("range", 0) + dc.get("month", 0)
    unparseable = report["quality"]["unparseable"]
    # unknown = "no date given" (missing/placeholder) + unparseable + estimates set
    # aside as likely entry errors; split them.
    set_aside = report["n_set_aside_delivery"]
    no_date = dc.get("unknown", 0) - len(unparseable) - set_aside
    san = report["sanitized"]
    pz = report["price"]
    rr, om, rm = report["resv"], report["orders_meta"], report["resv_meta"]
    captions = {
        "Order duplicates": "Repeat rows removed because they added nothing over the row kept",
        "Repeat usernames kept": "Rows sharing a username whose values disagree, so both were kept rather than one guessed away",
        "Reservation duplicates": "Repeat usernames in the reservations sheet (kept first)",
        "Reservations already ordered": "Reservation-holders already counted in the orders sheet",
        "VINs de-obfuscated": "Obfuscated VINs recovered (original → value)",
        "VINs recovered": "VINs that could not be recovered (dropped)",
        "Invalid dates dropped": "Order/reservation dates cleared as out-of-range (original → dropped)",
        "Likely entry errors set aside": "VINs and delivery estimates that contradict the order date or the orders around them, made unknown rather than charted (see the data-quality panel)",
        "Set aside as errors": "Delivery estimates that parsed but contradict the order date or cars with nearby VINs, so they count as unknown",
        "Premature configs dropped": "Orders for a trim/paint/interior not yet orderable on the order date (row removed)",
        "Curated removals": "Orders and reservations removed because the person posted that they cancelled, or the row is a superseded resubmission (reason from overrides.yaml)",
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
            ("Repeat usernames kept", len(san["Repeat usernames kept"]),
             san["Repeat usernames kept"]),
            ("Reservation duplicates", rr["n_self_dupes"], rr["self_dupe_records"]),
            ("Reservations already ordered", rr["n_matched"], rr["matched_records"]),
            ("Invalid dates dropped", report["bad_order"] + report["bad_resv"],
             san["Invalid dates dropped"]),
            ("Premature configs dropped", report["n_premature"],
             san["Premature configs dropped"]),
            ("Likely entry errors set aside", len(san["Likely entry errors set aside"]),
             san["Likely entry errors set aside"]),
            ("Curated removals", len(san["Removed by curation"]),
             san["Removed by curation"]),
            ("Manual fix-ups", len(san["Manual fix-ups"]), san["Manual fix-ups"]),
        ]),
        ("VIN recovery", [
            ("VINs recovered", report["vin_present"], san["VINs recovered"]),
            ("VINs de-obfuscated", report["vin_obfuscated"], san["VINs de-obfuscated"]),
        ]),
        # Partitions all orders: firm + range/window + no date + unparseable + set
        # aside = total.
        ("Delivery estimate (of %d orders)" % report["n_dedup"], [
            ("Firm date", firm, None),
            ("Range / window", rangewin, None),
            ("No date given", no_date, None),
            ("Unparseable", len(unparseable), unparseable),
            ("Set aside as errors", set_aside,
             [r for r in san["Likely entry errors set aside"]
              if r[2].startswith("delivery ")]),
        ]),
        # Delivery progress goes here, from the view (below).
        # Configured vehicle price (no destination/doc/taxes). "Unpriced" keeps the
        # mean/median honest by showing what they were NOT computed over.
        ("Configured price (of %d priced)" % pz["n_priced"], [
            ("Mean", _money(pz["mean"]), None),
            ("Median", _money(pz["median"]), None),
            ("Range", "%s–%s" % (_money(pz["min"]), _money(pz["max"])), None),
            ("Unpriced", pz["n_unpriced"], report["quality"]["price_issues"]),
        ]),
    ]
    groups = [readout_group(gtitle, [readout(v, k, rows or (), captions.get(k, ""))
                                     for k, v, rows in cards])
              for gtitle, cards in stat_groups]
    # Every order by delivery stage: the split the take-rate bars draw, from the
    # same aggregate (reconciled with the rest of the view). Delivered is inferred, not reported, which the caveat says. It
    # follows the delivery estimates (stat_groups[3]).
    progress = view.readouts["progress"]
    groups.insert(4, readout_group(
        "Delivery progress (of %s orders)" % format(progress.counted, ","),
        stage_readouts(progress), note=DIMENSIONS["delivered"]["caveat"]))
    stat_html = "".join(groups)

    intro_html = (
        '<h2>1 · Sources &amp; summary</h2>'
        + _src_line("Orders & Deliveries sheet", om,
                    "%d unique orders" % report["n_dedup"], ORDERS_THREAD)
        + _src_line("Reservations sheet", rm,
                    "%d incomplete reservations (of %d rows)"
                    % (rr["n_incomplete"], rr["n_raw"]), RESV_THREAD)
        + '<p class="src"><a href="https://www.rivianforums.com/forum/forums/r2-forum.8/"'
          ' target="_blank" rel="noopener">Rivian R2 forum</a> — the community these'
          ' owner/reservation trackers are compiled from</p>'
        + '<p class="meth">Delivery windows are measured from each customer&#8217;s '
          'R2 order date. Order dates before 2026-06-09 and reservations before '
          '2024-03-07 are treated as invalid; reservations already present in the '
          'orders sheet are dropped as duplicates. &#8220;Last updated&#8221; is '
          'when a sheet&#8217;s contents last changed between fetches. Click a '
          'number marked &#9432; to see the entries behind it. Charts with '
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
    header_bg = COLOR_HEX.get("Forest Green", "#226222")
    chrome_css = ":root{--header-bg:%s;--side-bg:%s;}" % (
        header_bg, COLOR_HEX.get("Launch Green", "#91aa81"))

    # Populate the (valid, standalone) template's DOM by element id, then splice
    # the Plotly fragments into their placeholders. Script/style content is set
    # via .string, which bs4 emits raw (no entity-escaping of < > &).
    soup = BeautifulSoup(_tpl("page.html"), "html.parser")

    def slot(*args, **kwargs):
        # A slot missing from page.html is a template bug: say which one, rather
        # than failing on None a line later.
        tag = soup.find(*args, **kwargs)
        if not isinstance(tag, Tag):
            raise LookupError("page.html has no slot %r %r" % (args, kwargs))
        return tag

    slot(id="theme-vars").string = _THEME_VARS_CSS
    slot(id="page-style").string = _tpl("styles.css")
    slot(id="chrome-vars").string = chrome_css
    slot(id="category-vars").string = category_css()
    # The browser tab/status-bar tint matches the header; theme.js keeps it in
    # step if the header color ever differs per theme.
    slot(id="theme-color")["content"] = header_bg
    slot(id="head-init").string = HEAD_JS
    slot(id="chrome-data").string = CHROME_JSON
    assets = publish_assets(Path(DASHBOARD).parent)
    for sid, name in PAGE_SCRIPTS.items():
        slot(id=sid)["src"] = assets + name
    slot(id="reportData")["href"] = ORDERS_THREAD
    slot(id="reportGithub")["href"] = _report_url(report)
    slot(id="reportForum")["href"] = FORUM_DM_URL
    slot(id="sidebar").append(BeautifulSoup(nav_links, "html.parser"))
    slot(id="sec-1").append(BeautifulSoup(
        intro_html + '<div class="statwrap">%s</div>' % stat_html, "html.parser"))
    slot("div", class_="wrap").append(
        BeautifulSoup("".join(sections), "html.parser"))

    html = str(soup)
    for n, frag in plots.items():
        html = html.replace("<!--PLOT:%d-->" % n, frag, 1)
    # to_html's "directory" mode references plotly.min.js but doesn't write it.
    out_dir = Path(DASHBOARD).parent
    (out_dir / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8")
    with open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)
