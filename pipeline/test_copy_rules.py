"""python -m unittest pipeline.test_copy_rules

Standing copy rules for captured itineraries (Martha, 2026-10-30/31):
no seine netting anywhere, and the kayak activity is named
"Kayaking at Pennekamp (Mangrove Tour)", not a variant."""
import json
import re
import unittest
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


if __name__ == "__main__":
    unittest.main()
