"""Malformed coordination remains rejected with actionable bounded feedback."""
import copy
import json
import unittest
from unittest.mock import patch

from harness.controller import materialize
from remediation_interventions import VERSION, coordinated_plan


def proposal(count=3):
    return {
        'operations': [
            {'action': 'set_attribute', 'selector': f'#target{i}',
             'name': 'aria-label', 'value': f'Target {i}'} for i in range(count)],
        'root_causes': [
            {'id': f'cause{i}', 'selectors': [f'#target{i}'],
             'depends_on': [], 'operation_indexes': [(i + 1) % count]}
            for i in range(count)]}


class CoordinationFeedbackTests(unittest.TestCase):
    def test_reports_all_shifted_assignments_without_mutating_response(self):
        plan = proposal()
        original = copy.deepcopy(plan)
        with self.assertRaises(ValueError) as caught:
            coordinated_plan('', plan)
        message = str(caught.exception)
        for i in range(3):
            self.assertIn(f'"group": "cause{i}"', message)
            self.assertIn(f'"operation_index": {i}', message)
            self.assertIn(f'"actual_operation_selector": "#target{i}"', message)
        self.assertIn('3 mismatched assignments', message)
        self.assertIn('zero-based', message)
        self.assertIn('No operation from this proposal was applied', message)
        self.assertEqual(plan, original)

    def test_feedback_is_bounded_for_large_untrusted_selectors(self):
        plan = proposal(60)
        for operation in plan['operations']:
            operation['selector'] = '#' + 'x' * 20000
        with self.assertRaises(ValueError) as caught:
            coordinated_plan('', plan)
        message = str(caught.exception)
        self.assertIn('60 mismatched assignments', message)
        self.assertEqual(message.count('"operation_index"'), 8)
        self.assertLess(len(message), 4000)

    def test_native_executor_preserves_feedback_and_never_applies_invalid_graph(self):
        from harness.contracts import ContractError
        with patch('harness.controller.apply_repair_plan') as apply:
            with self.assertRaises(ContractError) as caught:
                materialize('<p>Source</p>', json.dumps(proposal()), 3,
                            'https://example.test/', intervention_version=VERSION)
            self.assertIn('coordination-feedback-v1', str(caught.exception))
            apply.assert_not_called()

    def test_correctly_reindexed_plan_retains_dependency_order(self):
        plan = proposal()
        for i, group in enumerate(plan['root_causes']):
            group['operation_indexes'] = [i]
        plan['root_causes'][0]['depends_on'] = ['cause2']
        original = copy.deepcopy(plan)
        ordered, evidence = coordinated_plan('', plan)
        self.assertEqual(evidence['operation_order'], [1, 2, 0])
        self.assertEqual(ordered['operations'], [plan['operations'][i] for i in [1, 2, 0]])
        self.assertEqual(plan, original)

    def test_no_automatic_assignment_for_equivalent_selector_spelling(self):
        plan = proposal(1)
        plan['root_causes'][0]['selectors'] = ['p[id="target0"]']
        with self.assertRaises(ValueError):
            coordinated_plan('<p id="target0">Text</p>', plan)
