"""Recovery must preserve requests, costs, source identity and prior outcomes."""
import copy
import json
import tempfile
import unittest

from harness.contracts import ContractError, digest
from harness.execution_recovery import create_revision, create_preparation_revision, resolve_manifest, record_outcome
from harness.providers import Providers, UncertainCall, BudgetStop
from harness.reports import current_measurements
from harness.store import Store, Conflict
from test_harness import Session


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.model = {'model': 'openai/gpt-6-luna', 'provider': 'openrouter',
                      'context_length': 262144, 'pricing_source': 'offline fixture',
                      'input_usd_per_million': 0, 'output_usd_per_million': 0}
        budget = {'max_calls': 10, 'max_cost_usd': 1, 'max_seconds': 1800,
                  'max_call_cost_usd': 1, 'max_output_tokens': 128}
        self.manifest = {'repair_budget': budget, 'review_budget': dict(budget),
                         'campaign_cost_limit': 1, 'runtime_snapshot': {'code_digest': 'old'}}
        self.campaign = self.store.append('campaign', self.manifest)
        self.manifest = self.campaign['data']
        self.session = Session()
        self.provider = Providers(self.store, self.manifest, self.campaign['id'],
                                  {'openrouter_api_key': 'offline fixture',
                                   'openrouter_base_url': 'http://unused'}, self.session)

    def failed_call(self):
        self.session.transport = True
        with self.assertRaises(UncertainCall):
            self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.session.transport = False
        return self.provider.ledger.rows()[0]

    def authorize(self, call, cost=0):
        receipt = self.provider.ledger.reconcile(call['id'], cost, 'offline billing fixture')
        return self.provider.ledger.authorize_transport_retry(
            call['id'], receipt['id'], 'explicit recovery fixture')

    def test_unknown_charge_cannot_be_authorized(self):
        call = self.failed_call()
        receipt = self.store.append('call_reconciliation',
                                    {'call_id': call['id'], 'cost_usd': 0}, self.campaign['id'])
        with self.assertRaises(ContractError):
            self.provider.ledger.authorize_transport_retry(call['id'], receipt['id'], 'fixture')
        self.assertEqual(len(self.session.requests), 1)

    def test_reconciliation_alone_does_not_repeat_dispatch(self):
        call = self.failed_call()
        self.provider.ledger.reconcile(call['id'], 0, 'offline billing fixture')
        with self.assertRaisesRegex(ContractError, 'without a reusable response'):
            self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(len(self.session.requests), 1)

    def test_received_transient_error_needs_reconciliation_before_one_identical_retry(self):
        self.manifest['repair_budget']['max_calls'] = 1
        body = {'model':self.model['model'],'messages':[{'role':'user','content':'source'}],
                'max_tokens':128,'stream':False,'provider':{'allow_fallbacks':False,'require_parameters':True},
                'plugins':[{'id':'context-compression','enabled':False}],
                'response_format':{'type':'json_object'}}
        call, _ = self.provider.ledger.begin(self.campaign['id'], 'sql-run-1', 'repair',
            'source-key', body, self.model, self.manifest['repair_budget'], 1)
        raw = json.dumps({'id':'gen-error','error':{'code':502,'message':'Unavailable'}})
        response_id = self.provider.ledger.received(call, raw, self.model, 1, 200)
        with self.assertRaises(UncertainCall):
            self.provider.chat('sql-run-1','repair','source-key',self.model,'source')
        self.provider.ledger.reconcile(call['id'],0,'Confirmed billing fixture')
        with self.assertRaisesRegex(ContractError,'Provider error 502'):
            self.provider.chat('sql-run-1','repair','source-key',self.model,'source')
        authorization = self.authorize(call)
        value = self.provider.chat('sql-run-1','repair','source-key',self.model,'source')
        self.assertEqual(value,self.provider.chat('sql-run-1','repair','source-key',self.model,'source'))
        self.assertEqual(len(self.session.requests),1)
        self.assertEqual(len(self.provider.ledger.rows()),2)
        self.assertEqual(self.store.read_blob(response_id).decode(),raw)
        self.assertEqual(authorization['data']['failure_response_id'],response_id)

    def test_empty_choice_provider_error_allows_one_identical_reconciled_retry(self):
        call = self.failed_call()
        raw = json.dumps({'id': 'gen-empty', 'model': self.model['model'],
                          'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'cost': 0},
                          'choices': [{'finish_reason': 'error',
                                       'message': {'role': 'assistant', 'content': None,
                                                   'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'opaque fixture'}]},
                                       'error': {'code': 502, 'message': 'Provider returned an empty response'}}]})
        response = self.provider.ledger.received(call, raw, self.model, 1, 200)
        call = self.provider.ledger.rows()[0]
        self.assertTrue(self.provider.ledger.retryable_failure(call))
        self.authorize(call)
        result = self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(result, self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source'))
        self.assertEqual(len(self.session.requests), 2)
        self.assertEqual(len(self.provider.ledger.rows()), 2)
        self.assertEqual(self.store.read_blob(response).decode(), raw)

    def test_reasoning_metadata_needs_zero_completion_tokens_and_encrypted_type(self):
        call = self.failed_call()
        for tokens, kind in ((1, 'reasoning.encrypted'), (0, 'reasoning.text')):
            payload = {'usage': {'completion_tokens': tokens},
                       'choices': [{'finish_reason': 'error', 'error': {'code': 502},
                                    'message': {'content': None, 'reasoning_details': [{'type': kind, 'data': 'fixture'}]}}]}
            artifact = self.store.blob(json.dumps(payload), 'provider_response', self.campaign['id'])
            self.assertFalse(self.provider.ledger.retryable_failure(
                dict(call, status='received', response_id=artifact['id'])))

    def test_http_520_needs_reconciled_empty_response_before_identical_retry(self):
        call = self.failed_call()
        raw = json.dumps({'error': {'code': 520, 'message': 'Provider returned error',
                                   'metadata': {'raw': 'error code: 520'}}})
        response = self.provider.ledger.received(call, raw, self.model, 1, 520)
        call = self.provider.ledger.rows()[0]
        self.assertTrue(self.provider.ledger.retryable_failure(call))
        receipt = self.store.append('call_reconciliation',
                                    {'call_id': call['id'], 'cost_usd': 0}, self.campaign['id'])
        with self.assertRaises(ContractError):
            self.provider.ledger.authorize_transport_retry(call['id'], receipt['id'], 'fixture')
        self.authorize(call)
        result = self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(result, self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source'))
        rows = self.provider.ledger.rows()
        self.assertEqual(rows[0]['request_hash'], rows[1]['request_hash'])
        self.assertEqual(len(self.session.requests), 2)
        self.assertEqual(self.store.read_blob(response).decode(), raw)

    def test_choice_retry_does_not_discard_partial_or_nontransient_output(self):
        call = self.failed_call()
        for reason, code, message in (
                ('error', 502, {'content': 'partial output'}),
                ('error', 502, {'content': '', 'tool_calls': [{'id': 'tool'}]}),
                ('error', 502, {'content': '', 'reasoning': 'partial reasoning'}),
                ('error', 520, {'content': 'partial output'}),
                ('error', 401, {'content': ''}),
                ('length', 502, {'content': ''})):
            payload = {'choices': [{'finish_reason': reason, 'error': {'code': code}, 'message': message}]}
            artifact = self.store.blob(json.dumps(payload), 'provider_response', self.campaign['id'])
            self.assertFalse(self.provider.ledger.retryable_failure(
                dict(call, status='received', response_id=artifact['id'])))

    def test_authorized_retry_is_cached_and_preserves_original(self):
        self.manifest['repair_budget']['max_calls'] = 1
        call = self.failed_call()
        authorization = self.authorize(call, .2)
        result = self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(result, self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source'))
        rows = self.provider.ledger.rows()
        self.assertEqual(len(self.session.requests), 2)
        self.assertEqual(rows[0]['logical_key'], 'source-key')
        self.assertEqual(rows[0]['request_hash'], call['request_hash'])
        self.assertEqual(rows[0]['status'], 'transport_error')
        self.assertEqual(rows[1]['logical_key'], authorization['data']['retry_key'])
        self.assertEqual(rows[1]['request_hash'], call['request_hash'])
        self.assertAlmostEqual(sum(row['cost'] for row in rows), .2)
        with self.assertRaises(BudgetStop):
            self.provider.chat('sql-run-1', 'repair', 'another-key', self.model, 'source')
        self.assertEqual(len(self.session.requests), 2)

    def test_retry_cannot_change_payload_scope_or_bypass_old_cost(self):
        call = self.failed_call()
        self.authorize(call, .2)
        with self.assertRaises(Conflict):
            self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'different source')
        with self.assertRaises(ContractError):
            self.provider.chat('other-run', 'repair', 'source-key', self.model, 'source')
        self.manifest['repair_budget']['max_cost_usd'] = .1
        with self.assertRaises(BudgetStop):
            self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(len(self.session.requests), 1)

    def test_failed_retry_requires_its_own_reconciliation(self):
        call = self.failed_call()
        self.authorize(call)
        self.session.transport = True
        for _ in range(2):
            with self.assertRaises(UncertainCall):
                self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        self.assertEqual(len(self.session.requests), 2)

    def test_generation_header_is_saved_before_an_incomplete_response(self):
        import requests
        class Response:
            status_code = 200
            headers = {'X-Generation-Id':'gen-fixture', 'Authorization':'never persist'}
            @property
            def text(self):
                raise requests.ConnectionError('connection closed after headers')
        class HeaderSession:
            def post(inner, *args, **kwargs):
                self.assertTrue(kwargs['stream'])
                self.assertFalse(kwargs['json']['stream'])
                return Response()
        self.provider.session = HeaderSession()
        with self.assertRaises(UncertainCall):
            self.provider.chat('run','repair','header-key',self.model,'source')
        receipt = self.store.list('provider_response_headers')[0]
        self.assertEqual(receipt['data']['generation_id'], 'gen-fixture')
        self.assertNotIn('never persist', json.dumps(receipt))
        self.assertEqual(self.provider.ledger.rows()[0]['cost_status'], 'unknown')

    def interrupted_outcome(self):
        source = self.store.blob('<html>original</html>', 'rendered_html', self.campaign['id'])
        audit = self.store.append('audit', {'status': 'completed', 'axe': 10, 'lighthouse': 80},
                                  self.campaign['id'])
        outcome = {'run_id': 'sql-run-1', 'page_id': 'page', 'condition_id': 'P1',
                   'repetition': 0, 'intervention_version': 'fixture', 'attempts': [],
                   'selected': {'original': True, 'source_id': source['id'], 'audit_id': audit['id']},
                   'costs': {'call_ids': [], 'cost_usd': 0}, 'axe': 10, 'lighthouse': 80}
        self.store.append('run_result', outcome, self.campaign['id'], 'sql-run-1-result')
        self.store.checkpoint('sql-run-1', {'iteration': 0, 'attempts': []})
        return outcome

    def test_runtime_amendment_changes_only_runtime_and_keeps_parent(self):
        self.interrupted_outcome()
        runtime = {'code_digest': 'new'}
        revision = create_revision(self.store, self.campaign['id'], 'sql-run-1', runtime, 'fixture')
        manifest, _ = resolve_manifest(self.store, self.campaign, revision['id'], runtime, 'sql-run-1')
        self.assertEqual(manifest['repair_budget'], self.manifest['repair_budget'])
        self.assertEqual(self.store.get(self.campaign['id'])['data']['runtime_snapshot'], {'code_digest': 'old'})
        for actual, run in (({'code_digest': 'other'}, 'sql-run-1'), (runtime, 'other-run')):
            with self.assertRaises(ContractError):
                resolve_manifest(self.store, self.campaign, revision['id'], actual, run)
        changed = copy.deepcopy(manifest)
        changed['campaign_cost_limit'] = 100
        self.assertNotEqual(digest(changed), revision['data']['effective_manifest_hash'])
        with self.assertRaises(ContractError):
            resolve_manifest(self.store, self.campaign, None, runtime, 'sql-run-1')

    def test_source_admission_recovery_keeps_charge_and_creates_only_the_first_outcome(self):
        self.provider.chat('sql-run-1', 'review', 'source-admission:agent', self.model, 'source evidence')
        prior = self.store.append('evidence_verification', {'phase':'baseline', 'status':'rejected'},
                                  self.campaign['id'], 'source-admission')
        execution = create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                                               {'code_digest':'new'}, 'bounded source-scope fixture')
        calls = self.provider.ledger.rows()
        source = self.store.blob('<html>candidate</html>', 'candidate_html', self.campaign['id'])
        audit = self.store.append('audit', {'status':'completed', 'axe':1, 'lighthouse':99}, self.campaign['id'])
        outcome = {'run_id':'sql-run-1', 'attempts':['measured-attempt'],
            'selected':{'original':False, 'source_id':source['id'], 'audit_id':audit['id']},
            'axe':1, 'lighthouse':99, 'execution_revision_id':execution['id'],
            'generation_runtime_sha256':'new', 'costs':{'call_ids':[c['id'] for c in calls], 'cost_usd':0}}
        result = record_outcome(self.store, execution, outcome)
        self.assertEqual(result['kind'], 'run_result')
        self.assertEqual(result['id'], 'sql-run-1-result')
        self.assertEqual(self.store.get(prior['id']), prior)
        self.assertEqual(len(self.store.list('execution_recovery_result')), 0)
        self.assertEqual(execution['data']['prior_call_ids'], outcome['costs']['call_ids'])
        self.assertEqual(self.store.get(self.campaign['id'])['data']['runtime_snapshot']['code_digest'], 'old')
        with self.assertRaises(ContractError):
            create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                                        {'code_digest':'third'}, 'invalid repeat')

    def test_preparation_amendment_rejects_generation_and_unresolved_consumption(self):
        self.store.append('evidence_verification', {'phase':'baseline', 'status':'rejected'},
                          self.campaign['id'], 'source-admission')
        self.failed_call()
        with self.assertRaises(ContractError):
            create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                                        {'code_digest':'new'}, 'invalid fixture')
        self.authorize(self.provider.ledger.rows()[0])
        self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        with self.assertRaises(ContractError):
            create_preparation_revision(self.store, self.campaign['id'], 'sql-run-1',
                                        {'code_digest':'new'}, 'generation already invoked')

    def test_amendment_rejects_prior_attempts_and_unknown_costs(self):
        self.interrupted_outcome()
        self.store.checkpoint('sql-run-1', {'iteration': 1, 'attempts': ['attempt']})
        with self.assertRaises(ContractError):
            create_revision(self.store, self.campaign['id'], 'sql-run-1', {'code_digest': 'new'}, 'fixture')
        self.store.checkpoint('sql-run-1', {'iteration': 0, 'attempts': []})
        self.failed_call()
        with self.assertRaises(ContractError):
            create_revision(self.store, self.campaign['id'], 'sql-run-1', {'code_digest': 'new'}, 'fixture')

    def test_recovered_report_preserves_original_and_cumulative_charges(self):
        original = self.interrupted_outcome()
        call = self.failed_call()
        self.authorize(call, .2)
        execution = create_revision(self.store, self.campaign['id'], 'sql-run-1',
                                    {'code_digest': 'new'}, 'fixture')
        self.provider.chat('sql-run-1', 'repair', 'source-key', self.model, 'source')
        calls = self.provider.ledger.rows()
        source = self.store.blob('<html>candidate</html>', 'candidate_html', self.campaign['id'])
        audit = self.store.append('audit', {'status': 'completed', 'axe': 2, 'lighthouse': 98}, self.campaign['id'])
        outcome = {**original, 'selected': {'original': False, 'source_id': source['id'], 'audit_id': audit['id']},
                   'attempts': ['attempt'], 'axe': 2, 'lighthouse': 98,
                   'execution_revision_id': execution['id'], 'generation_runtime_sha256': 'new',
                   'costs': {'call_ids': [row['id'] for row in calls], 'cost_usd': .2}}
        record_outcome(self.store, execution, outcome)
        runs, actual_calls, revisions = current_measurements(
            self.store, self.campaign['id'], self.store.list('run_result'), calls)
        self.assertEqual(runs[0]['data']['axe'], 2)
        self.assertEqual(len(actual_calls), 2)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(self.store.get('sql-run-1-result')['data']['axe'], 10)
        outcome['costs']['call_ids'] = [calls[-1]['id']]
        with self.assertRaises(ContractError):
            record_outcome(self.store, execution, outcome)

    def test_mid_run_revision_preserves_the_completed_attempt_prefix(self):
        original = self.interrupted_outcome()
        source = self.store.blob('<html>measured</html>', 'candidate_html', self.campaign['id'])
        audit = self.store.append('audit', {'status':'completed','axe':2,'lighthouse':98}, self.campaign['id'])
        attempt = self.store.append('attempt', {'run_id':'sql-run-1'}, self.campaign['id'])
        # Build an independent interrupted-run fixture with a measured prefix.
        campaign = self.store.append('campaign', self.manifest)
        owned_attempt = self.store.append('attempt', {'run_id':'sql-run-2'}, campaign['id'])
        original.update(run_id='sql-run-2', attempts=[owned_attempt['id']],
                        selected={'original':False,'source_id':source['id'],'audit_id':audit['id']},axe=2,lighthouse=98)
        self.store.append('run_result', original, campaign['id'], 'sql-run-2-result')
        self.store.checkpoint('sql-run-2', {'iteration':1,'attempts':[owned_attempt['id']]})
        execution = create_revision(self.store, campaign['id'], 'sql-run-2', {'code_digest':'new'}, 'fixture')
        outcome = {**original, 'execution_revision_id':execution['id'],'generation_runtime_sha256':'new'}
        record_outcome(self.store, execution, outcome)
        outcome['attempts'] = []
        with self.assertRaises(ContractError):
            record_outcome(self.store, execution, outcome)

    def test_non_page_recovery_keeps_response_separate_from_evaluated_candidates(self):
        original = self.interrupted_outcome()
        execution = create_revision(self.store, self.campaign['id'], 'sql-run-1', {'code_digest': 'new'}, 'fixture')
        source = self.store.blob('A refusal with `<html>` examples.', 'zero_shot_output', self.campaign['id'])
        attempt = self.store.append('attempt', {'run_id': 'sql-run-1', 'source_id': source['id'],
            'output_evidence': {'evaluable': False}}, self.campaign['id'])
        outcome = {**original, 'comparison_mode': 'zero-shot', 'axe': None, 'lighthouse': None,
            'selected': {'original': False, 'source_id': source['id'], 'audit_id': None},
            'attempts': [], 'response_attempt_id': attempt['id'],
            'execution_revision_id': execution['id'], 'generation_runtime_sha256': 'new'}
        record_outcome(self.store, execution, outcome)
        outcome.pop('response_attempt_id')
        with self.assertRaises(ContractError):
            record_outcome(self.store, execution, outcome)

    def test_an_earlier_outcome_snapshot_does_not_claim_future_charges(self):
        original = self.interrupted_outcome()
        call = self.failed_call()
        self.authorize(call, .2)
        execution = create_revision(self.store, self.campaign['id'], 'sql-run-1', {'code_digest':'new'}, 'fixture')
        self.provider.chat('sql-run-1','repair','source-key',self.model,'source')
        old_calls = self.provider.ledger.rows()
        outcome = {**original, 'execution_revision_id':execution['id'],'generation_runtime_sha256':'new',
                   'costs':{'call_ids':[row['id'] for row in old_calls],'cost_usd':.2}}
        record_outcome(self.store, execution, outcome)
        self.provider.chat('sql-run-1','repair','later-key',self.model,'later request')
        calls = self.provider.ledger.rows()
        runs, counted, revisions = current_measurements(
            self.store,self.campaign['id'],self.store.list('run_result'),calls)
        self.assertEqual(runs[0]['data']['costs']['call_ids'], [row['id'] for row in old_calls])
        self.assertEqual(len(counted), 3)
        self.assertEqual(len(revisions), 1)


if __name__ == '__main__':
    unittest.main()
