"""python -m unittest pipeline.test_deposit_sentence

Martha 2026-11-03: the main proposal page's fallback "Next steps" must not state a deposit
amount (the old Deposit Due Now figure contradicted the administrator view and Airtable's
Agreement fields). Ben Gamla and both Hanover bookings stay exactly as before."""
import unittest

from pipeline import generate_booking_package as g

PINNED = ("recqb6DGaeJRpymL2", "recP88dd2wk5XdHU3", "reciijikzFlFdq3Qr")


def legacy_next_steps(b, reef_first):
    """Verbatim copy of the fallback as it was on main before this change (the snapshot)."""
    deposit = b.get("deposit_due_now") or 0
    return [
        "Review each section of this proposal with your team.",
        "Select “Looks Good — Prepare My Contract,” or “Request a Change” if anything needs adjusting.",
        f"{reef_first} prepares your contract with the payment schedule"
        + (f", starting with a {g.money(deposit)} deposit to hold your date." if deposit else "."),
        "Once the contract is signed, REEF confirms final logistics with you, including headcount, arrival details, and what to bring.",
    ]


class DepositSentenceTest(unittest.TestCase):
    def test_pinned_bookings_render_exactly_as_before(self):
        for rid in PINNED:
            for deposit in (0, 500, 1000):
                b = {"record_id": rid, "deposit_due_now": deposit, "deposit_amount_agreement": 5391.12}
                self.assertEqual(g.default_next_steps(b, "Rose"), legacy_next_steps(b, "Rose"), (rid, deposit))

    def test_the_pin_list_is_exactly_those_three(self):
        self.assertEqual(g.LEGACY_PAYMENT_WORDING_IDS, set(PINNED))

    def test_other_bookings_state_no_dollar_amount(self):
        for deposit, agreement in ((1000, 5391.12), (500, None), (0, 2482.2), (0, None)):
            b = {"record_id": "recR4mF8LDuuLSadt", "deposit_due_now": deposit, "deposit_amount_agreement": agreement}
            text = " ".join(g.default_next_steps(b, "Your REEF contact"))
            self.assertNotIn("$", text, (deposit, agreement))

    def test_exact_new_sentence(self):
        b = {"record_id": "recR4mF8LDuuLSadt", "deposit_due_now": 1000, "deposit_amount_agreement": 5391.12}
        self.assertEqual(g.default_next_steps(b, "Your REEF contact")[2],
                         "Your REEF contact prepares your contract with the payment schedule, "
                         "starting with a deposit to hold your date.")

    def test_no_deposit_means_no_deposit_clause(self):
        b = {"record_id": "recR4mF8LDuuLSadt", "deposit_due_now": 0, "deposit_amount_agreement": None}
        self.assertEqual(g.default_next_steps(b, "Rose")[2], "Rose prepares your contract with the payment schedule.")

    def test_other_three_steps_are_unchanged(self):
        b = {"record_id": "recR4mF8LDuuLSadt", "deposit_due_now": 1000}
        new, old = g.default_next_steps(b, "Rose"), legacy_next_steps(b, "Rose")
        self.assertEqual([new[0], new[1], new[3]], [old[0], old[1], old[3]])

    def test_airtable_next_steps_text_still_wins(self):
        # the helper is only the fallback: the call site prefers Airtable's own text
        src = open(g.__file__).read()
        self.assertIn('split_items(b.get("proposal_next_steps")) or default_next_steps(b, reef_first)', src)


if __name__ == "__main__":
    unittest.main()
