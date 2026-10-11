// Time grains for the weekly charts: a week, or whole weeks grouped into months
// or quarters, so a long span still draws columns wide enough to read. A week
// belongs to the month (or quarter) holding its Thursday, the ISO rule, so a
// group is always whole Monday weeks: the charts' counts are weekly, and
// splitting a week across two months would invent a precision they don't have.
// A group's heading says which weeks it spans.
//
// Pure: dates are UTC midnights, as the charts' ISO dates parse.

const DAY = 864e5;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const GRAINS = [
  { key: "week", label: "Week", every: "Weekly" },
  { key: "month", label: "Month", every: "Monthly" },
  { key: "quarter", label: "Quarter", every: "Quarterly" },
];
// A grain is offered when it makes at least this many groups, and picked by
// default when its columns are at least this many pixels wide.
export const MIN_GROUPS = 4;
export const MIN_PX = 6;

const monday = (d) => new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * DAY);
// The Monday whose Thursday is the first in a month: where that month's weeks start.
function firstWeek(y, mo) {
  const first = new Date(Date.UTC(y, mo, 1));
  return new Date(first.getTime() + (((4 - first.getUTCDay() + 7) % 7) - 3) * DAY);
}

// The group a date falls in: {key, start, end}, `end` the Monday after its last
// week.
export function groupOf(d, grain) {
  const mon = monday(d);
  if (grain === "week") {
    return { key: mon.toISOString().slice(0, 10), start: mon, end: new Date(mon.getTime() + 7 * DAY) };
  }
  const thu = new Date(mon.getTime() + 3 * DAY);
  const step = grain === "quarter" ? 3 : 1;
  const y = thu.getUTCFullYear(), mo = thu.getUTCMonth() - (thu.getUTCMonth() % step);
  return { key: `${y}-${String(mo + 1).padStart(2, "0")}`, start: firstWeek(y, mo), end: firstWeek(y, mo + step) };
}

const short = (d) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
const long = (d) => `${short(d)}, ${d.getUTCFullYear()}`;

// A group's tooltip heading, from its first and last week (Mondays). `sofar`
// marks the group the current week is in.
export function heading(grain, first, last, sofar = false) {
  if (grain === "week") return `Week of ${long(first)}${sofar ? " (so far)" : ""}`;
  // Named by the month (or quarter) its first week's Thursday is in.
  const thu = new Date(first.getTime() + 3 * DAY);
  const name = grain === "quarter" ? `Q${Math.floor(thu.getUTCMonth() / 3) + 1} ${thu.getUTCFullYear()}`
    : `${MONTHS[thu.getUTCMonth()]} ${thu.getUTCFullYear()}`;
  const weeks = first.getTime() === last.getTime() ? `week of ${short(first)}`
    : `weeks of ${short(first)} – ${short(last)}`;
  return `${name} (${weeks}${sofar ? ", so far" : ""})`;
}

// How many groups `grain` makes over [lo, hi).
export function count(lo, hi, grain) {
  let n = 0;
  for (let d = lo; d < hi; d = groupOf(d, grain).end) n++;
  return n;
}

// The grains worth offering over [lo, hi): the week, and each coarser one that
// still makes MIN_GROUPS groups.
export function offered(lo, hi) {
  return GRAINS.filter((g, i) => !i || count(lo, hi, g.key) >= MIN_GROUPS).map((g) => g.key);
}

// The default: the finest offered grain whose columns are MIN_PX wide across
// `px` pixels, else the coarsest.
export function pick(lo, hi, px, grains = offered(lo, hi)) {
  return grains.find((g) => px / count(lo, hi, g) >= MIN_PX) || grains.at(-1);
}
