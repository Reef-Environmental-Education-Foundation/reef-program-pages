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

Review gate (Martha, 2026-09-04): once the confirmed page + contract are
generated below, this script also creates an Asana task for Rose to review
both before staff send the link to the customer -- see create_review_task()
near the bottom of the "Contract" section. The page/contract still
auto-deploy to GitHub Pages exactly as before; the Asana task is a pure
process gate for staff, not a technical block on deploy or on this script.
"""

import copy
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
import docx

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
        "activity_topics": activity_topics,
        "program_type": program_type,
        "asana_task_id": f.get("Asana Task ID", ""),
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
    path = ITINERARIES_DIR / f"{record_id}.json"
    if not path.exists():
        raise NoItineraryCaptured(
            f"No captured itinerary for booking {record_id} at {path}. "
            "This script deliberately does not fabricate a day-by-day schedule -- "
            "export the itinerary JSON from that booking's already-sent proposal first "
            "(see OXP_System_Connection_Roadmap_2026-09-03.md, priority #4, for the real fix)."
        )
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------- Proposal page

def build_proposal_data(b, photos=None):
    """Builds the docType "proposal" shape -- the advanced six-section
    customer proposal experience in assets/render.js. Parallel to
    build_confirmed_page_data() below; a booking gets one or the other
    depending on Status (see main()).

    Note the two separate meta objects render.js reads: the shared
    top-level data.meta (sampleFlag, used by both modes) and the
    proposal-specific data.proposal.meta."""
    pt = b.get("program_type") or {}
    label, word = PROGRAM_WORDS_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_PROGRAM_WORDS)

    # load_itinerary() output already matches the proposal's days schema
    # (dayNumber/totalDays/title/theme/blocks/studentsWill/outcomesNote),
    # so unlike build_confirmed_page_data() -- which reshapes it to add
    # morningLabel/afternoonLabel/learningOutcome for the glance table --
    # it is passed through as-is.
    days = copy.deepcopy(load_itinerary(b["record_id"]))

    students = b["students"] or 0
    chaperones = b["chaperones"] or 0
    free_chaperones = b["free_chaperones"] or 0

    # "Focus" is the deduped Educational Topic values of the linked
    # Activities Requested records, rather than the activity names
    # themselves: the names include pure logistics ("Travel / Transit",
    # "Welcome Program (arrival)") that read badly as a program focus,
    # and repeat the day-by-day section further down the page. Activities
    # with no topic set drop out of the join entirely.
    focus = " · ".join(b.get("activity_topics") or []) or "[confirm from booking data]"

    reef = b["reef_contact"]
    # QA walkthrough (2026-09-09): appending the Program Type's generic
    # marketing description here made "A note from your REEF contact" read
    # as marketing copy rather than a personal note from Rose (or whoever
    # the contact is). The contact's own welcome_line is the personal note;
    # the program description belongs to the Experience section (pillars),
    # not attributed to a person who didn't write it. Fall back to the
    # program description only if the contact has no welcome_line at all,
    # so the note is never blank.
    welcome_body = [reef.get("welcome_line")] if reef.get("welcome_line") else (
        [pt.get("description")] if pt.get("description") else [])

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
            "group": {
                "orgName": b["org_name"],
                "contactName": b["contact_name"],
                # render.js labels this chip "Your Contact's Role".
                "gradeLevel": b["contact_role"],
                "students": students,
                "chaperones": chaperones,
            },
            "dates": {
                "label": "Proposed",
                "range": f"{date_pretty(b['arrival_date'])} - {date_pretty(b['departure_date'])}",
            },
            "roadmap": {
                "steps": ROADMAP_STEPS,
                # Cancelled has no mapped step and falls back to 1 -- see
                # main(), which also does not route Cancelled here.
                "currentStep": ROADMAP_STEP_BY_STATUS.get(b["status"], 1),
            },
            "cta": {
                "primaryText": "Ready to Move Forward",
                "primaryConfirmHeadline": "Thanks — we've got your response!",
                "primaryConfirmBody": "A member of the REEF team will review your response and follow "
                                      "up by email with next steps to confirm your program.",
                "secondaryText": "Need to adjust something?",
                "changeFormLabel": "What would you like us to adjust?",
                "changeConfirmHeadline": "Thanks — we've got your note.",
                "changeConfirmBody": "The REEF Ocean Explorers team will follow up by email to talk "
                                     "through the change.",
                "contactEmail": reef.get("email", "") or "explorers@REEF.org",
                # Implementation Plan item 5 (the Zapier Catch Hook replacing
                # Airtable's broken native webhook) is a separate follow-up.
                # Until it exists render.js logs responses to the console and
                # still shows the on-page confirmation.
                "responseWebhookUrl": "https://hooks.zapier.com/hooks/catch/28743322/4hv7eqd/",
            },
            "reefContact": {
                "name": reef.get("name", ""),
                "role": reef.get("title", ""),
                # EPO REEF Personnel does carry a Photo attachment field.
                # It is not wired up here: like the hero art it would need
                # downloading (Airtable URLs expire), and staff headshots
                # are a separate call from program photography.
                "photo": None,
                "welcomeLine": reef.get("welcome_line", ""),
                "email": reef.get("email", ""),
                "phone": reef.get("phone", ""),
            },
            "welcome": {
                "body": welcome_body,
                "signOff": reef.get("name", "") or "The REEF Ocean Explorers Team",
            },
            "glance": [
                {"k": "Dates", "v": f"{date_pretty(b['arrival_date'])} - {date_pretty(b['departure_date'])}"},
                {"k": "Group Size", "v": f"{students} students + {chaperones} chaperones"},
                {"k": "Location", "v": b["location"] or "Key Largo (REEF)"},
                {"k": "Focus", "v": focus},
            ],
            "pillars": PILLARS_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_PILLARS),
            "team": TEAM_BY_BOOKING_TYPE.get(b["booking_type"], DEFAULT_TEAM),
            "days": days,
            "included": [{
                "title": f"Included in Your {label}",
                "items": split_items(b["proposal_included"]),
            }],
            "notIncluded": split_items(b["proposal_not_included"]),
            "photos": photos or {},
            # No credit field exists on the Program Types hero attachments.
            # REEF's brand standards expect photo credits, so this is a real
            # gap -- called out in the PR rather than filled with a guess.
            "photoCredits": {},
            "pricing": {
                "tileRate": {
                    "label": "Per Student",
                    "num": money(b["price_per_paid_space"]),
                    "unit": f"per student for the full {word}",
                },
                "tileChaperones": {
                    "label": "Complimentary Chaperones",
                    "num": str(free_chaperones),
                    "unit": "included at no charge",
                },
                "ratioNote": f"This proposal is built for {students} students and {chaperones} "
                             f"chaperones, {free_chaperones} of them complimentary.",
                # QA walkthrough (2026-09-09): the page showed the resulting
                # numbers (rate, complimentary count, total) with no
                # explanation of the math behind any of them. These two
                # bullets state the actual rule -- both derived from the
                # same fields "# Free Chaperones" / "# Billable Chaperones"
                # already compute from (confirmed against the live Airtable
                # formula, not guessed): 1 complimentary chaperone space per
                # {threshold} total people, any chaperone beyond that billed
                # at the per-student rate above.
                "conditions": [
                    f"Every group receives 1 complimentary chaperone space for every "
                    f"{b['free_chap_threshold']} total people (students + chaperones) in the "
                    f"group \u2014 REEF calculates this automatically from your group size, so it "
                    f"updates if your numbers change.",
                    "Chaperones beyond the complimentary count shown above are billed at the "
                    "same per-student rate.",
                ],
                "estimatedTotal": money(b["total_package_price"]),
                "estimatedTotalNote": f"<strong>{money(b['total_package_price'])}</strong> estimated "
                                      f"total for the group and dates above, including REEF program "
                                      f"fees and any applicable discount or sales tax. This estimate is "
                                      f"valid for the group size and dates shown here \u2014 REEF will "
                                      f"re-quote automatically if activities, headcount, or dates change.",
                "assumptions": split_items(b["proposal_assumptions"]),
                # Deliberately empty: nothing in Airtable backs a
                # "what could change the price" list, and inventing
                # customer-facing pricing language is not this script's
                # call. render.js omits the section when empty.
                "whatCouldChange": [],
            },
        },
    }


# ---------------------------------------------------------------- Confirmed page

def build_confirmed_page_data(b):
    days_raw = load_itinerary(b["record_id"])
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


# ---------------------------------------------------------------- Review gate (Asana)

def asana_project_for_booking(booking_type):
    """Same OXP-vs-Facility-Rental routing used by Zap 1 (EPO to Asana Task
    Sync): Facility Rental bookings go to the Facility Rental project,
    everything else (all "OXP - ..." types) goes to the OXP project."""
    if booking_type == "Facility Rental":
        return ASANA_FACILITY_PROJECT_GID
    return ASANA_OXP_PROJECT_GID


def create_review_task(b, page_url, contract_url):
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

    name = f"Review proposal + contract before sending — {b['org_name']}"
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

    BOOKINGS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACTS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    booking_dir = BOOKINGS_OUT_DIR / slug
    booking_dir.mkdir(exist_ok=True)

    # Which page this booking gets is purely a function of Status. The slug
    # is deliberately the same either way, so a booking's URL does not change
    # when it moves from proposal to confirmed -- the page the customer
    # already has a link to just becomes the pre-trip packet.
    if b["status"] in PROPOSAL_STATUSES:
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

    with open(booking_dir / "data.js", "w") as f:
        f.write("/* GENERATED by generate_booking_package.py -- do not hand-edit. */\n")
        f.write("window.BOOKING_DATA = " + json.dumps(page_data, indent=2) + ";\n")
    print(f"Wrote {booking_dir / 'data.js'}")

    page_title = f"{b['org_name']} — Expedition Packet"
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
    contract_path = CONTRACTS_OUT_DIR / f"{slug}-contract.docx"
    if b["status"] in PROPOSAL_STATUSES:
        contract_url = None
        print(f"Skipping contract generation: status {b['status']!r} is pre-commitment "
              f"(no signable contract is published before 'Contracted').")
    else:
        build_contract(b, contract_path)
        contract_url = f"{PAGES_BASE_URL}/contracts/{slug}-contract.docx"
        print(f"Wrote {contract_path}")

    page_url = f"{PAGES_BASE_URL}/bookings/{slug}/"
    create_review_task(b, page_url, contract_url)


if __name__ == "__main__":
    main()
