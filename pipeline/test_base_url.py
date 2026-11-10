"""python -m unittest pipeline.test_base_url

PAGES_BASE_URL is the one place the public address is set. It must default to
the github.io address, honour the PAGES_BASE_URL env var (repo variable in the
publish workflow), ignore an empty value, and drop a trailing slash.
"""
import importlib
import os
import unittest
from unittest import mock

from pipeline import generate_booking_package as g

OLD = "https://reef-environmental-education-foundation.github.io/reef-program-pages"


def reload_with(value):
    env = {k: v for k, v in os.environ.items() if k != "PAGES_BASE_URL"}
    if value is not None:
        env["PAGES_BASE_URL"] = value
    with mock.patch.dict(os.environ, env, clear=True):
        return importlib.reload(g).PAGES_BASE_URL


class BaseUrlTest(unittest.TestCase):
    def tearDown(self):
        reload_with(None)

    def test_default_is_github_io(self):
        self.assertEqual(reload_with(None), OLD)

    def test_empty_variable_keeps_default(self):
        self.assertEqual(reload_with(""), OLD)
        self.assertEqual(reload_with("   "), OLD)

    def test_custom_domain_and_trailing_slash(self):
        self.assertEqual(reload_with("https://programs.reef.org"), "https://programs.reef.org")
        self.assertEqual(reload_with("https://programs.reef.org/"), "https://programs.reef.org")


if __name__ == "__main__":
    unittest.main()
