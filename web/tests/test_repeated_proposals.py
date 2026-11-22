"""Exact repeated pages reuse prior evidence while retaining proposal consumption."""
import tempfile
import unittest
from types import SimpleNamespace
from harness.contracts import ContractError
from harness.remediation_bridge import Bridge
from harness.store import Store
from remediation_completion import REPEATED_PROPOSAL_FEEDBACK


class RepeatedProposalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.bridge = Bridge.__new__(Bridge)
        self.bridge.store = self.store
        self.bridge.cid = 'campaign'
        self.bridge.rid = 'run'
        self.bridge.level = 1
        self.bridge.worker = {'id': 'worker'}
        self.bridge.decision = {'id': 'decision'}
        self.bridge.providers = SimpleNamespace(completion_stage='iteration')
        self.bridge.number = 3
        self.bridge.attempt_id = 'attempt-3'
        self.bridge.costs = lambda: {'known': True, 'cost_usd': .1,
                                    'call_ids': ['paid-response']}
        self.a = '<main>Retained A</main>'
        self.b = '<main>Measured B</main>'
        self.first = self.attempt('first', self.a)
        self.second = self.attempt('second', self.b)
        self.bridge.state = {'attempts': ['first', 'second'], 'iteration': 2,
            'incumbent': {'source_id': self.first['source_id'],
                          'audit_id': self.first['audit_id']},
            'loop_context': {'completed_iteration': 2}}

    def attempt(self, ident, html, status='completed', campaign='campaign'):
        source = self.store.blob(html, 'candidate', campaign, 'text/html')
        audit = self.store.append('audit', {'status': status}, campaign, ident+'-audit')
        record = self.store.append('attempt', {'run_id': 'run',
            'source_id': source['id'], 'audit_id': audit['id']}, campaign, ident)
        return record['data']

    def test_repeat_of_rejected_candidate_is_not_a_new_measurement_or_selection(self):
        measured = self.bridge.previously_measured_candidate(self.b)
        self.assertEqual(measured['attempt_id'], 'second')
        before = dict(self.bridge.state['incumbent'])
        audits = self.store.list('audit')
        record = self.bridge.record_repeated_proposal(self.b, measured,
            REPEATED_PROPOSAL_FEEDBACK, {'applied': ['remove_attribute'], 'skipped': []})
        self.bridge.record_repeated_proposal(self.b, measured,
            REPEATED_PROPOSAL_FEEDBACK, {'applied': ['remove_attribute'], 'skipped': []})
        self.assertEqual(self.store.list('audit'), audits)
        self.assertEqual(self.bridge.state['incumbent'], before)
        self.assertEqual(self.bridge.state['attempts'], ['first', 'second'])
        self.assertEqual(self.bridge.state['iteration'], 3)
        from harness.loop_checkpoint import validate_iteration_boundary
        self.assertTrue(validate_iteration_boundary(
            [{'iteration_number': 1}, {'iteration_number': 2}], self.bridge.state, self.store))
        self.assertEqual(self.bridge.state['empty_patch_count'], 1)
        self.assertFalse(record['data']['evaluated'])
        self.assertEqual(record['data']['reused_audit_id'], self.second['audit_id'])
        self.assertEqual(record['data']['consumption']['cost_usd'], .1)
        self.assertEqual(self.bridge.state['last_noop']['feedback'], REPEATED_PROPOSAL_FEEDBACK)

    def test_a_changed_page_and_an_incomplete_audit_are_not_suppressed(self):
        self.assertIsNone(self.bridge.previously_measured_candidate(self.b+' changed'))
        self.attempt('incomplete', '<main>Unmeasured</main>', 'failed')
        self.bridge.state['attempts'].append('incomplete')
        self.assertIsNone(self.bridge.previously_measured_candidate('<main>Unmeasured</main>'))

    def test_instrument_recovery_keeps_an_opportunity_under_the_new_execution(self):
        self.bridge.execution_revision = {'data': {'prior_attempt_ids': ['first', 'second']}}
        self.assertIsNone(self.bridge.previously_measured_candidate(self.b))
        self.attempt('corrected', self.b)
        self.bridge.state['attempts'].append('corrected')
        self.assertEqual(self.bridge.previously_measured_candidate(self.b)['attempt_id'], 'corrected')

    def test_wrong_measurement_and_foreign_attempt_fail_before_reuse(self):
        with self.assertRaises(ContractError):
            self.bridge.record_repeated_proposal(self.b,
                {'attempt_id': 'first', **self.first}, 'feedback', {})
        self.attempt('foreign', self.b, campaign='another-campaign')
        self.bridge.state['attempts'].append('foreign')
        with self.assertRaises(ContractError):
            self.bridge.previously_measured_candidate(self.b)
