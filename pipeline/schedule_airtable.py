"""
schedule_airtable.py -- read a booking's itinerary from Airtable instead of
from itineraries/<record_id>.json (hand-off spec 2026-10-01).

Staff edit a time, activity or cohort in Airtable (tables "Schedule Items"
and "Itinerary Activities"); the next Publish run regenerates every schedule
display from it. This module is deliberately network-free: the Airtable
fetch lives in generate_booking_package.py (fetch_schedule_rows) and hands
plain dicts in here, so everything below is unit-testable.

    schedule_from_rows(booking, rows, json_itin) -> the SAME dict shape
    load_itinerary() returns for a schemaVersion 2 file, so render.js,
    validate_rotation, resolve_schedule_format and the audience pages are
    untouched.

Precedence (decided by the caller): Schedule Items (count) > 0 -> this path
and the JSON's rotation / days[].blocks are ignored; count == 0 -> the JSON
path, unchanged (Hanover and every legacy booking).

Everything is wall-clock Key Largo time. There is no time-zone conversion
anywhere, on purpose.
"""

import copy
import re

# ---------------------------------------------------------------- Airtable field IDs
# Field IDs, not names: they survive a rename in Airtable.

BOOKING_FIELDS = {
    "item_ids": "fldU7Wh5iEubsYwxI",          # Schedule Items (link)
    "activity_ids": "fldAmdGgbJThGCufS",      # Itinerary Activities (link)
    "count": "fldSSMqHPB547irV5",             # Schedule Items (count)
    "cohort_size_label": "fldEluDf2lzg3ehhb",
    "notes": "fldLM08w3h7sokUZF",             # Schedule Notes (customer-facing)
    "intro": "fldhtWfC1vNmUOVBL",             # Schedule Intro (optional override)
    "program_hours": "fld2W7cUnQLismUOU",     # Program Hours (from schedule)
    "row_checks": "fldLgoLWtH7c4PXIV",        # Schedule Row Checks
    "changed_after_approval": "fldi8oF6jigne8mvi",
}

ITEM_FIELDS = {
    "day": "fldD5F2jqNh98G059",
    "block_type": "fldRX68Do7nXfibOc",
    "cohort": "fldyF4IOUHnjLBOhe",
    "start": "fld6ZXXwtnyVQXiJz",
    "end": "flduffPfhDSfUpoRs",
    "station": "fldHPefOFklV1Waav",           # link to Itinerary Activities
    "catalog": "fld0Q5gpC2idnOezC",           # direct link to the Activities catalog
    "name": "fldA1uxhbnsdlnM53",
    "description": "fldD88MQ9xQgKY31T",
    "location": "fld6Lf6mYXQOoYcTA",
    "short": "fldGA0z66oJq6493X",
    "row_check": "fldBdQbcgMPNih7dn",
}

STATION_FIELDS = {
    "label": "fldJq0vMyOnAQsp2Y",
    "catalog": "fld7q85AP3cGa1nvY",           # link to the Activities catalog
    "name": "fldgYk2RvZ6eMZdUF",
    "description": "fldbCkHmE1mN0G0dK",
    "location": "fldAiAJJeBnvcvdtV",
    "row_check": "fldkllfXJ3ZQ4vCZQ",
}

CATALOG_CATEGORY_FIELD = "fld7Gg5VrnDZY825T"  # Activities catalog -> Category

TAG_BY_CATEGORY = {
    "Citizen Science": "Citizen Science",
    "Workshop": "Hands-On Lab",
    "Off-Site Visit": "Field Experience",
    "Field Activity": "Field Experience",
    "Campus Activity": "Education",
    "Travel/Transit": "Travel",
}
DEFAULT_TAG = "Education"

STATION_TYPE_BY_BLOCK_TYPE = {
    "Activity": "experience",
    "Meal / Break": "meal",
    "Whole-Group Block": "shared",
}


class ScheduleError(Exception):
    """The Airtable schedule is missing, inconsistent or uses a bad token.
    Fails the run loudly; nothing is published."""


# ---------------------------------------------------------------- Time helpers

def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def clock(hhmm):
    """'13:30' -> '1:30 PM'."""
    h, m = divmod(minutes(hhmm), 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def clock_range(start, end):
    """'09:00','11:30' -> '9:00–11:30 AM'; spans noon -> '11:30 AM–12:30 PM'."""
    a, b = clock(start), clock(end)
    return f"{a[:-3]}–{b}" if a[-2:] == b[-2:] else f"{a}–{b}"


_NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
              7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _word(n):
    return _NUM_WORDS.get(n, str(n))


def _num(x):
    """2.0 -> '2', 2.5 -> '2.5', 2.25 -> '2.25'."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def format_duration(mins):
    """90 -> '1.5 hours', 60 -> '1 hour', 45 -> '45 minutes', 135 -> '2.25 hours'."""
    if mins < 60:
        return f"{mins} minute" + ("" if mins == 1 else "s")
    hours = mins / 60
    return f"{_num(hours)} hour" + ("" if hours == 1 else "s")


def format_duration_range(durations):
    """{150} -> '2.5 hours'; {120, 150} -> '2-2.5 hours'; {45, 60} -> '45 minutes to 1 hour'."""
    ds = sorted(durations)
    if len(ds) == 1:
        return format_duration(ds[0])
    lo, hi = ds[0], ds[-1]
    if lo >= 60:
        return f"{_num(lo / 60)}-{_num(hi / 60)} hours"
    if hi < 60:
        return f"{lo}-{hi} minutes"
    return f"{format_duration(lo)} to {format_duration(hi)}"


def format_duration_adj(mins):
    """60 -> 'one-hour', 150 -> '2.5-hour', 45 -> '45-minute' (1-10 as words)."""
    if mins < 60:
        return f"{_word(mins)}-minute"
    hours = mins / 60
    return (f"{_word(int(hours))}-hour" if hours == int(hours) else f"{_num(hours)}-hour")


def format_duration_adj_range(durations):
    ds = sorted(durations)
    if len(ds) == 1:
        return format_duration_adj(ds[0])
    return format_duration_range(ds).replace(" hours", "").replace(" minutes", "") + (
        "-hour" if ds[0] >= 60 else "-minute")


# ---------------------------------------------------------------- Token engine

_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)\s*(?::([^{}]*?))?\s*\}\}")


def render_tokens(text, ctx, where=""):
    """Replaces {{token}} / {{token:Label}} in one string.

    An unknown token, a missing Label, or a stray '{{' / '}}' that is not a
    well-formed token raises ScheduleError -- a literal '{{...}}' must never
    reach a published page."""
    if not isinstance(text, str) or "{{" not in text and "}}" not in text:
        return text

    def sub(m):
        name, label = m.group(1), (m.group(2) or "").strip()
        simple = {
            "arrival_time": ctx["arrival_time"],
            "departure_time": ctx["departure_time"],
            "program_hours": ctx["program_hours"],
            "cohort_count": str(ctx["cohort_count"]),
            "cohort_count_word": _word(ctx["cohort_count"]),
            "experience_count": str(ctx["experience_count"]),
            "experience_count_word": _word(ctx["experience_count"]),
        }
        if name in simple:
            if label:
                raise ScheduleError(f"{where}Token {{{{{name}}}}} does not take a label (got {label!r}).")
            return simple[name]
        if name == "durations":
            parts = [f"{lab} {format_duration_range(d)}" for lab, d in ctx["durations"] if d]
            return "; ".join(parts)
        if name in ("duration", "duration_adj"):
            if not label:
                raise ScheduleError(f"{where}Token {{{{{name}}}}} needs a Station Label, "
                                    f"e.g. {{{{{name}:Boat Tour}}}}.")
            known = dict(ctx["durations_all"])
            if label not in known:
                raise ScheduleError(
                    f"{where}Token {{{{{name}:{label}}}}} names no Station Label on this booking. "
                    f"Station Labels are: {', '.join(sorted(known)) or '(none)'}. "
                    "If a Station Label was renamed, update the text that uses it.")
            d = known[label]
            if not d:
                raise ScheduleError(f"{where}Station {label!r} has no timed rows, so "
                                    f"{{{{{name}:{label}}}}} has no duration.")
            return format_duration_range(d) if name == "duration" else format_duration_adj_range(d)
        raise ScheduleError(f"{where}Unknown schedule token {{{{{name}}}}}. Known tokens: arrival_time, "
                            "departure_time, program_hours, cohort_count, cohort_count_word, "
                            "experience_count, experience_count_word, duration:Label, "
                            "duration_adj:Label, durations.")

    out = _TOKEN_RE.sub(sub, text)
    if "{{" in out or "}}" in out:
        raise ScheduleError(f"{where}Malformed schedule token in text: {text[:120]!r}")
    return out


def apply_tokens(obj, ctx, where=""):
    """Walks dicts/lists and renders every string. Returns a new structure."""
    if isinstance(obj, str):
        return render_tokens(obj, ctx, where)
    if isinstance(obj, list):
        return [apply_tokens(x, ctx, where) for x in obj]
    if isinstance(obj, dict):
        return {k: apply_tokens(v, ctx, where) for k, v in obj.items()}
    return obj


def assert_no_tokens(obj, where="page data"):
    """Last-line guard for EVERY booking (also the legacy JSON path): a literal
    '{{...}}' must never be published."""
    found = []

    def walk(x, path):
        if isinstance(x, str):
            if "{{" in x or "}}" in x:
                found.append(f"{path}: {x[:80]!r}")
        elif isinstance(x, list):
            for i, y in enumerate(x):
                walk(y, f"{path}[{i}]")
        elif isinstance(x, dict):
            for k, y in x.items():
                walk(y, f"{path}.{k}")

    walk(obj, where)
    if found:
        raise ScheduleError("Unresolved {{token}} text would be published:\n  " + "\n  ".join(found[:10]))


# ---------------------------------------------------------------- Row normalisation

def _first(v):
    """Lookup / formula cells arrive as a scalar or a one-item list."""
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("name")
    return v


def _text(v):
    v = _first(v)
    return "" if v is None else str(v).strip()


def normalize_item(rec):
    f = rec.get("fields") or {}
    g = lambda k: f.get(ITEM_FIELDS[k])  # noqa: E731
    day = g("day")
    return {
        "id": rec["id"],
        "day": int(day) if day not in (None, "") else None,
        "block_type": _text(g("block_type")),
        "cohort": _text(g("cohort")),
        "start": _text(g("start")),
        "end": _text(g("end")),
        "station_id": (g("station") or [None])[0],
        "catalog_id": (g("catalog") or [None])[0],
        "name": _text(g("name")),
        "description": _text(g("description")),
        "location": _text(g("location")),
        "short": _text(g("short")),
        "row_check": _text(g("row_check")),
    }


def normalize_station(rec, category=None):
    f = rec.get("fields") or {}
    g = lambda k: f.get(STATION_FIELDS[k])  # noqa: E731
    return {
        "id": rec["id"],
        "label": _text(g("label")),
        "name": _text(g("name")),
        "description": _text(g("description")),
        "location": _text(g("location")),
        "row_check": _text(g("row_check")),
        "catalog_id": (g("catalog") or [None])[0],
        "category": category,
    }


# ---------------------------------------------------------------- Validation

def _slug(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def _abbrev(name):
    first = name.split()[0] if name.split() else name
    return first[:10]


def validate_rows(booking, items, stations, rotation_setting=""):
    """Row-level and cross-row checks that need no sibling timing logic
    (overlap / off-grid / unknown-id stay in validate_rotation)."""
    problems = []
    for it in items:
        if it["row_check"] != "OK":
            problems.append(f"Schedule Item {it['id']} ({it['name'] or it['block_type'] or 'unnamed'}, "
                            f"Day {it['day']}, Cohort {it['cohort'] or 'all'}): Row Check is "
                            f"{it['row_check'] or 'blank'!r}")
    for st in stations:
        if st["row_check"] != "OK":
            problems.append(f"Itinerary Activity {st['id']} ({st['label'] or st['name'] or 'unnamed'}): "
                            f"Row Check is {st['row_check'] or 'blank'!r}")
    row_checks = booking.get("schedule_row_checks")
    if row_checks not in (None, "", "OK") and not problems:
        problems.append(f"Bookings 'Schedule Row Checks' is {row_checks!r}")

    cohorts = sorted({it["cohort"] for it in items if it["cohort"]})
    n = booking.get("cohort_count")
    if (rotation_setting or "").strip().lower().startswith("yes") and len(cohorts) < 2:
        problems.append(f"'Concurrent Cohort Rotation' is Yes but the schedule has "
                        f"{len(cohorts)} distinct cohort(s); rotation needs at least 2")
    if n:
        n = int(n)
        allowed = [chr(ord("A") + i) for i in range(n)]
        stray = [c for c in cohorts if c not in allowed]
        if stray:
            problems.append(f"Cohort letter(s) {', '.join(stray)} are outside the first {n} "
                            f"cohorts ({', '.join(allowed)}) allowed by '# Cohorts'")
        if cohorts and len(cohorts) != n:
            problems.append(f"'# Cohorts' is {n} but the schedule uses {len(cohorts)} "
                            f"distinct cohort(s): {', '.join(cohorts)}")
    if cohorts and len({it["day"] for it in items if it["cohort"]}) > 1:
        problems.append("Cohort rotations are single-day: cohort rows appear on more than one day")

    types_by_station = {}
    for it in items:
        if it["block_type"] in STATION_TYPE_BY_BLOCK_TYPE:
            types_by_station.setdefault(_station_key(it), set()).add(it["block_type"])
    for key, types in types_by_station.items():
        if len(types) > 1:
            problems.append(f"Station {key[1]!r} appears with different Block Types: "
                            f"{', '.join(sorted(types))}")
    if problems:
        raise ScheduleError("Airtable schedule for " + booking["record_id"] + " cannot be published:\n  - "
                            + "\n  - ".join(problems))


def _station_key(it):
    return ("station", it["station_id"]) if it["station_id"] else ("name", it["name"])


# ---------------------------------------------------------------- Builder

def _join_and(items):
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _fmt_program_hours(start, end):
    return f"{clock(start)} – {clock(end)}"


def schedule_from_rows(booking, rows, json_itin=None, log=print):
    """Builds the load_itinerary() dict from Airtable rows.

    booking   fetch_booking_data() dict (needs record_id, cohort_count,
              rotation_setting and the schedule_* fields)
    rows      {"items": [raw Airtable Schedule Items records],
               "stations": [normalised station dicts (normalize_station)]}
    json_itin the legacy JSON itinerary dict (or None); supplies day metadata
              and the "audiences" block only.
    """
    rid = booking["record_id"]
    items = [normalize_item(r) for r in rows["items"]]
    stations = rows["stations"]
    if not items:
        raise ScheduleError(f"{rid}: Schedule Items (count) is positive but no rows were fetched")
    if json_itin and (json_itin.get("rotation") or any(d.get("blocks") for d in json_itin.get("days") or [])):
        log(f"WARNING: {rid}: itineraries/{rid}.json still has rotation / days[].blocks; "
            "Airtable has Schedule Items, so the JSON schedule is ignored.")

    validate_rows(booking, items, stations, booking.get("rotation_setting"))

    station_by_id = {s["id"]: s for s in stations}
    # Category for the tag map: from the linked station's catalog activity.
    for it in items:
        st = station_by_id.get(it["station_id"])
        it["label"] = st["label"] if st else ""
        it["category"] = st["category"] if st else None
        if not it["name"] and st:
            it["name"] = st["name"]

    items.sort(key=lambda it: (it["day"], minutes(it["start"]), it["cohort"], it["id"]))
    arrival = [it for it in items if it["block_type"] == "Arrival"]
    departure = [it for it in items if it["block_type"] == "Departure"]
    body = [it for it in items if it["block_type"] in STATION_TYPE_BY_BLOCK_TYPE]
    total_days = max(it["day"] for it in items)

    # ---- program facts (feed tokens and the Program Hours chip)
    day1 = [it for it in items if it["day"] == 1]
    start_time = min(it["start"] for it in day1 or items)
    if arrival:
        arrival_time = min(arrival, key=lambda it: (it["day"], it["start"]))["start"]
    else:
        arrival_time = start_time
    if departure:
        last_dep = max(departure, key=lambda it: (it["day"], it["start"]))
        end_time = last_dep["start"]
        departure_time = last_dep["start"]
    else:
        end_time = max(it["end"] for it in body if it["end"])
        departure_time = end_time
    program_hours = _fmt_program_hours(arrival_time, departure_time)
    declared = booking.get("schedule_program_hours")
    if declared and re.sub(r"[\s–—-]+", "", declared) != re.sub(r"[\s–—-]+", "", program_hours):
        log(f"WARNING: {rid}: Airtable 'Program Hours (from schedule)' is {declared!r} but the rows "
            f"compute {program_hours!r}; using the computed value.")

    # ---- stations in order of first appearance
    order, by_key = [], {}
    for it in body:
        k = _station_key(it)
        if k not in by_key:
            by_key[k] = {"items": [], "key": k}
            order.append(k)
        by_key[k]["items"].append(it)
    stn_list, used_ids = [], set()
    for idx, k in enumerate(order):
        first = by_key[k]["items"][0]
        sid = _slug(first["label"] or first["short"] or first["name"])
        if not sid or sid in used_ids:
            raise ScheduleError(f"{rid}: two stations resolve to the same id {sid!r}; "
                                "give each Itinerary Activity a distinct Station Label")
        used_ids.add(sid)
        by_key[k]["id"] = sid
        stn_list.append({
            "id": sid,
            "name": first["name"],
            "short": first["short"] or _abbrev(first["name"]),
            "location": next((i["location"] for i in by_key[k]["items"] if i["location"]), ""),
            "type": STATION_TYPE_BY_BLOCK_TYPE[first["block_type"]],
            "color": idx % 6,
        })

    # ---- durations per station label (all cohorts)
    durations_all = {}
    for k in order:
        label = by_key[k]["items"][0]["label"]
        if not label:
            continue
        ds = {minutes(i["end"]) - minutes(i["start"]) for i in by_key[k]["items"] if i["end"]}
        durations_all[label] = ds
    exp_ids = {s["id"] for s in stn_list if s["type"] == "experience"}
    durations_listed = []
    for k in order:
        if by_key[k]["id"] in exp_ids:
            label = by_key[k]["items"][0]["name"]
            durations_listed.append((label, durations_all.get(by_key[k]["items"][0]["label"], set())))

    cohorts = sorted({it["cohort"] for it in items if it["cohort"]})
    ctx = {
        "arrival_time": clock(arrival_time),
        "departure_time": clock(departure_time),
        "program_hours": program_hours,
        "cohort_count": len(cohorts),
        "experience_count": len(exp_ids),
        "durations": durations_listed,
        "durations_all": list(durations_all.items()),
    }

    # ---- days: metadata from the JSON when present, else auto
    json_days = {d.get("dayNumber"): d for d in (json_itin or {}).get("days") or []}
    setting = (booking.get("rotation_setting") or "").strip().lower()
    # "No" / "Not yet determined" mean the whole group is not rotating, even if
    # cohort letters were typed on some rows: render the standard day cards.
    rotation_possible = len(cohorts) >= 1 and not setting.startswith("no")
    days = []
    for n in range(1, total_days + 1):
        meta = json_days.get(n) or {}
        day_body = [it for it in body if it["day"] == n]
        if rotation_possible:
            seen, blocks = set(), []
            for it in day_body:
                k = _station_key(it)
                if k in seen:
                    continue
                seen.add(k)
                blocks.append(_station_block(by_key[k], it))
        else:
            seen_rows, blocks = set(), []
            day_rows = [it for it in items if it["day"] == n
                        and it["block_type"] in {**STATION_TYPE_BY_BLOCK_TYPE, "Arrival": 1, "Departure": 1}]
            for it in sorted(day_rows, key=lambda r: (minutes(r["start"]), r["end"])):
                key = (it["name"], it["start"], it["end"])
                if key in seen_rows:
                    continue
                seen_rows.add(key)
                blocks.append(_timed_block(it))
        days.append({
            "dayNumber": n,
            "totalDays": total_days,
            "title": meta.get("title") or ("One Day on the Reef" if total_days == 1 else f"Day {n}"),
            "theme": meta.get("theme") or _auto_theme(rotation_possible),
            "blocks": blocks,
            "studentsWill": meta.get("studentsWill") or [],
            "outcomesNote": meta.get("outcomesNote"),
        })

    rotation = None
    if rotation_possible:
        assignments = [{"cohort": it["cohort"], "station": by_key[_station_key(it)]["id"],
                        "start": it["start"], "end": it["end"]}
                       for it in body if it["cohort"]]
        shared = [{"station": by_key[_station_key(it)]["id"], "start": it["start"], "end": it["end"]}
                  for it in body if not it["cohort"]]
        n_coh = len(cohorts)
        size_label = (booking.get("schedule_cohort_size_label") or "").strip()
        rotation = {
            "heading": f"{_word(n_coh).capitalize()} Cohorts, One Coordinated Day" if total_days == 1
                       else f"{_word(n_coh).capitalize()} Cohorts, One Coordinated Schedule",
            "intro": (booking.get("schedule_intro") or "").strip()
                     or _auto_intro(n_coh, size_label, stn_list),
            "startTime": start_time,
            "endTime": end_time,
            "slotMinutes": 15,
            "cohortSizeLabel": size_label,
            "cohorts": [{"id": c, "label": f"Cohort {c}", "size": None} for c in cohorts],
            "stations": stn_list,
            "assignments": assignments,
            "notes": [ln.strip() for ln in (booking.get("schedule_notes") or "").splitlines() if ln.strip()],
        }
        if shared:
            rotation["shared"] = shared
        if departure:
            d = max(departure, key=lambda it: (it["day"], it["start"]))
            rotation["departure"] = {"time": d["start"], "label": d["name"] or "Departure",
                                     "note": d["description"]}

    result = {
        "days": days,
        "rotation": rotation,
        "scheduleFormat": "rotation" if rotation else "standard",
        "summary": (json_itin or {}).get("summary"),
        "location": (json_itin or {}).get("location"),
        "audiences": (json_itin or {}).get("audiences"),
        "programHours": program_hours,
        "scheduleSource": "airtable",
    }
    result = apply_tokens(result, ctx, where=f"{rid}: ")
    return result


def _auto_theme(rotation):
    if rotation:
        return ("Students rotate in {{cohort_count_word}} cohorts through {{experience_count_word}} hands-on "
                "experiences led by REEF educators, from {{program_hours}}.")
    return "Hands-on marine science with REEF educators."


def _auto_intro(n_cohorts, size_label, stations):
    names = []
    for s in stations:
        if s["type"] == "meal":
            names.append("a scheduled lunch" if "lunch" in s["name"].lower() else "a scheduled break")
        else:
            names.append(s["name"])
    size = ""
    if size_label:
        size = " of " + (size_label[0].lower() + size_label[1:])
    return (f"Students will be divided into {_word(n_cohorts)} cohorts{size}. "
            f"Cohorts rotate among {_join_and(names)}. Activities run concurrently, so the schedule "
            "below shows where each cohort will be throughout the day.")


def _tag_for(first_item, block_type):
    if block_type == "Meal / Break":
        return "Break"
    return TAG_BY_CATEGORY.get(first_item.get("category") or "", DEFAULT_TAG)


def _station_block(entry, it):
    first = entry["items"][0]
    return {"station": entry["id"], "tag": _tag_for(first, first["block_type"]),
            "title": first["name"], "description": first["description"]}


def _timed_block(it):
    if it["block_type"] in ("Arrival", "Departure"):
        when = clock(it["start"])
        tag = "Travel"
    else:
        when = clock_range(it["start"], it["end"])
        tag = _tag_for(it, it["block_type"])
    return {"time": when, "tag": tag, "title": it["name"] or it["block_type"],
            "description": it["description"]}
