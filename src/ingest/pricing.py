"""Configured-vehicle pricing: turn a cleaned order's configuration into a price.

Sums the trim base, drive system, package, paint, wheels, interior, and add-ons
from conf/pricing.yaml. DELIBERATELY EXCLUDES destination, doc fees, taxes, and
incentives — this is the configured vehicle price only (issue #11).

Two things the caller gets back besides the total:

* a per-category breakdown, so the dashboard can show where the average dollar
  goes without recomputing anything, and
* configuration issues — options the sheet claims that aren't offered on that
  trim. Those are reported for review, not corrected: the order is still priced
  (best effort) and stays in the price statistics, matching how the rest of the
  pipeline surfaces suspect data instead of dropping it.

A price of None anywhere it's needed makes the whole total None ("unknown
price"), which the dashboard reports as its own bucket.
"""
from config import (PRICE_DRIVE_SYSTEMS, PRICE_INTERIORS, PRICE_OPTIONS,
                     PRICE_PACKAGES, PRICE_PAINTS, PRICE_TRIM_ALIASES,
                     PRICE_TRIMS, OPTED_IN_TOKENS, SPARE_TOKENS)

# The breakdown columns, in the order the price builds up. Kept as one list so
# the loader, the CSV, and the chart all agree on the set.
PRICE_PARTS = ("price_base", "price_drive", "price_package", "price_paint",
               "price_wheels", "price_interior", "price_spare",
               "price_autonomy_tow")


def _norm(s):
    """Collapse whitespace and case for tolerant catalog lookups. Keys still have
    to match the sheet's spelling — this only forgives case and stray spaces."""
    return " ".join(str(s or "").split()).casefold()


def _table(d):
    return {_norm(k): v for k, v in (d or {}).items()}


_PAINTS = _table(PRICE_PAINTS)
_INTERIORS = _table(PRICE_INTERIORS)
_DRIVES = _table(PRICE_DRIVE_SYSTEMS)
_TRIMS = _table(PRICE_TRIMS)
_ALIASES = _table(PRICE_TRIM_ALIASES)
# Fallback wheel prices for a wheel quoted on a trim that doesn't offer it: the
# upcharge from the first trim that does. Only used for flagged bad combos, so
# the order can still be priced instead of silently leaving the statistics.
_WHEEL_FALLBACK = {}
for _t in PRICE_TRIMS.values():
    for _w, _v in (_t.get("wheels") or {}).items():
        _WHEEL_FALLBACK.setdefault(_norm(_w), _v)


def resolve_trim(trim_raw):
    """Sheet trim label -> (display name, trim dict, drive system name or None).

    Aliases decompose combined labels ("Standard RWD LR") into a trim plus its
    drive system. Matching is exact (after case/space normalization), never by
    prefix: "Standard RWD" is a prefix of "Standard RWD LR", and prefix matching
    would price the long-range car $3,500 short. Returns (None, None, None) for
    an unknown trim.
    """
    key = _norm(trim_raw)
    drive = None
    alias = _ALIASES.get(key)
    if alias:
        drive = alias.get("drive_system")
        key = _norm(alias.get("trim"))
    trim = _TRIMS.get(key)
    if trim is None:
        return (None, None, None)
    name = next(k for k in PRICE_TRIMS if _norm(k) == key)
    return (name, trim, drive)


def _offered_paints(trim, drive, package):
    """Paints available on this exact configuration: the trim's base list plus
    anything its drive system or package unlocks (Launch Green, say)."""
    out = {_norm(p) for p in (trim.get("paints") or [])}
    if drive:
        out |= {_norm(p) for p in (trim.get("paints_by_drive") or {}).get(drive, [])}
    if package:
        out |= {_norm(p)
                for p in (trim.get("paints_by_package") or {}).get(package, [])}
    return out


def price_order(trim="", launch="", color="", interior="", wheels="",
                autonomy="", tow="", spare=""):
    """Price one order's configuration.

    Returns (parts, issues): `parts` holds every PRICE_PARTS component plus
    "price" (the total, or None if any needed price is unknown) and
    "price_trim"/"price_drive_system" for grouping; `issues` is a list of
    human-readable configuration problems for the data-quality panel.
    """
    parts = {k: 0 for k in PRICE_PARTS}
    parts.update(price=None, price_trim=None, price_drive_system=None)
    issues, unknown = [], False

    name, t, drive = resolve_trim(trim)
    if t is None:
        return parts, (["unknown trim %r — not in pricing.yaml" % trim]
                       if str(trim).strip() else [])
    parts["price_trim"], parts["price_drive_system"] = name, drive
    parts["price_base"] = t.get("base")
    if parts["price_base"] is None:
        unknown = True

    # Drive system: only some trims offer a choice, and the sheet encodes it in
    # the trim label (see resolve_trim), so an unlisted drive is a config error.
    if drive:
        if drive not in (t.get("drive_systems") or []):
            issues.append("%s not offered on %s" % (drive, name))
        parts["price_drive"] = _DRIVES.get(_norm(drive))
        if parts["price_drive"] is None:
            unknown = True

    # Package: the "Launch Package" column is the authority for whether it
    # applies — the Autonomy+/Tow columns say "Included" OR "Yes" for the same
    # thing, so they can't be used to detect bundling.
    package = None
    if _norm(launch) in OPTED_IN_TOKENS and "launch" in (t.get("packages") or []):
        package = "launch"
        parts["price_package"] = (PRICE_PACKAGES.get("launch") or {}).get("price")
        if parts["price_package"] is None:
            unknown = True
    included = set((PRICE_PACKAGES.get(package) or {}).get("includes") or [])

    if str(color).strip():
        parts["price_paint"] = _PAINTS.get(_norm(color))
        if parts["price_paint"] is None:
            unknown = True
            issues.append("no price for paint %r" % color)
        elif _norm(color) not in _offered_paints(t, drive, package):
            issues.append("%s paint not offered on %s" % (color, name))

    # Wheels are priced per trim, so an unlisted wheel has no price of its own;
    # fall back to another trim's upcharge so the order still gets a total.
    if str(wheels).strip():
        wmap = _table(t.get("wheels"))
        if _norm(wheels) in wmap:
            parts["price_wheels"] = wmap[_norm(wheels)]
        else:
            parts["price_wheels"] = _WHEEL_FALLBACK.get(_norm(wheels))
            if parts["price_wheels"] is None:
                unknown = True
                issues.append("no price for wheels %r" % wheels)
            else:
                issues.append("%s not offered on %s (priced from another trim)"
                              % (wheels, name))
        if parts["price_wheels"] is None:
            unknown = True

    if str(interior).strip():
        parts["price_interior"] = _INTERIORS.get(_norm(interior))
        if parts["price_interior"] is None:
            unknown = True
            issues.append("no price for interior %r" % interior)
        elif _norm(interior) not in {_norm(i) for i in (t.get("interiors") or [])}:
            issues.append("%s not offered on %s" % (interior, name))

    if _norm(spare) in SPARE_TOKENS:
        parts["price_spare"] = PRICE_OPTIONS.get("spare")
        if parts["price_spare"] is None:
            unknown = True

    # Autonomy+ / Tow: charged only when no package already includes them.
    extra = 0
    for field, val in (("autonomy", autonomy), ("tow", tow)):
        if _norm(val) in OPTED_IN_TOKENS and field not in included:
            price = PRICE_OPTIONS.get(field)
            if price is None:
                unknown = True
            else:
                extra += price
    parts["price_autonomy_tow"] = extra

    if not unknown:
        parts["price"] = sum(parts[k] or 0 for k in PRICE_PARTS)
    return parts, issues
