import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from harness.contracts import ContractError
from harness.remediation_bridge import Bridge


class AdmittedWorkerSourceTests(unittest.TestCase):
    def bridge(self, original, artifact):
        bridge = Bridge.__new__(Bridge)
        bridge.original = original
        bridge.page = {'data': {'original_id': 'admitted-source'}}
        bridge.store = Mock()
        bridge.store.read_blob.return_value = artifact
        return bridge

    def test_recovered_dom_replaces_old_response_before_worker_input(self):
        admitted = '<html><body><button>Captured control</button></body></html>'
        bridge = self.bridge(admitted, admitted.encode())
        with tempfile.TemporaryDirectory() as directory:
            source_file = Path(directory) / 'source.html'
            source_file.write_text('<html><body>Response shell</body></html>')
            worker_input = bridge.prepared_source(source_file)
            self.assertEqual(worker_input, admitted)
            self.assertEqual(source_file.read_bytes(), admitted.encode())
        bridge.store.read_blob.assert_called_once_with('admitted-source')
        bridge.store.append.assert_not_called()

    def test_mismatched_admitted_artifact_blocks_before_replacing_input(self):
        bridge = self.bridge('different DOM', b'admitted DOM')
        with tempfile.TemporaryDirectory() as directory:
            source_file = Path(directory) / 'source.html'
            source_file.write_bytes(b'previous input')
            with self.assertRaises(ContractError):
                bridge.prepared_source(source_file)
            self.assertEqual(source_file.read_bytes(), b'previous input')

    def test_unchanged_response_keeps_unicode_bytes(self):
        admitted = '<p>Información accesible</p>'
        bridge = self.bridge(admitted, admitted.encode())
        with tempfile.TemporaryDirectory() as directory:
            source_file = Path(directory) / 'source.html'
            self.assertEqual(bridge.prepared_source(source_file), admitted)
            self.assertEqual(source_file.read_bytes(), admitted.encode())
