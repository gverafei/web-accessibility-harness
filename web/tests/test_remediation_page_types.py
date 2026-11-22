import tempfile
import unittest
from pathlib import Path

from routes.remediation import classified_page_type


class RemediationPageTypeTests(unittest.TestCase):
    def _page(self, markup):
        temporary = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        temporary.close()
        path = Path(temporary.name)
        self.addCleanup(path.unlink, missing_ok=True)
        path.write_text(f"<!doctype html><html><body>{markup}</body></html>", encoding="utf-8")
        return path

    def test_search_signal_wins_over_result_timestamps(self):
        path = self._page(
            '<form role="search"><input type="search"></form>'
            + "<time></time>" * 8
            + "<article></article>" * 3,
        )
        self.assertEqual(classified_page_type(path), "search")

    def test_product_signal_wins_over_generic_form_controls(self):
        path = self._page(
            '<main class="product"><span itemprop="price">$20</span>'
            '<form><input><select></select><textarea></textarea></form></main>',
        )
        self.assertEqual(classified_page_type(path), "product")

    def test_password_signal_wins_over_search_and_forms(self):
        path = self._page(
            '<form role="search"><input type="search"><input type="password"></form>',
        )
        self.assertEqual(classified_page_type(path), "authentication")

    def test_homepage_landmarks_win_over_incidental_article_elements(self):
        path = self._page(
            "<header></header><nav></nav><main><article><time></time></article></main><footer></footer>",
        )
        self.assertEqual(classified_page_type(path), "homepage")
