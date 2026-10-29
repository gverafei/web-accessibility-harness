"""Dataset navigation retains exact documents and the internal server boundary."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from routes.remediation import remediation_bp


class DatasetNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'remediations' / '363'
        self.directory.mkdir(parents=True)
        self.document = b'<!doctype html><html><body>Saved candidate</body></html>'
        (self.directory / 'candidate.html').write_bytes(self.document)
        self.app = Flask(__name__)
        self.app.register_blueprint(remediation_bp)
        self.client = self.app.test_client()
        self.patch_root = patch('routes.remediation.DATASET_ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def test_navigation_uses_dataset_server_and_retains_bytes_in_an_isolated_origin(self):
        upstream = Mock(status_code=200, content=self.document,
                        headers={'Content-Type': 'text/html; charset=utf-8'})
        with patch('requests.get', return_value=upstream) as get:
            response = self.client.get('/remediation/363/dataset/candidate.html')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.document)
        self.assertEqual(get.call_args.args[0], 'http://dataset-server:8080/remediations/363/candidate.html')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertIn('sandbox', response.headers['Content-Security-Policy'])
        self.assertNotIn('allow-same-origin', response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_other_run_and_path_traversal_do_not_reach_dataset_server(self):
        outside = self.root / 'remediations' / '364'
        outside.mkdir()
        (outside / 'candidate.html').write_bytes(self.document)
        with patch('requests.get') as get:
            response = self.client.get('/remediation/363/dataset/../364/candidate.html')
        self.assertEqual(response.status_code, 404)
        get.assert_not_called()

    def test_page_link_resolves_only_the_candidate_belonging_to_the_run(self):
        cursor = Mock()
        cursor.fetchone.return_value = {'output_path': str(self.directory / 'candidate.html')}
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch('routes.remediation.get_connection', return_value=connection):
            response = self.client.get('/remediation/363/iterations/455/page')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/remediation/363/dataset/candidate.html'))
        self.assertEqual(cursor.execute.call_args.args[1], (363, 455))
        cursor.fetchone.return_value = {'output_path': str(self.root / 'remediations/364/candidate.html')}
        with patch('routes.remediation.get_connection', return_value=connection):
            response = self.client.get('/remediation/363/iterations/455/page')
        self.assertEqual(response.status_code, 404)

    def test_original_prefers_the_same_frozen_baseline_used_for_measurement(self):
        (self.directory / 'source-baseline.html').write_bytes(self.document)
        cursor = Mock()
        cursor.fetchone.return_value = {'response_source_path': '/absent-source'}
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch('routes.remediation.get_connection', return_value=connection):
            response = self.client.get('/remediation/363/original/page')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/remediation/363/dataset/source-baseline.html'))
