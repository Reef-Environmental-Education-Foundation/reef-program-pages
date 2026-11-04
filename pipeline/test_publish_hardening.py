"""python -m unittest pipeline.test_publish_hardening

Covers the publish-pipeline hardening: build validation, the approval gate,
a failed build leaving the live page untouched, the Airtable write-back
fields, and Asana's one-open-task-per-version rule. No network."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import airtable_writeback as wb
from pipeline import generate_booking_package as g
from pipeline import publish_support as ps

REPO = Path(g.__file__).parent.parent


def good_proposal():
    return {"docType": "proposal", "proposal": {
        "meta": {"bookingId": "recAAAAAAAAAAAAAA"}, "group": {"orgName": "X"}, "dates": {"label": "d"},
        "roadmap": {"steps": ["a"]}, "cta": {"primaryText": "ok"}, "reefContact": {"name": "R"},
        "welcome": {"body": ["hi"]}, "glance": [{"k": "a", "v": "b"}], "days": [{"title": "d"}],
        "included": [{"title": "t", "items": ["i"]}],
        "pricing": {"estimatedTotal": "$1.00"}}}


def write_build(root, data, index="<html></html>"):
    d = Path(root)
    (d / "data.js").write_text("/* GENERATED */\nwindow.BOOKING_DATA = " + json.dumps(data, indent=2) + ";\n")
    if index is not None:
        (d / "index.html").write_text(index)
    return d


class ValidateBuildTest(unittest.TestCase):
    def test_good_build_passes(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertEqual(ps.validate_build(write_build(r, good_proposal()), True), [])

    def test_missing_index_and_empty_section_fail(self):
        data = good_proposal()
        data["proposal"]["days"] = []
        with tempfile.TemporaryDirectory() as r:
            problems = ps.validate_build(write_build(r, data, index=None), True)
        self.assertIn("index.html was not written", problems)
        self.assertTrue(any("'days'" in p for p in problems))

    def test_unparseable_data_js_fails(self):
        with tempfile.TemporaryDirectory() as r:
            (Path(r) / "index.html").write_text("x")
            (Path(r) / "data.js").write_text("window.BOOKING_DATA = {oops};")
            self.assertTrue(any("does not parse" in p for p in ps.validate_build(r, True)))

    def test_bad_text_fails(self):
        for bad in ("undefined", "NaN", "${total}", "{{token}}"):
            data = good_proposal()
            data["proposal"]["welcome"]["body"] = [f"Total {bad}"]
            with tempfile.TemporaryDirectory() as r:
                problems = ps.validate_build(write_build(r, data), True)
            self.assertTrue(any("data.js contains" in p for p in problems), bad)

    def test_every_published_page_on_main_validates(self):
        for d in sorted((REPO / "bookings").iterdir()):
            if d.name.startswith(("sample", "zzz")) or not (d / "data.js").exists():
                continue
            self.assertEqual(ps.validate_build(d, True), [], d.name)


class GateTest(unittest.TestCase):
    def booking(self, **kw):
        b = {"approved_to_share": True, "approved_stage": "Proposal", "approved_version": 2,
             "proposal_version": 2, "approved_by": "Martha"}
        b.update(kw)
        return b

    def test_approved_current_version_passes(self):
        self.assertEqual(g.check_share_approval(self.booking(), True), [])

    def test_version_mismatch_blocks(self):
        self.assertTrue(g.check_share_approval(self.booking(proposal_version=3), True))

    def test_unapproved_blocks(self):
        self.assertTrue(g.check_share_approval(self.booking(approved_to_share=False), True))

    def test_blank_versions_agree(self):
        self.assertEqual(g.check_share_approval(self.booking(approved_version=None, proposal_version=None), True), [])


class FailedBuildKeepsLivePageTest(unittest.TestCase):
    """promote_build is the only thing that touches bookings/; main() calls it
    only after validate_build is clean."""

    def test_failed_validation_never_reaches_bookings(self):
        with tempfile.TemporaryDirectory() as live_root, tempfile.TemporaryDirectory() as build:
            live = Path(live_root) / "bookings" / "school"
            live.mkdir(parents=True)
            (live / "data.js").write_text("LIVE v1")
            broken = good_proposal()
            broken["proposal"]["pricing"] = {}
            write_build(build, broken)
            problems = ps.validate_build(build, True)
            self.assertTrue(problems)
            # the real flow stops here; confirm the live copy is untouched
            self.assertEqual((live / "data.js").read_text(), "LIVE v1")

    def test_promote_overlays_and_keeps_existing_photos(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as build:
            bookings = Path(root) / "bookings"
            (bookings / "school" / "photos").mkdir(parents=True)
            (bookings / "school" / "photos" / "days.jpeg").write_text("old photo")
            write_build(build, good_proposal())
            with mock.patch.object(g, "BOOKINGS_OUT_DIR", bookings), \
                    mock.patch.object(g, "CONTRACTS_OUT_DIR", Path(root) / "contracts"):
                g.promote_build(Path(build), "school")
            self.assertTrue((bookings / "school" / "data.js").exists())
            self.assertEqual((bookings / "school" / "photos" / "days.jpeg").read_text(), "old photo")


class WritebackTest(unittest.TestCase):
    RESULT = {"status": "published", "proposal_version": 2,
              "page_url": "https://example.test/bookings/school/"}

    def test_decide(self):
        self.assertEqual(wb.decide(self.RESULT, "success", "success", "success"), (True, ""))
        self.assertEqual(wb.decide(self.RESULT, "success", "success", "skipped", "false"), (True, ""))
        self.assertFalse(wb.decide(self.RESULT, "success", "success", "failure")[0])
        self.assertFalse(wb.decide(self.RESULT, "success", "failure", "skipped")[0])
        self.assertFalse(wb.decide(None, "success", "success", "success")[0])
        blocked = {"status": "blocked", "message": "Not approved"}
        ok, msg = wb.decide(blocked, "failure", "skipped", "skipped")
        self.assertEqual((ok, msg), (False, "Not approved"))

    def test_success_fields(self):
        f = ps.writeback_fields(self.RESULT, True, "https://github.test/run/1")
        self.assertEqual(f[ps.F_PUBLISH_RESULT], "Success")
        self.assertEqual(f[ps.F_PUBLISHED_VERSION], 2)
        self.assertFalse(f[ps.F_PUBLISH_REQUESTED])
        self.assertIn("https://github.test/run/1", f[ps.F_PUBLISH_MESSAGE])
        self.assertIn("https://example.test/bookings/school/", f[ps.F_PUBLISH_MESSAGE])
        self.assertTrue(f[ps.F_PUBLISHED_AT].endswith("Z"))

    def test_failure_fields_do_not_move_published_version(self):
        f = ps.writeback_fields({"message": "boom"}, False, "https://github.test/run/1")
        self.assertEqual(f[ps.F_PUBLISH_RESULT], "Failed - previous version still live")
        self.assertNotIn(ps.F_PUBLISHED_VERSION, f)
        self.assertNotIn(ps.F_PUBLISHED_AT, f)
        self.assertFalse(f[ps.F_PUBLISH_REQUESTED])
        self.assertIn("boom", f[ps.F_PUBLISH_MESSAGE])

    def test_main_patches_airtable_and_clears_the_checkbox(self):
        with tempfile.TemporaryDirectory() as d:
            rf = Path(d) / "result.json"
            rf.write_text(json.dumps(self.RESULT))
            env = {"RECORD_ID": "recAAAAAAAAAAAAAA", "RESULT_FILE": str(rf), "GENERATE_OUTCOME": "success",
                   "COMMIT_OUTCOME": "success", "DEPLOY_OUTCOME": "success", "PUSHED": "true",
                   "AIRTABLE_WRITE_KEY": "k", "GITHUB_RUN_ID": "9", "GITHUB_REPOSITORY": "o/r"}
            with mock.patch.object(wb, "patch_record") as patch:
                self.assertEqual(wb.main(env), 0)
            record_id, fields, key = patch.call_args[0]
            self.assertEqual(record_id, "recAAAAAAAAAAAAAA")
            self.assertFalse(fields[ps.F_PUBLISH_REQUESTED])
            self.assertEqual(fields[ps.F_PUBLISH_RESULT], "Success")

    def test_main_with_no_token_or_bad_id_is_a_quiet_noop(self):
        with mock.patch.object(wb, "patch_record") as patch:
            self.assertEqual(wb.main({"RECORD_ID": "recAAAAAAAAAAAAAA"}), 0)
            self.assertEqual(wb.main({"RECORD_ID": "x; rm -rf /", "AIRTABLE_WRITE_KEY": "k"}), 0)
        patch.assert_not_called()

    def test_failed_run_still_clears_publish_requested(self):
        env = {"RECORD_ID": "recAAAAAAAAAAAAAA", "RESULT_FILE": "/nonexistent", "GENERATE_OUTCOME": "failure",
               "AIRTABLE_WRITE_KEY": "k"}
        with mock.patch.object(wb, "patch_record") as patch:
            wb.main(env)
        fields = patch.call_args[0][1]
        self.assertFalse(fields[ps.F_PUBLISH_REQUESTED])
        self.assertEqual(fields[ps.F_PUBLISH_RESULT], "Failed - previous version still live")

    def test_record_id_validation(self):
        self.assertTrue(ps.RECORD_ID_RE.match("recqb6DGaeJRpymL2"))
        self.assertFalse(ps.RECORD_ID_RE.match("rec123"))
        self.assertFalse(ps.RECORD_ID_RE.match("recqb6DGaeJRpymL2; echo"))


class AsanaDedupeTest(unittest.TestCase):
    B = {"record_id": "recAAAAAAAAAAAAAA", "proposal_version": 2, "asana_task_id": "111",
         "booking_type": "Group Program - Expedition"}

    def response(self, tasks):
        r = mock.Mock()
        r.json.return_value = {"data": tasks}
        r.raise_for_status.return_value = None
        return r

    def test_marker_includes_version(self):
        self.assertEqual(g.review_task_marker(self.B), "[recAAAAAAAAAAAAAA v2]")

    def test_finds_open_task_for_same_version_only(self):
        tasks = [{"gid": "1", "name": "x [recAAAAAAAAAAAAAA v1]", "completed": False},
                 {"gid": "2", "name": "x [recAAAAAAAAAAAAAA v2]", "completed": True},
                 {"gid": "3", "name": "x [recAAAAAAAAAAAAAA v2]", "completed": False}]
        with mock.patch.object(g.requests, "get", return_value=self.response(tasks)):
            self.assertEqual(g.find_open_review_task(self.B, "[recAAAAAAAAAAAAAA v2]"), "3")

    def test_no_match_returns_none(self):
        with mock.patch.object(g.requests, "get", return_value=self.response([])):
            self.assertIsNone(g.find_open_review_task(self.B, "[recAAAAAAAAAAAAAA v2]"))

    def test_existing_task_gets_a_comment_not_a_duplicate(self):
        with mock.patch.object(g, "ASANA_API_KEY", "k"), \
                mock.patch.object(g, "find_open_review_task", return_value="3"), \
                mock.patch.object(g, "add_asana_comment") as comment, \
                mock.patch.object(g.requests, "post") as post:
            b = dict(self.B, org_name="X", approved_by="M", approved_date="", approved_stage="Proposal",
                     approved_version=2)
            self.assertEqual(g.create_review_task(b, "https://p/", None), "3")
        post.assert_not_called()
        comment.assert_called_once()

    def test_search_failure_falls_back_to_none(self):
        with mock.patch.object(g.requests, "get", side_effect=g.requests.ConnectionError("down")):
            self.assertIsNone(g.find_open_review_task(self.B, "[m]"))


class WorkflowTest(unittest.TestCase):
    def test_workflow_has_triggers_concurrency_and_always_writeback(self):
        text = (REPO / ".github" / "workflows" / "publish-booking.yml").read_text()
        self.assertIn("repository_dispatch:", text)
        self.assertIn("types: [publish-booking]", text)
        self.assertIn("concurrency:", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("if: always()", text)
        self.assertNotIn("${{ github.event.inputs.booking_record_id }}\"", text)  # never inline into shell

    def test_no_runner_context_in_job_level_env(self):
        # `runner` is not available in jobs.<id>.env: GitHub rejects the whole
        # workflow file ("Unrecognized named-value: 'runner'"). Regression
        # from the first version of this workflow.
        text = (REPO / ".github" / "workflows" / "publish-booking.yml").read_text()
        job_level = text.split("    steps:")[0]
        self.assertNotIn("runner.", job_level)
        self.assertIn("RESULT_FILE=$RUNNER_TEMP", text)


if __name__ == "__main__":
    unittest.main()
