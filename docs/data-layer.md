# Data layer design

Status: **proposed**. This is part of the dashboard revamp (#65), tracked in #80, and it
comes before the presentation work (#66). It is a design, not a commitment to an implementation;
each stage below becomes its own issue and PR.

## Why

Each build today reads **only the newest snapshot** of each sheet:

- **Unused history.** The 226 order and 83 reservation snapshots in `data/raw/`
  (29 MB since 2026-07-10) are committed on every change, but nothing reads them.
- **Curation applies to all time.** `src/conf/overrides.yaml` (about 1,100 lines)
  applies every correction to every build as though it had always been true. It is
  keyed by username and records its sources only in comments.
- **Issues waiting on this.** Several open issues need data over time or a data
  format the page can mount from, which the current setup can't provide:
  - **#32** trends from the fetch history
  - **#34** estimate accuracy
  - **#51** reconfigurable charts

This document describes how the data is stored, identified, sanitized, corrected,
and tracked over time.

Ground rules agreed for the design:

- **Privacy:** only aggregates and the current snapshot are published. Per-order
  history is used internally (for accuracy scoring and change detection) and never
  published.
- **Storage:** start from the raw CSVs and rebuild everything from them. Whether to
  commit a derived store is decided once replay cost has been measured.
- **Scope:** both sheets, orders and reservations.
- **Unchanged output:** the current dashboard is "the state at T = now". Every stage
  must leave its output unchanged, apart from new QA findings.

## What the history looks like

A survey of every snapshot, on 2026-10-03:

- **No schema drift.** Every snapshot's header maps cleanly with today's
  `schema.yaml`, so the existing parsers can replay all of history unchanged.
- **The sheet is almost append-only.**
  - **One deletion:** only one row was ever deleted (`ricktardif`, 2026-09-21), and
    it renumbered the 124 rows after it, so `#` is not an identity.
  - **One spelling variant:** one username gained a variant spelling (`FL5guy` /
    `FL5Guy`).
  - **Duplicate usernames:** 14 usernames hold more than one row.
  - **A workable key:** the lowercased username plus the row's position among that
    user's rows gives 674 stable keys.
- **Little changes.**
  - **Overall:** 175 of 674 orders ever changed a field, in 267 change events.
  - **By field:** `delivery_raw` changed on 157 orders, `vin_raw` on 128, and
    `order_raw` on 12. Only 5 changed configuration.
  - **VINs:** 17 changed after being set (typo fixes); none was ever cleared.
- **Time is approximate.**
  - **Timestamps:** a snapshot's filename timestamp is authoritative. Git commit times
    lag only for the bulk add of the 7/10–7/19 files.
  - **Change windows:** a change happened somewhere in (previous snapshot, this
    snapshot]. The median gap between order snapshots is 7 hours; the longest is
    121 hours.
  - **First-VIN dates:** recoverable for 121 orders. The other 239 already had a VIN
    when first seen, so only an upper bound is known.
- **Curation, today:**

  | Section | Entries | With a forum URL in a comment |
  |---|---|---|
  | `overrides` | 67 | 63 |
  | `additions` | 45 | 45 |
  | `deletions` (scoped) | 5 | 3 |

  Three overrides are already fully redundant with the sheet, and one partly.

## Layers

Each layer is a pure function of the one below it, so any build can be reproduced
from `data/raw/` and the curation file.

| # | Layer | What it holds | Built from |
|---|---|---|---|
| 1 | **Snapshots** | `data/raw/*.csv`, immutable, committed | `ingest/fetch.py` (unchanged) |
| 2 | **Observations** | per snapshot, each row's raw mapped fields tagged with an order key; raw text only, no cleaning | `schema_check.find_header` / `map_columns` + order identity |
| 3 | **Event log** | consecutive identical observations collapsed into `(key, field, value, first_seen, last_seen)` | layer 2 |
| 4 | **Curation** | each correction with `source`, `as_of`, `reason`, and optional `checked` / milestone `dates` | `overrides.yaml` (v2) |
| 5 | **Today's cleaned orders, with milestones** | the cleaned orders, plus when each final VIN and final delivery date took hold | layers 3–4, through the existing cleaning (`ingest/milestones.py`) |
| 6 | **Published artifacts** | current-snapshot CSV, event-dated time series, data contract | layer 5 |

### Time semantics

- **When a value took hold.** A value's start is only bounded: it took hold after
  the previous snapshot and by `first_seen`. Values present in the first snapshot are
  left-censored ("on or before 2026-07-10"). Anything computed from history carries
  these bounds and never claims a precise time.
- **Final values only (#99).** What matters long term is each order's final values
  and when they took hold, not the transient values in between. A move like
  10/9 → 10/19 can't be told apart from a typo fix unless a post says which. So
  milestones date the *final* VIN and the *final* firm delivery date: from a post's
  date when curated, else from the first snapshot that showed the final value (an
  upper bound).
- **"True by date", not "reported by date" (#99).** The series counts each order on
  its own event dates, from today's data, so later reports revise past points.
  How far the sheet lagged behind events is forum participation, which isn't a
  goal, so it isn't published. Values from the sheet stay tied to their snapshots:
  a sheet edit can't be backdated, so a sheet-derived date means "by then".

### Reuse of the existing cleaning

Layer 5 is the existing pipeline, not a rewrite:

- the `load_and_clean` stages (`ingest/loaders.py`)
- the parsers (`ingest/parsing.py`)
- the entry-error checks (`ingest/outliers.py`)
- pricing (`ingest/pricing.py`)

It runs once, on the newest snapshot. The history adds order keys, the stale-override
check's dates, and the milestones. #84 first re-ran the cleaning as of each Monday for
a "reported by date" series; #99 replaced that with one pass and event dates.

## Order identity

- **Key:** the lowercased username when that user has one order, otherwise
  `username#n`, with `n` assigned in order of first appearance.
- **Matching across snapshots:** rows under the same username are matched by best
  field agreement (order date, reservation date, configuration), not by position. A
  deleted duplicate can't shift its siblings, as the deletion did to `#`.
- **Spelling variants** (the `FL5guy` case) fall out of the lowercasing. The existing
  fuzzy-duplicate QA check keeps flagging near-misses.

This settles how a correction targets an order:

- **`username`** keeps working unchanged for the large majority of users, who have
  one order.
- **`username#n`** is accepted when a user holds several. Today an override on such a
  user lands on their latest row and only warns (`_apply_overrides`).

## Sanitization over time

These are new cross-snapshot checks. Each is listed in the data-quality panel, and
none is auto-corrected (the same policy as `ingest/outliers.py`):

- **Changed VINs:** a VIN changed after being set (17 historic cases).
- **Changed order dates:** an order date changed after submission.
- **Backward estimates:** a firm date reverted to a vague one, and is still vague.
  ("Moved earlier after it had passed" was tried in #83 and dropped: on this data it
  only found people recording the earlier day they actually took delivery.)
- **Vanished rows:** a row disappeared from the sheet. That is a silent cancellation,
  or a candidate for curation.
- **Stale curation:**
  - **Redundant:** the sheet now says what the override says, so the entry can be
    removed.
  - **Possibly outdated:** the sheet changed after the override's `as_of`.
  - **Unapplied deletion:** a deletion's target is still in the sheet.

## Curation file v2

The sections stay as they are (`overrides`, `additions`, `deletions`, `verified`).
Each entry gains:

```yaml
overrides:
  SomeUser:                    # illustrative entry
    source: https://www.rivianforums.com/forum/posts/<id>/   # required
    as_of: 2026-09-14          # effective date: when the information was posted
    reason: "posted a firm date in the forum"
    delivery_raw: "9/30/2026"
```

- **`source`** is required. A missing source is a QA warning for existing entries and
  fatal for new ones.
- **`as_of`** is when we learned it: the post, or the curation date. It anchors the
  stale-override check. It defaults to the date git first added the entry.
- **`checked`** (#99, optional) is a later date on which someone re-checked the
  override against the sheet. Sheet changes before it no longer count as stale.
- **`dates`** (#99, optional) holds milestone dates for the order's final values,
  `vin_assigned` and `delivery_scheduled`, from a post that says when they
  happened. An entry may carry only `dates`, to date values the sheet already has;
  it then needs a `source` but no `as_of`, since it overrides nothing.
  A date that can't fit is listed in the data-quality panel and not used: in the
  future, before the order, after the sheet already showed the value, or a
  scheduling date after the delivery.
- **Migration:** a one-time migration script lifts the URL comments into `source:`
  and backfills `as_of` from git. Entries it can't resolve are left for hand review,
  not guessed.

## Data contract for presentation

This is the hand-off to #66 and #51. Alongside the rows, the pipeline publishes
**dimension metadata**, so the page no longer hard-codes per-chart conventions:

- **Ordering and labels:** each dimension's label and its category order (today
  scattered across `palette.yaml` and `charts.py`; now one file, `dimensions.yaml`,
  published as-is).
- **Missing values:** the bucket each dimension uses for them ("Unknown",
  "No state data").
- **Thresholds and caveats:** the small-n threshold, and caveat text (state
  averages, inferred deliveries), so caveats compose instead of being per-chart prose.
- **Colors:** a color *by category name*, while CSS owns the actual value (the
  approach recorded in #66).

The published set:

- **The current cleaned rows**, as today's `r2_orders_clean.csv`.
- **An event-dated daily time series (#99)**, cumulative counts of what was true by
  each date:
  - orders, by order date
  - final VINs assigned, by `vin_assigned`
  - final delivery dates set, by `delivery_scheduled`
  - inferred deliveries, by delivery date
  - outstanding reservations, by reservation date
  - reservation → order conversions, by order date

  Undated items are counted beside the series, not placed on it. Anything already
  in the first snapshot is counted on that date (`history_start`, with its count in
  `on_history_start`). Estimate firmness isn't included: it is a state, with no
  event date.

Whether #51 uses a pre-aggregated cube or row-level aggregation in the browser is a
presentation decision, made in that stage.

## Storage

- **Default: rebuild from `data/raw/` on every run.** Replay reads raw fields only
  (CSV parsing), which is cheap; the expensive cleaning is bounded as described above.
- **Benchmark first.** Stage 1 measures replay time. If it's too slow, the event log
  becomes a **gitignored build cache** first. A committed store is considered only
  after that.
- **Repo growth:** see *Snapshot storage* below. Git stores the snapshots as
  deltas, so the repository itself stays small. The costs that grow are the
  working tree and the replay time.

### Snapshot storage (long term)

Decision record, discussed in #89. **Decision (2026-10-03): keep today's format, a
timestamped snapshot per change, and revisit when a trigger below fires.**

Measured 2026-10-03:

- **Working tree:** `data/raw` holds 29 MB on disk across 226 order and 83
  reservation snapshots.
- **Git's own storage:** a fresh bare clone of the whole repo, every snapshot
  included, takes **under 1 MB** of objects. Consecutive snapshots are nearly
  identical, and git stores them as deltas.
- **Actual change:** the line-level difference between consecutive order snapshots
  totals 254 KB, against 16.9 MB of raw files.
- **Replay time:** about 1.5 s per sheet (stage 1), growing linearly.

The options weighed:

| | Option | Why / why not |
|---|---|---|
| ✓ | **Timestamped snapshots, written only on change** (today) | Unique filenames, so no merge conflicts: the scheduled deploy, local builds and `./curate` can all add caches at once. Two copies of one change become a no-op snapshot, which replay handles without generating events. Raw data stays plain files, independent of git operations. |
| ✗ | **One mirror file per sheet, with git history as the log** | Every concurrent writer edits one file, so merge conflicts. Replay needs full history (`fetch-depth: 0`). A squash, rebase or history rewrite silently loses snapshots, and commit time stands in for fetch time. It saves almost nothing, since git already deltas the snapshots. |
| ✗ | **Journaled database** | A binary SQLite file in git neither deltas nor merges. A text journal is the event log stage 1 already derives: committing it adds a second source of truth, and appends to one file conflict. It could make sense outside git, but that adds hosting. |

Known weakness of the chosen format: a value's time window runs back to the
previous *changed* snapshot (7 h median, 121 h max), not to the last check that
found no change. Day-level timing is enough for everything planned so far.

Triggers to revisit, with the change each one points to:

- **Working tree:** `data/raw` passes about 250 MB, or CI checkout time becomes
  noticeable. Pack each closed month's snapshots into one compressed archive that
  replay reads. Only one writer touches a closed month, so this can't conflict.
- **Replay time:** replay takes more than about 10 s. Add a gitignored event-log
  cache.
- **Timing precision:** a feature needs sub-day timing (#34, maybe). Record checks
  that found no change as one marker file per check
  (`data/raw/checks/<slug>_<ts>`), which is conflict-free. Deploy run times from
  the Actions API would miss local checks.
- **Coupling:** data and code coupling gets painful (syncing `main` into `dev/*`
  just for caches, ruleset friction). Move the snapshots to a `data` branch or a
  separate repo, at the cost of the pipeline checking out two refs.

## Stages

Each stage is one issue and one PR, in this order, tracked under **#80**. Each must
leave the dashboard's output unchanged apart from new QA findings.

1. **#81 Snapshot replay, order identity, event log.** Internal only.
   - *Acceptance:* the dashboard HTML and CSV are identical to `dev/data-layer`'s,
     apart from plotly's random div ids.
   - *Acceptance:* replay reproduces the survey (674 keys, 267 change events).
   - *Acceptance:* a replay benchmark is recorded.
2. **#82 Curation v2.** `source` / `as_of` / `reason`, the migration script,
   `username#n` targeting, and stale and redundant detection. Blocked by #81.
3. **#83 Timeline sanity checks** (the list above) in the data-quality panel. Blocked
   by #81 and #82.
4. **#84 Published data contract.** Dimension metadata, plus the aggregate time series
   as JSON. Blocked by #81; blocks #66 and #51.
5. **#99 Curation timing.** `checked`, milestone dates, and the event-dated series in
   place of #84's weekly replay. Settled before the cutover so `main` gets one clean
   data layer.
6. **#85 Consumers.** Sequenced after the presentation stage (blocked by #84, #99 and
   #66):
   - **#32** trends, from the aggregate series.
   - **#34** accuracy: compare the earliest quoted window with the final firm date.
     It runs internally and publishes only distributions.
   - **Reservation → order conversion.**

## Execution

All data-layer work happens on a long-lived branch, so `main` (which deploys to the
live site) never carries a partial data layer.

- **Integration branch:** `dev/data-layer`, cut from `main`.
- **Stage PRs:** each stage is developed on its own branch, `data-layer/<stage>`
  (`replay`, `curation`, `timeline-qa`, `contract`), and merged by PR into
  `dev/data-layer`. Previews and the static checks run on those PRs as usual.
- **Keeping up with `main`:** `main` keeps moving (cache refreshes every few hours,
  and curation through `./curate`). Merge `main` into `dev/data-layer` periodically,
  and before each stage PR. Merge rather than rebase, because the branch is shared.
- **Curation migration timing (#82):** `overrides.yaml` keeps changing on `main`, so
  the migration script runs on the latest file just before the final merge, or is
  re-run then. Don't hand-convert the file early, or it will conflict.
- **Into `main`:** once stages 1–5 (including #99) are done, `dev/data-layer` merges
  into `main` in one PR (#97). Its check is the same as each stage's: the output is
  unchanged apart from QA. That PR also publishes the data contract.
- **After the merge:** #85 is sequenced after the presentation work. It is planned
  with that stage and is not part of the `dev/data-layer` merge.

After this, presentation (#66, with #29 and #30) and then the UI nits (#41, #46) get
their own planning stage.
