"""python -m unittest pipeline.test_payment_wording"""
import unittest

from pipeline import generate_booking_package as g
import audience_views as av

BEN_GAMLA, HANOVER_2, HANOVER_4 = "recqb6DGaeJRpymL2", "recP88dd2wk5XdHU3", "reciijikzFlFdq3Qr"


def booking(**kw):
    b = {"record_id": "recR4mF8LDuuLSadt", "min_guaranteed_spaces": 63, "agreement_date": None,
         "deposit_amount_agreement": 5391.12, "deposit_due_agreement": "2026-11-16",
         "payment2_amount_agreement": 8086.68, "payment2_due_agreement": "2026-11-16",
         "final_due_date": "2027-02-09", "guaranteed_cost_agreement": 22642.7,
         "deposit_due_now": 1000, "payment2_amount": 12977.80, "payment2_due_date": "2026-12-01",
         "final_amount": 12977.80, "payment_tier": "C", "total_package_price": 26955.60}
    b.update(kw)
    return b


class AgreementTermsTest(unittest.TestCase):
    def test_applies_when_min_guaranteed_or_agreement_date_is_set(self):
        self.assertTrue(g.agreement_payment_terms(booking())["provisional"])
        self.assertFalse(g.agreement_payment_terms(
            booking(min_guaranteed_spaces=None, agreement_date="2026-11-02"))["provisional"])

    def test_not_applied_without_either_field_or_without_a_deposit(self):
        self.assertIsNone(g.agreement_payment_terms(booking(min_guaranteed_spaces=None)))
        self.assertIsNone(g.agreement_payment_terms(booking(deposit_amount_agreement=None)))

    def test_the_pin_list_is_exactly_ben_gamla_and_both_hanover_bookings(self):
        # Martha, 2026-11-02: these three stay on the old wording even though Minimum
        # Guaranteed Paid Spaces is set on them. Changing this list needs her decision.
        self.assertEqual(g.LEGACY_PAYMENT_WORDING_IDS, {BEN_GAMLA, HANOVER_2, HANOVER_4})

    def test_ben_gamla_and_hanover_stay_on_the_old_wording(self):
        for rec in (BEN_GAMLA, HANOVER_2, HANOVER_4):
            self.assertIsNone(g.agreement_payment_terms(booking(record_id=rec)), rec)


class WordingTest(unittest.TestCase):
    defaults = av.load_defaults()

    def lines(self, **kw):
        b = booking(**kw)
        b["agreement_payment"] = g.agreement_payment_terms(b)
        b["payment2_due_pretty"] = "Dec 1, 2026"
        b["final_due_pretty"] = "Feb 9, 2027"
        return " | ".join(av._payment_lines(b, self.defaults, g.money))

    def test_administrator_view_uses_agreement_terms(self):
        text = self.lines()
        self.assertIn("$5,391.12 deposit", text)
        self.assertIn("$8,086.68", text)
        self.assertNotIn("$12,977.80", text)
        self.assertIn("provisional until the agreement date", text)
        self.assertEqual(text.count("The final payment is due"), 1)

    def test_legacy_booking_keeps_the_old_lines(self):
        text = self.lines(record_id=BEN_GAMLA)
        self.assertIn("$1,000.00 deposit", text)
        self.assertIn("Payment 2 of $12,977.80", text)

    def test_confirmed_page_payment_schedule(self):
        new = g.build_payment_schedule(booking())
        self.assertEqual([i["amount"] for i in new["items"]], ["$5,391.12", "$8,086.68", None])
        self.assertEqual(new["items"][0]["dueDate"], "Nov 16, 2026")
        old = g.build_payment_schedule(booking(record_id=BEN_GAMLA))
        self.assertEqual(old["items"][0]["label"], "Deposit (due now)")
        self.assertEqual(old["items"][1]["amount"], "$12,977.80")


class ContractLinesTest(unittest.TestCase):
    """Option B (Martha, 2026-11-02): the contract uses the Agreement terms; the final
    payment is the balance of the total; no guarantee wording."""

    def test_zzz_scenario_booking(self):
        dep, p2, final = g.contract_payment_lines(booking())
        self.assertEqual(dep, "$5,391.12 to secure group space")
        self.assertEqual(p2, "$8,086.68 by Nov 16, 2026 (Payment 2)")
        self.assertEqual(final, "$13,477.80 by Feb 9, 2027 (Final Payment)")
        for line in (dep, p2, final):
            self.assertNotIn("guarantee", line.lower())

    def test_pinned_bookings_keep_the_old_fields(self):
        for rec in (BEN_GAMLA, HANOVER_2, HANOVER_4):
            dep, p2, final = g.contract_payment_lines(booking(record_id=rec))
            self.assertEqual(dep, "$1,000.00 to secure group space", rec)
            self.assertEqual(p2, "$12,977.80 by Dec 1, 2026 (Payment 2)", rec)
            self.assertEqual(final, "$12,977.80 by Feb 9, 2027 (Final Payment)", rec)

    def test_a_deposit_and_payment_2_that_exceed_the_total_fail_loudly(self):
        with self.assertRaises(ValueError):
            g.contract_payment_lines(booking(deposit_amount_agreement=20000, payment2_amount_agreement=10000))


if __name__ == "__main__":
    unittest.main()
