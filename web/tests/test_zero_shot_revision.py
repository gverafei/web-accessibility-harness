import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from harness.contracts import ContractError
from harness.reports import current_measurements
from harness.store import Store
from harness.zero_shot_revision import validate_revision


class OutputRevisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.raw = 'I cannot return this page. Its `<html>` contains too much content.'
        response = self.store.blob(json.dumps({'choices': [{'message': {'content': self.raw}}]}),
                                   'provider_response', 'campaign', 'application/json')
        document = self.store.blob(self.raw, 'zero_shot_output', 'campaign', 'text/plain')
        self.calls = [dict(id='generator', run='run', logical_key='attempt:call:0', account='repair',
                           status='received', cost_status='provider_reported', created=20, elapsed=5,
                           cost=.02, input_tokens=100, output_tokens=20, response_id=response['id']),
                      dict(id='measurement', run='run', logical_key='taxonomy', account='review',
                           status='received', cost_status='provider_reported', created=26, elapsed=3,
                           cost=.01, input_tokens=50, output_tokens=5, response_id=response['id'])]
        artifact = self.store.blob('{}', 'sql_archive', 'campaign', 'application/json')
        archive = self.store.append('sql_correction_archive',
                                    {'artifact_id': artifact['id'], 'run_started_epoch': 10}, 'campaign')
        self.old = dict(run_id='run', page_id='page', condition_id='zero-shot', comparison_mode='zero-shot',
                        attempts=['old-attempt'], seconds=30, axe=0, lighthouse=100,
                        selected={'original': False, 'source_id': document['id'], 'audit_id': 'bad-audit'},
                        costs={'call_ids': ['generator', 'measurement'], 'cost_usd': .03})
        self.outcome = dict(self.old, attempts=[], seconds=15, axe=None, lighthouse=None,
                            preservation='unverified', preserved_success=False, admissible_success=False,
                            selected={'source_id': document['id'], 'audit_id': None, 'original': False, 'admissible': False},
                            source_fidelity={}, taxonomy_measurement={'status': 'not_applicable'},
                            output_evidence={'evaluable': False},
                            costs={'call_ids': ['generator'], 'cost_usd': .02, 'input_tokens': 100, 'output_tokens': 20})
        self.data = dict(outcome=self.outcome, response_call_id='generator', response_sha256=hashlib.sha256(self.raw.encode()).hexdigest(),
                         excluded_call_ids=['measurement'], sql_archive_id=archive['id'], raw_receipts_modified=False, no_generation=True)

    def test_reclassification_keeps_the_response_and_generator_charge(self):
        validate_revision(self.store, {'data': self.data}, self.old, self.calls)

    def test_no_fictitious_scores_or_omitted_generator_cost(self):
        for fields in ({'axe': 0}, {'lighthouse': 100}, {'seconds': 0},
                       {'costs': dict(self.outcome['costs'], cost_usd=0)}):
            with self.subTest(fields=fields):
                data = copy.deepcopy(self.data)
                data['outcome'].update(fields)
                with self.assertRaises(ContractError):
                    validate_revision(self.store, {'data': data}, self.old, self.calls)

    def test_real_html_cannot_be_reclassified_as_an_unavailable_page(self):
        response = self.store.blob(json.dumps({'choices': [{'message': {'content': '<main>real fragment</main>'}}]}),
                                   'provider_response', 'campaign', 'application/json')
        calls = copy.deepcopy(self.calls)
        calls[0]['response_id'] = response['id']
        with self.assertRaises(ContractError):
            validate_revision(self.store, {'data': self.data}, self.old, calls)

    def test_unknown_charge_cannot_be_excluded(self):
        calls = copy.deepcopy(self.calls)
        calls[1]['cost_status'] = 'unknown'
        with self.assertRaises(ContractError):
            validate_revision(self.store, {'data': self.data}, self.old, calls)

    def test_only_committed_correction_changes_the_active_report(self):
        parent = self.store.append('run_result', self.old, 'campaign', 'run-result')
        revision = self.store.append('zero_shot_output_revision', dict(self.data, parent_outcome_id=parent['id']), 'campaign')
        with patch('harness.reports.Ledger.rows', return_value=self.calls):
            rows, included, applied = current_measurements(self.store, 'campaign', [parent], list(self.calls))
            self.assertEqual(rows[0]['data']['axe'], 0)
            self.assertFalse(applied)
            self.store.checkpoint(revision['id'] + '-application', {'committed': True})
            rows, included, applied = current_measurements(self.store, 'campaign', [parent], list(self.calls))
        self.assertIsNone(rows[0]['data']['axe'])
        self.assertEqual([c['id'] for c in included], ['generator'])
        self.assertEqual(applied, [revision['id']])
        self.assertEqual(self.store.get(parent['id'])['data']['axe'], 0)
        self.assertEqual(len(self.calls), 2)

    def test_non_page_native_analysis_retains_unknown_issue_counts(self):
        from harness.analysis import outcomes
        audit = self.store.append('audit', {'axe': 3, 'lighthouse': 90, 'failures': []}, 'campaign')
        self.store.append('page', {'audit_id': audit['id']}, 'campaign', 'page')
        row = {'data': self.outcome, 'campaign': 'campaign'}
        result = outcomes(self.store, {'analysis': {}}, [row], [self.calls[0]])[0]
        self.assertIsNone(result['axe'])
        self.assertIsNone(result['corrected_instances'])
        self.assertIsNone(result['PRE'])
        self.assertEqual(result['baseline_axe'], 3)


if __name__ == '__main__':
    unittest.main()
