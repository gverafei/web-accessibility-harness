import unittest
from unittest.mock import Mock
from remediation_completion import completion_status, achieved_feedback, retain_interrupted_result
from main import app


class CompletionTests(unittest.TestCase):
    def test_provider_error_preserves_previously_evaluated_result(self):
        self.assertTrue(retain_interrupted_result(42,'automated',True))
        self.assertFalse(retain_interrupted_result(None,'automated',True))
        self.assertFalse(retain_interrupted_result(42,'strict',True))
        self.assertFalse(retain_interrupted_result(42,'automated',False))

    def test_achieved_targets_do_not_claim_zero_remaining_issues(self):
        feedback=achieved_feedback([{'rule':'color-contrast'}],[{'audit':'color-contrast'}])
        self.assertIn('color-contrast',feedback)
        self.assertIn('does not certify',feedback)
        self.assertNotIn('No automated failures remain',feedback)
        self.assertIn('Lighthouse audit findings: 1',feedback)

    def test_unmet_targets_do_not_reject_an_evaluated_result(self):
        self.assertEqual(completion_status(None, 3, 'automated', False), 'completed_with_warnings')

    def test_no_executable_candidate_is_still_a_failure(self):
        self.assertEqual(completion_status(None, 0, 'automated', False), 'failed')

    def test_target_attainment_remains_distinguishable(self):
        self.assertEqual(completion_status(42, 1, 'automated', True), 'accepted')

    def test_explicit_specialist_gate_is_not_bypassed(self):
        self.assertEqual(completion_status(None, 2, 'comprehensive', True), 'review_not_achieved')
