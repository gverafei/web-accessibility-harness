"""Reviewer manuscripts are explicit, revalidated files outside study catalogues."""
from pathlib import Path
import tempfile
from unittest import TestCase

from flask import render_template
from main import create_app


class PaperDocumentTests(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pdf = b'%PDF-1.4\nreviewer document\n%%EOF\n'
        (self.root / 'harness.pdf').write_bytes(self.pdf)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'fixture',
            'PAPER_DOCUMENT_ROOT': str(self.root), 'SHOW_GLOBAL_SEARCH': False})
        self.client = self.app.test_client()

    def test_inline_pdf_supports_revalidation_ranges_and_replacement(self):
        response = self.client.get('/papers/harness.pdf')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.pdf)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertTrue(response.headers['Content-Disposition'].startswith('inline;'))
        self.assertEqual(response.headers['Cache-Control'], 'private, no-cache')
        unchanged = self.client.get('/papers/harness.pdf', headers={
            'If-None-Match': response.headers['ETag']})
        self.addCleanup(unchanged.close)
        self.assertEqual(unchanged.status_code, 304)
        partial = self.client.get('/papers/harness.pdf', headers={'Range': 'bytes=0-7'})
        self.addCleanup(partial.close)
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.data, self.pdf[:8])
        updated = self.pdf + b'updated version\n'
        (self.root / 'harness.pdf').write_bytes(updated)
        fresh = self.client.get('/papers/harness.pdf', headers={'If-None-Match': response.headers['ETag']})
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(fresh.data, updated)

    def test_missing_unknown_and_external_symlink_are_not_served(self):
        for path in ('/papers/dataset.pdf', '/papers/private.pdf', '/papers/../config.py.pdf'):
            self.assertEqual(self.client.get(path).status_code, 404)
        with tempfile.TemporaryDirectory() as external:
            target = Path(external) / 'private.pdf'
            target.write_bytes(self.pdf)
            (self.root / 'dataset.pdf').symlink_to(target)
            self.assertEqual(self.client.get('/papers/dataset.pdf').status_code, 404)


    def test_review_only_portal_can_open_the_same_explicit_pdf(self):
        self.app.config['REVIEW_PORTAL_ONLY'] = True
        response = self.client.get('/papers/harness.pdf')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
