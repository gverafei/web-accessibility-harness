import math
import tempfile
import unittest
from harness.store import Store
from harness.progress_continuation import append,choose,supported_progress
from harness.time_policy import effective_limits,BUDGET_PROGRESS


class ProgressContinuationTests(unittest.TestCase):
    def test_candidate_retries_keep_monetary_guards_without_a_request_count_cap(self):
        import math
        from harness.time_policy import CANDIDATE_BOUNDARY
        limits = dict(max_cost_usd=1, max_call_cost_usd=.5, max_seconds=60, max_calls=24)
        effective = effective_limits(limits, {'time_policy': CANDIDATE_BOUNDARY}, 'iteration')
        self.assertTrue(math.isinf(effective['max_calls']))
        self.assertEqual(effective['max_cost_usd'], 1)
        self.assertEqual(effective['max_call_cost_usd'], .5)
        outside = effective_limits(limits, {'time_policy': CANDIDATE_BOUNDARY}, None)
        self.assertEqual(outside['max_seconds'], 60)
        self.assertEqual(limits['max_calls'], 24)

    def progress_fixture(self):
        history = []
        original = {'axe': 20, 'lighthouse': 95}
        for axe in (16, 12):
            history = append(history, original, {
                'axe': axe, 'lighthouse': 95, 'retained': True,
                'content_retention': dict(text_percent=100, links_percent=100,
                                          images_percent=100),
            })
        limits = dict(attempt_limit=10, iteration=2, run_limit_usd=5, spent_usd=.04)
        findings = dict(candidate={'axe': 12, 'lighthouse': 95},
                        functional_status='admitted', visual_status='admitted',
                        visual_impact='none', functional_reasons=[],
                        remaining_lighthouse_failures=[{
                            'audit': 'target-size', 'items': [{'selector': '#help'}]}])
        return history, limits, findings

    def test_two_preserving_gains_and_observed_targets_do_not_need_an_advisory_veto(self):
        history, limits, findings = self.progress_fixture()
        class Provider:
            campaign = 'fixture'
            def decisions(self, *args, **kwargs):
                raise AssertionError('Measured progress supplies the bounded next step')
        with tempfile.TemporaryDirectory() as tmp:
            record = choose(Store(tmp), Provider(), 'run', 'next', None,
                            history, limits, findings)
        self.assertEqual(record['data']['action'], 'continue')
        self.assertEqual(record['data']['reason'],
                         'preserving_progress_with_measured_repair_targets')
        self.assertIsNone(record['data']['answers'])

    def test_progress_guard_preserves_caps_coverage_retention_and_evidence_identity(self):
        import copy
        history, limits, findings = self.progress_fixture()
        self.assertTrue(supported_progress(history, limits, findings))
        cases = []
        for changes in ({'iteration': 10}, {'spent_usd': 5}, {'attempt_limit': None}):
            cases.append((history, {**limits, **changes}, findings))
        for changes in ({'visual_status': 'not_assessed'}, {'visual_impact': 'material'},
                        {'functional_reasons': ['broken image']},
                        {'candidate': {'axe': 11, 'lighthouse': 95}},
                        {'remaining_lighthouse_failures': [{'items': [{}]}]}):
            cases.append((history, limits, {**findings, **changes}))
        for change in ('tie', 'tradeoff', 'retention', 'unretained'):
            altered = copy.deepcopy(history)
            if change == 'retention':
                altered[-1]['content_retention']['images_percent'] = 99
            elif change == 'unretained':
                altered[-1]['retained'] = False
            else:
                altered[-1]['direction'] = change
            cases.append((altered, limits, findings))
        for number, values in enumerate(cases):
            with self.subTest(case=number):
                self.assertFalse(supported_progress(*values))

    def test_nonprogress_still_uses_and_preserves_the_recorded_advisory(self):
        history, limits, findings = self.progress_fixture()
        history[-1]['direction'] = 'tie'
        class Provider:
            campaign = 'fixture'
            def decisions(self, *args, **kwargs):
                return {'action': {'choice': 'stop'}}
        with tempfile.TemporaryDirectory() as tmp:
            record = choose(Store(tmp), Provider(), 'run', 'stopped', None,
                            history, limits, findings)
        self.assertEqual(record['data']['action'], 'stop')
        self.assertEqual(record['data']['reason'], 'recorded_decision')

    def test_only_two_consecutive_pareto_regressions_close_the_numeric_guard(self):
        original={'axe':10,'lighthouse':90};history=[]
        for current in [{'axe':12,'lighthouse':88},{'axe':8,'lighthouse':92},{'axe':9,'lighthouse':91},{'axe':11,'lighthouse':89}]:
            history=append(history,original,current)
        self.assertEqual([r['direction'] for r in history],['worse','improved','worse','worse'])
        self.assertEqual([r['consecutive_regressions']for r in history],[1,0,1,2])
        trade=append(history,original,{'axe':9,'lighthouse':87})[-1]
        self.assertEqual(trade['direction'],'tradeoff')
        self.assertEqual(trade['consecutive_regressions'],0)

    def test_progress_beyond_five_uses_recorded_decision_without_changing_money(self):
        with tempfile.TemporaryDirectory()as tmp:
            store=Store(tmp);history=[];original={'axe':10,'lighthouse':80}
            for n in range(6):history=append(history,original,{'axe':9-n,'lighthouse':81+n})
            class Provider:
                campaign='fixture'
                def decisions(self,*args,**kw):return {'action':{'choice':'continue'}}
            result=choose(store,Provider(),'run','sixth','fixture-model',history,{'iteration_reference':5,'seconds_reference':1800}, {'functional_reasons':['fixture-detail']})
            self.assertEqual(result['data']['action'],'continue')
            self.assertEqual(result['data']['history'],history)
            limits={'max_cost_usd':5,'max_call_cost_usd':5,'max_seconds':1800,'max_calls':24}
            effective=effective_limits(limits,{'time_policy':BUDGET_PROGRESS},'iteration')
            self.assertTrue(math.isinf(effective['max_seconds']))
            self.assertTrue(math.isinf(effective['max_calls']))
            self.assertEqual(effective['max_cost_usd'],5)
            self.assertEqual(effective['max_call_cost_usd'],5)
            self.assertEqual(limits['max_calls'],24)

    def test_first_regression_gets_one_correction_without_an_advisory_veto(self):
        with tempfile.TemporaryDirectory()as tmp:
            class Provider:
                campaign='fixture'
                def decisions(self,*args,**kw):raise AssertionError('No stop after the first measured candidate')
            history=append([],{'axe':10,'lighthouse':90},{'axe':12,'lighthouse':88})
            result=choose(Store(tmp),Provider(),'run','next',None,history,{}, {})
            self.assertEqual(result['data']['action'],'continue')
            history=append(history,{'axe':10,'lighthouse':90},{'axe':13,'lighthouse':87})
            result=choose(Store(tmp),Provider(),'run','last',None,history,{}, {})
            self.assertEqual(result['data']['action'],'stop')
            self.assertEqual(result['data']['reason'],'two_consecutive_audit_regressions')

    def test_clean_first_candidate_stops_without_a_paid_advisory_or_second_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Provider:
                campaign = 'fixture'
                def decisions(self, *args, **kwargs):
                    raise AssertionError('No paid advisory is necessary')
            findings = {
                'candidate': {'axe': 0, 'lighthouse': 100},
                'functional_status': 'admitted', 'functional_reasons': [],
                'visual_status': 'admitted', 'visual_impact': 'none',
                'visual_warnings': [], 'destination_repairs': [],
                'remaining_taxonomy_failures': {'Semantic': 0, 'Layout': 0},
            }
            history = append([], {'axe': 5, 'lighthouse': 88}, findings['candidate'])
            result = choose(Store(tmp), Provider(), 'run', 'after-first', None,
                            history, {'targets': {'max_axe': 5, 'min_lighthouse': 90}}, findings)
            self.assertEqual(result['data']['action'], 'stop')
            self.assertEqual(result['data']['reason'], 'targets_met_without_remaining_findings')

    def test_maximum_audit_scores_do_not_hide_remaining_review_or_taxonomy_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Provider:
                campaign = 'fixture'
                def decisions(self, *args, **kwargs):
                    raise AssertionError('First unresolved candidate gets a corrective opportunity')
            base = {
                'candidate': {'axe': 0, 'lighthouse': 100},
                'functional_status': 'admitted', 'visual_status': 'admitted',
                'visual_impact': 'none',
            }
            variants = [
                {'functional_reasons': ['broken useful image']},
                {'visual_warnings': ['overlapping controls']},
                {'remaining_taxonomy_failures': {'Semantic': 3}},
                {'destination_repairs': [{'selector': '#help'}]},
                {'visual_status': 'not_assessed'},
                {'candidate': {'axe': 7, 'lighthouse': 100}},
            ]
            history = append([], {'axe': 5, 'lighthouse': 88}, base['candidate'])
            for number, changes in enumerate(variants):
                result = choose(Store(tmp), Provider(), 'run', 'unresolved-' + str(number), None,
                                history, {'targets': {'max_axe': 5, 'min_lighthouse': 90}},
                                {**base, **changes})
                self.assertEqual(result['data']['action'], 'continue')


    def test_requested_perfect_audit_stop_keeps_findings_without_another_paid_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Provider:
                campaign = 'fixture'
                def decisions(self, *args, **kwargs):
                    raise AssertionError('The explicit stopping rule precedes paid advice')
            findings = {'candidate': {'axe': 0, 'lighthouse': 100},
                        'functional_reasons': ['broken_visible_resources'],
                        'remaining_taxonomy_failures': {'Semantic': 3}}
            result = choose(Store(tmp), Provider(), 'run', 'perfect', None,
                            [findings['candidate']], {'stop_at_perfect_audit': True}, findings)
            self.assertEqual(result['data']['action'], 'stop')
            self.assertEqual(result['data']['reason'], 'perfect_audit_stop_requested')
            self.assertEqual(result['data']['findings'], findings)


class PracticalAttemptLimitTests(unittest.TestCase):
    def test_patch_plateau_requires_actual_identical_documents_and_correction_opportunities(self):
        from harness.remediation_bridge import Bridge
        with tempfile.TemporaryDirectory() as tmp:
            bridge = Bridge.__new__(Bridge)
            bridge.store = Store(tmp)
            bridge.state = {'attempts': []}
            bridge.manifest = {'intervention_version':'two-patch-creative-regeneration-v2'}
            for number, html in enumerate((b'<html>same</html>',) * 3):
                source = bridge.store.blob(html, 'candidate_html', 'fixture', 'text/html')
                attempt = bridge.store.append('attempt', {'level': 1, 'source_id': source['id']})
                bridge.state['attempts'].append(attempt['id'])
                self.assertEqual(bridge.repeated_unchanged_documents(), number == 2)
            bridge.execution_revision = {'data': {'prior_attempt_ids': list(bridge.state['attempts'])}}
            self.assertFalse(bridge.repeated_unchanged_documents())
            bridge.execution_revision = None
            for level, html in ((2, b'<html>changed</html>'), (6, b'<html>same</html>')):
                source = bridge.store.blob(html, 'candidate_html', 'fixture', 'text/html')
                attempt = bridge.store.append('attempt', {'level': level, 'source_id': source['id']})
                bridge.state['attempts'][-1] = attempt['id']
                self.assertFalse(bridge.repeated_unchanged_documents())

    def test_identical_regeneration_documents_stop_without_another_provider_call(self):
        from harness.remediation_bridge import Bridge
        with tempfile.TemporaryDirectory() as tmp:
            from remediation_interventions import POLICIES
            for level in (policy.wire_level for policy in POLICIES):
                bridge = Bridge.__new__(Bridge)
                bridge.store = Store(tmp)
                source = bridge.store.blob(b'<html>measured</html>', 'candidate_html', 'fixture', 'text/html')
                attempts = [bridge.store.append('attempt', {'level':level, 'source_id':source['id']})['id']
                            for _ in range(3)]
                bridge.state = {'attempts':attempts}
                bridge.manifest = {'attempt_limit':10, 'intervention_version':'two-patch-creative-regeneration-v2'}
                bridge.persist = lambda:None
                self.assertEqual(bridge.begin_iteration(4), (None, None))
                self.assertIn('identical HTML', bridge.state['stop_reason_override'])

    def test_cap_stops_before_an_eleventh_call_even_with_progress(self):
        from harness.remediation_bridge import Bridge
        bridge=Bridge.__new__(Bridge)
        bridge.manifest={'attempt_limit':10}
        bridge.state={'progress_history':[{'iteration':10,'direction':'improved'}]}
        saved=[]
        bridge.persist=lambda:saved.append(dict(bridge.state))
        # No provider exists: the guard must return before any paid advisory.
        self.assertEqual(bridge.begin_iteration(11),(None,None))
        self.assertEqual(saved[0]['stop_reason_override'],'Practical repair attempt limit reached')
