import unittest
from remediation_completion import measurable_noop, unchanged_proposal


class MeasurableNoopTests(unittest.TestCase):
    def test_valid_empty_plan_is_recognized_without_rejected_operations(self):
        self.assertTrue(measurable_noop({'applied': [], 'skipped': []}))

    def test_failed_selectors_are_not_noop(self):
        self.assertFalse(measurable_noop({'applied': [], 'skipped': [{'reason': 'selector did not match'}]}))

    def test_missing_or_applied_plan_is_not_noop(self):
        for result in (None, {}, {'applied': []}, {'applied': [{'action': 'set_attribute'}], 'skipped': []}):
            self.assertFalse(measurable_noop(result))

    def test_empty_serialization_does_not_create_a_candidate(self):
        self.assertTrue(unchanged_proposal('<input disabled>', '<input disabled=""/>',
                                          {'applied': [], 'skipped': []}))

    def test_deterministic_or_widget_changes_still_require_measurement(self):
        empty = {'applied': [], 'skipped': []}
        self.assertFalse(unchanged_proposal('before', 'after', empty, ['widget repair']))
        self.assertFalse(unchanged_proposal('before', 'after',
                                          {'applied': ['attribute'], 'skipped': []}))

    def test_identical_applied_attribute_is_not_another_page(self):
        self.assertTrue(unchanged_proposal('same', 'same',
                                         {'applied': ['attribute'], 'skipped': []}))

    def test_skipped_invalid_operation_retains_output_contract_path(self):
        self.assertFalse(unchanged_proposal('same', 'same',
                                          {'applied': [], 'skipped': ['forbidden']}))
