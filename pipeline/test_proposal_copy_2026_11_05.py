"""python -m unittest pipeline.test_proposal_copy_2026_11_05

Martha's 2026-11-05 copy changes: the standard REEF contact note, the contact
extension, the seine-netting build guard, one "What students will do at each stop"
heading, and the Benjamin School 2-day rotation."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generate_booking_package as g  # noqa: E402
import publish_support as ps  # noqa: E402

REPO = Path(__file__).parent.parent
BENJAMIN = "recXmG8ySdXrgmj85"


class ContactTest(unittest.TestCase):
    def test_extension_is_appended(self):
        self.assertEqual(g.contact_phone("305-852-0030", "1005"), "305-852-0030 ext. 1005")

    def test_blank_extension_fails_soft(self):
        for blank in ("", None, "  ", "n/a"):
            self.assertEqual(g.contact_phone("305-852-0030", blank), "305-852-0030")

    def test_no_phone_never_prints_a_dangling_ext(self):
        self.assertEqual(g.contact_phone("", "1005"), "")

    def test_default_extension_is_1005(self):
        self.assertEqual(g.REEF_CONTACT_EXTENSION_DEFAULT, "1005")

    def test_note_text_is_exact(self):
        self.assertEqual(g.REEF_CONTACT_NOTE, (
            "Hi! We are so excited to welcome you all to REEF, this personalized website is a place for you "
            "to understand what comes with your REEF Booking! Feel free to call with any questions or changes "
            "and I would be happy to walk you through it."))


class SeineGuardTest(unittest.TestCase):
    def test_guard_fails_on_seine_in_any_case(self):
        for text in ("Seine netting", "we go SEINING", "a seine net", {"optional": ["seine netting for fish ID"]}):
            with self.assertRaises(ps.ForbiddenCopy):
                ps.assert_no_forbidden_copy(text, "test page")

    def test_guard_passes_clean_copy(self):
        ps.assert_no_forbidden_copy({"a": ["Snorkel Trip", "Seine River"[:0] + "Kayak"]}, "test page")

    def test_build_validation_fails_a_seeded_build(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "index.html").write_text("<html></html>")
            (d / "data.js").write_text('window.BOOKING_DATA = {"docType":"proposal","proposal":{"optional":["Seine netting"]}};')
            problems = ps.validate_build(d, True)
            self.assertTrue(any("seine" in p.lower() for p in problems), problems)


class BenjaminItineraryTest(unittest.TestCase):
    """Airtable Schedule Items are Benjamin's only schedule source (2026-11-06);
    the JSON holds the summary, day titles and audiences."""

    def setUp(self):
        self.raw = json.loads((REPO / "pipeline" / "itineraries" / f"{BENJAMIN}.json").read_text())

    def test_no_schedule_left_in_the_json(self):
        self.assertNotIn("rotation", self.raw)
        self.assertTrue(all("blocks" not in d for d in self.raw["days"]))

    def test_summary_names_the_three_locations_and_night_activity(self):
        s = self.raw["summary"]
        for word in ("Ocean Exploration Center", "MOTE", "Pennekamp", "night activity", "three cohorts"):
            self.assertIn(word, s)
        self.assertNotIn("all at Pennekamp", s)

    def test_day_titles_match_the_new_schedule(self):
        self.assertEqual([d["title"] for d in self.raw["days"]], ["Welcome to the Reef", "Reef, Mangroves & Lionfish"])

    def test_no_stale_wording_anywhere_in_the_file(self):
        blob = json.dumps(self.raw)
        self.assertNotRegex(blob, r"(?i)middle school|seine|9:00|\$\d|bus moves|bus times")

    def test_audiences_say_the_school_arranges_meals_and_transport(self):
        lg = self.raw["audiences"]["logistics"]
        self.assertIn("school arranges", lg["meals"].lower())
        self.assertIn("school arranges", lg["transportation"].lower())


class HoursCountAndLegendTest(unittest.TestCase):
    def item(self, day, bt, start, end=None, name="x"):
        return {"day": day, "block_type": bt, "start": start, "end": end or "", "name": name}

    def test_per_day_hours_include_night_activity_and_skip_meals(self):
        import schedule_airtable as sa
        items = [self.item(1, "Activity", "10:30", "12:00"), self.item(1, "Meal / Break", "07:00", "08:00"),
                 self.item(1, "Whole-Group Block", "20:00", "21:00"),
                 self.item(2, "Meal / Break", "07:00", "08:00"), self.item(2, "Activity", "08:30", "10:30"),
                 self.item(2, "Departure", "18:15")]
        self.assertEqual(sa.per_day_program_hours(items), "Day 1: 10:30 AM – 9:00 PM; Day 2: 8:30 AM – 6:15 PM")

    def test_only_real_activities_are_counted(self):
        import schedule_airtable as sa
        yes = [("Activity", "Mangrove Kayak Tour"), ("Activity", "Lionfish Lesson & Dissection"),
               ("Whole-Group Block", "Night Activity: Human Impact Skits")]
        no = [("Activity", "Beach Time & Snorkel Check-In"), ("Activity", "Showers & Field Time"),
              ("Meal / Break", "Lunch at REEF"), ("Whole-Group Block", "Beach Time & Rinse-Off")]
        for bt, name in yes:
            self.assertTrue(sa.counts_as_activity(bt, name), name)
        for bt, name in no:
            self.assertFalse(sa.counts_as_activity(bt, name), name)

    def test_location_legend_colours_stations_by_location(self):
        import schedule_airtable as sa
        groups = [{"name": "Pennekamp Coral Reef State Park", "color": 5, "match": ["Pennekamp"]},
                  {"name": "MOTE Coral Nursery", "color": 3, "match": ["MOTE"]}]
        self.assertEqual(sa._location_group("Pennekamp mangrove trails", groups)["color"], 5)
        self.assertEqual(sa._location_group("MOTE Coral Nursery", groups)["color"], 3)
        self.assertIsNone(sa._location_group("Somewhere else", groups))

    def test_benjamin_json_has_the_four_legend_locations_with_addresses(self):
        raw = json.loads((REPO / "pipeline" / "itineraries" / f"{BENJAMIN}.json").read_text())
        locs = {l["name"]: l["address"] for l in raw["locations"]}
        self.assertEqual(locs["REEF Ocean Exploration Center"], "98380 Overseas Hwy, Key Largo, FL 33037")
        self.assertEqual(locs["Pennekamp Coral Reef State Park"], "102601 Overseas Hwy, Key Largo, FL 33037")
        self.assertEqual(locs["MOTE Coral Nursery"], "103800 Overseas Hwy, Key Largo, FL 33037")


class SchoolFacingTest(unittest.TestCase):
    def hits(self, payload, names=("Rose Kelly",)):
        return ps.internal_wording_hits(payload, names)

    def test_flags_each_internal_word(self):
        for w in ("Draft Program Schedule", "Outstanding decisions", "TBD", "Times to be confirmed",
                  "Date to be determined", "Approval pending", "Schedule being finalized",
                  "Martha will send it", "Waiting on Rose", "Under review by staff"):
            self.assertTrue(self.hits({"x": w.replace("Waiting on Rose", "Waiting on Rose")}, names=()), w)

    def test_next_steps_review_sentence_is_allowed(self):
        self.assertEqual(self.hits(["Review each section of this proposal with your team, including the schedule"]), [])

    def test_educational_review_is_not_flagged(self):
        self.assertEqual(self.hits(["Level 2 Fish ID Review & Exam", "Students review fish identification"]), [])

    def test_booking_contact_may_be_named_but_other_staff_may_not(self):
        self.assertEqual(self.hits(["Rose Kelly", "Rose prepares your contract", "rose@REEF.org"]), [])
        self.assertTrue(self.hits(["Martha will send it"]))
        self.assertTrue(self.hits(["Rose prepares your contract"], names=("Pat Lee",)))

    def test_json_keys_are_not_scanned(self):
        self.assertEqual(self.hits({"scheduleDraft": False, "pendingNote": ""}), [])

    def test_guard_raises(self):
        with self.assertRaises(ps.InternalWording):
            ps.assert_school_facing_clean({"a": "Draft Program Schedule"}, "booking page")

    def test_validate_build_fails_a_published_page_with_draft_wording(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "index.html").write_text("<html></html>")
            (d / "data.js").write_text('window.BOOKING_DATA = {"docType":"proposal","proposal":{"x":"Draft Program Schedule"}};')
            self.assertTrue(any("internal wording" in p for p in ps.validate_build(d, True, ["Rose Kelly"])))

    def test_school_facing_share_status_never_says_draft(self):
        import audience_views as av
        self.assertEqual(av.share_status("Quoting", None), ("draft", "Draft"))
        self.assertEqual(av.share_status("Quoting", None, school_facing=True), ("proposal", "Proposal"))

    def test_renderer_only_prints_draft_wording_behind_the_flag(self):
        js = (REPO / "assets" / "render.js").read_text()
        self.assertNotIn('statusLabel || "Draft"', js)
        self.assertIn("V.scheduleDraft ? \"Proposed program · Draft schedule", js)


class RenderOnceTest(unittest.TestCase):
    def test_stops_heading_is_written_once_in_each_renderer(self):
        js = (REPO / "assets" / "render.js").read_text()
        self.assertEqual(js.count('"What students will do at each stop"'), 1)
        self.assertEqual(js.count('"What happens at each stop"'), 1)
        self.assertNotIn('el("span", { class: "eyebrow" }, ["WELCOME"])', js)
        self.assertEqual(js.count("A note from your REEF Contact"), 1)


if __name__ == "__main__":
    unittest.main()
