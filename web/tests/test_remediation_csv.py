import copy
import csv
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from remediation_csv import FIELDS, remediation_csv


class RemediationCsvTests(unittest.TestCase):
    def test_dynamic_run_identity_remains_distinct_from_the_executed_strategy(self):
        self.run.update(dynamic_level=True, accessibility_priority=55,
                        intervention_version='two-patch-creative-regeneration-v2')
        strategy = json.loads(self.iterations[0]['strategy_json'])
        strategy.update(assigned_level=2, wire_level=3)
        self.iterations[0]['strategy_json'] = json.dumps(strategy)
        rows = self.rows(remediation_csv(self.run, self.source, self.iterations))
        self.assertEqual({row['run_strategy'] for row in rows}, {'P5'})
        self.assertEqual(rows[1]['assigned_level'], '2')
        self.assertEqual(rows[1]['wire_level'], '3')
        self.assertEqual(rows[1]['run_accessibility_priority'], '55')

    def test_evaluable_fragment_keeps_its_measured_scores(self):
        self.iterations[0]['strategy_json']={'baseline':{'evaluable':True,
            'complete_document':False,'format':'html-fragment'}}
        row=self.rows(remediation_csv(self.run,self.source,self.iterations))[1]
        self.assertEqual(row['proposal_document_status'],'partial_document')
        self.assertEqual(row['axe_issue_instances'],'3')
        self.assertEqual(row['lighthouse_score'],'93')

    def test_unavailable_response_exports_cost_without_candidate_or_page_metrics(self):
        self.run.update(execution_mode='single_shot', accepted_iteration_id=None,
            harness_outcome_json={'selected':{'original':False},
                'output_evidence':{'evaluable':False}, 'stop_reason':'Response unavailable'})
        rows=self.rows(remediation_csv(self.run,self.source,[]))
        self.assertEqual([r['row_kind']for r in rows],['original','unavailable_output'])
        missing=rows[1]
        self.assertEqual(missing['proposal_document_status'],'response_unavailable')
        self.assertEqual(missing['cost_usd'],'0.00298868')
        self.assertEqual(missing['iteration_number'],'')
        self.assertEqual(missing['axe_issue_instances'],'')
        self.assertEqual(missing['lighthouse_score'],'')

    def test_plain_taxonomy_counts_export_original_and_retained_only(self):
        self.run['harness_outcome_json']=json.dumps({'selected':{'original':False},'taxonomy_measurement':{
            'original':{'categories':{'Syntactic':{'failed':4,'judged':115},'Semantic':{'failed':2,'judged':17,'unassessed':71},'Layout':{'failed':39,'judged':132}}},
            'retained':{'categories':{'Syntactic':{'failed':0,'judged':123},'Semantic':{'failed':4,'judged':16,'unassessed':75},'Layout':{'failed':13,'judged':152}}}}})
        rows=self.rows(remediation_csv(self.run,self.source,self.iterations))
        self.assertEqual(rows[0]['taxonomy_layout_failures'],'39')
        self.assertEqual(rows[1]['taxonomy_layout_failures'],'13')
        self.assertEqual(rows[1]['taxonomy_semantic_failures'],'4')
        self.assertEqual(rows[2]['taxonomy_layout_failures'],'')

    def setUp(self):
        self.run = {'id': 21, 'source_result_id': 11, 'title': 'Repair, "UV" á',
                    'status': 'completed_with_warnings', 'accepted_iteration_id': 31,
                    'total_cost_usd': Decimal('0.00298868'), 'execution_seconds': 26.0,
                    'total_input_tokens': 100, 'total_output_tokens': 20,
                    'max_cost_usd': Decimal('0.25'), 'max_execution_seconds': 360,
                    'use_rag': True, 'error_message': 'Timeout after best candidate'}
        self.source = {'id': 11, 'experiment_id': 5, 'url': 'https://www.uv.mx/',
                       'axe_violations': 24, 'axe_wcag_violations': 14,
                       'axe_best_practice_issues': 10, 'lighthouse_score': 93}
        self.iterations = [
            {'id': 31, 'iteration_number': 1, 'decision': 'refine',
             'decision_reason': 'Targets not met', 'generator_model': 'openai/gpt-6-luna',
             'axe_violations': 10, 'axe_wcag_violations': 3, 'axe_best_practice_issues': 7,
             'lighthouse_score': 93, 'wave_aim_score': None, 'cost_usd': Decimal('0.00298868'),
             'execution_seconds': 26.0, 'input_tokens': 100, 'output_tokens': 20,
             'strategy_json': json.dumps({'rag': {'enabled': True, 'retrieved': []},
                 'content_retention': {'text_percent': 100, 'links_percent': 90, 'images_percent': 80}})},
            {'id': 32, 'iteration_number': 2, 'decision': 'rollback', 'axe_wcag_violations': 0,
             'axe_best_practice_issues': 0, 'lighthouse_score': None,
             'strategy_json': {'rag': {'retrieved': [{'rule_id': 'one'}, {'rule_id': 'two'}]}}},
        ]

    def rows(self, text):
        return list(csv.DictReader(StringIO(text.lstrip('\ufeff'))))

    def test_original_and_all_iterations_keep_wcag_costs_and_retained_link(self):
        before = copy.deepcopy((self.run, self.source, self.iterations))
        text = remediation_csv(self.run, self.source, self.iterations)
        self.assertTrue(text.startswith('\ufeff'))
        rows = self.rows(text)
        self.assertEqual(tuple(rows[0]), FIELDS)
        self.assertEqual([row['row_kind'] for row in rows], ['original', 'iteration', 'iteration'])
        self.assertEqual([row['axe_issue_instances'] for row in rows], ['14', '3', '0'])
        self.assertEqual([row['axe_best_practice_issues'] for row in rows], ['10', '7', '0'])
        self.assertEqual([row['is_retained'] for row in rows], ['False', 'True', 'False'])
        self.assertEqual(rows[1]['cost_usd'], '0.00298868')
        self.assertEqual(rows[1]['run_total_cost_usd'], '0.00298868')
        self.assertEqual(rows[1]['run_max_execution_seconds'], '360')
        self.assertEqual(rows[1]['content_retention_percent'], '90.0')
        self.assertEqual(rows[1]['run_title'], 'Repair, "UV" á')
        self.assertEqual(rows[2]['run_error_message'], 'Timeout after best candidate')
        self.assertEqual((self.run, self.source, self.iterations), before)

    def test_coordinator_retention_overrides_historical_sql_link(self):
        from remediation_report_presentation import retained_summary, iteration_ordinals
        self.iterations[0]['iteration_number'] = 3
        self.iterations[1]['iteration_number'] = 7
        self.run.update(max_axe=5,min_lighthouse=90,accepted_iteration_id=32,
            harness_outcome_json=json.dumps({'selected':{'original':False,'audit_id':'sql-run-21-attempt-2-audit'},'axe':3,'lighthouse':93}))
        summary=retained_summary(self.run,self.iterations)
        self.assertEqual(summary['id'],31)
        rows=self.rows(remediation_csv(self.run,self.source,self.iterations))
        self.assertEqual([r['is_retained'] for r in rows],['False','True','False'])
        self.assertEqual([r['iteration_number'] for r in rows], ['', '1', '2'])
        self.assertEqual(iteration_ordinals(list(reversed(self.iterations))), {31: 1, 32: 2})
        self.assertEqual([item['iteration_number'] for item in self.iterations], [3, 7])
        self.assertEqual(self.run['accepted_iteration_id'],32) # immutable historical record

    def test_rejected_regression_exports_proposal_measurement_not_retained_original(self):
        self.run.update(accepted_iteration_id=None,harness_outcome_json={'selected':{'original':True}})
        self.iterations[0]['axe_wcag_violations']=20
        self.iterations[0]['lighthouse_score']=80
        rows=self.rows(remediation_csv(self.run,self.source,self.iterations))
        self.assertEqual(rows[0]['experiment_role'],'baseline')
        self.assertEqual(rows[1]['experiment_role'],'generated_proposal')
        self.assertEqual(rows[1]['axe_issue_instances'],'20')
        self.assertLess(float(rows[1]['axe_reduction_percent']),0)
        self.assertLess(float(rows[1]['lighthouse_increase_percent']),0)
        self.assertEqual(rows[0]['is_retained'],'True')
        self.assertEqual(rows[1]['is_retained'],'False')

    def test_historical_prose_score_is_raw_evidence_without_page_result(self):
        self.iterations[0].update(axe_wcag_violations=2,lighthouse_score=50,
            strategy_json={'baseline':{'output':'raw zero-shot response recorded; no unique complete HTML document'}})
        rows=self.rows(remediation_csv(self.run,self.source,self.iterations))
        self.assertEqual(rows[1]['proposal_document_status'],'no_complete_document')
        self.assertEqual(rows[1]['raw_axe_issue_instances'],'2')
        self.assertEqual(rows[1]['raw_lighthouse_score'],'50')
        for key in ('axe_issue_instances','lighthouse_score','axe_reduction_percent','lighthouse_increase_percent','targets_met'):
            self.assertEqual(rows[1][key],'')

    def test_null_metrics_and_missing_rag_are_not_measured_zeros(self):
        self.source['axe_wcag_violations'] = None
        self.run['accepted_iteration_id'] = None
        self.iterations[1]['strategy_json'] = 'invalid json'
        rows = self.rows(remediation_csv(self.run, self.source, self.iterations))
        self.assertEqual(rows[0]['axe_issue_instances'], '')
        self.assertEqual(rows[2]['lighthouse_score'], '')
        self.assertEqual(rows[1]['wave_aim_score'], '')
        self.assertEqual(rows[1]['rag_used'], 'False')
        self.assertEqual(rows[1]['rag_example_count'], '0')
        self.assertEqual(rows[2]['rag_used'], '')
        self.assertEqual(rows[2]['rag_example_count'], '')
        self.assertEqual(rows[1]['is_retained'], '')

    def test_taxonomy_export_only_describes_assessed_documents_and_retained_original(self):
        self.run['harness_outcome_json']=json.dumps({'selected':{'original':True},'distance':0,
            'taxonomy_measurement':{'version':'taxonomy-test','status':'completed',
                'original_assessment_id':'same','retained_assessment_id':'same',
                'original':{'categories':{}},'retained':{'categories':{}},
                'comparison':{'excluded_original_ids':['ambiguous']},
                'measurement_cost_usd':0.01,'shared_baseline_cost_usd':0.01}})
        self.run['accepted_iteration_id']=None
        rows=self.rows(remediation_csv(self.run,self.source,self.iterations))
        self.assertEqual(rows[0]['is_retained'],'True')
        self.assertEqual(rows[0]['dom_distance_percent'],'0.0')
        self.assertEqual(rows[0]['taxonomy_assessment_id'],'same')
        self.assertEqual(json.loads(rows[0]['taxonomy_comparison_json'])['excluded_original_ids'],['ambiguous'])
        self.assertEqual(rows[1]['taxonomy_summary_json'],'')

    def test_rag_enabled_is_distinct_from_retrieved_examples(self):
        rows = self.rows(remediation_csv(self.run, self.source, self.iterations))
        self.assertEqual(rows[1]['run_use_rag'], 'True')
        self.assertEqual(rows[1]['rag_used'], 'False')
        self.assertEqual(rows[2]['rag_used'], 'True')
        self.assertEqual(rows[2]['rag_example_count'], '2')

    def test_recovered_accounting_is_blank_while_run_totals_remain(self):
        self.iterations[0]['strategy_json'] = {'recovery': {'source': 'old export'}}
        rows = self.rows(remediation_csv(self.run, self.source, self.iterations))
        self.assertEqual(rows[1]['evidence_recovered'], 'True')
        for field in ('input_tokens', 'output_tokens', 'cost_usd', 'execution_seconds',
                      'run_total_input_tokens', 'run_total_output_tokens'):
            self.assertEqual(rows[1][field], '', field)
        self.assertEqual(rows[1]['run_total_cost_usd'], '0.00298868')
        self.assertEqual(rows[1]['run_execution_seconds'], '26.0')

    def test_formula_like_text_is_escaped_but_numeric_values_are_unchanged(self):
        for title in ('=1+1', ' +SUM(1,2)', '-1+1', '@command', '\tformula', '\nformula'):
            with self.subTest(title=title):
                self.run['title'] = title
                self.iterations[0]['dom_distance'] = -1.5
                rows = self.rows(remediation_csv(self.run, self.source, self.iterations))
                self.assertEqual(rows[0]['run_title'], "'" + title)
                self.assertEqual(rows[1]['dom_distance_percent'], '-1.5')

    def test_no_iterations_still_exports_original_and_run_failure(self):
        self.run['status'] = 'failed'
        rows = self.rows(remediation_csv(self.run, self.source, []))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['run_status'], 'failed')

    def route_app(self):
        from flask import Flask
        from routes.remediation import remediation_bp
        app = Flask(__name__)
        app.register_blueprint(remediation_bp)
        return app

    def test_route_downloads_only_recorded_data_with_no_external_calls_or_writes(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [self.run, self.source]
        cursor.fetchall.return_value = self.iterations
        with patch('routes.remediation.get_connection', return_value=conn), \
             patch('requests.post', side_effect=AssertionError('No paid calls')):
            response = self.route_app().test_client().get('/remediation/21/csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertEqual(response.headers['Content-Disposition'], 'attachment; filename="remediation-21.csv"')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(self.rows(response.data.decode('utf-8-sig'))), 3)
        for call in cursor.execute.call_args_list:
            self.assertTrue(call.args[0].startswith('SELECT'))
        conn.commit.assert_not_called()
        cursor.close.assert_called_once()
        conn.close.assert_called_once()

    def test_route_missing_run_or_source_is_404_and_closes_database(self):
        for records in ([None], [self.run, None]):
            with self.subTest(records=records):
                conn = MagicMock()
                cursor = conn.cursor.return_value
                cursor.fetchone.side_effect = records
                with patch('routes.remediation.get_connection', return_value=conn):
                    response = self.route_app().test_client().get('/remediation/21/csv')
                self.assertEqual(response.status_code, 404)
                cursor.fetchall.assert_not_called()
                cursor.close.assert_called_once()
                conn.close.assert_called_once()

    def test_route_closes_database_if_iteration_query_fails(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [self.run, self.source]
        cursor.fetchall.side_effect = RuntimeError('database unavailable')
        app = self.route_app()
        app.testing = True
        with patch('routes.remediation.get_connection', return_value=conn):
            with self.assertRaisesRegex(RuntimeError, 'database unavailable'):
                app.test_client().get('/remediation/21/csv')
        cursor.close.assert_called_once()
        conn.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
