# -*- coding: utf-8 -*-
"""Locked layout, fed by computed data.  build(M, as_of) -> render payload dict.

Structure lives here in code, so a table can never silently drop. Every number
comes from the computed M dict (see build_brief.py). Status is computed by the
engine. Goals + cadence are pulled LIVE from the registry (Scorecard Mapping) each
run via M["registry_goals"] and resolved per row by _rg(); a hardcoded literal is
kept as a fallback only for rows the registry has no match for. Randall edits the
registry, the report follows the next morning.
"""
from brief_engine import status as _status

# Ascend member list replaces the prospect contact table (Derrick 2026-09-21). False until he approves the look;
# ASCEND_MEMBER_LIST=1 in the environment forces it on for a test render.
import os as _os
ASCEND_MEMBER_LIST_LIVE = True  # live per Derrick 2026-09-21; set False to fall back to the prospect table

def A(t, c="ink", b=False): return [t, c, b]
def money(x): return "$%s" % format(int(round(x)), ",") if x is not None else "-"
def cpl(x): return "$%.2f" % x if x else "n/a"
def num(x): return format(int(round(x)), ",")

def st(mtd, goal, cad, as_of, direction="up", confirmed=True):
    return _status(mtd, goal, cad, as_of, direction, confirmed)

def W(w, k): return w.get(k, 0)

# ---- registry-driven goals (Scorecard Mapping is the source of truth; Randall edits, report follows) ----
_UNIT = {"day": "day", "week": "wk", "mo": "mo", "overview": "mo"}
# report row label -> registry KPI name(s). ("sum",[...]) sums several registry rows;
# a list tries each spelling in order (first match wins); a string is a single lookup.
# A label with no entry here looks itself up in the registry verbatim.
_ALIAS = {
    "kcm": {
        "Construction Loans Approved": "New Construction Loans",
        "Showings (buyer + listing)": ("sum", ["Buyer Showings", "Showings on Listing"]),
    },
    "ascend": {
        "New Leads": "New Lead",
        "Mastermind RSVPs (Non-Member)": "Mastermind RSVP's (Non-Member)",
        "Mastermind RSVPs (Member)": "Mastermind RSVP's (Member)",
        "Shared Event RSVP (Breakfast)": "Shared Event RSVP - Breakfast",
        "Churned Members": "Churned Members (events)",
    },
    "cowork": {
        "Free Tours Booked": "Free Tours",
        "Verbal Commitments": "Verbal Commits",
        "Event Revenue": "Events Booked Revenue",
        "Day Passes": "Day Pass",
    },
    "rentals": {},
    "fundamentals": {
        "Churn (withdrawals)": "Churned",
        "Terminations": "Terminated Employees",
        "Added to Waitlist": "Added to the Waitlist",
    },
}

def _rg(M, div, label, fb_goal, fb_cad):
    """Resolve (goal, cadence, found) from the live registry pull, keyed by division + label.
    Falls back to the passed literal only when the registry has NO matching row (a row that
    exists with a blank goal returns goal=None, so the report shows '-' and no pace status)."""
    reg = M.get("registry_goals", {}).get(div, {})
    spec = _ALIAS.get(div, {}).get(label, label)
    def look(name): return reg.get(str(name).strip().lower())
    if isinstance(spec, tuple) and spec and spec[0] == "sum":
        rows = [x for x in (look(n) for n in spec[1]) if x is not None]
        if rows:
            return sum((x["goal"] or 0) for x in rows), rows[0]["cad"], True
        return fb_goal, fb_cad, False
    for name in (spec if isinstance(spec, list) else [spec]):
        row = look(name)
        if row is not None:
            return row["goal"], row["cad"], True
    return fb_goal, fb_cad, False

def _gnum(M, div, name):
    """Plain goal number for ad/organic rows (no pace math). None if absent or blank."""
    row = M.get("registry_goals", {}).get(div, {}).get(str(name).strip().lower())
    if row and row["goal"] not in (None, ""):
        return row["goal"]
    return None

import accountability as ACC

# ---- registry-driven OWNERS (Scorecard Mapping is the source of truth for owners too; 2026-10-15) ----
def _owners(M, div, label):
    """Owner names for a report row, from the live registry pull. Same alias map as goals. A ("sum", [...])
    spec unions the owners of every summed row. Empty when the registry has no match or the pull was
    saved without the Owner field, in which case the caller's literal is the fallback."""
    reg = M.get("registry_goals", {}).get(div, {})
    spec = _ALIAS.get(div, {}).get(label, label)
    union = isinstance(spec, tuple)
    names = spec[1] if union else (spec if isinstance(spec, list) else [spec])
    out = []
    for n in names:
        row = reg.get(str(n).strip().lower())
        if row is None:
            continue
        for o in row.get("owners") or []:
            if o not in out:
                out.append(o)
        if not union:
            break
    return out

def _own(M, div, label, fb):
    return ACC.label(_owners(M, div, label), fb)

def _expected(M, div, labels, fb):
    """Who is expected to file a division's daily form = the registry owners across its form rows."""
    out = []
    for lb in labels:
        for o in _owners(M, div, lb):
            if o not in out:
                out.append(o)
    return out or list(fb)

def _report_block(what, rep):
    """The accountability line under a daily-forms table."""
    return {"kind": "report", "what": what, "missed": [ACC.first(x) for x in rep["missed_yest"]],
            "weekend": rep["weekend"], "tally": ACC.tally_text(rep), "window": rep["window"]}

def _att(who, where, ask):
    """One ask for one person. The cover groups these by person: 'who do I need to talk to today, and why'."""
    return {"who": who, "where": where, "ask": ask}

def _attention_missed(div_name, rep, form_name):
    """One entry per person who did not file yesterday, in plain words."""
    if rep["weekend"] or not rep["missed_yest"]:
        return []
    out = []
    for t in rep["tally"]:
        if t["name"] not in rep["missed_yest"]:
            continue
        if not t["on_form"]:
            why = "has never filed it"
        elif t["last"]:
            why = "last filed %s" % ACC._md(t["last"])
        else:
            why = "not filed"
        out.append(_att(t["name"], form_name, "did not file yesterday (%s)" % why))
    return out

def _group_attention(items):
    """[{who, where, ask}] -> [[person, [line, ...]]], one block per person, asks merged per place.
    Order: people with the most asks first, then alphabetical."""
    by = {}
    for it in items:
        by.setdefault(it["who"], {}).setdefault(it["where"], []).append(it["ask"])
    out = []
    for who, places in by.items():
        lines = []
        for where, asks in places.items():
            lines.append("%s: %s." % (where, "; ".join(asks)))
        out.append([who, lines])
    out.sort(key=lambda x: (-sum(len(v) for v in by[x[0]].values()), ACC.first(x[0]).lower()))
    return out

def _goaltxt(goal, cad, money=False, event=False):
    if goal in (None, ""):
        return "-"
    if event:
        return "%d/event" % goal
    u = _UNIT.get(cad, "mo")
    if money:
        return "$%s/%s" % (format(int(round(goal)), ","), u)
    return "%d/%s" % (goal, u)

def build(M, as_of):
    def row_k(label, goal_txt, w, goal, cad, owner_or_status, as_of, direction="up", confirmed=True, mtd_cell=None):
        pass
    P = {
        "as_of_line": "As of %s   ·   Yest %s  ·  WTD %s-%s  ·  MTD %s-%s  ·  LastMo previous month"
                      % (as_of.strftime("%A, %B %-d, %Y"), as_of.strftime("%-m/%-d"),
                         _wk(as_of)[0], _wk(as_of)[1], as_of.replace(day=1).strftime("%-m/%-d"), as_of.strftime("%-m/%-d")),
        "as_of_short": as_of.strftime("%b %-d, %Y"),
        "brief_foot": "One card per division, pulled nightly from the team's records · owners and goals come from the Scorecard Mapping · Questions: reply to the Slack ping",
        # Fundamentals joins after Rentals in the locked order, gated by FELC_GO_LIVE_AS_OF in
        # build_brief (first five-card send targeted Fri 2026-09-04, as_of 9/03).
        "divisions": [_kcm(M, as_of), _ascend(M, as_of), _coworking(M, as_of), _rentals(M, as_of)]
                     + ([_fundamentals(M, as_of)] if "felc_ov" in M else [])
                     + ([_team(M, as_of)] if M.get("fub_loaded") else []),
    }
    # NEEDS ATTENTION on the cover (2026-10-15, Wyatt's ask): every gap in the brief carries a name.
    # Each division contributes its own items; the cover just lists them, non-reporters first.
    attention = []
    for d in P["divisions"]:
        attention += d.pop("attention", []) or []
    P["cover"] = _cover(M)
    P["cover"]["attention"] = _group_attention(attention)
    return P

def _wk(as_of):
    from datetime import timedelta
    mon = as_of - timedelta(days=as_of.weekday())
    return mon.strftime("%-m/%-d"), as_of.strftime("%-m/%-d")

# ---------------- cover ----------------
def _cover(M):
    ar = M["ascend_roster"]; cr = M["cowork_roster"]; ks = M["kcm_state"]; ro = M["rentals_ov"]; fo = M.get("felc_ov")
    felc_health = (" Fundamentals has %d children enrolled with %d families waiting." % (fo["enrolled_total"], fo["waitlist_active"])) if fo else ""
    felc_line = [["Fundamentals of Early Learning Center", "%d enrolled · %s booked weekly tuition · %d on the waitlist" % (fo["enrolled_total"], money(fo["weekly_rev"]), fo["waitlist_active"])]] if fo else []
    ta = M.get("team_act"); tp = M.get("team_pipe") or {}
    oa = M.get("office_act"); op = M.get("office_pipe") or {}
    team_line = [["Kaizen Home Sales & Services", "%d active agents · %d closings MTD · %d under contract · Kaizen Team detail inside" % (
        M.get("office_active_agents", 0), oa["Closings"]["MTD"], op.get("Under Contract", {}).get("n", 0))]] if M.get("fub_loaded") else []
    coming = ([] if fo else ["Fundamentals of Early Learning Center"]) + ([] if M.get("fub_loaded") else ["Kaizen Home Sales & Services"]) + ["Shared Events", "IMG", "Gobundance"]
    return {
        "title": "Wyatt Portfolio Daily Brief",
        "health": ("KCM has %d homes under construction (%d of them already listed) and %d active listings, with deal detail below. "
                   "Ascend holds %d paying members and its paid engine keeps improving. Coworking sits at %d members. "
                   "Rentals occupancy is %s%%.%s "
                   "Every number is pulled from the team's own records at 1:15 AM. When an entry is missing or out of date, "
                   "WHO TO TALK TO TODAY names the person who keeps that record."
                   % (ks["under_construction"], ks["uc_listed"], ks["active"], ar["members"], cr["members"]+cr["unpaid"],
                      _pct(ro["occ"]), felc_health)),
        "included": [
            ["Kaizen Construction Management", "%d under construction (%d of them listed) · %d listed total · deal economics below" % (ks["under_construction"], ks["uc_listed"], ks["active"])],
            ["Ascend Mastermind Community", "%d paying members, %s MRR · paid leads accelerating" % (ar["members"], money(ar["mrr"]))],
            ["Kaizen Coworking & Event Space", "%d members, %s MRR" % (cr["members"]+cr["unpaid"], money(cr["mrr"]))],
            ["Rentals", "%s%% occupancy across %d units" % (_pct(ro["occ"]), ro["units"] or 0)],
        ] + felc_line + team_line,
        "coming": coming,
        "note": "Divisions join as their cards are verified, in the locked portfolio order.",
    }

def _pct(x):
    return ("%.1f" % x) if isinstance(x, (int, float)) else "-"

# ---------------- KCM ----------------
def _kcm(M, ao):
    s = M["kcm_state"]; ev = M["kcm_events"]; f = M["kcm_forms"]
    lst, lt = M["kcm_listings"]; uc, ut = M["kcm_uc"]; cm, ct = M["kcm_coming"]; lenders = M["kcm_lenders"]
    pipe, pipe_need = M["kcm_pipeline"]
    profit_motion = lt + ut + ct
    def evrow(label, owner, fb_goal, key):
        g, cad, _ = _rg(M, "kcm", label, fb_goal, "mo")
        e = ev[key]; mtd = e["MTD"]
        met = g not in (None, "") and label == "Lots Funded" and mtd >= g
        mtd_cell = A("%d (met)" % mtd, "green", True) if met else str(mtd)
        status = st(mtd, g, cad, ao) if g not in (None, "") else A("--", "light")
        return [label, owner, _goaltxt(g, cad), str(e["Yest"]), str(e["WTD"]), mtd_cell, str(e["LastMo"]), status]
    def frow(label, fb_goal, fb_cad, w):
        g, cad, _ = _rg(M, "kcm", label, fb_goal, fb_cad)
        status = st(w["MTD"], g, cad, ao) if g not in (None, "") else A("--", "light")
        return [label, _own(M, "kcm", label, "Team"), _goaltxt(g, cad),
                str(w["Yest"]), str(w["WTD"]), str(w["MTD"]), str(w["LastMo"]), status]
    # Who is expected to file the KCM daily form = the registry owners of its rows; who did = the form's
    # submitter field. The fallback list is the form's own select choices, used only when the registry
    # pull carries no owners.
    form_rows = ["Conversations", "New Leads", "Buyer Showings", "Showings on Listing", "Pre-approved Buyers", "Pre-Sold Contracts"]
    reporters = _expected(M, "kcm", form_rows, ["Danielle", "Laurie", "Tommy", "Gabby"])
    rep = ACC.reporting(M.get("kcm_submits") or {}, reporters, ao)
    attention = _attention_missed("KCM", rep, "KCM daily form")
    blocks = [
        {"kind": "section", "title": "PORTFOLIO SNAPSHOT", "sub": "live from the KCM construction base at build time"},
        {"kind": "cards", "items": [
            # Sub-text spells out how the listing counts relate to the build count
            # (Wyatt 2026-08-24: "I need the report to say that so I don't have to ask").
            ["Homes Under Construction", str(s["under_construction"]),
             "%d listed · %d pre-list · %d pre-sold" % (s["uc_listed"], s["uc_prelist"], s["uc_presold"]), ""],
            ["Active Listings", str(s["active"]),
             "%d still building · %d complete" % (s["active"] - s["active_done"], s["active_done"]), ""],
            ["Under Contract", str(s["specs_uc"]), "%d pre-sold" % s["pre_solds"], ""],
            ["Specs Sold · YTD", str(s["specs_sold_ytd"]), money(s["sold_vol_ytd"]) + " in 2026", "green"]]},
        {"kind": "cards", "items": [
            # Amber ONLY when funds data is missing; a full count is normal, not a warning
            # (Wyatt 2026-08-24 read the standing amber "12 of 12" as a red flag).
            ["Open Constr. Loans", str(s["open_loans"]),
             ("all %d report funds" % s["open_loans"]) if s["funds_report"] == s["open_loans"]
             else "%d of %d report funds" % (s["funds_report"], s["open_loans"]),
             "" if s["funds_report"] == s["open_loans"] else "amber"],
            ["Constr. Funds Available", money(s["funds_avail"]), "left to draw, all open loans", ""],
            ["Loan Capacity Used", ("%.1f%%" % s["capacity_pct"]) if s["capacity_pct"] is not None else "-", "dollar-weighted", ""],
            ["Private $ Need (Lots)", money(s["priv_need"]), "lots awaiting loan close", ""]]},
        {"kind": "cards", "items": [
            ["Lots Owned", str(s["lots_owned"]), "vacant", ""],
            ["Lots Under Contract", str(s["lots_uc"]), "financed", ""],
            ["Specs Sold (all-time)", str(s["specs_sold_cum"]), money(s["sold_volume"]), ""],
            ["Homes in Motion", str(len(lst) + len(uc) + len(cm)), "listed + UC + coming", ""]]},
        {"kind": "section", "title": "MONTHLY EVENTS", "sub": "derived live from Specs · Status = on/off the goal's pace this month"},
        {"kind": "table", "cols": ["Event", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [122, 104, 46, 38, 38, 38, 50, 68], "left_cols": 2, "rows": [
            evrow("New Starts", _own(M, "kcm", "New Starts", "Amber"), 5, "New Starts"),
            evrow("Specs Sold", _own(M, "kcm", "Specs Sold", "Danielle"), 2, "Specs Sold"),
            evrow("Construction Loans Approved", _own(M, "kcm", "Construction Loans Approved", "Randall"), 6, "Loans Approved"),
            evrow("Lots Funded", _own(M, "kcm", "Lots Funded", "Shane"), 2, "Lots Funded"),
            evrow("Lot Closings", _own(M, "kcm", "Lot Closings", "Shane"), 2, "Lot Closings"),
            evrow("Lot Contracts", _own(M, "kcm", "Lot Contracts", "Shane"), 2, "Lot Contracts"),
            evrow("Listed Specs", _own(M, "kcm", "Listed Specs", "Danielle"), 7, "Listed Specs")] + _flips_evrows(M, ao)},
        {"kind": "section", "title": "TEAM ACTIVITY - DAILY FORMS",
         "sub": "reporters: %s · Status = on or off the goal's pace for this point in the month" % ACC.names(reporters)},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [122, 104, 46, 38, 38, 38, 50, 68], "left_cols": 2, "rows": [
            frow("Conversations", 13, "day", f["conv"]),
            frow("New Leads", 3, "day", f["lead"]),
            frow("Showings (buyer + listing)", 2, "day", f["show"]),
            frow("Pre-approved Buyers", 1, "day", f["preapp"]),
            frow("Pre-Sold Contracts", 4, "mo", f["presold"])]},
        _report_block("KCM daily form", rep),
        {"kind": "section", "title": "ACTIVE LISTINGS",
         "sub": "%d listed · %s projected profit · bank and loan drawn per home (added 2026-08-24)" % (len(lst), money(lt))},
        {"kind": "table", "cols": ["Address", "Build Stage", "DOM", "List Price", "Proj. Profit", "Bank", "Drawn · Cap%"],
         "widths": [112, 112, 30, 52, 52, 72, 74], "left_cols": 2,
         "rows": [[r["addr"], r["stage"], str(r["dom"]), money(r["list"]), money(r["profit"]), r["bank"],
                   ("%s · %d%%" % (money(r["owed"]), r["cap"])) if r["owed"] is not None else "-"] for r in lst],
         "note": "Drawn = construction loan consumed to date (loan amount minus funds still available); Cap% = share of the loan used. DOM '-' means the listing date has not been entered in the base yet."},
        {"kind": "section", "title": "UNDER CONTRACT", "sub": "%s projected profit" % money(ut)},
        {"kind": "table", "cols": ["Address", "Purchase Price", "vs Proj. List", "Proj. Profit", "Proj. Close", "Bank"],
         "widths": [150, 84, 78, 72, 60, 60], "left_cols": 1,
         "rows": [[r["addr"], money(r["purch"]), ("+" if r["vs"] >= 0 else "") + money(r["vs"]), money(r["profit"]),
                   (r["close"][5:7] + "/" + r["close"][8:10] + "/" + r["close"][2:4]) if r["close"] else "TBD",
                   r["bank"]] for r in uc]},
        {"kind": "section", "title": "COMING TO MARKET", "sub": "%d pre-listing · %s projected profit" % (len(cm), money(ct))},
        {"kind": "table", "cols": ["Address", "Plan", "SF", "Build Stage", "Proj. List", "Proj. Profit", "Bank", "Drawn · Cap%"],
         "widths": [104, 66, 32, 80, 50, 50, 58, 64], "left_cols": 2,
         "rows": [[r["addr"], r["plan"], num(r["sf"]) if r["sf"] else "-", r["stage"], money(r["list"]), money(r["profit"]),
                   r["bank"], ("%s · %d%%" % (money(r["owed"]), r["cap"])) if r["owed"] is not None else "-"] for r in cm]},
        {"kind": "prose", "text": "Projected profit in motion: %s = %s listed + %s under contract + %s coming to market"
                                  % (money(profit_motion), money(lt), money(ut), money(ct)), "size": 9},
    ] + _flips_blocks(M, ao) + [
        {"kind": "section", "title": "ACTIVE PIPELINE - LOTS AWAITING CONSTRUCTION LOAN",
         "sub": "%d lots not yet loan-closed · %s private-money need (the detail behind the Private $ Need card)"
                % (len(pipe), money(pipe_need))},
        {"kind": "table", "cols": ["Spec ID", "Lot Status", "Finance Status", "Private $ Need"],
         "widths": [184, 118, 138, 64], "left_cols": 3,
         "rows": [[r["spec_id"], r["lot"], r["fin"], money(r["need"]) if r["need"] else "-"] for r in pipe]
                 + [[A("Total", "ink", True), "", A("%d lots" % len(pipe), "ink", True), A(money(pipe_need), "ink", True)]],
         "note": "Lots that have not yet closed a construction loan: private-money-funded, loan submitted, or under contract. Loan-submitted lots are closest to closing and appear first."},
        {"kind": "section", "title": "CAPITAL & LENDERS", "sub": "construction exposure by bank across the open loans"},
        {"kind": "table", "cols": ["Bank", "Contact", "Open Loans", "Funds Remaining", "Cap. Used", "Line Capacity"],
         "widths": [110, 110, 70, 90, 64, 60], "left_cols": 2,
         "rows": [[b["bank"], b["contact"] or "-", str(b["n"]), money(b["avail"]), "%.1f%%" % b["cap"], "TBD"] for b in lenders]},
    ]
    # Data flags: a Construction Funds Available value the engine refused (negative / larger than the loan),
    # plus every Flips row whose Data Gap Flag is non-empty. Named rather than hidden, same rule as every other card.
    dropped = M.get("kcm_dropped_funds") or []
    fl = M.get("kcm_flips")
    loans_owner = ACC.names(_owners(M, "kcm", "Open Construction Loans"), "Randall")
    specs_owner = ACC.names(_owners(M, "kcm", "Under Contract"), "Gabby")
    flips_owner = ACC.names(_owners(M, "kcm", "Active Flips"), "Randall")
    flag_items = []
    for sid, val in dropped:
        flag_items.append(["%s: construction funds available left out · %s" % (sid, loans_owner),
                           "The Specs table shows %s, which cannot be right (negative, or more than the loan). The funds and "
                           "capacity numbers above leave it out until it is corrected." % money(val)])
        for o in (_owners(M, "kcm", "Open Construction Loans") or ["Randall Landry"]):
            attention.append(_att(o, "Specs table", "correct construction funds available for %s (shows %s)" % (sid, money(val))))
    # A spec whose projected close has passed but still sits Under Contract is a stage nobody updated —
    # and it is why the opening paragraph and Specs Sold can read wrong (Wyatt 10/15).
    for r in uc:
        if r.get("close") and r["close"][:10] < ao.isoformat():
            cl = "%s/%s" % (r["close"][5:7].lstrip("0"), r["close"][8:10].lstrip("0"))
            flag_items.append(["%s: closing date %s has passed, still shown Under Contract · %s" % (r["addr"], cl, specs_owner),
                               "If it closed, move it to Sold. If the closing slipped, update the date. Until then Specs Sold reads low."])
            for o in (_owners(M, "kcm", "Under Contract") or ["Gabby Theriot"]):
                attention.append(_att(o, "Specs table", "%s shows a %s closing that has passed; mark it Sold or update the date" % (r["addr"], cl)))
    if fl:
        for r in fl["rows"]:
            if r["phase"] == "Sold":
                continue
            miss = [n for n, v in (("Purchase Price", r["purch"]), ("Rehab Budget", r["rehab"]), ("Projected List", r["proj_list"])) if v is None]
            if miss:
                flag_items.append(["%s: %s not entered · %s" % (r["addr"], ", ".join(miss).lower(), flips_owner),
                                   "Blank in the Flips table, so the row reads MISSING and this flip is left out of the profit total. Nothing is assumed as $0."])
                for o in (_owners(M, "kcm", "Active Flips") or ["Randall Landry"]):
                    attention.append(_att(o, "Flips table", "%s needs %s" % (r["addr"], ", ".join(miss).lower())))
        for addr, gaps in fl["flags"]:
            flag_items.append(["%s: %s · %s" % (addr, gaps.rstrip(";").replace("missing", "not entered"), flips_owner),
                               "Fill it in on the Flips table."])
    if flag_items:
        blocks.append({"kind": "section", "title": "DATA FLAGS", "sub": "known gaps, named rather than hidden · the name is who keeps that record"})
        blocks.append({"kind": "flags", "items": flag_items})
    return {"title": "Kaizen Construction Management", "attention": attention,
            "foot": "Sources: KCM construction base (live derivation) + team daily forms · owners from Scorecard Mapping",
            "health": ("%d homes are under construction: %d of them already listed, %d pre-listing, %d pre-sold under contract%s. "
                       "%d homes are actively listed in total (%d still building, %d complete), with %s of projected profit in motion "
                       "across listed, under-contract and coming-to-market inventory. Team activity pace is shown per KPI below."
                       % (s["under_construction"], s["uc_listed"], s["uc_prelist"], s["uc_presold"],
                          (", and %d not yet staged for listing" % s["uc_unstaged"]) if s["uc_unstaged"] else "",
                          s["active"], s["active"] - s["active_done"], s["active_done"], money(profit_motion))
                       + ((" Flips: %d active (%d selling, %d in rehab, %d acquiring) with %s profit in motion%s; %d sold YTD."
                           % (fl["state"]["active"], fl["state"]["selling"], fl["state"]["rehab"], fl["state"]["acquiring"],
                              money(fl["state"]["motion"]),
                              (" (%d of %d report)" % (fl["state"]["motion_n"], fl["state"]["active"])) if fl["state"]["motion_n"] != fl["state"]["active"] else "",
                              fl["state"]["sold_ytd"])) if fl else "")),
            "blocks": blocks}

def _flips_evrows(M, ao):
    """Three Monthly Events rows for flips (added 2026-10-01), only when the Flips pull is present.
    Owner = Team: the registry carries no owner for flips KPIs yet."""
    fl = M.get("kcm_flips")
    if not fl:
        return []
    out = []
    for label in ("Flips Acquired", "Flips Listed", "Flips Sold"):
        g, cad, _ = _rg(M, "kcm", label, 1, "mo")
        e = fl["events"][label]
        status = st(e["MTD"], g, cad, ao) if g not in (None, "") else A("--", "light")
        out.append([label, _own(M, "kcm", label, "Team"), _goaltxt(g, cad), str(e["Yest"]), str(e["WTD"]), str(e["MTD"]), str(e["LastMo"]), status])
    return out

def _flips_blocks(M, ao):
    """FLIPS block inside the KCM card (added 2026-10-01, Derrick's layout rulings the same day):
    four snapshot cards + ONE table of flips in motion (selling, rehab, acquiring), one line per flip by
    address, projected numbers only. Sold flips never get a table (same as specs): they roll off the night
    they close and live on in the Flips Sold YTD card (count + realized profit) and the Monthly Events row.
    No subdivision grouping, no phase column."""
    fl = M.get("kcm_flips")
    if not fl:
        return []
    s = fl["state"]
    def mcell(v, bold=False):
        return A("MISSING", "amber", True) if v is None else (A(money(v), "ink", True) if bold else money(v))
    def pl(v):   # profit or loss: negative prints in amber so a loss is never mistaken for a typo
        if v is None: return A("MISSING", "amber", True)
        return A(money(v), "amber", True) if v < 0 else money(v)
    active = [r for r in fl["rows"] if r["phase"] != "Sold"]
    flips_owner = ACC.names(_owners(M, "kcm", "Active Flips"), "Randall")
    # Profit follows the Specs convention (Wyatt 10/15): projected until a contract / sale price is entered,
    # then the base's ACTUAL profit against that price. Capital Heights: $9,150 projected, -$17,875 at contract.
    def profit_cell(r):
        if r["sale"] is not None and r["nap"] is not None:
            return A(money(r["nap"]) + " *", "amber" if r["nap"] < 0 else "green", True)
        return pl(r["npp"])
    def dash(v):
        return money(v) if v is not None else "-"
    rows = [[r["addr"], r["stage"], str(r["days"]) if r["days"] is not None else "-",
             mcell(r["purch"]), mcell(r["rehab"]), mcell(r["proj_list"]), dash(r["sale"]), profit_cell(r)] for r in active]
    total = s["motion"]
    rows.append([A("Total", "ink", True), A("%d active flips" % s["active"], "ink", True), "", "", "", "", "",
                 A(money(total), "ink", True)])
    blocks = [
        {"kind": "section", "title": "FLIPS", "sub": "%d in motion · %s profit in motion%s · live from the KCM Flips table · data owner %s"
         % (s["active"], money(s["motion"]), "" if s["motion_n"] == s["active"] else " (%d of %d report)" % (s["motion_n"], s["active"]), flips_owner)},
        {"kind": "cards", "items": [
            ["Active Flips", str(s["active"]), "%d selling · %d rehab · %d acquiring" % (s["selling"], s["rehab"], s["acquiring"]), ""],
            ["Profit in Motion (Active)", money(s["motion"]),
             (("%d under contract at actual" % s["under_contract"]) if s["under_contract"] else "all projected")
             if s["motion_n"] == s["active"] else "%d of %d report profit" % (s["motion_n"], s["active"]),
             "" if s["motion_n"] == s["active"] else "amber"],
            ["Flips Sold · YTD", str(s["sold_ytd"]),
             (money(s["realized"]) + " realized") if s["realized_n"] == s["sold_ytd"] else "%d of %d report actual profit" % (s["realized_n"], s["sold_ytd"]),
             "green" if (s["sold_ytd"] and s["realized_n"] == s["sold_ytd"]) else ("amber" if s["sold_ytd"] else "")],
            ["Avg Days Held (Active)", str(s["avg_days"]) if s["avg_days"] is not None else "-", "acquisition to today", ""]]},
        {"kind": "table", "cols": ["Flip", "Stage", "Days", "Purchase", "Rehab Budget", "Proj. List", "Contract", "Profit"],
         "widths": [116, 92, 34, 52, 56, 52, 50, 52], "left_cols": 2, "rows": rows,
         "note": "Profit is projected (list price less rehab budget, purchase, closing, financing and holding costs) until a contract price is entered; "
                 "then * = what the flip actually makes or loses at that price, the same way Specs read once a home is under contract. "
                 "MISSING = not yet entered in the Flips table, which %s keeps. See Data Flags." % flips_owner},
    ]
    return blocks

# ---------------- Ascend ----------------
def _third_thursday(y, m):
    from datetime import date as _d, timedelta as _td
    d = _d(y, m, 1)
    d += _td(days=(3 - d.weekday()) % 7)   # first Thursday
    return d + _td(days=14)                 # third Thursday

def next_mastermind(ao):
    """Next third-Thursday mastermind on or after as_of."""
    d = _third_thursday(ao.year, ao.month)
    if d < ao:
        y, m = (ao.year + 1, 1) if ao.month == 12 else (ao.year, ao.month + 1)
        d = _third_thursday(y, m)
    return d

def _ascend(M, ao):
    r = M["ascend_roster"]; p = M["ascend_pipe"]; a = M["ascend_ads"]; fn = M["ascend_funnel"]
    mm = next_mastermind(ao)
    def prow(label, fb_goal, fb_cad, w, direction="up", mtd_green=False, lastmo_txt=None, event_cycle=False):
        g, cad, _ = _rg(M, "ascend", label, fb_goal, fb_cad)
        mtd = w["MTD"]
        # Event-cycle KPIs (Derrick's ruling 2026-08-12): the mastermind runs the THIRD THURSDAY,
        # so calendar-month pacing is meaningless — RSVPs accrue toward the event date, not evenly
        # across the month. No On/Off track for these rows; the MTD cell earns a green "(met)"
        # when the goal is hit, and the section sub carries the next event date for context.
        if event_cycle:
            met = g not in (None, "") and mtd >= g
            mtd_cell = A("%d (met)" % mtd, "green", True) if met else str(mtd)
            status_cell = A("Met", "green", True) if met else A("--", "light")
            return [label, _own(M, "ascend", label, "Tommy"), _goaltxt(g, cad, event=True), str(w["Yest"]), str(w["WTD"]), mtd_cell,
                    lastmo_txt if lastmo_txt is not None else str(w["LastMo"]), status_cell]
        mtd_cell = A("%d (met)" % mtd, "green", True) if (mtd_green and g not in (None, "") and mtd >= g) else str(mtd)
        status = st(mtd, g, cad, ao, direction) if g not in (None, "") else A("--", "light")
        return [label, _own(M, "ascend", label, "Tommy"), _goaltxt(g, cad),
                str(w["Yest"]), str(w["WTD"]), mtd_cell,
                lastmo_txt if lastmo_txt is not None else str(w["LastMo"]), status]
    blocks = [
        {"kind": "section", "title": "MEMBERSHIP SNAPSHOT"},
        {"kind": "cards", "items": [
            ["Paying Members", str(r["members"]), money(r["mrr"]) + " MRR", ""],
            ["Non-Paying", str(_nonpay(M)), "guests and team", ""],
            ["Churned (all-time)", str(r["churned"]), "", "amber"],
            ["Ad Leads MTD", str(a["MTD"]["leads"]), money(a["MTD"]["spend"]) + " spend", "green"]]},
        {"kind": "section", "title": "PIPELINE ACTIVITY",
         "sub": "RSVP split on membership status · next mastermind %s · event-cycle rows show Met when hit, no pace status"
                % mm.strftime("%b %-d")},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [150, 64, 54, 44, 44, 44, 50, 54], "left_cols": 2, "rows": [
            prow("New Leads", 3, "day", p["new_leads"]),
            prow("Mastermind RSVPs (Non-Member)", 10, "mo", p["rsvp_nm"], event_cycle=True),
            prow("Mastermind RSVPs (Member)", 30, "mo", p["rsvp_m"], event_cycle=True),
            prow("Attended Event (Non-Member)", 10, "mo", p["att_nm"], event_cycle=True),
            prow("Attended Event (Member)", 30, "mo", p["att_m"], event_cycle=True),
            prow("Shared Event RSVP (Breakfast)", 10, "mo", p["breakfast"], event_cycle=True),
            prow("New Members", 6, "mo", p["new_members"]),
            # Churn is roster-inferred (no historical stamp) — LastMo is unknowable, render "-".
            prow("Churned Members", 1, "mo", p["churn"], direction="down", lastmo_txt="-")]},
        {"kind": "section", "title": "MARKETING ENGINE", "sub": "Meta campaign, launched 7/29 · live from Meta via Windsor"},
        {"kind": "table", "cols": ["Metric", "Owner", "Goal", "Yest", "WTD", "MTD", "Since Launch 7/29"],
         "widths": [150, 64, 54, 44, 44, 44, 104], "left_cols": 2, "rows": _adrows(a, _adgoals(M, "ascend", "300"), owner=_own(M, "ascend", "Ad Spend", "Derrick"))},
    ]
    org = M.get("ascend_org")
    if org:
        blocks += [
            {"kind": "section", "title": "ORGANIC SOCIAL", "sub": "Ascend Mastermind Community Facebook page · live via Windsor"},
            {"kind": "table", "cols": ["Metric", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo"],
             "widths": [150, 64, 54, 44, 44, 44, 104], "left_cols": 2, "rows": _orgrows(org, _orggoals(M, "ascend"), owner=_own(M, "ascend", "Organic Posts Published", "Roxanne")),
             "note": "Page followers now %s. Posts counted by publish date; impressions and engagements are page-level daily totals." % num(org["fans_now"]) if org.get("fans_now") is not None else None},
        ]
    ml = M.get("ascend_members") or []
    if ASCEND_MEMBER_LIST_LIVE and ml:
        import datetime as _dt
        aod = _dt.date.fromisoformat(ao) if isinstance(ao, str) else ao
        def _since(d): return (d[5:7] + "/" + d[8:10] + "/" + d[2:4]) if d else "-"
        def _days(d):
            try: return (aod - _dt.date.fromisoformat(d[:10])).days
            except Exception: return None
        def _row(x):
            n = _days(x["since"])
            days = ("%s" % num(n)) if n is not None else "-"
            return [x["name"], _since(x["since"]), days, money(x["rate"]) if x["paying"] else "-"]
        pay = [x for x in ml if x["paying"]]; non = [x for x in ml if not x["paying"]]
        mrr = sum(x["rate"] for x in pay)
        cols = ["Member", "Member Since", "Days", "MRR"]; widths = [264, 96, 64, 80]
        blocks += [
            {"kind": "section", "title": "PAYING MEMBERS", "keep": 690, "sub": "%d members · %s MRR · alphabetical" % (len(pay), money(mrr))},
            {"kind": "table", "cols": cols, "widths": widths, "left_cols": 1,
             "rows": [_row(x) for x in pay]
                     + [[A("Total", "ink", True), "", "", A(money(mrr), "ink", True)]]},
            {"kind": "section", "title": "NON-PAYING MEMBERS", "sub": "%d members · alphabetical" % len(non)},
            {"kind": "table", "cols": cols, "widths": widths, "left_cols": 1,
             "rows": [_row(x) for x in non],
             "note": "Original members show 09/17/25, the roster load date, until real start dates are entered."},
        ]
    else:
        blocks += [
            {"kind": "section", "title": "AUGUST PROSPECT FUNNEL", "sub": "non-member registrants from the paid campaign, newest first"},
            {"kind": "table", "cols": ["Contact", "Date", "Phone", "Email"], "widths": [128, 50, 102, 224], "left_cols": 4,
             "rows": [[r2["name"], r2["date"][5:7] + "/" + r2["date"][8:10], r2["phone"], r2["email"]] for r2 in fn],
             "note": "Every prospect enters as a non-member RSVP, so contact detail is shown for follow-up. This pool is the month's conversion opportunity."},
        ]
    return {"title": "Ascend Mastermind Community",
            "foot": "Sources: GHL (The Mentee) via KPI workflows + Ascend Overview + Meta Ads%s via Windsor"
                    % (" + Facebook Organic" if org else ""),
            "health": ("Membership stands at %d paying members generating %s in recurring revenue. The paid engine, live "
                       "since 7/29, has driven %d leads since launch. Non-member RSVPs for the next mastermind are building."
                       % (r["members"], money(r["mrr"]), a["SinceLaunch"]["leads"])),
            "blocks": blocks}

def _nonpay(M):
    return M.get("ascend_nonpay", 0)

# ---------------- Coworking ----------------
def _coworking(M, ao):
    r = M["cowork_roster"]; p = M["cowork_pipe"]; a = M["cowork_ads"]; bk = M["cowork_bookings"]
    def prow(label, fb_goal, fb_cad, w, direction="up", money_row=False):
        g, cad, _ = _rg(M, "cowork", label, fb_goal, fb_cad)
        mtd = w["MTD"]
        cells = [money(w["Yest"]), money(w["WTD"]), money(w["MTD"]), money(w["LastMo"])] if money_row else \
                [str(w["Yest"]), str(w["WTD"]), str(w["MTD"]), str(w["LastMo"])]
        status = st(mtd, g, cad, ao, direction) if g not in (None, "") else A("--", "light")
        return [label, _own(M, "cowork", label, "Lindsey"), _goaltxt(g, cad, money=money_row)] + cells + [status]
    # bk is the upcoming-events dict (rows / beyond_count / beyond_rev) since 2026-08-21;
    # replaces the previous-month bookings listing per Randall's ask.
    from datetime import timedelta
    up_rows = bk["rows"]
    up_total = sum(b["rev"] for b in up_rows)
    win_lo = (ao + timedelta(days=1)).strftime("%b %-d")
    win_hi = (ao + timedelta(days=30)).strftime("%b %-d")
    blocks = [
        {"kind": "section", "title": "MEMBERSHIP SNAPSHOT"},
        {"kind": "cards", "items": [
            ["Active Members", str(r["members"] + r["unpaid"]), "%d unpaid" % r["unpaid"] if r["unpaid"] else "all paying", ""],
            ["MRR", money(r["mrr"]), "paying members", "green"],
            ["Churned (all-time)", str(r["churned"]), "", ""],
            ["Ad Leads MTD", str(a["MTD"]["leads"]), money(a["MTD"]["spend"]) + " spend", "green"]]},
        {"kind": "section", "title": "PIPELINE ACTIVITY", "sub": "owners %s · Status = on/off the goal's pace" % ACC.names(_expected(M, "cowork", ["New Leads", "Conversations", "Free Tours Booked", "Events Booked"], ["Lindsey Moore"]))},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [124, 96, 48, 40, 40, 42, 52, 62], "left_cols": 2, "rows": [
            prow("New Leads", 3, "day", p["new_leads"]),
            prow("Conversations", 5, "day", p["conv"]),
            prow("Free Tours Booked", 1, "day", p["tours"]),
            prow("Verbal Commitments", 1, "day", p["verbal"]),
            prow("New Members", 1, "day", p["new_members"]),
            prow("Events Booked", 1, "day", p["events"]),
            prow("Event Revenue", 440, "day", p["event_rev"], money_row=True),
            prow("Day Passes", 1, "day", p["day_pass"])]},
        {"kind": "section", "title": "MARKETING ENGINE", "sub": "Meta account, live since May 25 · live from Meta via Windsor"},
        {"kind": "table", "cols": ["Metric", "Owner", "Goal", "Yest", "WTD", "MTD", "Since Launch 5/25"],
         "widths": [148, 64, 56, 42, 42, 44, 108], "left_cols": 2, "rows": _adrows(a, _adgoals(M, "cowork", "300"), owner=_own(M, "cowork", "Ad Spend", "Derrick"))},
    ]
    org = M.get("cowork_org")
    if org:
        blocks += [
            {"kind": "section", "title": "ORGANIC SOCIAL", "sub": "Kaizen Coworking & Event Space Facebook page · live via Windsor"},
            {"kind": "table", "cols": ["Metric", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo"],
             "widths": [148, 64, 56, 42, 42, 44, 108], "left_cols": 2, "rows": _orgrows(org, _orggoals(M, "cowork"), owner=_own(M, "cowork", "Organic Posts Published", "Roxanne")),
             "note": "Page followers now %s. Posts counted by publish date; impressions and engagements are page-level daily totals." % num(org["fans_now"]) if org.get("fans_now") is not None else None},
        ]
    upcoming_note = "Booked = date the booking came in; Event Date = when the event runs. Window rolls forward every day."
    if bk["beyond_count"]:
        upcoming_note = ("Beyond 30 days: %d more booked, %s. " % (bk["beyond_count"], money(bk["beyond_rev"]))) + upcoming_note
    blocks += [
        {"kind": "section", "title": "UPCOMING EVENTS, NEXT 30 DAYS (%s to %s)" % (win_lo, win_hi),
         "sub": "rolling window · live from the booking table · soonest first · booked revenue"},
        {"kind": "table", "cols": ["Contact", "Booked", "Event Date", "Time", "Space", "Revenue"],
         "widths": [114, 50, 66, 104, 86, 84], "left_cols": 5,
         "rows": [[b["name"], (b["booked"][5:7] + "/" + b["booked"][8:10]) if b["booked"] else "-",
                   (b["evdate"][5:7] + "/" + b["evdate"][8:10] + "/" + b["evdate"][2:4]) if b["evdate"] else "-",
                   ("%s - %s" % (b["start"], b["end"])) if b["start"] else "-", b["space"], money(b["rev"])] for b in up_rows]
                 + [[A("Total", "ink", True), "", "", "", A("%d events" % len(up_rows), "ink", True), A(money(up_total), "ink", True)]],
         "note": upcoming_note},
    ]
    return {"title": "Kaizen Coworking & Event Space",
            "foot": "Sources: GHL (Kaizen Coworking) via KPI workflows + Coworking Overview + Meta Ads%s via Windsor"
                    % (" + Facebook Organic" if org else ""),
            "health": ("The space holds %d members%s at %s recurring revenue. Lead flow, tours and event bookings are "
                       "shown below; the paid engine has been live since May 25."
                       % (r["members"] + r["unpaid"], (", %d unpaid," % r["unpaid"]) if r["unpaid"] else "", money(r["mrr"]))),
            "blocks": blocks}

# ---------------- Rentals ----------------
def _rentals(M, ao):
    o = M["rentals_ov"]; act = M["rentals_act"]; rf = M.get("rentals_fub") or {}
    def arow(label, fb_goal, fb_cad, owner, w, direction="up"):
        g, cad, _ = _rg(M, "rentals", label, fb_goal, fb_cad)
        status = st(w["MTD"], g, cad, ao, direction) if g not in (None, "") else A("--", "light")
        return [label, _own(M, "rentals", label, owner), _goaltxt(g, cad),
                str(w["Yest"]), str(w["WTD"]), str(w["MTD"]), str(w["LastMo"]), status]
    # Expected reporters for the Rentals daily forms = registry owners of the form rows; actual = Entry Type.
    form_rows = ["Leads", "Conversations", "Appointments Set", "Showings", "Applications", "New Leases",
                 "Renewals", "Notice Given", "Evictions", "Leased by Arkie", "Leased by Tommy"]
    pm_rows = ["Showings", "Applications", "New Leases", "Renewals", "Notice Given", "Evictions"]
    reporters = _expected(M, "rentals", form_rows, ["Arkie", "Lara Harris", "Tommy Sigman"])
    pm_reporters = _expected(M, "rentals", pm_rows, ["Lara Harris"])
    rep_all = ACC.reporting(M.get("rentals_submits") or {}, reporters, ao)
    rep_pm = ACC.reporting(M.get("rentals_submits") or {}, pm_reporters, ao)
    attention = _attention_missed("Rentals", rep_all, "Rentals daily form")
    snap_sub = "Buildium via the nightly sync" + ((" · snapshot dated %s" % o["snap_date"]) if o.get("snap_date") else "")
    vac_txt = ("%d vacant" % o["vacant_total"]) if o.get("vacant_total") is not None else ""
    prop_rows = [[p["name"], str(p["units"]), str(p["vac"]),
                  ("%s%%" % _pct(p["occ"])) if p["occ"] is not None else "-"]
                 for p in o.get("props", [])]
    if o.get("coliving_vac"):
        prop_rows.append(["Coliving", "-", str(o["coliving_vac"]), A("excluded", "light")])
    blocks = [
        {"kind": "section", "title": "PORTFOLIO SNAPSHOT", "sub": snap_sub},
        {"kind": "cards", "items": [
            ["Total Occupancy", "%s%%" % _pct(o["occ"]), "goal 96%", "amber"],
            ["Units", str(o["units"] or 0), vac_txt, ""],
            ["Outstanding Balance", money(o["balance"]), "ceiling $10,000", "amber"],
            ["New Leases MTD", str(act["New Leases"]["MTD"]), "", ""]]},
        {"kind": "section", "title": "PROPERTY OCCUPANCY", "sub": "per-property split from the same Buildium snapshot"},
        # widths must total 504 (page content width) — the first cut at 560 pushed Occupancy off the right edge
        {"kind": "table", "cols": ["Property", "Units", "Vacant", "Occupancy"],
         "widths": [246, 78, 78, 102], "left_cols": 1, "rows": prop_rows,
         "note": "Coliving vacancies are tracked but excluded from the occupancy rate."},
    ]
    if rf:
        blocks += [
            {"kind": "section", "title": "LEASING FUNNEL", "sub": "leads, calls and appointments straight from Follow Up Boss · Status = on/off the goal's pace"},
            {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
             "widths": [120, 100, 46, 42, 42, 42, 52, 60], "left_cols": 2, "rows": [
                arow("Leads", 5, "day", "Arkie/Tommy", rf["Leads"]),
                arow("Conversations", 3, "day", "Arkie/Tommy", rf["Conversations"]),
                arow("Appointments Set", 1, "day", "Arkie/Tommy", rf["Appointments Set"])],
             "note": "Leads = FUB people created with a rental source or assigned to Arkie. Conversations = Arkie + Tommy calls of 30 seconds or more. Appointments Set = people moved into the FUB 'Rental - Appt Set' stage. Showings onward come from Lara's form below; the later FUB rental stages are not kept up (3 people marked Leased in FUB, ever) and are not used."},
            {"kind": "section", "title": "APPOINTMENTS SET THIS MONTH - BY PROPERTY", "sub": "from the FUB property tag on each person"},
            {"kind": "table", "cols": ["Property", "Appointments Set MTD"],
             "widths": [396, 108], "left_cols": 1,
             "rows": [[p, str(n)] for p, n in sorted(M.get("rentals_set_by_prop", {}).items(), key=lambda kv: (kv[0].startswith("("), -kv[1], kv[0]))]
                     + [[A("Total", "ink", True), A(str(sum(M.get("rentals_set_by_prop", {}).values())), "ink", True)]]},
            {"kind": "section", "title": "PROPERTY MANAGEMENT ACTIVITY", "sub": "reporters: %s · daily form until the Buildium lease-event feed lands · Status = on/off the goal's pace" % ACC.names(pm_reporters)},
            {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
             "widths": [120, 100, 46, 42, 42, 42, 52, 60], "left_cols": 2, "rows": [
                arow("Showings", 2, "day", "Lara", act["Showings"]),
                arow("Applications", 1, "day", "Lara", act["Applications"]),
                arow("New Leases", 1, "day", "Lara", act["New Leases"]),
                arow("Renewals", 1, "day", "Lara", act["Renewals"]),
                arow("Notice Given", 0, "day", "Lara", act["Notice Given"], direction="down"),
                arow("Evictions", 0, "mo", "Lara", act["Evictions"], direction="down")]},
            _report_block("Rentals property-management form", rep_pm),
        ]
    else:
        # pre-FUB layout (the brief Wyatt gets until FUB_GO_LIVE_AS_OF): every row from the daily forms
        blocks += [
        {"kind": "section", "title": "LEASING ACTIVITY", "sub": "reporters: %s · hand-logged daily forms · Status = on/off the goal's pace" % ACC.names(reporters)},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [120, 100, 46, 42, 42, 42, 52, 60], "left_cols": 2, "rows": [
            arow("Leads", 5, "day", "Arkie/Tommy", act["Leads"]),
            arow("Conversations", 3, "day", "Arkie/Tommy", act["Conversations"]),
            arow("Appointments Set", 1, "day", "Arkie/Tommy", act["Appointments Set"]),
            arow("Showings", 2, "day", "Lara", act["Showings"]),
            arow("Applications", 1, "day", "Lara", act["Applications"]),
            arow("New Leases", 1, "day", "Lara", act["New Leases"]),
            arow("Renewals", 1, "day", "Lara", act["Renewals"]),
            arow("Notice Given", 0, "day", "Lara", act["Notice Given"], direction="down"),
            arow("Evictions", 0, "mo", "Lara", act["Evictions"], direction="down"),
            arow("Leased by Arkie", 1, "week", "Arkie", act["Leased by Arkie"]),
            arow("Leased by Tommy", 1, "week", "Tommy", act["Leased by Tommy"])]},
        _report_block("Rentals daily forms", rep_all),
        ]
    foot = ("Sources: Buildium via nightly sync + Follow Up Boss (leads, calls, rental stages) + Lara (property manager) daily form" if rf
            else "Sources: Buildium via nightly sync + Arkie, Tommy and Lara (property manager) daily forms")
    return {"title": "Rentals", "attention": attention,
            "foot": foot + " · owners from Scorecard Mapping",
            "health": ("Occupancy is %s%% across %d units. Leasing activity pace is shown per KPI below."
                       % (_pct(o["occ"]), o["units"] or 0)),
            "blocks": blocks}

# ---------------- Kaizen Home Sales & Services — brokerage + Kaizen Team, from Follow Up Boss ----------------
# Owners come from Scorecard Mapping (Kaizen Home Sales & Services rows): Tommy owns leads/conversations/agent
# activity, Randall owns closings. Software is the source, never the owner.
_OFFICE_OWNER = {"New Leads": "Tommy", "Conversations": "Tommy", "Closings": "Randall"}
def _team(M, ao):
    act = M["team_act"]; ag = M["team_agents"]; pipe = M["team_pipe"]; order = M["team_pipe_order"]
    uc = M["team_uc"]; cl = M["team_closed_mtd"]
    oa = M["office_act"]; op = M["office_pipe"]; ocl = M["office_closed_mtd"]; board = M["office_board"]; idle = M["office_idle"]
    n_agents = M["office_active_agents"]
    def trow(label, fb_goal, fb_cad, w, money_row=False):
        g, cad, _ = _rg(M, "team", label, fb_goal, fb_cad)
        status = st(w["MTD"], g, cad, ao) if g not in (None, "") else A("--", "light")
        f = money if money_row else (lambda x: str(x))
        return [label, "Laurie/Danielle/Tommy", _goaltxt(g, cad, money=money_row), f(w["Yest"]), f(w["WTD"]), f(w["MTD"]), f(w["LastMo"]), status]
    def dt(s): return (s[5:7] + "/" + s[8:10] + "/" + s[2:4]) if s else "TBD"
    uc_n = pipe["Under Contract"]["n"]; open_n = sum(v["n"] for v in pipe.values())
    ouc_n = op["Under Contract"]["n"]; oopen_n = sum(v["n"] for v in op.values())
    # Sisu keeps the money; FUB deals usually carry $0 price/commission. Show money only when it is there.
    has_money = any(v["vol"] or v["comm"] for v in op.values()) or any(r["price"] or r["comm"] for r in ocl)
    def deal_table(rows, last_col, last_key):
        if has_money:
            return {"kind": "table", "cols": ["Address", "Agent", "Side", "Price", "GCI", last_col],
                    "widths": [176, 96, 64, 64, 56, 48], "left_cols": 3,
                    "rows": [[r["addr"], r["agent"], r["pipe"].replace("Sisu ", ""), money(r["price"]), money(r["comm"]), dt(r[last_key])] for r in rows]}
        return {"kind": "table", "cols": ["Address", "Agent", "Side", last_col],
                "widths": [246, 130, 64, 64], "left_cols": 3,
                "rows": [[r["addr"], r["agent"], r["pipe"].replace("Sisu ", ""), dt(r[last_key])] for r in rows]}
    def pipe_table(p):
        if has_money:
            return {"kind": "table", "cols": ["Stage", "Deals", "Volume", "GCI at close"], "widths": [216, 72, 108, 108], "left_cols": 1,
                    "rows": [[k, str(p[k]["n"]), money(p[k]["vol"]), money(p[k]["comm"])] for k in order]}
        return {"kind": "table", "cols": ["Stage", "Deals"], "widths": [396, 108], "left_cols": 1,
                "rows": [[k, str(p[k]["n"])] for k in order]}
    idle_txt = ("%d of %d active agents had no FUB activity this month (no leads, calls, appointments or deals)." % (len(idle), n_agents)) if n_agents else ""
    blocks = [
        # ---- BROKERAGE (whole office)
        {"kind": "section", "title": "BROKERAGE SNAPSHOT", "sub": "whole office, live from Follow Up Boss (all sales pipelines) · roster from FUB users"},
        {"kind": "cards", "items": [
            ["Active Agents", str(n_agents), "FUB users, agent + broker", ""],
            ["Closings MTD", str(oa["Closings"]["MTD"]), "office-wide", ""],
            ["Under Contract", str(ouc_n), "pending / buyer contract", ""],
            ["Open Pipeline", str(oopen_n), "deals not yet closed", ""]]},
        {"kind": "section", "title": "OFFICE ACTIVITY - FROM FOLLOW UP BOSS", "sub": "every agent · leads, calls and deal dates straight from FUB · goals are the Kaizen Team's; office rows carry no pace status"},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [148, 50, 62, 44, 44, 48, 52, 56], "left_cols": 2, "rows": [
            [k, _OFFICE_OWNER.get(k, "Tommy"), "-", str(oa[k]["Yest"]), str(oa[k]["WTD"]), str(oa[k]["MTD"]), str(oa[k]["LastMo"]), A("--", "light")]
            for k in ("New Leads", "Conversations", "Appointments Set", "Appointments Met", "Signed Clients", "Contracts", "Closings")]},
        {"kind": "section", "title": "AGENT LEADERBOARD - MONTH TO DATE", "sub": "agents with any FUB activity this month, most closings first · * = Kaizen Team"},
        {"kind": "table", "cols": ["Agent", "Leads", "Convos", "Set", "Met", "Signed", "Under Contract", "Closed"],
         "widths": [156, 44, 52, 40, 40, 52, 72, 48], "left_cols": 1,
         "rows": [[r["name"] + (" *" if r["team"] else ""), str(r["leads"]), str(r["conv"]), str(r["set"]), str(r["met"]),
                   str(r["signed"]), str(r["uc"]), str(r["closed"])] for r in board],
         "note": idle_txt},
        {"kind": "section", "title": "OFFICE PIPELINE BY STAGE", "sub": "%d open deals entered within the last year · %d older open deals excluded as stale" % (oopen_n, M.get("office_stale", 0))},
        pipe_table(op),
        {"kind": "section", "title": "OFFICE CLOSINGS THIS MONTH", "sub": "%d closing%s" % (len(ocl), "" if len(ocl) == 1 else "s")},
        deal_table(ocl, "Closed", "closed"),
        # ---- KAIZEN TEAM
        {"kind": "section", "title": "KAIZEN TEAM - ACTIVITY VS GOAL", "sub": "Laurie, Danielle, Tommy · goals from Scorecard Mapping (Kaizen Team) · Status = on/off the goal's pace", "keep": 300},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [118, 92, 56, 40, 40, 44, 50, 56], "left_cols": 2, "rows": [
            trow("New Leads", 5, "day", act["New Leads"]),
            trow("Conversations", 30, "day", act["Conversations"]),
            trow("Appointments Set", 3, "day", act["Appointments Set"]),
            trow("Appointments Met", 3, "day", act["Appointments Met"]),
            trow("Signed Clients", 3, "day", act["Signed Clients"]),
            trow("Contracts", 3, "day", act["Contracts"]),
            trow("Closings", 1, "day", act["Closings"]),
            trow("GCI (After COS)", 2500, "week", act["GCI (After COS)"], money_row=True)],
         "note": "Conversations = logged FUB calls of 30 seconds or more. Appointments, signed, contracts and closings count on the Sisu dates FUB stores on each deal (or the day the deal entered that stage when the date is blank). GCI reads FUB's commission field, which is $0 until Sisu pushes it."},
        {"kind": "section", "title": "KAIZEN TEAM - BY AGENT, MONTH TO DATE", "sub": "same definitions, one agent at a time"},
        {"kind": "table", "cols": ["Agent", "Leads", "Convos", "Set", "Met", "Signed", "Contracts", "Closed", "GCI"],
         "widths": [120, 44, 48, 40, 40, 48, 56, 48, 60], "left_cols": 1,
         "rows": [[a["name"], str(a["leads"]), str(a["conv"]), str(a["set"]), str(a["met"]), str(a["signed"]),
                   str(a["uc"]), str(a["closed"]), money(a["gci"])] for a in ag]},
        {"kind": "section", "title": "KAIZEN TEAM - OPEN PIPELINE", "sub": "%d open deals · %d under contract" % (open_n, uc_n)},
        pipe_table(pipe),
        {"kind": "section", "title": "KAIZEN TEAM - UNDER CONTRACT", "sub": "%d deals in Pending / Buyer Contract" % uc_n},
        deal_table(uc, "Proj. Close", "proj"),
        {"kind": "section", "title": "KAIZEN TEAM - CLOSED THIS MONTH", "sub": "%d closing%s" % (len(cl), "" if len(cl) == 1 else "s")},
        deal_table(cl, "Closed", "closed"),
    ]
    return {"title": "Kaizen Home Sales & Services",
            "foot": "Sources: Follow Up Boss deals, calls, people and users, synced nightly by n8n · Kaizen Team goals from Scorecard Mapping",
            "health": ("The brokerage has %d active agents, %d deal%s under contract and %d closing%s month to date office-wide; the Kaizen Team (Laurie, Danielle, Tommy) holds %d of the open deals. "
                       "Activity comes straight from Follow Up Boss: no forms to fill, nothing to remember to log."
                       % (n_agents, ouc_n, "" if ouc_n == 1 else "s", oa["Closings"]["MTD"], "" if oa["Closings"]["MTD"] == 1 else "s", open_n)),
            "blocks": blocks}

# ---------------- Fundamentals ELC ----------------
def _fundamentals(M, ao):
    """Owner Paige Comeaux. Source = the ELC operational base (roster, staff, waitlist she runs
    the school in) + her trimmed M-F form (leads / conversations / tours only). No ad block
    (Derrick directive 2026-08-04). Standard template: Overview cards → KPI table → the
    detail table of the thing the division sells (rooms) → data flags."""
    o = M["felc_ov"]; p = M["felc_pipe"]; rooms = M["felc_rooms"]; fl = M["felc_flags"]
    def cell(w, k, dead):
        return "-" if k in dead else str(w[k])
    def prow(label, fb_goal, fb_cad, w, direction="up", dead=()):
        g, cad, _ = _rg(M, "fundamentals", label, fb_goal, fb_cad)
        mtd = w["MTD"]
        status = st(mtd, g, cad, ao, direction) if (g not in (None, "") and "MTD" not in dead) else A("--", "light")
        return [label, _own(M, "fundamentals", label, "Paige"), _goaltxt(g, cad), cell(w, "Yest", dead), cell(w, "WTD", dead),
                cell(w, "MTD", dead), cell(w, "LastMo", dead), status]
    # Paige's M-F form has one submitter; expected = registry owners of its three rows.
    reporters = _expected(M, "fundamentals", ["New Leads", "Conversations", "Tours"], ["Paige Comeaux"])
    rep = ACC.reporting({ACC.first(reporters[0]): set(p.get("form_dates") or [])}, reporters, ao)
    attention = _attention_missed("Fundamentals", rep, "Fundamentals daily form")
    wl_owner = ACC.names(_owners(M, "fundamentals", "Waitlist"), "Paige")
    wl_exits = o.get("waitlist_converted", 0) + o.get("waitlist_cold", 0)
    wl_since = o.get("waitlist_since") or ""
    wl_since_txt = ("%d/%d" % (int(wl_since[5:7]), int(wl_since[8:10]))) if len(wl_since) >= 10 else "load"
    if wl_exits == 0:
        for own in (_owners(M, "fundamentals", "Waitlist") or ["Paige Comeaux"]):
            attention.append(_att(own, "Waitlist",
                                  "%d families are still marked active and none has been moved to Converted or Cold since the %s load, "
                                  "so the waitlist number only ever grows" % (o["waitlist_active"], wl_since_txt)))
    enr_goal = _gnum(M, "fundamentals", "Kids Enrolled")
    open_goal = _gnum(M, "fundamentals", "Openings")
    wl_goal = _gnum(M, "fundamentals", "Waitlist")
    pct = (100.0 * o["class_enrolled"] / o["class_cap"]) if o["class_cap"] else None
    wl_dead = tuple(p["_waitlist_dead"]); form_dead = tuple(p["_form_dead"])
    def _ratio(r):
        n = r.get("staff") or 0
        return ("%d (1:%.0f)" % (n, r["enrolled"] / n)) if n and r["enrolled"] else (str(n) if n else "-")
    rows_tbl = [[r["name"], r["age"], str(r["cap"]), str(r["enrolled"]), str(r["open"]),
                 str(r["waitlist"]) if r["waitlist"] else "-", money(r["rev"])] for r in rooms]
    # the waitlist rows that carry no target room yet (assigned when a seat is offered) get their
    # own row so the column sums to the Active Waitlist card (Derrick 2026-09-02: 54 vs 136 read as a
    # contradiction; it is assigned-to-a-room vs all active families).
    unassigned = o["waitlist_unassigned"]
    rows_tbl.append(["Not yet assigned", "birth-year pool, room set when a seat is offered", "", "", "",
                     str(unassigned), ""])
    rows_tbl.append([A("Total", "ink", True), "", A(str(sum(r["cap"] for r in rooms)), "ink", True),
                     A(str(o["enrolled_total"]), "ink", True), A(str(o["open_seats"]), "ink", True),
                     A(str(sum(r["waitlist"] for r in rooms) + unassigned), "ink", True), A(money(o["weekly_rev"]), "ink", True)])
    demand_txt = " · ".join("%s: %d" % (k, v) for k, v in o["demand"])
    blocks = [
        {"kind": "section", "title": "ENROLLMENT SNAPSHOT", "sub": "live from the Fundamentals ELC base at build time · fall 2026 roster"},
        {"kind": "cards", "items": [
            ["Children Enrolled", str(o["enrolled_total"]),
             ("goal %d" % enr_goal) if enr_goal else "classroom + before/after care", ""],
            ["Classroom Seats Filled", "%s%%" % (("%.0f" % pct) if pct is not None else "-"),
             "%d of %d seats" % (o["class_enrolled"], o["class_cap"]), ""],
            ["Booked Weekly Tuition", money(o["weekly_rev"]), "live from the roster, rate less discounts", "green"],
            ["Active Waitlist", str(o["waitlist_active"]),
             "%d converted · %d cold since %s · %s" % (o.get("waitlist_converted", 0), o.get("waitlist_cold", 0), wl_since_txt, ACC.first(wl_owner)),
             "amber" if wl_exits == 0 else "green"]]},
        {"kind": "cards", "items": [
            ["Open Seats", str(o["open_seats"]), ("goal %d" % open_goal if open_goal else "across all rooms"), ""],
            ["Before/After Care", "%d of %d" % (o["purple_enrolled"], o["purple_cap"]), "Purple Room", ""],
            ["Active Staff", str(o["staff_active"]), ("%d CPR expired" % fl["cpr_expired"]) if fl["cpr_expired"] else "certs current", "amber" if fl["cpr_expired"] else ""],
            ["Withdrawals MTD", str(p["churn"]["MTD"]), "%d last month" % p["churn"]["LastMo"], ""]]},
        {"kind": "section", "title": "ENROLLMENT & STAFF ACTIVITY", "sub": "owner Paige Comeaux · derived from start / end / hire dates in the base · Status = on/off the goal's pace"},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [124, 96, 48, 40, 40, 42, 52, 62], "left_cols": 2, "rows": [
            prow("New Enrollments", 2, "day", p["new_enroll"]),
            prow("Churn (withdrawals)", 0, "day", p["churn"], direction="down"),
            prow("New Hires", 1, "day", p["new_hires"]),
            prow("Terminations", 0, "day", p["terminations"], direction="down"),
            prow("Added to Waitlist", 1, "day", p["waitlist_added"], dead=wl_dead)],
         "note": ("Added to Waitlist counts from 8/28; the 8/27 bulk load of the existing list is excluded, so earlier windows show '-'. "
                  "Churn is counted on each child's last day. Goals render as stored in the registry (daily cadence, set before the base existed); Randall is confirming the periods.")},
        {"kind": "section", "title": "PROSPECT FUNNEL", "sub": "leads, conversations and tours from Paige's M-F daily form, live since 9/01 · enrollments from start dates in the base"},
        {"kind": "table", "cols": ["KPI", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo", "Status"],
         "widths": [124, 96, 48, 40, 40, 42, 52, 62], "left_cols": 2, "rows": [
            prow("New Leads", None, "day", p["leads"], dead=form_dead),
            prow("Conversations", None, "day", p["conv"], dead=form_dead),
            prow("Tours", None, "day", p["tours"], dead=form_dead),
            prow("New Enrollments", 2, "day", p["new_enroll"])],
         "note": "Windows before the form went live show '-'. New Enrollments is the same count as the activity table above, shown here as the bottom of the funnel. Goals for the first three rows are being set in the registry; pace status appears once they are."},
        _report_block("Fundamentals daily form", rep),
        {"kind": "section", "title": "ROOMS: CAPACITY, FILLED, OPEN, DEMAND", "keep": 320,
         "sub": "%d classroom seats open · %d families targeting a specific room, %d more in the birth-year pool" % (
             sum(r["open"] for r in rooms if r["name"] != "Purple Room"), sum(r["waitlist"] for r in rooms), unassigned)},
        {"kind": "table", "cols": ["Room", "Age Group", "Cap", "Enrolled", "Open", "Waitlist", "Weekly $"],
         "widths": [90, 150, 40, 56, 44, 56, 68], "left_cols": 2, "rows": rows_tbl,
         "note": "Waitlist = active families Paige has pointed at a room; '-' = none assigned to that room yet. The pool row is everyone else, matched to a room when a seat is offered. Active waitlist by birth year: %s." % demand_txt},
    ]
    org = M.get("felc_org")
    if org:
        blocks += [
            {"kind": "section", "title": "ORGANIC SOCIAL", "sub": "Fundamentals Early Learning Center Facebook page · live via Windsor · no paid ads run for this division"},
            {"kind": "table", "cols": ["Metric", "Owner", "Goal", "Yest", "WTD", "MTD", "LastMo"],
             "widths": [148, 64, 56, 42, 42, 44, 108], "left_cols": 2, "rows": _orgrows(org, _orggoals(M, "fundamentals"), owner=_own(M, "fundamentals", "Organic Posts Published", "Roxanne")),
             "note": "Page followers now %s. Posts counted by publish date; impressions and engagements are page-level daily totals." % num(org["fans_now"]) if org.get("fans_now") is not None else None},
        ]
    flag_items = []
    if fl["departed_no_end"]:
        flag_items.append(["%d departed children carry no last day" % fl["departed_no_end"],
                           "Fall transition departures without an End Date. Until Paige dates them, churn for July and August reads low. The base flags each one for her."])
    if fl["inactive_no_end"]:
        flag_items.append(["%d inactive staff carry no end date · %s" % (fl["inactive_no_end"], wl_owner),
                           "Marked Inactive without a last day, so Terminations reads low until Paige dates them."])
    q = fl["children"] + fl["staff"] + fl["waitlist"]
    if q:
        flag_items.append(["Data backfill queue: %d records · %s" % (q, wl_owner),
                           "%d children, %d staff, %d waitlist rows are missing dates, contacts or certs in the Fundamentals base." % (fl["children"], fl["staff"], fl["waitlist"])])
    if flag_items:
        blocks += [{"kind": "section", "title": "DATA FLAGS", "sub": "known gaps, named rather than hidden"},
                   {"kind": "flags", "items": flag_items}]
    ann = o["annualized"]
    return {"title": "Fundamentals of Early Learning Center", "attention": attention,
            "foot": "Sources: Fundamentals ELC operational base (rooms, children, staff, waitlist; live derivation) + Paige's daily form%s · owners from Scorecard Mapping"
                    % (" + Facebook Organic via Windsor" if org else ""),
            "health": ("The school has %d children enrolled, %d of %d classroom seats (%s%%) plus %d in before/after care, "
                       "booking %s a week in tuition (about %s a year). %d families are on the active waitlist against %d open seats, "
                       "so demand is concentrated where rooms are full. Staff stands at %d."
                       % (o["enrolled_total"], o["class_enrolled"], o["class_cap"], ("%.0f" % pct) if pct is not None else "-",
                          o["purple_enrolled"], money(o["weekly_rev"]), money(ann), o["waitlist_active"], o["open_seats"], o["staff_active"])),
            "blocks": blocks}

# widths for the leasing table are 8 cols; fix the header count
def _adgoals(M, div, spend_fb):
    """Ad-row goals live from the registry (Ad Spend / Ad Leads / CPL). Blank -> '-'."""
    sp = _gnum(M, div, "Ad Spend"); ld = _gnum(M, div, "Ad Leads"); cp = _gnum(M, div, "Cost Per Lead (CPL)")
    return {"spend": (str(int(round(sp))) if sp not in (None, "") else spend_fb),
            "leads": (str(int(round(ld))) if ld not in (None, "") else "-"),
            "cpl":   (str(int(round(cp))) if cp not in (None, "") else "-")}

def _orggoals(M, div):
    """ORGANIC SOCIAL row goals live from the registry (all monthly). None -> '-'."""
    return {"posts": _gnum(M, div, "Organic Posts Published"),
            "impressions": _gnum(M, div, "Organic Page Impressions"),
            "engagements": _gnum(M, div, "Organic Post Engagements"),
            "net_fans": _gnum(M, div, "Organic Net New Followers")}

def _adrows(a, goals, owner="Derrick"):
    # Column geometry mirrors the division's PIPELINE ACTIVITY table (Derrick, 2026-08-12):
    # Metric · Owner · Goal · Yest · WTD · MTD share the pipeline x-positions; the final
    # column spans the pipeline's LastMo + Status widths. Goals come live from the registry.
    sl = a.get("SinceLaunch", a["MTD"])
    lg = goals.get("leads", "-"); cg = goals.get("cpl", "-")
    return [
        ["Ad Spend", owner, "$%s/mo" % goals.get("spend", "-"), money(a["Yest"]["spend"]), money(a["WTD"]["spend"]), money(a["MTD"]["spend"]), money(sl["spend"])],
        ["Impressions", owner, "-", num(a["Yest"]["impr"]), num(a["WTD"]["impr"]), num(a["MTD"]["impr"]), num(sl["impr"])],
        ["Clicks", owner, "-", num(a["Yest"]["clicks"]), num(a["WTD"]["clicks"]), num(a["MTD"]["clicks"]), num(sl["clicks"])],
        ["Ad Leads", owner, lg if lg == "-" else "%s/mo" % lg, str(a["Yest"]["leads"]), str(a["WTD"]["leads"]), str(a["MTD"]["leads"]), str(sl["leads"])],
        ["Cost per Lead", owner, "$%s" % cg if cg != "-" else "-", cpl(a["Yest"]["cpl"]), cpl(a["WTD"]["cpl"]), cpl(a["MTD"]["cpl"]), cpl(sl["cpl"])],
    ]

def _orgrows(o, goals=None, owner="Roxanne"):
    """ORGANIC SOCIAL rows from the computed organic dict (windows Yest/WTD/MTD/LastMo).
    Goals now come live from the registry (all monthly); a blank registry goal renders '-'."""
    goals = goals or {}
    def gtxt(k):
        v = goals.get(k)
        return "-" if v in (None, "") else "%s/mo" % num(v)
    def n(w, k):
        v = o[w].get(k)
        return "-" if v is None else num(v)
    def delta(w):
        v = o[w].get("net_fans")
        if v is None: return "-"
        return ("+%d" % v) if v > 0 else str(v)
    return [
        ["Posts Published", owner, gtxt("posts"), n("Yest","posts"), n("WTD","posts"), n("MTD","posts"), n("LastMo","posts")],
        ["Page Impressions", owner, gtxt("impressions"), n("Yest","impressions"), n("WTD","impressions"), n("MTD","impressions"), n("LastMo","impressions")],
        ["Post Engagements", owner, gtxt("engagements"), n("Yest","engagements"), n("WTD","engagements"), n("MTD","engagements"), n("LastMo","engagements")],
        ["Net New Followers", owner, gtxt("net_fans"), delta("Yest"), delta("WTD"), delta("MTD"), delta("LastMo")],
    ]
