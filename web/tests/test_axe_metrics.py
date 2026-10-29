import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from axe_metrics import candidate_metrics, persist_metrics, project_wcag, raw_metrics
from backfill_axe_metrics import backfill, iteration_evidence
from remediation_taxonomy import axe_taxonomy


class AxeMetricsTests(unittest.TestCase):
    def evidence(self):
        return {'url': 'http://candidate/', 'violations': [
            {'id': 'button-name', 'tags': ['wcag2a'], 'impact': 'critical', 'nodes': [{}] * 23},
            {'id': 'region', 'tags': ['best-practice'], 'impact': 'moderate', 'nodes': [{}] * 1182}],
            'incomplete': [{'id': 'contrast', 'tags': ['wcag2aa'], 'nodes': [{}]},
                           {'id': 'region', 'tags': ['best-practice'], 'nodes': [{}] * 3}]}

    def raw_file(self, directory):
        path = directory / 'page_axe.json'
        path.write_text(json.dumps(self.evidence()))
        return path

    def test_raw_evidence_counts_wcag_and_best_practices_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.raw_file(Path(temporary))
            metrics = raw_metrics(path)
            self.assertEqual(metrics['axe_wcag_violations'], 23)
            self.assertEqual(metrics['axe_best_practice_issues'], 1182)
            self.assertEqual(metrics['axe_combined_violations'], 1205)
            self.assertEqual(metrics['axe_wcag_critical'], 23)
            self.assertEqual(metrics['axe_wcag_moderate'], 0)
            self.assertEqual(metrics['axe_wcag_failed_rules'], 1)
            self.assertEqual(metrics['axe_wcag_needs_review'], 1)
            self.assertEqual(axe_taxonomy(path)['Syntactic']['count'], 23)
            self.assertEqual(sum(item['count'] for item in axe_taxonomy(path).values()), 23)

    def test_projection_does_not_rewrite_evidence_and_is_idempotent(self):
        stored = {'axe_violations': 1205, 'axe_wcag_violations': 23,
                  'axe_critical': 40, 'axe_wcag_critical': 23, 'axe_best_practice_issues': 1182}
        result = project_wcag(stored)
        self.assertEqual(result['axe_violations'], 23)
        self.assertEqual(result['axe_combined_violations'], 1205)
        self.assertEqual(result['axe_critical'], 23)
        self.assertEqual(stored['axe_violations'], 1205)
        self.assertEqual(result, project_wcag(result))

    def test_zero_and_unknown_are_not_combined_counts(self):
        self.assertEqual(project_wcag({'axe_violations': 1182, 'axe_wcag_violations': 0})['axe_violations'], 0)
        self.assertIsNone(project_wcag({'axe_violations': 1182, 'axe_wcag_violations': None})['axe_violations'])
        self.assertEqual(project_wcag({'axe_violations': 23})['axe_violations'], 23)

    def test_iteration_projection_reads_separated_json(self):
        stored = {'axe_violations': 1205, 'axe_wcag_violations': 23,
                  'axe_metrics_json': json.dumps({'axe_wcag_critical': 23, 'axe_wcag_failed_rules': 1})}
        self.assertEqual(project_wcag(stored)['axe_failed_rules'], 1)

    def test_candidate_contract_never_accepts_combined_only(self):
        with self.assertRaisesRegex(RuntimeError, 'WCAG and Best Practices'):
            candidate_metrics({'violations': 1205})
        measured = candidate_metrics({'violations': 1205, 'wcag_violations': 23, 'best_practice_issues': 1182})
        self.assertEqual(measured['axe_wcag_violations'], 23)
        with self.assertRaisesRegex(RuntimeError, 'Inconsistent'):
            candidate_metrics({'violations': 1205, 'wcag_violations': 24, 'best_practice_issues': 1182})
        for value in (-1, True, 1.5, '23'):
            with self.assertRaisesRegex(RuntimeError, 'Invalid Axe'):
                candidate_metrics({'violations': 1205, 'wcag_violations': value, 'best_practice_issues': 1182})

    def test_remediation_gate_uses_measured_wcag_count(self):
        from remediation_jobs import candidate_gate_distance, validate_candidate_evaluation
        item = {'axe': {'violations': 1205, 'wcag_violations': 2, 'best_practice_issues': 1203},
                'lighthouse': {'accessibility_score': 96}}
        validate_candidate_evaluation(item)
        metrics = candidate_metrics(item['axe'])
        self.assertEqual(candidate_gate_distance(metrics['axe_wcag_violations'], 96, 3, 94), 0)

    def test_candidate_raw_evidence_is_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.raw_file(Path(temporary))
            self.assertEqual(candidate_metrics({'raw_path': str(path)})['axe_wcag_violations'], 23)
            with self.assertRaisesRegex(RuntimeError, 'disagrees'):
                candidate_metrics({'raw_path': str(path), 'wcag_violations': 1205})


    def test_backfill_is_read_only_by_default_and_does_not_rewrite_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'experiment_remediation_658_1'
            directory.mkdir()
            self.raw_file(directory)
            rows = [{'id': 99, 'run_id': 658, 'iteration_number': 1, 'output_url': 'http://candidate/'}]
            members = [{'id': 50, 'source_remediation_iteration_id': 99}]
            cursor = MagicMock(); cursor.fetchall.side_effect = [rows, members]
            report = backfill(cursor, root=root)
            self.assertEqual((report['iterations'], report['members']), (1, 1))
            self.assertEqual(report['unresolved_members'], [])
            self.assertTrue(all(call.args[0].startswith('SELECT') for call in cursor.execute.call_args_list))
            cursor = MagicMock(); cursor.fetchall.side_effect = [rows, members]
            self.assertEqual(backfill(cursor, apply=True, root=root), report)
            updates = [call.args[0] for call in cursor.execute.call_args_list if call.args[0].startswith('UPDATE')]
            self.assertEqual(len(updates), 2)
            for sql in updates:
                self.assertNotIn('SET axe_violations=', sql)
                self.assertNotIn('decision', sql)
                self.assertNotIn('remediation_runs', sql)
            cursor = MagicMock(); cursor.fetchall.side_effect = [[], []]
            self.assertEqual(backfill(cursor, apply=True, root=root)['iterations'], 0)

    def test_ambiguous_or_different_candidate_evidence_is_not_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory = root / 'experiment_remediation_658_1'; directory.mkdir()
            path = self.raw_file(directory)
            row = {'run_id': 658, 'iteration_number': 1, 'output_url': 'http://other/'}
            self.assertIsNone(iteration_evidence(row, root))
            row['output_url'] = 'http://candidate/'
            (directory / 'duplicate_axe.json').write_text(path.read_text())
            self.assertIsNone(iteration_evidence(row, root))

    def test_persistence_cannot_target_source_or_run_tables(self):
        with self.assertRaises(ValueError):
            persist_metrics(MagicMock(), 'experiment_results', 9216, {})

    def test_redirected_evidence_requires_exact_submitted_url_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory = root / 'experiment_remediation_658_1'; directory.mkdir()
            row = {'run_id': 658, 'iteration_number': 1, 'output_url': 'http://candidate/'}
            raw = self.evidence(); raw['url'] = 'https://redirected.test/'
            digest = hashlib.sha256(row['output_url'].encode()).hexdigest()[:16]
            path = directory / ('candidate_' + digest + '_axe.json')
            path.write_text(json.dumps(raw))
            self.assertEqual(iteration_evidence(row, root), path)
            row['output_url'] = 'http://different/'
            self.assertIsNone(iteration_evidence(row, root))


if __name__ == '__main__':
    unittest.main()
