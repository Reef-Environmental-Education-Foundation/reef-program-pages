"""python -m unittest pipeline.test_get_ready"""
import unittest
from datetime import date

from pipeline import get_ready as gr

TODAY = date(2026, 10, 31)


def booking(**kw):
    b = {"org_name": "Test School", "arrival_date": "2027-03-17", "students": 66, "chaperones": 10,
         "guarantee_lock_date": "2026-12-17", "final_roster_due": "2027-02-15", "final_due_date": "2026-12-17",
         "deposit_due_agreement": "2026-11-14", "payment2_due_agreement": "2026-11-14",
         "deposit_amount_agreement": 2482.2, "payment2_amount_agreement": 3723.3,
         "min_guaranteed_spaces": 59, "total_package_price": 12411, "agreement_date": None,
         "proposal_version": 2, "stage": "Accepted", "agreement_contract_status": None}
    b.update(kw)
    return b


def by_key(items):
    return {i["key"]: i for i in items}


class ChecklistTest(unittest.TestCase):
    def test_all_four_groups_and_reef_present(self):
        groups = {i["group"] for i in gr.build_checklist(booking(), TODAY)}
        self.assertEqual(groups, set(gr.GROUPS))

    def test_dates_come_from_airtable(self):
        k = by_key(gr.build_checklist(booking(), TODAY))
        self.assertEqual(k["guarantee"]["due"], date(2026, 12, 17))
        self.assertEqual(k["final_roster"]["due"], date(2027, 2, 15))
        self.assertEqual(k["collect_forms"]["due"], date(2027, 2, 15))
        self.assertEqual(k["bring_lunch"]["due"], date(2027, 3, 17))
        self.assertEqual(k["deposit"]["due"], date(2026, 11, 14))
        self.assertEqual(k["guarantee"]["daysToDue"], 47)

    def test_payment_items_are_provisional_until_agreement_date(self):
        k = by_key(gr.build_checklist(booking(), TODAY))
        self.assertTrue(k["deposit"]["provisional"] and k["payment2"]["provisional"])
        k = by_key(gr.build_checklist(booking(agreement_date="2026-11-01"), TODAY))
        self.assertFalse(k["deposit"]["provisional"])

    def test_completion_state_and_overdue(self):
        state = {"deposit": {"done": True, "doneOn": "2026-11-02"}}
        items = by_key(gr.build_checklist(booking(), date(2026, 11, 20), state))
        self.assertTrue(items["deposit"]["done"])
        self.assertFalse(items["deposit"]["overdue"])
        self.assertTrue(items["payment2"]["overdue"])          # due 11/14, not done, today 11/20
        s = gr.summarize(list(items.values()))
        self.assertEqual(s["complete"], 1)
        self.assertEqual(s["outstanding"], s["total"] - 1)
        self.assertGreaterEqual(s["overdue"], 1)

    def test_no_money_outside_the_administrator_group(self):
        for it in gr.build_checklist(booking(), TODAY):
            if it["group"] != "School administrator":
                self.assertIsNone(it["money"], it["key"])
                self.assertNotIn("$", it["title"] + it["detail"])

    def test_missing_dates_do_not_crash(self):
        items = gr.build_checklist(booking(guarantee_lock_date=None, final_roster_due=None, arrival_date=None), TODAY)
        self.assertTrue(all(i["daysToDue"] is None for i in items if i["due"] is None))


class PreviewHtmlTest(unittest.TestCase):
    def test_preview_is_internal_noindex_and_provisional(self):
        out = gr.build_preview_html(booking(), TODAY)
        self.assertIn("INTERNAL PREVIEW", out)
        self.assertIn('content="noindex, nofollow"', out)
        self.assertIn("provisional until the Agreement Date is entered", out)
        self.assertIn("Template (confirm)", out)
        self.assertIn("$2,482.20", out)

    def test_preview_does_not_present_ready_to_proceed_as_final(self):
        out = gr.build_preview_html(booking(), TODAY)
        self.assertIn("not treated as final", out)

    def test_preview_escapes_school_names(self):
        out = gr.build_preview_html(booking(org_name="<script>x</script>"), TODAY)
        self.assertNotIn("<script>x</script>", out)

    def test_family_and_student_rows_show_no_dollars(self):
        out = gr.build_preview_html(booking(), TODAY)
        for group in ("Teacher to families", "Students and families"):
            start = out.index(f"<h3>{group}</h3>")
            end = out.index("</table>", start)
            self.assertNotIn("$", out[start:end])


if __name__ == "__main__":
    unittest.main()
