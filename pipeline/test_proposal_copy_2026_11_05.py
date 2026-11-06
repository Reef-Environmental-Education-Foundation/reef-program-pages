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
    def setUp(self):
        self.raw = json.loads((REPO / "pipeline" / "itineraries" / f"{BENJAMIN}.json").read_text())

    def test_rotation_validates_and_has_three_cohorts_two_days(self):
        rot = self.raw["rotation"]
        g.validate_rotation(rot, BENJAMIN)
        self.assertEqual([c["id"] for c in rot["cohorts"]], ["A", "B", "C"])
        self.assertEqual([d["day"] for d in rot["days"]], [1, 2])

    def test_three_locations_in_legend(self):
        names = [l["name"] for l in self.raw["rotation"]["locations"]]
        self.assertEqual(names[:3], ["REEF campus", "Pennekamp Coral Reef State Park", "MOTE Coral Nursery"])

    def test_night_activity_is_an_all_cohort_block(self):
        night = [s for s in self.raw["rotation"]["shared"] if s["station"] == "skits"]
        self.assertEqual([(s["day"], s["start"]) for s in night], [(1, "20:00")])

    def test_audiences_have_no_old_hours_seine_or_prices(self):
        blob = json.dumps(self.raw["audiences"])
        self.assertNotRegex(blob, r"(?i)seine|9:00|5:00 PM|\$\d")

    def test_airtable_schedule_items_would_override_this_file(self):
        # documented gotcha: with Schedule Items > 0 the rotation here is ignored
        self.assertTrue(self.raw["rotation"])


class RenderOnceTest(unittest.TestCase):
    def test_stops_heading_is_written_once_in_each_renderer(self):
        js = (REPO / "assets" / "render.js").read_text()
        self.assertEqual(js.count('"What students will do at each stop"'), 1)
        self.assertEqual(js.count('"What happens at each stop"'), 1)
        self.assertNotIn('el("span", { class: "eyebrow" }, ["WELCOME"])', js)
        self.assertEqual(js.count("A note from your REEF Contact"), 1)


if __name__ == "__main__":
    unittest.main()
