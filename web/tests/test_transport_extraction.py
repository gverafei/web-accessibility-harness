import unittest
import json
import tempfile
from pathlib import Path
from remediation_baseline import baseline_candidate


class TransportExtractionTests(unittest.TestCase):
    def test_refusal_with_quoted_document_tokens_is_not_a_page(self):
        raw = ("I cannot return the complete page from `<!doctype html>` through `</html>`.\n"
               "Please send the navigation section so I can correct its <nav> element.")
        candidate, evidence = baseline_candidate(raw, '<html>original</html>')
        self.assertEqual(candidate, raw)
        self.assertFalse(evidence['evaluable'])

    def test_unique_fenced_fragment_remains_evaluable_despite_prose(self):
        raw = 'Try this change:\n```html\n<input aria-label="Search">\n```\nApply it yourself.'
        candidate, evidence = baseline_candidate(raw, '<main>original</main>')
        self.assertEqual(candidate, '<input aria-label="Search">')
        self.assertTrue(evidence['evaluable'])

    def test_transport_unwrapping_keeps_broken_markup(self):
        cases = [('<html><body><p>unfinished', '<html><body><p>unfinished'),
                 ('```html\n<input aria-label="Search">\n```', '<input aria-label="Search">'),
                 ('```html\n<main>truncated', '<main>truncated'),
                 ('<!-- retained comment -->\n<main>text</main>', '<!-- retained comment -->\n<main>text</main>')]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                candidate, evidence = baseline_candidate(raw, '<html>original</html>')
                self.assertEqual(candidate, expected)
                self.assertTrue(evidence['evaluable'])

    def test_raw_document_is_not_sliced_at_an_embedded_closing_tag(self):
        raw = '<html><body>one</body></html>\n<p>trailing broken fragment</p>'
        candidate, evidence = baseline_candidate(raw, 'original')
        self.assertEqual(candidate, raw)
        self.assertTrue(evidence['evaluable'])

    def test_report_uses_the_recorded_non_page_classification(self):
        from remediation_output_format import recorded_output_format
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'remediations' / '1'
            root.mkdir(parents=True)
            (root / 'response.txt').write_text('Cannot reproduce `<html>` today.')
            (root / 'baseline-output.json').write_text(json.dumps({'evaluable': False}))
            self.assertEqual(recorded_output_format(root / 'response.txt', 1, directory), 'no-html-document')


if __name__ == '__main__':
    unittest.main()
