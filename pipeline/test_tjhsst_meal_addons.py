"""python -m unittest pipeline.test_tjhsst_meal_addons

Optional meal add-ons (Martha, 2026-11-10; 2027 Meals & Lodging Guidelines): REEF offers optional
meals only during program hours. A lunch is "optional add-on" when scheduled program runs right
before or after it; a dinner only when an evening program follows. Everything else is "on your own".
The add-on note is copy only: it never changes the estimated total."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generate_booking_package as g  # noqa: E402
import publish_support as ps  # noqa: E402

ITIN = Path(__file__).parent / "itineraries"
FOUR, THREE = "rechXL7mCZJTGNofS", "recWsjgw9VBY53vA4"


def load(rid):
    return json.loads((ITIN / f"{rid}.json").read_text())["days"]


def meals(days):
    """(day, kind, block, eligible-by-rule) for every lunch/dinner block."""
    for d in days:
        bl = d["blocks"]
        for i, b in enumerate(bl):
            kind = "Lunch" if b["title"].startswith("Lunch") else "Dinner" if b["title"].startswith("Dinner") else None
            if not kind:
                continue
            before = i > 0 and bl[i - 1]["tag"] != "Break"
            after = i + 1 < len(bl) and bl[i + 1]["tag"] not in ("Break", "Departure")
            yield d["dayNumber"], kind, b, (before or after) if kind == "Lunch" else after


class MealAddOnTest(unittest.TestCase):
    def test_titles_follow_the_rule(self):
        for rid in (FOUR, THREE):
            for day, kind, b, eligible in meals(load(rid)):
                want = f"{kind} (optional add-on)" if eligible else f"{kind} (on your own)"
                self.assertEqual(b["title"], want, f"{rid} day {day}")
                if eligible:
                    rate = g.MEAL_ADDON_RATES[kind]
                    self.assertIn(f"REEF can coordinate this meal for your group at ${rate} per person", b["description"])
                    self.assertIn("Not included in your estimated total.", b["description"])
                else:
                    self.assertIn("not included", b["description"].lower())

    def test_expected_meal_by_meal_result(self):
        got = {rid: {(d, k): "optional add-on" in b["title"] for d, k, b, _ in meals(load(rid))} for rid in (FOUR, THREE)}
        self.assertEqual({k for k, v in got[FOUR].items() if v}, {(2, "Lunch"), (3, "Lunch")})
        self.assertEqual({k for k, v in got[THREE].items() if v}, {(1, "Lunch"), (2, "Lunch"), (3, "Lunch")})
        for rid in got:   # every dinner is on your own, and the 4-day's Day 4 has no meal block
            self.assertFalse(any(v for (d, k), v in got[rid].items() if k == "Dinner"))
        self.assertNotIn((4, "Lunch"), got[FOUR])

    def test_rates_match_the_airtable_optional_line(self):
        self.assertEqual(g.MEAL_ADDON_RATES, {"Lunch": 10, "Dinner": 12})

    def test_note_is_example_only_and_not_in_the_total(self):
        note = g.meal_add_on_note(load(FOUR), 18, 2)
        text = " ".join(note["lines"])
        self.assertEqual(note["heading"], "Meal add-on")
        self.assertIn("$10 per person", text)
        self.assertIn("Example only", text)
        self.assertIn("one lunch for a group of 20 (18 students and 2 chaperones) is about $200", text)
        self.assertIn("not included in your estimated total", text)
        self.assertNotRegex(text, r"\$1[12],\d{3}")
        self.assertEqual(ps.internal_wording_hits({"x": note}, ("Rose Kelly",)), [])

    def test_no_note_without_optional_meals(self):
        days = [{"blocks": [{"title": "Lunch (on your own)"}, {"title": "Dinner (on your own)"}]}]
        self.assertIsNone(g.meal_add_on_note(days, 18, 2))

    def test_estimated_total_is_unchanged(self):
        class B(dict):
            def __missing__(self, k):
                return ""
        for rid, total in ((FOUR, "$11,562.60"), (THREE, "$11,184.60")):
            b = B(record_id=rid, students=18, chaperones=2, free_chaperones=2, billable_chaperones=0,
                  free_chap_threshold=10, free_chap_override=None, pricing_model="Expedition",
                  booking_type="Expedition", total_package_price=float(total.strip("$").replace(",", "")),
                  price_per_paid_space=600.0, status="Quoting", org_name="TJHSST", reef_contact={},
                  proposal_included="a", proposal_not_included="b", proposal_optional="c",
                  proposal_assumptions="", proposal_next_steps="", activity_topics=[])
            pricing = g.build_proposal_data(b)["proposal"]["pricing"]
            self.assertEqual(pricing["estimatedTotal"], total)
            self.assertEqual(pricing["tileTotal"]["num"], total)
            self.assertIn(total, pricing["estimatedTotalNote"])
            self.assertIn("mealAddOn", pricing)
            payload = {"days": g.build_proposal_data(b)["proposal"]["days"], "p": pricing}
            self.assertEqual(ps.internal_wording_hits(payload, ("Rose Kelly",)), [])


if __name__ == "__main__":
    unittest.main()
