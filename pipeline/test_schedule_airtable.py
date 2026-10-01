"""
Tests for the Airtable-sourced schedule (hand-off 2026-10-01). No network:
Airtable rows are synthesised from the captured Ben Gamla JSON, which is
what the Airtable tables were seeded from (24/24 assignments match).

    python3 -m unittest pipeline/test_schedule_airtable.py     (from repo root)
    python3 -m unittest test_schedule_airtable                 (from pipeline/)
"""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import schedule_airtable as sa  # noqa: E402

BEN_GAMLA = "recqb6DGaeJRpymL2"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pre_airtable"
JSON_PATH = FIXTURE_DIR / f"{BEN_GAMLA}.json"   # the pre-migration file

CATEGORY = {"boat": "Off-Site Visit", "fishid": "Citizen Science", "lionfish": "Workshop",
            "lunch": None, "ecology": "Campus Activity", "endangered": "Campus Activity"}
STATION_LABEL = {"boat": "Boat Tour", "fishid": "Fish ID", "lionfish": "Lionfish",
                 "lunch": "Lunch", "ecology": "Ecology", "endangered": "Species"}


def hhmm_ok(t):
    return t


def build_rows(itin_json):
    """Airtable-shaped rows equivalent to the Ben Gamla JSON."""
    rot = itin_json["rotation"]
    desc = {b["station"]: b["description"] for b in itin_json["days"][0]["blocks"]}
    # Descriptions in Airtable use tokens instead of hard-coded durations/times.
    desc["lunch"] = ("Each cohort has the same {{duration_adj:Lunch}} picnic lunch. Lunch is not "
                     "provided, so students and chaperones should bring a packed lunch.")
    stations, items = [], []
    for st in rot["stations"]:
        stations.append({
            "id": f"recSTN{st['id']}", "label": STATION_LABEL[st["id"]], "name": st["name"],
            "description": desc[st["id"]], "location": st["location"], "row_check": "OK",
            "catalog_id": None, "category": CATEGORY[st["id"]]})
    n = 0

    def item(**kw):
        nonlocal n
        n += 1
        f = {sa.ITEM_FIELDS["day"]: 1, sa.ITEM_FIELDS["row_check"]: "OK"}
        f.update({sa.ITEM_FIELDS[k]: v for k, v in kw.items()})
        return {"id": f"recITEM{n:03d}", "fields": f}

    st_by = {s["id"]: s for s in rot["stations"]}
    items.append(item(block_type="Arrival", start="09:00", name="Arrival", description="", location="", short=""))
    for a in rot["assignments"]:
        st = st_by[a["station"]]
        items.append(item(
            block_type="Meal / Break" if st["type"] == "meal" else "Activity",
            cohort=a["cohort"], start=a["start"], end=a["end"],
            station=[f"recSTN{a['station']}"], name=st["name"], short=st["short"],
            description=desc[a["station"]], location=st["location"]))
    items.append(item(
        block_type="Departure", start="17:00", name="Departure", location="", short="",
        description="The program day ends at {{departure_time}}, when buses return to pick up students."))
    return {"items": items, "stations": stations}


def booking(**kw):
    b = {
        "record_id": BEN_GAMLA, "rotation_setting": "Yes — rotating cohorts", "cohort_count": 4,
        "schedule_count": 26, "schedule_cohort_size_label": "About 28–29 students",
        "schedule_notes": ("Planned activity lengths: {{durations}}.\n"
                           "Every cohort has the same {{duration_adj:Lunch}} lunch.\n"
                           "Buses arrive for a {{arrival_time}} drop-off and return at {{departure_time}}."),
        "schedule_intro": "", "schedule_program_hours": "9:00 AM – 5:00 PM",
        "schedule_row_checks": "OK", "schedule_changed_after_approval": "",
    }
    b.update(kw)
    return b


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(JSON_PATH) as fh:
            raw = json.load(fh)
        cls.json = {"days": raw["days"], "rotation": raw["rotation"], "audiences": raw["audiences"],
                    "summary": raw["summary"], "location": raw["location"]}

    def rows(self):
        return build_rows(self.json)

    def load(self, rows=None, **bk):
        return sa.schedule_from_rows(booking(**bk), rows or self.rows(), self.json, log=lambda *_: None)


class TokenEngine(Base):
    CTX = {"arrival_time": "9:00 AM", "departure_time": "5:00 PM", "program_hours": "9:00 AM – 5:00 PM",
           "cohort_count": 4, "experience_count": 5,
           "durations": [("Boat", {150}), ("Fish ID", {60})],
           "durations_all": [("Boat", {150}), ("Fish ID", {60}), ("Mixed", {120, 150}), ("Short", {45})]}

    def r(self, t):
        return sa.render_tokens(t, self.CTX)

    def test_simple(self):
        self.assertEqual(self.r("{{arrival_time}}-{{departure_time}}"), "9:00 AM-5:00 PM")
        self.assertEqual(self.r("{{program_hours}}"), "9:00 AM – 5:00 PM")
        self.assertEqual(self.r("{{cohort_count}} {{cohort_count_word}} {{experience_count}} "
                                "{{experience_count_word}}"), "4 four 5 five")

    def test_durations(self):
        self.assertEqual(self.r("{{duration:Boat}}"), "2.5 hours")
        self.assertEqual(self.r("{{duration:Fish ID}}"), "1 hour")
        self.assertEqual(self.r("{{duration:Short}}"), "45 minutes")
        self.assertEqual(self.r("{{duration:Mixed}}"), "2-2.5 hours")
        self.assertEqual(self.r("{{duration_adj:Fish ID}}"), "one-hour")
        self.assertEqual(self.r("{{duration_adj:Boat}}"), "2.5-hour")
        self.assertEqual(self.r("{{duration_adj:Short}}"), "45-minute")
        self.assertEqual(self.r("{{durations}}"), "Boat 2.5 hours; Fish ID 1 hour")

    def test_unknown_token_fails(self):
        with self.assertRaisesRegex(sa.ScheduleError, "Unknown schedule token"):
            self.r("at {{start_time}}")

    def test_missing_label_fails(self):
        with self.assertRaisesRegex(sa.ScheduleError, "needs a Station Label"):
            self.r("{{duration}}")

    def test_renamed_label_fails_with_known_labels(self):
        # Edge case 14: Lunch Station Label renamed -> loud, with the valid labels listed.
        with self.assertRaises(sa.ScheduleError) as cm:
            self.r("{{duration_adj:Lunch}}")
        self.assertIn("Station Labels are:", str(cm.exception))
        self.assertIn("Boat", str(cm.exception))

    def test_malformed_fails(self):
        with self.assertRaises(sa.ScheduleError):
            self.r("oops {{arrival_time")

    def test_passes_unicode_and_quotes(self):
        # Edge case 15: curly quotes, en dashes, line breaks survive untouched.
        t = "“Quoted” – dash\nline two ’s"
        self.assertEqual(self.r(t), t)
        self.assertEqual(json.loads(json.dumps(self.r(t))), t)

    def test_assert_no_tokens(self):
        sa.assert_no_tokens({"a": ["fine", {"b": "ok"}]})
        with self.assertRaises(sa.ScheduleError):
            sa.assert_no_tokens({"a": [{"b": "x {{oops}}"}]})


class BenGamlaRegression(Base):
    """Pre-migration (JSON) vs Airtable-sourced render of the same booking."""

    def test_grid_matches_json(self):
        got = self.load()
        want = self.json["rotation"]
        r = got["rotation"]
        key = lambda a: (a["cohort"], a["start"], a["end"], a["station"])  # noqa: E731
        self.assertEqual(len(r["assignments"]), 24)
        # station ids differ (slug of Station Label) -> compare by station NAME
        name = lambda rot: {s["id"]: s["name"] for s in rot["stations"]}  # noqa: E731
        got_n, want_n = name(r), name(want)
        self.assertEqual(
            sorted((a["cohort"], a["start"], a["end"], got_n[a["station"]]) for a in r["assignments"]),
            sorted((a["cohort"], a["start"], a["end"], want_n[a["station"]]) for a in want["assignments"]))
        self.assertEqual(r["cohorts"], want["cohorts"])
        self.assertEqual(r["startTime"], want["startTime"])
        self.assertEqual(r["endTime"], want["endTime"])
        self.assertEqual(r["departure"]["time"], want["departure"]["time"])
        self.assertEqual(r["departure"]["note"].split(". ")[0].rstrip("."),
                         want["departure"]["note"].split(". ")[0].rstrip("."))
        self.assertEqual(r["cohortSizeLabel"], want["cohortSizeLabel"])
        self.assertEqual(r["heading"], want["heading"])
        self.assertEqual(sorted(s["name"] for s in r["stations"]), sorted(s["name"] for s in want["stations"]))
        for s in r["stations"]:
            w = next(x for x in want["stations"] if x["name"] == s["name"])
            self.assertEqual((s["type"], s["location"]), (w["type"], w["location"]))

    def test_station_card_times_match_json(self):
        import generate_booking_package as g
        got = self.load()["rotation"]
        want = self.json["rotation"]
        gt = {s["name"]: g.station_times(got)[s["id"]] for s in got["stations"]}
        wt = {s["name"]: g.station_times(want)[s["id"]] for s in want["stations"]}
        self.assertEqual(gt, wt)

    def test_validates_with_existing_validator(self):
        import generate_booking_package as g
        g.validate_rotation(self.load()["rotation"], BEN_GAMLA)

    def test_days_blocks_and_tags(self):
        got = self.load()
        blocks = got["days"][0]["blocks"]
        self.assertEqual(len(blocks), 6)
        tags = {b["title"]: b["tag"] for b in blocks}
        self.assertEqual(tags["Glass-Bottom Boat Tour"], "Field Experience")
        self.assertEqual(tags["Citizen Science & Fish Identification"], "Citizen Science")
        self.assertEqual(tags["Lionfish Lesson & Dissection"], "Hands-On Lab")
        self.assertEqual(tags["Picnic Lunch"], "Break")
        self.assertEqual(tags["Marine Ecology"], "Education")
        # first-appearance order: A fishid, B lionfish, C/D boat ... (colors follow it)
        self.assertEqual([b["title"] for b in blocks][:3], [
            "Citizen Science & Fish Identification", "Lionfish Lesson & Dissection", "Glass-Bottom Boat Tour"])
        self.assertEqual([s["color"] for s in got["rotation"]["stations"]], [0, 1, 2, 3, 4, 5])

    def test_tokens_resolved_everywhere(self):
        got = self.load()
        sa.assert_no_tokens(got)
        notes = got["rotation"]["notes"]
        self.assertEqual(len(notes), 3)
        self.assertIn("Glass-Bottom Boat Tour 2.5 hours", notes[0])
        self.assertIn("Lionfish Lesson & Dissection 1 hour", notes[0])
        self.assertEqual(notes[1], "Every cohort has the same one-hour lunch.")
        self.assertIn("9:00 AM drop-off and return at 5:00 PM", notes[2])
        self.assertEqual(got["rotation"]["departure"]["note"],
                         "The program day ends at 5:00 PM, when buses return to pick up students.")
        self.assertEqual(got["programHours"], "9:00 AM – 5:00 PM")

    def test_auto_intro(self):
        intro = self.load()["rotation"]["intro"]
        self.assertTrue(intro.startswith("Students will be divided into four cohorts of about 28–29 students. "))
        self.assertIn("a scheduled lunch", intro)
        self.assertIn("Glass-Bottom Boat Tour", intro)
        self.assertTrue(intro.endswith("where each cohort will be throughout the day."))

    def test_intro_override(self):
        self.assertEqual(self.load(schedule_intro="Custom {{cohort_count_word}}.")["rotation"]["intro"],
                         "Custom four.")

    def test_audiences_and_day_meta_carried_over(self):
        got = self.load()
        self.assertEqual(got["audiences"], self.json["audiences"])
        self.assertEqual(got["days"][0]["title"], "One Day on the Reef")
        self.assertEqual(got["days"][0]["studentsWill"], self.json["days"][0]["studentsWill"])

    def test_audience_views_match(self):
        """Cohort schedule + family schedule in the audience views are identical
        to the JSON-sourced ones (the grid is the source of truth for both)."""
        import audience_views as av
        a = self.load()["rotation"]
        n = self.json["rotation"]
        key = lambda r, lines: {c["cohort"] if isinstance(c, dict) and "cohort" in c else str(i): c  # noqa: E731
                                for i, c in enumerate(lines)}
        pd_a = {"rotation": a, "days": []}
        pd_n = {"rotation": n, "days": []}
        la, ln = av._cohort_lines(a), av._cohort_lines(n)
        norm = lambda ls: [[(i["time"], i["name"]) for i in c["items"]] if "items" in c else c for c in ls]  # noqa: E731
        self.assertEqual(norm(la), norm(ln))
        self.assertEqual(av._simple_schedule(pd_a, {}), av._simple_schedule(pd_n, {}))


class MigrationRegression(Base):
    """Spec section 5: render Ben Gamla before (fixture JSON, legacy path) and
    after (migrated JSON + Airtable rows) and diff the rotation grid, cohort
    list and audience views. Order differs on purpose (stations follow first
    appearance); content must not. The intended wording/format changes are
    asserted explicitly so any NEW difference fails the test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import generate_booking_package as g
        cls.g = g
        b0 = {k: "" for k in [
            "org_name", "contact_name", "contact_role", "contact_email", "contact_phone", "location",
            "booking_type", "status", "proposal_response", "payment_tier", "proposal_included",
            "proposal_not_included", "proposal_assumptions", "proposal_next_steps", "org_type",
            "proposal_optional", "asana_task_id", "approved_stage", "approved_by", "approved_date"]}
        b0.update(
            record_id=BEN_GAMLA, org_name="Ben Gamla Charter School", booking_type="Group Program - Expedition",
            arrival_date="2027-03-17", departure_date="2027-03-17", students=115, chaperones=12,
            free_chaperones=1, free_chap_threshold=9, free_chap_override=None, total_package_price=1000,
            price_per_paid_space=10, reef_contact={}, program_type={}, activity_topics=[], activity_names=[],
            status="Quoting", approved_to_share=False, approved_version=None, proposal_version=None,
            rotation_setting="Yes — rotating cohorts", cohort_count=4, deposit_due_now=0, payment2_amount=0,
            final_amount=0, reef_program_fees_total=0, reef_supplies_total=0, campus_facility_fee_total=0,
            pricing_model="", deposit_payment_status=None, agreement_contract_status=None,
            payment2_due_date=None, final_due_date=None, proposal_sent_date=None)
        g._ITINERARY_CACHE.clear()
        real_dir = g.ITINERARIES_DIR
        g.ITINERARIES_DIR = FIXTURE_DIR
        try:
            cls.pre = g.build_proposal_data(dict(b0))
            cls.pre_v = g.build_share_views(dict(b0), cls.pre, True, "u")
        finally:
            g.ITINERARIES_DIR = real_dir
            g._ITINERARY_CACHE.clear()
        b1 = dict(b0, **{k: v for k, v in booking().items() if k != "record_id"},
                  schedule_rows=build_rows(cls.json))
        cls.post = g.build_proposal_data(dict(b1))
        cls.post_v = g.build_share_views(dict(b1), cls.post, True, "u")
        g._ITINERARY_CACHE.clear()

    @staticmethod
    def grid(rot):
        name = {s["id"]: s["name"] for s in rot["stations"]}
        return sorted((a["cohort"], a["start"], a["end"], name[a["station"]]) for a in rot["assignments"])

    def test_grid_and_cohorts_identical(self):
        for pre, post in ((self.pre["proposal"], self.post["proposal"]),
                          (self.pre_v["educator"]["view"], self.post_v["educator"]["view"])):
            self.assertEqual(self.grid(pre["rotation"]), self.grid(post["rotation"]))
            self.assertEqual(pre["rotation"]["cohorts"], post["rotation"]["cohorts"])
            self.assertEqual((pre["rotation"]["startTime"], pre["rotation"]["endTime"]),
                             (post["rotation"]["startTime"], post["rotation"]["endTime"]))

    def test_activity_cards_and_family_student_experiences_same_set(self):
        card = lambda blocks: {(b["title"], b["when"] if "when" in b else None, b["description"])  # noqa: E731
                               for b in blocks}
        self.assertEqual(card(self.pre["proposal"]["days"][0]["blocks"]),
                         card(self.post["proposal"]["days"][0]["blocks"]))
        for v in ("family", "student"):
            exp = lambda d: {(e["title"], e["text"]) for e in d[v]["view"]["experiences"]}  # noqa: E731
            self.assertEqual(exp(self.pre_v), exp(self.post_v))

    def test_cohort_lines_same(self):
        for v in ("educator", "family"):
            a, b = self.pre_v[v]["view"], self.post_v[v]["view"]
            self.assertEqual(a.get("cohortSchedule") and sorted(map(json.dumps, a["cohortSchedule"])),
                             b.get("cohortSchedule") and sorted(map(json.dumps, b["cohortSchedule"])))

    def test_intended_differences_only(self):
        # Program Hours chip: spaced en dash now, matching Airtable's own field.
        self.assertEqual(self.pre["proposal"]["hours"], "9:00 AM–5:00 PM")
        self.assertEqual(self.post["proposal"]["hours"], "9:00 AM – 5:00 PM")
        # Lunch window is not a token, so the hard-coded "between 11:00 AM and 12:30 PM" is gone.
        self.assertNotIn("between 11:00", self.post_v["family"]["view"]["lunch"])
        # Day theme is generated from tokens (wording slightly different, same facts).
        self.assertEqual(self.post["proposal"]["days"][0]["theme"],
                         "Students rotate in four cohorts through five hands-on experiences led by "
                         "REEF educators, from 9:00 AM to 5:00 PM.")
        # No raw tokens anywhere in either page or any view.
        sa.assert_no_tokens(self.post)
        sa.assert_no_tokens(self.post_v)


class EditCases(Base):
    def edit(self, rows, station_label=None, cohort=None, **changes):
        out = copy.deepcopy(rows)
        for it in out["items"]:
            f = it["fields"]
            if cohort and f.get(sa.ITEM_FIELDS["cohort"]) != cohort:
                continue
            if station_label and (f.get(sa.ITEM_FIELDS["station"]) or [""])[0] != station_label:
                continue
            for k, v in changes.items():
                f[sa.ITEM_FIELDS[k]] = v
        return out

    def test_1_move_fish_id_start(self):
        rows = self.edit(self.rows(), "recSTNfishid", "A", start="08:30")
        got = self.load(rows)["rotation"]
        fish = next(s["id"] for s in got["stations"] if s["short"] == "Fish ID")
        a = next(x for x in got["assignments"] if x["cohort"] == "A" and x["station"] == fish)
        self.assertEqual(a["start"], "08:30")

    def test_1b_start_before_window_or_off_grid_still_caught_by_validator(self):
        import generate_booking_package as g
        rows = self.edit(self.rows(), "recSTNfishid", "A", start="09:10")
        with self.assertRaisesRegex(g.InvalidRotation, "grid"):
            g.validate_rotation(self.load(rows)["rotation"], BEN_GAMLA)

    def test_4_departure_moved(self):
        rows = copy.deepcopy(self.rows())
        dep = rows["items"][-1]["fields"]
        dep[sa.ITEM_FIELDS["start"]] = "16:00"
        got = self.load(rows, schedule_program_hours="9:00 AM – 4:00 PM")
        self.assertEqual(got["programHours"], "9:00 AM – 4:00 PM")
        self.assertIn("return at 4:00 PM", got["rotation"]["notes"][2])
        self.assertEqual(got["rotation"]["endTime"], "16:00")

    def test_5_overlap_caught(self):
        import generate_booking_package as g
        rows = self.edit(self.rows(), "recSTNlionfish", "A", start="09:30")
        with self.assertRaisesRegex(g.InvalidRotation, "overlap"):
            g.validate_rotation(self.load(rows)["rotation"], BEN_GAMLA)

    def test_gap_is_not_an_error(self):
        import generate_booking_package as g
        rows = self.edit(self.rows(), "recSTNlionfish", "A", start="10:30", end="11:00")
        g.validate_rotation(self.load(rows)["rotation"], BEN_GAMLA)

    def test_8_count_zero_uses_json_path(self):
        import generate_booking_package as g
        itin = g.load_itinerary("reciijikzFlFdq3Qr", {"schedule_count": 0})
        self.assertIn("days", itin)
        self.assertNotIn("scheduleSource", itin)
        legacy = g.load_itinerary("reciijikzFlFdq3Qr")
        self.assertEqual(itin, legacy)

    def test_9_durations_differing_by_cohort_range(self):
        rows = self.edit(self.rows(), "recSTNboat", "A", end="14:15")
        got = self.load(rows, schedule_notes="Boat: {{duration:Boat Tour}}")
        self.assertEqual(got["rotation"]["notes"], ["Boat: 2.25-2.5 hours"])

    def test_6_cohort_count_three(self):
        rows = self.rows()
        rows["items"] = [i for i in rows["items"] if i["fields"].get(sa.ITEM_FIELDS["cohort"]) != "D"]
        got = self.load(rows, cohort_count=3, schedule_notes="")
        self.assertEqual([c["id"] for c in got["rotation"]["cohorts"]], ["A", "B", "C"])
        self.assertIn("three cohorts", got["rotation"]["intro"])

    def test_6b_colors_repeat_after_six(self):
        rows = self.rows()
        extra = copy.deepcopy(rows["items"][1])
        extra["id"] = "recITEMx"
        st = dict(rows["stations"][0], id="recSTNseven", label="Seven", name="Seventh")
        rows["stations"].append(st)
        extra["fields"][sa.ITEM_FIELDS["station"]] = ["recSTNseven"]
        extra["fields"][sa.ITEM_FIELDS["name"]] = "Seventh"
        extra["fields"][sa.ITEM_FIELDS["cohort"]] = "A"
        extra["fields"][sa.ITEM_FIELDS["start"]] = "16:30"
        extra["fields"][sa.ITEM_FIELDS["end"]] = "17:00"
        rows["items"].append(extra)
        got = self.load(rows)
        self.assertEqual([s["color"] for s in got["rotation"]["stations"]], [0, 1, 2, 3, 4, 5, 0])

    def test_13_blank_end_for_arrival_departure_not_midnight(self):
        got = self.load()
        self.assertEqual(got["rotation"]["startTime"], "09:00")
        self.assertNotIn("00:00", [a["end"] for a in got["rotation"]["assignments"]])

    def test_swap_station_changes_all_cohorts(self):
        rows = copy.deepcopy(self.rows())
        stn = next(s for s in rows["stations"] if s["id"] == "recSTNfishid")
        stn["name"], stn["label"], stn["description"] = "Gyotaku Fish Printing", "Gyotaku", "Fish printing."
        for it in rows["items"]:
            if (it["fields"].get(sa.ITEM_FIELDS["station"]) or [""])[0] == "recSTNfishid":
                it["fields"][sa.ITEM_FIELDS["name"]] = "Gyotaku Fish Printing"
                it["fields"][sa.ITEM_FIELDS["description"]] = "Fish printing."
        got = self.load(rows, schedule_notes="")["rotation"]
        names = [s["name"] for s in got["stations"]]
        self.assertIn("Gyotaku Fish Printing", names)
        self.assertNotIn("Citizen Science & Fish Identification", names)

    def test_7_multiday_standard(self):
        def it(i, day, bt, start, end, name, desc="d"):
            f = {sa.ITEM_FIELDS["day"]: day, sa.ITEM_FIELDS["row_check"]: "OK",
                 sa.ITEM_FIELDS["block_type"]: bt, sa.ITEM_FIELDS["start"]: start,
                 sa.ITEM_FIELDS["name"]: name, sa.ITEM_FIELDS["description"]: desc}
            if end:
                f[sa.ITEM_FIELDS["end"]] = end
            return {"id": f"recM{i}", "fields": f}
        items = [it(1, 1, "Arrival", "09:00", None, "Arrival"),
                 it(2, 1, "Activity", "10:00", "11:00", "Fish ID", "Learn {{duration:Fish ID}}"),
                 it(3, 2, "Activity", "09:00", "10:30", "Reef Walk"),
                 it(4, 4, "Departure", "15:00", None, "Departure", "Leave {{departure_time}}")]
        items[1]["fields"][sa.ITEM_FIELDS["station"]] = ["recSTNa"]
        items[2]["fields"][sa.ITEM_FIELDS["station"]] = ["recSTNb"]
        stations = [
            {"id": "recSTNa", "label": "Fish ID", "name": "Fish ID", "description": "d", "location": "",
             "row_check": "OK", "catalog_id": None, "category": "Citizen Science"},
            {"id": "recSTNb", "label": "Reef Walk", "name": "Reef Walk", "description": "d", "location": "",
             "row_check": "OK", "catalog_id": None, "category": None}]
        b = booking(rotation_setting="No — full group together", cohort_count=None, schedule_count=4,
                    schedule_notes="", schedule_program_hours="")
        got = sa.schedule_from_rows(b, {"items": items, "stations": stations}, None, log=lambda *_: None)
        self.assertIsNone(got["rotation"])
        self.assertEqual(len(got["days"]), 4)
        self.assertEqual(got["days"][0]["blocks"][0]["time"], "9:00 AM")
        self.assertEqual(got["days"][0]["blocks"][1]["time"], "10:00–11:00 AM")
        self.assertEqual(got["days"][0]["blocks"][1]["description"], "Learn 1 hour")
        self.assertEqual(got["days"][3]["blocks"][0]["description"], "Leave 3:00 PM")
        self.assertEqual(got["days"][1]["title"], "Day 2")
        # first arrival -> LAST departure
        self.assertEqual(got["programHours"], "9:00 AM – 3:00 PM")


class Validation(Base):
    def expect(self, pattern, rows=None, **bk):
        with self.assertRaisesRegex(sa.ScheduleError, pattern):
            self.load(rows, **bk)

    def test_row_check_not_ok(self):
        rows = copy.deepcopy(self.rows())
        rows["items"][3]["fields"][sa.ITEM_FIELDS["row_check"]] = "Pick an end time"
        self.expect("Pick an end time", rows)

    def test_station_row_check_not_ok(self):
        rows = copy.deepcopy(self.rows())
        rows["stations"][0]["row_check"] = "Add a description (no catalog text available)"
        self.expect("Add a description", rows)

    def test_rotation_yes_with_one_cohort(self):
        rows = self.rows()
        rows["items"] = [i for i in rows["items"]
                         if i["fields"].get(sa.ITEM_FIELDS["cohort"]) in (None, "A")]
        self.expect("at least 2", rows, cohort_count=1)

    def test_cohort_count_mismatch(self):
        self.expect("'# Cohorts' is 5", None, cohort_count=5)

    def test_cohort_letter_outside_count(self):
        rows = copy.deepcopy(self.rows())
        for it in rows["items"]:
            if it["fields"].get(sa.ITEM_FIELDS["cohort"]) == "D":
                it["fields"][sa.ITEM_FIELDS["cohort"]] = "E"
        self.expect("outside the first 4", rows)

    def test_station_with_two_block_types(self):
        rows = copy.deepcopy(self.rows())
        for it in rows["items"]:
            f = it["fields"]
            if f.get(sa.ITEM_FIELDS["cohort"]) == "A" and (f.get(sa.ITEM_FIELDS["station"]) or [""])[0] == "recSTNfishid":
                f[sa.ITEM_FIELDS["block_type"]] = "Meal / Break"
        self.expect("different Block Types", rows)

    def test_unknown_token_in_description_fails_run(self):
        rows = copy.deepcopy(self.rows())
        rows["items"][1]["fields"][sa.ITEM_FIELDS["description"]] = "Starts at {{start_time}}"
        self.expect("Unknown schedule token", rows)

    def test_json_rotation_ignored_with_warning(self):
        logs = []
        sa.schedule_from_rows(booking(), self.rows(), self.json, log=logs.append)
        self.assertTrue(any("WARNING" in m and "ignored" in m for m in logs))

    def test_published_refused_when_changed_after_approval(self):
        import generate_booking_package as g
        b = {"approved_to_share": True, "approved_stage": "Proposal", "proposal_version": None,
             "approved_version": None, "approved_by": "Rose", "schedule_changed_after_approval": ""}
        self.assertEqual(g.check_share_approval(b, True), [])
        b["schedule_changed_after_approval"] = "2026-10-02"
        reasons = g.check_share_approval(b, True)
        self.assertEqual(len(reasons), 1)
        self.assertIn("schedule changed after approval", reasons[0])


if __name__ == "__main__":
    unittest.main()
