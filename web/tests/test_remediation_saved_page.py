"""A saved remediation page must replay its own capture, not live resources."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

from flask import Flask
from harness.store import Store
from routes.remediation import remediation_bp


class SavedRemediationPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.datasets = self.root / 'datasets'
        self.directory = self.datasets / 'remediations' / '363'
        self.directory.mkdir(parents=True)
        self.store = Store(self.root / 'store')
        self.raw = (b'<!doctype html><html><head><link rel="stylesheet" '
                    b'href="https://example.org/main.css" integrity="old"></head>'
                    b'<body><h1>Measured page</h1></body></html>')
        self.path = self.directory / 'candidate.html'
        self.path.write_bytes(self.raw)
        source = self.store.blob(self.raw, 'candidate', 'campaign')
        css = self.store.blob(b'body { color: black }', 'captured_css', 'campaign')
        self.store.append('capture', {'captured_url': 'https://example.org/',
            'scope': 'Frozen public resources', 'assets': [{
                'url': 'https://example.org/main.css', 'sha256': css['data']['sha256'],
                'mime': 'text/css', 'artifact_id': css['id']}]}, 'campaign', 'capture')
        self.store.append('page', {'capture_id': 'capture', 'original_id': source['id']},
                          'campaign', 'sql-run-363-page')
        self.store.append('attempt', {'run_id': 'sql-run-363', 'source_id': source['id']},
                          'campaign', 'sql-run-363-attempt-0')
        self.app = Flask(__name__)
        self.app.config['HARNESS_ROOT'] = str(self.store.root)
        self.app.register_blueprint(remediation_bp)
        self.client = self.app.test_client()
        self.root_patch = patch('routes.remediation.DATASET_ROOT', self.datasets)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def upstream(self, url, **kwargs):
        path = self.datasets / unquote(urlsplit(url).path).lstrip('/')
        return Mock(status_code=200 if path.is_file() else 404,
                    content=path.read_bytes() if path.is_file() else b'',
                    headers={'Content-Type': 'text/html' if path.suffix == '.html' else 'text/css'})

    def test_navigation_rewrites_only_a_derived_copy_and_serves_bound_assets(self):
        with patch('requests.get', side_effect=self.upstream):
            opening = self.client.get('/remediation/363/dataset/candidate.html')
            self.assertEqual(opening.status_code, 302)
            self.assertIn('/remediation/363/saved/', opening.location)
            response = self.client.get(opening.location)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'/remediation/363/saved/', response.data)
            self.assertNotIn(b'https://example.org/main.css', response.data)
            self.assertNotIn(b'integrity="old"', response.data)
            self.assertEqual(self.path.read_bytes(), self.raw)
            receipt = next(self.directory.glob('.saved/*/navigation.json'))
            info = json.loads(receipt.read_text())
            self.assertEqual(info['source_sha256'], hashlib.sha256(self.raw).hexdigest())
            css_url = info['transport']['resource_map']['https://example.org/main.css']
            css = self.client.get(css_url)
            self.assertEqual(css.data, b'body { color: black }')
            self.assertEqual(css.headers['Access-Control-Allow-Origin'], '*')
            self.assertIn('sandbox', response.headers['Content-Security-Policy'])
            denied = self.client.get('/remediation/363/saved/' + receipt.parent.name + '/navigation.json')
            self.assertEqual(denied.status_code, 404)

    def test_existing_display_links_upgrade_without_changing_the_measured_html(self):
        with patch('requests.get', side_effect=self.upstream):
            opening = self.client.get('/remediation/363/dataset/candidate.html')
        receipt = next(self.directory.glob('.saved/*/navigation.json'))
        info = json.loads(receipt.read_text())
        info['version'] = 'measured-remediation-navigation-v1'
        receipt.write_text(json.dumps(info))
        response = self.client.get(opening.location)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/remediation/363/dataset/candidate.html')
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_changed_html_cannot_inherit_a_measured_source_or_capture(self):
        self.path.write_bytes(self.raw + b'<p>Unmeasured change</p>')
        with patch('requests.get') as get:
            response = self.client.get('/remediation/363/dataset/candidate.html')
        self.assertEqual(response.status_code, 409)
        get.assert_not_called()
        self.assertFalse(list(self.directory.glob('.saved/*/navigation.json')))
