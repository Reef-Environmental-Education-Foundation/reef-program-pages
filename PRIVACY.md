# Privacy and GitHub Pages — what this site can and can't protect

Written 2026-09-28 with the Approve & Share audience views.

## The short version

- **Everything published here is public.** GitHub Pages is static public
  hosting. Any page, and the `data.js` file behind it, can be opened by anyone
  who has or guesses the URL. This repository itself is also public, so every
  file in it (including `pipeline/itineraries/*.json`) is readable by anyone.
- **Unguessable or query-string URLs are not security.** `?view=family`,
  `share/family/`, or a long random slug only make a page harder to stumble on.
  They don't restrict who can read it.
- **So nothing is hidden in the browser.** Hiding fields with JavaScript after
  they've been delivered would be fake privacy. Instead, the pipeline decides
  at build time what each page's data file contains.

## How the audience views are built

One booking record, one set of facts, several views:

| Page | URL | Data file contains |
|---|---|---|
| Coordinator proposal (six steps) | `bookings/<slug>/` | Full proposal: schedule, pricing, inclusions, share links |
| Administrator Approval Summary | `bookings/<slug>/share/administrator/` | Pricing and REEF's standard terms. No internal notes or margins. |
| Educator Plan | `bookings/<slug>/share/educator/` | Schedule, rotation, logistics. **No pricing.** |
| Family & Chaperone Overview | `bookings/<slug>/share/family/` | **No pricing, no terms, no booking ID, no REEF staff contact details** |
| Student Preview | `bookings/<slug>/share/student/` | Same as family, simpler |

`pipeline/audience_views.py` writes each view's own `data.js` containing only
that view's fields, and **fails the run** if any price (or any `$` amount)
appears in the family or student data. Someone forwarded the family link gets
a payload with no pricing in it.

**Limit to be clear about:** the family URL sits next to the coordinator URL
(`.../bookings/<slug>/share/family/` vs `.../bookings/<slug>/`). A parent who
edits the address can open the coordinator proposal, which includes the price.
Pricing is not confidential in that sense; it's just not sent to families.

## Rules for anything that goes into this repo

- No student names, rosters, ages, medical or accommodation details for
  individuals, or any protected records.
- No email addresses or phone numbers for school staff. Names and titles only
  (the pipeline rejects emails in `audiences.roles`).
- No internal notes, margins, costs, or vendor pricing.
- Test/QA bookings (`ZZZ` names) always carry the SAMPLE banner.

## Admin approvals

The administrator view has Approve / Send Feedback with required name and
role. There is no login, so anyone with the link could click it. It's a record
of intent that REEF confirms by email, never a signature. Until the Zapier
"CTA Response Write-Back to Airtable" Zap maps `admin_approved` and
`admin_feedback`, the page sends the response by email to the REEF contact
(`ADMIN_WEBHOOK_ENABLED = False` in `audience_views.py`).

## What a future backend would change

The view builder is already shaped like an API: "give me the `family` view of
booking X" returns only the family fields. A backend (for example a small
serverless function in front of Airtable) could serve that same projection
per request, with:

1. Real access control: signed, expiring links or sign-in per contact, so the
   coordinator and administrator pages aren't public.
2. Per-contact status: invited / viewed / approved, recorded by the server.
   A static site can't know who opened a link.
3. A Booking Contacts table in Airtable (name, role, email, approval
   authority, audiences) instead of names in the itinerary JSON.
4. Authenticated approvals tied to a verified person, feeding the contract step.
5. A private data store for anything that shouldn't be public, such as rosters,
   cohort assignments by student, and accommodation plans. That's what the full
   Group Planning Hub would need.
