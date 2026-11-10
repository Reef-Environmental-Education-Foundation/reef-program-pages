"""python -m unittest pipeline.test_smoke_check"""
import unittest

from pipeline import smoke_check as s

BASE = "https://programs.reef.org"


class JudgeTest(unittest.TestCase):
    def test_200_is_healthy(self):
        self.assertIsNone(s.judge(200, ""))

    def test_github_io_redirect_is_named(self):
        p = s.judge(301, "https://reef-environmental-education-foundation.github.io/reef-program-pages/")
        self.assertIn("github.io", p)

    def test_other_redirect_fails(self):
        self.assertIn("redirects", s.judge(302, "https://example.com/"))

    def test_non_200_fails(self):
        self.assertIn("404", s.judge(404, ""))
        self.assertIn("failed", s.judge(0, "URLError: boom"))


class RunTest(unittest.TestCase):
    def test_urls_are_root_plus_each_slug(self):
        self.assertEqual(s.build_urls(BASE + "/", ["a-b"]), [BASE + "/", BASE + "/bookings/a-b/"])

    def test_all_ok(self):
        r = s.run(BASE, ["a"], 1, 0, fetcher=lambda u: (200, ""))
        self.assertTrue(all(p is None for _, p in r))
        self.assertIn("All 2 URLs", s.summary(r))

    def test_failure_is_reported_per_url(self):
        def f(u):
            return (404, "") if u.endswith("/bookings/a/") else (200, "")
        r = s.run(BASE, ["a"], 2, 0, fetcher=f, sleep=lambda _: None)
        self.assertEqual([p is not None for _, p in r], [False, True])
        self.assertIn("FAILED", s.summary(r))

    def test_retry_then_pass(self):
        calls = []
        def f(u):
            calls.append(u)
            return (404, "") if len(calls) < 3 else (200, "")
        self.assertIsNone(s.check(BASE + "/", 5, 0, fetcher=f, sleep=lambda _: None))

    def test_bad_slug_rejected(self):
        with self.assertRaises(ValueError):
            s.run(BASE, ["../x"], 1, 0, fetcher=lambda u: (200, ""))


if __name__ == "__main__":
    unittest.main()
