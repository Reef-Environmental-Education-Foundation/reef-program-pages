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
