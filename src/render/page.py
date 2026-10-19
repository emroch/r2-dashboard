"""Dashboard assembly: the section registry, template loading, HTML helpers,
and the build_dashboard entry point that renders every chart into one HTML file.

The page shell lives under templates/ — page.html (a valid, standalone HTML
shell with id'd slots) plus the stylesheet (templates/css/) and the inlined head.js. The page scripts
live under web/ and are published as hashed static assets (render/assets.py).
build_dashboard parses the shell with BeautifulSoup and populates it by element
id (theme vars, stat cards, nav links, chart sections, script URLs).
"""
import os
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from .assets import publish_assets
from .categories import category_css
from .components import (INFO_SVG, notes_html, readout, readout_group,
                         shared_caveats, stage_key)
from config import (COLOR_HEX, DASHBOARD, ORDER_DATE_MIN, ORDERS_THREAD,
                    RESV_DATE_MIN, RESV_THREAD, SECTIONS_CONF, SECTION_GROUPS,
                    THEME_CSS, AS_OF, COMPONENTS)

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


def page_css():
    """The page stylesheet: templates/css/*.css, joined in file-name order. The
    files are numbered by area (base, header, sidebar, page, components, charts,
    map, access) and the order is the cascade's, so a later file wins a tie."""
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((_TPL_DIR / "css").glob("*.css")))


def _section(entry):
    """(title, desc_html, howto_html) from a sections.yaml entry, checking its
    components. howto is "" for a section with nothing to explain."""
    unknown = [c for c in entry.get("components", []) if c not in COMPONENTS]
    if unknown:
        raise LookupError("sections.yaml: %r names unknown components %s"
                          % (entry["title"], unknown))
    return entry["title"], entry["desc"], entry.get("howto", "")


def _howto(html):
    """How to use a section's interactive charts: shown only when scripts run
    (css/04-page.css .howto, under head.js's html.js), since without them there
    is nothing to hover, click or drag."""
    return '<p class="desc howto">%s</p>' % html if html else ""


# sections.yaml `layout` -> the component grid's extra class (css/05-components.css).
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
# Each section's anchor, the group it starts (or None) and the old anchors that
# land on it (sections.yaml `id`, `group`, `aliases`). The summary and the
# data-quality panel, built here, have theirs too: the live page's #sec-1 and
# #sec-18 before stable anchors (#139).
SECTION_IDS = [e["id"] for e in SECTIONS_CONF]
SECTION_GROUP = [e.get("group") for e in SECTIONS_CONF]
SECTION_ALIASES = [list(e.get("aliases", [])) for e in SECTIONS_CONF]
SUMMARY_ID, SUMMARY_ALIASES = "summary", ["sec-1"]
QA_ID, QA_ALIASES = "data-quality", ["sec-18"]
_anchors = ([SUMMARY_ID, QA_ID] + SECTION_IDS + SUMMARY_ALIASES + QA_ALIASES
            + [a for al in SECTION_ALIASES for a in al])
_dupes = sorted({a for a in _anchors if _anchors.count(a) > 1})
if _dupes:
    raise LookupError("sections.yaml: anchors used twice: %s" % _dupes)
_ungrouped = sorted({g for g in SECTION_GROUP if g} - set(SECTION_GROUPS))
if _ungrouped:
    raise LookupError("sections.yaml: unknown group %s (one of %s)"
                      % (_ungrouped, sorted(SECTION_GROUPS)))
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

# The page scripts are static assets under src/web/, published content-hashed by
# render/assets.py and loaded at the end of <body> in page.html's order:
#   theme.js         the toggle; fires r2:themechange, keeps theme-color in step
#   nav.js           sidebar toggle + scroll-spy, report-menu dismissal, local times
#   main.js          the module that boots browser-drawn components
PAGE_SCRIPTS = {"theme-script": "theme.js", "nav-script": "nav.js",
                "main-script": "main.js"}

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


def _day_words(ts):
    """A date as words ("June 9, 2026"), which a screen reader reads as a date."""
    return "%s %d, %d" % (ts.strftime("%B"), ts.day, ts.year)


def _fmt_time(dt):
    """Render a timestamp as a <time> carrying the absolute instant (ISO 8601 with
    offset) so client JS can localize it to the viewer's timezone; the server text
    is the build-timezone fallback shown when JS is off. Written as words ("Oct
    10, 2026, 10:12 PM CDT"), which a screen reader reads as a date and time,
    not as a run of numbers."""
    if dt is None:
        return "—"
    aware = dt.astimezone()  # naive build-local datetime -> attach local offset
    text = "%s %d, %d, %d:%s %s" % (aware.strftime("%b"), aware.day, aware.year,
                                    aware.hour % 12 or 12, aware.strftime("%M %p"),
                                    aware.strftime("%Z"))
    return ('<time datetime="%s" data-r2time>%s</time>'
            % (aware.isoformat(timespec="minutes"), text.strip()))


# A warning sign: a filled triangle (the stat-card yellow, css .src-warn) with a
# dark "!", legible at text size in both themes.
_WARN_SVG = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.2 15.4 14.3'
             'H.6z" fill="currentColor"/><path d="M8 5.6v4.3" stroke="#1e2127" '
             'stroke-width="1.9" stroke-linecap="round"/><circle cx="8" cy="12.1" '
             'r="1.05" fill="#1e2127"/></svg>')


def _src_line(name, meta, extra, thread_url):
    """One header line: linked sheet name, count, when its data last changed
    (viewer-localized via <time>), and a link to the forum thread where an entry
    is submitted or corrected — the sheet is the source of truth, so that thread
    is the only route to changing any of these numbers.

    No "fetched" time: a recent fetch of an unchanged sheet reads the same as an
    old update. A fetch that failed (the build fell back to the newest cache) is
    the one case where an old time means a problem rather than a quiet sheet, so
    a warning sign follows the time, saying so: its label, and the hover/tap
    popover (web/lib/barhover.js)."""
    warn = "Couldn&#8217;t check the sheet for newer data; this is the last copy fetched."
    failed = ("" if meta["live"] or meta.get("offline")
              else ' <span class="src-warn" role="img" aria-label="%s" data-tip="%s">'
                   '%s</span>' % (warn, warn, _WARN_SVG))
    return ('<p class="src"><a href="%s" target="_blank" rel="noopener">%s</a> — %s '
            '<span class="dim">·</span> last updated %s%s '
            '<span class="dim">·</span> <a href="%s" target="_blank" '
            'rel="noopener">add/correct your entry</a></p>'
            % (meta["view_url"], _esc(name), _esc(extra),
               _fmt_time(meta["updated_at"]), failed, thread_url))


# Roamer's R2 Tracker, which this page's design follows (credited in the intro
# and the footer, page.html), through the owner's referral link.
ROAMER_URL = "https://rivianroamer.com/join?with=emroch"


def _aliases(ids):
    """Old anchors that land on a section: empty targets at its top."""
    return "".join('<span class="anchor-alias" id="%s"></span>' % a for a in ids)


def _quality_section(quality, num, cards=""):
    """The data-quality panel: readout cards for what was cleaned, corrected and
    flagged (`cards`), each opening the entries behind its count, then the table
    of how every delivery string was read."""
    conv = quality.get("conversions", [])
    conv_body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                        % (_esc(r), _esc(t), _esc(anc), _esc(res))
                        for r, t, res, anc in conv)
    conv_html = (
        '<div class="qa-conv"><h3>Delivery date parsing'
        '<span class="qa-n">%d</span></h3>'
        '<p class="qa-note">Every distinct delivery string that parsed, and the '
        'date or range it became. A relative window is measured from the order '
        'date (or the as-of date, if there is none).</p>'
        '<table><tr><th>raw</th><th>type</th><th>anchor</th><th>parsed</th></tr>'
        '%s</table></div>'
        % (len(conv), conv_body))
    return ('<section id="%s">%s<h2>%d · Data quality &amp; anomalies</h2>'
            '<p class="desc">What was cleaned, corrected and flagged. A card with an '
            'info mark opens the entries behind its count.</p>%s%s</section>'
            % (QA_ID, _aliases(QA_ALIASES), num, cards, conv_html))


def build_dashboard(df, report, resv, view):
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
    q = report["quality"]
    captions = {
        # Cleaned / removed
        "Order duplicates": "Repeat rows that added nothing over the row kept.",
        "Reservation duplicates": "Repeat usernames in the reservations sheet; the first is kept.",
        "Reservations converted": "Reservation holders already counted as orders.",
        "Invalid dates": "Order or reservation dates outside the plausible window, cleared (original → dropped).",
        "Premature configs": "Orders for a trim, paint or interior not yet orderable on the order date; the row is removed.",
        "Likely entry errors": "VINs and delivery estimates that contradict the order date or the orders around them, made unknown. Nothing is corrected.",
        "Cancellations": "Orders and reservations removed because the person cancelled or the row is a superseded resubmission (reason from overrides.yaml).",
        "Unrecoverable VINs": "VINs too redacted to recover (a trailing X hides the low digits), so they count as unknown.",
        "Resubmission conflicts": "Repeat submissions of the same build that disagreed. They merge into one order, taking each field from the latest that filled it.",
        # Added or corrected
        "Manual additions": "Forum-only orders added in overrides.yaml (not in the sheet).",
        "Manual fix-ups": "Fields set or corrected in overrides.yaml (field: old → new).",
        "Recovered VINs": "VINs with leading X's, recovered from the digits that remain (original → value).",
        "Contradictory answers": "Rows where two answers can't both be right, with the reading assumed. The Launch Package column beats Autonomy+ and Tow; a named R1 model beats \"not an owner\".",
        # Flagged, not changed
        "Repeat usernames": "A username on several rows that disagree, so all are kept rather than guessed between; the fields that differ are listed.",
        "Shared-VIN orders": "A VIN is one car's, so a shared one is a typo, a masked VIN typed as round digits, or one order entered twice. Each entry says whether the other order matches.",
        "Similar usernames": "Usernames that differ only in case, spaces or punctuation but weren't merged.",
        "Missing order dates": "Orders with no order date, which the charts by order week leave out. One with no VIN or estimate may be a reservation entered early.",
        "Inferred deliveries": "Counted as delivered only because a window, range or month estimate has passed, with no firm date to confirm it. Some may be stale.",
        "Unpriced orders": "Options with no published price, or not offered on the order's trim. An order with an unknown price is left out of the price stats.",
        "Milestone mismatches": "Posted VIN or scheduling dates that don't fit the order or the sheet's history, or a sheet showing a value before the order date.",
        "Override issues": "Entries in overrides.yaml naming an unknown field, a username with no matching order, or an addition already in the sheet.",
        "Unmapped columns": "Columns in a source sheet that nothing reads. A mapped column that is missing or renamed stops the build instead.",
        # Changed in the sheet (from its history)
        "VIN changes": "A VIN replaced by a different one after it was recorded. Often a typo fix; one that goes back to an earlier value usually means an edit to the wrong row.",
        "Order date changes": "An order date replaced by another. Most are year-typo fixes; one that moves by weeks shifts every window measured from it.",
        "Firm-to-vague changes": "A firm delivery date replaced by something vaguer (\"TBD\", \"Delayed\"): usually a real delay.",
        "Vanished orders": "An order that disappeared without a curated deletion: a silent cancellation, or a row removed by mistake.",
        # The delivery estimate cards (Order-to-delivery time)
        "Likely errors": "Delivery estimates that contradict the order date or cars with nearby VINs; they count as unknown.",
        "Unparseable": "Non-empty delivery text that didn't parse to a date, range or window.",
    }

    def card(label, rows, count=None):
        return (label, len(rows) if count is None else count, rows)

    # How the data was cleaned and what is flagged: readout cards, at the foot of
    # the page in the data-quality panel (they matter to anyone checking the
    # numbers, not to a first look), each opening the entries behind its count.
    cleaning_groups = [
        ("Cleaned / removed", [
            card("Order duplicates", san["Duplicates removed"]),
            ("Reservation duplicates", rr["n_self_dupes"], rr["self_dupe_records"]),
            ("Reservations converted", rr["n_matched"], rr["matched_records"]),
            ("Invalid dates", report["bad_order"] + report["bad_resv"],
             san["Invalid dates dropped"]),
            ("Premature configs", report["n_premature"],
             san["Premature configs dropped"]),
            card("Likely entry errors", san["Likely entry errors set aside"]),
            # Both sheets' cancellations (the orders' alone are san[...]).
            card("Cancellations", q["deletions"]),
            card("Unrecoverable VINs", q["vin_unrec"]),
            card("Resubmission conflicts", q["merge_conflicts"]),
        ]),
        ("Added or corrected", [
            ("Manual additions", report["n_added"], san["Manual additions"]),
            card("Manual fix-ups", san["Manual fix-ups"]),
            ("Recovered VINs", report["vin_obfuscated"], san["VINs de-obfuscated"]),
            card("Contradictory answers", q["answer_conflicts"]),
        ]),
        # Listed for review and left as they are: every order stays counted.
        ("Flagged, not changed", [
            card("Repeat usernames", san["Repeat usernames kept"]),
            card("Shared-VIN orders", q["shared_vins"]),
            card("Similar usernames", q["fuzzy_dups"]),
            card("Missing order dates", q["no_order_date"]),
            card("Inferred deliveries", q["inferred_delivery"]),
            # Configured price leaves these out (no published price yet).
            ("Unpriced orders", pz["n_unpriced"], q["price_issues"]),
            card("Milestone mismatches", q["milestone_issues"]),
            card("Override issues", q["override_issues"]),
            card("Unmapped columns", q["schema_notices"]),
        ]),
        # From the sheet's history (every committed snapshot).
        ("Changed in the sheet", [
            card("VIN changes", q.get("vin_changes", [])),
            card("Order date changes", q.get("order_date_changes", [])),
            card("Firm-to-vague changes", q.get("firm_to_vague", [])),
            card("Vanished orders", q.get("left_sheet", [])),
        ]),
    ]

    def _groups(spec):
        # A sheet notice names a sheet, not a user.
        return "".join(readout_group(
            gtitle, [readout(v, k, rows or (), captions.get(k, ""),
                             who="Sheet" if k == "Unmapped columns" else "User")
                     for k, v, rows in cards])
            for gtitle, cards in spec)

    # Each order's delivery estimate, in Order-to-delivery time, which charts
    # only the firm ones. Partitions all orders: firm + range/window + no date +
    # unparseable + set aside = total.
    callouts = {"order-to-delivery": _groups([
        ("Delivery estimate (of %d orders)" % report["n_dedup"], [
            ("Firm date", firm, None),
            ("Range / window", rangewin, None),
            ("No date given", no_date, None),
            ("Unparseable", len(unparseable), unparseable),
            ("Likely errors", set_aside,
             [r for r in san["Likely entry errors set aside"]
              if r[2].startswith("delivery ")]),
        ])])}

    # The summary's headline numbers, each linking to the section behind it.
    # Delivered is the summary progress aggregate's (reconciled with the view);
    # the build rate is the cadence chart's latest.
    progress = view.readouts["progress"]
    delivered = next(int(c["n"]) for c in progress.cells if c["value"] == "delivered")
    share = round(100 * delivered / progress.counted) if progress.counted else 0
    rate = view.mounted["build-cadence"].meta.get("rate") if "build-cadence" in view.mounted else None
    headline = [
        readout(format(report["n_dedup"], ","), "Orders", href="#reservations-orders"),
        readout(format(rr["n_incomplete"], ","), "Reservations not yet ordered",
                href="#reservations-orders"),
        readout(format(delivered, ","), "Delivered (%d%%)" % share, href="#delivery-progress"),
    ] + ([readout("≈ %s" % rate, "VINs a day, lately", href="#build-front")]
         if rate else [])
    stat_html = '<div class="ro-group ro-head"><div class="ro-row">%s</div></div>' % "".join(headline)

    # Sections, in sections.yaml order, numbered from 2 (the summary is 1). A
    # section that starts a group is preceded by the group's label.
    sections = []
    for i, (title, desc, howto) in enumerate(SECTIONS):
        n, sid, group = i + 2, SECTION_IDS[i], SECTION_GROUP[i]
        comps = _components_html(SECTION_COMPONENTS[i], view, SECTION_LAYOUTS[i])
        label = ('<p class="sec-group">%s <span>%s</span></p>'
                 % (_esc(group), _esc(SECTION_GROUPS[group])) if group else "")
        sections.append(
            '%s<section id="%s">%s<h2>%d · %s</h2><p class="desc">%s</p>%s%s'
            '%s</section>' % (label, sid, _aliases(SECTION_ALIASES[i]), n, _esc(title),
                              desc, _howto(howto), callouts.get(sid, ""), comps))
    sections.append(_quality_section(report["quality"], len(SECTIONS) + 2,
                                     cards='<div class="qa-clean">%s</div>'
                                     % _groups(cleaning_groups)))

    intro_html = (
        _aliases(SUMMARY_ALIASES) + '<h2>1 · Sources &amp; summary</h2>'
        + _src_line("Orders & Deliveries sheet", om,
                    "%d unique orders" % report["n_dedup"], ORDERS_THREAD)
        + _src_line("Reservations sheet", rm,
                    "%d incomplete reservations (of %d rows)"
                    % (rr["n_incomplete"], rr["n_raw"]), RESV_THREAD)
        + '<p class="src"><a href="https://www.rivianforums.com/forum/forums/r2-forum.8/"'
          ' target="_blank" rel="noopener">Rivian R2 forum</a> — the community these'
          ' owner/reservation trackers are compiled from</p>'
        # The design's credit, asked for by Roamer's owner, who okayed it.
        + '<p class="src">Design inspired by <a href="%s" target="_blank"'
          ' rel="noopener">Roamer&#8217;s R2 Tracker</a></p>' % ROAMER_URL
        # How the data is read, and (with scripts) how the charts are used:
        # reference, so it's folded away rather than standing between the
        # sources and the numbers. Written to read the same aloud as on screen
        # (dates and ranges in words, keys spelled out): an inline swap for a
        # screen reader splits the sentence into separate stops.
        + '<details class="intro-more"><summary>About this page</summary>'
          '<p class="meth">Data collected from Rivian R2 reservation holders and '
          'buyers on the Rivian forums, who track their reservations, orders, VINs '
          'and deliveries in two community spreadsheets. This page cleans those '
          'entries and charts what the cohort ordered, how orders are moving toward '
          'delivery, how production is advancing by VIN, and where the cars are '
          'going.</p>'
          '<p class="meth">Relative delivery windows, such as &#8220;4 to 8 weeks&#8221;, '
          'are measured from each order date. Order dates before %s and '
          'reservations before %s are treated as invalid, and reservations that '
          'also appear as orders are dropped. &#8220;Last updated&#8221; is when a '
          'sheet last changed. Numbers marked with an info icon %s open the entries '
          'behind them.</p>'
          % (_day_words(ORDER_DATE_MIN), _day_words(RESV_DATE_MIN), INFO_SVG)
        + _howto('Hover a chart for its values. Click a legend entry to hide it, '
                 'or double-click to show it alone. On the scatter charts, pinch, '
                 'or hold Command or Control and scroll, to zoom; drag to pan; '
                 'double-click or <em>Reset view</em> to return.')
        + '</details>')

    # Chart-navigation sidebar: the summary (1), each section (2..N+1) under its
    # group's heading, and the QA panel (N+2), numbered as the headings are.
    nav = ['<a href="#%s" data-sec="%s">1 · Sources &amp; summary</a>' % (SUMMARY_ID, SUMMARY_ID)]
    for i, (t, _, _) in enumerate(SECTIONS):
        if SECTION_GROUP[i]:
            nav.append('<div class="side-group">%s</div>' % _esc(SECTION_GROUP[i]))
        nav.append('<a href="#%s" data-sec="%s">%d · %s</a>'
                   % (SECTION_IDS[i], SECTION_IDS[i], i + 2, _esc(t)))
    qa_num = len(SECTIONS) + 2
    nav.append('<div class="side-group">Data</div>')
    nav.append('<a href="#%s" data-sec="%s">%d · Data quality &amp; anomalies</a>'
               % (QA_ID, QA_ID, qa_num))
    nav_links = "".join(nav)
    # Header/sidebar chrome takes its greens from the palette (a nod to the
    # Rivian paints): Forest Green for the header, Launch Green for the sidebar.
    header_bg = COLOR_HEX.get("Forest Green", "#226222")
    chrome_css = ":root{--header-bg:%s;--side-bg:%s;}" % (
        header_bg, COLOR_HEX.get("Launch Green", "#91aa81"))

    # Populate the (valid, standalone) template's DOM by element id. Script/style
    # content is set via .string, which bs4 emits raw (no entity-escaping of < > &).
    soup = BeautifulSoup(_tpl("page.html"), "html.parser")

    def slot(*args, **kwargs):
        # A slot missing from page.html is a template bug: say which one, rather
        # than failing on None a line later.
        tag = soup.find(*args, **kwargs)
        if not isinstance(tag, Tag):
            raise LookupError("page.html has no slot %r %r" % (args, kwargs))
        return tag

    slot(id="theme-vars").string = _THEME_VARS_CSS
    slot(id="page-style").string = page_css()
    slot(id="chrome-vars").string = chrome_css
    slot(id="category-vars").string = category_css()
    # The browser tab/status-bar tint matches the header; theme.js keeps it in
    # step if the header color ever differs per theme.
    slot(id="theme-color")["content"] = header_bg
    slot(id="head-init").string = HEAD_JS
    assets = publish_assets(Path(DASHBOARD).parent)
    for sid, name in PAGE_SCRIPTS.items():
        slot(id=sid)["src"] = assets + name
    slot(id="reportData")["href"] = ORDERS_THREAD
    slot(id="reportGithub")["href"] = _report_url(report)
    slot(id="reportForum")["href"] = FORUM_DM_URL
    slot(id="sidebar").append(BeautifulSoup(nav_links, "html.parser"))
    slot(id=SUMMARY_ID).append(BeautifulSoup(
        intro_html + '<div class="statwrap">%s</div>' % stat_html, "html.parser"))
    slot("main", class_="wrap").append(
        BeautifulSoup("".join(sections), "html.parser"))

    html = str(soup)
    with open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)
