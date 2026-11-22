import json
import unittest
import tempfile
from unittest.mock import Mock, patch
from datetime import datetime,timedelta,timezone
from dashboard_activity import activity, build_activity
from harness.store import Store

NOW=datetime(2026,10,15,12)


def run(ident, effort, policy=15, cost=.1, axe=1):
    model='openai/gpt-6-luna'
    return dict(id=ident,source_result_id=1,created_at=NOW,status='accepted',
                generator_model=model,model_cost_tier='low',model_config_json=json.dumps({'model':model,'reasoning_effort':effort}),
                accessibility_priority=policy,intervention_version='two-patch-creative-regeneration-v2',
                execution_mode='iterative',cost=cost,seconds=20,axe=axe,lighthouse=99,
                original_axe=4,iterations=2,total_input_tokens=10,total_output_tokens=5,
                retention_json=json.dumps({'text_percent':100,'links_percent':50,'images_percent':0}))


class DashboardActivity(unittest.TestCase):
    def test_status_filter_applies_to_points_resources_and_counts_without_rewriting_outcomes(self):
        accepted = run(1, 'low')
        observed = run(876, 'high', axe=166, cost=.207)
        observed.update(status='completed_with_warnings', original_axe=29, execution_mode='single_shot')
        failed = run(3, 'low', cost=.3)
        failed.update(status='failed', axe=None)
        rows = [accepted, observed, failed]
        board = build_activity([], rows, {'status':'accepted'}, NOW)
        self.assertEqual(board['filters']['status'], 'accepted')
        self.assertEqual([p['id'] for p in board['points']], [1])
        self.assertEqual(board['totals']['runs'], 1)
        self.assertEqual(board['totals']['cost'], .1)
        warnings = build_activity([], rows, {'status':'completed_with_warnings'}, NOW)
        self.assertEqual(warnings['points'][0]['removed'], -137)
        self.assertEqual(warnings['points'][0]['policy'], 'P0')
        self.assertEqual(warnings['totals']['cost'], .207)
        all_rows = build_activity([], rows, {'status':'unknown'}, NOW)
        self.assertEqual(all_rows['filters']['status'], '')
        self.assertEqual(all_rows['totals']['runs'], 3)
        self.assertEqual(observed['axe'], 166)


    def test_scores_weight_measured_pages_and_keep_configurations_and_content_distinct(self):
        evaluations=[dict(created_at=NOW,pages=3,axe_n=2,lighthouse_n=3,axe=4,lighthouse=90,cost=0,seconds=3),
                     dict(created_at=NOW,pages=1,axe_n=1,lighthouse_n=1,axe=8,lighthouse=100,cost=0,seconds=1)]
        board=build_activity(evaluations,[run(1,'low'),run(2,'high',cost=.2,axe=6)],{},NOW)
        self.assertAlmostEqual(board['totals']['evaluation_axe'],16/3)
        self.assertEqual(board['totals']['evaluation_lighthouse'],92.5)
        self.assertEqual(board['totals']['content'],50)
        self.assertEqual(len(board['models']),2)
        self.assertAlmostEqual(sum(sum(s['cost'])for s in board['timeline']['series']),.3)
        self.assertEqual(sum(sum(s['tokens'])for s in board['timeline']['series']),30)
        self.assertEqual(sum(sum(s['input_tokens'])for s in board['timeline']['series']),20)
        self.assertEqual(sum(sum(s['output_tokens'])for s in board['timeline']['series']),10)
        self.assertEqual([p['removed']for p in board['points']],[3,-2])
        self.assertEqual(sum(item['iterations'] for item in board['models']),4)

    def test_filters_preserve_unavailable_scores_and_do_not_invent_empty_measurements(self):
        old=run(1,'low');old['created_at']=NOW-timedelta(days=9)
        current=run(2,'high');current.update(axe=None,lighthouse=None,retention_json=None)
        board=build_activity([],[old,current],{'period':'7','model':'openai/gpt-6-luna:high','policy':'P1'},NOW)
        self.assertEqual(board['totals']['runs'],1)
        self.assertIsNone(board['totals']['axe'])
        self.assertIsNone(board['totals']['content'])
        self.assertEqual(board['points'],[])
        self.assertEqual(board['models'][0]['label'],'Luna high')
        self.assertEqual(sum(board['timeline']['series'][0]['tokens']),15)
        self.assertTrue(all(x>=0 for x in board['trends']['runs']))

    def test_dynamic_campaign_is_p5_even_when_its_selected_action_is_a_fixed_strategy(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            campaign = store.append('campaign', {'conditions': [{'level': 6}]})
            fixed = run(1, 'low', cost=.1)
            dynamic = run(2, 'high', cost=.3)
            dynamic['harness_config_json'] = json.dumps({'campaign_id': campaign['id']})
            zero = run(3, 'low', cost=.05)
            zero['execution_mode'] = 'single_shot'
            for selected_priority in (15, 55):
                with self.subTest(selected_priority=selected_priority):
                    dynamic['accessibility_priority'] = selected_priority
                    cursor = Mock()
                    cursor.fetchall.side_effect = [[], [fixed, dynamic, zero]]
                    board = activity(cursor, {}, NOW, store)
                    self.assertEqual(board['policies'], ['P0', 'P1', 'P5'])
                    groups = {item['policy']: item for item in board['strategies']}
                    self.assertEqual(groups['P1']['runs'], 1)
                    self.assertEqual(groups['P5']['runs'], 1)
                    self.assertEqual(groups['P5']['cost'], .3)
                    self.assertAlmostEqual(sum(item['cost'] for item in groups.values()), .45)
                    self.assertEqual(board['totals']['runs'], 3)
                    self.assertEqual(board['points'][1]['policy'], 'P5')
                    model_groups = {item['id']: item for item in board['models']}
                    self.assertNotIn('dynamic-harness', model_groups)
                    self.assertNotIn('P5', [item['label'] for item in board['profiles']])
                    self.assertEqual(board['points'][1]['profile'], None)
                    self.assertAlmostEqual(sum(sum(item['cost']) for item in board['timeline']['series']), .15)
                    self.assertAlmostEqual(sum(sum(item['cost']) for item in board['strategy_timeline']['series']), .45)
                    self.assertEqual(model_groups['openai/gpt-6-luna:low']['runs'], 2)
                    self.assertNotIn('openai/gpt-6-luna:high', model_groups)
                    cursor.fetchall.side_effect = [[], [fixed, dynamic, zero]]
                    filtered = activity(cursor, {'policy': 'P5'}, NOW, store)
                    self.assertEqual(filtered['totals']['runs'], 1)
                    self.assertEqual(filtered['totals']['cost'], .3)
                    self.assertEqual(filtered['timeline']['series'], [])
                    self.assertEqual(filtered['models'], [])
                    self.assertEqual(sum(filtered['strategy_timeline']['series'][0]['runs']), 1)
                    self.assertEqual(filtered['strategies'][0]['iterations'], 2)

    def test_strategy_colors_are_distinct_and_resources_reconcile_without_last_worker_attribution(self):
        rows = [run(index, 'low', policy=priority) for index, priority in enumerate((15, 55, 75, 90), 1)]
        zero = run(5, 'low'); zero['execution_mode'] = 'single_shot'
        dynamic = run(6, 'high', cost=.7); dynamic['dynamic_level'] = True
        dynamic.update(status='failed', axe=None, lighthouse=None, total_input_tokens=120)
        board = build_activity([], [*rows, zero, dynamic], {}, NOW)
        groups = {item['id']: item for item in board['strategies']}
        self.assertEqual(set(groups), {'P0','P1','P2','P3','P4','P5'})
        self.assertEqual(len({item['color'] for item in groups.values()}), 6)
        self.assertNotEqual(groups['P5']['color'].lower(), '#218a79')
        for field, total in [('cost', board['totals']['remediation_cost']),
                             ('tokens', board['totals']['tokens']), ('runs', board['totals']['runs'])]:
            self.assertAlmostEqual(sum(sum(item[field]) for item in board['strategy_timeline']['series']), total)
            self.assertAlmostEqual(sum(sum(item[field]) for item in board['timeline']['series']),
                                   total - (dynamic['cost'] if field=='cost' else 125 if field=='tokens' else 1))
        self.assertEqual(groups['P5']['runs'], 1)
        self.assertEqual(groups['P5']['cost'], .7)
        self.assertEqual(len(board['points']), 5)


if __name__=='__main__':
    unittest.main()
