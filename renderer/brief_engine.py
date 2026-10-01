# -*- coding: utf-8 -*-
"""Wyatt Daily Brief ENGINE — deterministic compute core.

Design: locked structure + computed data.
- The nightly agent pulls each source once and saves the raw JSON to a known path.
- This engine reads those saved pulls + a config, computes every window and
  status the same way every night, assembles the render payload from per-division
  builder functions (structure lives in code, so tables can never silently drop),
  and hands off to render_brief.py.
- No MCP, no credentials, no hand math. Adding a division = register its source
  files + write one builder function.

This file is the shared spine (dates, windows, status, generic table math).
Division builders and the orchestrator import from here.
"""
import json, math
from datetime import date, timedelta

# ----------------------------------------------------------------------------
# 1. DATES & WINDOWS  (America/Chicago; week starts Monday)
# ----------------------------------------------------------------------------
def windows(as_of: date):
    """Return the four reporting windows as (start, end) inclusive date pairs."""
    monday = as_of - timedelta(days=as_of.weekday())          # this week's Monday
    mtd_start = as_of.replace(day=1)
    last_end = mtd_start - timedelta(days=1)                   # last day of prior month
    last_start = last_end.replace(day=1)
    return {
        "Yest":   (as_of, as_of),
        "WTD":    (monday, as_of),
        "MTD":    (mtd_start, as_of),
        "LastMo": (last_start, last_end),
    }

def biz_days(a: date, b: date):
    """Weekdays (Mon-Fri) between a and b inclusive."""
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def month_biz_progress(as_of: date):
    """(business days elapsed this month through as_of, total business days in month)."""
    first = as_of.replace(day=1)
    # last day of month
    nxt = (as_of.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = nxt - timedelta(days=1)
    return biz_days(first, as_of), biz_days(first, last)

# ----------------------------------------------------------------------------
# 2. STATUS  (on / off the goal's pace for this point in the month)
# ----------------------------------------------------------------------------
def status(mtd, goal, cadence, as_of, direction="up", confirmed=True):
    """cadence: 'day', 'week', 'mo' (or 'overview'/None). direction: 'up' (higher better)
       or 'down' (ceiling). Returns a render cell [text, color, bold].
       Goals now come live from the registry (Scorecard Mapping), so a blank/None goal
       renders no pace status."""
    if not confirmed or goal in (None, ""):
        return ["--", "light", False]
    elapsed, total = month_biz_progress(as_of)
    if direction == "down":
        # ceiling metric (churn, evictions): at or under the cap is on track
        return ["On track", "green", False] if mtd <= goal else ["Off track", "amber", False]
    if goal == 0:
        return ["--", "light", False]
    if cadence == "day":
        target = goal * total                 # daily goal -> monthly target (business days)
    elif cadence == "week":
        target = goal * (total / 5.0)          # weekly goal -> monthly target (~business weeks)
    else:
        target = goal                          # monthly goal as-is
    expected = target * elapsed / total
    return ["On track", "green", False] if mtd >= math.floor(expected) else ["Off track", "amber", False]

# ----------------------------------------------------------------------------
# 3. GENERIC TABLE MATH  — count/sum a KPI over the four windows from a saved pull
# ----------------------------------------------------------------------------
def _load(path):
    return json.load(open(path))["records"]

def _name(v):
    if isinstance(v, dict):
        return v.get("name")
    if isinstance(v, list):
        return _name(v[0]) if v else None
    return v

def in_win(d, a, b):
    return d is not None and a.isoformat() <= d <= b.isoformat()

def window_count(records, date_field, as_of, match=None):
    """Count rows (optionally where match(cell)==True) in each window. Returns dict."""
    w = windows(as_of)
    out = {}
    for label, (a, b) in w.items():
        n = 0
        for r in records:
            c = r["cellValuesByFieldId"]
            if match and not match(c):
                continue
            if in_win(c.get(date_field), a, b):
                n += 1
        out[label] = n
    return out

def window_sum(records, date_field, value_field, as_of, match=None):
    w = windows(as_of)
    out = {}
    for label, (a, b) in w.items():
        s = 0
        for r in records:
            c = r["cellValuesByFieldId"]
            if match and not match(c):
                continue
            if in_win(c.get(date_field), a, b):
                s += (c.get(value_field) or 0)
        out[label] = s
    return out

def entry_type_match(field_id, wanted_name):
    return lambda c: _name(c.get(field_id)) == wanted_name

# ----------------------------------------------------------------------------
# 4. AD (Windsor) AGGREGATION — spend/leads/impr/clicks over windows + since-launch
# ----------------------------------------------------------------------------
def ad_windows(rows, as_of, launch=None):
    """rows: list of dicts with date/spend/actions_lead/impressions/clicks (Windsor).
       Returns per-window aggregates plus 'SinceLaunch' if launch given."""
    w = windows(as_of)
    def agg(sel):
        sp = sum(r.get("spend", 0) for r in sel)
        ld = sum(r.get("actions_lead", 0) for r in sel)
        im = sum(r.get("impressions", 0) for r in sel)
        cl = sum(r.get("clicks", 0) for r in sel)
        cpl = round(sp / ld, 2) if ld else None
        return dict(spend=round(sp, 2), leads=ld, impr=im, clicks=cl, cpl=cpl)
    res = {}
    for label, (a, b) in w.items():
        res[label] = agg([r for r in rows if a.isoformat() <= r["date"] <= b.isoformat()])
    if launch:
        res["SinceLaunch"] = agg([r for r in rows if r["date"] >= launch])
    return res

# ----------------------------------------------------------------------------
# self-test hook (run: python3 brief_engine.py <as_of>)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    ao = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 8, 11)
    print("as_of:", ao)
    print("windows:", {k: (a.isoformat(), b.isoformat()) for k, (a, b) in windows(ao).items()})
    print("month biz progress:", month_biz_progress(ao))
