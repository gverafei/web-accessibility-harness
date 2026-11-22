"""No-network regression checks for failure signals, tariffs and grouped evidence."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness import adaptive_repair_context as policy
from harness.dynamic_objectives import repair_work, work_messages, CURRENT_EVIDENCE_VERSION, corrective_messages
from harness.planning_evidence import expanded_feedback, shared_feedback
from test_role_scoped_evidence import evidence


class CoordinatedRepairTests(unittest.TestCase):
    def test_failed_proposal_does_not_borrow_prior_progress_or_manufacture_plateau(self):
        state = {'iteration': 3, 'stagnant': 0, 'continuation_potential': True,
                 'continuation_reasons': ['accessibility_progress'], 'blocked_actions': [],
                 'measured_feedback': shared_feedback({'recent_attempts': [{'iteration': 2}],
                     'unmeasured_proposal': {'iteration': 3, 'feedback': 'invalid CSS'}})}
        before = copy.deepcopy(state)
        actual = policy.normalize_progress(state)
        self.assertEqual(state, before)
        self.assertFalse(actual['continuation_potential'])
        self.assertFalse(actual['last_proposal']['progress'])
        self.assertIsNone(actual['stagnant'])
        self.assertTrue(actual['measured_progress_before_last_proposal']['continuation_potential'])
        self.assertEqual(actual['blocked_actions'], [])
        self.assertEqual(actual['measured_feedback'], state['measured_feedback'])

    def test_stale_failure_does_not_override_a_newer_successful_proposal(self):
        state = {'iteration': 4, 'continuation_potential': True,
                 'measured_feedback': {'unmeasured_proposal': {'iteration': 3}}}
        self.assertEqual(policy.normalize_progress(state), state)

    def test_coordinated_payload_round_trips_all_context_and_uncertainty(self):
        data = evidence()
        data['failed_opportunities'].append({**data['failed_opportunities'][1],
            'opportunity_id': 'second', 'target': ['#other']})
        before = copy.deepcopy(data)
        payload = policy.repair_projection(data)
        self.assertEqual(expanded_feedback(payload['evidence']), data)
        self.assertEqual(data, before)
        group = next(g for g in payload['same_type_coordination_candidates'] if g['type'] == 'link-name')
        self.assertEqual([data['failed_opportunities'][i]['target'] for i in group['failed_opportunity_indices']], [['#link'], ['#other']])
        self.assertEqual(group['shared_root_cause'], 'requires source verification')
        self.assertEqual(len(expanded_feedback(payload['evidence'])['unresolved_prior_findings']), 1)

    def test_both_worker_roles_get_same_complete_scope_but_no_new_css_authority(self):
        work = repair_work(evidence(), {'patch_failures': [{}]},
            {'focus': 'all', 'target_types': ['link-name']}, version=policy.VERSION)
        planner = work_messages(work, 'component-planner')
        generator = work_messages(work, 'patch-generator')
        self.assertEqual(planner, generator)
        payload = json.loads(generator[1]['content'].split('\n', 1)[1])
        self.assertEqual(expanded_feedback(payload['evidence']), evidence())
        self.assertIn('existing property/value limits', planner[0]['content'])
        self.assertIn('never generalize', planner[0]['content'])

    def test_explicit_focus_and_legacy_full_messages_are_preserved(self):
        work = repair_work(evidence(), {}, {'focus': 'Semantic',
            'target_types': ['landmark-purpose-mismatch']}, version=policy.VERSION)
        self.assertEqual([r['opportunity_id'] for r in work['active_contextual_evidence']['failed_opportunities']], ['sem'])
        old = repair_work(evidence(), {}, version=CURRENT_EVIDENCE_VERSION)
        self.assertEqual(work_messages(old), corrective_messages(evidence()))

    def test_whole_projected_context_crosses_tariff_and_reference_is_not_modified(self):
        model = {'context_length': 1000000, 'input_usd_per_million': .1,
                 'output_usd_per_million': .5, 'pricing_overrides': [
                     {'min_prompt_tokens': 100000, 'input_usd_per_million': .5, 'output_usd_per_million': 2.5}]}
        request = {'messages': [{'role': 'user', 'content': 'x'*100000}], 'max_tokens': 1000}
        call = {'id': 'paid', 'request_id': 'req', 'input_tokens': 98000, 'output_tokens': 100, 'cost': .01}
        before = copy.deepcopy(request)
        data = {'failed_opportunities': [{'type': 'link-name', 'opportunity_id': 'x',
                                        'context': {'text': ''.join(str(n) for n in range(20000))}}]}
        result = policy.request_projection(request, model, call, data)
        self.assertGreater(result['estimated_input_tokens'], 100000)
        self.assertEqual(result['estimated_rates_usd_per_million']['input'], .5)
        self.assertGreater(result['estimated_call_cost_usd'], .05)
        self.assertGreaterEqual(result['input_token_upper_bound'], result['estimated_input_tokens'])
        self.assertEqual(request, before)

    def test_images_and_missing_native_tokens_do_not_receive_fake_estimates(self):
        model = {'context_length': 1000000, 'input_usd_per_million': .1, 'output_usd_per_million': .5}
        request = {'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA'}}]}], 'max_tokens': 1000}
        call = {'id': 'paid', 'request_id': 'req', 'input_tokens': 500, 'output_tokens': 100}
        result = policy.request_projection(request, model, call, evidence())
        self.assertIsNone(result['estimated_input_tokens'])
        self.assertIsNone(result['estimated_call_cost_usd'])
        request = {'messages': []}
        call['input_tokens'] = None
        self.assertIsNone(policy.request_projection(request, model, call, evidence())['estimated_call_cost_usd'])

    def test_updated_envelope_replaces_old_addendum_without_duplicates(self):
        request = {'messages': [{'role': 'user', 'content': 'base prompt'}, *corrective_messages(evidence())]}
        projected = policy.replace_context_messages(request, evidence())
        self.assertEqual(len(projected['messages']), 3)
        self.assertEqual(projected['messages'][0]['content'], 'base prompt')
        twice = policy.replace_context_messages(projected, evidence())
        self.assertEqual(projected, twice)


    def test_rules_do_not_depend_on_domain_run_id_or_worker_name(self):
        for domain, run, worker in [('example.org', 'new-run', 'worker-a'),
                                    ('unknown.test', 'arbitrary-903', 'worker-b')]:
            state = {'domain': domain, 'run_id': run, 'iteration': 3,
                     'stagnant': 0, 'continuation_potential': True,
                     'measured_feedback': {'unmeasured_proposal': {
                         'iteration': 3, 'worker_id': worker, 'feedback': 'invalid CSS'}}}
            actual = policy.normalize_progress(state)
            self.assertFalse(actual['continuation_potential'])
            self.assertFalse(actual['last_proposal']['retained_page_changed'])
            self.assertEqual(actual['last_proposal']['worker_id'], worker)
            self.assertNotIn('selected', actual)


    def test_failed_consumption_is_not_hidden_or_double_counted(self):
        state = {'iteration': 3, 'measured_feedback': {
            'unmeasured_proposal': {'iteration': 3},
            'recent_attempts': [{'cumulative_cost_usd': .4, 'cumulative_input_tokens': 1000,
                                 'cumulative_output_tokens': 10}],
            'consumption': {'cost_usd': .6, 'input_tokens': 2000, 'output_tokens': 20}}}
        actual = policy.normalize_progress(state)
        delta = actual['last_proposal']['consumption_since_last_measured_candidate']
        self.assertAlmostEqual(delta['cost_usd'], .2)
        self.assertEqual(delta['input_tokens'], 1000)
        self.assertEqual(actual['measured_feedback']['consumption']['cost_usd'], .6)
