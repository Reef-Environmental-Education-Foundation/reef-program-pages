"""python -m unittest pipeline.test_page_consistency

Defect 1 (scenario test 2026-11-02): after republishes the main proposal page showed
v2 while the administrator share view showed v5. These tests keep the pieces of one
booking in step, in the build, in the committed pages, and on the deployed site."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import publish_support as ps
from pipeline import verify_live as vl

REPO = Path(ps.__file__).parent.parent


def js(obj):
    return "window.BOOKING_DATA = " + json.dumps(obj) + ";\n"


def write_booking(root, page_v="v5", admin_v="v5", marker_v=5, total="$26,955.60", admin_total=None,
                  students=75, admin_students=None):
    d = Path(root)
    (d / "share" / "administrator").mkdir(parents=True)
    (d / "share" / "family").mkdir(parents=True)
    (d / "data.js").write_text(js({"docType": "proposal", "proposal": {
        "meta": {"proposalVersion": page_v}, "pricing": {"estimatedTotal": total},
        "group": {"students": students}}}))
    (d / "share" / "administrator" / "data.js").write_text(js({"view": {
        "version": admin_v, "pricing": {"total": admin_total or total},
        "counts": {"students": admin_students if admin_students is not None else students}}}))
    (d / "share" / "family" / "data.js").write_text(js({"view": {"version": page_v}}))
    if marker_v is not None:
        (d / "version.json").write_text(json.dumps({"currentVersion": marker_v}))
    return d


class BuildConsistencyTest(unittest.TestCase):
    def test_matching_pieces_pass(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertEqual(ps.check_page_consistency(write_booking(r)), [])

    def test_the_reported_defect_is_caught(self):
        with tempfile.TemporaryDirectory() as r:
            problems = ps.check_page_consistency(write_booking(r, page_v="v2", admin_v="v5", marker_v=5,
                                                               total="$14,689.50", admin_total="$26,955.60",
                                                               students=60, admin_students=75))
        text = " | ".join(problems)
        self.assertIn("share/administrator says v5 but the main page says v2", text)
        self.assertNotIn("version.json says", text)  # marker v5 > page v2 is the designed banner state
        self.assertIn("administrator total $26,955.60 differs from the main page total $14,689.50", text)
        self.assertIn("administrator shows 75 students but the main page shows 60", text)

    def test_marker_newer_than_the_page_is_the_designed_updating_state(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertEqual(ps.check_page_consistency(write_booking(r, marker_v=6)), [])

    def test_marker_older_than_the_page_is_a_problem(self):
        with tempfile.TemporaryDirectory() as r:
            problems = ps.check_page_consistency(write_booking(r, marker_v=4))
        self.assertEqual(problems, ["version.json says v4 but the main page says v5"])

    def test_each_mismatch_alone_is_caught(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertTrue(ps.check_page_consistency(write_booking(r, admin_v="v4")))
        with tempfile.TemporaryDirectory() as r:
            self.assertTrue(ps.check_page_consistency(write_booking(r, marker_v=4)))
        with tempfile.TemporaryDirectory() as r:
            self.assertTrue(ps.check_page_consistency(write_booking(r, admin_total="$1.00")))

    def test_string_and_number_versions_compare_equal(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertEqual(ps.check_page_consistency(write_booking(r, page_v="v5", admin_v="5", marker_v=5)), [])

    def test_missing_pieces_are_skipped(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertEqual(ps.check_page_consistency(write_booking(r, marker_v=None)), [])

    def test_validate_build_refuses_an_inconsistent_build(self):
        with tempfile.TemporaryDirectory() as r:
            d = write_booking(r, page_v="v2", admin_v="v5")
            (d / "index.html").write_text("<html></html>")
            data = json.loads((d / "data.js").read_text().split("=", 1)[1].rstrip().rstrip(";"))
            for k in ps.PROPOSAL_REQUIRED:
                data["proposal"].setdefault(k, {"x": 1} if k not in ("days", "included", "glance", "welcome") else [{"x": 1}])
            data["proposal"]["pricing"] = {"estimatedTotal": "$26,955.60"}
            data["proposal"]["welcome"] = {"body": ["hi"]}
            (d / "data.js").write_text(js(data))
            problems = ps.validate_build(d, True)
        self.assertTrue(any("share/administrator says v5" in p for p in problems), problems)

    def test_every_published_booking_on_main_is_consistent(self):
        checked = 0
        for d in sorted((REPO / "bookings").iterdir()):
            if d.name.startswith("sample") or not (d / "data.js").exists():
                continue
            self.assertEqual(ps.check_page_consistency(d), [], d.name)
            checked += 1
        self.assertGreaterEqual(checked, 8)


class FakeHttp:
    def __init__(self, files):
        self.files, self.urls = files, []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        path = url.split("?")[0]
        resp = mock.Mock()
        if path not in self.files:
            resp.raise_for_status.side_effect = RuntimeError("404")
        else:
            resp.raise_for_status.return_value = None
            resp.text = self.files[path]
        return resp


BASE = "https://example.test/bookings/school/"


def live_files(page_v="v5", admin_v="v5", marker_v=5, total="$26,955.60"):
    return {BASE + "data.js": js({"proposal": {"meta": {"proposalVersion": page_v}, "pricing": {"estimatedTotal": total}}}),
            BASE + "version.json": json.dumps({"currentVersion": marker_v}),
            BASE + "share/administrator/data.js": js({"view": {"version": admin_v, "pricing": {"total": total}}})}


class LiveCheckTest(unittest.TestCase):
    def test_matching_deploy_passes_and_uses_a_cache_buster(self):
        http = FakeHttp(live_files())
        self.assertEqual(vl.live_problems(BASE, 5, "$26,955.60", http=http), [])
        self.assertTrue(all("?cb=" in u for u in http.urls))

    def test_stale_main_page_is_reported(self):
        problems = vl.live_problems(BASE, 5, "$26,955.60", http=FakeHttp(live_files(page_v="v2")))
        self.assertEqual(problems, ["main page serves v2, expected v5"])

    def test_missing_files_are_a_finding_not_a_crash(self):
        problems = vl.live_problems(BASE, 5, None, http=FakeHttp({}))
        self.assertTrue(problems and "could not fetch" in problems[0])

    def test_main_writes_a_warning_and_exits_1_on_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            rf = Path(d) / "r.json"
            rf.write_text(json.dumps({"status": "published", "page_url": BASE, "proposal_version": 5,
                                      "estimated_total": "$26,955.60"}))
            code = vl.main({"RESULT_FILE": str(rf)}, http=FakeHttp(live_files(page_v="v2")),
                           sleep=lambda s: None, attempts=3)
            self.assertEqual(code, 1)
            warning = json.loads(rf.read_text())["live_check_warning"]
        self.assertIn("main page serves v2", warning)
        fields = ps.writeback_fields({"page_url": BASE, "proposal_version": 5, "live_check_warning": warning}, True, "run")
        self.assertIn("WARNING:", fields[ps.F_PUBLISH_MESSAGE])
        self.assertEqual(fields[ps.F_PUBLISH_RESULT], ps.RESULT_SUCCESS)

    def test_main_passes_quietly_when_it_matches_and_retries_until_then(self):
        with tempfile.TemporaryDirectory() as d:
            rf = Path(d) / "r.json"
            rf.write_text(json.dumps({"status": "published", "page_url": BASE, "proposal_version": 5,
                                      "estimated_total": "$26,955.60"}))
            states = [live_files(page_v="v4"), live_files()]
            http = mock.Mock()
            sleeps = []

            def get(url, timeout=None, headers=None):
                files = states[0] if len(sleeps) == 0 else states[1]
                return FakeHttp(files).get(url)

            http.get = get
            code = vl.main({"RESULT_FILE": str(rf)}, http=http, sleep=lambda s: sleeps.append(s), attempts=4)
            self.assertEqual(code, 0)
            self.assertEqual(len(sleeps), 1)
            self.assertNotIn("live_check_warning", json.loads(rf.read_text()))

    def test_main_skips_when_nothing_was_published(self):
        with tempfile.TemporaryDirectory() as d:
            rf = Path(d) / "r.json"
            rf.write_text(json.dumps({"status": "blocked", "page_url": BASE}))
            self.assertEqual(vl.main({"RESULT_FILE": str(rf)}, http=FakeHttp({})), 0)
        self.assertEqual(vl.main({}, http=FakeHttp({})), 0)


class WorkflowTest(unittest.TestCase):
    def test_verify_step_runs_after_deploy_and_before_the_write_back(self):
        text = (REPO / ".github" / "workflows" / "publish-booking.yml").read_text()
        self.assertLess(text.index("Trigger Pages deploy"), text.index("Verify the live page matches"))
        self.assertLess(text.index("Verify the live page matches"), text.index("Record the result on the Bookings record"))
        self.assertIn("python pipeline/verify_live.py", text)


if __name__ == "__main__":
    unittest.main()
