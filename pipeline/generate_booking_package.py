"""
generate_booking_package.py -- the live-Airtable version of the two
proof-of-concept scripts built 2026-09-03 (gen_contract.py and
generate_confirmed_page.py). Given a Bookings record ID, this pulls fresh
data straight from the Airtable REST API (no hardcoded dict) and produces:

  1. bookings/<slug>/data.js   -- the customer page's data, matching the
     schema in assets/render.js. Which of render.js's two rendering modes
     it targets depends on Bookings.Status: Quoting / Proposal Sent /
     Verbal Yes produce the six-section proposal (docType "proposal");
     Contracted and beyond produce the confirmed/pre-trip packet
     (docType "pretrip"). The slug is the same either way, so a booking's
     URL does not change as it moves through the pipeline -- the link a
     customer already has simply becomes the pre-trip packet.
  2. contracts/<slug>-contract.docx -- the merged contract document,
     produced only once the booking reaches Contracted. Everything here
     is published to the public Pages site, so a booking still at
     Quoting / Proposal Sent / Verbal Yes deliberately gets no signable
     agreement put up before anything has been agreed.

A Cancelled booking produces neither: see CancelledBookingNotSupported.

This is the script .github/workflows/publish-booking.yml calls. It
requires an AIRTABLE_API_KEY environment variable (a read-only personal
access token scoped to the two bases below) -- see HANDOFF_INSTRUCTIONS.md
for how to create one and add it as a GitHub Actions secret.

USAGE:
    AIRTABLE_API_KEY=... python generate_booking_package.py <booking_record_id>

Honesty note on what this script can and cannot do (unchanged from the
two POCs it replaces): Airtable has no field recording which day/time slot
a requested Activity falls into for a given booking, so the day-by-day
itinerary content is NOT derived from Activities Requested here. Instead
this script looks up a per-booking itinerary JSON under itineraries/
(captured from that booking's already-sent, human-approved proposal) and
reshapes it into the confirmed page's schema. If a booking has no file
under itineraries/<record_id>.json yet, this script fails loudly rather
than fabricating an itinerary -- see NoItineraryCaptured below. Building a
real day/time data model so this step isn't needed is tracked separately
(OXP_System_Connection_Roadmap_2026-09-03.md, priority #4) and is out of
scope here per Martha's 2026-09-03 direction to skip the intake/data-model
work for this push.

Approved-to-Share lock (Martha, 2026-09-25): NOTHING is published to the
public Pages site unless a REEF staff member has explicitly approved it in
Airtable first. Before writing anything under bookings/ or contracts/, this
script checks the booking's approval fields (see check_share_approval()):

  - "Approved to Share" is checked,
  - "Approved to Share - Stage" matches the page this run would build
    ("Proposal" for Quoting / Proposal Sent / Verbal Yes; "Pre-trip Packet +
    Contract" for Contracted and beyond) -- approving a proposal never
    auto-approves the later pre-trip packet or contract,
  - "Approved for Proposal Version" equals the booking's current "Proposal
    Version" (when one is set), so a revised proposal needs a fresh approval,
  - "Approved to Share By" names the person who approved it.

If any check fails, the run is PREVIEW ONLY: the page (and contract, when the
stage calls for one) is generated into a temp folder outside the repo, packed
into a single self-contained HTML file with an "INTERNAL PREVIEW" banner and
the customer response buttons disabled, and attached to an internal Asana
review task for Rose. Nothing is written under bookings/ or contracts/, so
the workflow's commit step finds no changes and nothing is pushed or deployed.
Once approved and re-run, the page is published and the review task says so.
"""

import base64
import copy
import json
import mimetypes
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests
import docx

sys.path.insert(0, str(Path(__file__).parent))
import audience_views  # noqa: E402  (Approve & Share audience views, 2026-09-28)

AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
API_ROOT = "https://api.airtable.com/v0"

BOOKINGS_BASE = "app3FIECuG8iQr7kY"
BOOKINGS_TABLE = "Bookings"
ACTIVITIES_TABLE = "Activities"
PROGRAM_TYPES_TABLE = "Program Types"
EPO_BASE = "appCK2qlT3WHdhYKd"
PERSONNEL_TABLE = "REEF Personnel"

# Program Types' six per-section hero attachment fields, keyed by the
# section names render.js's proposal mode expects in data.proposal.photos.
# Field names use an em dash, matching Airtable exactly -- a hyphen here
# silently yields None and falls back to the gradient art.
PROPOSAL_HERO_FIELDS = {
    "overview": "Proposal Hero — Overview",
    "experience": "Proposal Hero — Your Experience",
    "days": "Proposal Hero — Day by Day",
    "included": "Proposal Hero — What's Included",
    "pricing": "Proposal Hero — Pricing & Details",
    "next": "Proposal Hero — Next Steps",
}

# Bookings.Status values that mean "the customer is still deciding", and so
# should publish the proposal experience rather than the confirmed/pre-trip
# packet. Everything else (Contracted and beyond) gets the pre-trip page.
PROPOSAL_STATUSES = {"Quoting", "Proposal Sent", "Verbal Yes"}

# Bookings.Status -> which of the 5 roadmap steps the customer is on now.
# render.js renders steps below currentStep as done and currentStep as
# current, so "Quoting" sits ON step 2 (proposal being prepared).
ROADMAP_STEPS = ["Inquiry", "Proposal Prepared", "Your Review", "Contract", "Confirmed"]
ROADMAP_STEP_BY_STATUS = {
    "Quoting": 2,
    "Proposal Sent": 3,
    "Verbal Yes": 3,
    "Contracted": 4,
    "Confirmed": 5,
    "In Progress": 5,
    "Completed": 5,
}

REPO_ROOT = Path(__file__).parent
TEMPLATE_PATH = REPO_ROOT / "templates" / "Benjamin_School_Expedition_Contract_TEMPLATE.docx"
ITINERARIES_DIR = REPO_ROOT / "itineraries"
BOOKINGS_OUT_DIR = REPO_ROOT.parent / "bookings"
CONTRACTS_OUT_DIR = REPO_ROOT.parent / "contracts"

# Review gate (Martha, 2026-09-04): an Asana Personal Access Token, read
# from a GitHub Actions secret of the same name -- see README.md for how
# to create one. If unset, create_review_task() logs a warning and skips
# itself rather than failing the whole pipeline run.
ASANA_API_KEY = os.environ.get("ASANA_API_KEY")
ASANA_API_ROOT = "https://app.asana.com/api/1.0"
ASANA_OXP_PROJECT_GID = "1208312572861835"        # "OXP New Reservation Workflow"
ASANA_FACILITY_PROJECT_GID = "1210526829539105"   # "Facility Rental New Reservation Workflow"
ASANA_REVIEWER_GID = "1209845394372396"           # Rose Kelly
PAGES_BASE_URL = "https://reef-environmental-education-foundation.github.io/reef-program-pages"

# Approved-to-Share lock (Martha, 2026-09-25) -- see module docstring.
# Values must match the Bookings "Approved to Share - Stage" single-select
# options exactly (em dash in the field name, matching Airtable).
SHARE_STAGE_PROPOSAL = "Proposal"
SHARE_STAGE_PRETRIP = "Pre-trip Packet + Contract"
ASSETS_DIR = REPO_ROOT.parent / "assets"


# Booking Type -> the customer-facing noun render.js drops into proposal
# headings ("Florida Keys Ocean Explorers <label>", "your <word>, at a
# glance"). Derived from Booking Type rather than the linked Program Type
# record because Program Type Name is plural ("Expeditions") and only
# covers 3 of the 5 Booking Type values.
PROGRAM_WORDS_BY_BOOKING_TYPE = {
    # "Expedition" is REEF's brand term for this program type, so the mid-
    # sentence word is capitalized the same as the label (QA walkthrough,
    # 2026-09-09: "all references to REEF ... and Expedition should be
    # capitalized"). The other booking types use genuinely generic nouns
    # ("program", "rental"), which stay lowercase on purpose.
    "Group Program - Expedition": ("Expedition", "Expedition"),
    "Group Program - Discovery": ("Discovery Program", "program"),
    "Facility Rental": ("Facility Rental", "rental"),
    "OXP – Virtual": ("Virtual Program", "program"),
    "OXP – Monroe County": ("Monroe County Program", "program"),
}
DEFAULT_PROGRAM_WORDS = ("Program", "program")

# ---- Static proposal copy (no Airtable source) -------------------------
# The proposal's "why REEF works" pillars and its educator-team section
# have no backing Airtable fields, so per Martha's direction they are
# hardcoded here, one set per Booking Type, rather than left blank.
#
# Two deliberate constraints on this copy:
#   1. Every claim traces to something REEF actually does (the Volunteer
#      Fish Survey Project, educator-led instruction, the Ocean
#      Exploration Center) -- this text goes in front of customers.
#   2. The team entries name ROLES, not people. render.js already tells
#      the reader these are illustrative rather than their assigned
#      educators, and inventing named REEF staff for a customer-facing
#      page would be fabricating real colleagues' identities. Real bios
#      should come from EPO REEF Personnel, which already carries
#      Full name, Customer-Facing Title and Photo -- see the note in
#      build_proposal_data().
PILLARS_BY_BOOKING_TYPE = {
    "Group Program - Expedition": [
        {"title": "Real citizen science, not a demo",
         "text": "Students are trained in REEF's Volunteer Fish Survey Project methods and collect survey data using the same protocol REEF's volunteer network uses across the Caribbean and beyond."},
        {"title": "Taught by REEF educators",
         "text": "Every session and field activity is led by REEF marine science educators, with pre- and post-activity debriefs that connect what students saw to what it means."},
        {"title": "The Florida Keys as the classroom",
         "text": "Programs are based at REEF's Ocean Exploration Center in Key Largo and run out into the coral reef, mangrove, and seagrass habitats that surround it."},
        {"title": "Built around your group",
         "text": "The itinerary in this proposal is shaped around your dates, group size, and what you told us your students need to get out of the trip."},
    ],
    "Group Program - Discovery": [
        {"title": "Hands-on from the first session",
         "text": "Discovery Programs put students in front of real specimens, real data, and real marine science questions rather than a lecture."},
        {"title": "Taught by REEF educators",
         "text": "Sessions are led by REEF marine science educators who work with school and youth groups year-round."},
        {"title": "Anchored at the Ocean Exploration Center",
         "text": "Your group learns at REEF's Ocean Exploration Center for Marine Conservation in Key Largo."},
        {"title": "Sized to your group",
         "text": "Session content and pacing are matched to your group's age range, size, and available time."},
    ],
    "Facility Rental": [
        {"title": "A purpose-built marine science venue",
         "text": "Your event is hosted at REEF's Ocean Exploration Center for Marine Conservation in Key Largo."},
        {"title": "Clear, itemized pricing",
         "text": "Space, staffing, and any add-on programming are quoted separately so you can see exactly what drives the total."},
        {"title": "REEF staff on site",
         "text": "REEF staff coordinate setup, access, and logistics for the spaces included in your rental."},
        {"title": "Optional programming",
         "text": "Educational sessions can be added to a rental if you want REEF content as part of your event."},
    ],
}
DEFAULT_PILLARS = PILLARS_BY_BOOKING_TYPE["Group Program - Expedition"]

TEAM_BY_BOOKING_TYPE = {
    "Group Program - Expedition": [
        {"name": "REEF Marine Science Educators", "role": "Program Instruction",
         "bio": "Lead every session and field activity, from fish ID training through the reef survey itself."},
        {"name": "Volunteer Fish Survey Project Staff", "role": "Citizen Science",
         "bio": "Run REEF's survey methodology training and help students log real observations into REEF's database."},
        {"name": "REEF Ocean Explorers Coordination", "role": "Trip Logistics",
         "bio": "Your planning contact for dates, headcount, vendors, and everything between booking and arrival."},
    ],
    "Group Program - Discovery": [
        {"name": "REEF Marine Science Educators", "role": "Program Instruction",
         "bio": "Lead each Discovery session and adapt content to your group's age range and goals."},
        {"name": "REEF Ocean Explorers Coordination", "role": "Program Logistics",
         "bio": "Your planning contact for scheduling, headcount, and on-site details."},
    ],
    "Facility Rental": [
        {"name": "REEF Facility Coordination", "role": "Event Logistics",
         "bio": "Coordinates space setup, access, and timing for your event."},
        {"name": "REEF Marine Science Educators", "role": "Optional Programming",
         "bio": "Available if you add educational sessions to your rental."},
    ],
}
DEFAULT_TEAM = TEAM_BY_BOOKING_TYPE["Group Program - Expedition"]


class NoItineraryCaptured(Exception):
    """Raised when a booking has no captured day-by-day content yet.
    See the module docstring -- this is deliberate, not a bug to patch
    around with fabricated content."""


class CancelledBookingNotSupported(Exception):
    """Raised when a booking's Status is Cancelled.

    Same deliberate-failure pattern as NoItineraryCaptured: what a
    cancelled booking's public page should say -- a cancellation notice,
    an unpublish, a redirect, or simply nothing at all -- is a design
    decision that has not been made. Falling through to the confirmed /
    pre-trip page would quietly publish a cancelled group's itinerary as
    though the trip were still happening, so this fails loudly instead of
    guessing."""


def airtable_get(base_id, table_name, record_id):
    if not AIRTABLE_API_KEY:
        raise RuntimeError("AIRTABLE_API_KEY environment variable is not set.")
    url = f"{API_ROOT}/{base_id}/{table_name}/{record_id}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {AIRTABLE_API_KEY}"}, timeout=30)
    resp.raise_for_status()
    return resp.json()  # {"id": ..., "createdTime": ..., "fields": {...}}


def slugify(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def reef_email(addr):
    """Capitalize the REEF domain in a REEF staff address ("rose@reef.org" ->
    "rose@REEF.org"). REEF is an acronym and is capitalized everywhere else in
    customer-facing copy, but Airtable stores staff addresses lowercase, so the
    2026-09-09 QA walkthrough's capitalization fix did not survive the next
    regeneration when it was only hand-applied to the generated data.js.

    Only the domain is touched, and only when it is exactly reef.org: the local
    part is left alone (it is a real mailbox name), and a non-REEF address --
    notably the customer's own Contact Email -- is returned unchanged.
    """
    if not addr or "@" not in addr:
        return addr or ""
    local, _, domain = addr.rpartition("@")
    return f"{local}@REEF.org" if domain.lower() == "reef.org" else addr


def is_test_org(org_name):
    """True for QA/test bookings, which REEF names with a leading "ZZZ"
    (e.g. "ZZZ TEST ORG -- Riverside Academy"). Matched case-insensitively
    and tolerant of leading whitespace, since the value is typed by hand
    into Airtable's Organization Name field."""
    return (org_name or "").lstrip().upper().startswith("ZZZ")


def money(n):
    return f"${n:,.2f}"


def date_pretty(iso):
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %-d, %Y")


def us_date(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d")
    return f"{d.month}/{d.day}/{d.year % 100:02d}"


def date_span(arrival_iso, departure_iso):
    """Customer-facing date line (2026-09-28 copy review):
        one day            -> "March 17, 2027"      (not "Mar 17, 2027 - Mar 17, 2027")
        same month         -> "April 13–14, 2027"
        different months   -> "March 30 – April 2, 2027"
        different years    -> "December 30, 2026 – January 2, 2027"
    """
    if not arrival_iso:
        return ""
    a = datetime.strptime(arrival_iso[:10], "%Y-%m-%d")
    d = datetime.strptime((departure_iso or arrival_iso)[:10], "%Y-%m-%d")
    if a == d:
        return f"{a:%B} {a.day}, {a.year}"
    if a.year != d.year:
        return f"{a:%B} {a.day}, {a.year} – {d:%B} {d.day}, {d.year}"
    if a.month != d.month:
        return f"{a:%B} {a.day} – {d:%B} {d.day}, {a.year}"
    return f"{a:%B} {a.day}–{d.day}, {a.year}"


def date_weekday(iso):
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%A") if iso else ""


# Bookings.Location values -> customer-facing wording. The raw values are
# internal categories ("Off-site Florida Keys") that read like a database
# field on a customer page. An itinerary JSON "location" overrides this.
CUSTOMER_LOCATION = {
    "Key Largo (REEF)": "REEF Ocean Exploration Center, Key Largo",
    "Off-site Florida Keys": "Florida Keys field sites",
    "Hybrid": "REEF Ocean Exploration Center and Florida Keys field sites",
}

# Organization Type -> the label for the customer's own contact person
# ("School Contact" rather than the old "Your Contact's Role").
CONTACT_LABEL_BY_ORG_TYPE = {
    "K-12 School": "School Contact",
    "College / University": "Group Contact",
}


def join_list(items):
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def max_complimentary_chaperones(students, threshold):
    """Largest chaperone count that is still fully complimentary under the
    Expedition rule MIN(chaperones, FLOOR((students + chaperones) / threshold))."""
    c = 0
    while (students + c + 1) // threshold >= c + 1:
        c += 1
    return c


def chaperone_policy(b):
    """Plain-language explanation of the complimentary chaperone count,
    computed from the same rule as the Bookings '# Free Chaperones' formula
    (checked against the live formula 2026-09-28), so the customer can see
    WHY their number is what it is instead of decoding an internal rule."""
    s, c, free = b["students"] or 0, b["chaperones"] or 0, b["free_chaperones"] or 0
    discovery = "Discovery" in (b.get("pricing_model") or "") and not b.get("free_chap_override")
    lines = []
    if discovery:
        cap = s // 15
        lines.append(f"One chaperone space is complimentary for every 15 students. With {s} students, "
                     f"your group can bring up to {cap} chaperone{'s' if cap != 1 else ''} at no charge.")
    else:
        t = b["free_chap_threshold"]
        total = s + c
        earned = total // t
        cap = max_complimentary_chaperones(s, t)
        lines.append(f"One chaperone space is complimentary for every {t} people in your group, counting "
                     f"students and chaperones together. Your group of {s} students and {c} chaperones "
                     f"({total} people) earns {earned} complimentary space{'s' if earned != 1 else ''}.")
        if cap >= c:
            lines.append(f"With {s} students, you can bring up to {cap} chaperones before any chaperone is billed.")
    if c and free >= c:
        headline = f"All {c} chaperone{'s' if c != 1 else ''} are complimentary."
    elif c:
        headline = f"{free} of your {c} chaperones are complimentary."
    else:
        headline = "No chaperones are listed yet."
    # Policy (Martha, 2026-09-28): anyone beyond the complimentary ratio pays the full per-participant package, same as a student.
    lines.append("Each additional chaperone beyond the complimentary spaces pays the full "
                 "per-participant package price, the same as a student.")
    return headline, lines


def fetch_booking_data(record_id):
    """Pulls the Bookings record + its linked REEF Personnel contact and
    normalizes them into one plain dict. Every value here traces to a
    live Airtable field -- field names match Airtable's REST API exactly
    (see list_tables_for_base output captured 2026-09-03)."""
    rec = airtable_get(BOOKINGS_BASE, BOOKINGS_TABLE, record_id)
    f = rec["fields"]

    # Linked-record fields come back from the REST API as bare record ID
    # strings (the Airtable UI and MCP show names, the API does not), so
    # each linked record has to be fetched to get anything human-readable.
    activity_topics = fetch_linked_names(
        BOOKINGS_BASE, ACTIVITIES_TABLE, f.get("Activities Requested"), "Educational Topic")
    activity_names = fetch_linked_names(
        BOOKINGS_BASE, ACTIVITIES_TABLE, f.get("Activities Requested"), "Activity Name")

    program_type = {}
    program_type_ids = f.get("Program Type") or []
    if program_type_ids:
        pt = airtable_get(BOOKINGS_BASE, PROGRAM_TYPES_TABLE, program_type_ids[0])["fields"]
        program_type = {
            "name": pt.get("Program Type Name", ""),
            "tagline": pt.get("Tagline", ""),
            "description": pt.get("Customer-Facing Description", ""),
            # Attachment cells are absent (not empty lists) when unset.
            "heroes": {key: (pt.get(field) or []) for key, field in PROPOSAL_HERO_FIELDS.items()},
        }

    personnel_record_id = f.get("REEF Booking Contact (EPO Personnel Record ID)")
    reef_contact = {}
    if personnel_record_id:
        p = airtable_get(EPO_BASE, PERSONNEL_TABLE, personnel_record_id)["fields"]
        reef_contact = {
            "name": p.get("Full name", ""),
            "title": p.get("Customer-Facing Title", ""),
            "email": reef_email(p.get("Email", "")),
            "phone": p.get("Phone", ""),
            "welcome_line": p.get("Proposal Welcome Line", ""),
        }

    return {
        "record_id": record_id,
        "org_name": f.get("Organization Name", ""),
        "contact_name": f.get("Primary Contact Name", ""),
        "contact_role": f.get("Contact Role", ""),
        "contact_email": f.get("Contact Email", ""),
        "contact_phone": f.get("Contact Phone", ""),
        "arrival_date": f.get("Arrival Date"),
        "departure_date": f.get("Departure Date"),
        "location": f.get("Location", ""),
        "students": f.get("# Student Participants", 0),
        "chaperones": f.get("# Total Chaperones", 0),
        "booking_type": f.get("Booking Type", ""),
        "total_package_price": f.get("Total Package Price", 0),
        "price_per_paid_space": f.get("Price Per Paid Space", 0),
        "status": f.get("Status", ""),
        "proposal_response": f.get("Proposal Response", ""),
        "agreement_contract_status": f.get("Agreement/Contract Status"),
        "deposit_payment_status": f.get("Deposit/Payment Status"),
        "payment_tier": f.get("Payment Tier", ""),
        "deposit_due_now": f.get("Deposit Due Now", 0),
        "payment2_amount": f.get("Payment 2 Amount", 0),
        "payment2_due_date": f.get("Payment 2 Due Date"),
        "final_amount": f.get("Final Payment Amount", 0),
        "final_due_date": f.get("Final Payment Due Date"),
        "reef_contact": reef_contact,
        "reef_program_fees_total": f.get("REEF Program Fees Total", 0),
        "reef_supplies_total": f.get("REEF Supplies Total", 0),
        "campus_facility_fee_total": f.get("Campus Facility Fee Total", 0),
        "proposal_included": f.get("Proposal — What's Included", ""),
        "proposal_not_included": f.get("Proposal — What's Not Included", ""),
        "proposal_assumptions": f.get("Proposal — Assumptions", ""),
        "proposal_next_steps": f.get("Proposal — Next Steps", ""),
        "proposal_version": f.get("Proposal Version"),
        "proposal_sent_date": f.get("Proposal Sent Date"),
        "free_chaperones": f.get("# Free Chaperones", 0),
        # The ratio behind "# Free Chaperones" (defaults to 9 when no
        # override is set on this booking -- see the field's own formula:
        # MIN(chaperones, ROUNDDOWN((students+chaperones)/threshold, 0))).
        # Pulled through so the proposal can state the actual rule in
        # plain language instead of only showing the resulting number
        # (QA walkthrough, 2026-09-09 -- pricing clarity finding).
        "free_chap_threshold": f.get("Free Chap Threshold Override") or 9,
        "free_chap_override": f.get("Free Chap Threshold Override"),
        "pricing_model": f.get("Pricing Model (auto)", ""),
        "org_type": f.get("Organization Type", ""),
        # Concurrent-rotation setup question (added 2026-09-28): "Yes --
        # rotating cohorts" / "No -- full group together" / "Not yet
        # determined". Blank = decide from the captured itinerary.
        "rotation_setting": f.get("Concurrent Cohort Rotation", ""),
        "cohort_count": f.get("# Cohorts"),
        "proposal_optional": f.get("Proposal — Optional Add-Ons (Not Priced)", ""),
        "activity_topics": activity_topics,
        "activity_names": activity_names,
        "program_type": program_type,
        "asana_task_id": f.get("Asana Task ID", ""),
        # Approved-to-Share lock (2026-09-25). Collaborator fields come back
        # from the REST API as {"id", "email", "name"} objects.
        "approved_to_share": bool(f.get("Approved to Share")),
        "approved_stage": f.get("Approved to Share — Stage") or "",
        "approved_version": f.get("Approved for Proposal Version"),
        "approved_by": (f.get("Approved to Share By") or {}).get("name", ""),
        "approved_date": f.get("Approved to Share Date") or "",
    }


def fetch_linked_names(base_id, table_name, record_ids, name_field):
    """Resolves a multipleRecordLinks cell (a list of record ID strings)
    into that field's values across the linked records.

    Handles both single-value fields (singleLineText -> "Boat Snorkel")
    and multi-value ones (multipleSelects -> ["Citizen Science",
    "Caribbean Fish ID"]), which the REST API returns as a plain list of
    strings. Results are flattened, empties dropped, and duplicates
    removed while preserving first-seen order, since several linked
    records routinely share a value.

    Deliberately lets an HTTP error propagate: a stale link is a data
    problem worth failing loudly on, consistent with NoItineraryCaptured."""
    names = []
    for record_id in record_ids or []:
        if not isinstance(record_id, str) or not record_id.startswith("rec"):
            continue
        value = airtable_get(base_id, table_name, record_id)["fields"].get(name_field)
        if not value:
            continue
        for item in (value if isinstance(value, list) else [value]):
            item = str(item).strip()
            if item and item not in names:
                names.append(item)
    return names


def split_items(text):
    """Splits a free-text Airtable field into bullet items.

    Staff write these fields inconsistently: "Proposal — What's Included"
    and "— What's Not Included" are semicolon-separated lists, while
    "— Assumptions" is written as prose sentences. Splitting on newlines
    then on semicolons alone therefore mangles Assumptions, cutting
    "...program days. Rate assumes both days run as outlined" into one
    item. Breaking on either terminator handles all three, and leaves a
    field written with neither as a single item.

    Trailing semicolons are dropped; authored periods are kept as-is
    rather than second-guessing how staff wrote the sentence."""
    if not text:
        return []
    parts = [line.strip() for line in str(text).splitlines() if line.strip()]
    if len(parts) == 1:
        parts = re.split(r"(?<=[.;])\s+", parts[0])
    cleaned = [part.strip().rstrip(";").strip() for part in parts if part.strip(" ;")]
    # QA walkthrough (2026-09-09): staff type these fields with inconsistent
    # capitalization (some items start mid-sentence lowercase, e.g. "pre- and
    # post-activity debriefs..."), which reads as sloppy in a bulleted list.
    # Capitalize only the first character -- leave everything else exactly
    # as staff wrote it, so "REEF educator-led..." isn't touched.
    return [item[0].upper() + item[1:] if item else item for item in cleaned]


def download_hero_photos(b, booking_dir):
    """Downloads each populated Program Types hero attachment into the
    booking's own photos/ directory and returns the relative paths
    render.js expects in data.proposal.photos.

    The download is not incidental. Airtable attachment URLs
    (v5.airtableusercontent.com) are short-lived signed links that expire
    within hours, so writing them straight into data.js would produce a
    page whose photography silently breaks the same day. Committing the
    file alongside the page is what makes it durable -- publish-booking.yml
    already stages bookings/ wholesale, so these get committed with it.

    Sections whose attachment is empty are simply omitted from the returned
    dict; render.js then falls back to its own decorative gradient SVG."""
    heroes = (b.get("program_type") or {}).get("heroes") or {}
    photos = {}
    for key, attachments in heroes.items():
        if not attachments:
            continue
        attachment = attachments[0]
        url = attachment.get("url")
        if not url:
            continue
        ext = os.path.splitext(attachment.get("filename") or "")[1].lower() or ".jpg"
        photos_dir = booking_dir / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        (photos_dir / f"{key}{ext}").write_bytes(resp.content)
        photos[key] = f"photos/{key}{ext}"
    return photos


def load_itinerary(record_id):
    """Returns the booking's captured itinerary, normalized to a dict:

        {"days": [...], "rotation": dict|None, "scheduleFormat": str|None,
         "summary": str|None, "location": str|None}

    Two file shapes are accepted, so every itinerary captured before
    2026-09-28 keeps working unchanged:
      - legacy: a bare JSON list of day objects (standard day-by-day format)
      - schemaVersion 2: an object with "days" plus an optional "rotation"
        block (concurrent-cohort rotation schedule), "scheduleFormat",
        "summary" and customer-facing "location". See ROTATION SCHEMA below.
    """
    path = ITINERARIES_DIR / f"{record_id}.json"
    if not path.exists():
        raise NoItineraryCaptured(
            f"No captured itinerary for booking {record_id} at {path}. "
            "This script deliberately does not fabricate a day-by-day schedule -- "
            "export the itinerary JSON from that booking's already-sent proposal first "
            "(see OXP_System_Connection_Roadmap_2026-09-03.md, priority #4, for the real fix)."
        )
    with open(path) as fh:
        raw = json.load(fh)
    if isinstance(raw, list):
        return {"days": raw, "rotation": None, "scheduleFormat": None,
                "summary": None, "location": None, "audiences": None}
    rotation = raw.get("rotation")
    if rotation:
        validate_rotation(rotation, record_id)
    return {
        "days": raw.get("days") or [],
        "rotation": rotation,
        "scheduleFormat": raw.get("scheduleFormat"),
        "summary": raw.get("summary"),
        "location": raw.get("location"),
        # Approve & Share audience content (2026-09-28) -- see audience_views.py
        # and the "audiences" section of itineraries/README.md.
        "audiences": raw.get("audiences"),
    }


# ---------------------------------------------------------------- Rotation schedule
#
# ROTATION SCHEMA (itineraries/<record_id>.json -> "rotation"), added
# 2026-09-28 for bookings where participant cohorts complete activities
# concurrently (e.g. Ben Gamla: four cohorts rotating through three
# experiences). render.js draws it as a cohort-by-time matrix; nothing
# here is specific to any one booking.
#
#   heading (optional)        "Four Cohorts, One Coordinated Day"; auto if omitted
#   intro (optional)          customer-facing paragraph above the matrix
#   startTime / endTime       "HH:MM" 24h, the program window shown
#   slotMinutes (optional)    grid resolution, default 15; every time must land on it
#   cohortSizeLabel (opt.)    e.g. "About 28-29 students" until exact sizes are set
#   cohorts   [ {id, label, size|null} ]
#   stations  [ {id, name, short, location, type: experience|meal|shared, color: 0-5} ]
#   assignments [ {cohort, station, start, end} ]   one row per cohort per activity
#   shared (optional) [ {station, start, end} ]     whole-group blocks (arrival, welcome)
#   departure (optional) {time, label, note}
#   notes (optional) [string]                       customer-relevant logistics only
#
# Gaps between a cohort's assignments render as transition time. Overlaps,
# unknown ids and times outside the window fail loudly here rather than
# producing a schedule that silently misstates where a cohort is.

class InvalidRotation(Exception):
    """Raised when a captured rotation schedule is internally inconsistent."""


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def clock(hhmm):
    """'13:30' -> '1:30 PM'."""
    total = _minutes(hhmm)
    h, m = divmod(total, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def clock_range(start, end):
    """'09:00','11:30' -> '9:00–11:30 AM'; spans noon -> '11:30 AM–12:30 PM'."""
    a, b = clock(start), clock(end)
    if a[-2:] == b[-2:]:
        return f"{a[:-3]}–{b}"
    return f"{a}–{b}"


def validate_rotation(rot, record_id):
    problems = []
    slot = rot.get("slotMinutes") or 15
    try:
        start, end = _minutes(rot["startTime"]), _minutes(rot["endTime"])
    except (KeyError, ValueError):
        raise InvalidRotation(f"{record_id}: rotation needs startTime and endTime as HH:MM")
    cohorts = {c["id"] for c in rot.get("cohorts") or []}
    stations = {s["id"] for s in rot.get("stations") or []}
    if not cohorts:
        problems.append("no cohorts")
    if not stations:
        problems.append("no stations")
    by_cohort = {}
    for a in (rot.get("assignments") or []) + [dict(x, cohort="*") for x in rot.get("shared") or []]:
        if a["cohort"] != "*" and a["cohort"] not in cohorts:
            problems.append(f"assignment for unknown cohort {a['cohort']!r}")
        if a["station"] not in stations:
            problems.append(f"assignment for unknown station {a['station']!r}")
        s, e = _minutes(a["start"]), _minutes(a["end"])
        if not (start <= s < e <= end):
            problems.append(f"{a['cohort']} {a['station']} {a['start']}-{a['end']} is outside "
                            f"{rot['startTime']}-{rot['endTime']} or ends before it starts")
        if (s - start) % slot or (e - start) % slot:
            problems.append(f"{a['cohort']} {a['station']} {a['start']}-{a['end']} is not on the "
                            f"{slot}-minute grid")
        targets = cohorts if a["cohort"] == "*" else [a["cohort"]]
        for c in targets:
            by_cohort.setdefault(c, []).append((s, e, a["station"]))
    for c, spans in by_cohort.items():
        spans.sort()
        for (s1, e1, st1), (s2, e2, st2) in zip(spans, spans[1:]):
            if s2 < e1:
                problems.append(f"cohort {c}: {st1} and {st2} overlap")
    if problems:
        raise InvalidRotation(f"{record_id}: rotation schedule is inconsistent: " + "; ".join(problems))


def station_times(rot):
    """{station_id: "Cohorts C & D: 9:00–11:30 AM · Cohorts A & B: 12:15–2:30 PM"}
    Derived from the assignments, so the activity cards below the matrix can
    never disagree with it. Cohorts sharing an identical time are grouped."""
    labels = {c["id"]: c["label"] for c in rot["cohorts"]}
    order = [c["id"] for c in rot["cohorts"]]
    out = {}
    for st in rot["stations"]:
        slots = {}
        for a in rot["assignments"]:
            if a["station"] == st["id"]:
                slots.setdefault((a["start"], a["end"]), []).append(a["cohort"])
        parts = []
        for (s, e), cs in sorted(slots.items(), key=lambda kv: _minutes(kv[0][0])):
            cs = sorted(cs, key=order.index)
            if len(cs) == 1:
                who = labels[cs[0]]
            else:
                who = "Cohorts " + ", ".join(cs[:-1]) + " & " + cs[-1]
            parts.append(f"{who}: {clock_range(s, e)}")
        for sh in rot.get("shared") or []:
            if sh["station"] == st["id"]:
                parts.append(f"All cohorts: {clock_range(sh['start'], sh['end'])}")
        out[st["id"]] = " · ".join(parts)
    return out


NUMBER_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six",
                7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}


def number_word(n, lower=False):
    w = NUMBER_WORDS.get(n, str(n))
    return w.lower() if lower else w


# ---------------------------------------------------------------- Proposal page

class NoRotationCaptured(NoItineraryCaptured):
    """Raised when Bookings says cohorts rotate concurrently ("Concurrent
    Cohort Rotation" = Yes) but the captured itinerary has no rotation
    schedule. Same deliberate-failure pattern as NoItineraryCaptured."""


def resolve_schedule_format(b, itin):
    """Which Day-by-Day presentation a proposal gets (2026-09-28):

      "rotation" -- cohorts rotate among concurrent activities; render.js
                    draws the cohort-by-time Rotation Schedule matrix.
      "standard" -- the whole group follows one schedule; the simpler
                    chronological day-by-day cards.
      "pending"  -- not yet determined; a clear "schedule being finalized"
                    state with no internal planning language.

    The Bookings field "Concurrent Cohort Rotation" is the setup question
    staff answer. Blank falls back to what the captured itinerary contains,
    so bookings captured before this field existed are unchanged."""
    setting = (b.get("rotation_setting") or "").strip().lower()
    rot = itin.get("rotation")
    if setting.startswith("yes"):
        if not rot:
            raise NoRotationCaptured(
                f"Booking {b['record_id']} is set to 'Concurrent Cohort Rotation = Yes' but "
                f"itineraries/{b['record_id']}.json has no 'rotation' block. Capture the cohort "
                "schedule (cohorts, stations, times) first -- see ROTATION SCHEMA in this file.")
        fmt = "rotation"
    elif setting.startswith("not yet"):  # must precede the "no" check
        fmt = "pending"
    elif setting.startswith("no"):
        fmt = "standard"
    else:
        fmt = "rotation" if rot else (itin.get("scheduleFormat") or "standard")
        if fmt == "rotation" and not rot:
            fmt = "standard"
    if fmt == "rotation" and b.get("cohort_count") and int(b["cohort_count"]) != len(rot["cohorts"]):
        raise InvalidRotation(
            f"Booking {b['record_id']}: '# Cohorts' is {b['cohort_count']} but the captured rotation "
            f"has {len(rot['cohorts'])} cohorts. Fix one so the proposal and Airtable agree.")
    return fmt


def first_clause(text):
    """'Meals. Lunch time is built in...' -> 'Meals' (for the approval summary)."""
    return re.split(r"(?<=[a-z0-9)])[.;:]\s|\s\u2014\s|\s\(", text, maxsplit=1)[0].rstrip(".")


def lower_first(text):
    """'Transportation to...' -> 'transportation to...' for mid-sentence use;
    leaves acronyms/proper starts like 'REEF' or 'John Pennekamp' alone."""
    if len(text) > 1 and text[0].isupper() and text[1].islower() and text.split(" ")[0] not in ("John",):
        return text[0].lower() + text[1:]
    return text


def build_proposal_data(b, photos=None):
    """Builds the docType "proposal" shape -- the advanced six-section
    customer proposal experience in assets/render.js. Parallel to
    build_confirmed_page_data() below; a booking gets one or the other
    depending on Status (see main()).

    Note the two separate meta objects render.js reads: the shared
    top-level data.meta (sampleFlag, used by both modes) and the
    proposal-specific data.proposal.meta.

    Copy and structure revised 2026-09-28 (system-wide customer-facing
    review): consistent terminology -- "group" is the whole booking,
    "cohort" a rotating subset, "experience"/"station" an activity,
    "schedule" the timing -- plus the concurrent-rotation format, a plain-
    language chaperone policy, and an approval summary before the CTA."""
    pt = b.get("program_type") or {}
    label, word = PROGRAM_WORDS_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_PROGRAM_WORDS)
    is_group_program = b["booking_type"] != "Facility Rental"

    itin = load_itinerary(b["record_id"])
    days = copy.deepcopy(itin["days"])
    schedule_format = resolve_schedule_format(b, itin)
    rot = copy.deepcopy(itin["rotation"]) if schedule_format == "rotation" else None

    students = b["students"] or 0
    chaperones = b["chaperones"] or 0
    free_chaperones = b["free_chaperones"] or 0
    n_days = len(days) or 1
    length_word = f"{number_word(n_days, lower=True)}-day"

    dates_line = date_span(b["arrival_date"], b["departure_date"])
    location = itin.get("location") or CUSTOMER_LOCATION.get(b["location"], b["location"]) \
        or "REEF Ocean Exploration Center, Key Largo"
    group_line = f"{students} students + {chaperones} chaperones"

    hours = None
    experiences = []
    if rot:
        hours = clock_range(rot["startTime"], rot["endTime"])
        times = station_times(rot)
        experiences = [s["name"] for s in rot["stations"] if s.get("type", "experience") == "experience"]
        n_cohorts = len(rot["cohorts"])
        rot.setdefault("heading", f"{number_word(n_cohorts)} Cohorts, One Coordinated Day"
                       if n_days == 1 else f"{number_word(n_cohorts)} Cohorts, One Coordinated Schedule")
        rot["startLabel"] = clock(rot["startTime"])
        rot["endLabel"] = clock(rot["endTime"])
        for d in days:
            for blk in d.get("blocks", []):
                if blk.get("station"):
                    blk["when"] = times.get(blk["station"], "")
                    st = next((s for s in rot["stations"] if s["id"] == blk["station"]), {})
                    blk["color"] = st.get("color")
                    blk["location"] = st.get("location")
        format_line = (f"{number_word(n_cohorts)} cohorts rotating through "
                       f"{number_word(len(experiences), lower=True)} hands-on experiences")
    else:
        experiences = b.get("activity_names") or []
        format_line = "Full group together" if n_days == 1 else f"{n_days}-day itinerary"

    if itin.get("summary"):
        summary = itin["summary"]
    elif not is_group_program:
        summary = f"A {word} at {location}, prepared for {b['org_name'] or 'your group'}."
    elif rot:
        summary = (f"A {length_word} marine science {word} for {students} students, organized into "
                   f"{number_word(len(rot['cohorts']), lower=True)} cohorts rotating through "
                   f"{number_word(len(experiences), lower=True)} hands-on experiences at {location}.")
    else:
        summary = (f"A {length_word} marine science {word} for {students} students and "
                   f"{chaperones} chaperones at {location}.")

    if schedule_format == "rotation":
        schedule_label = "Schedule & Rotations"
    elif n_days == 1:
        schedule_label = "Schedule"
    else:
        schedule_label = "Day by Day"

    focus = " · ".join(b.get("activity_topics") or []) or None

    reef = b["reef_contact"]
    reef_first = (reef.get("name") or "").split(" ")[0] or "Your REEF contact"
    # QA walkthrough (2026-09-09): the contact's own welcome_line is the
    # personal note; the Program Type description is only a fallback.
    welcome_body = [reef.get("welcome_line")] if reef.get("welcome_line") else (
        [pt.get("description")] if pt.get("description") else [])

    contact_label = CONTACT_LABEL_BY_ORG_TYPE.get(b.get("org_type"), "Group Contact")
    contact_line = ", ".join(x for x in [b["contact_name"], b["contact_role"]] if x)

    included = split_items(b["proposal_included"])
    not_included = split_items(b["proposal_not_included"])
    optional = split_items(b.get("proposal_optional"))

    glance = [
        {"k": "Date" if n_days == 1 else "Dates", "v": dates_line},
        {"k": "Group Size", "v": group_line},
        {"k": "Program Hours" if hours else "Length", "v": hours or (f"{n_days} days" if n_days > 1 else "One day")},
        {"k": "Location", "v": location},
        {"k": "Format", "v": format_line, "wide": True},
    ]
    if focus:
        glance.append({"k": "Focus", "v": focus, "wide": True})

    policy_headline, policy_lines = chaperone_policy(b)
    total = money(b["total_package_price"])

    what_could_change = [
        "Changes to your student or chaperone count",
        "A different date or program hours",
        "Adding or removing activities",
    ] + [f"Adding an optional item ({lower_first(first_clause(o))})" for o in optional]

    confirm_summary = [
        {"k": "Date", "v": f"{date_weekday(b['arrival_date'])}, {dates_line}" if n_days == 1 else dates_line},
        {"k": "Group", "v": f"{students} students and {chaperones} chaperones"
                            + (f" (all {chaperones} complimentary)" if chaperones and free_chaperones >= chaperones
                               else f" ({free_chaperones} complimentary)" if chaperones else "")},
    ]
    if rot:
        confirm_summary.append({"k": "Format", "v": format_line})
    if experiences:
        confirm_summary.append({"k": "Activities", "v": join_list(experiences)})
    confirm_summary.append({"k": "Location & hours" if hours else "Location",
                            "v": f"{location}, {hours}" if hours else location})
    confirm_summary.append({"k": "Estimated total", "v": total})
    if not_included:
        clauses = [first_clause(x) for x in not_included]
        confirm_summary.append({"k": "Not included",
                                "v": join_list(clauses[:1] + [lower_first(c) for c in clauses[1:]])})

    deposit = b.get("deposit_due_now") or 0
    next_steps = split_items(b.get("proposal_next_steps")) or [
        "Review each section of this proposal with your team.",
        "Select “Looks Good — Prepare My Contract,” or “Request a Change” if anything needs adjusting.",
        f"{reef_first} prepares your contract with the payment schedule"
        + (f", starting with a {money(deposit)} deposit to hold your date." if deposit else "."),
        "Once the contract is signed, REEF confirms final logistics with you, including headcount, arrival details, and what to bring.",
    ]

    change_topics = ("cohort assignments, activity timing, group size, transportation, meals, "
                     "accessibility needs, or program content") if rot else (
                    "dates, activities, timing, group size, transportation, meals, accessibility "
                    "needs, or program content")

    return {
        "docType": "proposal",
        "assetDepth": 2,
        "meta": {
            "sampleFlag": False,
            "generatedFrom": b["record_id"],
            "generatedNote": f"Generated by generate_booking_package.py from live Airtable "
                              f"fields on {datetime.utcnow().strftime('%Y-%m-%d')}.",
        },
        "proposal": {
            "meta": {
                "bookingId": b["record_id"],
                "proposalVersion": f"v{b['proposal_version']}" if b.get("proposal_version") else "v1",
                "proposalDate": date_pretty(b["proposal_sent_date"]) if b.get("proposal_sent_date") else "",
                "programTypeLabel": label,
                "programWord": word,
            },
            "summary": summary,
            "scheduleFormat": schedule_format,
            "scheduleLabel": schedule_label,
            "rotation": rot,
            "pendingNote": (f"Your detailed schedule is still being finalized. {reef_first} will share "
                            "exact times before your contract is prepared. The activities below are "
                            "included either way."),
            "group": {
                "orgName": b["org_name"],
                "contactName": b["contact_name"],
                "contactLabel": contact_label,
                "contactLine": contact_line,
                # Kept for older render.js builds; the chip now uses contactLabel/contactLine.
                "gradeLevel": b["contact_role"],
                "students": students,
                "chaperones": chaperones,
            },
            "dates": {
                "label": "Proposed",
                "range": dates_line,
            },
            "location": location,
            "hours": hours,
            "roadmap": {
                "steps": ROADMAP_STEPS,
                # Cancelled has no mapped step and falls back to 1 -- see
                # main(), which also does not route Cancelled here.
                "currentStep": ROADMAP_STEP_BY_STATUS.get(b["status"], 1),
            },
            "cta": {
                "primaryText": "Looks Good — Prepare My Contract",
                "confirmButtonText": "Approve Proposal",
                "primaryConfirmHeadline": "Thank you — your proposal is approved.",
                "primaryConfirmBody": f"{reef_first} will prepare your contract and confirm any remaining "
                                      "details with you by email. Approving doesn't sign anything or "
                                      "commit a payment; the contract is the next step.",
                "secondaryText": "Request a Change",
                "changeFormLabel": f"Tell us about any requested changes to {change_topics}.",
                "changeConfirmHeadline": "Thank you — your change request is on its way.",
                "changeConfirmBody": f"{reef_first} will follow up by email and send a revised "
                                     "proposal if anything changes.",
                "contactEmail": reef.get("email", "") or "explorers@REEF.org",
                "responseWebhookUrl": "https://hooks.zapier.com/hooks/catch/28743322/4hv7eqd/",
            },
            "confirmSummary": confirm_summary,
            "nextSteps": next_steps,
            "reefContact": {
                "name": reef.get("name", ""),
                "role": reef.get("title", ""),
                "photo": None,
                "welcomeLine": reef.get("welcome_line", ""),
                "email": reef.get("email", ""),
                "phone": reef.get("phone", ""),
            },
            "welcome": {
                "body": welcome_body,
                "signOff": reef.get("name", "") or "The REEF Ocean Explorers Team",
            },
            "glance": glance,
            "pillars": PILLARS_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_PILLARS),
            "team": TEAM_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_TEAM),
            "days": days,
            "included": [{
                "title": f"Included in your {label}",
                "items": included,
            }],
            "notIncluded": not_included,
            "optional": optional,
            "photos": photos or {},
            # No credit field exists on the Program Types hero attachments.
            "photoCredits": {},
            "pricing": {
                "tileTotal": {
                    "label": "Estimated Total",
                    "num": total,
                    "unit": f"for {students} students and {chaperones} chaperones",
                },
                "tileRate": {
                    "label": "Per Student",
                    "num": money(b["price_per_paid_space"]),
                    "unit": f"per student for the full {word}",
                },
                "tileChaperones": {
                    "label": "Complimentary Chaperones",
                    "num": f"{free_chaperones} of {chaperones}" if chaperones else "0",
                    "unit": "chaperone spaces at no charge",
                },
                "chaperonePolicy": {"headline": policy_headline, "lines": policy_lines},
                "estimatedTotal": total,
                "estimatedTotalNote": (f"<strong>{total}</strong> is your estimated total, based on the "
                                       "details below. It includes REEF's program fees and every item "
                                       "listed under What's Included. If anything below changes, REEF "
                                       "will send a revised proposal with an updated total."),
                # Customer-relevant "Pricing Based On" list (was "Assumptions
                # behind this rate"), from Bookings "Proposal — Assumptions".
                "assumptions": split_items(b["proposal_assumptions"]),
                "whatCouldChange": what_could_change,
            },
        },
    }


# ---------------------------------------------------------------- Confirmed page

def build_confirmed_page_data(b):
    itin = load_itinerary(b["record_id"])
    days_raw = copy.deepcopy(itin["days"])
    if itin["rotation"]:
        # The pre-trip page has no rotation matrix yet; give each activity its
        # cohort times as text so the confirmed page stays accurate.
        times = station_times(itin["rotation"])
        for d in days_raw:
            for blk in d.get("blocks", []):
                if blk.get("station") and not blk.get("time"):
                    blk["time"] = times.get(blk["station"], "")
    days = []
    for d in days_raw:
        days.append({
            "dayNumber": d["dayNumber"],
            "totalDays": d["totalDays"],
            "title": d["title"],
            "theme": d["theme"],
            "morningLabel": d["blocks"][0]["title"] if d["blocks"] else "",
            "afternoonLabel": d["blocks"][-1]["title"] if len(d["blocks"]) > 1 else "",
            "learningOutcome": "; ".join(s.split(" (")[0] for s in d.get("studentsWill", [])[:2]),
            "blocks": d["blocks"],
            "studentsWill": d.get("studentsWill", []),
            "outcomesNote": d.get("outcomesNote"),
        })

    status = b["agreement_contract_status"]
    if status == "Signed":
        action_needed = {"show": False}
        agreement = {"status": "Signed", "zohoSignUrl": None, "lastUpdated": None}
    elif status == "Sent":
        action_needed = {
            "show": True,
            "headline": "Your agreement is ready to sign",
            "detail": "Review and sign your Ocean Explorers agreement to lock in your dates.",
            "ctaText": "Review & Sign Agreement",
            # Zoho Sign integration is out of scope for this build (Martha, 2026-09-03).
            "ctaUrl": None,
        }
        agreement = {"status": "Sent", "zohoSignUrl": None, "lastUpdated": None}
    else:
        action_needed = {
            "show": True,
            "headline": "Your contract is being prepared",
            "detail": "REEF is finalizing your agreement based on the proposal you approved. You'll receive it here once it's ready to sign.",
            "ctaText": None,
            "ctaUrl": None,
        }
        agreement = {"status": "Not Sent", "zohoSignUrl": None, "lastUpdated": None}

    payment_schedule = {
        "tier": b["payment_tier"],
        "items": [
            {"label": "Deposit (due now)", "amount": money(b["deposit_due_now"]), "dueDate": None},
            {"label": "Payment 2", "amount": money(b["payment2_amount"]),
             "dueDate": date_pretty(b["payment2_due_date"]) if b["payment2_due_date"] else None},
            {"label": "Final Payment", "amount": money(b["final_amount"]),
             "dueDate": date_pretty(b["final_due_date"]) if b["final_due_date"] else None},
        ],
        "total": money(b["total_package_price"]),
        "note": "Generated from REEF Bookings' payment-schedule fields (added 2026-09-03); "
                "confirm the 50/50 Payment 2 / Final split assumption before treating as final.",
    }

    return {
        "docType": "pretrip",
        "assetDepth": 2,
        "meta": {
            "sampleFlag": False,
            "generatedFrom": b["record_id"],
            "generatedNote": f"Generated by generate_booking_package.py from live Airtable "
                              f"fields on {datetime.utcnow().strftime('%Y-%m-%d')}.",
        },
        "program": {
            "name": "Florida Keys Marine Science Expedition",
            "track": "Expedition",
            "groupName": b["org_name"],
            "schoolOrg": b["org_name"],
            "gradeLevel": b["contact_role"],
            "groupSize": f"{b['students']} Students / {b['chaperones']} Chaperones",
            "location": "REEF Campus, Key Largo",
            "dates": {
                "label": "Confirmed" if b["status"] == "Confirmed" else "Proposed",
                "range": f"{date_pretty(b['arrival_date'])} - {date_pretty(b['departure_date'])}",
            },
        },
        "contacts": {
            "educatorName": b["contact_name"],
            "reefEducatorName": b["reef_contact"].get("name", ""),
            "reefEducatorTitle": b["reef_contact"].get("title", ""),
            "reefEducatorWelcomeLine": b["reef_contact"].get("welcome_line", ""),
            "reefPhone": b["reef_contact"].get("phone", ""),
            "reefEmail": b["reef_contact"].get("email", ""),
        },
        "hero": {
            "kicker": "OCEAN EXPLORERS\nEXPEDITION PACKET",
            "eyebrowTag": "Florida Keys Marine Science Expedition",
            "headline": "From Student to Scientist in Key Largo",
            "promise": "Turn the ocean into your classroom. Your students won't just study marine science \u2014 they become part of it.",
            "imageUrl": "../../assets/photos/hero-reef-shark.jpg",
            "imageCredit": "Photo: Jeffrey Haines / REEF",
        },
        "actionNeeded": action_needed,
        "agreement": agreement,
        "paymentSchedule": payment_schedule,
        "nextSteps": {
            "items": [
                "Review and sign your agreement once it's sent (see above).",
                "Return your group's signed waivers and health/medical forms.",
                "Confirm final headcount with your REEF educator at least 2 weeks before arrival.",
                "Reach out any time with questions before your Expedition.",
            ],
        },
        "welcome": {
            "body": [
                "We're glad your group is joining us. This packet lays out what to expect from your "
                "Florida Keys Marine Science Expedition \u2014 where your students will identify reef fish, "
                "explore real coral reef, mangrove, and seagrass habitats, and practice the same "
                "citizen-science methods REEF's volunteer network uses across the Caribbean and beyond.",
                "This is not a sightseeing trip. It's a working Expedition: your students will observe, "
                "identify, survey, investigate, and contribute \u2014 and leave with a real sense of what it "
                "means to practice marine science, not just read about it.",
            ],
            "signOff": "The REEF Ocean Explorers Team",
        },
        "glanceNote": "A quick-scan summary for planning. Full detail \u2014 including “students will” "
                      "outcomes and gear notes \u2014 follows on the day-by-day pages.",
        "days": days,
    }


# ---------------------------------------------------------------- Contract

def set_paragraph_text(paragraph, new_text):
    if not paragraph.runs:
        paragraph.add_run(new_text)
        return
    paragraph.runs[0].text = new_text
    for r in paragraph.runs[1:]:
        r.text = ""


def replace_exact(doc, old, new, occurrence=0):
    count = 0
    for p in doc.paragraphs:
        if p.text.strip() == old:
            if count == occurrence:
                set_paragraph_text(p, new)
                return True
            count += 1
    return False


def insert_watermark_banner(doc):
    banner = doc.paragraphs[0].insert_paragraph_before()
    run = banner.add_run(
        "⚠ GENERATED FROM LIVE AIRTABLE DATA -- REVIEW BEFORE SENDING."
    )
    run.bold = True
    run.font.size = docx.shared.Pt(12)
    run.font.color.rgb = docx.shared.RGBColor(0xB2, 0x1D, 0x1D)


def build_contract(b, out_path):
    """Same merge logic proven in gen_contract.py 2026-09-03, now driven
    by live-fetched values instead of a hardcoded dict. This does not
    re-derive the freeform program description / topics text (those were
    hand-composed for the Riverside Academy proof-of-concept and Airtable
    has no single field holding "topics covered" as a clean list yet) --
    those two paragraphs are left as the template's originals for a human
    to review and edit before sending, same as today's manual process,
    until that content gets a real field to live in."""
    doc = docx.Document(TEMPLATE_PATH)
    insert_watermark_banner(doc)

    replace_exact(doc, "The Benjamin School", b["org_name"], occurrence=0)
    replace_exact(doc, "The Benjamin School", b["org_name"], occurrence=0)
    replace_exact(doc, "Erin Gigele", b["contact_name"])
    replace_exact(doc, "7th Grade Marine Science", b["contact_role"])
    replace_exact(doc, "561-626-3747 (ext. 3362)", b["contact_phone"])
    replace_exact(doc, "erin.ryan@thebenjaminschool.org", b["contact_email"])
    replace_exact(doc, "Contract Date: 9/2/2025", f"Contract Date: {datetime.utcnow().strftime('%-m/%-d/%Y')}")
    replace_exact(doc, "Program Dates: 4/16/26- 4/17/26",
                  f"Program Dates: {us_date(b['arrival_date'])} - {us_date(b['departure_date'])}")
    replace_exact(
        doc,
        "Program Location: Key Largo: REEF Campus, Pennekamp Coral Reef State Park, MOTE Coral Nursey",
        f"Program Location: {b['location']}",
    )
    replace_exact(doc, "Total Participants: 90", f"Total Participants: {b['students'] + b['chaperones']}")
    replace_exact(doc, "Total Program Cost Rate: $24,510",
                  f"Total Program Cost Rate: {money(b['total_package_price'])}")
    replace_exact(
        doc,
        "Program Rate Per Person (90): $272",
        f"Program Rate Per Person ({b['students'] + b['chaperones']}): {money(round(b['price_per_paid_space']))}",
    )
    replace_exact(doc, "$1000 to secure group space", f"{money(b['deposit_due_now'])} to secure group space")
    if b["payment2_due_date"]:
        replace_exact(
            doc, "$11,755 by 8/18/2025 (Half after 1000)",
            f"{money(b['payment2_amount'])} by {date_pretty(b['payment2_due_date'])} (Payment 2)",
        )
    if b["final_due_date"]:
        replace_exact(
            doc, "$11,755 by 1/16/2026 (Final Payment)",
            f"{money(b['final_amount'])} by {date_pretty(b['final_due_date'])} (Final Payment)",
        )
    replace_exact(doc, "Print Name\tRose Kelly", f"Print Name\t{b['reef_contact'].get('name', '')}")

    doc.save(out_path)


# ---------------------------------------------------------------- Approved-to-Share lock

def check_share_approval(b, is_proposal):
    """Returns a list of reasons this booking is NOT approved to be published
    for the page this run would build. An empty list means approved.
    See the module docstring for the rules (Martha, 2026-09-25)."""
    needed_stage = SHARE_STAGE_PROPOSAL if is_proposal else SHARE_STAGE_PRETRIP
    problems = []
    if not b["approved_to_share"]:
        problems.append("'Approved to Share' is not checked")
    if b["approved_stage"] != needed_stage:
        problems.append(
            f"'Approved to Share — Stage' is {b['approved_stage'] or 'blank'!r}, "
            f"but this run would build the {needed_stage!r} stage")
    if b["proposal_version"] is not None and b["approved_version"] != b["proposal_version"]:
        problems.append(
            f"'Approved for Proposal Version' is {b['approved_version']!r} but the current "
            f"'Proposal Version' is {b['proposal_version']!r} -- a revised proposal needs a fresh approval")
    if not b["approved_by"]:
        problems.append("'Approved to Share By' is blank")
    return problems


def _data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def build_preview_html(page_data, booking_dir, title, reasons, views=None):
    """Packs a generated page into ONE self-contained HTML file for internal
    review: styles, render.js, page data, the REEF logo and hero photos are
    all inlined, so the file opens straight from an Asana attachment with no
    public URL involved. The customer response webhook is stripped so a
    reviewer clicking the buttons writes nothing back to Airtable, and a
    red INTERNAL PREVIEW banner sits above the page."""
    data = copy.deepcopy(page_data)

    def inline_photos(node):
        if isinstance(node, dict):
            return {k: inline_photos(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline_photos(v) for v in node]
        if isinstance(node, str) and node.startswith("photos/") and (booking_dir / node).exists():
            return _data_uri(booking_dir / node)
        return node

    data = inline_photos(data)
    logo_uri = _data_uri(ASSETS_DIR / "reef-logo-white.png")
    data.setdefault("hero", {})["logoUrl"] = logo_uri
    cta = (data.get("proposal") or {}).get("cta")
    if isinstance(cta, dict):
        cta.pop("responseWebhookUrl", None)

    css = (ASSETS_DIR / "styles.css").read_text()
    js = (ASSETS_DIR / "render.js").read_text()
    # render.js builds the nav logo path from the page's folder depth; point
    # it at the inlined copy instead (harmless no-op if that line changes).
    js = js.replace('return "../".repeat(depth) + "assets/reef-logo-white.png";',
                    "return " + json.dumps(logo_uri) + ";")
    shell = BOOKING_PAGE_SHELL_TEMPLATE.format(title="INTERNAL PREVIEW — " + title,
                                               robots=TEST_PAGE_ROBOTS_META)
    banner = (
        '<div style="background:#b3261e;color:#fff;padding:14px 18px;font:600 15px/1.4 '
        'system-ui,sans-serif;text-align:center;position:sticky;top:0;z-index:9999;">'
        "INTERNAL PREVIEW — NOT PUBLISHED — DO NOT FORWARD TO THE CUSTOMER. "
        "Response buttons are disabled in this preview.</div>\n"
    )
    shell = shell.replace('<link rel="stylesheet" href="../../assets/styles.css">',
                          "<style>\n" + css + "\n</style>")
    # Approve & Share (2026-09-28): the audience views ride along in the same
    # file so a reviewer can open each one (render.js switches on ?view=...)
    # without anything being published. Webhooks are stripped here too.
    preview_views = {}
    for key, vdata in (views or {}).items():
        vd = copy.deepcopy(vdata)
        vd.setdefault("hero", {})["logoUrl"] = logo_uri
        if isinstance((vd.get("view") or {}).get("approval"), dict):
            vd["view"]["approval"]["webhookUrl"] = None
        preview_views[key] = vd
    shell = shell.replace('<script src="data.js"></script>',
                          "<script>window.BOOKING_DATA = " + json.dumps(data) + ";"
                          + ("window.REEF_PREVIEW_VIEWS = " + json.dumps(preview_views) + ";" if preview_views else "")
                          + "</script>")
    shell = shell.replace('<script src="../../assets/render.js"></script>',
                          "<script>\n" + js.replace("</script>", "<\\/script>") + "\n</script>")
    shell = shell.replace("<body>\n", "<body>\n" + banner, 1)
    out = booking_dir / "INTERNAL-PREVIEW.html"
    out.write_text(shell)
    return out


def attach_to_asana(task_gid, path):
    """Uploads a file as an attachment on an Asana task (internal only)."""
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        resp = requests.post(
            f"{ASANA_API_ROOT}/attachments",
            headers={"Authorization": f"Bearer {ASANA_API_KEY}"},
            data={"parent": task_gid},
            files={"file": (Path(path).name, fh, mime)},
            timeout=120,
        )
    resp.raise_for_status()
    print(f"Attached {Path(path).name} to Asana task {task_gid}")


# ---------------------------------------------------------------- Review gate (Asana)

def asana_project_for_booking(booking_type):
    """Same OXP-vs-Facility-Rental routing used by Zap 1 (EPO to Asana Task
    Sync): Facility Rental bookings go to the Facility Rental project,
    everything else (all "OXP - ..." types) goes to the OXP project."""
    if booking_type == "Facility Rental":
        return ASANA_FACILITY_PROJECT_GID
    return ASANA_OXP_PROJECT_GID


def create_review_task(b, page_url, contract_url, preview_reasons=None, attachments=()):
    """Creates an Asana task gating human review before the generated
    proposal/contract is sent to the customer (Martha, 2026-09-04): the
    page and contract still auto-deploy exactly as before, but staff must
    not email the link to a customer until this task is marked complete.
    No automation is tied to completing it -- it is a pure process gate
    for Rose, not a technical enforcement mechanism.

    If this booking already has a tracking Asana task (Bookings' "Asana
    Task ID", written by Zap 1 at intake), the review task is created as a
    subtask of it so it shows up nested under the booking's existing
    task. Otherwise it's created directly in the OXP or Facility Rental
    project, same routing Zap 1 uses.

    Requires an ASANA_API_KEY GitHub Actions secret (a Personal Access
    Token) -- see README.md's "Setting up the ASANA_API_KEY secret"
    section for how to create one. If it's not set, this logs a warning
    and returns without failing the rest of the pipeline run.
    """
    if not ASANA_API_KEY:
        print(
            "ASANA_API_KEY not set -- skipping review task creation. "
            "The page and contract were still generated normally; see "
            "README.md to enable this step.",
            file=sys.stderr,
        )
        return

    if preview_reasons is not None:
        # PREVIEW run: nothing was published. The generated page is attached
        # to this task as a self-contained file for internal review.
        stage = SHARE_STAGE_PROPOSAL if contract_url is None else SHARE_STAGE_PRETRIP
        name = f"PREVIEW (not published) — review before sharing — {b['org_name']}"
        notes = (
            f"Auto-generated by generate_booking_package.py for booking {b['record_id']}.\n\n"
            "NOTHING HAS BEEN PUBLISHED OR SENT. This booking is not yet approved to share, "
            "so the page was generated as an internal preview only:\n"
            + "".join(f"- {r}\n" for r in preview_reasons)
            + "\nThe attached INTERNAL-PREVIEW.html is the full page (open it in a browser"
            + (", plus the attached contract .docx" if contract_url else "")
            + "). Check dates, price, org/contact details, and the day-by-day content.\n"
            "Its last step, Approve & Share, has Preview buttons for the four audience views "
            "(administrator, educator, family, student) -- check each one too.\n\n"
            "When it's ready to share, in REEF Bookings | PILOT set on this booking:\n"
            "- Approved to Share: checked\n"
            f"- Approved to Share — Stage: {stage}\n"
            f"- Approved for Proposal Version: {b['proposal_version'] if b['proposal_version'] is not None else '(leave blank -- no Proposal Version set)'}\n"
            "- Approved to Share By: your name\n"
            "- Approved to Share Date: today\n"
            "Then re-run the 'Publish Booking Package (manual)' workflow. Only then does the page "
            f"go live at {page_url} -- and only then should anyone send the link to the customer."
        )
    else:
        name = f"Published after approval — confirm before sending — {b['org_name']}"
        notes = (
            f"Auto-generated by generate_booking_package.py for booking {b['record_id']}.\n\n"
            "Review before this goes to the customer:\n"
            f"- Proposal/pre-trip page: {page_url}\n"
            "  (may take a couple of minutes to go live after this task is created)\n"
            + (f"- Contract: {contract_url}\n\n" if contract_url else
               "- Contract: not generated yet -- this booking is still pre-commitment "
               "(Quoting / Proposal Sent / Verbal Yes). The contract is produced once "
               "Status reaches 'Contracted'.\n\n")
            + "Check dates, price, org/contact details, and the day-by-day content for accuracy.\n\n"
            "This task is a process gate only -- marking it complete does not trigger anything "
            "automated. It's the documented signal that a human has reviewed both documents and "
            "it's OK for staff to send the link to the customer. Do not send the link before this "
            "is checked off."
            f"\n\nApproved to share by {b['approved_by']} on {b['approved_date'] or '(no date set)'} "
            f"(stage: {b['approved_stage']}, proposal version: {b['approved_version']})."
        )

    payload = {"data": {"name": name, "notes": notes, "assignee": ASANA_REVIEWER_GID}}
    parent_gid = b.get("asana_task_id")
    if parent_gid:
        payload["data"]["parent"] = parent_gid
    else:
        payload["data"]["projects"] = [asana_project_for_booking(b["booking_type"])]

    resp = requests.post(
        f"{ASANA_API_ROOT}/tasks",
        headers={"Authorization": f"Bearer {ASANA_API_KEY}"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    task = resp.json()["data"]
    print(f"Created Asana review task {task['gid']} (assigned to Rose): {task.get('permalink_url', '')}")
    for path in attachments:
        attach_to_asana(task["gid"], path)
    return task["gid"]


# Search-engine exclusion for test/QA bookings. A ZZZ record is deliberately
# run through the real publish pipeline (see the sampleFlag override in
# main()), so its page lands on the public Pages site like any other -- the
# on-page SAMPLE banner makes that obvious to a human who opens it, but not
# to a search crawler that indexes the URL. This keeps test pages out of
# search results entirely.
#
# It lives in the generated shell rather than in the page file because
# index.html is rewritten on every publish: the 2026-09-09 QA walkthrough
# added this tag by hand to bookings/zzz-test-org-riverside-academy-proposal-qa/
# and the very next regeneration silently stripped it back out.
TEST_PAGE_ROBOTS_META = (
    '<meta name="robots" content="noindex, nofollow">\n'
)

BOOKING_PAGE_SHELL_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{robots}<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&display=swap">
<title>{title}</title>
<link rel="stylesheet" href="../../assets/styles.css">
</head>
<body>
  <div class="page">
    <div id="sample-flag"></div>
    <div id="hero"></div>
    <div id="mini-nav"></div>
    <div id="action-needed"></div>
    <div id="snapshot"></div>
    <div id="welcome"></div>
    <div id="glance"></div>
    <div id="day-by-day"></div>
    <div id="students-will-do"></div>
    <div id="gear"></div>
    <div id="next-steps"></div>
    <div id="share-views"></div>
    <div id="closing-cta"></div>
    <div id="site-footer"></div>
  </div>

  <script src="data.js"></script>
  <script src="../../assets/render.js"></script>
</body>
</html>
"""
# ^ This is the same thin shell every booking page in bookings/<slug>/ uses
# (identical to bookings/sample-ocean-explorers-2day/index.html, which is
# hand-maintained separately since it's a fixed sample, not a generated
# booking). Every generated booking gets its own copy of this file because
# the earlier version of this script wrote data.js alone -- that page
# 404'd on GitHub Pages until this was added (2026-09-03, after Martha's
# first live test run). If the shared shell markup ever changes, update it
# both here and in the sample page.


SHARE_PAGE_SHELL_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&display=swap">
<title>{title}</title>
<link rel="stylesheet" href="../../../../assets/styles.css">
</head>
<body>
  <div class="page"></div>
  <script src="data.js"></script>
  <script src="../../../../assets/render.js"></script>
</body>
</html>
"""
# ^ Approve & Share audience views (2026-09-28): bookings/<slug>/share/<view>/.
# Each view has its OWN data.js holding only that view's fields (see
# audience_views.py and PRIVACY.md) -- never the coordinator's full data.


def build_share_views(b, page_data, is_proposal, page_url):
    """Builds the share block + the four audience payloads from the same
    canonical facts as the proposal. For a pre-trip booking the facts are
    rebuilt with build_proposal_data() (no photos) so both stages project
    from one function, not two copies of the booking's details."""
    pd = page_data["proposal"] if is_proposal else build_proposal_data(b)["proposal"]
    itin = load_itinerary(b["record_id"])
    share, views = audience_views.build_views(
        b, pd, itin, money, date_pretty, page_url,
        generated_on=date_pretty(datetime.utcnow().strftime("%Y-%m-%d")))
    if is_proposal:
        page_data["proposal"]["share"] = share
    else:
        page_data["share"] = share
        # The pre-trip page now draws the same rotation matrix (was a known
        # gap: cohort times showed only as text in the activity list).
        if pd.get("scheduleFormat") == "rotation" and pd.get("rotation"):
            page_data["rotation"] = pd["rotation"]
    sample = is_test_org(b["org_name"])
    return {k: audience_views.view_page_data(v, sample) for k, v in views.items()}


def write_share_views(booking_dir, view_data, org_name):
    for key, data in view_data.items():
        d = booking_dir / "share" / key
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "data.js", "w") as f:
            f.write("/* GENERATED by generate_booking_package.py -- do not hand-edit. "
                    "Contains ONLY the fields this audience view shows. */\n")
            f.write("window.BOOKING_DATA = " + json.dumps(data, indent=2) + ";\n")
        with open(d / "index.html", "w") as f:
            f.write(SHARE_PAGE_SHELL_TEMPLATE.format(
                title=f"{org_name} — {data['view']['title']} — REEF"))
        print(f"Wrote {d / 'data.js'}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python generate_booking_package.py <booking_record_id>", file=sys.stderr)
        sys.exit(1)
    record_id = sys.argv[1]

    b = fetch_booking_data(record_id)

    # Checked before anything is written: a cancelled booking has no
    # designed page behavior yet, and the pre-trip branch below would
    # otherwise publish its itinerary as if the trip were still on.
    if b["status"] == "Cancelled":
        raise CancelledBookingNotSupported(
            f"Booking {record_id} has Status 'Cancelled'. This script does not publish a page "
            "for cancelled bookings: what the public page should show in that case -- a "
            "cancellation notice, an unpublished/removed page, a redirect, or nothing at all -- "
            "has not been designed yet, and defaulting to the confirmed/pre-trip packet would "
            "quietly advertise a cancelled group's itinerary as though it were still happening. "
            "Decide the intended behavior first, then teach this script that rule explicitly."
        )

    slug = slugify(b["org_name"])
    is_proposal = b["status"] in PROPOSAL_STATUSES

    # Approved-to-Share lock (Martha, 2026-09-25): decided BEFORE anything is
    # written. Unapproved runs write only to a temp folder outside the repo,
    # so the workflow's `git add bookings/ contracts/` sees nothing to commit
    # and nothing is pushed or deployed to the public site.
    preview_reasons = check_share_approval(b, is_proposal)
    preview = bool(preview_reasons)
    if preview:
        out_root = Path(tempfile.mkdtemp(prefix="reef-preview-"))
        bookings_out, contracts_out = out_root / "bookings", out_root / "contracts"
        print("NOT APPROVED TO SHARE -- PREVIEW ONLY, nothing will be published:")
        for r in preview_reasons:
            print(f"  - {r}")
    else:
        bookings_out, contracts_out = BOOKINGS_OUT_DIR, CONTRACTS_OUT_DIR
        print(f"Approved to share by {b['approved_by']} ({b['approved_stage']}) -- publishing.")

    bookings_out.mkdir(parents=True, exist_ok=True)
    contracts_out.mkdir(parents=True, exist_ok=True)

    booking_dir = bookings_out / slug
    booking_dir.mkdir(exist_ok=True)

    # Which page this booking gets is purely a function of Status. The slug
    # is deliberately the same either way, so a booking's URL does not change
    # when it moves from proposal to confirmed -- the page the customer
    # already has a link to just becomes the pre-trip packet.
    if is_proposal:
        page_data = build_proposal_data(b, photos=download_hero_photos(b, booking_dir))
        print(f"Status {b['status']!r} -> proposal page")
    else:
        page_data = build_confirmed_page_data(b)
        print(f"Status {b['status']!r} -> confirmed/pre-trip page")

    # Test/QA records are deliberately run through the real publish pipeline
    # -- that end-to-end run IS the check (Unified Dashboard Implementation
    # Plan, Section H QA criteria), so the fix is never to block them, only
    # to make them unmistakable. Every page this script writes lands on the
    # public Pages site via deploy.yml, and a test booking that renders
    # without the SAMPLE FORMAT banner reads as a genuine booking to anyone
    # who finds the URL (exactly what happened with
    # bookings/zzz-test-org-riverside-academy-proposal-qa/).
    #
    # So this is an unconditional last-word override, applied here rather
    # than inside build_confirmed_page_data() on purpose: it sits immediately
    # before the write, after all page-shaping logic, so no present or future
    # branch above can leave a ZZZ record unbannered.
    if is_test_org(b["org_name"]):
        page_data.setdefault("meta", {})["sampleFlag"] = True

    # Approve & Share audience views (2026-09-28). Built from the same facts,
    # written to share/<view>/ with per-view data files, and gated by the
    # same Approved-to-Share lock (preview runs write them to the temp dir).
    page_url = f"{PAGES_BASE_URL}/bookings/{slug}/"
    view_data = build_share_views(b, page_data, is_proposal, page_url)
    write_share_views(booking_dir, view_data, b["org_name"])

    with open(booking_dir / "data.js", "w") as f:
        f.write("/* GENERATED by generate_booking_package.py -- do not hand-edit. */\n")
        f.write("window.BOOKING_DATA = " + json.dumps(page_data, indent=2) + ";\n")
    print(f"Wrote {booking_dir / 'data.js'}")

    page_title = (f"{b['org_name']} — REEF Proposal" if is_proposal
                  else f"{b['org_name']} — Expedition Packet")
    with open(booking_dir / "index.html", "w") as f:
        f.write(BOOKING_PAGE_SHELL_TEMPLATE.format(
            title=page_title,
            # Real bookings get no robots meta at all (unchanged behavior);
            # only test/QA records are excluded from search.
            robots=TEST_PAGE_ROBOTS_META if is_test_org(b["org_name"]) else "",
        ))
    print(f"Wrote {booking_dir / 'index.html'}")

    # Contracts are gated on commitment, not just on which page was built.
    # Everything this script writes is published to the public Pages site,
    # and a booking still at Quoting / Proposal Sent / Verbal Yes has not
    # agreed to anything yet -- putting a signable agreement up at that
    # point invites a customer to sign terms nobody has negotiated. The
    # contract appears once the booking reaches Contracted.
    contract_path = contracts_out / f"{slug}-contract.docx"
    if is_proposal:
        contract_url = None
        print(f"Skipping contract generation: status {b['status']!r} is pre-commitment "
              f"(no signable contract is published before 'Contracted').")
    else:
        build_contract(b, contract_path)
        contract_url = f"{PAGES_BASE_URL}/contracts/{slug}-contract.docx"
        print(f"Wrote {contract_path}")

    if preview:
        preview_html = build_preview_html(page_data, booking_dir, page_title, preview_reasons,
                                          views=view_data)
        attachments = [preview_html] + ([contract_path] if contract_url else [])
        create_review_task(b, page_url, contract_url,
                           preview_reasons=preview_reasons, attachments=attachments)
        print(f"PREVIEW ONLY -- wrote {preview_html} (attached to the Asana review task). "
              "Nothing under bookings/ or contracts/ was changed, so nothing will be published.")
    else:
        create_review_task(b, page_url, contract_url)


if __name__ == "__main__":
    main()
