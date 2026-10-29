import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from jobs import pending_evaluation_urls, record_evaluator_interruption, request_evaluation, reuse_frozen_evaluation, process_experiment


class EvaluationRequestTests(unittest.TestCase):
    def full_top_stratum(self, retries):
        from tranco_sampling import sample_tranco
        ranking = [(rank, f"site-{rank}.example") for rank in range(1, 501)]
        candidates, strata = sample_tranco(ranking, "TEST123", "census", {"rank_1_1000": 500}, 500)
        for item in candidates:
            item["retry_count"] = retries
        failures = [{"id": i + 1, "url": item["url"], "error_message": "DNS failure"}
                    for i, item in enumerate(candidates[300:])]
        cursor = Mock()
        cursor.fetchone.return_value = {"candidates": candidates, "strata": strata,
                                       "list_id": "TEST123", "sampling_seed": "census"}
        cursor.fetchall.return_value = failures
        experiment = {"id": 71, "source_type": "tranco",
                      "urls": "\n".join(item["url"] for item in candidates)}
        return cursor, experiment



    def test_resume_skips_completed_and_failed_results_but_not_interrupted_url(self):
        urls = ["https://complete.test/", "https://failed.test/", "https://pending.test/"]
        existing = {
            urls[0]: {"status": "completed", "source_snapshot_path": "/results/source.html"},
            urls[1]: {"status": "failed", "source_snapshot_path": None},
        }
        self.assertEqual(pending_evaluation_urls(urls, existing), [urls[2]])

    def test_evaluator_outage_requeues_without_creating_failed_result(self):
        cursor = Mock()
        record_evaluator_interruption(cursor, 131, 77, ConnectionError("evaluator down"), 10.0, "end")
        self.assertEqual(cursor.execute.call_count, 2)
        attempt_sql, attempt_values = cursor.execute.call_args_list[0].args
        self.assertIn("status='interrupted'", attempt_sql)
        self.assertEqual(attempt_values, ("end", 10.0, "evaluator down", 77))
        experiment_sql, experiment_values = cursor.execute.call_args_list[1].args
        self.assertIn("status='queued'", experiment_sql)
        self.assertEqual(experiment_values, (131,))



    def test_retries_a_transient_evaluator_disconnect(self):
        app = Mock(config={"EVALUATOR_URL": "http://evaluator:3000"})
        successful = Mock()
        successful.raise_for_status.return_value = None
        successful.json.return_value = {"results": []}
        import requests
        with patch("jobs.requests.post", side_effect=[
            requests.ConnectionError("closed"), successful,
        ]) as post, patch("jobs.time.sleep") as sleep:
            self.assertEqual(request_evaluation(app, {"urls": ["https://example.com"]}), {"results": []})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_raises_after_three_disconnects(self):
        app = Mock(config={"EVALUATOR_URL": "http://evaluator:3000"})
        import requests
        with patch("jobs.requests.post", side_effect=requests.ConnectionError("closed")) as post, patch("jobs.time.sleep"):
            with self.assertRaises(requests.ConnectionError):
                request_evaluation(app, {"urls": ["https://example.com"]})
        self.assertEqual(post.call_count, 3)


class FrozenEvaluationReuseTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(':memory:')
        self.addCleanup(self.database.close)
        self.database.row_factory = sqlite3.Row
        self.database.executescript("""
            CREATE TABLE experiments (
                id INTEGER PRIMARY KEY, evaluation_signature TEXT,
                source_type TEXT, axe_include_best_practices INTEGER
            );
            CREATE TABLE experiment_results (
                id INTEGER PRIMARY KEY, experiment_id INTEGER, normalized_url TEXT,
                url TEXT, status TEXT, evaluated_at TEXT, created_at TEXT,
                source_snapshot_path TEXT
            );
            INSERT INTO experiments VALUES (1, 'matching', 'url', 0);
            INSERT INTO experiments VALUES (2, 'different', 'url', 0);
            INSERT INTO experiments VALUES (3, 'matching', 'url', 1);
            INSERT INTO experiments VALUES (4, 'matching', 'local_html', 0);
            INSERT INTO experiments VALUES (9, 'matching', 'url', 0);
        """)
        self.query = self.database.cursor()
        self.cursor = Mock()
        self.cursor.execute.side_effect = lambda sql, values: self.query.execute(sql.replace('%s', '?'), values)
        self.cursor.fetchone.side_effect = self.fetchone
        self.experiment = {'id': 9, 'reuse_cached_results': True,
                           'evaluation_signature': 'matching', 'axe_include_best_practices': False}

    def fetchone(self):
        row = self.query.fetchone()
        return dict(row) if row else None

    def add_result(self, ident, experiment=1, status='completed', url='https://example.org/',
                   snapshot='/results/raw/experiment_1/source.html'):
        self.database.execute(
            'INSERT INTO experiment_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (ident, experiment, url, url, status, f'2026-10-{ident:02d}',
             f'2026-10-{ident:02d}', snapshot),
        )

    def test_reuse_selects_latest_compatible_completed_web_capture(self):
        self.add_result(1)
        self.add_result(2)
        self.add_result(3, experiment=2)
        self.add_result(4, experiment=3)
        self.add_result(5, experiment=4)
        self.add_result(6, status='failed')
        self.add_result(7, url='https://other.org/')
        self.add_result(8, experiment=9)
        url = 'https://EXAMPLE.org:443/#section'
        with patch('jobs.Path.is_file', return_value=True), patch('jobs.clone_result', return_value=81) as clone:
            self.assertEqual(reuse_frozen_evaluation(self.cursor, self.experiment, url), 81)
        source = clone.call_args.args[1]
        self.assertEqual(source['id'], 2)
        self.assertEqual(source['url'], url)
        self.assertEqual(source['evaluated_at'], '2026-10-02')
        self.assertEqual(clone.call_args.args[2:], (9, 'cache'))
        original = self.database.execute('SELECT url FROM experiment_results WHERE id=2').fetchone()
        self.assertEqual(original['url'], 'https://example.org/')

    def test_disabled_reuse_or_missing_signature_never_looks_up_an_old_result(self):
        for values in ({'reuse_cached_results': False}, {'evaluation_signature': None}):
            with self.subTest(values=values):
                self.assertIsNone(reuse_frozen_evaluation(self.cursor, dict(self.experiment, **values), 'https://example.org/'))
        self.cursor.execute.assert_not_called()

    def test_missing_or_unavailable_html_falls_back_to_fresh_capture(self):
        for snapshot in (None, '/tmp/unrelated.html', '/results/raw/experiment_1/missing.html'):
            self.database.execute('DELETE FROM experiment_results')
            self.add_result(1, snapshot=snapshot)
            with self.subTest(snapshot=snapshot), patch('jobs.Path.is_file', return_value=False), patch('jobs.clone_result') as clone:
                self.assertIsNone(reuse_frozen_evaluation(self.cursor, self.experiment, 'https://example.org/'))
            clone.assert_not_called()

    def test_incompatible_results_are_not_copied(self):
        self.add_result(1, experiment=2)
        self.add_result(2, experiment=3)
        with patch('jobs.clone_result') as clone:
            self.assertIsNone(reuse_frozen_evaluation(self.cursor, self.experiment, 'https://example.org/'))
        clone.assert_not_called()

    def test_worker_uses_a_frozen_result_without_requesting_the_live_page(self):
        from contextlib import nullcontext
        for reused in (81, None):
            cursor = Mock()
            cursor.fetchone.side_effect = [
                dict(self.experiment, status='queued', urls='https://example.org/'),
                {'status': 'running'}, {'status': 'running'}, {'total': 0},
            ]
            cursor.fetchall.return_value = []
            connection = Mock()
            connection.cursor.return_value = cursor
            app = Mock()
            app.app_context.return_value = nullcontext()
            with self.subTest(reused=reused), patch('jobs.get_settings', return_value={'app_timezone': 'UTC'}), patch('jobs.evaluator_runtime_config', return_value={}), patch('jobs.get_connection', return_value=connection), patch('jobs.reuse_frozen_evaluation', return_value=reused), patch('jobs.request_evaluation', return_value={'results': []}) as evaluate, patch('jobs.store_result') as store:
                process_experiment(app, 9)
            self.assertEqual(evaluate.call_count, int(reused is None))
            self.assertEqual(store.call_count, int(reused is None))


if __name__ == "__main__":
    unittest.main()
