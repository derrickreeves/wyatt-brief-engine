# -*- coding: utf-8 -*-
"""KCM division compute — everything derived live from the KCM construction base.

All state and events come straight from Specs at build time (no midnight cache).
Functions take the raw records (from the saved Specs/Flips pulls) + as_of date and
return computed numbers + drill-down rows. Locked definitions per kcm-overview-compute
and kcm-events-compute rulebooks.
"""
from datetime import date
from brief_engine import _name, windows

# --- Specs field IDs ---
LiS="fldpvR1bpY4mOGAlC"; CS="fldqT8QJnwawICxBZ"; FS="fldgiX23n9c1XhBDm"; LotS="fldYVll4ZTtlXasLR"
SCD="fldSSfJalgC6oWM4e"; PURCH="fldBEXUNvW8GBgb7r"; CFA="fld9kQZnzpcVwcYnI"; UND="fldqAsEEePsJ7uT2N"
PML="fld5jByPruRNSYxa3"
START="fldEtRtVk3FUNLcpQ"; LOANCLOSE="fldUGLij0Dn6mHEg8"; LOTCONTRACT="fldzbRKkpQp3Ju87V"
LOTFUNDED="flduAOciMEQBvghqr"; LOTPURCH="fldaqNBEMFltHwYNL"; LISTDATE="fld6ZWxnlHzvwqSHz"
ADDR="fld4hPC6c42AHJ7p9"; LISTP="fldSDpxEnW8cEPXsZ"; PROJLIST="fldPjEDsMOSYt8w8F"
SPECID="fldZTIK9PRlgbBAnO"  # primary formula field: CONCATENATE(Subdivision,"-",Lot#) — record-tied ID
NPP="fldfqByfxqcU2uMYh"; PROJCLOSE="fldDLddBG3Xx9OcjE"; PLAN="fldAeu32Ud90bKRzb"; SF="fldMwpjXIpDxC1LN4"
CLENDER="fldJOnOf9eW3LxnQx"; LOANAMT="fldOnaIyOs7blz8Y9"
REJECT={"Offer Rejected","Rejected by Underwriting"}

def _sane_funds(cells):
    """Drop-and-flag rule (Derrick 9/21, made structural 9/22): a Construction Funds Available value that is
    negative or larger than the loan itself is a data-entry error (Whisper Hollow-8 read -$44B on 9/21).
    Treat it as MISSING so it neither prints nor poisons the sums; the funds_report count shows the gap
    ("11 of 12 report funds") exactly as a blank would. Returns the ids dropped so the caller can flag them."""
    dropped=[]
    for x in cells:
        v=x.get(CFA); loan=x.get(LOANAMT)
        if v is None: continue
        # small negatives are real overdraws (a loan consumed past its available funds) and stay in;
        # only values no construction loan could produce are refused
        bad = v < -250_000 or v > 5_000_000 or (loan and v > loan*1.05)
        if bad:
            dropped.append((x.get(SPECID) or "?", v)); x[CFA]=None
    return dropped

def _cells(specs):
    cells=[r["cellValuesByFieldId"] for r in specs]
    for sid,v in _sane_funds(cells):          # accumulate across calls; the cell is nulled so it drops once
        if sid not in [d[0] for d in DROPPED_FUNDS]: DROPPED_FUNDS.append((sid,v))
    return cells
DROPPED_FUNDS=[]

def _lk(v):
    """Unwrap an Airtable lookup/link value to its first scalar."""
    if isinstance(v, dict) and "valuesByLinkedRecordId" in v:
        for _, val in v["valuesByLinkedRecordId"].items():
            if val:
                return val[0] if isinstance(val, list) else val
        return None
    if isinstance(v, list):
        return v[0] if v else None
    return v

def kcm_state(specs):
    c=_cells(specs); s={}
    def g(x,f): return _name(x.get(f))
    s["lots_owned"]   = sum(1 for x in c if g(x,LotS)=="Lot Purchased" and not g(x,CS) and not g(x,LiS))
    s["lots_uc"]      = sum(1 for x in c if g(x,LotS)=="Lot Under Contract")
    s["pre_solds"]    = sum(1 for x in c if g(x,LiS)=="Under Contract" and g(x,CS)!="Completed Spec")
    # Homes Under Construction = a real build stage underway, not finished, not sold.
    # Excludes vacant lots + stub rows (no Construction Stage) and Completed/Closed homes.
    # Overlaps the listing sections by design (a listed home can still be building).
    # Ruling: Derrick 2026-08-12 (replaces the old "not listed / not sold" count that mixed in lots).
    bldg = [x for x in c if g(x,CS) and g(x,CS)!="Completed Spec" and g(x,LiS)!="Closed"]
    s["under_construction"] = len(bldg)
    # Listing-status split OF the under-construction set (Wyatt's ask 2026-08-24:
    # the snapshot must say how the listing counts relate to the build count,
    # because "11 building / 5 listed" read as ambiguous — and 4, not 5, of the
    # active listings are actually among the 11; the 5th is a completed home).
    s["uc_listed"]   = sum(1 for x in bldg if g(x,LiS)=="Active Listing")
    s["uc_prelist"]  = sum(1 for x in bldg if g(x,LiS)=="Pre-Listing")
    s["uc_presold"]  = sum(1 for x in bldg if g(x,LiS)=="Under Contract")
    s["uc_unstaged"] = sum(1 for x in bldg if not g(x,LiS))
    s["specs_uc"]     = sum(1 for x in c if g(x,LiS)=="Under Contract")
    s["active"]       = sum(1 for x in c if g(x,LiS)=="Active Listing")
    # Active listings that are FINISHED homes (not in the build count).
    s["active_done"]  = sum(1 for x in c if g(x,LiS)=="Active Listing" and g(x,CS)=="Completed Spec")
    s["pre_listing"]  = sum(1 for x in c if g(x,LiS)=="Pre-Listing")
    openset=[x for x in c if g(x,FS) in ("Construction Loan Closed","Draw Stage") and not x.get(SCD)]
    s["open_loans"]   = len(openset)
    s["funds_avail"]  = round(sum(x.get(CFA) or 0 for x in openset),2)
    s["funds_report"] = sum(1 for x in openset if x.get(CFA) is not None)
    und=sum(x.get(UND) or 0 for x in openset)
    s["capacity_pct"] = round((1-s["funds_avail"]/und)*100,1) if und else None
    closed=[x for x in c if g(x,LiS)=="Closed"]
    s["specs_sold_cum"]=len(closed)
    s["sold_volume"]  = sum(x.get(PURCH) or 0 for x in closed)
    s["priv_need"]    = round(sum(x.get(PML) or 0 for x in c if g(x,FS) in ("Private Money","Construction Loan Submitted","Appraisal")),2)
    ytd=[x for x in closed if (x.get(SCD) or "").startswith("2026")]
    s["specs_sold_ytd"]=len(ytd); s["sold_vol_ytd"]=sum(x.get(PURCH) or 0 for x in ytd)
    return s

def _ev(c, date_field, as_of, ok=None):
    w=windows(as_of); out={}
    for lab,(a,b) in w.items():
        out[lab]=sum(1 for x in c if (not ok or ok(x)) and (x.get(date_field) or "") and a.isoformat()<=x.get(date_field)<=b.isoformat())
    return out

def kcm_events(specs, as_of):
    c=_cells(specs); g=lambda x,f:_name(x.get(f))
    return {
     "New Starts":  _ev(c,START,as_of),
     "Specs Sold":  _ev(c,SCD,as_of, ok=lambda x:g(x,LiS)=="Closed"),
     "Loans Approved":_ev(c,LOANCLOSE,as_of, ok=lambda x:g(x,FS) in ("Construction Loan Closed","Draw Stage","Paid Off")),
     "Lot Contracts":_ev(c,LOTCONTRACT,as_of, ok=lambda x:g(x,LotS) not in REJECT),
     "Lots Funded": _ev(c,LOTFUNDED,as_of, ok=lambda x:g(x,LotS) not in REJECT),
     "Lot Closings":_ev(c,LOTPURCH,as_of, ok=lambda x:g(x,LotS) not in REJECT),
     "Listed Specs":_ev(c,LISTDATE,as_of),
    }

def _dom(listdate, as_of):
    if not listdate: return "-"
    return (as_of - date.fromisoformat(listdate[:10])).days

def _loan(x):
    """Per-home construction-loan position: (owed, cap%).
    owed = Construction Loan Amount - Construction Funds Available, i.e. everything
    consumed on the loan to date (pre-draw lot/closing consumption + draws + interest).
    cap% = owed / loan amount — matches the base's gated Loan Capacity Used % formula.
    Both None until the HUD's Undisbursed figure is entered (intentional gate).
    Added 2026-08-24, Wyatt's ask: loan capacity vs actually drawn, per home."""
    loan=x.get(LOANAMT); cfa=x.get(CFA)
    if loan and cfa is not None:
        owed=loan-cfa
        return round(owed), round(owed/loan*100)
    return None, None

def _bank(x, g, lender_map):
    person=g(x,CLENDER)
    return lender_map.get(person, person or "-")

def kcm_listings(specs, as_of, lender_map):
    c=_cells(specs); g=lambda x,f:_name(x.get(f)); rows=[]; tot=0
    for x in c:
        if g(x,LiS)=="Active Listing":
            pp=x.get(NPP) or 0; tot+=pp
            owed,cap=_loan(x)
            rows.append(dict(addr=g(x,ADDR), stage=g(x,CS), dom=_dom(x.get(LISTDATE),as_of),
                             list=x.get(LISTP), profit=round(pp),
                             bank=_bank(x,g,lender_map), owed=owed, cap=cap))
    rows.sort(key=lambda r:(r["dom"] if isinstance(r["dom"],int) else 0))
    return rows, round(tot)

def kcm_under_contract(specs, lender_map):
    c=_cells(specs); g=lambda x,f:_name(x.get(f)); rows=[]; tot=0
    for x in c:
        if g(x,LiS)=="Under Contract":
            pp=x.get(NPP) or 0; tot+=pp
            rows.append(dict(addr=g(x,ADDR), purch=x.get(PURCH), vs=(x.get(PURCH) or 0)-(x.get(PROJLIST) or 0),
                             profit=round(pp), close=x.get(PROJCLOSE),
                             bank=_bank(x,g,lender_map)))
    return rows, round(tot)

def kcm_coming(specs, lender_map):
    c=_cells(specs); g=lambda x,f:_name(x.get(f)); rows=[]; tot=0
    for x in c:
        if g(x,LiS)=="Pre-Listing":
            pp=x.get(NPP) or 0; tot+=pp
            plan=g(x,PLAN) or ""
            plan=plan.rsplit("-",1)[0] if plan and plan.rsplit("-",1)[-1].isdigit() else plan
            sf=_lk(x.get(SF))
            owed,cap=_loan(x)
            rows.append(dict(addr=g(x,ADDR), plan=plan, sf=sf, stage=g(x,CS),
                             list=x.get(PROJLIST), profit=round(pp),
                             bank=_bank(x,g,lender_map), owed=owed, cap=cap))
    return rows, round(tot)

# Active pipeline = lots in progress that have NOT yet closed a construction loan
# (Randall's ask, 2026-08-17): the deals sitting before Pre-Listing that never appeared
# on the card except inside the "Private $ Need (Lots)" total. Scope (Derrick 2026-08-17):
# Lot Purchased or Lot Under Contract, finance status Private Money / Construction Loan
# Submitted / none (i.e. NOT Construction Loan Closed, Draw Stage or Paid Off), excluding
# the rejected offer and the Underwriting stub. Total private-money need ties to kcm_state
# priv_need exactly.
PIPE_LISTED = {"Closed", "Active Listing", "Under Contract", "Pre-Listing"}
PIPE_LOANCLOSED = {"Construction Loan Closed", "Draw Stage", "Paid Off"}
PIPE_LOTS = {"Lot Purchased", "Lot Under Contract"}
_FIN_LABEL = {"Construction Loan Submitted": "Loan Submitted", "Private Money": "Private Money"}
_FIN_ORDER = {"Construction Loan Submitted": 0, "Private Money": 1}

def kcm_pipeline(specs):
    c = _cells(specs); g = lambda x, f: _name(x.get(f)); rows = []; tot_need = 0
    for x in c:
        if g(x, LiS) in PIPE_LISTED:            continue
        if g(x, LotS) not in PIPE_LOTS:         continue
        if g(x, FS) in PIPE_LOANCLOSED:         continue
        need = x.get(PML) or 0; tot_need += need
        plan = g(x, PLAN) or ""
        plan = plan.rsplit("-", 1)[0] if plan and plan.rsplit("-", 1)[-1].isdigit() else plan
        fin = g(x, FS)
        rows.append(dict(spec_id=(g(x, SPECID) or "-").strip(),
                         addr=(g(x, ADDR) or "-").strip(), plan=plan.strip(), lot=g(x, LotS) or "-",
                         fin=_FIN_LABEL.get(fin, "-" if not fin else fin),
                         fin_key=fin or "", need=round(need)))
    # closest-to-closing first (loan submitted), then private money, then acquisition (lot UC);
    # within a group, alphabetical by Spec ID (Subdivision-Lot#) so raw lots without an address
    # still sort deterministically and read as grouped subdivisions.
    rows.sort(key=lambda r: (_FIN_ORDER.get(r["fin_key"], 2), r["spec_id"]))
    return rows, round(tot_need)

def kcm_lenders(specs, lender_map):
    c=_cells(specs); g=lambda x,f:_name(x.get(f)); banks={}
    for x in c:
        if g(x,FS) in ("Construction Loan Closed","Draw Stage") and not x.get(SCD):
            person=g(x,CLENDER); bank=lender_map.get(person, person or "Unassigned")
            b=banks.setdefault(bank, dict(bank=bank, contact=person, n=0, avail=0.0, und=0.0))
            b["n"]+=1; b["avail"]+=(x.get(CFA) or 0); b["und"]+=(x.get(UND) or 0)
    for b in banks.values():
        b["cap"]=round((1-b["avail"]/b["und"])*100,1) if b["und"] else 0.0
        b["avail"]=round(b["avail"])
    return sorted(banks.values(), key=lambda b:-b["n"])

# ============================================================================
# FLIPS  (Wyatt's ask 2026-10-01: Capital Heights / Pea Ridge / Other, projected profit or loss)
# Everything derives live from the Flips table (tbl85RQGyIIwFbGY3) at build time, same rules as Specs:
# flag-not-filter (a blank input prints MISSING, never $0), projected/actual symmetry (actual profit
# and ROI exist only once the base's gated formulas produce them), Dead Deals excluded.
# ============================================================================
FL_ADDR="fldB9fGvRzG06eC0D"; FL_SUB="fldQZB5RxnR7C7Fsm"; FL_CITY="fldz6QAXEi4I5yeTk"
FL_LIS="fldHbhrsikuLXtrJM"; FL_ACQS="fldjOjaMXqDaa8j3c"; FL_REHS="fldpzzKw2nVCMHVu7"; FL_PHASE="fldwLpQ91N9JyaPq8"
FL_PURCH="fldxFaKEkMTjbjjon"; FL_REHB="fldUQ5m5z289QfOFB"; FL_REHA="fld6qNoC35AQateYW"
FL_PROJLIST="flds0RIRAamKGuuml"; FL_LIST="fldQV23GJoKqDlKJ1"; FL_SALE="fld7z9i89aFUg0HEt"
FL_NPP="fldPHD7zCeJs7ma4d"; FL_NAP="fldwtQLuQISVHTS2D"; FL_ROI="fldCzYcWlwKu5PejL"; FL_DAYS="fldFEA67WmTzYs0az"
FL_ACQD="fldwVwEq8XXbyIvcW"; FL_LISTD="fldxYyyh9Gllt78Mv"; FL_CLOSED="fldbZ1w6ax2am0rlD"; FL_PROJCLOSE="fld7uMzMxcvtRVKXQ"
FL_PML="fldfWBxlXPDa7CrQ5"; FL_GAP="fldb3JV0RpRS9Dad6"
FL_OTHER="Other"
_PHASE_ORDER={"Selling":0,"Rehab":1,"Acquisition":2,"Sold":3}

def _flip_cells(flips):
    out=[]
    for r in flips:
        x=r["cellValuesByFieldId"]
        if _name(x.get(FL_ACQS))=="Dead Deal": continue   # dead deals never ride into the report
        out.append(x)
    return out

def _days_held(x, as_of):
    """Mirror of the base's Days Held formula so the number is as-of the brief date, not render time."""
    a=x.get(FL_ACQD)
    if not a: return None
    end=date.fromisoformat(x.get(FL_CLOSED)[:10]) if x.get(FL_CLOSED) else as_of
    return (end-date.fromisoformat(a[:10])).days

def kcm_flips(flips, as_of):
    c=_flip_cells(flips); g=lambda x,f:_name(x.get(f))
    rows=[]
    for x in c:
        phase=g(x,FL_PHASE) or "Acquisition"
        stage=(g(x,FL_LIS) if phase in ("Selling","Sold") else g(x,FL_REHS) if phase=="Rehab" else g(x,FL_ACQS)) or "-"
        sub=(g(x,FL_SUB) or "").strip()
        rows.append(dict(addr=(g(x,FL_ADDR) or "-").strip(), city=g(x,FL_CITY) or "", sub=sub or FL_OTHER, sub_missing=not sub,
                         phase=phase, stage=stage, days=_days_held(x,as_of),
                         purch=x.get(FL_PURCH), rehab=x.get(FL_REHB), rehab_actual=x.get(FL_REHA), proj_list=x.get(FL_PROJLIST), list=x.get(FL_LIST), sale=x.get(FL_SALE),
                         npp=x.get(FL_NPP), nap=x.get(FL_NAP), roi=x.get(FL_ROI),
                         lender=g(x,FL_PML) or "-", gaps=(x.get(FL_GAP) or "").strip(), closed=x.get(FL_CLOSED), proj_close=x.get(FL_PROJCLOSE)))
    rows.sort(key=lambda r:(_PHASE_ORDER.get(r["phase"],9), r["addr"]))
    groups=[]
    for r in rows:
        if not groups or groups[-1]["name"]!=r["sub"]:
            groups.append(dict(name=r["sub"], rows=[], proj=0.0, proj_n=0, n=0))
        grp=groups[-1]; grp["rows"].append(r)
        if r["phase"]!="Sold":
            grp["n"]+=1
            if r["npp"] is not None: grp["proj"]+=r["npp"]; grp["proj_n"]+=1
    active=[r for r in rows if r["phase"]!="Sold"]
    sold=[r for r in rows if r["phase"]=="Sold"]
    sold_ytd=[r for r in sold if (r["closed"] or "").startswith(str(as_of.year))]
    s=dict(active=len(active),
           acquiring=sum(1 for r in active if r["phase"]=="Acquisition"),
           rehab=sum(1 for r in active if r["phase"]=="Rehab"),
           selling=sum(1 for r in active if r["phase"]=="Selling"),
           proj=round(sum(r["npp"] for r in active if r["npp"] is not None)),
           proj_n=sum(1 for r in active if r["npp"] is not None),
           sold_ytd=len(sold_ytd),
           realized=round(sum(r["nap"] for r in sold_ytd if r["nap"] is not None)),
           realized_n=sum(1 for r in sold_ytd if r["nap"] is not None),
           avg_days=round(sum(r["days"] for r in active if r["days"] is not None)/max(1,sum(1 for r in active if r["days"] is not None))) if any(r["days"] is not None for r in active) else None)
    events={
     "Flips Acquired": _ev(c,FL_ACQD,as_of),
     "Flips Listed":   _ev(c,FL_LISTD,as_of),
     "Flips Sold":     _ev(c,FL_CLOSED,as_of, ok=lambda x:g(x,FL_LIS)=="Closed"),
    }
    flags=[(r["addr"], r["gaps"]) for r in rows if r["gaps"]]
    return dict(groups=groups, rows=rows, state=s, events=events, flags=flags)
