"""Post-measurement reporting must tolerate an explicitly unavailable bounded view."""
import unittest
from remediation_patch_prompt import prompt_metadata
from remediation_approaches import APPROACHES

class PatchContextReportingTests(unittest.TestCase):
    def test_oversized_view_is_unknown_not_a_reporting_exception_or_invented_version(self):
        result = prompt_metadata('{}', APPROACHES[0])
        self.assertIsNone(result['context_version'])
        self.assertEqual(result['context_status'], 'unavailable')
        self.assertEqual(result['operation_level'], APPROACHES[0].step)

    def test_existing_metadata_remains_identical(self):
        from remediation_patch_prompt import VERSION
        result = prompt_metadata('{"version":"grounded-target-coverage-v1"}', APPROACHES[0])
        self.assertEqual(result, {'version': VERSION, 'context_version': 'grounded-target-coverage-v1',
                                 'operation_level': APPROACHES[0].step, 'max_operations': APPROACHES[0].max_operations})
