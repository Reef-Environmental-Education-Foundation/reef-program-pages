# REEF Program Pages

Customer-facing itinerary and pre-trip packet pages for REEF Ocean Explorers
Expeditions and Facility Rentals, built as a static site so every booking
gets its own shareable, photo-friendly HTML page instead of a Word doc or PDF.

Live site (once GitHub Pages is enabled): `https://reef-environmental-education-foundation.github.io/reef-program-pages/`

## How this is organized

```
assets/
  styles.css     <- shared REEF design system (navy/teal, Fraunces + Public Sans)
  render.js      <- shared page-building logic. Never fork this per booking.
bookings/
  <booking-slug>/
    index.html   <- thin shell that loads styles.css, its own data.js, then render.js
    data.js      <- sets window.BOOKING_DATA — the only thing that changes per booking
index.html       <- landing page listing all booking pages
.github/workflows/deploy.yml  <- auto-deploys to GitHub Pages on every push to main
```

One shared `render.js` builds every page from a `BOOKING_DATA` object. Adding
a new booking means adding a new `bookings/<slug>/` folder with its own
`data.js` and a copy of the two-line `index.html` shell — never copying or
editing `render.js` or `styles.css` per booking.

## Document types

The format follows the Itinerary Format & Component Spec Martha provided
(`REEF_OceanExplorers_Itinerary_Format_Spec.docx`):

- **`docType: "pretrip"`** — Confirmed/Pre-Trip Packet. Sent to a confirmed
  group: welcome note, trip snapshot, daily schedule, what students will do,
  what to bring, forms & readiness, final reminders. This is the type
  illustrated in `bookings/sample-ocean-explorers-2day/`.
- **`docType: "proposal"`** — Proposal/Sales Itinerary. Sent pre-booking to
  help an educator say yes: cover letter (use `welcome.body`), at-a-glance
  table, day-by-day, why this Expedition works, next steps. `render.js`
  already branches on `docType` — a proposal page just needs a `data.js`
  with `docType: "proposal"` and a `proposal: { whyItWorks, nextSteps }`
  block instead of `gear` / `finalReminders`.

Both types read from the same `days[]` shape, matching the spec's shared
5-part day-page component (day header, time block, outcomes box, day
footer, section divider).

## Adding a new booking by hand (until the generator exists)

1. Copy `bookings/sample-ocean-explorers-2day/` to `bookings/<new-slug>/`.
2. Edit `data.js` with that booking's real program, contact, day-by-day,
   gear, and reminder details. See the schema comment at the top of
   `assets/render.js` for every field `render.js` understands.
3. Add a line for it to the list in the root `index.html`.
4. Commit and push to `main` — the GitHub Actions workflow deploys
   automatically; no manual upload step (this replaces the manual
   GitHub Pages upload process used for the Midriff Islands site, which
   caused a stale-cache incident there — see `TECH_DEBT.md` in that repo).

## Where this is headed

Per REEF's Digital Operations Tracker (D-022/D-023): `data.js` for each
booking should eventually be generated automatically from the matching
REEF Bookings Airtable record and its linked Activities, not hand-typed.
The schema in `render.js`'s header comment is written to match the fields
already available in Bookings/Activities so that generator has a direct
field-to-field mapping to implement. Guardrails carried over from the
format spec: never invent dates, times, prices, capacities, safety claims,
certifications, or vendor confirmations — every `data.js` should be
traceable back to an actual booking record.

## Logo

`assets/reef-logo-white.png` is REEF's official reversed/white logo, pulled
from the REEF Brand Kit ("REEF Logos Reversed - SECONDARY" ▸ "REEF Logo_Reversed_White RGB_For Digital"),
which is the right mark for the dark navy hero banner. `render.js` uses it
by default on every page. If a booking page needs a different mark, set
`hero.logoUrl` in its `data.js` to a path relative to that booking's own
`index.html`; setting `hero.logoFallbackText: true` instead falls back to a
plain text "REEF" wordmark (only meant as a safety net if the image file
is ever missing).

## Enabling GitHub Pages (one-time setup)

In this repo's Settings → Pages, set **Source** to **GitHub Actions**
(not "Deploy from a branch"). The included workflow
(`.github/workflows/deploy.yml`) then deploys automatically on every push
to `main`.
