import copy
import tempfile
import unittest
from unittest.mock import Mock

from accessibility_taxonomy.consistency import compare, record, attach, pending, STOP_REASON
from harness.remediation_bridge import Bridge
from harness.store import Store
from remediation_interventions import VERSION


def assessment(status='passed', text='A web server.', title='Project'):
    return {'model': {'id': 'decisions'}, 'opportunities': [{
        'opportunity_id': 'title', 'identity_basis': 'title::'+title,
        'type': 'page-title-not-descriptive', 'method': 'decisions', 'status': status,
        'context': {'element': {'tag': 'title', 'text': title, 'attributes': {}},
                    'observed_text': text}}]}


class ContextualConsistencyTests(unittest.TestCase):
    def test_unchanged_title_flip_is_not_attributed_to_a_title_edit(self):
        before, after = assessment(), assessment('failed', 'Project web server. A web server.')
        original = copy.deepcopy((before, after))
        review = compare(before, after)
        self.assertFalse(review['review_required'])
        self.assertEqual(review['changes'][0]['classification'], 'context_changed_reassessment')
        self.assertEqual(review['changes'][0]['changed_context_fields'], ['observed_text'])
        self.assertEqual((before, after), original)
        self.assertFalse(review['raw_measurements_modified'])

    def test_identical_evidence_contradiction_is_explicit_not_silently_cached(self):
        review = compare(assessment(), assessment('failed'))
        self.assertEqual(review['changes'][0]['classification'], 'identical_context_verdict_conflict')
        self.assertTrue(review['review_required'])

    def test_actual_title_changes_and_stable_verdicts_are_not_false_conflicts(self):
        self.assertFalse(compare(assessment(), assessment('failed', title='Unrelated'))['review_required'])
        self.assertFalse(compare(assessment(), assessment(text='Expanded page content.'))['review_required'])

    def test_changed_judge_is_distinguished_from_repeatability(self):
        before, after = assessment(), assessment('failed')
        after['model'] = {'id': 'different'}
        self.assertEqual(compare(before, after)['changes'][0]['classification'], 'judge_model_changed')

    def test_unchanged_widget_with_changed_neighbor_roles_keeps_current_finding(self):
        before = assessment()
        row = before['opportunities'][0]
        row['type'] = 'widget-label-purpose-mismatch'
        row['context'] = {'element': {'tag': 'a', 'text': 'Help', 'attributes': {'role': 'menuitem'}},
                          'observed_purpose': {'programmatic_context_html': '<nav><button role="menuitem">Menu</button><a role="menuitem">Help</a></nav>'}}
        after = copy.deepcopy(before)
        after['opportunities'][0]['status'] = 'failed'
        after['opportunities'][0]['context']['observed_purpose']['programmatic_context_html'] = '<nav><button>Menu</button><a role="menuitem">Help</a></nav>'
        review = compare(before, after)
        self.assertFalse(review['review_required'])
        self.assertEqual(review['changes'][0]['after_status'], 'failed')
        state = {}
        attach(state, {'id': 'diagnostic', 'data': review})
        self.assertFalse(pending(state))
        self.assertEqual(state['evaluator_consistency_review']['changes'][0]['after_status'], 'failed')

    def test_same_identity_copies_are_paired_by_opportunity_not_last_dictionary_value(self):
        before = assessment()
        duplicate = copy.deepcopy(before['opportunities'][0])
        duplicate.update(opportunity_id='other-copy', status='failed')
        before['opportunities'].append(duplicate)
        after = copy.deepcopy(before)
        self.assertFalse(compare(before, after)['changes'])

    def test_instrument_changes_still_block_and_nonblocking_context_does_not_clear_conflict(self):
        before, after = assessment(), assessment('failed', 'Changed contextual evidence')
        after['judge_protocol'] = 'new-instrument'
        self.assertTrue(compare(before, after)['review_required'])
        state = {'evaluator_consistency_review': {'review_required': True, 'record_id': 'unresolved'}}
        attach(state, {'id': 'context-change', 'data': compare(assessment(), assessment('failed', 'New context'))})
        self.assertTrue(pending(state))
        self.assertEqual(state['evaluator_consistency_review']['record_id'], 'unresolved')

    def test_record_is_receipt_linked_immutable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            before = store.append('taxonomy_assessment', assessment(), 'fixture')
            after = store.append('taxonomy_assessment', assessment('failed'), 'fixture')
            measurement = {'retained_assessment_id': after['id']}
            review = record(store, 'fixture', before['id'], measurement)
            self.assertEqual(review, record(store, 'fixture', before['id'], measurement))
            self.assertEqual(store.get(before['id']), before)
            self.assertEqual(store.get(after['id']), after)
            self.assertEqual(review['data']['before_assessment_hash'], before['hash'])

    def test_adaptive_iteration_stops_before_selector_retrieval_or_generation(self):
        bridge = object.__new__(Bridge)
        bridge.condition = {'level': 6}
        bridge.manifest = {'intervention_version': VERSION}
        bridge.state = {'evaluator_consistency_review': {'review_required': True}}
        bridge.providers = Mock()
        bridge.persist = Mock()
        bridge.prepare_dynamic_context = Mock()
        self.assertEqual(bridge.begin_iteration(3), (None, None))
        self.assertEqual(bridge.state['stop_reason_override'], STOP_REASON)
        bridge.prepare_dynamic_context.assert_not_called()
        self.assertEqual(bridge.providers.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
