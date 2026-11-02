"""python -m unittest pipeline.test_get_ready"""
import unittest
import unittest.mock
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


REC = "recAAAAAAAAAAAAAA"


def row(key, booking=REC, done=False, done_on=None, done_by=None):
    f = {gr.F_ITEM_KEY: key, gr.F_BOOKING: [booking] if booking else [], gr.F_DONE: done}
    if done_on:
        f[gr.F_DONE_ON] = done_on
    if done_by:
        f[gr.F_DONE_BY] = done_by
    return {"id": "recRow", "fields": f}


class CompletionStateTest(unittest.TestCase):
    def test_state_from_rows_filters_to_the_booking(self):
        rows = [row("deposit", done=True, done_on="2026-11-02", done_by="Rose"),
                row("payment2", booking="recBBBBBBBBBBBBBB", done=True),
                row("guarantee", booking=None, done=True),
                row("", done=True)]
        state = gr.state_from_rows(rows, REC)
        self.assertEqual(state, {"deposit": {"done": True, "doneOn": "2026-11-02", "doneBy": "Rose"}})

    def test_done_wins_over_a_duplicate_open_row(self):
        state = gr.state_from_rows([row("deposit", done=True), row("deposit", done=False)], REC)
        self.assertTrue(state["deposit"]["done"])
        state = gr.state_from_rows([row("deposit", done=False), row("deposit", done=True)], REC)
        self.assertTrue(state["deposit"]["done"])

    def test_unchecked_row_is_outstanding(self):
        self.assertFalse(gr.state_from_rows([row("deposit", done=False)], REC)["deposit"]["done"])

    def test_state_drives_the_checklist(self):
        state = gr.state_from_rows([row("deposit", done=True, done_on="2026-11-02", done_by="Rose")], REC)
        items = by_key(gr.build_checklist(booking(), TODAY, state))
        self.assertTrue(items["deposit"]["done"])
        self.assertEqual(items["deposit"]["doneBy"], "Rose")
        self.assertFalse(items["payment2"]["done"])
        self.assertIn("Complete 2026-11-02", gr.build_preview_html(booking(checklist_state=state), TODAY))

    def test_item_keys_cover_every_checklist_item(self):
        keys = {i["key"] for i in gr.build_checklist(booking(), TODAY)}
        self.assertEqual(keys, set(gr.ITEM_KEYS))

    def test_unknown_keys_are_reported(self):
        state = gr.state_from_rows([row("deposti", done=True), row("deposit")], REC)
        self.assertEqual(gr.unknown_keys(state), ["deposti"])

    def test_fetch_paginates_and_reads_only(self):
        pages = [{"records": [row("deposit", done=True)], "offset": "o1"}, {"records": [row("payment2", done=True)]}]
        calls = []

        class Resp:
            def __init__(self, body): self.body = body
            def raise_for_status(self): pass
            def json(self): return self.body

        class Http:
            def get(self, url, params=None, headers=None, timeout=None):
                calls.append(dict(params))
                return Resp(pages[len(calls) - 1])

        state = gr.fetch_completion_state(REC, api_key="k", http=Http())
        self.assertEqual(set(state), {"deposit", "payment2"})
        self.assertNotIn("offset", calls[0])
        self.assertEqual(calls[1]["offset"], "o1")
        self.assertTrue(any(k == "returnFieldsByFieldId" for k in calls[0]) or "returnFieldsByFieldId" in calls[0])

    def test_fetch_failure_returns_empty_and_never_raises(self):
        class Http:
            def get(self, *a, **k): raise requests_error()
        import requests
        requests_error = requests.ConnectionError
        self.assertEqual(gr.fetch_completion_state(REC, api_key="k", http=Http()), {})

    def test_no_key_returns_empty(self):
        import os
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gr.fetch_completion_state(REC), {})


class ViewsPayloadTest(unittest.TestCase):
    def test_money_only_in_administrator_view(self):
        v = gr.views_payload(booking(), TODAY)
        self.assertIn("$", str(v["administrator"]))
        for k in ("educator", "family", "student"):
            self.assertNotIn("$", str(v[k]), k)

    def test_internal_reef_items_never_published(self):
        blob = str(gr.views_payload(booking(), TODAY))
        self.assertNotIn("never promise", blob)
        self.assertNotIn("Rose, by hand", blob)
        self.assertNotIn("group rates", blob)

    def test_family_and_student_only_see_their_group(self):
        v = gr.views_payload(booking(), TODAY)
        for k in ("family", "student"):
            self.assertEqual([g["group"] for g in v[k]["groups"]], ["Students and families"])

    def test_dollar_amount_in_non_admin_view_fails_the_build(self):
        with unittest.mock.patch.dict(gr.ITEM_VIEWS, {"bring_lunch": gr.ALL_VIEWS}):
            with unittest.mock.patch.object(gr, "build_checklist", return_value=[
                    {"key": "bring_lunch", "group": "Students and families", "title": "Pack $5 lunch", "due": None,
                     "source": "x", "detail": "", "money": None, "provisional": False, "done": False, "doneOn": None}]):
                with self.assertRaises(gr.GetReadyContentError):
                    gr.views_payload(booking(), TODAY)

    def test_provisional_flag_and_payment_verified(self):
        v = gr.views_payload(booking(deposit_payment_status="Deposit Received"), TODAY)["administrator"]
        self.assertTrue(v["provisional"])
        dep = next(i for g in v["groups"] for i in g["items"] if i["key"] == "deposit")
        self.assertTrue(dep["paymentReceived"])

    def test_strict_fetch_raises(self):
        with self.assertRaises(RuntimeError):
            gr.fetch_completion_state("recAAAAAAAAAAAAAA", api_key="", strict=True)


if __name__ == "__main__":
    unittest.main()
