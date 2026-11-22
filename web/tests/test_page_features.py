import sys
import types
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))
database_stub = types.ModuleType("database")
database_stub.get_connection = lambda: None
sys.modules.setdefault("database", database_stub)

from backfill_page_features import extract_page_features


class PageFeatureTestCase(unittest.TestCase):
    def test_extracts_webaim_comparison_features(self):
        html = '''<!doctype html><html><body role="document"><a href="#main">Skip</a>
        <a href="/inside">Inside</a><a href="https://other.test/">Outside</a>
        <a href="/details">Read more</a><a href="/image"><img alt="Click here"></a>
        <main id="main" aria-label="Content">Hello</main></body></html>'''
        result = extract_page_features(html, "https://example.test/")
        self.assertEqual(result["same_domain_links"], 4)
        self.assertEqual(result["aria_attributes"], 1)
        self.assertTrue(result["uses_aria"])
        self.assertEqual(result["skip_links"], 1)
        self.assertEqual(result["broken_skip_links"], 0)
        self.assertEqual(result["ambiguous_links"], 2)
        self.assertTrue(result["valid_html5_doctype"])


if __name__ == "__main__":
    unittest.main()
