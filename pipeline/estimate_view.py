"""
estimate_view.py -- the Estimate stage (Step 2, 2026-10-10 spec).

A pre-proposal page a group sees at first inquiry, before a finished schedule
exists: a sample itinerary, an estimated price RANGE, the free-chaperone
policy in plain language, what would change the total, and what is not
included. It is NOT a quote, has no Approve button and no contract language.

Like audience_views.py this module only PROJECTS facts into a page payload,
and builds it from an ALLOWLIST: every field below is named on purpose. The
payload is never "proposal data minus some fields", because this repo and
GitHub Pages are public (see PRIVACY.md). The Step 3 privacy guard will scan
whatever this returns.

  low  = Bookings "Total Package Price" (already includes REEF's pricing; only
         the total is ever read, so no internal cost or uplift figure is
         present anywhere in this module's inputs)
  high = ceil(low x highMultiplier / roundUpTo) x roundUpTo
  per paid student = total / paid spaces (students + billable chaperones)

All money math is Decimal, never float. Copy and settings come from
content/estimate_defaults.json so staff can edit them without touching code.
"""

import copy
import json
import re
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import quote

CONTENT_DIR = Path(__file__).parent / "content"
ITINERARIES_DIR = Path(__file__).parent / "itineraries"
SAMPLE_ITINERARY = "sample-3-day"

# Activities whose drafted narrative has not been approved by Martha
# (Activities."Proposal Narrative Status" blank). Until it is set, no text
# about them may appear on any page. This is the fallback used when the
# status could not be read from Airtable (offline runs, the stable sample
# template); a status that IS set in Airtable releases the activity.
HELD_UNTIL_NARRATIVE_SET = ("Marine Ecology Program", "Fish ID Program")
HELD_PLACEHOLDER = "Campus program session"

CENTS = Decimal("0.01")


class EstimateContentError(Exception):
    """Raised when the estimate cannot be built safely or honestly."""


def load_defaults():
    with open(CONTENT_DIR / "estimate_defaults.json") as fh:
        return json.load(fh)


def free_chaperone_divisor(defaults=None):
    """The 'one free chaperone space for every N participants' divisor.
    Single source for the page copy AND the proposal copy, so wording and
    pricing config cannot drift apart."""
    return int((defaults or load_defaults())["freeChaperoneDivisor"])


# ---------------------------------------------------------------- money

def _dec(value):
    return Decimal(str(value if value is not None else 0))


def estimate_range(total, multiplier, round_to):
    """(low, high) as Decimals. high rounds UP to the next `round_to`."""
    low = _dec(total)
    if low <= 0:
        raise EstimateContentError(f"Total Package Price is {low}; cannot build an estimate range.")
    step = _dec(round_to)
    high = (low * _dec(multiplier) / step).to_integral_value(rounding=ROUND_CEILING) * step
    return low, high


def per_student(amount, paid_spaces):
    if paid_spaces <= 0:
        raise EstimateContentError("No paid spaces; cannot compute a per-student figure.")
    return (amount / Decimal(paid_spaces)).quantize(CENTS, rounding=ROUND_HALF_UP)


def money_label(amount, cents=False):
    amount = Decimal(amount)
    if not cents and amount == amount.to_integral_value():
        return f"${int(amount):,}"
    return f"${amount.quantize(CENTS, rounding=ROUND_HALF_UP):,.2f}"


def _num(amount):
    amount = Decimal(amount)
    return int(amount) if amount == amount.to_integral_value() else float(amount)


# ---------------------------------------------------------------- itinerary

def load_estimate_itinerary(record_id, itineraries_dir=None):
    """Estimate mode uses the record's own itinerary JSON only if it carries an
    "estimate" block; otherwise the generic sample-3-day.json. It reads ONLY
    "days": never rotation, audiences or Airtable schedule items, which hold
    real-cohort detail."""
    d = Path(itineraries_dir or ITINERARIES_DIR)
    own = d / f"{record_id}.json"
    if own.exists():
        with open(own) as fh:
            raw = json.load(fh)
        if isinstance(raw, dict) and raw.get("estimate"):
            return raw.get("days") or []
    sample = d / f"{SAMPLE_ITINERARY}.json"
    if not sample.exists():
        raise EstimateContentError(
            f"No estimate itinerary: {own.name} has no 'estimate' block and {sample.name} does not exist. "
            "This pipeline does not fabricate a schedule.")
    with open(sample) as fh:
        raw = json.load(fh)
    return (raw.get("days") if isinstance(raw, dict) else raw) or []


def _hold_text(text, held):
    for name in held:
        text = re.sub(re.escape(name), HELD_PLACEHOLDER, text, flags=re.I)
    return text


def project_days(days, held):
    """Allowlist copy of the itinerary days. Text naming a held activity is
    reduced to a neutral label and its description dropped."""
    out = []
    for d in days:
        blocks = []
        for blk in d.get("blocks") or []:
            joined = " ".join(str(blk.get(k) or "") for k in ("title", "tag", "description"))
            is_held = any(h.lower() in joined.lower() for h in held)
            blocks.append({
                "time": blk.get("time") or "",
                "tag": _hold_text(blk.get("tag") or "", held),
                "title": _hold_text(blk.get("title") or "", held),
                "description": "" if is_held else (blk.get("description") or ""),
            })
        out.append({
            "dayNumber": d.get("dayNumber"),
            "totalDays": d.get("totalDays"),
            "title": _hold_text(d.get("title") or "", held),
            "theme": _hold_text(d.get("theme") or "", held),
            "blocks": blocks,
        })
    return out


def held_activities(narrative_status):
    """Names still on hold. `narrative_status` is {activity name: status} from
    Airtable, or None when unknown (then the fallback list applies)."""
    if narrative_status is None:
        return list(HELD_UNTIL_NARRATIVE_SET)
    held = [n for n, s in narrative_status.items() if not (s or "").strip()]
    return held + [n for n in HELD_UNTIL_NARRATIVE_SET
                   if n not in narrative_status and n not in held]


# ---------------------------------------------------------------- page data

def paid_spaces(b):
    students = int(b.get("students") or 0)
    billable = b.get("billable_chaperones")
    if billable is None:  # field absent: derive from the same rule Airtable uses
        billable = max(int(b.get("chaperones") or 0) - int(b.get("free_chaperones") or 0), 0)
    return students + int(billable)


def build_estimate_data(b, itinerary_days, defaults=None, is_sample=False):
    """Returns the docType "estimate" payload. `b` is the dict from
    fetch_booking_data(); `itinerary_days` from load_estimate_itinerary()."""
    cfg = defaults or load_defaults()
    contact = cfg["contact"]
    if contact.get("emailStatus") == "PENDING_MARTHA_CONFIRMATION":
        print(f"WARNING: estimate contact email {contact['email']} is still "
              "PENDING_MARTHA_CONFIRMATION in estimate_defaults.json.", file=sys.stderr)

    low, high = estimate_range(b["total_package_price"], cfg["highMultiplier"], cfg["roundUpTo"])
    spaces = paid_spaces(b)
    per_low, per_high = per_student(low, spaces), per_student(high, spaces)

    divisor = int(b.get("free_chap_threshold") or free_chaperone_divisor(cfg))
    students = int(b.get("students") or 0)
    chaperones = int(b.get("chaperones") or 0)
    held = held_activities(b.get("activity_narrative_status"))
    if held:
        print("Estimate: text withheld for activities without an approved Proposal Narrative Status: "
              + ", ".join(held), file=sys.stderr)

    subject = quote(contact.get("mailtoSubject") or "Request a proposal")
    if not is_sample and b.get("org_name"):
        subject += quote(f" — {b['org_name']}")

    return {
        "docType": "estimate",
        "assetDepth": 2,
        "meta": {
            "sampleFlag": bool(is_sample),
            "robots": cfg.get("robots", "noindex"),
            "generatedFrom": b["record_id"],
        },
        # Org name only: no contact names, emails, students or families.
        "org": {"displayName": b.get("org_name") or ""},
        "group": {
            "students": students,
            "chaperones": chaperones,
            "freeChaperones": int(b.get("free_chaperones") or 0),
        },
        "itinerary": {
            "note": cfg["sampleItineraryNote"],
            "days": project_days(itinerary_days, held),
        },
        "estimate": {
            "ribbon": cfg["ribbon"],
            "low": _num(low), "high": _num(high),
            "lowLabel": money_label(low), "highLabel": money_label(high),
            "perPaidStudentLow": _num(per_low), "perPaidStudentHigh": _num(per_high),
            "perPaidStudentLowLabel": money_label(per_low, cents=True),
            "perPaidStudentHighLabel": money_label(per_high, cents=True),
            "paidSpaces": spaces,
            "chaperonePolicy": cfg["chaperonePolicyTemplate"].format(divisor=divisor),
            "changes": list(cfg["whatWouldChangeYourTotal"]),
            "notIncluded": list(cfg["notIncluded"]),
        },
        "cta": {
            "label": contact.get("mailtoSubject") or "Request a proposal",
            "mailto": f"mailto:{contact['email']}?subject={subject}",
        },
    }
