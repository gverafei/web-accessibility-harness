"""The Data adapter must use native acquisition, not the legacy capture route."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness.contracts import ContractError
from harness.environment import Environment
from harness.store import Store


class VerifiedNativeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / 'store')
        self.environment = Environment(self.store, results=self.root)
        self.source = self.root / 'response.html'
        self.rendered = self.root / 'rendered.html'
        self.source.write_text('<html><body><main>Response fixture</main></body></html>')
        self.rendered.write_text('<html><body><main>Rendered fixture</main></body></html>')
        self.screenshot = self.root / 'page.jpg'
        self.screenshot.write_bytes(b'synthetic image')
        self.package = Path(str(self.screenshot) + '.resources.json')
        self.payload = {'version': 'native-resource-package-v4', 'requested_url': 'https://fixture.example/',
            'captured_url': 'https://fixture.example/', 'network': self.source.read_text(),
            'rendered': self.rendered.read_text(), 'assets': [], 'visible': {},
            'native_control_reference': {'version': 'observed-native-control-state-v1', 'records': []}}
        self.package.write_text(json.dumps(self.payload))
        self.raw = self.root / 'audit.json'
        self.raw.write_text('{}')
        self.result = {'results': [{'status': 'completed', 'url': 'https://fixture.example/',
            'screenshot_path': str(self.screenshot), 'response_source_path': str(self.source),
            'source_snapshot_path': str(self.rendered), 'axe': {'raw_path': str(self.raw), 'wcag_violations': 0},
            'lighthouse': {'raw_path': str(self.raw), 'accessibility_score': 100}}]}

    def test_native_endpoint_freezes_complete_evidence_without_wave_or_score_filter(self):
        with patch.object(self.environment, 'capture_request', return_value=self.result) as request:
            capture = self.environment.capture_verified('https://fixture.example/', 'campaign', 'capture')
        args = request.call_args.args
        self.assertEqual(args[0], '/evaluate')
        self.assertEqual(args[4]['urls'], ['https://fixture.example/'])
        self.assertFalse(args[4]['include_wave'])
        self.assertTrue(args[4]['quality_policy']['require_complete_evidence'])
        self.assertNotIn('min_lighthouse', json.dumps(args[4]))
        self.assertEqual(capture['data']['native_control_reference'], self.payload['native_control_reference'])
        self.assertEqual(capture['data']['package_sha256'], hashlib.sha256(self.package.read_bytes()).hexdigest())
        self.assertEqual(self.store.read_blob(capture['data']['network_id']), self.source.read_bytes())
        self.assertEqual(self.store.read_blob(capture['data']['rendered_id']), self.rendered.read_bytes())
        measurement = self.store.get(capture['data']['acquisition_measurement_id'])
        self.assertEqual(measurement['data']['axe'], 0)
        self.assertEqual(measurement['data']['lighthouse'], 100)

    def test_missing_native_package_cannot_fall_back_to_legacy_capture(self):
        self.package.unlink()
        with patch.object(self.environment, 'capture_request', return_value=self.result), patch.object(self.environment, 'capture') as legacy:
            with self.assertRaises((ContractError, FileNotFoundError)):
                self.environment.capture_verified('https://fixture.example/', 'campaign', 'capture')
            legacy.assert_not_called()

    def test_cross_state_document_mismatch_is_not_admitted(self):
        self.rendered.write_text('<html>Different later state</html>')
        with patch.object(self.environment, 'capture_request', return_value=self.result):
            with self.assertRaisesRegex(ContractError, 'document'):
                self.environment.capture_verified('https://fixture.example/', 'campaign', 'capture')

    def test_failed_native_acquisition_is_retained_without_fallback(self):
        with patch.object(self.environment, 'capture_request', return_value={'results': [{'status': 'failed', 'error': 'Synthetic failure'}]}):
            with self.assertRaisesRegex(ContractError, 'Synthetic failure'):
                self.environment.capture_verified('https://fixture.example/', 'campaign', 'capture')
