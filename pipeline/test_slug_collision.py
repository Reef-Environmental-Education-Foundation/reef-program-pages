"""python -m unittest pipeline.test_slug_collision"""
import tempfile
import unittest
from pathlib import Path

from pipeline import generate_booking_package as g


def publish(root, slug, record_id):
    d = Path(root) / slug
    d.mkdir()
    (d / "data.js").write_text('window.BOOKING_DATA = {"meta": {"bookingId": "%s"}};' % record_id)


class SlugCollisionTest(unittest.TestCase):
    def test_nothing_published_is_available(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(g.check_slug_available("hanover-high-school", "recAAA", Path(root)))

    def test_same_record_may_republish(self):
        with tempfile.TemporaryDirectory() as root:
            publish(root, "hanover-high-school", "recAAA")
            self.assertIsNone(g.check_slug_available("hanover-high-school", "recAAA", Path(root)))

    def test_different_record_collides(self):
        with tempfile.TemporaryDirectory() as root:
            publish(root, "hanover-high-school", "recAAA")
            self.assertEqual(g.check_slug_available("hanover-high-school", "recBBB", Path(root)), "recAAA")

    def test_page_without_booking_id_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            d = Path(root) / "legacy"
            d.mkdir()
            (d / "data.js").write_text("window.BOOKING_DATA = {};")
            self.assertIsNone(g.check_slug_available("legacy", "recBBB", Path(root)))

    def test_live_ben_gamla_page_is_recognised(self):
        self.assertEqual(g.published_booking_id("ben-gamla-charter-school"), "recqb6DGaeJRpymL2")


if __name__ == "__main__":
    unittest.main()
