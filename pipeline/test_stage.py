"""python -m unittest pipeline.test_stage"""
import unittest
from datetime import date

from pipeline import generate_booking_package as g

TODAY = date(2026, 10, 31)


def stage(**kw):
    b = {"status": "Quoting", "proposal_response": "", "agreement_contract_status": None,
         "arrival_date": "2027-03-17"}
    b.update(kw)
    return g.derive_stage(b, today=TODAY)


class StageTest(unittest.TestCase):
    def test_proposal(self):
        self.assertEqual(stage(status="Quoting"), "Proposal")
        self.assertEqual(stage(status="Proposal Sent"), "Proposal")
        self.assertEqual(stage(status="Something New"), "Proposal")

    def test_accepted(self):
        self.assertEqual(stage(status="Verbal Yes"), "Accepted")
        self.assertEqual(stage(status="Proposal Sent", proposal_response="Ready to Proceed"), "Accepted")
        self.assertEqual(stage(status="Proposal Sent", proposal_response="Change Requested"), "Proposal")

    def test_agreement_pending(self):
        self.assertEqual(stage(status="Verbal Yes", agreement_contract_status="Sent"), "Agreement pending")
        self.assertEqual(stage(status="Contracted"), "Agreement pending")

    def test_confirmed_and_get_ready_by_arrival_window(self):
        self.assertEqual(stage(status="Confirmed", arrival_date="2027-06-01"), "Confirmed")        # 213 days out
        self.assertEqual(stage(status="Confirmed", arrival_date="2027-02-28"), "Get Ready")        # 120 days out
        self.assertEqual(stage(status="Confirmed", arrival_date="2027-03-01"), "Confirmed")        # 121 days out
        self.assertEqual(stage(status="In Progress", arrival_date="2026-10-30"), "Get Ready")
        self.assertEqual(stage(status="Confirmed", arrival_date=None), "Confirmed")

    def test_completed(self):
        self.assertEqual(stage(status="Completed", arrival_date="2026-01-01"), "Completed")

    def test_signed_agreement_is_get_ready_without_window(self):
        # Martha, 2026-11-10: Signed + Confirmed/Contracted/In Progress = Get Ready, however far out
        self.assertEqual(stage(status="Confirmed", agreement_contract_status="Signed", arrival_date="2027-03-17"), "Get Ready")  # 127 days
        self.assertEqual(stage(status="Contracted", agreement_contract_status="Signed"), "Get Ready")
        self.assertEqual(stage(status="In Progress", agreement_contract_status="Signed", arrival_date="2028-01-01"), "Get Ready")
        self.assertEqual(stage(status="Confirmed", agreement_contract_status="Signed", arrival_date=None), "Get Ready")

    def test_signed_does_not_override_other_statuses(self):
        self.assertNotEqual(stage(status="Cancelled", agreement_contract_status="Signed"), "Get Ready")
        self.assertEqual(stage(status="Completed", agreement_contract_status="Signed"), "Completed")
        self.assertEqual(stage(status="Verbal Yes", agreement_contract_status="Signed"), "Accepted")

    def test_not_signed_keeps_window_rule(self):
        self.assertEqual(stage(status="Confirmed", agreement_contract_status="Sent", arrival_date="2027-03-17"), "Confirmed")
        self.assertEqual(stage(status="Confirmed", agreement_contract_status=None, arrival_date="2027-03-17"), "Confirmed")
        self.assertEqual(stage(status="Confirmed", arrival_date="2027-02-09"), "Get Ready")  # 100 days


if __name__ == "__main__":
    unittest.main()
