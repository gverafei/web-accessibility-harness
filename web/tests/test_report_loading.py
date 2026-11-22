import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import render_template


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

if "database" not in sys.modules:
    database_stub = types.ModuleType("database")
    database_stub.init_db = lambda: None
    database_stub.get_connection = lambda: None
    sys.modules["database"] = database_stub

main = importlib.import_module("main")


class LoadingReportTestCase(unittest.TestCase):
    def test_global_search_results_use_loading_for_evaluations_and_urls(self):
        routes = importlib.import_module('routes.experiments')
        conn = MagicMock(); cursor = conn.cursor.return_value
        cursor.fetchall.side_effect = [
            [{'id':131, 'title':'1,800 pages', 'status':'completed', 'created_at':'2026-09-24'}],
            [{'experiment_id':131, 'url':'https://nike.com/', 'title':'1,800 pages'}],
        ]
        with patch.object(routes, 'get_connection', return_value=conn):
            response = main.app.test_client().get('/experiments/search-suggestions?q=nike')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['experiments'][0]['href'], '/experiments/131/loading')
        self.assertEqual(data['urls'][0]['href'], '/experiments/131/loading#url-results')
        self.assertEqual(cursor.execute.call_args_list[0].args[1], ('nike', '%nike%', '%nike%', '%nike%', '%nike%', None))
        self.assertEqual(cursor.execute.call_args_list[1].args[1], ('nike', '%nike%'))
        for call in cursor.execute.call_args_list:
            self.assertIn('LIMIT 6', call.args[0])
        conn.commit.assert_not_called()

    def test_evaluation_id_search_accepts_hash_and_plain_ids(self):
        routes = importlib.import_module('routes.experiments')
        for query in ('407', '#407'):
            conn = MagicMock()
            conn.cursor.return_value.fetchall.side_effect = [[], []]
            with patch.object(routes, 'get_connection', return_value=conn):
                response = main.app.test_client().get('/experiments/search-suggestions', query_string={'q': query})
            self.assertEqual(response.status_code, 200)
            call = conn.cursor.return_value.execute.call_args_list[0]
            self.assertIn('id = %s', call.args[0])
            self.assertEqual(call.args[1][-1], '407')
            conn.commit.assert_not_called()






    def test_evaluation_list_has_no_llm_usage_controls_or_costs(self):
        listing = (APP_DIR / 'templates' / 'experiments.html').read_text()
        route = (APP_DIR / 'routes' / 'experiments.py').read_text()
        self.assertNotIn('summary.llm_experiments', listing)
        self.assertNotIn('summary.llm_tokens', listing)
        self.assertNotIn('experiment.include_semantic', listing)
        self.assertNotIn('experiment.llm_tokens', listing)
        self.assertNotIn('WAVE and LLM combined', listing)
        self.assertNotIn('AS llm_tokens', route[route.index('def experiments():'):route.index('all_experiments = cursor.fetchall()')])














if __name__ == "__main__":
    unittest.main()
