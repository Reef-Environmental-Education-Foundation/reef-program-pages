"""python -m unittest pipeline.test_version_marker"""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import write_version_marker as wvm

REC = "recAAAAAAAAAAAAAA"


def publish(root, slug, rec=REC, version=None):
    d = Path(root) / slug
    d.mkdir(parents=True)
    (d / "data.js").write_text('window.BOOKING_DATA = {"proposal": {"meta": {"bookingId": "%s"}}};' % rec)
    if version is not None:
        (d / "version.json").write_text(json.dumps({"currentVersion": version}))
    return d


class MarkerTest(unittest.TestCase):
    def test_raises_the_marker_for_a_published_page(self):
        with tempfile.TemporaryDirectory() as r:
            d = publish(r, "some-school", version=2)
            self.assertIsNotNone(wvm.write_marker(REC, "Some School", 3, r))
            self.assertEqual(json.loads((d / "version.json").read_text())["currentVersion"], 3)

    def test_unchanged_version_writes_nothing(self):
        with tempfile.TemporaryDirectory() as r:
            publish(r, "some-school", version=3)
            self.assertIsNone(wvm.write_marker(REC, "Some School", 3, r))

    def test_unpublished_booking_is_ignored(self):
        with tempfile.TemporaryDirectory() as r:
            self.assertIsNone(wvm.write_marker(REC, "Some School", 3, r))

    def test_another_bookings_page_is_never_marked(self):
        with tempfile.TemporaryDirectory() as r:
            publish(r, "some-school", rec="recBBBBBBBBBBBBBB", version=1)
            self.assertIsNone(wvm.write_marker(REC, "Some School", 5, r))

    def test_hanover_options_use_their_own_slugs(self):
        with tempfile.TemporaryDirectory() as r:
            d2 = publish(r, "hanover-high-school-2-day", rec="recP88dd2wk5XdHU3", version=1)
            d4 = publish(r, "hanover-high-school-4-day", rec="reciijikzFlFdq3Qr", version=1)
            wvm.write_marker("recP88dd2wk5XdHU3", "Hanover High School", 2, r)
            self.assertEqual(json.loads((d2 / "version.json").read_text())["currentVersion"], 2)
            self.assertEqual(json.loads((d4 / "version.json").read_text())["currentVersion"], 1)

    def test_blank_version_means_one(self):
        with tempfile.TemporaryDirectory() as r:
            d = publish(r, "some-school", version=4)
            wvm.write_marker(REC, "Some School", None, r)
            self.assertEqual(json.loads((d / "version.json").read_text())["currentVersion"], 1)


if __name__ == "__main__":
    unittest.main()
