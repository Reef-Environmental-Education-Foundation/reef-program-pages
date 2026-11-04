"""python -m unittest pipeline.test_summary_guard"""
import json
import unittest
from pathlib import Path

from pipeline import generate_booking_package as g

ITINERARIES = Path(g.__file__).parent / "itineraries"


class SummaryGuardTest(unittest.TestCase):
    def test_stale_count_is_detected(self):
        self.assertTrue(g.summary_count_is_stale("A one-day program for 115 students, in four cohorts.", 66))

    def test_current_count_is_kept(self):
        self.assertFalse(g.summary_count_is_stale("A one-day program for 66 students, in four cohorts.", 66))
        self.assertFalse(g.summary_count_is_stale("A program for 1,200 students.", 1200))

    def test_summary_without_a_count_is_kept(self):
        self.assertFalse(g.summary_count_is_stale("A day of marine science in Key Largo.", 66))
        self.assertFalse(g.summary_count_is_stale(None, 66))

    def test_ben_gamla_json_summary_is_stale_at_66(self):
        # the captured file still says 115; the generator must not publish it at 66
        summary = json.loads((ITINERARIES / "recqb6DGaeJRpymL2.json").read_text()).get("summary")
        if summary and "115 students" in summary:
            self.assertTrue(g.summary_count_is_stale(summary, 66))


if __name__ == "__main__":
    unittest.main()
