import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from flask import Flask
from flask_babel import Babel
from remediation_model_choices import run_model_presentation
from routes.remediation import remediation_bp


def run(status='running'):
    return dict(id=651, status=status, source_name='https://example.test/',
        source_experiment='Acquisition', source_evaluated_at='2026-09-30',
        created_at='2026-09-30', original_axe=169, original_lighthouse=88,
        model_cost_tier='medium', generator_model='openai/gpt-6-luna',
        model_config_json=json.dumps({'model':'openai/gpt-6-luna', 'tier':'medium',
            'color':'#2f9e66','label':'GPT-6 Luna','reasoning_effort':'low'}),
        execution_mode='iterative', accessibility_priority=15,
        progress_percent=56, progress_message='Evaluating candidate 2',
        latest_actor='Evaluation team', max_axe=3, min_lighthouse=94,
        min_aim=None, latest_axe=556, latest_lighthouse=91, latest_aim=None,
        remediated_axe=555, remediated_lighthouse=95, remediated_aim=None,
        total_cost_usd=.01, execution_seconds=51.5)


class LiveHistoryTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'app/templates'))
        Babel(self.app)
        self.app.register_blueprint(remediation_bp)

    def fetch(self, row, iterations=None):
        conn = MagicMock(); cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [[row], iterations or [], []]
        with patch('routes.remediation.get_connection', return_value=conn):
            response = self.app.test_client().get('/remediation/?live_ids=651')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('WHERE rr.id IN (%s)', cursor.execute.call_args_list[0].args[0])
        self.assertEqual(cursor.execute.call_args_list[0].args[1], (651,))
        self.assertIn('WHERE run_id IN (%s)', cursor.execute.call_args_list[1].args[0])
        self.assertIn('harness_outcome_json FROM remediation_runs WHERE id IN (%s)',
                      cursor.execute.call_args_list[2].args[0])
        self.assertEqual(cursor.execute.call_args_list[2].args[1], [651])
        self.assertFalse(conn.commit.called)
        return BeautifulSoup(response.get_data(as_text=True), 'html.parser')

    def test_live_refresh_keeps_all_persisted_iteration_ids_searchable(self):
        dom = self.fetch(run(), [{'id':2110,'run_id':651,'iteration_number':1},
                                {'id':2112,'run_id':651,'iteration_number':3}])
        ids = json.loads(dom.select_one('tbody[data-history-entry]')['data-search-ids'])
        self.assertEqual(ids, {'run':'651','iterations':['2110','2112']})

    def test_running_rows_show_real_progress_not_false_success(self):
        dom = self.fetch(run())
        group = dom.select_one('tbody[data-history-entry]')
        self.assertEqual(len(group.select('tr')), 2)
        self.assertEqual(len(group.select('tr:first-child > td')), 5)
        self.assertEqual(group.select_one('.history-actions-row td')['colspan'], '5')
        self.assertFalse(group.select('[data-row-open]'))
        for button in group.select('.history-action'):
            self.assertEqual(button.select_one('span').get_text(), button['aria-label'])
        self.assertEqual(dom.select_one('tr')['data-run-status'], 'running')
        self.assertIn('56%', dom.get_text())
        self.assertIn('Evaluating candidate 2', dom.get_text())
        self.assertIn('Evaluation in progress', dom.get_text())
        self.assertNotIn('Automated scores were reached', dom.get_text())
        self.assertTrue(dom.select_one('button[type=submit]').has_attr('disabled'))
        self.assertFalse(dom.select('a.warp-export'))
        selection = dom.select_one('input[data-history-select]')
        self.assertTrue(selection.has_attr('disabled'))
        self.assertEqual(selection['form'], 'remediationExportSelection')

    def test_terminal_regression_and_frozen_model_color(self):
        dom = self.fetch(run('completed_with_warnings'))
        self.assertIn('-228.4%', dom.select_one('.remediation-metric-change.regressed').get_text())
        self.assertIn('+58.3%', dom.get_text())
        self.assertFalse(dom.select_one('button[type=submit]').has_attr('disabled'))
        self.assertIn('--tier-color:#2f9e66', dom.select_one('.remediation-model-tier')['style'])
        self.assertIn('Light', dom.select_one('.remediation-model-tier').get_text())
        self.assertIsNone(dom.select_one('.slider-chip'))
        export = dom.select_one('a.warp-export')
        self.assertEqual(export['href'], '/remediation/651/export')
        self.assertEqual(export.get_text(strip=True), 'Export data')
        self.assertTrue(export.has_attr('download'))
        selection = dom.select_one('input[data-history-select]')
        self.assertFalse(selection.has_attr('disabled'))
        self.assertEqual(selection['name'], 'run_ids')
        self.assertEqual(selection['value'], '651')
        self.assertFalse(selection.find_parent('form'))

    def test_old_export_screen_redirects_to_history_without_querying(self):
        with patch('routes.remediation.get_connection') as connection:
            response = self.app.test_client().get('/remediation/export')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/remediation/')
        connection.assert_not_called()

    def test_metric_changes_use_normal_weight_even_for_regressions(self):
        dom = self.fetch(run('completed_with_warnings'))
        for node in dom.select('.remediation-metric-change'):
            self.assertFalse(node.select('strong,b,.fw-bold'))
        css = (Path(__file__).resolve().parents[1] / 'app/static/css/style.css').read_text()
        self.assertIn('.remediation-history-table .remediation-metric-change{font-weight:400}', css)
        self.assertNotIn('.remediation-metric-change.regressed{color:#b42318;font-weight:', css)

    def test_invalid_or_unbounded_identifiers_never_query_database(self):
        with patch('routes.remediation.get_connection') as connection:
            for ids in ['', 'x', '1 OR 1=1', ','.join(['1'] * 51), '123456789012']:
                self.assertEqual(self.app.test_client().get('/remediation/', query_string={'live_ids':ids}).status_code, 400)
            connection.assert_not_called()

    def test_frozen_color_and_reasoning_are_independent_of_tier(self):
        row = run(); row['generator_model']='openai/gpt-6.1-sol'
        row['model_config_json']=json.dumps({'model':row['generator_model'], 'tier':'xhigh',
            'color':'#c3486b','label':'GPT-6.1 Sol','reasoning_effort':'low'})
        display = run_model_presentation(row)
        self.assertEqual((display['tier'],display['color'],display['reasoning_effort']), ('xhigh','#c3486b','low'))
        row['model_config_json']='[]'
        self.assertEqual(run_model_presentation(row)['tier'], 'medium')
        row['model_config_json']=json.dumps({'model':'different/model','color':'#ffffff'})
        self.assertEqual(run_model_presentation(row)['color'], '#2686c9')

    def test_invalid_color_is_not_rendered_as_style(self):
        row=run(); row['model_config_json']=json.dumps({'model':row['generator_model'], 'tier':'medium', 'color':'red;background:url(x)'})
        self.assertEqual(run_model_presentation(row)['color'], '#2686c9')
        row['model_config_json']=json.dumps({'model':row['generator_model'], 'tier':{},'label':[], 'reasoning_effort':{}})
        self.assertIsNone(run_model_presentation(row)['label'])
        self.assertIsNone(run_model_presentation(row)['reasoning_effort'])
