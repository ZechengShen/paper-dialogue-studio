"""Presentation changes must not lose, execute or reinterpret research content."""
import copy
import json
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import research_pipeline as research


class ReportStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = 0
        self.closed_sections = 0
        self.heading_ids = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "section":
            self.sections += 1
        if tag == "h2":
            self.heading_ids.append(attributes.get("id"))
        if tag == "a" and attributes.get("href", "").startswith("#section-"):
            self.anchors.append(attributes["href"][1:])

    def handle_endtag(self, tag):
        if tag == "section":
            self.closed_sections += 1


class ReportDesignTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(research.read(ROOT / "examples/research-v3/research.json"))
        self.temp = tempfile.TemporaryDirectory(prefix="report-test-", dir=str(ROOT / "tests"))
        self.path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_every_section_is_kept_and_navigable(self):
        research.render(self.path, self.data)
        page = (self.path / "report.html").read_text(encoding="utf-8")
        document = ReportStructure()
        document.feed(page)
        expected = len(re.findall(r"^## ", research.markdown(self.data), re.M))
        self.assertEqual(document.sections, expected)
        self.assertEqual(document.closed_sections, expected)
        self.assertEqual(document.heading_ids, document.anchors)
        self.assertIn('id="reader-focus"', page)
        self.assertIn('id="reader-type"', page)
        self.assertIn('<dt>论文</dt><dd>1</dd>', page)
        self.assertNotRegex(page, r'<(?:script|link)[^>]+(?:src|href)="https?://')

    def test_template_tokens_in_research_are_literal(self):
        self.data["project"]["title"] = "__REPORT__ __TOC__ <script>bad()</script>"
        self.data["synthesis"]["summary"] = "__REPORT_META__ <img src=x onerror=bad()>"
        research.render(self.path, self.data)
        page = (self.path / "report.html").read_text(encoding="utf-8")
        self.assertIn('<title>__REPORT__ __TOC__ &lt;script&gt;bad()&lt;/script&gt;</title>', page)
        self.assertIn('__REPORT_META__ &lt;img src=x onerror=bad()&gt;', page)
        self.assertNotIn('<script>bad()', page)

    def test_list_and_last_section_close_without_trailing_newline(self):
        result = research.md_html('# Title\n## One\n- a\n## Two\n- b')
        self.assertEqual(result.count('<section '), 2)
        self.assertEqual(result.count('</section>'), 2)
        self.assertEqual(result.count('</ul>'), 2)
        self.assertTrue(result.endswith('</ul>\n</section>'))

    def test_reference_snapshot_has_verified_selection_metadata(self):
        data = json.loads((ROOT / "docs/design-reference-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["projects"]), 4)
        for project in data["projects"]:
            self.assertGreater(project["stars"], 10000)
            self.assertRegex(project["commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(project["url"].startswith('https://github.com/'))


if __name__ == "__main__":
    unittest.main()
