"""python -m unittest pipeline.test_noindex

Every page under bookings/ must be kept out of search results:
  - generated main page shell and share page shell carry the robots meta;
  - the generator writes it for real (non-test) bookings too;
  - render.js adds it at load for already-published pages that lack it, and
    never adds a second one.
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from pipeline import generate_booking_package as g

ROOT = Path(__file__).resolve().parent.parent
META = '<meta name="robots" content="noindex, nofollow">'


class GeneratedShellsTest(unittest.TestCase):
    def test_main_shell_has_noindex(self):
        self.assertIn(META, g.BOOKING_PAGE_SHELL_TEMPLATE.format(title="t", robots=g.NOINDEX_META))

    def test_share_shell_has_noindex(self):
        self.assertIn(META, g.SHARE_PAGE_SHELL_TEMPLATE.format(title="t"))

    def test_real_bookings_are_not_exempt(self):
        src = (ROOT / "pipeline" / "generate_booking_package.py").read_text()
        call = re.search(r"BOOKING_PAGE_SHELL_TEMPLATE\.format\(\s*title=page_title,(.*?)\), booking_dir", src, re.S).group(1)
        self.assertIn("robots=NOINDEX_META", call)
        self.assertNotIn("is_test_org", call)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RenderJsLoadTimeTest(unittest.TestCase):
    def run_stub(self, has_robots):
        render = (ROOT / "assets" / "render.js").read_text()
        start = render.index("(function ensureNoindex()")
        end = render.index("})();", start) + len("})();")
        js = f"""
        const added = [];
        const document = {{
          head: {{ appendChild: m => added.push(m) }},
          querySelector: () => {has_robots} ? {{}} : null,
          createElement: () => {{ const a = {{}}; return {{ setAttribute: (k, v) => a[k] = v, a }}; }},
        }};
        {render[start:end]}
        console.log(JSON.stringify(added.map(m => m.a)));
        """
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()

    def test_adds_tag_when_missing(self):
        self.assertEqual(self.run_stub("false"), '[{"name":"robots","content":"noindex, nofollow"}]')

    def test_no_duplicate_when_present(self):
        self.assertEqual(self.run_stub("true"), "[]")

    def test_runs_before_init(self):
        render = (ROOT / "assets" / "render.js").read_text()
        self.assertLess(render.index("ensureNoindex"), render.index("function el("))


if __name__ == "__main__":
    unittest.main()
