"""python -m unittest pipeline.test_estimate_guard

Estimate-stage privacy guard (Step 3). ZZZ test data only; no network."""
import copy
import unittest

from pipeline import estimate_view as ev

DAYS = [{"dayNumber": 1, "totalDays": 1, "title": "Day", "theme": "Theme",
         "blocks": [{"time": "Morning", "tag": "Boat", "title": "Boat snorkel", "description": "Half-day."}]}]


def booking(**kw):
    b = dict(record_id="recZZZSAMPLE000001", org_name="ZZZ TEST ORG -- Estimate Sample", students=26,
             chaperones=2, free_chaperones=2, billable_chaperones=0, total_package_price=9975,
             free_chap_threshold=10, activity_narrative_status=None)
    b.update(kw)
    return b


def clean():
    return ev.build_estimate_data(booking(), DAYS, is_sample=True)


class GuardTest(unittest.TestCase):
    def test_clean_payload_passes_and_numbers_match(self):
        d = clean()
        self.assertEqual((d["estimate"]["lowLabel"], d["estimate"]["highLabel"]), ("$9,975", "$11,000"))
        self.assertEqual((d["estimate"]["perPaidStudentLowLabel"], d["estimate"]["perPaidStudentHighLabel"]),
                         ("$383.65", "$423.08"))
        self.assertIs(ev.assert_estimate_safe(d), d)

    def fails(self, mutate, expect):
        d = clean()
        mutate(d)
        with self.assertRaises(ev.EstimatePrivacyError) as cm:
            ev.assert_estimate_safe(d)
        self.assertIn(expect, str(cm.exception))

    def test_injected_margin_field_fails(self):
        self.fails(lambda d: d["estimate"].update({"margin": 0.468}), "margin")

    def test_unlisted_field_fails_even_with_innocent_name(self):
        self.fails(lambda d: d.update({"notes": "x"}), "allowlist")

    def test_nested_unlisted_field_fails(self):
        self.fails(lambda d: d["itinerary"]["days"][0]["blocks"][0].update({"cost": 1}), "allowlist")

    def test_internal_terms_in_text_fail(self):
        for term in ("Net Income", "Margin Summary", "staff labor", "campus cost", "5% uplift", "vendor cost"):
            with self.subTest(term=term):
                self.fails(lambda d, t=term: d["estimate"]["changes"].append(f"x {t} y"), "text mentions")

    def test_bare_five_percent_fails_but_other_percentages_pass(self):
        self.fails(lambda d: d["estimate"]["changes"].append("adds 5% to the total"), "text mentions")
        d = clean()
        d["estimate"]["changes"].append("Paying by card adds 3%; some fees rise 15%")
        ev.assert_estimate_safe(d)

    def test_dollar_amount_in_itinerary_fails(self):
        self.fails(lambda d: d["itinerary"]["days"][0]["blocks"][0].update({"description": "Boat $900"}),
                   "$ amount")

    def test_school_email_fails_reef_email_passes(self):
        self.fails(lambda d: d["itinerary"].update({"note": "write teacher@school.org"}), "non-REEF email")
        d = clean()
        d["itinerary"]["note"] = "write explorers@REEF.org"
        ev.assert_estimate_safe(d)

    def test_builder_itself_refuses_a_leaky_config(self):
        cfg = copy.deepcopy(ev.load_defaults())
        cfg["whatWouldChangeYourTotal"].append("Our margin on this trip")
        with self.assertRaises(ev.EstimatePrivacyError):
            ev.build_estimate_data(booking(), DAYS, defaults=cfg, is_sample=True)

    def test_shipped_config_is_clean(self):
        ev.build_estimate_data(booking(), DAYS, is_sample=True)


class RangeTest(unittest.TestCase):
    def test_range_math(self):
        from decimal import Decimal as D
        self.assertEqual(ev.estimate_range(9975, "1.10", 50), (D(9975), D(11000)))
        self.assertEqual(ev.estimate_range(10000, "1.10", 50)[1], D(11000))
        self.assertEqual(ev.estimate_range(10001, "1.10", 50)[1], D(11050))


if __name__ == "__main__":
    unittest.main()
