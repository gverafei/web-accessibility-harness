import tempfile
import unittest
from harness.store import Store
from harness.contracts import ContractError
from harness.iteration_accounting import record_exclusion, exclusions, repair_count


class RepairAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.first = {'id': 10, 'iteration_number': 1, 'document_sha256': 'a' * 64}
        self.redundant = {'id': 11, 'iteration_number': 2, 'document_sha256': 'a' * 64}
        self.findings = {
            'candidate': {'axe': 0, 'lighthouse': 100},
            'functional_status': 'admitted', 'visual_status': 'admitted',
            'visual_impact': 'none',
        }

    def test_redundant_review_is_idempotent_and_preserves_billing_and_attempts(self):
        attempt = self.store.append('attempt', {'iteration': 2}, 'fixture', 'attempt-2')
        charge = self.store.append('call_receipt', {'cost_usd': .01}, 'fixture', 'paid-call')
        row = record_exclusion(self.store, 'fixture', 1, self.first, self.redundant,
                               self.findings, 10, 'forced-continue')
        again = record_exclusion(self.store, 'fixture', 1, self.first, self.redundant,
                                 self.findings, 10, 'forced-continue')
        self.assertEqual(row['id'], again['id'])
        self.assertEqual(repair_count(2, exclusions(self.store, 'fixture', 1)), 1)
        self.assertEqual(self.store.get(attempt['id']), attempt)
        self.assertEqual(self.store.get(charge['id']), charge)
        self.assertEqual(exclusions(self.store, 'fixture', 2), [])

    def test_useful_or_selected_attempts_cannot_be_excluded(self):
        for findings in [{**self.findings, 'candidate': {'axe': 2, 'lighthouse': 94}},
                         {**self.findings, 'remaining_taxonomy_failures': {'Semantic': 3}}]:
            with self.assertRaises(ContractError):
                record_exclusion(self.store, 'fixture', 1, self.first, self.redundant,
                                 findings, 10, 'forced-continue')
        with self.assertRaises(ContractError):
            record_exclusion(self.store, 'fixture', 1, self.first, self.redundant,
                             self.findings, 11, 'forced-continue')

    def test_uncertain_remote_provenance_is_not_a_repairable_defect(self):
        findings = {**self.findings,
                    'visual_warnings': ['destination_provenance_requires_human_confirmation']}
        row = record_exclusion(self.store, 'fixture', 1, self.first, self.redundant,
                               findings, 10, 'forced-continue')
        self.assertTrue(row['data']['identical_document'])

    def test_committed_cleanup_projects_one_cost_scope_without_rewriting_paid_receipts(self):
        from harness.reports import current_measurements
        archive_blob = self.store.blob(b'fixture recoverable archive', 'sql_cleanup_archive', 'fixture', 'application/gzip')
        archive = self.store.append('sql_correction_archive', {'artifact_id': archive_blob['id']}, 'fixture', 'archive')
        original_data = {
            'run_id': 'sql-run-1', 'selected': {'audit_id': 'first-audit'},
            'axe': 0, 'lighthouse': 100, 'attempts': ['first', 'second'],
            'costs': {'cost_usd': .02, 'call_ids': ['one', 'two']},
        }
        original = self.store.append('run_result', original_data, 'fixture', 'original')
        corrected = {**original['data'], 'attempts': ['first'],
                     'costs': {'cost_usd': .01, 'call_ids': ['one']}}
        revision = self.store.append('iteration_accounting_revision', {
            'parent_outcome_id': original['id'], 'outcome': corrected,
            'excluded_attempt_ids': ['second'], 'excluded_call_ids': ['two'],
            'raw_receipts_modified': False, 'sql_archive_id': archive['id'],
        }, 'fixture', 'cleanup')
        calls = [{'id': ident, 'run': 'sql-run-1', 'cost': .01,
                  'cost_status': 'provider_reported', 'status': 'completed'} for ident in ('one', 'two')]
        rows, measured, applied = current_measurements(self.store, 'fixture', [original], list(calls))
        self.assertEqual(len(measured), 2)
        self.store.checkpoint(revision['id'] + '-application', {'committed': True})
        rows, measured, applied = current_measurements(self.store, 'fixture', [original], list(calls))
        self.assertEqual(rows[0]['data']['costs']['cost_usd'], .01)
        self.assertEqual([row['id'] for row in measured], ['one'])
        self.assertEqual(self.store.get(original['id']), original)
        self.assertEqual(sum(row['cost'] for row in calls), .02)
