"""python -m unittest pipeline.test_no_schedule_failure

Defect 3 (scenario test 2026-11-02): a new booking with no Schedule Items failed with a message
that pointed to a JSON export. The wording was fixed in #34; this keeps the whole failure path
honest: no schedule is invented, nothing is published, and the message Rose reads in Airtable
tells her to add rows in the Itinerary Editor."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import generate_booking_package as g
from pipeline import publish_support as ps

NEW_ID = "recNoScheduleZZ01"


def zzz_fields():
    return {
        "Organization Name": "ZZZ TEST ORG - No Schedule Yet", "Primary Contact Name": "Test Person",
        "Contact Email": "test@example.org", "Arrival Date": "2027-05-10", "Departure Date": "2027-05-10",
        "Status": "Quoting", "# Student Participants": 20, "# Total Chaperones": 3,
        "Total Package Price": 1000, "Booking Type": "Group Program - Expedition",
        "Approved to Share": True, "Approved to Share — Stage": "Proposal", "Proposal Version": 1,
        "Approved for Proposal Version": 1, "Approved to Share By": {"name": "Martha"},
        "Schedule Items (count)": 0,
    }


class NoScheduleFailureTest(unittest.TestCase):
    def run_cli(self, bookings_dir):
        rf = Path(bookings_dir) / "result.json"
        with mock.patch.object(g, "airtable_get", lambda base, table, rec: {"id": rec, "fields": zzz_fields()}), \
                mock.patch.object(g, "airtable_list_by_ids", lambda *a, **k: {NEW_ID: {"id": NEW_ID, "fields": {}}}), \
                mock.patch.object(g, "RESULT_FILE", str(rf)), \
                mock.patch.object(g, "BOOKINGS_OUT_DIR", Path(bookings_dir) / "bookings"), \
                mock.patch.object(g, "CONTRACTS_OUT_DIR", Path(bookings_dir) / "contracts"), \
                mock.patch.object(g, "ASANA_API_KEY", None), \
                mock.patch.object(sys, "argv", ["generate_booking_package.py", NEW_ID]):
            with self.assertRaises(g.NoItineraryCaptured):
                g.cli()
        return rf

    def test_failure_names_the_editor_not_a_json_export_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            rf = self.run_cli(d)
            result = json.loads(rf.read_text())
            self.assertEqual(result["status"], "failed")
            self.assertIn("Add schedule rows in the Itinerary Editor first.", result["message"])
            self.assertIn("does not fabricate", result["message"])
            self.assertNotIn("JSON", result["message"])
            self.assertFalse((Path(d) / "bookings").exists() and any((Path(d) / "bookings").iterdir()),
                             "nothing may be written under bookings/")
            self.assertFalse((Path(d) / "contracts").exists() and any((Path(d) / "contracts").iterdir()))

    def test_airtable_write_back_says_failed_previous_version_still_live(self):
        with tempfile.TemporaryDirectory() as d:
            result = json.loads(self.run_cli(d).read_text())
        fields = ps.writeback_fields(result, False, "https://github.test/run/1")
        self.assertEqual(fields[ps.F_PUBLISH_RESULT], ps.RESULT_FAILED)
        self.assertIn("Itinerary Editor", fields[ps.F_PUBLISH_MESSAGE])
        self.assertNotIn(ps.F_PUBLISHED_VERSION, fields)   # the published version keeps pointing at what is live
        self.assertFalse(fields[ps.F_PUBLISH_REQUESTED])

    def test_a_booking_with_a_captured_itinerary_file_is_not_affected(self):
        # legacy bookings (captured JSON) still load through the JSON path
        self.assertTrue(g.load_itinerary("recnD4Ohnn3oeu7h3")["days"])


if __name__ == "__main__":
    unittest.main()
