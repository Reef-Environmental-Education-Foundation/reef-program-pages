"""
audience_views.py -- Approve & Share audience views (added 2026-09-28).

One booking record, one source of truth, several audience-specific views.
build_proposal_data() in generate_booking_package.py stays the single place
where a booking's facts (dates, group size, schedule, pricing, inclusions)
are assembled. This module only PROJECTS those facts into four focused,
printable views, and adds the "share" block the coordinator's Approve &
Share step renders:

    administrator  Administrator Approval Summary  (pricing + terms)
    educator       (Draft) Educator Plan           (full rotation matrix)
    family         Family & Chaperone Overview     (NO pricing / terms)
    student        Student Preview                 (NO pricing / terms)

Each view is written as its own folder with its own data.js
(bookings/<slug>/share/<view>/), containing ONLY the fields that view may
show. That is deliberate: GitHub Pages is public static hosting, so hiding
fields in the browser would be fake privacy -- whatever a page loads, anyone
can read. Filtering happens here, at build time, and assert_no_pricing()
fails the run if a price ever leaks into a family or student payload.

This is the same shape a future backend would use: a request for a view
returns only that view's fields. See PRIVACY.md at the repo root.

What this does NOT do (Martha, 2026-09-28, deferred on purpose):
  - track per-person status (invited / viewed / approved) -- a static site
    cannot know who opened a link; that needs an Airtable-backed contacts
    table and a backend
  - store anyone's email address -- this repo is public
  - the full post-confirmation Group Planning Hub (forms, deadlines,
    assignments as live records)

Booking-specific audience content comes from the booking's itinerary file,
itineraries/<record_id>.json -> "audiences" (schema documented in
itineraries/README.md). REEF-wide standard text comes from
content/audience_defaults.json. A section with no content is omitted rather
than filled with a guess -- same guardrail as the rest of the pipeline.
"""

import copy
import json
import re
from pathlib import Path

CONTENT_DIR = Path(__file__).parent / "content"
VIEW_KEYS = ("administrator", "educator", "family", "student")
PUBLIC_VIEWS = ("family", "student")          # never carry pricing or terms
CONFIRMED_STATUSES = {"Confirmed", "In Progress", "Completed"}
CONTRACT_SIGNED = "Signed"
ROLE_LABELS = {
    "coordinator": "Primary coordinator",
    "decisionMaker": "Authorized decision-maker",
    "planningTeam": "Planning team",
    "audience": "Read-only audience",
}
ALLOWED_ROLE_KEYS = {"name", "title", "roles", "approvalAuthority", "audiences", "note"}

# Set True once the "CTA Response Write-Back to Airtable" Zap has lookup rows
# for admin_approved / admin_feedback (and Bookings "Proposal Response" has
# matching options). Until then the administrator view sends its response by
# email to the REEF contact instead, so an unmapped value never reaches
# Airtable. See the change log, 2026-09-28.
ADMIN_WEBHOOK_ENABLED = False


class AudienceContentError(Exception):
    """Raised when audience content is unsafe to publish (e.g. an email
    address in the public repo, or pricing in a family/student view)."""


def load_defaults():
    with open(CONTENT_DIR / "audience_defaults.json") as fh:
        return json.load(fh)


def is_schedule_draft(booking_status, contract_status):
    """The one draft rule (2026-09-30), used by the proposal banner and by the
    audience pages' confirmed/draft test. A schedule stops being a draft only
    once the contract is received AND signed (Agreement/Contract Status ==
    "Signed"), or the booking has reached Confirmed / In Progress / Completed.
    Status "Contracted" alone is still a draft."""
    if contract_status == CONTRACT_SIGNED:
        return False
    return (booking_status or "") not in CONFIRMED_STATUSES


def share_status(booking_status, contract_status):
    confirmed = not is_schedule_draft(booking_status, contract_status)
    return ("confirmed", "Confirmed") if confirmed else ("draft", "Draft")


def _validate_roles(roles, record_id):
    clean = []
    for r in roles or []:
        extra = set(r) - ALLOWED_ROLE_KEYS
        if extra:
            raise AudienceContentError(
                f"{record_id}: audiences.roles entry {r.get('name')!r} has unsupported keys {sorted(extra)}. "
                "Contact details (email, phone) must not go in this public repo -- keep them in Airtable.")
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", json.dumps(r)):
            raise AudienceContentError(f"{record_id}: audiences.roles contains an email address. Remove it.")
        role_keys = r.get("roles") or []
        bad = [k for k in role_keys if k not in ROLE_LABELS]
        if bad:
            raise AudienceContentError(f"{record_id}: unknown proposal role(s) {bad}; use {sorted(ROLE_LABELS)}")
        clean.append({
            "name": r.get("name") or "",
            "title": r.get("title") or "",
            "roles": role_keys,
            "roleLabels": [ROLE_LABELS[k] for k in role_keys],
            "approvalAuthority": bool(r.get("approvalAuthority")),
            "audiences": [a for a in (r.get("audiences") or []) if a in VIEW_KEYS],
            "note": r.get("note") or "",
        })
    return clean


def _money_strings(b, pd):
    """Every price string this booking could render, for the leak check."""
    pr = pd.get("pricing") or {}
    vals = {pr.get("estimatedTotal")}
    for t in ("tileTotal", "tileRate"):
        if pr.get(t):
            vals.add(pr[t].get("num"))
    return {v for v in vals if v and v not in ("$0.00", "0")}


def assert_no_pricing(view_key, payload, money_strings, allow_other_amounts=False):
    """REEF's own prices can never appear. Any other "$" amount also fails,
    unless the booking file sets <view>.allowDollarAmounts (e.g. a school's own
    fundraising text that names its own amounts)."""
    blob = json.dumps(payload, ensure_ascii=False)
    hits = [m for m in money_strings if m in blob]
    if not allow_other_amounts and re.search(r"\$\s?\d", blob):
        hits.append("a $ amount")
    if hits:
        raise AudienceContentError(
            f"The {view_key} view would publish pricing ({', '.join(sorted(set(hits)))}). "
            "Family and student views must never include prices; fix the audience content.")


def _cohort_lines(rot):
    """Condensed per-cohort schedule for the administrator view."""
    st = {s["id"]: s for s in rot["stations"]}
    out = []
    for c in rot["cohorts"]:
        rows = sorted([a for a in rot["assignments"] if a["cohort"] == c["id"]], key=lambda a: a["start"])
        out.append({"cohort": c["label"],
                    "items": [{"time": f"{a['start']}-{a['end']}",
                               "name": st[a["station"]].get("short") or st[a["station"]]["name"]} for a in rows]})
    return out


def _clock(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _simple_schedule(pd, fam):
    """A family-level schedule: start, lunch window, end. Derived from the
    rotation (or the day blocks) so it can never disagree with the matrix."""
    if fam.get("schedule"):
        return fam["schedule"]
    rot = pd.get("rotation")
    if rot:
        meals = [s["id"] for s in rot["stations"] if s.get("type") == "meal"]
        lunch = [a for a in rot["assignments"] if a["station"] in meals]
        n = len(rot["cohorts"])
        out = [{"time": _clock(rot["startTime"]),
                "label": f"Program begins. Students work in {n} small groups (cohorts) that rotate between activities."}]
        if lunch:
            s, e = min(a["start"] for a in lunch), max(a["end"] for a in lunch)
            out.append({"time": f"{_clock(s)}–{_clock(e)}",
                        "label": "Picnic lunch. Each cohort has its own lunch time in this window."})
        end = (rot.get("departure") or {}).get("time") or rot["endTime"]
        out.append({"time": _clock(end), "label": "Program ends."})
        return out
    out = []
    for d in pd.get("days") or []:
        for blk in d.get("blocks") or []:
            if blk.get("time"):
                out.append({"time": blk["time"], "label": blk.get("title", "")})
    return out


def _experiences(pd, for_students=False):
    out = []
    for d in pd.get("days") or []:
        for blk in d.get("blocks") or []:
            if blk.get("tag") == "Break" or (blk.get("station") and _is_meal(pd, blk["station"])):
                continue
            text = (blk.get("studentBlurb") if for_students else blk.get("familyBlurb")) or blk.get("description", "")
            out.append({"title": blk.get("title", ""), "text": text, "color": blk.get("color")})
    return out


def _is_meal(pd, station_id):
    rot = pd.get("rotation") or {}
    return any(s["id"] == station_id and s.get("type") == "meal" for s in rot.get("stations") or [])


def _objectives(pd):
    out = []
    for d in pd.get("days") or []:
        out += d.get("studentsWill") or []
    return out


def _payment_lines(b, defaults, money):
    lines = []
    if b.get("deposit_due_now"):
        lines.append(f"A {money(b['deposit_due_now'])} deposit holds your group's date.")
    if b.get("payment2_due_date") and b.get("payment2_amount"):
        lines.append(f"Payment 2 of {money(b['payment2_amount'])} is due {b['payment2_due_pretty']}.")
    if b.get("final_due_date") and b.get("final_amount"):
        lines.append(f"The final payment of {money(b['final_amount'])} is due {b['final_due_pretty']}.")
        return lines + [t for t in defaults["paymentTerms"] if not t.startswith("The final payment")]
    return lines + defaults["paymentTerms"]


def build_views(b, pd, itin, money, date_pretty, pages_url, generated_on):
    """Returns (share_block, {view_key: payload}).

    b      booking dict from fetch_booking_data()
    pd     data["proposal"] from build_proposal_data() -- the canonical facts
    itin   load_itinerary() result (for the raw "audiences" block)
    """
    defaults = load_defaults()
    aud = copy.deepcopy(itin.get("audiences") or {})
    record_id = b["record_id"]
    status, status_label = share_status(b.get("status"), b.get("agreement_contract_status"))
    version = pd["meta"].get("proposalVersion") or "v1"
    roles = _validate_roles(aud.get("roles"), record_id)
    logistics = aud.get("logistics") or {}
    enabled = aud.get("views") or list(VIEW_KEYS)
    reef = pd.get("reefContact") or {}
    for k in ("payment2_due_date", "final_due_date"):
        b[k.replace("_date", "_pretty")] = date_pretty(b[k]) if b.get(k) else ""

    common = {
        "status": status,
        "statusLabel": status_label,
        "version": version,
        "lastUpdated": generated_on,
        "orgName": pd["group"]["orgName"],
        "dateLine": pd["dates"]["range"],
        "hours": pd.get("hours"),
        "programName": f"Florida Keys Ocean Explorers {pd['meta'].get('programTypeLabel') or 'Program'}",
        "summary": pd.get("summary"),
        # Draft Program Schedule notice (2026-09-30): the same flag the
        # proposal uses, so every schedule a school hands out (cohort table,
        # rotation matrix, family schedule) carries the draft line too.
        "scheduleDraft": bool(pd.get("scheduleDraft")),
    }
    def reef_contact():
        return {k: reef.get(k, "") for k in ("name", "role", "email", "phone")}

    views = {}
    group = pd["group"]
    counts = {"students": group["students"], "chaperones": group["chaperones"]}

    # ---------------- Administrator ----------------
    adm = aud.get("administrator") or {}
    pr = pd.get("pricing") or {}
    facts = [g for g in pd.get("glance") or [] if g["k"] != "Focus"]
    responsibilities = []
    if defaults.get("supervision"):
        responsibilities.append({"area": "Supervision", "text": " ".join(defaults["supervision"])})
    for area, key in (("Safety", "safety"), ("Accessibility", "accessibility"),
                      ("Transportation", "transportation"), ("Meals", "meals")):
        if logistics.get(key):
            responsibilities.append({"area": area, "text": logistics[key]})
    if pd.get("rotation") or any("boat" in (e or "").lower() for e in [x["title"] for x in _experiences(pd)]):
        responsibilities.append({"area": "Activity operators", "text": defaults["vendorNote"]})
    views["administrator"] = dict(common, **{
        "view": "administrator",
        "purpose": adm.get("purpose") or pd.get("summary"),
        "value": [{"title": p["title"], "text": p["text"]} for p in (pd.get("pillars") or [])][:2],
        "facts": facts,
        "counts": counts,
        "scheduleFormat": pd.get("scheduleFormat"),
        "cohortSchedule": _cohort_lines(pd["rotation"]) if pd.get("rotation") else None,
        "simpleSchedule": _simple_schedule(pd, {}),
        "outcomes": _objectives(pd),
        "responsibilities": responsibilities,
        "pricing": {
            "total": pr.get("estimatedTotal"),
            "perStudent": (pr.get("tileRate") or {}).get("num"),
            "chaperones": (pr.get("chaperonePolicy") or {}).get("headline"),
            "note": "Estimated total. REEF sends a revised proposal if anything that affects price changes.",
        },
        "included": [i for g in pd.get("included") or [] for i in g.get("items") or []],
        "notIncluded": pd.get("notIncluded") or [],
        "optional": pd.get("optional") or [],
        "paymentTerms": _payment_lines(b, defaults, money),
        "cancellationTerms": defaults["cancellationTerms"],
        "termsNote": defaults["termsNote"],
        "outstanding": adm.get("outstandingDecisions") or aud.get("outstandingDecisions") or [],
        "decisionMakers": [r for r in roles if "decisionMaker" in r["roles"] or r["approvalAuthority"]],
        "approval": {
            "enabled": adm.get("approval", True),
            "bookingId": record_id,
            "webhookUrl": (pd.get("cta") or {}).get("responseWebhookUrl") if ADMIN_WEBHOOK_ENABLED else None,
            "emailTo": reef.get("email") or "explorers@REEF.org",
        },
        "reefContact": reef_contact(),
    })

    # ---------------- Educator ----------------
    edu = aud.get("educator") or {}
    rot = pd.get("rotation")
    assignments = edu.get("cohortAssignments")
    if assignments is None and rot:
        assignments = [{"cohort": c["label"], "size": c.get("size"), "teachers": "", "chaperones": ""}
                       for c in rot["cohorts"]]
    views["educator"] = dict(common, **{
        "view": "educator",
        "objectives": edu.get("learningObjectives") or _objectives(pd),
        "scheduleFormat": pd.get("scheduleFormat"),
        "rotation": rot,
        "days": pd.get("days"),
        "pendingNote": pd.get("pendingNote") if pd.get("scheduleFormat") == "pending" else None,
        "cohortAssignments": assignments or [],
        "assignmentsNote": edu.get("assignmentsNote") or (
            "Your school assigns teachers and chaperones to each cohort. Use this table to plan, "
            "then share the final assignments with REEF." if assignments else None),
        "logistics": [{"k": k.title(), "v": logistics[k]} for k in ("arrival", "transitions", "lunch", "departure")
                      if logistics.get(k)],
        "bring": logistics.get("bring") or [],
        "accessibility": logistics.get("accessibility"),
        "supervision": (edu.get("supervision") or []) + defaults["supervision"],
        "counts": counts,
        "resources": (edu.get("resources") or []) + defaults["educatorResources"],
        "remaining": edu.get("remainingDecisions") or aud.get("outstandingDecisions") or [],
        "reefContact": reef_contact(),
    })

    # ---------------- Family ----------------
    fam = aud.get("family") or {}
    views["family"] = dict(common, **{
        "view": "family",
        "location": fam.get("generalLocation") or pd.get("location"),
        "intro": fam.get("intro") or pd.get("summary"),
        "experiences": _experiences(pd),
        "whyItMatters": fam.get("whyItMatters") or [p["text"] for p in (pd.get("pillars") or [])][:2],
        "schedule": _simple_schedule(pd, fam),
        "bring": fam.get("bring") or logistics.get("bring") or [],
        "clothing": fam.get("clothing") or [],
        "lunch": fam.get("lunch") or logistics.get("lunch"),
        "transportation": fam.get("transportation") or logistics.get("familyTransportation"),
        "chaperoneExpectations": (fam.get("chaperoneExpectations") or []) + defaults["supervision"][:1],
        "deadlines": fam.get("deadlines") or [],
        "fundraising": fam.get("fundraisingText"),
        "aboutReef": defaults["aboutReef"],
        "contactInstructions": fam.get("contactInstructions") or defaults["familyContactDefault"],
    })

    # ---------------- Student ----------------
    stu = aud.get("student") or {}
    views["student"] = dict(common, **{
        "view": "student",
        "headline": stu.get("headline") or "Get ready to explore the reef",
        "intro": stu.get("intro") or "",
        "experiences": _experiences(pd, for_students=True),
        "topics": stu.get("topics") or [t for t in ((pd.get("glance") or [{}])[-1].get("v", "").split(" · "))
                                        if (pd.get("glance") or [{}])[-1].get("k") == "Focus" and t],
        "feel": stu.get("feel") or [],
        "bring": stu.get("bring") or fam.get("bring") or logistics.get("bring") or [],
        "classroomPrep": stu.get("classroomPrep") or [],
    })

    views = {k: v for k, v in views.items() if k in enabled}
    money_strings = _money_strings(b, pd)
    for k in PUBLIC_VIEWS:
        if k in views:
            assert_no_pricing(k, views[k], money_strings,
                              allow_other_amounts=bool((aud.get(k) or {}).get("allowDollarAmounts")))

    copy_ = defaults["viewCopy"]
    share = {
        "status": status,
        "statusLabel": status_label,
        "version": version,
        "lastUpdated": generated_on,
        "needs": [n for n in defaults["needs"] if n.get("action") or n.get("view") in views],
        "views": [{
            "key": k,
            "title": copy_[k]["draftTitle"] if (status == "draft" and copy_[k].get("draftTitle")) else copy_[k]["title"],
            "audience": (aud.get("audienceLabels") or {}).get(k) or copy_[k]["audience"],
            "description": copy_[k]["description"],
            "includes": copy_[k]["includes"],
            "path": f"share/{k}/",
            "url": f"{pages_url}share/{k}/",
            "pricing": k not in PUBLIC_VIEWS,
        } for k in VIEW_KEYS if k in views],
        "roles": roles,
        "privacyNote": ("Anyone who has a link can open that page. The family and student views leave out "
                        "pricing and contract terms entirely. Please don't add student names or other "
                        "private details to anything you share."),
    }
    for k, v in views.items():
        v["title"] = next(x["title"] for x in share["views"] if x["key"] == k)
        v["audienceLabel"] = next(x["audience"] for x in share["views"] if x["key"] == k)
        v["url"] = next(x["url"] for x in share["views"] if x["key"] == k)
    return share, views


def view_page_data(view_payload, sample_flag):
    """Wraps one view as a complete BOOKING_DATA object (docType "audience")."""
    return {
        "docType": "audience",
        "assetDepth": 4,           # bookings/<slug>/share/<view>/index.html
        "meta": {"sampleFlag": bool(sample_flag)},
        "view": view_payload,
    }
