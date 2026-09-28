# Captured itineraries

One JSON file per booking, named `<Airtable Bookings record ID>.json`. The publish
pipeline refuses to invent a schedule, so a booking cannot be previewed or published
until its file exists.

## Two accepted shapes

**Legacy (standard day-by-day):** a bare list of day objects:
`[{dayNumber, totalDays, title, theme, blocks: [{time, tag, title, description}], studentsWill, outcomesNote}]`

**Schema v2 (added 2026-09-28):** an object:

```json
{
  "schemaVersion": 2,
  "scheduleFormat": "rotation | standard | pending",
  "location": "Customer-facing location (optional)",
  "summary": "One-sentence program summary for the Overview (optional; auto-built if omitted)",
  "rotation": { ... },
  "days": [ ...same day objects as legacy... ]
}
```

## Rotation schedule (concurrent cohorts)

Use `rotation` when participants are split into cohorts that do different activities
at the same time. Set Bookings → **Concurrent Cohort Rotation** = "Yes — rotating
cohorts" and **# Cohorts** to match. The proposal then shows a cohort-by-time matrix
(cohorts as rows, time as columns, transposed on phones), a legend, a text list, and
activity cards whose times are derived from the matrix.

| Key | Meaning |
|---|---|
| `startTime`, `endTime` | Program window, `HH:MM` 24-hour |
| `slotMinutes` | Grid resolution (default 15). Every time must land on it |
| `cohorts` | `[{id, label, size}]`. Use `size: null` plus `cohortSizeLabel` ("About 28–29 students") until the real sizes are known |
| `stations` | `[{id, name, short, location, type, color}]`. `short` is the phone label (≤10 characters); `type` is `experience`, `meal` or `shared`; `color` is 0–5 |
| `assignments` | `[{cohort, station, start, end}]`, one row per cohort per activity |
| `shared` | Optional whole-group blocks, such as arrival and welcome |
| `departure` | Optional `{time, label, note}` |
| `notes` | Customer-relevant logistics only |
| `heading`, `intro` | Optional customer copy above the matrix |

In `days[].blocks`, reference a station with `"station": "<id>"` instead of typing a
`time`. The cohort times are filled in automatically.

Gaps between a cohort's activities render as transition time. Overlaps, unknown ids,
off-grid times, or a `# Cohorts` mismatch stop the workflow with a clear error.
Nothing is published in that case.

Example: `recqb6DGaeJRpymL2.json` (Ben Gamla Charter School, 4 cohorts, March 17, 2027).

## `audiences` — Approve & Share content (added 2026-09-28)

Optional. Feeds the four audience views built by `pipeline/audience_views.py`
(Administrator Approval Summary, Educator Plan, Family & Chaperone Overview,
Student Preview). Facts (dates, group size, schedule, price, inclusions) are
**never** repeated here: they come from Airtable and the `rotation`/`days`
above. This block holds only the audience-specific extras. Anything left out
is simply not shown; nothing is guessed. REEF-wide standard text (supervision,
payment/cancellation terms, About REEF) lives in `pipeline/content/audience_defaults.json`.

**This repo is public.** No emails, phone numbers, student names, or internal
notes. The pipeline refuses to run if a role has an email, or if any `$` amount
appears in the family or student view.

```jsonc
"audiences": {
  "views": ["administrator", "educator", "family", "student"],   // which to build
  "audienceLabels": { "family": "Ben Gamla parents, guardians and chaperones" },
  "roles": [   // names + titles only; a person may hold several roles
    { "name": "Lindsay Pollack", "title": "Dean of Students", "roles": ["coordinator"],
      "approvalAuthority": false, "audiences": ["administrator", "educator"] },
    { "name": "", "title": "School leadership", "roles": ["decisionMaker"],
      "approvalAuthority": true, "note": "To be confirmed by the school" }
  ],                // roles: coordinator | decisionMaker | planningTeam | audience
  "logistics": {    // shared by several views
    "transportation", "familyTransportation", "meals", "lunch",
    "arrival", "transitions", "departure", "accessibility", "safety",
    "bring": ["..."]
  },
  "outstandingDecisions": ["..."],        // admin + educator, unless overridden
  "administrator": { "purpose", "outstandingDecisions", "approval": true },
  "educator": { "learningObjectives", "cohortAssignments": [{ "cohort", "size", "teachers", "chaperones" }],
                "assignmentsNote", "supervision", "resources", "remainingDecisions" },
  "family": { "generalLocation", "intro", "whyItMatters", "schedule": [{ "time", "label" }],
              "bring", "clothing", "lunch", "transportation", "chaperoneExpectations",
              "deadlines", "fundraisingText", "contactInstructions", "allowDollarAmounts": false },
  "student": { "headline", "intro", "topics", "feel", "bring", "classroomPrep" }
}
```

Per activity block in `days[].blocks[]`, optional `studentBlurb` and
`familyBlurb` give age-appropriate / family-friendly versions of the
description. Without them the standard description is used.

Defaults when omitted: learning objectives = the day's "Students will" lines;
cohort assignment table = one blank row per rotation cohort (a printable
planning sheet); family schedule = derived from the rotation (start, lunch
window, end), so it can never disagree with the matrix.
