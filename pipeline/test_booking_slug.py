"""python -m unittest pipeline.test_booking_slug"""
import unittest

from pipeline import generate_booking_package as g


class BookingSlugTest(unittest.TestCase):
    def test_hanover_options_get_separate_urls(self):
        two = g.booking_slug("recP88dd2wk5XdHU3", "Hanover High School")
        four = g.booking_slug("reciijikzFlFdq3Qr", "Hanover High School")
        self.assertEqual(two, "hanover-high-school-2-day")
        self.assertEqual(four, "hanover-high-school-4-day")
        self.assertNotEqual(two, four)

    def test_tjhsst_options_get_separate_urls_and_4_day_url_is_unchanged(self):
        org = "Thomas Jefferson High School for Science and Technology (TJHSST)"
        four = g.booking_slug("rechXL7mCZJTGNofS", org)
        three = g.booking_slug("recWsjgw9VBY53vA4", org)
        self.assertEqual(four, "thomas-jefferson-high-school-for-science-and-technology-tjhsst")
        self.assertEqual(three, four + "-3-day")

    def test_other_bookings_keep_the_org_slug(self):
        self.assertEqual(g.booking_slug("recqb6DGaeJRpymL2", "Ben Gamla Charter School"),
                         "ben-gamla-charter-school")
        self.assertEqual(g.booking_slug("recXmG8ySdXrgmj85", "The Benjamin School"), "the-benjamin-school")


if __name__ == "__main__":
    unittest.main()
