import copy
import tempfile
import unittest
from unittest.mock import patch

from accessibility_taxonomy.consistency import compare
from accessibility_taxonomy.consistency_resolution import resolve, revise_outcome, validate_revision
from harness.contracts import ContractError
from harness.reports import current_measurements
from harness.store import Store


def assessment(context, status):
    return {'model': {'id': 'judge'}, 'opportunities': [{
        'opportunity_id': 'control', 'type': 'widget-label-purpose-mismatch',
        'method': 'decisions', 'status': status,
        'context': {'element': {'tag': 'a', 'text': 'Help'}, 'observed_purpose': context}}]}


class ConsistencyResolutionTests(unittest.TestCase):
    def fixture(self, store, changed=True):
        before = store.append('taxonomy_assessment', assessment('old context', 'passed'), 'campaign')
        after = store.append('taxonomy_assessment', assessment('new context' if changed else 'old context', 'failed'), 'campaign')
        legacy = dict(compare(before['data'], after['data']), review_required=True,
                      version='unchanged-target-verdict-review-v1',
                      before_assessment_id=before['id'], before_assessment_hash=before['hash'],
                      after_assessment_id=after['id'], after_assessment_hash=after['hash'])
        review = store.append('taxonomy_consistency_review', legacy, 'campaign')
        outcome = store.append('run_result', dict(run_id='r', page_id='page', condition_id='p5',
            selected={'source_id': 'html', 'audit_id': 'audit'}, axe=0, lighthouse=100,
            costs={'cost_usd': .12, 'call_ids': ['paid']}, seconds=300, attempts=['candidate'],
            taxonomy_measurement={'retained_assessment_id': after['id'], 'status': 'completed'},
            stop_reason='Historical consistency stop',
            measurement_consistency=dict(review['data'], record_id=review['id'])), 'campaign', 'r-result')
        return review, outcome

    def test_resolution_preserves_verdicts_resources_historical_stop_and_report_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            review, original = self.fixture(store)
            resolution = resolve(store, review['id'], 'Offline evidence review')
            revision = revise_outcome(store, original['id'], resolution['id'])
            self.assertEqual(resolution, resolve(store, review['id'], 'Offline evidence review'))
            self.assertEqual(revision, revise_outcome(store, original['id'], resolution['id']))
            with patch('harness.reports.Ledger.rows', return_value=[]):
                runs, calls, revisions = current_measurements(store, 'campaign', [original], [])
            new = runs[0]['data']
            self.assertFalse(new['measurement_consistency']['review_required'])
            for key in original['data'].keys() - {'measurement_consistency'}:
                self.assertEqual(new[key], original['data'][key])
            self.assertEqual(store.get(original['id']), original)
            self.assertEqual(store.get(review['id']), review)
            self.assertEqual(new['measurement_consistency']['changes'][0]['after_status'], 'failed')
            self.assertEqual(calls, [])
            self.assertEqual(revisions, [revision['id']])

    def test_identical_context_conflict_cannot_be_resolved_by_this_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            review, _ = self.fixture(store, changed=False)
            with self.assertRaisesRegex(ContractError, 'Every historical conflict'):
                resolve(store, review['id'], 'Do not override genuine conflict')

    def test_resolution_cannot_change_any_metrics_resources_attempts_or_stop_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            review, original = self.fixture(store)
            resolution = resolve(store, review['id'], 'Offline diagnosis')
            revision = revise_outcome(store, original['id'], resolution['id'])
            for key, value in [('axe', 1), ('seconds', 1), ('costs', {}), ('attempts', []),
                               ('selected', {}), ('stop_reason', 'Success'), ('taxonomy_measurement', {})]:
                with self.subTest(key=key):
                    forged = copy.deepcopy(revision)
                    forged['data']['outcome'][key] = value
                    with self.assertRaises(ContractError):
                        validate_revision(store, forged, original['data'])

    def test_resolution_rejects_other_campaign_or_other_original_review(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            review, original = self.fixture(store)
            resolution = resolve(store, review['id'], 'Offline diagnosis')
            revision = revise_outcome(store, original['id'], resolution['id'])
            forged = copy.deepcopy(revision)
            forged['campaign'] = 'another'
            with self.assertRaises(ContractError):
                validate_revision(store, forged, original['data'])
            incumbent = copy.deepcopy(original['data'])
            incumbent['measurement_consistency']['record_id'] = 'unrelated'
            with self.assertRaises(ContractError):
                validate_revision(store, revision, incumbent)
