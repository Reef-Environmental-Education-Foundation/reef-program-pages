"""python -m unittest pipeline.test_cache_bust"""
import re
import tempfile
import unittest
from pathlib import Path

from pipeline import generate_booking_package as g


def versioned(html_shell, data_text):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.js"
        p.write_text(data_text)
        return g.cache_busted(html_shell, p)


class CacheBustTest(unittest.TestCase):
    def test_main_and_share_shells_get_a_content_hash(self):
        for shell in (g.BOOKING_PAGE_SHELL_TEMPLATE.format(title="t", robots=""),
                      g.SHARE_PAGE_SHELL_TEMPLATE.format(title="t")):
            out = versioned(shell, "window.BOOKING_DATA = {};")
            self.assertRegex(out, r'<script src="data\.js\?v=[0-9a-f]{12}"></script>')
            self.assertIn("render.js", out)

    def test_new_content_gives_a_new_url(self):
        shell = g.SHARE_PAGE_SHELL_TEMPLATE.format(title="t")
        a = re.search(r"v=([0-9a-f]+)", versioned(shell, "v2")).group(1)
        b = re.search(r"v=([0-9a-f]+)", versioned(shell, "v5")).group(1)
        self.assertNotEqual(a, b)
        self.assertEqual(a, re.search(r"v=([0-9a-f]+)", versioned(shell, "v2")).group(1))

    def test_render_js_and_styles_css_are_versioned_by_their_content(self):
        shell = g.BOOKING_PAGE_SHELL_TEMPLATE.format(title="t", robots="")
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as a:
            data = Path(d) / "data.js"
            data.write_text("x")
            (Path(a) / "render.js").write_text("one")
            (Path(a) / "styles.css").write_text("css")
            first = g.cache_busted(shell, data, a)
            self.assertRegex(first, r'assets/render\.js\?v=[0-9a-f]{12}"')
            self.assertRegex(first, r'assets/styles\.css\?v=[0-9a-f]{12}"')
            (Path(a) / "render.js").write_text("two")
            second = g.cache_busted(shell, data, a)
            self.assertNotEqual(re.search(r"render\.js\?v=(\w+)", first).group(1),
                                re.search(r"render\.js\?v=(\w+)", second).group(1))
            self.assertEqual(re.search(r"styles\.css\?v=(\w+)", first).group(1),
                             re.search(r"styles\.css\?v=(\w+)", second).group(1))

    def test_real_assets_are_found_for_main_and_share_shells(self):
        for shell in (g.BOOKING_PAGE_SHELL_TEMPLATE.format(title="t", robots=""),
                      g.SHARE_PAGE_SHELL_TEMPLATE.format(title="t")):
            out = versioned(shell, "x")
            self.assertRegex(out, r'render\.js\?v=[0-9a-f]{12}')
            self.assertRegex(out, r'styles\.css\?v=[0-9a-f]{12}')

    def test_templates_keep_the_plain_tag_the_internal_preview_replaces(self):
        self.assertIn('<script src="data.js"></script>', g.BOOKING_PAGE_SHELL_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
