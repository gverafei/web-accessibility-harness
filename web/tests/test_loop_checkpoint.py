import json
import tempfile
import unittest

from harness.contracts import ContractError
from harness.loop_checkpoint import VERSION, restore, validate_audit_source
from harness.providers import Ledger
from harness.store import Store


class LoopCheckpointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(directory.name)
        self.state = {'iteration': 3, 'incumbent': {'source_id': 'source', 'case_id': 'case'}}
        self.context = {'version': VERSION, 'completed_iteration': 3,
                        'incumbent_source_id': 'source', 'component_plan': [], 'feedback': 'exact'}

    def test_valid_checkpoint_is_restored_without_provider_calls(self):
        self.state['loop_context'] = self.context
        self.assertEqual(restore(self.store, self.state, 'campaign', 'run', []), self.context)
        self.assertEqual(Ledger(self.store).rows(), [])

    def test_committed_progress_restores_diagnosis_trigger_and_preserves_checkpoint(self):
        self.state['loop_context'] = self.context
        rows = [{'strategy_json':json.dumps({'candidate_selection':{
            'best_so_far':best,'gate_distance':7,'marginal_progress':True,
            'improvement_basis':'marginal'},'content_retention':{'text_percent':100}})}
            for best in (True,False)]
        restored = restore(self.store,self.state,'campaign','run',rows)
        self.assertEqual(restored['progress_state']['stagnant_attempts'],1)
        self.assertEqual(restored['progress_state']['marginal_attempts'],1)
        self.assertEqual(restored['progress_state']['previous_progress']['quality'],7)
        self.assertNotIn('progress_state',self.context)
        self.assertEqual(Ledger(self.store).rows(),[])

    def test_stale_checkpoint_source_or_iteration_is_rejected(self):
        for field, value in (('incumbent_source_id', 'other'), ('completed_iteration', 2)):
            self.state['loop_context'] = {**self.context, field: value}
            with self.assertRaises(ContractError):
                restore(self.store, self.state, 'campaign', 'run', [])

    def test_legacy_resumption_cannot_guess_missing_pending_request(self):
        with self.assertRaises(ContractError):
            restore(self.store, self.state, 'campaign', 'run', [])

    def paid_request(self, iteration=4):
        self.feedback = 'prior rejection summary\nPending feedback for the retained best page:\n' + 'context ' * 1500
        evidence = {'iteration': iteration, 'previous_evaluation_feedback': self.feedback}
        self.plan = [{'selector': '#component', 'intervention': 'patch', 'root_cause': 'names', 'depends_on': []}]
        prompt = 'Current evidence:\n' + json.dumps(evidence) + '\nArchitecture plan: ' + json.dumps(self.plan)
        model = {'model': 'fixture', 'provider': 'openrouter', 'context_length': 262144,
                 'pricing_source': 'offline fixture', 'input_usd_per_million': 0, 'output_usd_per_million': 0}
        budget = {'max_calls': 10, 'max_cost_usd': 1, 'max_seconds': 60, 'max_output_tokens': 128}
        body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 128}
        ledger = Ledger(self.store)
        call, _ = ledger.begin('campaign', 'run', 'repair', 'run-attempt-3:call:0', body, model, budget, 1)
        ledger.received(call, json.dumps({'model':'fixture','usage':{'prompt_tokens':1,'completion_tokens':1,'cost':0}}), model, 0, 200)
        self.store.append('technical_assessment', {'verification_id': 'visual'}, 'campaign', 'case')
        self.completed = [{'strategy_json': json.dumps({'harness': {'retained': True, 'verification_id': 'visual'},
                                                        'content_retention': {'text_percent': 100},
                                                        'candidate_selection': {'visual_similarity_percent': 99}})}]

    def test_exact_paid_feedback_and_plan_are_restored_without_truncation(self):
        self.paid_request()
        restored = restore(self.store, self.state, 'campaign', 'run', self.completed)
        self.assertEqual(restored['feedback'], self.feedback)
        self.assertEqual(restored['best_feedback'], 'context ' * 1500)
        self.assertGreater(len(restored['best_feedback']), 8000)
        self.assertEqual(restored['component_plan'], self.plan)
        self.assertEqual(restored['best_visual'], 99)
        self.assertEqual(len(Ledger(self.store).rows()), 1)

    def test_paid_request_from_wrong_iteration_is_rejected(self):
        self.paid_request(iteration=5)
        with self.assertRaises(ContractError):
            restore(self.store, self.state, 'campaign', 'run', self.completed)

    def test_cached_audit_requires_the_same_input_bytes(self):
        import hashlib
        source = '<html>measured candidate</html>'
        audit = {'data':{'replay':{'input_document_sha256':hashlib.sha256(source.encode()).hexdigest()}}}
        validate_audit_source(audit, source, required=True)
        with self.assertRaises(ContractError):
            validate_audit_source(audit, source.replace('candidate','other'), required=True)
        with self.assertRaises(ContractError):
            validate_audit_source({'data':{}}, source, required=True)


if __name__ == '__main__':
    unittest.main()


class ActiveRouteTests(unittest.TestCase):
    def test_saved_route_preserves_planning_state_on_resume(self):
        from harness.loop_checkpoint import active_route
        worker={'id':'light'}
        self.assertEqual(active_route({'active_wire_level':3,'active_worker_id':'light'},[],[worker]),(3,worker))

    def test_legacy_committed_route_uses_worker_from_that_iteration(self):
        from harness.loop_checkpoint import active_route
        worker={'id':'high'}
        row={'iteration_number':3,'strategy_json':json.dumps({'wire_level':3,'harness':{'worker_id':'high'}})}
        self.assertEqual(active_route({'completed_iteration':3},[row],[{'id':'light'},worker]),(3,worker))
        with self.assertRaises(ContractError):
            active_route({'completed_iteration':4},[row],[worker])
        with self.assertRaises(ContractError):
            active_route({'active_wire_level':3,'active_worker_id':'outside'},[],[worker])

class InvalidProposalBoundaryTests(unittest.TestCase):
    def test_history_free_invalid_output_is_not_a_missing_evaluated_page(self):
        from harness.remediation_bridge import Bridge
        from harness.loop_checkpoint import validate_iteration_boundary
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            bridge=Bridge.__new__(Bridge)
            bridge.store=Store(directory)
            bridge.cid='campaign';bridge.rid='sql-run-1';bridge.condition={'level':6}
            bridge.manifest={'record_experience':False};bridge.number=1;bridge.level=1
            bridge.worker={'id':'worker'};bridge.decision={'id':'decision'}
            bridge.attempt_id='sql-run-1-attempt-0';bridge.providers=SimpleNamespace(completion_stage='iteration')
            bridge.costs=lambda:{'cost_usd':.02,'known':True}
            bridge.state={'iteration':0,'attempts':[],'incumbent':{'source_id':'unchanged'},
                'loop_context':{'completed_iteration':0,'incumbent_source_id':'unchanged'}}
            recorded=bridge.record_invalid_proposal('Rejected invalid selector', '/saved/response.txt')
            self.assertFalse(recorded['data']['evaluated'])
            self.assertEqual(bridge.state['attempts'],[])
            self.assertEqual(bridge.state['incumbent'],{'source_id':'unchanged'})
            self.assertEqual(bridge.state['iteration'],1)
            self.assertEqual(bridge.state['loop_context']['completed_iteration'],1)
            self.assertTrue(validate_iteration_boundary([],bridge.state,bridge.store))
            bridge.record_invalid_proposal('Rejected invalid selector', '/saved/response.txt')
            self.assertEqual(bridge.state['empty_patch_count'],1)
            self.assertEqual(Ledger(bridge.store).rows(),[])
