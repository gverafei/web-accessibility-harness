"""Adaptive routing cannot silently change the selected worker's instructions."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness.contracts import ContractError
from harness.engine import create_campaign
from harness.iteration_policy import VERSION as ITERATION_POLICY
from harness.prompt_policy import VERSION
import test_slider_bridge as fixtures


class SelectedStrategyPromptTests(unittest.TestCase):
    def bridge(self, dynamic, *, shared=True):
        fixture = fixtures.BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.manifest.update(iteration_policy=ITERATION_POLICY)
        fixture.manifest['conditions'] = [{'id': 'adaptive' if dynamic else 'fixed',
            'level': 6 if dynamic else 1, 'worker_id': 'cheap', 'selector': 'rules'}]
        if dynamic and shared:
            fixture.manifest['worker_prompt_policy'] = VERSION
        bridge = fixture.bridge()
        bridge.begin_iteration(1)
        if dynamic:
            bridge.decision = {**bridge.decision, 'data': {
                **bridge.decision['data'], 'repair_focus': 'labels'}}
            bridge.generation_contextual_evidence = {
                'failed_opportunities': [{'type': 'link-name', 'target': ['#missing']}],
                'unresolved_prior_findings': []}
        return bridge, fixture

    def test_all_four_selected_routes_send_identical_worker_envelopes_to_fixed_routes(self):
        for level in (1, 3, 4, 5):
            for role in ('repair-generator', 'component-planner', 'repair-diagnostician'):
                with self.subTest(level=level, role=role):
                    fixed, fixed_fixture = self.bridge(False)
                    adaptive, adaptive_fixture = self.bridge(True)
                    body = {'model': fixed.worker['model'], 'max_tokens': 64,
                            'messages': [{'role': 'user', 'content': 'Selected strategy task and current page.'}]}
                    for bridge in (fixed, adaptive):
                        bridge.level = level
                        bridge.task_runtime = SimpleNamespace(active_task_name=role)
                        bridge.transport(copy.deepcopy(body))
                    self.assertEqual(fixed_fixture.session.requests[-1],
                                     adaptive_fixture.session.requests[-1])
                    self.assertIsNone(adaptive.worker_contextual_evidence())
                    self.assertEqual(adaptive.generation_contextual_evidence['failed_opportunities'][0]['target'], ['#missing'])

    def test_legacy_adaptive_envelope_remains_available_for_recorded_executions(self):
        bridge, fixture = self.bridge(True, shared=False)
        bridge.transport({'model': bridge.worker['model'], 'max_tokens': 64,
                          'messages': [{'role': 'user', 'content': 'Legacy worker task.'}]})
        text = str(fixture.session.requests[-1]['messages'])
        self.assertIn('Decisions advisory repair focus:', text)
        self.assertIn('Current document contextual findings:', text)
        self.assertIsNotNone(bridge.worker_contextual_evidence())

    def test_prompt_policy_is_explicit_and_unknown_versions_cannot_dispatch(self):
        fixture = fixtures.BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = create_campaign(fixture.store, fixture.manifest)['data']
        self.assertNotIn('worker_prompt_policy', original)
        fixture.manifest['worker_prompt_policy'] = VERSION
        self.assertEqual(create_campaign(fixture.store, fixture.manifest)['data']['worker_prompt_policy'], VERSION)
        fixture.manifest['worker_prompt_policy'] = 'unrecognized'
        with self.assertRaises(ContractError):
            create_campaign(fixture.store, fixture.manifest)

    def test_new_p5_registration_keeps_an_explicit_same_source_binding_and_shared_prompt(self):
        from harness.remediation_bridge import configure
        from harness.source_binding import VERSION as BINDING_VERSION
        from harness.decision_models import DEFINITIONS
        fixture = fixtures.BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        binding = {'version': BINDING_VERSION, 'sql_source_id': 7,
                   **{key: key for key in ('capture_id', 'audit_id', 'replay_id', 'source_artifact_id')},
                   **{key: 'a'*64 for key in ('input_sha256', 'native_package_sha256',
                                             'reference_document_sha256', 'evaluator_runtime_sha256')}}
        values = {'harness_corpus': fixture.corpus['id'], 'harness_verifier': 'cheap',
                  'preservation_level': '4', 'max_cost_usd': '1', 'max_iterations': '5',
                  'max_execution_seconds': '900', 'max_axe': '5', 'min_lighthouse': '90',
                  'harness_budget_json': json.dumps({'id': 'fixture-registration', 'stage': 'remediation',
                      'total_usd': 1, 'stage_limits': {'remediation': 1}})}
        with patch('remediation_model_choices.model_choices', return_value=fixture.workers), \
             patch('harness.remediation_bridge.options', return_value={'corpora': [{'id': fixture.corpus['id']}], 'groups': []}), \
             patch('harness.decision_models.capture_choices', return_value=[fixture.workers[0]]), \
             patch('harness.decision_models.catalogue', return_value=DEFINITIONS):
            configuration = configure(fixture.store, {}, {'id': 7, 'url': 'https://fixture.example/'},
                                      fixture.workers[0], values, frozen_source_binding=binding)
            manifest = fixture.store.get(configuration['campaign_id'])['data']
            self.assertEqual(manifest['worker_prompt_policy'], VERSION)
            self.assertEqual(manifest['frozen_source_binding'], binding)
            self.assertTrue(manifest['stop_at_perfect_audit'])
            self.assertFalse(manifest['conditions'][0]['controls']['memory'])
            with self.assertRaisesRegex(ContractError, 'selected acquisition'):
                configure(fixture.store, {}, {'id': 8, 'url': 'https://other.example/'},
                          fixture.workers[0], values, frozen_source_binding=binding)

    def test_perfect_adaptive_candidate_closes_without_another_selection_or_worker_call(self):
        bridge, fixture = self.bridge(True)
        bridge.manifest['stop_at_perfect_audit'] = True
        audit = fixture.store.append('audit', {'axe': 0, 'lighthouse': 100}, bridge.cid)
        bridge.state['incumbent'].update(audit_id=audit['id'], original=False)
        bridge.state['attempts'] = ['evaluated-candidate']
        requests = list(fixture.session.requests)
        with patch.object(bridge, 'prepare_dynamic_context', return_value=None):
            self.assertEqual(bridge.begin_iteration(2), (None, None))
        self.assertEqual(fixture.session.requests, requests)
        self.assertIn('Perfect audit', bridge.state['stop_reason_override'])


if __name__ == '__main__':
    unittest.main()
