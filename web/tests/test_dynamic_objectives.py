"""P5 must see and act on contextual defects even at perfect audit scores."""
import json
import unittest
from unittest.mock import patch

from harness.contracts import ContractError
from harness.dynamic_objectives import (
    contextual_gain, corrective_evidence, corrective_messages,
    prefer_contextual_candidate, taxonomy_view,
    remaining_context,
)
from harness.selection import select
from remediation_interventions import VERSION


def categories(semantic=2, coverage=1):
    return {name: {'failed': semantic if name == 'Semantic' else 0, 'coverage': coverage}
            for name in ('Syntactic', 'Semantic', 'Layout')}


def experience():
    cases = []
    for policy in ('P1', 'P2', 'P3', 'P4'):
        cases.append({'evidence': {
            'policy': policy, 'worker_id': 'high', 'model_profile': 'Luna high',
            'baseline': {'axe': 0, 'lighthouse': 100},
            'candidate': {'axe': 0, 'lighthouse': 100},
            'content_retention_percent': 100 if policy in ('P1', 'P2') else 75,
            'cost_usd': .02, 'attempt_count': 2, 'seconds': 40,
            'trajectory': [[0, 100, True], [0, 100, True]],
            **taxonomy_view(categories(1)),
            'original_taxonomy': taxonomy_view(categories(2)),
        }})
    return {'id': 'retrieval', 'data': {
        'included': cases, 'matching_scope': 'exact-source calibration',
        'source_sha256': 'source', 'library_hash': 'library', 'playbook': {'reference': 'hidden'},
    }}


class DynamicObjectiveTests(unittest.TestCase):
    def test_page_guided_continuation_shares_all_repeated_evidence(self):
        from copy import deepcopy
        from harness.planning_evidence import expanded_feedback

        class Provider:
            store = object()

            def decisions(self, run, stage, key, evidence, questions):
                self.evidence = json.loads(evidence)
                return {'action': {'choice': 'P2:worker'}}

        provider = Provider()
        manifest = {'intervention_version': VERSION, 'record_experience': False,
                    'workers': [{'id': 'worker', 'model': 'openai/gpt-6-luna',
                                 'reasoning_effort': 'low'}]}
        page_text = 'Visible page content with headings, links and controls. ' * 300
        feedback = {'remaining_taxonomy_failures': {'Semantic': 3},
                    'contextual_findings': {'failed_opportunities': [
                        {'identity': index, 'text': page_text, 'status': 'failed'}
                        for index in range(3)]}}
        state = {'iteration': 1, 'axe': 0, 'lighthouse': 99,
                 'measured_feedback': feedback}
        untouched = deepcopy(state)
        result = select(provider, 'run', 'continuation', manifest,
                        {'level': 6, 'selector': 'decisions'}, {}, state)
        supplied = provider.evidence['state']['measured_feedback']
        self.assertEqual(expanded_feedback(supplied), feedback)
        self.assertEqual(state, untouched)
        self.assertLess(len(json.dumps(supplied)), len(json.dumps(feedback)) / 2)
        self.assertNotIn('measured_experience', provider.evidence)
        self.assertEqual(result['selected'], 'P2:worker')
        self.assertIn('stop', result['available'])

    def test_page_guided_selection_excludes_other_run_outcomes(self):
        class Provider:
            store = object()

            def decisions(self, run, stage, key, evidence, questions):
                self.evidence = json.loads(evidence)
                self.questions = questions
                return {'action': {'choice': 'P2:worker'}}

        provider = Provider()
        manifest = {'intervention_version': VERSION, 'record_experience': False,
                    'workers': [{'id': 'worker', 'model': 'openai/gpt-6-luna',
                                 'reasoning_effort': 'low'}]}
        state = {'iteration': 0, 'axe': 10, 'lighthouse': 91}
        result = select(provider, 'run', 'choice', manifest,
                        {'level': 6, 'selector': 'decisions'},
                        {'source_url': 'https://example.org/'}, state)
        self.assertEqual(result['selected'], 'P2:worker')
        self.assertEqual(len(result['available']), 4)
        self.assertNotIn('measured_experience', provider.evidence)
        self.assertNotIn('source_matched_route_comparison', provider.evidence)
        self.assertNotIn('route_plan', result)
        action = next(q for q in provider.questions if q['name'] == 'action')
        self.assertIn('No previous remediation outcomes are supplied', action['instructions'])
        self.assertNotIn('historical', action['instructions'])

    def test_admitted_minor_difference_does_not_request_a_speculative_dynamic_repair(self):
        from harness.progress_continuation import completed_objective
        report = {'candidate':{'axe':0,'lighthouse':100}, 'functional_status':'admitted',
                  'visual_status':'admitted', 'visual_impact':'minor',
                  'visual_warnings':['minor_visual_finding'],
                  'remaining_taxonomy_failures':{'Syntactic':0,'Semantic':0,'Layout':0}}
        targets = {'max_axe':0,'min_lighthouse':100}
        # The fixed comparator retains its existing stopping contract.
        self.assertFalse(completed_objective(report, targets))
        self.assertTrue(completed_objective(report, targets, allow_minor_visual=True))
        for changes in ({'visual_impact':'material'}, {'visual_status':'not_assessed'},
                        {'visual_warnings':['overlapping_controls']},
                        {'functional_reasons':['broken_image']},
                        {'remaining_taxonomy_failures':{'Semantic':1}},
                        {'remaining_lighthouse_failures':['heading_order']},
                        {'destination_repairs':[{'selector':'a'}]}):
            self.assertFalse(completed_objective({**report, **changes}, targets,
                                                allow_minor_visual=True))
        self.assertTrue(remaining_context({'contextual_findings':{
            'unresolved_prior_findings':[{'status':'unassessed'}]}}))

    def test_failed_to_unassessed_remains_unresolved_with_current_evidence(self):
        from types import SimpleNamespace
        prior = {'opportunity_id': 'heading', 'identity_basis': 'h1:Welcome',
                 'type': 'heading-not-descriptive', 'status': 'failed'}
        current = dict(prior, status='insufficient_evidence',
                       context={'element': {'attributes': {'aria-label': 'University: Welcome'}}})
        records = {
            'original': {'id': 'original', 'data': {'opportunities': [prior]}},
            'candidate': {'id': 'candidate', 'data': {'opportunities': [current]}},
        }
        store = SimpleNamespace(get=lambda ident: records[ident])
        measurement = {'status': 'completed', 'original_assessment_id': 'original',
                       'retained_assessment_id': 'candidate', 'retained': {'categories': categories(0)}}
        evidence = corrective_evidence(store, measurement)
        self.assertEqual(evidence['failed_opportunities'], [])
        self.assertEqual(evidence['unresolved_prior_findings'][0]['current_opportunity'], current)
        self.assertTrue(remaining_context({'contextual_findings': evidence}))
        self.assertIn('not a confirmed', corrective_messages(evidence)[0]['content'])
        records['candidate']['data']['opportunities'][0] = dict(current, status='passed')
        resolved = corrective_evidence(store, measurement)
        self.assertFalse(remaining_context({'contextual_findings': resolved}))
        self.assertEqual(corrective_messages(resolved), [])



    def test_contextual_gain_breaks_audit_tie_without_rewarding_missing_coverage(self):
        before, after = taxonomy_view(categories(2)), taxonomy_view(categories(1))
        self.assertTrue(contextual_gain(before, after))
        self.assertFalse(contextual_gain(before, taxonomy_view(categories(1, .5))))
        after['taxonomy_failed']['Layout'] = 1
        self.assertFalse(contextual_gain(before, after))

    def test_taxonomy_improvement_cannot_replace_lost_content(self):
        def report(n):
            return {'candidate': {'axe': 0, 'lighthouse': 100},
                    'remaining_taxonomy_failures': taxonomy_view(categories(n))['taxonomy_failed'],
                    'taxonomy_coverage': taxonomy_view(categories(n))['taxonomy_coverage']}
        retention = dict.fromkeys(('text_percent', 'links_percent', 'images_percent'), 100)
        self.assertTrue(prefer_contextual_candidate(report(1), report(2), retention, retention))
        self.assertFalse(prefer_contextual_candidate(report(1), report(2),
                         dict(retention, images_percent=90), retention))
        uncertain = dict(report(0), unresolved_prior_finding_count=1)
        resolved = dict(report(0), unresolved_prior_finding_count=0)
        self.assertTrue(prefer_contextual_candidate(resolved, uncertain, retention, retention))
        self.assertFalse(prefer_contextual_candidate(uncertain, resolved, retention, retention))
        self.assertFalse(prefer_contextual_candidate(uncertain,
                         dict(report(1), unresolved_prior_finding_count=0), retention, retention))

    def test_failed_evidence_reaches_worker_and_survives_cached_reuse(self):
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bridge = fixture.bridge()
        bridge.manifest['intervention_version'] = VERSION
        bridge.manifest['decision_model'] = fixture.workers[0]
        failed = {'opportunity_id': 'heading-1', 'status': 'failed',
                  'type': 'heading-not-descriptive', 'context': {'element': {'tag': 'h1', 'text': 'Welcome'}}}
        assessment = bridge.store.append('taxonomy_assessment', {
            'document_sha256': 'fixture-document', 'opportunities': [failed]}, bridge.cid)
        measurement = {'status': 'completed', 'retained_assessment_id': assessment['id'],
                       'retained': {'categories': categories()}}
        with patch('accessibility_taxonomy.assessment.measure_pair', return_value=measurement) as measured:
            bridge.prepare_dynamic_context()
            bridge.prepare_dynamic_context()
        self.assertEqual(measured.call_count, 1)
        self.assertEqual(bridge.dynamic_selection_feedback()['remaining_taxonomy_failures']['Semantic'], 2)
        messages = corrective_messages(bridge.state['current_contextual_evidence'])
        self.assertIn('heading-not-descriptive', messages[1]['content'])
        self.assertIn('untrusted', messages[0]['content'])
        self.assertEqual(json.loads(messages[1]['content'].split('\n', 1)[1])['failed_opportunities'], [failed])
        with patch('accessibility_taxonomy.assessment.measure_pair', side_effect=AssertionError('Reuse the saved findings')):
            bridge.begin_iteration(1)
            bridge.transport({'model': bridge.worker['model'],
                              'messages': [{'role': 'user', 'content': 'Repair the fixture'}], 'max_tokens': 100})
        self.assertIn('heading-not-descriptive', json.dumps(fixture.session.requests[-1]['messages']))
        with self.assertRaises(ContractError):
            corrective_evidence(bridge.store, {'status': 'not_assessed'})


    def test_stalled_contextual_actions_stay_blocked_without_history(self):
        class Provider:
            def decisions(self, run, stage, key, evidence, questions):
                return {'action': {'choice': 'P2:high'}}
        manifest = {'intervention_version': VERSION,
                    'workers': [{'id': 'high', 'model': 'openai/gpt-6-luna', 'reasoning_effort': 'high'}]}
        state = {'iteration': 3, 'axe': 0, 'lighthouse': 100, 'blocked_actions': ['P1:high'],
                 'measured_feedback': {'remaining_taxonomy_failures': {'Semantic': 2}}}
        result = select(Provider(), 'run', 'choice', manifest, {'level':6, 'selector':'decisions'}, {}, state)
        self.assertNotIn('P1:high', result['available'])
        self.assertEqual(result['selected'], 'P2:high')

    def test_contextual_stop_requires_explanation_in_saved_decision(self):
        class Provider:
            def chat(self, *args, **kwargs):
                return json.dumps(self.answer)
        provider = Provider()
        provider.answer = {'action': 'stop', 'topic': 'education',
                           'purpose': 'homepage', 'repair_context': 'isolated'}
        manifest = {'intervention_version': VERSION, 'orchestrator': {'id': 'planner'},
                    'workers': [{'id': 'worker'}]}
        state = {'iteration': 2, 'axe': 0, 'lighthouse': 100,
                 'measured_feedback': {'remaining_taxonomy_failures': {'Semantic': 2}}}
        with self.assertRaisesRegex(ContractError, 'concrete recorded reason'):
            select(provider, 'run', 'choice', manifest, {'level': 6, 'selector': 'structured'}, {}, state)
        provider.answer['stop_reason'] = 'Both remaining descriptions require image details unavailable in the frozen evidence; no grounded edit remains.'
        result = select(provider, 'run', 'choice', manifest, {'level': 6, 'selector': 'structured'}, {}, state)
        self.assertEqual(result['stop_reason'], provider.answer['stop_reason'])


if __name__ == '__main__':
    unittest.main()
