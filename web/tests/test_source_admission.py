"""Frozen-input eligibility cannot change automatic or human outcome evidence."""
import copy
import unittest

from harness.contracts import ContractError
from harness.source_admission import approve, validate
from harness.execution_recovery import create_preparation_revision, resolve_manifest
import test_execution_recovery as recovery_fixture
import test_frozen_source_binding as source_fixture


class SourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        recovery_fixture.RecoveryTest.setUp(self)
        _, binding = source_fixture.FrozenSourceBindingTests().records(self.store.root)
        self.campaign = self.store.append('campaign', {**self.manifest, 'frozen_source_binding': binding})
        self.provider.campaign = self.campaign['id']
        self.provider.chat('sql-run-1', 'review', 'baseline:agent', self.model, 'source evidence')
        images = [self.store.blob(value, 'screenshot')['id'] for value in (b'original', b'replay')]
        self.verification = self.store.append('evidence_verification', {
            'phase': 'baseline', 'status': 'rejected', 'rationale': 'Peripheral advertisement',
            'capture_id': binding['capture_id'], 'audit_id': binding['audit_id'],
            'deterministic_id': binding['replay_id'], 'evidence_refs': images,
        }, self.campaign['id'], 'baseline')

    def test_explicit_admission_preserves_judgment_and_creates_no_human_answer(self):
        before = self.store.list()
        approval = approve(self.store, self.campaign['id'], 'sql-run-1', 'baseline', 'Explicit user confirmation')
        self.assertEqual(validate(self.store, self.campaign, 'sql-run-1', approval['id']), approval)
        self.assertEqual(self.store.get('baseline'), self.verification)
        self.assertEqual([r['kind'] for r in self.store.list() if r['id'] not in {v['id'] for v in before}],
                         ['source_admission'])
        for run, verification in (('other-run', None), ('sql-run-1', 'another')):
            with self.assertRaises((ContractError, KeyError)):
                validate(self.store, self.campaign, run, approval['id'], verification)

    def test_amendments_keep_original_manifest_and_source_calls(self):
        first = create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                                             {'code_digest':'first'}, 'Source clarification')
        approval = approve(self.store, self.campaign['id'], 'sql-run-1', 'baseline', 'User source eligibility')
        second = create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                     {'code_digest':'second'}, 'Recorded eligibility', approval['id'])
        effective, revision = resolve_manifest(self.store, self.campaign, second['id'],
                                               {'code_digest':'second'}, 'sql-run-1')
        self.assertEqual(second['data']['previous_execution_id'], first['id'])
        self.assertEqual(first['data']['prior_call_ids'], second['data']['prior_call_ids'])
        self.assertEqual(effective['frozen_source_binding'], self.campaign['data']['frozen_source_binding'])
        self.assertEqual(self.store.get(self.campaign['id']), self.campaign)
        self.assertNotIn('source_admission_id', effective)
        self.assertEqual(revision['data']['source_admission_hash'], approval['hash'])

    def test_cached_judgment_needs_no_new_call_for_exact_source_admission(self):
        campaign = self.store.append('campaign', self.campaign['data'])
        approval = approve(self.store, campaign['id'], 'sql-run-2', self.verification['id'],
                           'Explicit eligibility for the same frozen input')
        execution = create_preparation_revision(self.store, campaign['id'], 'sql-run-2',
                     {'code_digest': 'new'}, 'Reuse saved judgment', approval['id'])
        effective, _ = resolve_manifest(self.store, campaign, execution['id'],
                                       {'code_digest': 'new'}, 'sql-run-2')
        self.assertEqual(effective['frozen_source_binding'], campaign['data']['frozen_source_binding'])
        self.assertEqual(execution['data']['prior_call_ids'], [])
        self.assertEqual(execution['data']['prior_charges_usd'], 0)
        self.assertEqual(self.store.get(self.verification['id']), self.verification)
        self.assertEqual(len(self.session.requests), 1)

    def test_zero_call_recovery_requires_explicit_source_admission(self):
        campaign = self.store.append('campaign', self.campaign['data'])
        with self.assertRaises(ContractError):
            create_preparation_revision(self.store, campaign['id'], 'sql-run-2',
                                        {'code_digest': 'new'}, 'No explicit eligibility')

    def test_cached_judgment_cannot_admit_a_different_capture(self):
        data = copy.deepcopy(self.campaign['data'])
        data['frozen_source_binding']['capture_id'] = 'different-capture'
        campaign = self.store.append('campaign', data)
        with self.assertRaises(ContractError):
            approve(self.store, campaign['id'], 'sql-run-2', self.verification['id'],
                    'Eligibility does not transfer to a different capture')

    def test_admission_requires_frozen_scope_and_no_repair_started(self):
        for reference in ('', ' '):
            with self.assertRaises(ContractError):
                approve(self.store, self.campaign['id'], 'sql-run-1', 'baseline', reference)
        changed = copy.deepcopy(self.campaign)
        changed['data']['frozen_source_binding']['input_sha256'] = 'different'
        with self.assertRaises(ContractError):
            from harness.source_admission import evidence
            evidence(self.store, changed, self.verification)
        self.store.checkpoint('sql-run-1', {'iteration': 0})
        with self.assertRaises(ContractError):
            approve(self.store, self.campaign['id'], 'sql-run-1', 'baseline', 'User confirmation')
