"""python -m unittest pipeline.test_copy_rules

Standing copy rules for captured itineraries (Martha, 2026-10-30/31):
no seine netting anywhere, and the kayak activity is named
"Kayaking at Pennekamp (Mangrove Tour)", not a variant."""
import json
import re
import unittest
import zipfile
from pathlib import Path

ITINERARIES = Path(__file__).parent / "itineraries"
KAYAK_NAME = "Kayaking at Pennekamp (Mangrove Tour)"


def texts(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k != "sourceNote":          # internal, never rendered
                yield from texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from texts(v)


class CopyRulesTest(unittest.TestCase):
    def test_no_seine_netting_in_rendered_text(self):
        for path in sorted(ITINERARIES.glob("rec*.json")):
            for text in texts(json.loads(path.read_text())):
                self.assertNotRegex(text, r"(?i)\bseine", f"{path.name}: {text[:60]}")

    def test_kayak_titles_use_the_standard_name(self):
        for path in sorted(ITINERARIES.glob("rec*.json")):
            data = json.loads(path.read_text())
            days = data["days"] if isinstance(data, dict) else data
            for day in days:
                for block in day.get("blocks", []):
                    if re.search(r"(?i)kayak", block.get("title", "")):
                        self.assertEqual(block["title"], KAYAK_NAME, path.name)


REPO = Path(__file__).parent.parent
SEINING_RE = re.compile(r"(?i)\bsein(?:e|es|ed|ing)\b")
# REEF does not do fish seining (Martha, 2026-11-02): it must not appear in any
# option list, activity list, template, copy file or generated page.
# Generated pages that already carry it are listed here so the test still passes;
# the entry goes away when that booking is republished after Airtable is fixed.
KNOWN_GENERATED_SEINING = {"the-benjamin-school"}


def repo_text_files():
    skip_dirs = {".git", "bookings", "node_modules", "__pycache__"}
    for path in REPO.rglob("*"):
        if not path.is_file() or skip_dirs & set(path.relative_to(REPO).parts):
            continue
        # publish_support.py holds the validation guard, which has to name the word.
        if path.name.startswith("test_") or path.name == "publish_support.py" \
                or path.suffix in {".pyc", ".png", ".jpg", ".jpeg", ".docx"}:
            continue
        yield path


class NoSeiningTest(unittest.TestCase):
    def test_no_seining_in_source_content_templates_or_assets(self):
        for path in repo_text_files():
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            self.assertIsNone(SEINING_RE.search(text), str(path.relative_to(REPO)))

    def test_no_seining_in_the_contract_template(self):
        for path in (REPO / "pipeline" / "templates").glob("*.docx"):
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf8", "ignore")
            self.assertIsNone(SEINING_RE.search(re.sub(r"<[^>]+>", "", xml)), path.name)

    def test_no_seining_in_generated_pages_except_known_ones(self):
        for page in sorted((REPO / "bookings").glob("*/**/*.js")) + sorted((REPO / "bookings").glob("*/**/*.html")):
            slug = page.relative_to(REPO / "bookings").parts[0]
            if slug in KNOWN_GENERATED_SEINING:
                continue
            self.assertIsNone(SEINING_RE.search(page.read_text()), str(page.relative_to(REPO)))

    def test_the_known_exception_list_does_not_go_stale(self):
        for slug in KNOWN_GENERATED_SEINING:
            hits = [p for p in (REPO / "bookings" / slug).rglob("*") if p.is_file() and p.suffix in {".js", ".html"}
                    and SEINING_RE.search(p.read_text())]
            self.assertTrue(hits, f"{slug} no longer mentions seining: remove it from KNOWN_GENERATED_SEINING")


if __name__ == "__main__":
    unittest.main()
