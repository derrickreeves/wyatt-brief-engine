# -*- coding: utf-8 -*-
"""Owners and reporting accountability (added 2026-10-15, Wyatt's ask via Derrick).

Scorecard Mapping (the registry) is the source of truth for goals AND owners. Every owner cell on
every card resolves from M["registry_goals"][div][kpi]["owners"]; the literal a caller passes is only
the fallback for a row the registry has no match for (or a registry pull saved without the Owner
field). Randall edits an owner in the registry, the next morning's PDF follows. Nobody edits code.

Reporting: a daily-form table says who was expected to file (the registry owners of its rows), who
did (the form's submitter field) and who did not. Names, never "Team".
"""
from datetime import timedelta

OWNER_FIELD = "fld8YYVod7alaGHl6"   # Scorecard Mapping · Owner Name (lookup on the People link)


def norm_owners(v):
    """Owner Name arrives in three shapes: REST ['Danielle Story', ...]; the MCP lookup dict
    {'valuesByLinkedRecordId': {...}}; or linked-record dicts [{'id','name'}]. Return clean names."""
    if not v:
        return []
    if isinstance(v, dict):
        out = []
        for x in (v.get("valuesByLinkedRecordId") or {}).values():
            out += [str(y) for y in (x if isinstance(x, list) else [x])]
        return [o.strip() for o in out if o and o.strip()]
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    out = []
    for x in v:
        if isinstance(x, dict):
            x = x.get("name") or x.get("id")
        if x and str(x).strip():
            out.append(str(x).strip())
    return out


def first(name):
    n = (name or "").strip()
    return n.split()[0] if n else n


def same_person(a, b):
    """'Laurie' matches 'Laurie Rush'. First-name match, case-insensitive (the form selects carry first names)."""
    return first(a).lower() == first(b).lower()


def label(owners, fb="-", max_names=2):
    """Owner cell text: one or two first names; more than that reads 'Team (N)' and the reporting
    line under the table names every one of them."""
    if not owners:
        return fb
    if len(owners) <= max_names:
        return "/".join(first(o) for o in owners)
    return "Team (%d)" % len(owners)


def names(owners, fb="-"):
    """Full first-name list for section sub-lines and flags: 'Danielle, Laurie, Tommy, Gabby, Diana'."""
    return ", ".join(first(o) for o in owners) if owners else fb


def biz_days_back(as_of, n=5):
    out, d = [], as_of
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def reporting(submits, expected, as_of, n=5):
    """submits: {submitter name: set(ISO dates)} read from the form table; expected: registry owners.
    'Yesterday' is as_of (the brief is as-of the prior day). Weekends never produce a missed list."""
    days = biz_days_back(as_of, n)
    dayset = {d.isoformat() for d in days}
    weekend = as_of.weekday() >= 5

    def find(name):
        for k in submits:
            if same_person(k, name):
                return k
        return None

    tally, missed = [], []
    for e in expected:
        k = find(e)
        ds = submits.get(k, set()) if k else set()
        filed = len(ds & dayset)
        last = max(ds) if ds else None
        tally.append(dict(name=e, filed=filed, n=n, last=last, on_form=k is not None))
        if not weekend and as_of.isoformat() not in ds:
            missed.append(e)
    extra = [k for k in submits if k != "(unnamed)" and not any(same_person(k, e) for e in expected)]
    return dict(expected=list(expected), tally=tally, missed_yest=missed, weekend=weekend, extra=extra,
                window="%s-%s" % (_md(days[-1].isoformat()), _md(days[0].isoformat())))


def tally_text(rep):
    parts = []
    for t in rep["tally"]:
        s = "%s %d/%d" % (first(t["name"]), t["filed"], t["n"])
        if not t["on_form"]:
            s += " (never filed)"
        elif t["filed"] == 0 and t["last"]:
            s += " (last %s)" % _md(t["last"])
        parts.append(s)
    if rep.get("extra"):
        parts.append("filed but not an owner in Scorecard Mapping: " + ", ".join(first(x) for x in rep["extra"]))
    return " · ".join(parts)


def submits_from(cells, date_field, who_field):
    """{submitter first name: set(ISO dates)} from form rows. Rows with no submitter value are
    grouped under '(unnamed)' so an old form without the field still shows activity."""
    out = {}
    for c in cells:
        d = c.get(date_field)
        if not d:
            continue
        w = c.get(who_field)
        if isinstance(w, dict):
            w = w.get("name")
        w = (w or "(unnamed)").strip()
        out.setdefault(w, set()).add(str(d)[:10])
    return out


def _md(iso):
    try:
        return "%d/%d" % (int(iso[5:7]), int(iso[8:10]))
    except Exception:
        return iso
