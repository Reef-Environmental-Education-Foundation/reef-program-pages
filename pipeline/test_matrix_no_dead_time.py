"""python -m unittest pipeline.test_matrix_no_dead_time

2026-11-07: the rotation matrix never shows idle time. Gaps up to the configured minutes are
absorbed by visually extending the earlier block (printed times unchanged); longer gaps show
one neutral "Settle in and freshen up" block with no time; nothing is added after the last
block of the last day. No hatched cell class and no "Transition" label in school-facing HTML."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generate_booking_package as g  # noqa: E402

REPO = Path(__file__).parent.parent


def render(rot):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory() as td:
        rp = Path(td) / "rot.json"
        rp.write_text(json.dumps(rot))
        return subprocess.run([node, str(REPO / "pipeline" / "rot_render_harness.js"),
                               str(REPO / "assets" / "render.js"), str(rp)],
                              capture_output=True, text=True, check=True).stdout


def rotation(assignments, shared=(), start="09:00", end="17:00", **extra):
    rot = {"startTime": start, "endTime": end, "slotMinutes": 15,
           "cohorts": [{"id": "A", "label": "Cohort A", "size": None}],
           "stations": [{"id": "x", "name": "Fish ID", "short": "Fish ID", "location": "REEF", "type": "experience", "color": 1},
                        {"id": "y", "name": "Kayak", "short": "Kayak", "location": "Park", "type": "experience", "color": 5},
                        {"id": "d", "name": "Dinner", "short": "Dinner", "location": "Hotel", "type": "meal", "color": 4}],
           "assignments": [dict(cohort="A", station=s, start=a, end=b) for s, a, b in assignments]}
    if shared:
        rot["shared"] = [dict(station=s, start=a, end=b) for s, a, b in shared]
    rot.update(extra)
    return rot


def cell(html, text):
    """(grid-column start, end) of the first desktop cell containing `text`."""
    m = re.search(r'class="rot-cell[^"]*" style="grid-row:\d+;grid-column:(\d+) / (\d+);">(?:(?!</div>).)*?' + re.escape(text), html)
    return (int(m.group(1)), int(m.group(2))) if m else None


class GapRendering(unittest.TestCase):
    def test_gap_up_to_the_limit_extends_the_earlier_block_and_keeps_its_times(self):
        html = render(rotation([("x", "09:00", "10:00"), ("y", "11:00", "12:00")], end="12:00"))   # exactly 60 min
        self.assertEqual(cell(html, "Fish ID"), (2, 10))          # 9:00 -> 11:00 on a 15-minute grid
        self.assertIn("9:00–10:00 AM", html)                       # printed time unchanged
        self.assertNotIn("Settle in", html)

    def test_gap_over_the_limit_gets_a_settle_block_with_no_time(self):
        html = render(rotation([("x", "09:00", "10:00"), ("y", "11:15", "12:15")], end="12:15"))   # 75 min
        self.assertIn("Settle in and freshen up", html)
        self.assertEqual(cell(html, "Fish ID"), (2, 6))            # earlier block NOT stretched
        m = re.search(r'rot-settle[^>]*>(.*?)</div>', html)
        self.assertNotRegex(m.group(1), r"\d:\d\d")                # no time on the settle block

    def test_settle_block_borrows_the_colour_of_the_meal_after_it(self):
        html = render(rotation([("x", "09:00", "10:00")], shared=[("d", "13:00", "14:00")], end="14:00"))
        self.assertRegex(html, r'rot-cell rot-settle rot-c4')      # Dinner is colour 4
        html = render(rotation([("x", "09:00", "10:00"), ("y", "13:00", "14:00")], end="14:00"))
        self.assertRegex(html, r'rot-cell rot-settle rot-neutral')   # next block is an experience

    def test_threshold_and_label_are_config_values(self):
        rot = rotation([("x", "09:00", "10:00"), ("y", "10:45", "11:45")], end="11:45")          # 45 min
        self.assertNotIn("Settle in", render(rot))                          # default 60 absorbs it
        rot.update(gapFillMinutes=30, settleLabel="Rest and refresh")
        html = render(rot)
        self.assertIn("Rest and refresh", html)
        self.assertNotIn("Settle in and freshen up", html)

    def test_nothing_is_added_after_the_last_block_of_the_last_day(self):
        html = render(rotation([("x", "09:00", "10:00")], end="17:00", departure={"time": "17:00", "label": "Departure", "note": ""}))
        self.assertNotIn("Settle in", html)
        self.assertEqual(cell(html, "Fish ID"), (2, 6))

    def test_multi_day_first_day_gets_settle_block_last_day_does_not(self):
        rot = rotation([("x", "10:00", "11:00"), ("y", "09:00", "10:00")], end="19:00")
        rot["assignments"][0]["day"] = 1
        rot["assignments"][1]["day"] = 2
        rot["days"] = [{"day": 1, "label": "Day 1", "startTime": "10:00", "endTime": "19:00"},
                       {"day": 2, "label": "Day 2", "startTime": "09:00", "endTime": "17:00",
                        "departure": {"time": "17:00", "label": "Departure", "note": ""}}]
        html = render(rot)
        self.assertEqual(html.count("Settle in and freshen up"), 2)   # Day 1 once (desktop + phone grids); Day 2 never

    def test_no_hatched_cells_and_no_transition_label_in_school_facing_html(self):
        for rot in (rotation([("x", "09:00", "10:00"), ("y", "13:00", "14:00")], end="17:00"),
                    rotation([("x", "09:00", "10:00"), ("y", "10:15", "11:00")], end="11:00")):
            html = render(rot)
            self.assertNotIn("rot-gap", html)
            self.assertNotIn("rc-gap-label", html)
            self.assertNotRegex(html, r"(?i)transition")

    def test_renderer_and_styles_have_no_hatch_or_transition_code(self):
        js = (REPO / "assets" / "render.js").read_text()
        css = (REPO / "assets" / "styles.css").read_text()
        for src in (js, css):
            self.assertNotIn("rot-gap", src)
            self.assertNotIn("rc-gap-label", src)
            self.assertNotIn("repeating-linear-gradient", src[src.index(".rot-cell"):src.index(".rot-cell") + 1500] if ".rot-cell" in src else "")
        self.assertNotIn('"Transition"', js)

    def test_the_generator_supplies_the_defaults(self):
        self.assertEqual(g.ROTATION_GAP_FILL_MINUTES, 60)
        self.assertEqual(g.ROTATION_SETTLE_LABEL, "Settle in and freshen up")
        self.assertIn('rot.setdefault("gapFillMinutes", ROTATION_GAP_FILL_MINUTES)',
                      (REPO / "pipeline" / "generate_booking_package.py").read_text())

    def test_settle_label_passes_the_school_facing_wording_guard(self):
        import publish_support as ps
        self.assertEqual(ps.internal_wording_hits({"label": g.ROTATION_SETTLE_LABEL}), [])


if __name__ == "__main__":
    unittest.main()
