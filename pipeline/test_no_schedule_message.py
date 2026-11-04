"""python -m unittest pipeline.test_no_schedule_message"""
import unittest

from pipeline import generate_booking_package as g


class NoScheduleMessageTest(unittest.TestCase):
    def test_new_booking_is_told_to_use_the_itinerary_editor(self):
        with self.assertRaises(g.NoItineraryCaptured) as cm:
            g.load_itinerary("recNoSuchBooking00", {"schedule_count": 0})
        msg = str(cm.exception)
        self.assertIn("Add schedule rows in the Itinerary Editor first.", msg)
        self.assertNotIn("JSON", msg)
        self.assertIn("does not fabricate", msg)


if __name__ == "__main__":
    unittest.main()
