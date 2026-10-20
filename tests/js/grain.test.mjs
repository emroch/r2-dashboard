// Time grains (lib/grain.js): whole Monday weeks grouped by their Thursday's
// month or quarter, the grains worth offering over a span, and the default.
import assert from "node:assert/strict";
import { test } from "node:test";

import { count, groupOf, heading, offered, pick } from "../../src/web/lib/grain.js";

const d = (iso) => new Date(`${iso}T00:00:00Z`);
const iso = (x) => x.toISOString().slice(0, 10);

test("a week goes to the month its Thursday is in, and a group is whole weeks", () => {
  // Mon Jun 29 2026: its Thursday is Jul 2, so it's July's first week.
  assert.equal(groupOf(d("2026-06-29"), "month").key, "2026-07");
  assert.equal(
    groupOf(d("2026-07-02"), "month").key,
    "2026-07",
    "any day of the week, its Monday's group",
  );
  // Mon Jun 22: Thursday Jun 25, June.
  const jun = groupOf(d("2026-06-22"), "month");
  assert.deepEqual(
    [jun.key, iso(jun.start), iso(jun.end)],
    ["2026-06", "2026-06-01", "2026-06-29"],
  );
  const q = groupOf(d("2026-09-28"), "quarter"); // Thursday Oct 1: Q4
  assert.deepEqual([q.key, iso(q.start), iso(q.end)], ["2026-10", "2026-09-28", "2027-01-04"]);
  assert.equal(iso(groupOf(d("2027-01-06"), "quarter").end), "2027-03-29", "a year rolls over");
  const w = groupOf(d("2026-10-08"), "week");
  assert.deepEqual([iso(w.start), iso(w.end)], ["2026-10-05", "2026-10-12"]);
});

test("a group's heading names it and the weeks it spans", () => {
  assert.equal(
    heading("week", d("2026-10-05"), d("2026-10-05"), true),
    "Week of Oct 5, 2026 (so far)",
  );
  assert.equal(
    heading("month", d("2026-06-01"), d("2026-06-22")),
    "Jun 2026 (weeks of Jun 1 – Jun 22)",
  );
  assert.equal(
    heading("month", d("2026-06-29"), d("2026-06-29"), true),
    "Jul 2026 (week of Jun 29, so far)",
  );
  assert.equal(
    heading("quarter", d("2026-09-28"), d("2026-10-05"), true),
    "Q4 2026 (weeks of Sep 28 – Oct 5, so far)",
  );
});

test("coarser grains are offered when they make four groups; the default reads at the width", () => {
  const lo = d("2024-03-04"),
    hi = d("2026-10-12"); // 136 weeks
  assert.equal(count(lo, hi, "week"), 136);
  assert.deepEqual(offered(lo, hi), ["week", "month", "quarter"]);
  assert.equal(pick(lo, hi, 900), "week", "6.6 px a week");
  assert.equal(pick(lo, hi, 270), "month", "a phone: 2 px a week, 8 a month");
  assert.equal(pick(lo, hi, 60), "quarter", "too narrow for anything: the coarsest");
  const short = [d("2026-06-08"), d("2026-10-12")]; // 18 weeks: 5 months, 2 quarters
  assert.deepEqual(offered(...short), ["week", "month"]);
  assert.deepEqual(offered(d("2026-07-06"), d("2026-08-03")), ["week"]);
});
