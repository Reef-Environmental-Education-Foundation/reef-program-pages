"""python -m unittest pipeline.test_chaperone_policy

Free-chaperone copy must come from Airtable's "# Free Chaperones" /
"# Billable Chaperones" (rule: MIN(chaperones, FLOOR((students + chaperones) / 10)),
i.e. one complimentary chaperone per 9 paid participants), never total people / 9."""
import re
import unittest

from pipeline import generate_booking_package as g


def booking(students, chaperones, free, billable):
    return {"students": students, "chaperones": chaperones, "free_chaperones": free,
            "billable_chaperones": billable, "free_chap_threshold": 10,
            "free_chap_override": None, "pricing_model": "Expedition"}


def airtable_free(students, chaperones):
    return min(chaperones, (students + chaperones) // 10)


class ChaperonePolicyTest(unittest.TestCase):
    CASES = [  # students, chaperones, free, billable
        (66, 10, 7, 3),    # Ben Gamla
        (35, 8, 4, 4),     # Palmetto Bay
        (90, 14, 10, 4),   # The Benjamin School
    ]

    def test_cases_match_airtable_rule(self):
        for s, c, free, billable in self.CASES:
            self.assertEqual(airtable_free(s, c), free)
            self.assertEqual(c - free, billable)

    def test_copy_uses_airtable_counts(self):
        for s, c, free, billable in self.CASES:
            headline, lines = g.chaperone_policy(booking(s, c, free, billable))
            text = " ".join([headline] + lines)
            self.assertEqual(headline, f"{free} of your {c} chaperones are complimentary.")
            self.assertIn(f"includes {free} complimentary chaperone space", text)
            self.assertIn("every 9 paid participants", text)
            # never the old total_people / 9 count, and never the old wording
            self.assertNotIn("earns", text)
            self.assertNotIn("people in your group", text)
            self.assertNotRegex(text, r"per-10|per 10")
            if billable:
                self.assertIn(f"The other {billable} chaperone", text)

    def test_ben_gamla_is_not_eight(self):
        headline, lines = g.chaperone_policy(booking(66, 10, 7, 3))
        self.assertNotIn("8 complimentary", " ".join([headline] + lines))

    def test_all_free_group(self):
        headline, lines = g.chaperone_policy(booking(18, 2, 2, 0))
        self.assertEqual(headline, "All 2 chaperones are complimentary.")

    def test_missing_billable_falls_back_to_chaperones_minus_free(self):
        _, lines = g.chaperone_policy(booking(66, 10, 7, None))
        self.assertIn("The other 3 chaperones", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
