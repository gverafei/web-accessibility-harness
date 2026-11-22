import json
import unittest
from unittest.mock import MagicMock
from summary_metrics import evaluation_metrics, remediation_metrics, observed_reducer_rankings, evaluation_run_summary, score_number


class SummaryMetricsTests(unittest.TestCase):
    def test_averages_use_completed_measurements_and_selected_remediations(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'average_axe': 3.5, 'average_lighthouse': 96}
        self.assertEqual(evaluation_metrics(cursor)['average_axe'], 3.5)
        self.assertIn("status='completed'", cursor.execute.call_args.args[0])
        self.assertEqual(remediation_metrics(cursor)['average_lighthouse'], 96)
        self.assertIn('ri.id=rr.accepted_iteration_id', cursor.execute.call_args.args[0])

    def test_origin_counts_partition_evaluations_and_time_uses_all_runs(self):
        rows = [dict(source_type='url', urls='https://example.org', execution_seconds=2),
                dict(source_type='url', urls='http://127.0.0.1:80', execution_seconds=3),
                dict(source_type='local_html', execution_seconds=5),
                dict(source_type='tranco', execution_seconds=7),
                dict(source_type='tranco', experiment_origin='imported', execution_seconds=0),
                dict(source_type='local_html', experiment_origin='composed', execution_seconds=0)]
        result = evaluation_run_summary(rows)
        self.assertEqual(result['source_counts'], dict(url=1, local=1, html=1, tranco=1, imported=1, combined=1))
        self.assertEqual(result['total_seconds'], 17)
        self.assertEqual(score_number(92.0), '92')
        self.assertEqual(score_number(92.5), '92.5')
        self.assertEqual(score_number(None), '—')

    def test_strategy_ranking_weights_issues_keeps_regressions_and_excludes_legacy(self):
        rows = [
            dict(presentation_level=1, preservation_filter='current-15', original_axe=10, result_axe=5),
            dict(presentation_level=1, preservation_filter='current-15', original_axe=90, result_axe=90),
            dict(presentation_level=2, preservation_filter='current-55', original_axe=10, result_axe=8),
            dict(presentation_level=3, preservation_filter='current-75', original_axe=10, result_axe=15),
            dict(presentation_level=5, preservation_filter='90', original_axe=1000, result_axe=0),
        ]
        rows.extend(dict(presentation_level=p, preservation_filter='current-55',original_axe=90,result_axe=90) for p in (2,3))
        for row in rows:
            row.update(generator_model='openai/gpt-6-luna',model_presentation={'reasoning_effort':'low'},source_result_id=2 if row['original_axe']==90 else 1)
        rows.append(dict(execution_mode='single_shot', presentation_level=1, preservation_filter='current-15', original_axe=999, result_axe=0))
        ranking = observed_reducer_rankings(rows, strategies=True)["reduction"]
        self.assertEqual([item['label'] for item in ranking], ['P1', 'P2', 'P3'])
        self.assertEqual([item['score'] for item in ranking], [5, 2, -5])
        self.assertEqual(observed_reducer_rankings([])["reduction"], [])

    def test_model_rankings_separate_reasoning_and_count_regressions_in_value(self):
        rows = [dict(generator_model='openai/gpt-6-luna', model_presentation={'label':'Luna','reasoning_effort':effort},
                     source_result_id=source,presentation_level=1,preservation_filter='current-15',
                     original_axe=10,result_axe=result,total_cost_usd=cost)
                for effort,source,result,cost in [('low',1,5,.1),('low',2,12,.1),('high',1,0,.5),('high',2,0,.5)]]
        rows.append(dict(rows[0], execution_mode='single_shot', result_axe=10))
        rankings = observed_reducer_rankings(rows)
        self.assertEqual([r['label'] for r in rankings['reduction']], ['Luna high', 'Luna light'])
        self.assertEqual([r['label'] for r in rankings['value']], ['Luna high', 'Luna light'])
        self.assertEqual([r['score'] for r in rankings['reduction']], [20, 3])
        self.assertAlmostEqual(rankings['value'][1]['score'], 10)
        self.assertEqual(rankings['reduction'][1]['runs'], 3)

    def test_content_ranking_reports_retention_with_audit_and_cost_tiebreaks(self):
        def result(level, retained, axe, cost):
            return dict(generator_model='openai/gpt-6-luna',model_presentation={'reasoning_effort':'low'},source_result_id=1,
                        presentation_level=level, preservation_filter='current-15',
                        original_axe=10, result_axe=axe, total_cost_usd=cost,
                        accepted_strategy_json=json.dumps({'content_retention':dict(
                            text_percent=retained, links_percent=retained, images_percent=retained,
                            dynamic_images_percent=0)}))
        rows=[result(1,100,2,.10), result(2,100,1,.20),
              result(3,80,0,.01), result(4,100,1,.10)]
        rows.append(dict(rows[0], execution_mode='single_shot'))
        ranking=observed_reducer_rankings(rows,strategies=True)['content']
        self.assertEqual([r['label'] for r in ranking],['P4','P2','P0','P1','P3'])
        self.assertEqual([r['score'] for r in ranking],[100,100,100,100,80])
        self.assertEqual(ranking[0]['content_runs'],1)
        self.assertEqual(observed_reducer_rankings([dict(rows[0],accepted_strategy_json='{}')],strategies=True)['content'],[])

    def test_confirmed_zero_cost_corrections_contribute_to_total_efficiency(self):
        base=dict(generator_model='provider/model',model_presentation={},source_result_id=1,
                  presentation_level=1,preservation_filter='current-15',original_axe=10)
        rows=[dict(base,result_axe=0,total_cost_usd=0),
              dict(base,source_result_id=2,result_axe=5,total_cost_usd=1)]
        ranking=observed_reducer_rankings(rows)
        self.assertEqual(ranking['value'][0]['score'],15)

    def test_dynamic_results_have_their_own_strategy_and_never_enter_fixed_model_rankings(self):
        fixed = dict(generator_model='openai/gpt-6-luna', model_presentation={'reasoning_effort': 'low'},
                     source_result_id=1, presentation_level=2, preservation_filter='current-55',
                     original_axe=10, result_axe=5, total_cost_usd=.1,
                     accepted_strategy_json=json.dumps({'content_retention': {
                         'text_percent': 100, 'links_percent': 100, 'images_percent': 100}}))
        dynamic = dict(fixed, dynamic_level=True, result_axe=0, total_cost_usd=.4)
        ranking = observed_reducer_rankings([fixed, dynamic], strategies=True)
        self.assertEqual(ranking['coverage']['levels'], [2, 5])
        self.assertEqual([(item['label'], item['runs'], item['score']) for item in ranking['reduction']],
                         [('P5', 1, 100), ('P2', 1, 50)])
        self.assertEqual([(item['label'], item['score']) for item in ranking['value']],
                         [('P2', 50), ('P5', 25)])
        self.assertEqual([item['label'] for item in ranking['content']], ['P5', 'P2'])
        model = observed_reducer_rankings([fixed, dynamic])
        self.assertEqual(model['coverage']['runs'], 1)
        self.assertEqual(model['reduction'][0]['removed'], 5)

    def test_all_models_keep_counts_and_volume_differs_from_efficiency(self):
        rows=[]
        for model in ('openai/luna','anthropic/haiku'):
            for source in (1,2):
                for level in (1,2,3,4):
                    rows.append(dict(generator_model=model,model_presentation={'reasoning_effort':'low'},
                                     source_result_id=source,presentation_level=level,preservation_filter='current-15',
                                     original_axe=10,result_axe=2,total_cost_usd=.1))
        rows.append(dict(rows[0],generator_model='anthropic/opus',result_axe=0,total_cost_usd=.01))
        ranking=observed_reducer_rankings(rows)
        self.assertEqual(ranking['coverage']['models'],3)
        self.assertEqual(ranking['coverage']['runs'],17)
        self.assertEqual([r['score'] for r in ranking['reduction']],[64,64,10])
        self.assertEqual([r['runs'] for r in ranking['reduction']],[8,8,1])
        self.assertEqual(ranking['value'][0]['label'],'opus light')
        self.assertEqual(ranking['value'][0]['runs'],1)
        self.assertEqual(ranking['value'][0]['score'],1000)
        strategies=observed_reducer_rankings(rows,strategies=True)
        self.assertEqual(strategies['reduction'][0]['runs'],5)
        self.assertEqual(strategies['reduction'][0]['score'],84)
        self.assertEqual(observed_reducer_rankings([rows[-1]])['reduction'][0]['score'],10)
