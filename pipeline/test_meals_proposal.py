"""python -m unittest pipeline.test_meals_proposal   (run from the repo root)

2027 meals on the proposal page: customer-facing fields only, nothing for bookings
without meals, and no internal meal / lodging field can be requested from Airtable."""
import re
import unittest
from pathlib import Path

from pipeline import generate_booking_package as g

SRC = Path(g.__file__).read_text()

INTERNAL_FIELD_IDS = {
    "fldyG2j53bTHydu9c": "Meals - Est. Vendor Cost",
    "fldjnRfqLzo8dz7eG": "Meals - Margin $",
    "fldvZeOcYz1Xplauw": "Combined Margin $ incl. Meals",
    "fld5DDgBNdMABfxFI": "Meals - Count Needing Review",
    "fldVZp8BvBoTNzJ0v": "Meals - Next Order Deadline",
    "fldRg3ccjUTaFCtpc": "Meals - Count (not cancelled)",
    "fldxtw6lqJut4PeP6": "Meals - Open Items",
    "fld5CvdfXfeXlZkJv": "Lodging Access Code",
    "fldjnrqH2QKI6Xpws": "Lodging Info Released On",
    "fldDtxpFOmmZ8sS5f": "Lodging Booked Using REEF Code",
    "fld7rVPsiiZbkRWfG": "Lodging Recommendations Requested",
}


class FieldRequestTest(unittest.TestCase):
    def test_only_the_two_customer_facing_fields_are_requested(self):
        self.assertEqual(set(g.MEALS_CUSTOMER_FIELD_IDS),
                         {"fldRbZteXnW5l4v4X", "fldihGwsEvNsqIRaU"})

    def test_no_internal_meal_or_lodging_field_id_appears_in_the_generator(self):
        for fid, name in INTERNAL_FIELD_IDS.items():
            self.assertNotIn(fid, SRC, f"{name} ({fid}) must never be read by the public-page generator")

    def test_fetch_uses_field_ids_and_only_those_fields(self):
        calls = []

        def fake(base, table, ids, field_ids):
            calls.append(list(field_ids))
            return {ids[0]: {"fields": {"fldRbZteXnW5l4v4X": "  Optional lunch.  ", "fldihGwsEvNsqIRaU": 9100.5}}}
        real, g.airtable_list_by_ids = g.airtable_list_by_ids, fake
        try:
            out = g.fetch_meals_proposal_fields("recAAAAAAAAAAAAAA")
        finally:
            g.airtable_list_by_ids = real
        self.assertEqual(calls, [["fldRbZteXnW5l4v4X", "fldihGwsEvNsqIRaU"]])
        self.assertEqual(out, {"meals_proposal_text": "Optional lunch.", "meals_total_payable": 9100.5})

    def test_missing_fields_mean_no_meals(self):
        real, g.airtable_list_by_ids = g.airtable_list_by_ids, lambda *a: {a[2][0]: {"fields": {}}}
        try:
            out = g.fetch_meals_proposal_fields("recAAAAAAAAAAAAAA")
        finally:
            g.airtable_list_by_ids = real
        self.assertEqual(out, {"meals_proposal_text": "", "meals_total_payable": None})


class PricingBlockTest(unittest.TestCase):
    def test_no_meals_adds_nothing(self):
        for b in ({}, {"meals_proposal_text": ""}, {"meals_proposal_text": "  \n ", "meals_total_payable": 500}):
            self.assertEqual(g.meals_pricing_block(b), {})

    def test_meals_block(self):
        blk = g.meals_pricing_block({"meals_proposal_text": "Optional lunch.", "meals_total_payable": 12345.5})["mealsOutside"]
        self.assertEqual(blk["text"], "Optional lunch.")
        self.assertEqual(blk["totalPayable"], g.money(12345.5))
        self.assertIn("including selected meals", blk["totalPayableLabel"])

    def test_total_line_omitted_when_total_missing(self):
        blk = g.meals_pricing_block({"meals_proposal_text": "Optional lunch."})["mealsOutside"]
        self.assertNotIn("totalPayable", blk)

    def test_total_package_price_untouched(self):
        # the helper never reads or returns the package price, deposit or guarantee
        blk = g.meals_pricing_block({"meals_proposal_text": "x", "meals_total_payable": 1,
                                     "total_package_price": 99999, "deposit_due_now": 5})
        self.assertNotIn("99999", str(blk))
        self.assertEqual(set(blk), {"mealsOutside"})


if __name__ == "__main__":
    unittest.main()
