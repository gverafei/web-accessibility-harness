"""Original dynamic acquisitions and frozen evidence have distinct policies."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('artifact_server', Path(__file__).resolve().parents[2] / 'dataset_server/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class ArtifactPolicyTests(unittest.TestCase):
    def test_frozen_harness_cannot_enable_external_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'harness').mkdir()
            (root/'harness/.warp-dataset.json').write_text(json.dumps({'resource_policy':'external'}))
            self.assertEqual(server.resource_csp(root,'/harness/capture/index.html'),server.ISOLATED_CSP)

    def test_original_acquisition_declared_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'remediations').mkdir()
            self.assertIn("connect-src 'self'",server.resource_csp(root,'/remediations/1/index.html'))
            (root/'remediations/.warp-dataset.json').write_text(json.dumps({'resource_policy':'external'}))
            self.assertIsNone(server.resource_csp(root,'/remediations/1/index.html'))
            self.assertIsNotNone(server.resource_csp(root,'/%2e%2e/remediations/index.html'))
