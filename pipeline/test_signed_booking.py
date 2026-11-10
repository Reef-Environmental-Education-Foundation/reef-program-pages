"""python -m unittest pipeline.test_signed_booking

A booking whose Agreement/Contract Status is Signed shows the signed terms (Agreement fields) and never the
proposal-stage wording: the old $500 deposit, the 10% late fee, 'Approve Program', 'once it's sent'.
Martha, 2026-11-10 (Ben Gamla)."""
import json
import re
import unittest
from datetime import date
from pathlib import Path

from pipeline import generate_booking_package as g
from pipeline import get_ready as gr
import audience_views as av

REPO = Path(__file__).parent.parent

BEN_GAMLA = "recqb6DGaeJRpymL2"
FORBIDDEN = ("$500", "10% late fee", "Approve Program", "once it's sent", "once it’s sent",
             "Approving this summary", "Send feedback", "[confirm from booking data]")


def booking(**kw):
    b = {"record_id": BEN_GAMLA, "status": "Confirmed", "agreement_contract_status": "Signed",
         "agreement_date": "2026-11-09", "min_guaranteed_spaces": 57,
         "deposit_amount_agreement": 2514.33, "deposit_due_agreement": "2026-11-23T00:00:00.000Z",
         "payment2_amount_agreement": 3771.5, "payment2_due_agreement": "2026-11-23T00:00:00.000Z",
         "final_amount_agreement": 6285.82, "final_due_date": "2026-12-17T00:00:00.000Z",
         "guarantee_lock_date": "2026-12-17T00:00:00.000Z", "guaranteed_cost_agreement": 10236.92,
         "deposit_due_now": 500, "payment2_amount": 6035.82, "payment2_due_date": "2026-11-10",
         "final_amount": 6285.82, "payment_tier": "Mid (90–180 days out): $500 deposit + 2 payments",
         "total_package_price": 12571.65, "deposit_payment_status": None,
         "contact_role": "Dean of Students", "student_grade_level": "Elementary (K–6)"}
    b.update(kw)
    return b


def signed_text(b):
    b = dict(b)
    b["agreement_payment"] = g.agreement_payment_terms(b)
    b["payment2_due_pretty"] = b["final_due_pretty"] = ""
    defaults = av.load_defaults()
    parts = av._payment_lines(b, defaults, g.money)
    parts.append(json.dumps(g.build_payment_schedule(b)))
    parts.append(g.signed_first_step(b))
    return " | ".join(parts)


class SignedTermsTest(unittest.TestCase):
    def test_signed_renders_agreement_terms_even_for_a_legacy_pinned_booking(self):
        text = signed_text(booking())
        for want in ("$2,514.33", "$3,771.50", "$6,285.82", "Nov 23, 2026", "Dec 17, 2026",
                     "57 paid spaces", "$10,236.92", "flat $100 late fee"):
            self.assertIn(want, text)

    def test_signed_never_renders_proposal_stage_wording(self):
        text = signed_text(booking())
        for bad in FORBIDDEN:
            self.assertNotIn(bad, text)
        self.assertNotIn("6,035.82", text)          # the old Payment 2

    def test_signed_without_agreement_fields_still_avoids_the_standard_terms(self):
        b = booking(deposit_amount_agreement=None)
        b["agreement_payment"] = g.agreement_payment_terms(b)
        self.assertIsNone(b["agreement_payment"])
        lines = " ".join(av._payment_lines(b, av.load_defaults(), g.money))
        self.assertNotIn("10% late fee", lines)
        self.assertNotIn("$500", lines)

    def test_unsigned_bookings_are_unchanged(self):
        b = booking(agreement_contract_status="Sent")
        b["agreement_payment"] = g.agreement_payment_terms(b)
        b["payment2_due_pretty"] = "Nov 10, 2026"
        b["final_due_pretty"] = "Dec 17, 2026"
        self.assertIsNone(b["agreement_payment"])                    # legacy pin still applies
        lines = " ".join(av._payment_lines(b, av.load_defaults(), g.money))
        self.assertIn("10% late fee", lines)
        self.assertIn("$500.00 deposit", lines)
        self.assertEqual(g.build_payment_schedule(b)["items"][0]["label"], "Deposit (due now)")
        self.assertFalse(g.is_signed(b))

    def test_next_step_is_signed_wording(self):
        step = g.signed_first_step(booking())
        self.assertIn("Your agreement is signed", step)
        self.assertNotIn("once it's sent", step)


class HeroChipsTest(unittest.TestCase):
    def test_grade_chip_hidden_for_ben_gamla_and_never_a_contact_title(self):
        self.assertIsNone(g.grade_level_chip(booking()))
        other = booking(record_id="recOTHER00000000A")
        self.assertEqual(g.grade_level_chip(other), "Elementary (K–6)")
        self.assertIsNone(g.grade_level_chip(booking(record_id="recOTHER00000000A", student_grade_level=None)))
        self.assertNotEqual(g.grade_level_chip(other), other["contact_role"])

    def test_dates_chip_vocabulary(self):
        self.assertEqual(g.dates_chip(booking()), ("Dates held", "Deposit due Nov 23, 2026"))
        self.assertEqual(g.dates_chip(booking(deposit_payment_status="Deposit Received")), ("Dates confirmed", None))
        self.assertEqual(g.dates_chip(booking(status="Proposal Sent", agreement_contract_status=None)), ("Proposed", None))

    def test_per_student_rounds_half_up_like_the_contract(self):
        self.assertEqual(g.money(179.595), "$179.60")
        self.assertEqual(g.money(179.59), "$179.59")
        self.assertEqual(g.money(12571.65), "$12,571.65")


class RenderSourceTest(unittest.TestCase):
    """render.js hides what a signed or valueless page must not show (checked in the source; the browser
    check is in the sprint closeout)."""
    JS = (Path(__file__).parent.parent / "assets" / "render.js").read_text()

    def test_signed_hides_approval_and_placeholder_boxes(self):
        self.assertIn("V.agreementSigned", self.JS)
        self.assertIn("signed ? null : el(\"h3\", { class: \"a-h3\" }, [\"Approval\"])", self.JS)
        self.assertIn("!signed ? adminApproval(V)".replace("!signed ? ", "&& !signed ? "), self.JS)
        self.assertIn("A box with no value is hidden", self.JS)
        self.assertIn('pair[0] !== "Grade Level"', self.JS)

    def test_audience_data_for_signed_turns_off_the_approval_box(self):
        src = (Path(__file__).parent / "audience_views.py").read_text()
        self.assertIn('"enabled": adm.get("approval", True) and not signed', src)
        self.assertIn('"agreementSigned": signed', src)


class RemovedZzzPublishTest(unittest.TestCase):
    """Martha, 2026-11-10: the ZZZ Riverside test page (rec4YP9ruVPOD90US) is not published and not linked."""

    def test_riverside_test_page_is_gone_and_unlinked(self):
        self.assertFalse((REPO / "bookings" / "zzz-test-org-riverside-academy-proposal-qa").exists())
        self.assertNotIn("zzz-test-org-riverside", (REPO / "index.html").read_text())
        for d in (REPO / "bookings").iterdir():
            vm = d / "version.json"
            if vm.exists():
                self.assertNotEqual(json.loads(vm.read_text()).get("bookingId"), "rec4YP9ruVPOD90US", d.name)


class SignedCancellationTest(unittest.TestCase):
    def lines(self, **kw):
        b = booking(**kw)
        return av.signed_cancellation_lines(g.agreement_payment_terms(b), g.money)

    def test_section_10_text_and_numbers_are_exact(self):
        text = " | ".join(self.lines())
        for want in ("the greater of (a) the percentage of the Guaranteed Program Cost below, or (b) REEF's nonrecoverable "
                     "costs incurred through the cancellation date, but never more than 100% of the Guaranteed Program Cost",
                     "more than 180 days before the program start: the deposit",
                     "121 to 180 days before the program start: 35%",
                     "91 to 120 days before the program start: 50%",
                     "61 to 90 days before the program start: 75%",
                     "60 days or fewer before the program start: 100%", "(no refund)",
                     "Cooling-off period (Section 3)", "within 7 days after the Agreement Date",
                     "guarantee in Section 7 and are not partial cancellations",
                     "in writing to explorers@REEF.org"):
            self.assertIn(want, text)

    def test_dollar_figures_come_from_the_agreement_cost_or_are_left_out(self):
        text = " | ".join(self.lines())
        self.assertIn("$3,582.92", text)        # 35% of $10,236.92
        self.assertIn("$10,236.92", text)       # 100%
        no_cost = " | ".join(av.signed_cancellation_lines({"guaranteed_cost": None}, g.money))
        self.assertNotIn("$", no_cost)
        self.assertIn("35% of the Guaranteed Program Cost.", no_cost)

    def test_unsigned_keeps_the_standard_cancellation_terms(self):
        d = av.load_defaults()
        self.assertIn("$100 per day of scheduled programming", " ".join(d["cancellationTerms"]))


class SignedCleanupTest(unittest.TestCase):
    TODAY = date(2026, 11, 10)

    def items(self, **kw):
        b = booking(arrival_date="2027-03-17", final_roster_due="2027-02-15", **kw)
        state = {"sign_agreement": {"done": True, "doneOn": "2026-11-09"}}
        return {i["key"]: i for i in gr.build_checklist(b, self.TODAY, state)}

    def test_final_payment_shows_the_agreement_amount(self):
        it = self.items()["final_payment"]
        self.assertEqual(it["money"], "$6,285.82")
        self.assertNotIn("balance under the signed agreement", it["detail"])

    def test_unsigned_final_payment_wording_is_unchanged(self):
        it = self.items(agreement_contract_status="Sent", final_amount_agreement=None)["final_payment"]
        self.assertIn("balance under the signed agreement", it["detail"])

    def test_sign_item_says_when_it_was_signed(self):
        self.assertEqual(self.items()["sign_agreement"]["detail"], "Signed on Nov 9, 2026.")

    def test_template_tags_only_in_internal_mode(self):
        b = booking(arrival_date="2027-03-17", final_roster_due="2027-02-15")
        school = gr.views_payload(b, self.TODAY, school_facing=True)
        internal = gr.views_payload(b, self.TODAY, school_facing=False)
        flags = lambda p: [i["template"] for v in p.values() for g_ in v["groups"] for i in g_["items"]]  # noqa: E731
        self.assertFalse(any(flags(school)))
        self.assertTrue(any(flags(internal)))

    def test_headcount_step_uses_the_booking_dates(self):
        step = g.signed_headcount_step(booking(final_roster_due="2027-02-15T00:00:00.000Z"))
        self.assertEqual(step, "Confirm your final participant count by Dec 17, 2026 (guarantee lock) and send the "
                               "final roster by Feb 15, 2027.")
        self.assertNotIn("2 weeks", step)

    def test_admin_page_title_for_signed_bookings(self):
        src = (Path(__file__).parent / "audience_views.py").read_text()
        self.assertEqual(src.count('"Administrator Summary"'), 2)       # share card + the page itself


if __name__ == "__main__":
    unittest.main()
