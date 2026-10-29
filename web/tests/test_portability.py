import importlib
import base64
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

if "database" not in sys.modules:
    database_stub = types.ModuleType("database")
    database_stub.init_db = lambda: None
    database_stub.get_connection = lambda: None
    sys.modules["database"] = database_stub

portability = importlib.import_module("result_portability")


class ResultPortabilityTestCase(unittest.TestCase):
    def test_archive_exports_observed_taxonomy_without_changing_result_columns(self):
        from warp_export import portable_manifest
        observed={'inventory_version':'observed-taxonomy-inventory-v1','opportunities':[]}
        with patch('warp_export.read_acquired',return_value=observed):
            payload,files=portable_manifest({'format':'warp-experiment','experiment':{}},
                [{'url':'https://example.org/','source_snapshot_path':None}])
        self.assertEqual(payload['results'][0]['taxonomy_inventory'],observed)
        self.assertNotIn('taxonomy_inventory',payload['results'][0]['data'])
        self.assertEqual(files,[])
        self.assertEqual(len(portability.validate_portable_payload(payload)),1)

    def test_portable_package_includes_frozen_html_evidence(self):
        self.assertIn("source_snapshot_path", portability.ARTIFACT_COLUMNS)
        self.assertIn("response_source_path", portability.ARTIFACT_COLUMNS)

    def test_url_normalization_removes_fragment_default_port_and_trailing_slash(self):
        self.assertEqual(
            portability.normalize_url("HTTPS://Example.COM:443/research/#section"),
            "https://example.com/research",
        )

    def test_missing_url_protocol_defaults_to_https(self):
        self.assertEqual(
            portability.ensure_http_scheme("www.example.com/path"),
            "https://www.example.com/path",
        )
        self.assertEqual(
            portability.normalize_url("www.example.com/path/"),
            "https://www.example.com/path",
        )
        self.assertEqual(
            portability.ensure_http_scheme("http://www.example.com"),
            "http://www.example.com",
        )

    def test_evaluation_signature_changes_with_research_protocol(self):
        settings = {
            "wave_report_type": "2", "page_load_timeout_ms": "60000",
            "network_idle_timeout_ms": "15000", "page_settle_delay_ms": "2000",
            "dom_stability_window_ms": "1500", "dom_stability_timeout_ms": "10000",
            "enable_lazy_load_scroll": "true", "scroll_step_px": "700",
            "scroll_delay_ms": "350", "max_scroll_steps": "40",
        }
        baseline = portability.evaluation_signature(
            settings, False, False, None, None, "wcag22aa"
        )
        changed = dict(settings, scroll_step_px="900")
        self.assertNotEqual(
            baseline,
            portability.evaluation_signature(
                changed, False, False, None, None, "wcag22aa"
            ),
        )

    def test_portable_payload_validation_is_all_or_nothing(self):
        valid = {
            "format": "warp-experiment", "version": 3, "experiment": {}, "environment": [],
            "results": [{"data": {"url": "https://example.org/", "status": "completed"},
                         "artifacts": {"axe_raw_path": {"filename": "axe.json", "base64": base64.b64encode(b"{}").decode()}}}],
        }
        self.assertEqual(len(portability.validate_portable_payload(valid)), 1)

        invalid = dict(valid)
        invalid["results"] = list(valid["results"]) + [
            {"data": {"url": "not-a-url"}, "artifacts": {}}
        ]
        with self.assertRaises(ValueError):
            portability.validate_portable_payload(invalid)

    def test_portable_payload_rejects_corrupt_embedded_artifact(self):
        payload = {
            "format": "warp-experiment", "version": 3, "experiment": {}, "environment": [],
            "results": [{"data": {"url": "https://example.org/"},
                         "artifacts": {"axe_raw_path": {"filename": "axe.json", "base64": "not base64!"}}}],
        }
        with self.assertRaises(ValueError):
            portability.validate_portable_payload(payload)



if __name__ == "__main__":
    unittest.main()
