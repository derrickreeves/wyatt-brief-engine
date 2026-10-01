# -*- coding: utf-8 -*-
"""ORCHESTRATOR — turn a directory of saved source pulls into the printable brief.

The nightly agent pulls each source ONCE (MCP), saves raw JSON to <pulls>/<name>.json,
then runs:   python3 build_brief.py <pulls_dir> <as_of YYYY-MM-DD> <out.pdf>

This file does ZERO network I/O. It parses the saved pulls into the computed M dict
(one key per division block), then hands M to build_payload_engine.build() -> payload,
writes payload.json next to the PDF, and renders. Deterministic: same pulls in, same
PDF out, every night. Adding a division = save its pull + add a parse block here + a
builder in build_payload_engine.py.

Canonical pull filenames (saved by the shift):
  kcm_specs.json          KCM construction base — Specs table (list_records raw)
  kcm_forms.json          KCM team daily forms
  kcm_flips.json          KCM construction base — Flips table (optional; adds the FLIPS block)
  ascend_overview.json    Ascend overview (members/mrr/churn)
  ascend_kpi.json         Ascend pipeline KPI forms
  ascend_ads.json         Windsor Meta rows for the Ascend ad account
  cowork_overview.json    Coworking overview
  cowork_kpi.json         Coworking pipeline KPI forms
  cowork_bookings.json    Coworking event-booking rows
  cowork_ads.json         Windsor Meta rows for the Coworking ad account
  rentals_overview.json   Rentals overview (occupancy/units/balance)
  rentals_kpi.json        Rentals leasing activity forms
  felc_rooms.json         Fundamentals ELC base (appi00AKQ9TZaJIFN) Rooms — all rows, all fields
  felc_children.json      Fundamentals ELC base Children — all rows (departed kids stay for churn)
  felc_staff.json         Fundamentals ELC base Staff — all rows
  felc_waitlist.json      Fundamentals ELC base Waitlist — all rows
  felc_kpi.json           Fundamentals KPI's form table (app8A3ZyxQaghkq1m / tbluQyQGQne6QbvH6),
                          prior-month-start onward
  felc_organic.json + felc_organic_posts.json  Windsor facebook_organic, page 207866299354865
                          (same shape as cowork_organic / cowork_organic_posts)
  registry_fundamentals.json  Scorecard Mapping rows for Division link recjcgZ56583xTGkd
  registry_team.json      Scorecard Mapping rows for Division link recehpKOQAF4Zz3y2 (Kaizen Team)
  fub_deals.json          KPI Scorecard base FUB Deals (tblo0a8nb7hFSglKi) — all rows, all fields.
                          Written nightly 12:30 AM by n8n "FUB → KPI Scorecard nightly" (fUoKD2P85WcPgPSw).
  fub_calls.json          FUB Calls (tbldBKWQd71IknYja) — all rows (rolling 45 days)
  fub_rental.json         FUB Rental Leads (tblcmBjaxkKdXcQIb) — all rows
  fub_leads.json          FUB New Leads (tblXY9qzt3QZRYX2z) — all rows (rolling 60 days)
  fub_users.json          FUB Users (tbl21PFnad40vLOqJ) — all rows (agent roster: name, role, status)
"""
import json, os, sys, subprocess
from datetime import date
import brief_engine as E
import kcm as K
import build_payload_engine as BP

# --------------------------------------------------------------------------
# field IDs
# --------------------------------------------------------------------------
# KCM daily forms
F_DATE="fldQBhqe75egflhy0"; F_CONV="fldCs0I6edbUun2GF"; F_LEAD="fldBP0kmCfokC2cmx"
F_SHOWL="fldExlKs1MzaUh23Z"; F_BUYS="fldcSWGeEgYwqpwsh"; F_PREAPP="fldKh0PnSoCKvWew1"
F_PRESOLD="fldhA9GXiacavYgJl"
# Ascend overview
AO_STAT="flduzAMWSYrRs7byH"; AO_REV="fldXsiSmPc0h5xrSX"; AO_UPD="fldXCgV7EEt5nCXSU"
# Member list (Randall ask 9/17, Derrick spec 2026-09-21): Contact name. The ascend_overview pull MUST include this field
# or the member list cannot render (the card then keeps the old prospect table rather than show blank names).
AO_NAME="fldwRuzV9tcR9Nk6r"
# Churn Date (Derrick added 2026-09-21): churn is counted on THIS field when it is filled, else it falls
# back to Start Date (fldXCgV7EEt5nCXSU, renamed from "Updated" 2026-09-21) as it always has.
AO_CHURN="fldKIimh8FKPaG6f5"
# Ascend KPI
AK_DATE="fldMCGXb9RmzY0FOS"; AK_ET="fldv2TPwlcXiAfHQn"; AK_MEM="fldYciTiq2FdXx2y7"
AK_EVT="fldaL62vRM0Eo85Eq"; AK_PHONE="fldNXYAisbDfjG5sm"; AK_EMAIL="fldbyLThL2EUCGQVB"; AK_NAME="fldXxbGvzs7JFr9wp"
# Coworking overview
CO_STAT="flduD1qpRNpvIpo7K"; CO_REV="fldD7vmzoVRpOLbZJ"
# Coworking KPI
CK_DATE="fldZZLoyUnLV3zg1e"; CK_ET="fldglMUgxI4VbDYoX"; CK_REV="fldWMFxLVOxsbFyZr"
CK_SPACE="fldBd0Tx3ULNuhWXy"; CK_NAME="fld1hQkRKFKG4Ccor"; CK_EVDATE="fldgiFg66ckTo1voJ"
CK_START="fldKKMyokZvmLSQ7L"; CK_END="fldmz66CiUKJaGrwD"
# Rentals overview
RO_OCC="fldUXdtaGpWsdC34V"; RO_UNITS="fldhGnvxhpYdOcSAC"; RO_BAL="fldT954tHBonMOpYm"
RO_DATE="fld0WK3Cqn8oEgzvd"; RO_COLIVING_VAC="fldjaoyZ1ftV8ObJ2"
# Per-property (units, vacant, occupancy%) field triplets — mapped 2026-08-12 by matching the
# live row against the 8/11 send's property stats (unit counts are unique per property).
RO_PROPS=[("Corbin","fldiN54TKGOoep3q8","fldezWbRUjmV93t9i","fldhcbc69nCKhmmwf"),
          ("Cane Market","fldsN9FqtflYD9sU1","fldZYksjC4DVj2YDd","fldKwVpl4Mzzr0iK6"),
          ("Sunset","fldM2pN3PiB1g8VfF","fldXMfce1s2a54NsM","fldReR6fvwwBre4U5"),
          ("Cade's Lake","fldWjyvHXL32Di9ID","fldunbmoW7RuwdMVq","flddIJDyDBb0muvhW"),
          ("Greenwell Springs","fldihKkZn05tblSri","fldPZAGN1Fj8rP2X3","fldp6gDDGYJHrzw1O")]
# Rentals KPI
RK_DATE="fld4kOVsaSICYJDPu"
RK={"Leads":"fld8zL1I5JOs4T66T","Conversations":"fld5StD4hkWOAYwUH","Appointments Set":"fldxWD40JUuJNkNok",
    "Showings":"fldsvYDsWCA0v4cGV","Applications":"fldObKkY9qXedpnei","New Leases":"fldFc1iXPBEMaOqwh",
    "Renewals":"fldhPlwn358h1yu8X","Notice Given":"fld9VgTpGZsYeMiZY","Evictions":"fldy6lixAYCLZhDmR",
    "Leased by Arkie":"fldgvl2RWehinaSw6","Leased by Tommy":"fldhisyxHBEqjmBgN"}
# Rentals KPI table gained an Entry Type field (Arkie / Lara Harris / Tommy Sigman) + Tommy's form 2026-09-10.
# The engine SUMS each metric field across ALL rows, so no Entry-Type filter is needed: Leads/Conversations/
# Appointments Set are filled by Arkie AND Tommy (combined total, correct), Showings..Evictions by Lara, and
# each "Leased by <person>" field only by that person. The rentals_kpi pull MUST include every field ID in RK
# above (now including Leased by Tommy fldhisyxHBEqjmBgN) so a new metric can never silently drop.
# --- Follow Up Boss landing tables (KPI Scorecard base), synced nightly by n8n. Built 2026-09-21.
# FUB Deals
FD_ID="fldHp5onEIO4cq2w2"; FD_ADDR="fldZaaZOCG66kVK5Z"; FD_PIPE="fld21GHkYdbH0I1Iu"; FD_STAGE="fld15qKKY0RLJwy2A"
FD_STATUS="fld9CmHc4jMpRTdYr"; FD_AGENT="fld1x3wsSI7TdozZu"; FD_CLIENT="fldq95nRU3FVYgA2Y"; FD_PRICE="fldzWEfnqYxJFqd53"
FD_COMM="fldrmqzdZS6LiA6Sd"; FD_AGCOMM="fldcfHTfH3oxpsfYF"; FD_CREATED="flddXBoOP61W3yJFn"; FD_ENTERED="fld15q5JL4FHh93kL"
FD_CLOSED="fld4evv9AAZzTw9C5"; FD_PROJ="fldeVay92uEBAwxIE"; FD_APPTSET="flduoFL4ss12CkC1i"; FD_APPTMET="fldS3QifMRMyPdkle"
FD_SIGNED="fldlARhsOtA10nibp"; FD_UC="fldrDl9EUXmiDXIw0"; FD_MLS="flddRAnb4f7JGy90y"; FD_CITY="fldAnOFJkP7rvC04d"
# FUB Calls
FC_DATE="flduvIpeKtO7Svwqw"; FC_USER="fldMi770tD7BtQg3B"; FC_DIR="fldTZdC5BdC8PwnRp"; FC_DUR="fldV4sW5X97woBaFn"; FC_CONV="fldROHysmOxeX79mJ"
# FUB Rental Leads
FRL_STAGE="fldPgyiu261YzDzY5"; FRL_SRC="fldWbHeGzEB3gdKbU"; FRL_ASSIGN="fld5ldL4HpAepznu7"; FRL_PROP="fldvp8yrpVOZexdAx"
FRL_CREATED="fldhvuoGSzULVAlns"; FRL_CHANGED="fldcCpSfINIe2BNtz"; FRL_NAME="fldSYTQtQtnADKJ2d"
# FUB Users (roster)
FU_ID="fld8A3rfwWin37GTu"; FU_NAME="fldx8MAizZOzSgdPd"; FU_ROLE="fldylxlYnpqF3hXur"; FU_STATUS="fld5436MD5k4epzu6"
# FUB New Leads
FNL_CREATED="fldBB4gQzqdJCrgzd"; FNL_ASSIGN="fldZp2odvaSfcsIYA"; FNL_SRC="fldtkvtCFgThMQQTT"; FNL_STAGE="fld2VQkhAz4O0SDyc"
# Kaizen Team = the three agents the Scorecard Mapping names as owners of the Kaizen Team KPIs.
# Deals/calls/leads are attributed by FUB user name. Tommy also runs rentals, so he is counted on
# both cards on purpose (same as today's daily forms).
FUB_TEAM=("Laurie Rush","Danielle Story","Tommy Sigman")
FUB_RENTAL_USERS=("Arkie Aliponga","Tommy Sigman")
# FUB user rows that are not people (shared inboxes / entities) — never counted as agents.
FUB_NOT_AGENTS=("Accounting Team","Marketing Team","Ronae Properties")
# A "conversation" = a logged FUB call of 30+ seconds (n8n sets the checkbox; threshold lives there).
# Construction Lender contact -> bank, mirroring the Construction Lenders table in the
# KCM base (tbliqjk7SzbnhVjsd, Lender Name -> Bank Name). Rebuilt 2026-08-24: the old
# 4-key map keyed on bank nicknames that matched NO contact names, so every bank rollup
# fell through to the contact's name (Wyatt saw "Nicole Glover" as a bank).
LENDER_MAP={"Mac Field":"Bank of St. Francisville","Ron Anderson":"Hancock Bank",
            "Nicole Glover":"UCB","Don Greer":"Cotton Port Bank",
            "Joshua Prejean":"Bank of Zachary","Melissa Devall":"Synergy Bank",
            "Mark Juneau":"JD Bank","Julie Bennet":"Sabine Bank",
            "Eric Schmolke":"Louisiana National Bank"}
ASCEND_LAUNCH="2026-07-29"; COWORK_LAUNCH="2026-05-25"
SHARED_EVENTS={"Breakfast","Investor Meetup","Pickleball"}
# Fundamentals ELC operational base (appi00AKQ9TZaJIFN) — built live with Paige 2026-08-27.
# Rooms
FR_NAME="flde5oMnvs1vxsENI"; FR_AGE="fldbZ1txWbx0NubEm"; FR_CAP="fldo97Po7gX0klFnR"; FR_RATE="fldrg6d0FzPbSpXTR"
FR_STAFF="fldKsA9uluDtuKycn"; FR_ENR="fldOow0vNwUpIDHqf"; FR_OPEN="fldWvVHcqSUDQV6h0"; FR_WL="fldGEHqG8ihgsQJZR"; FR_REV="fldZOfdmPzlj5tOVn"
# Children  (Status choices: Enrolled / Not Returning / Withdrawn — schema-verified 2026-09-02)
FC_NAME="fldew0bEEHrm91l89"; FC_STAT="fldqcBEHKyjG7LXqB"; FC_START="fldLju3qnczVqAMhZ"; FC_END="fldqT3RWUjganrrmh"
FC_ROOM="fld1y4q8MwJxMzMix"; FC_TUITION="fldm5yKBqYK8b67vw"; FC_FLAGS="fldw6Pkbw5iVbRRKL"
# Staff  (Status: Active / Inactive)
FS_NAME="fldVKmmJ5SBcZPrDQ"; FS_STAT="fldFslXJSvaN8WYbn"; FS_HIRE="fldMvfNeMwyyHFBkV"; FS_END="fldEcZRVfsXw3n0Z4"
FS_CPR="fldq5bgrEoZUMND5r"; FS_FLAGS="fldGSZb9BVPFC10gL"
# Waitlist  (blank Status = Active by design; Active? formula = 1 counts toward depth)
FW_ACTIVE="fldpuGXYRkoYQ1U5T"; FW_TARGET="fldSYVKpIugXuDtWL"; FW_YEAR="fldo34w97dLU2i52X"; FW_FLAGS="fldfKoS3xfGgrXAHL"
# Fundamentals KPI's form table (app8A3ZyxQaghkq1m / tbluQyQGQne6QbvH6) — Paige's trimmed M-F form
FK_DATE="fldfQzNsMWuyldNFG"; FK_LEADS="fld9dslBh58J2SQQR"; FK_CONV="fld1TRabPSK3Sl7hg"; FK_TOURS="fldmETo2Etu15zr6J"
# Waitlist rows were bulk-imported on 2026-08-27 (one createdTime spike); created-in-window
# counts are only real from the next day. The form was re-pointed 8/27 and its first row
# landed 9/01; windows that predate it render "-" rather than a fake zero.
FELC_WAITLIST_LIVE="2026-08-28"; FELC_FORM_LIVE="2026-09-01"
# GO-LIVE GATE (Derrick 2026-09-02): the card joins the send whose as_of is on/after this date.
# The engine runs from the vault, so code lands live the moment it is saved; this constant is
# what keeps a Thursday run from shipping the card before the Friday 3 AM target (as_of 9/03).
# Before the gate the cover lists Fundamentals under "coming" and no card renders.
FELC_GO_LIVE_AS_OF="2026-09-03"
# Follow Up Boss work (Kaizen Home Sales & Services card + Rentals FUB funnel rows) is GATED OFF until Derrick
# gives the go (built 2026-09-21, held so the 9/22 send is untouched ahead of his 8 AM with Wyatt). Set the date
# to the first as-of that should carry it, or FUB_FORCE=1 in the environment for review renders only.
FUB_GO_LIVE_AS_OF="2099-01-01"
# Room display order = age progression, the way Paige reads her roster.
FELC_ROOM_ORDER=["Pink Room","Lime Room","Orange Room","Green Room","Brown Room","Red Room","Blue Room","Yellow Room","Purple Room"]
FELC_AFTERCARE="Purple Room"

# --- Registry (Scorecard Mapping) live goals pull, one file per division (saved by the shift).
# Goals + cadence come from here so Randall's edits flow to the report the next run.
# base appgWVT7izV2FBvqS / tblPn77ZeN37EFpnl. Missing file => that division falls back to
# the hardcoded literals in build_payload_engine (no crash, no blank goals).
REG_FILES={"kcm":"registry_kcm.json","ascend":"registry_ascend.json",
           "cowork":"registry_cowork.json","rentals":"registry_rentals.json",
           "fundamentals":"registry_fundamentals.json","team":"registry_team.json"}
REG_KPI="fldJneEqHnbmlmMRb"; REG_GOAL="fldLPpv1oY10sn7gE"; REG_CAD="fldgChMlnK0rqOqZi"; REG_STATUS="fldwPGQRS265R8LgF"
CAD_MAP={"Daily":"day","Weekly":"week","Monthly":"mo","Overview":"overview"}

def _load(pulls, name):
    p=os.path.join(pulls, name)
    return json.load(open(p)) if os.path.exists(p) else {"records":[]}

def _recs(obj):
    return obj.get("records", obj) if isinstance(obj, dict) else obj

def _cells(recs):
    return [r.get("cellValuesByFieldId", r.get("fields", {})) for r in recs]

def _nm(v):
    return E._name(v)

# --------------------------------------------------------------------------
# per-division parse blocks  ->  M
# --------------------------------------------------------------------------
def kcm_M(pulls, as_of):
    specs=_recs(_load(pulls,"kcm_specs.json"))
    forms=_recs(_load(pulls,"kcm_forms.json"))
    fc=_cells(forms)
    def w(field):
        # daily-form windowed sum of an integer field
        recs=[{"cellValuesByFieldId":c} for c in fc]
        return E.window_sum(recs, F_DATE, field, as_of)
    lst,lt=K.kcm_listings(specs, as_of, LENDER_MAP); uc,ut=K.kcm_under_contract(specs, LENDER_MAP); cm,ct=K.kcm_coming(specs, LENDER_MAP)
    return {
        "kcm_state":K.kcm_state(specs), "kcm_events":K.kcm_events(specs, as_of),
        "kcm_forms":{"conv":w(F_CONV),"lead":w(F_LEAD),
                     "show":_show(fc,as_of),"preapp":w(F_PREAPP),"presold":w(F_PRESOLD)},
        "kcm_listings":(lst,lt),"kcm_uc":(uc,ut),"kcm_coming":(cm,ct),
        "kcm_pipeline":K.kcm_pipeline(specs),
        "kcm_lenders":K.kcm_lenders(specs, LENDER_MAP),
        "kcm_dropped_funds":list(K.DROPPED_FUNDS),
        # Flips (added 2026-10-01, Wyatt's ask). Only when the shift pulled kcm_flips.json; a missing pull
        # omits the block rather than printing an empty table, so a workflow without the node still renders.
        "kcm_flips":(K.kcm_flips(_recs(_load(pulls,"kcm_flips.json")), as_of)
                     if os.path.exists(os.path.join(pulls,"kcm_flips.json")) else None),
    }

def _show(fc, as_of):
    recs=[{"cellValuesByFieldId":c} for c in fc]
    a=E.window_sum(recs, F_DATE, F_SHOWL, as_of); b=E.window_sum(recs, F_DATE, F_BUYS, as_of)
    return {k:a[k]+b[k] for k in a}

def ascend_M(pulls, as_of):
    ov=_cells(_recs(_load(pulls,"ascend_overview.json")))
    kpi=_recs(_load(pulls,"ascend_kpi.json")); kc=_cells(kpi)
    members=sum(1 for c in ov if _nm(c.get(AO_STAT))=="Member")
    # Roster statuses are Member / Non-Paying Member / Churned (schema-verified 2026-08-12).
    nonpay=sum(1 for c in ov if _nm(c.get(AO_STAT))=="Non-Paying Member")
    churned=sum(1 for c in ov if _nm(c.get(AO_STAT))=="Churned")
    mrr=sum(c.get(AO_REV) or 0 for c in ov if _nm(c.get(AO_STAT))=="Member")
    def et(name): return E.entry_type_match(AK_ET, name)
    recs=[{"cellValuesByFieldId":c} for c in kc]
    ov_recs=[{"cellValuesByFieldId":c} for c in ov]
    # Entry Type choice is "RSVP's" (NOT "Mastermind RSVP") — schema-verified 2026-08-12.
    # RULING (Derrick, 2026-08-12, supersedes the 7/21 no-Event-Type-gate rule): the Mastermind
    # RSVP rows count ONLY Event Type = "Ascend Mastermind". Breakfast / Pickleball / Investor
    # Meetup are SHARED events (brokerage + Ascend) and report on their own lines / the shared
    # card, never inside the Mastermind rows. Caveat carried from the 7/14 incident: if the team
    # stops stamping Event Type, these rows silently undercount — blank-EVT RSVP rows are the smell.
    AM="Ascend Mastermind"
    pipe={
      "new_leads":E.window_count(recs,AK_DATE,as_of,et("New Lead")),
      "rsvp_nm":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="RSVP's" and _nm(c.get(AK_EVT))==AM and _nm(c.get(AK_MEM))!="Member"),
      "rsvp_m":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="RSVP's" and _nm(c.get(AK_EVT))==AM and _nm(c.get(AK_MEM))=="Member"),
      "att_nm":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="Attended Event" and _nm(c.get(AK_MEM))!="Member"),
      "att_m":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="Attended Event" and _nm(c.get(AK_MEM))=="Member"),
      # Event-specific RSVP line (SOP): Entry Type = RSVP's + that Event Type.
      "breakfast":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="RSVP's" and _nm(c.get(AK_EVT))=="Breakfast"),
      # New Members = Entry Type "Members" EXCLUDING Churned status — the roster logs a churn
      # as an ET "Members" row with Membership Status = Churned (verified live: Xavier Reyes
      # 2026-08-10), so counting ET alone reads a churn as a new member. Found in the 8/12
      # validation run against the known-good 8/11 send (engine said 1, truth 0).
      "new_members":E.window_count(recs,AK_DATE,as_of,lambda c:_nm(c.get(AK_ET))=="Members" and _nm(c.get(AK_MEM))!="Churned"),
      # Churn is ROSTER-INFERRED (no "Churned Member" entry type exists): Overview rows at
      # Membership Status = Churned, windowed on the roster Updated stamp. Only the recent
      # windows are trustworthy — the payload renders LastMo as "-" for this row.
      "churn":E.window_count([{"cellValuesByFieldId":dict(r["cellValuesByFieldId"],**{AO_UPD:(r["cellValuesByFieldId"].get(AO_CHURN) or r["cellValuesByFieldId"].get(AO_UPD))})} for r in ov_recs],
                            AO_UPD,as_of,lambda c:_nm(c.get(AO_STAT))=="Churned"),
    }
    funnel=_ascend_funnel(kc, as_of)
    ads=E.ad_windows(_ad_rows(_load(pulls,"ascend_ads.json")), as_of, ASCEND_LAUNCH)
    org=_organic(pulls,"ascend_organic.json","ascend_organic_posts.json",as_of)
    # Member list: paying + non-paying, alphabetical by name as written on the roster.
    # "since" = the roster date field; rate = Revenue. Rows without a name are dropped, so a pull
    # that lacks AO_NAME yields an empty list and the card falls back (see build_payload_engine).
    mlist=[dict(name=(c.get(AO_NAME) or "").strip(), since=c.get(AO_UPD) or "", rate=c.get(AO_REV) or 0,
                paying=_nm(c.get(AO_STAT))=="Member")
           for c in ov if _nm(c.get(AO_STAT)) in ("Member","Non-Paying Member") and (c.get(AO_NAME) or "").strip()]
    mlist.sort(key=lambda r:r["name"].lower())
    return {"ascend_roster":{"members":members,"mrr":mrr,"churned":churned},"ascend_nonpay":nonpay,"ascend_members":mlist,
            "ascend_pipe":pipe,"ascend_funnel":funnel,"ascend_ads":ads,"ascend_org":org}

def _ascend_funnel(kc, as_of):
    # Mirrors the Mastermind RSVPs (Non-Member) row — same Event Type gate (Derrick 2026-08-12).
    mtd0=as_of.replace(day=1).isoformat()
    rows=[]
    for c in kc:
        if _nm(c.get(AK_ET))=="RSVP's" and _nm(c.get(AK_EVT))=="Ascend Mastermind" and _nm(c.get(AK_MEM))!="Member":
            d=c.get(AK_DATE)
            if d and d>=mtd0:
                rows.append(dict(name=_nm(c.get(AK_NAME)) or "-", date=d,
                                 phone=c.get(AK_PHONE) or "-", email=c.get(AK_EMAIL) or "-"))
    rows.sort(key=lambda r:r["date"], reverse=True)
    return rows

def cowork_M(pulls, as_of):
    ov=_cells(_recs(_load(pulls,"cowork_overview.json")))
    kpi=_recs(_load(pulls,"cowork_kpi.json")); kc=_cells(kpi)
    members=sum(1 for c in ov if _nm(c.get(CO_STAT))=="Member")
    unpaid=sum(1 for c in ov if _nm(c.get(CO_STAT))=="Unpaid")
    churned=sum(1 for c in ov if _nm(c.get(CO_STAT))=="Churned")
    mrr=sum(c.get(CO_REV) or 0 for c in ov if _nm(c.get(CO_STAT))=="Member")
    recs=[{"cellValuesByFieldId":c} for c in kc]
    def et(name): return E.entry_type_match(CK_ET, name)
    # Entry Type choice names schema-verified 2026-08-12 (plural/booked forms — the singular
    # names silently counted ZERO across the whole pipeline).
    pipe={
      "new_leads":E.window_count(recs,CK_DATE,as_of,et("New Leads")),
      "conv":E.window_count(recs,CK_DATE,as_of,et("Conversations")),
      "tours":E.window_count(recs,CK_DATE,as_of,et("Free Tours Booked")),
      "verbal":E.window_count(recs,CK_DATE,as_of,et("Verbal Commitments")),
      "new_members":E.window_count(recs,CK_DATE,as_of,et("Members")),
      "events":E.window_count(recs,CK_DATE,as_of,et("Events Booked")),
      "event_rev":E.window_sum(recs,CK_DATE,CK_REV,as_of,et("Events Booked")),
      "day_pass":E.window_count(recs,CK_DATE,as_of,et("Day Passes Booked")),
    }
    bookings=_cowork_bookings(kc, as_of)
    ads=E.ad_windows(_ad_rows(_load(pulls,"cowork_ads.json")), as_of, COWORK_LAUNCH)
    org=_organic(pulls,"cowork_organic.json","cowork_organic_posts.json",as_of)
    return {"cowork_roster":{"members":members,"unpaid":unpaid,"churned":churned,"mrr":mrr},
            "cowork_pipe":pipe,"cowork_bookings":bookings,"cowork_ads":ads,"cowork_org":org}

def _cowork_bookings(kc, as_of):
    # UPCOMING events, rolling next 30 days (Randall's ask, 2026-08-21; replaces the
    # previous-month listing). Window = event date in (as_of, as_of+30] — as_of is the
    # completed day, so the window starts the morning Wyatt reads the brief. Also counts
    # the tail beyond 30 days so booked-out revenue stays visible.
    # NOTE: the cowork_kpi PULL must include Events Booked rows with a future event date
    # regardless of booking date (a June booking for an August event otherwise falls
    # outside the prior-month-start pull filter and silently vanishes from this table).
    from datetime import timedelta
    lo=as_of.strftime("%Y-%m-%d"); hi=(as_of+timedelta(days=30)).strftime("%Y-%m-%d")
    rows=[]; beyond_count=0; beyond_rev=0
    for c in kc:
        if _nm(c.get(CK_ET))=="Events Booked":
            ev=c.get(CK_EVDATE)
            if not ev or ev<=lo: continue
            if ev<=hi:
                rows.append(dict(name=_nm(c.get(CK_NAME)) or "-", booked=c.get(CK_DATE),
                                 evdate=ev, start=c.get(CK_START), end=c.get(CK_END),
                                 space=_nm(c.get(CK_SPACE)) or "-", rev=c.get(CK_REV) or 0))
            else:
                beyond_count+=1; beyond_rev+=c.get(CK_REV) or 0
    rows.sort(key=lambda r:r["evdate"])
    return {"rows":rows,"beyond_count":beyond_count,"beyond_rev":beyond_rev}

def rentals_M(pulls, as_of):
    ov=_cells(_recs(_load(pulls,"rentals_overview.json")))
    o={"occ":None,"units":None,"balance":0,"snap_date":None,"coliving_vac":0,"props":[],"vacant_total":None}
    if ov:
        c=ov[0]
        props=[dict(name=n, units=c.get(u) or 0, vac=c.get(v) or 0, occ=c.get(p))
               for n,u,v,p in RO_PROPS]
        o={"occ":c.get(RO_OCC),"units":c.get(RO_UNITS),"balance":c.get(RO_BAL) or 0,
           "snap_date":c.get(RO_DATE),"coliving_vac":c.get(RO_COLIVING_VAC) or 0,
           "props":props,"vacant_total":sum(p["vac"] for p in props)}
    kpi=_recs(_load(pulls,"rentals_kpi.json")); kc=_cells(kpi)
    recs=[{"cellValuesByFieldId":c} for c in kc]
    act={name:E.window_sum(recs, RK_DATE, fid, as_of) for name,fid in RK.items()}
    return {"rentals_ov":o,"rentals_act":act}

def _has_user(cell, users):
    s = (cell or "")
    return any(u in s for u in users)

def _prop_of(tags):
    t=(tags or "").lower()
    for k,v in (("cane","Cane Market"),("corbin","Corbin"),("sunset","Sunset Village"),("cade","Cade's Lake"),("greenwell","Greenwell Springs")):
        if k in t: return v
    return "(no property tag)"

def _fub_dates(deals):
    """Give every deal one date per funnel step. Sisu's custom date wins; when it is blank and the deal
    currently sits in that stage, the day it entered the stage stands in (FUB keeps only the current
    stage's entry date, so earlier steps of an undated deal stay uncounted rather than guessed)."""
    fam={"Appointment Met":FD_APPTMET,"Signed":FD_SIGNED,"Pending":FD_UC,"Buyer Contract":FD_UC,"Closed":FD_CLOSED}
    for r in deals:
        c=r["cellValuesByFieldId"]; st=c.get(FD_STAGE) or ""
        c["_set"]=c.get(FD_APPTSET) or (c.get(FD_ENTERED) if st=="Appointment Set" else None)
        c["_met"]=c.get(FD_APPTMET) or (c.get(FD_ENTERED) if st=="Appointment Met" else None)
        c["_signed"]=c.get(FD_SIGNED) or (c.get(FD_ENTERED) if st=="Signed" else None)
        c["_uc"]=c.get(FD_UC) or (c.get(FD_ENTERED) if st in ("Pending","Buyer Contract") else None)
        c["_closed"]=c.get(FD_CLOSED) or (c.get(FD_ENTERED) if st=="Closed" else None)
    return deals

def fub_M(pulls, as_of):
    """Kaizen Team (brokerage) + Rentals funnel rows, straight from the FUB landing tables.
    Every window count is a dated record, never a hand-typed number: deals count on the Sisu
    date fields FUB carries (appt set/met, signed, under contract, closed) with the stage-entry
    date as the stand-in (see _fub_dates), calls on Call Date, leads on Created, rental stage
    moves on Stage Changed."""
    deals=_fub_dates([{"cellValuesByFieldId":c} for c in _cells(_recs(_load(pulls,"fub_deals.json")))])
    calls=[{"cellValuesByFieldId":c} for c in _cells(_recs(_load(pulls,"fub_calls.json")))]
    rent =[{"cellValuesByFieldId":c} for c in _cells(_recs(_load(pulls,"fub_rental.json")))]
    leads=[{"cellValuesByFieldId":c} for c in _cells(_recs(_load(pulls,"fub_leads.json")))]
    # Every sales pipeline counts (Sisu Buyers/Sellers for the team, the older Buyers/Sellers pipelines are
    # still what most of the office works in); Rentals excluded; Deleted/Archived never count.
    # Open-pipeline SNAPSHOTS also skip deals that entered their stage over a year ago (2018-2022 "pending"
    # rows nobody closed out) — counted as stale, never as pipeline. Windowed counts are unaffected.
    live=lambda c: (c.get(FD_STATUS) or "") == "Active" and (c.get(FD_PIPE) or "") != "Rentals"
    from datetime import timedelta as _td
    stale_before=(as_of-_td(days=365)).isoformat()
    fresh=lambda c: (c.get(FD_ENTERED) or "9999") >= stale_before
    def metrics(who):
        """who(cell)->bool on the Agent / User / Assigned To text."""
        dl=lambda c: live(c) and who(c.get(FD_AGENT))
        return {
        "New Leads":        E.window_count(leads, FNL_CREATED, as_of, lambda c: who(c.get(FNL_ASSIGN))),
        "Conversations":    E.window_count(calls, FC_DATE, as_of, lambda c: bool(c.get(FC_CONV)) and who(c.get(FC_USER))),
        "Appointments Set": E.window_count(deals, "_set", as_of, dl),
        "Appointments Met": E.window_count(deals, "_met", as_of, dl),
        "Signed Clients":   E.window_count(deals, "_signed", as_of, dl),
        "Contracts":        E.window_count(deals, "_uc", as_of, dl),
        "Closings":         E.window_count(deals, "_closed", as_of, dl),
        "GCI (After COS)":  E.window_sum(deals, "_closed", FD_COMM, as_of, dl),
        }
    act=metrics(lambda s: _has_user(s, FUB_TEAM))
    agents=[]
    for a in FUB_TEAM:
        m=metrics(lambda s, a=a: a in (s or ""))
        agents.append({"name":a,"leads":m["New Leads"]["MTD"],"conv":m["Conversations"]["MTD"],"set":m["Appointments Set"]["MTD"],
                       "met":m["Appointments Met"]["MTD"],"signed":m["Signed Clients"]["MTD"],"uc":m["Contracts"]["MTD"],
                       "closed":m["Closings"]["MTD"],"gci":m["GCI (After COS)"]["MTD"]})
    team=lambda c: live(c) and _has_user(c.get(FD_AGENT), FUB_TEAM)
    # open pipeline (team, Active, not Closed/Lost) grouped by stage family
    fam={"Appointment Set":"Appt Set","Appointment Met":"Appt Met","Signed":"Signed","Pipeline":"Pipeline",
         "Listed":"Listed","Mls Live Listings":"Listed","Buyer Contract":"Under Contract","Pending":"Under Contract"}
    order=["Pipeline","Appt Set","Appt Met","Signed","Listed","Under Contract"]
    pipe={k:{"n":0,"vol":0,"comm":0} for k in order}
    uc_rows=[]; closed_mtd=[]
    m0=as_of.replace(day=1).isoformat()
    for r in deals:
        c=r["cellValuesByFieldId"]
        if not team(c): continue
        st=c.get(FD_STAGE) or ""
        if st=="Closed":
            cd=c.get("_closed") or ""
            if m0<=cd<=as_of.isoformat():
                closed_mtd.append(dict(addr=c.get(FD_ADDR) or "-", agent=c.get(FD_AGENT) or "-", pipe=c.get(FD_PIPE) or "-",
                                       price=c.get(FD_PRICE) or 0, comm=c.get(FD_COMM) or 0, closed=cd))
            continue
        if st=="Lost" or not fresh(c): continue
        f=fam.get(st)
        if not f: continue
        pipe[f]["n"]+=1; pipe[f]["vol"]+=c.get(FD_PRICE) or 0; pipe[f]["comm"]+=c.get(FD_COMM) or 0
        if f=="Under Contract":
            uc_rows.append(dict(addr=c.get(FD_ADDR) or "-", agent=c.get(FD_AGENT) or "-", pipe=c.get(FD_PIPE) or "-",
                                price=c.get(FD_PRICE) or 0, comm=c.get(FD_COMM) or 0, proj=c.get(FD_PROJ) or ""))
    uc_rows.sort(key=lambda r: r["proj"] or "9999"); closed_mtd.sort(key=lambda r: r["closed"])
    # ---- Brokerage-wide (every FUB user): office pipeline + per-agent leaderboard, Sisu pipelines only
    users=[{"cellValuesByFieldId":c} for c in _cells(_recs(_load(pulls,"fub_users.json")))]
    # de-duplicated by name (Wyatt has three FUB logins), agents + brokers only, Active only
    active_agents=sorted({c.get(FU_NAME) for c in _cells(users) if (c.get(FU_STATUS) or "")=="Active"
                          and (c.get(FU_ROLE) or "") in ("Agent","Broker") and c.get(FU_NAME) and c.get(FU_NAME) not in FUB_NOT_AGENTS})
    office_act=metrics(lambda s: True)
    office_pipe={k:{"n":0,"vol":0,"comm":0} for k in order}; office_closed_mtd=[]; office_stale=0
    for r in deals:
        c=r["cellValuesByFieldId"]
        if not live(c): continue
        st=c.get(FD_STAGE) or ""
        if st=="Closed":
            cd=c.get("_closed") or ""
            if m0<=cd<=as_of.isoformat():
                office_closed_mtd.append(dict(addr=c.get(FD_ADDR) or "-", agent=c.get(FD_AGENT) or "-", pipe=c.get(FD_PIPE) or "-",
                                              price=c.get(FD_PRICE) or 0, comm=c.get(FD_COMM) or 0, closed=cd))
            continue
        if st=="Lost": continue
        if not fresh(c):
            office_stale+=1; continue
        f=fam.get(st)
        if f: office_pipe[f]["n"]+=1; office_pipe[f]["vol"]+=c.get(FD_PRICE) or 0; office_pipe[f]["comm"]+=c.get(FD_COMM) or 0
    office_closed_mtd.sort(key=lambda r: r["closed"])
    # leaderboard: every FUB user name seen on a live deal, a call or a lead this month
    names=set(active_agents)
    for r in deals:
        c=r["cellValuesByFieldId"]
        if live(c):
            for n in (c.get(FD_AGENT) or "").split(", "):
                if n: names.add(n)
    board=[]
    for a in sorted(names):
        m=metrics(lambda s, a=a: a in (s or ""))
        # open under-contract count for this agent (snapshot, not windowed)
        uc_n=sum(1 for r in deals if live(r["cellValuesByFieldId"]) and fresh(r["cellValuesByFieldId"]) and a in (r["cellValuesByFieldId"].get(FD_AGENT) or "")
                 and fam.get(r["cellValuesByFieldId"].get(FD_STAGE) or "")=="Under Contract")
        row={"name":a,"leads":m["New Leads"]["MTD"],"conv":m["Conversations"]["MTD"],"set":m["Appointments Set"]["MTD"],
             "met":m["Appointments Met"]["MTD"],"signed":m["Signed Clients"]["MTD"],"uc":uc_n,"closed":m["Closings"]["MTD"],
             "team":a in FUB_TEAM}
        row["active"]=any(row[k] for k in ("leads","conv","set","met","signed","uc","closed"))
        board.append(row)
    board.sort(key=lambda r:(-r["closed"],-r["uc"],-r["signed"],-r["conv"],r["name"]))
    active_board=[r for r in board if r["active"]]
    idle=[r["name"] for r in board if not r["active"] and r["name"] in active_agents]
    # ---- Rentals funnel from FUB (replaces the Arkie/Tommy hand-form rows)
    rlead=lambda c: "rental" in (c.get(FNL_SRC) or "").lower() or "Arkie" in (c.get(FNL_ASSIGN) or "")
    rconv=lambda c: bool(c.get(FC_CONV)) and _has_user(c.get(FC_USER), FUB_RENTAL_USERS)
    stage_is=lambda s: (lambda c: (c.get(FRL_STAGE) or "")==s)
    ract={
        "Leads":            E.window_count(leads, FNL_CREATED, as_of, rlead),
        "Conversations":    E.window_count(calls, FC_DATE, as_of, rconv),
        "Appointments Set": E.window_count(rent, FRL_CHANGED, as_of, stage_is("Rental - Appt Set")),
        "Appointments Met": E.window_count(rent, FRL_CHANGED, as_of, stage_is("Rental - Appt Met")),
        "Applications":     E.window_count(rent, FRL_CHANGED, as_of, stage_is("Rental - Application")),
        "Leased":           E.window_count(rent, FRL_CHANGED, as_of, stage_is("Rental - Leased")),
    }
    # appointments set this month by property (the one rental stage Arkie keeps current)
    setprop={}
    for r in rent:
        c=r["cellValuesByFieldId"]
        if (c.get(FRL_STAGE) or "")=="Rental - Appt Set" and m0<=(c.get(FRL_CHANGED) or "")<=as_of.isoformat():
            p=_prop_of(c.get(FRL_PROP)); setprop[p]=setprop.get(p,0)+1
    snap={}; byprop={}
    return {"office_act":office_act,"office_pipe":office_pipe,"office_closed_mtd":office_closed_mtd,"office_board":active_board,
            "office_idle":idle,"office_stale":office_stale,"office_active_agents":len(active_agents),"office_users_loaded":bool(users),
            "team_act":act,"team_agents":agents,"team_pipe":pipe,"team_pipe_order":order,"team_uc":uc_rows,
            "team_closed_mtd":closed_mtd,"team_n_deals":sum(1 for r in deals if team(r["cellValuesByFieldId"])),
            "fub_loaded":bool(deals),
            "rentals_fub":ract,"rentals_stage_snap":snap,"rentals_by_prop":byprop,"rentals_set_by_prop":setprop}

def fundamentals_M(pulls, as_of):
    """Fundamentals ELC — derived from Paige's OPERATIONAL base, not a reporting feed.
    Roster/revenue/waitlist/staff come from status-aware rollups (departed records stay
    for history and would poison count-alls); windowed KPIs come from the date fields the
    End-Date automations stamp on status flips. Only the 3 funnel KPIs come from the form."""
    rooms=_cells(_recs(_load(pulls,"felc_rooms.json")))
    kids=_recs(_load(pulls,"felc_children.json")); kc=_cells(kids)
    if not rooms or not kc:
        # No pull, no card. A missing file must never render as a school with zero children.
        sys.stderr.write("WARN fundamentals: felc_rooms.json / felc_children.json missing or empty — card WITHHELD, stays under 'coming'\n")
        return {}
    staff=_recs(_load(pulls,"felc_staff.json")); sc=_cells(staff)
    wl=_recs(_load(pulls,"felc_waitlist.json"))
    form=_recs(_load(pulls,"felc_kpi.json")); fc=_cells(form)
    # --- rooms (capacity · filled · open · demand · booked weekly $) in age order
    order={n:i for i,n in enumerate(FELC_ROOM_ORDER)}
    # staff per room = ACTIVE staff linked to the room (Wyatt 9/03 huddle: "2 teachers for 13 kids");
    # inactive staff stay linked in the base, so filter by status. A floater linked to 3 rooms counts in each.
    active_ids={r.get("id") for r in staff if _nm((r.get("cellValuesByFieldId") or {}).get(FS_STAT))=="Active"}
    rrows=[]
    for c in rooms:
        links=c.get(FR_STAFF) or []
        nstaff=sum(1 for l in links if (l.get("id") if isinstance(l,dict) else l) in active_ids)
        rrows.append(dict(name=c.get(FR_NAME) or "-", age=c.get(FR_AGE) or "-", cap=c.get(FR_CAP) or 0,
                          enrolled=c.get(FR_ENR) or 0, open=c.get(FR_OPEN) or 0, waitlist=c.get(FR_WL) or 0,
                          rev=c.get(FR_REV) or 0, rate=c.get(FR_RATE) or 0, staff=nstaff))
    rrows.sort(key=lambda r:(order.get(r["name"], 99), r["name"]))
    classroom=[r for r in rrows if r["name"]!=FELC_AFTERCARE]
    purple=[r for r in rrows if r["name"]==FELC_AFTERCARE]
    ov={
        "enrolled_total": sum(r["enrolled"] for r in rrows),
        "class_enrolled": sum(r["enrolled"] for r in classroom), "class_cap": sum(r["cap"] for r in classroom),
        "purple_enrolled": (purple[0]["enrolled"] if purple else 0), "purple_cap": (purple[0]["cap"] if purple else 0),
        "open_seats": sum(r["open"] for r in rrows),
        "weekly_rev": sum(r["rev"] for r in rrows),
        # cross-check: the Children table's Active Tuition must equal the Rooms rollup
        "weekly_rev_children": sum((c.get(FC_TUITION) or 0) for c in kc if _nm(c.get(FC_STAT))=="Enrolled"),
        "enrolled_children": sum(1 for c in kc if _nm(c.get(FC_STAT))=="Enrolled"),
        "staff_active": sum(1 for c in sc if _nm(c.get(FS_STAT))=="Active"),
        "waitlist_active": sum(1 for r in wl if (r.get("cellValuesByFieldId",{}).get(FW_ACTIVE) or 0)==1),
        "waitlist_unassigned": sum(1 for r in wl if (r.get("cellValuesByFieldId",{}).get(FW_ACTIVE) or 0)==1
                                   and not r.get("cellValuesByFieldId",{}).get(FW_TARGET)),
    }
    ov["annualized"]=ov["weekly_rev"]*52
    # waitlist demand by birth-year group (Paige's organizing axis), active rows only
    demand={}
    for r in wl:
        c=r.get("cellValuesByFieldId",{})
        if (c.get(FW_ACTIVE) or 0)!=1: continue
        k=_nm(c.get(FW_YEAR)) or "no birth year"
        demand[k]=demand.get(k,0)+1
    ov["demand"]=sorted(demand.items(), key=lambda kv:(kv[0]=="no birth year", kv[0]))
    # --- windowed KPIs
    def flip(recs):  # wrap cell dicts back into record shape for the window helpers
        return [{"cellValuesByFieldId":c} for c in recs]
    kr=flip(kc); sr=flip(sc); fr=flip(fc)
    pipe={
      # a start date in the window is an enrollment, whatever the child's status today
      "new_enroll": E.window_count(kr, FC_START, as_of),
      # churn = last day in the window (End Date is stamped by the status-flip automation)
      "churn": E.window_count(kr, FC_END, as_of, lambda c:_nm(c.get(FC_STAT)) in ("Withdrawn","Not Returning")),
      "new_hires": E.window_count(sr, FS_HIRE, as_of),
      "terminations": E.window_count(sr, FS_END, as_of, lambda c:_nm(c.get(FS_STAT))=="Inactive"),
      # created-in-window on the waitlist table itself (createdTime, not a cell)
      "waitlist_added": E.window_count([{"cellValuesByFieldId":{"_created":(r.get("createdTime") or "")[:10]}} for r in wl],
                                       "_created", as_of),
      "leads": E.window_sum(fr, FK_DATE, FK_LEADS, as_of),
      "conv": E.window_sum(fr, FK_DATE, FK_CONV, as_of),
      "tours": E.window_sum(fr, FK_DATE, FK_TOURS, as_of),
    }
    # which windows predate each source going live (rendered "-", never a fake zero)
    W=E.windows(as_of)
    pipe["_waitlist_dead"]=[lab for lab,(a,b) in W.items() if a.isoformat()<FELC_WAITLIST_LIVE]
    pipe["_form_dead"]=[lab for lab,(a,b) in W.items() if b.isoformat()<FELC_FORM_LIVE]
    pipe["form_rows"]=len(fc)
    # --- data flags = Paige's backfill queue (count only; the base holds the detail)
    flags={"children":sum(1 for c in kc if c.get(FC_FLAGS)),
           "staff":sum(1 for c in sc if c.get(FS_FLAGS)),
           "waitlist":sum(1 for r in wl if r.get("cellValuesByFieldId",{}).get(FW_FLAGS)),
           # departed kids with no End Date: the reason churn undercounts the summer exodus
           "departed_no_end":sum(1 for c in kc if _nm(c.get(FC_STAT)) in ("Withdrawn","Not Returning") and not c.get(FC_END)),
           # inactive staff with no End Date: terminations undercount the same way
           "inactive_no_end":sum(1 for c in sc if _nm(c.get(FS_STAT))=="Inactive" and not c.get(FS_END)),
           "cpr_expired":sum(1 for c in sc if _nm(c.get(FS_STAT))=="Active" and c.get(FS_CPR) and c.get(FS_CPR)<as_of.isoformat())}
    # Facebook organic (Windsor facebook_organic, page 207866299354865 "Fundamentals Early Learning
    # Center - Central", connected and verified live 2026-09-02). No ad block: the school runs no ads.
    org=_organic(pulls,"felc_organic.json","felc_organic_posts.json",as_of)
    return {"felc_ov":ov,"felc_rooms":rrows,"felc_pipe":pipe,"felc_flags":flags,"felc_org":org}

def _organic(pulls, page_file, posts_file, as_of):
    """Facebook organic (Windsor facebook_organic) → per-window aggregates, or None if the
    page's pull is absent/empty (division renders no ORGANIC SOCIAL section until it exists).
    Page pull rows: date + page_impressions + page_post_engagements + page_fans/page_follows
    (daily LEVEL values). Posts pull rows: post_created_time + post_impressions + post_clicks.
    Net New Followers = follower level at window end minus level the day before window start."""
    from datetime import timedelta
    page=_load(pulls, page_file); posts=_load(pulls, posts_file)
    prows=page.get("result", page.get("records", page)) if isinstance(page, dict) else page
    if not isinstance(prows, list) or not prows:
        return None
    rows=[r for r in prows if isinstance(r, dict) and r.get("date")]
    if not rows:
        return None
    fans_by_date={r["date"]: (r.get("page_follows") if r.get("page_follows") is not None else r.get("page_fans")) for r in rows}
    dates=sorted(d for d, v in fans_by_date.items() if v is not None)
    def fans_at(d):
        iso=d.isoformat(); v=None
        for dt in dates:
            if dt <= iso: v=fans_by_date[dt]
            else: break
        return v
    po=posts.get("result", posts.get("records", posts)) if isinstance(posts, dict) else posts
    pr=[{"date": (p.get("post_created_time") or "")[:10]} for p in (po or []) if isinstance(p, dict) and p.get("post_created_time")]
    def s(field, a, b):
        return sum(int(r.get(field) or 0) for r in rows if a.isoformat() <= r["date"] <= b.isoformat())
    out={}
    for lab,(a,b) in E.windows(as_of).items():
        f_end=fans_at(b); f_start=fans_at(a - timedelta(days=1))
        out[lab]={
            "posts": sum(1 for p in pr if a.isoformat() <= p["date"] <= b.isoformat()),
            "impressions": s("page_impressions", a, b),
            "engagements": s("page_post_engagements", a, b),
            "net_fans": (f_end - f_start) if (f_end is not None and f_start is not None) else None,
        }
    out["fans_now"]=fans_at(as_of)
    return out

def _ad_rows(obj):
    """Normalize a Windsor pull to [{date,spend,actions_lead,impressions,clicks}].
    Accepts a bare list OR the raw Windsor MCP response {"result":[...]} (verified live
    2026-08-12 — the MCP wraps rows in "result", so saving the response verbatim is fine)."""
    recs=obj.get("result", obj.get("data", obj.get("rows", obj))) if isinstance(obj,dict) else obj
    out=[]
    for r in recs or []:
        out.append({
            "date": r.get("date") or r.get("date_start") or r.get("day"),
            "spend": float(r.get("spend",0) or 0),
            "actions_lead": int(r.get("actions_lead", r.get("leads",0)) or 0),
            "impressions": int(r.get("impressions",0) or 0),
            "clicks": int(r.get("clicks",0) or 0),
        })
    return [r for r in out if r["date"]]

# --------------------------------------------------------------------------
def registry_M(pulls):
    """Load the per-division registry goal pulls into {div: {kpi_lower: {goal,cad,status}}}.
    A division with no file (or an empty pull) yields an empty dict, and the payload
    builder falls back to its hardcoded literal for that row."""
    goals={}
    for div, fn in REG_FILES.items():
        recs=_recs(_load(pulls, fn)); d={}
        for r in recs:
            c=r.get("cellValuesByFieldId", {})
            nm=c.get(REG_KPI)
            if not nm:
                continue
            d[str(nm).strip().lower()]={"goal":c.get(REG_GOAL),
                                        "cad":CAD_MAP.get(_nm(c.get(REG_CAD)), "mo"),
                                        "status":_nm(c.get(REG_STATUS))}
        goals[div]=d
    return {"registry_goals":goals}

def build_M(pulls, as_of):
    M={}
    M.update(registry_M(pulls))
    M.update(kcm_M(pulls, as_of))
    M.update(ascend_M(pulls, as_of))
    M.update(cowork_M(pulls, as_of))
    M.update(rentals_M(pulls, as_of))
    if as_of.isoformat() >= FUB_GO_LIVE_AS_OF or os.environ.get("FUB_FORCE") == "1":
        M.update(fub_M(pulls, as_of))
    # FELC_FORCE=1 in the environment renders the card regardless of the gate (review builds only).
    if as_of.isoformat() >= FELC_GO_LIVE_AS_OF or os.environ.get("FELC_FORCE") == "1":
        M.update(fundamentals_M(pulls, as_of))
    return M

def main():
    if len(sys.argv) < 4:
        print("usage: build_brief.py <pulls_dir> <as_of YYYY-MM-DD> <out.pdf>"); sys.exit(2)
    pulls=sys.argv[1]; as_of=date.fromisoformat(sys.argv[2]); out=sys.argv[3]
    M=build_M(pulls, as_of)
    payload=BP.build(M, as_of)
    pj=os.path.splitext(out)[0]+".payload.json"
    json.dump(payload, open(pj,"w"), indent=1, default=str)
    here=os.path.dirname(os.path.abspath(__file__))
    subprocess.check_call([sys.executable, os.path.join(here,"render_brief.py"), pj, out])
    print("built", out, "from", pulls, "as_of", as_of)

if __name__ == "__main__":
    main()
