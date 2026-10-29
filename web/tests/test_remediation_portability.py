import copy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from remediation_portability import validate_package, import_package, export_manifest, _relocate_json
from warp_export import file_archive_chunks


class MemoryCursor:
    def __init__(self, payload, fail=False):
        self.tables = {
            'experiments': [entry['data'] for entry in payload['experiments']],
            'experiment_results': payload['sources'],
            'experiment_environment': [], 'tranco_samples': [],
            'remediation_runs': [entry['data'] for entry in payload['runs']],
            'remediation_iterations': [row for entry in payload['runs'] for row in entry['iterations']],
            'remediation_events': [row for entry in payload['runs'] for row in entry['events']],
            'remediation_templates': payload['templates'],
        }
        self.lastrowid = 100
        self.writes = []
        self.fail = fail

    def execute(self, sql, params=()):
        if sql.startswith('SHOW COLUMNS'):
            table = sql.split()[-1]
            columns = {key for row in self.tables[table] for key in row}
            columns |= {'import_provenance_json', 'provenance', 'normalized_url', 'cost_incurred_usd'}
            self.rows = [{'Field': key} for key in columns]
        elif sql.startswith('SELECT'):
            table = sql.split('FROM ')[1].split()[0]
            self.rows = self.tables[table]
        else:
            if self.fail and sql.startswith('INSERT INTO remediation_iterations'):
                raise RuntimeError('Injected insert failure')
            self.lastrowid += 1
            self.writes.append((sql, params, self.lastrowid))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def close(self):
        pass


class MemoryConnection:
    def __init__(self, payload, fail=False):
        self.q = MemoryCursor(payload, fail)
        self.committed = False
        self.rolled_back = False

    def cursor(self, **kwargs):
        return self.q

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class RemediationPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            'format': 'warp-remediations', 'version': 1,
            'sources': [{'id': 11, 'experiment_id': 5, 'url': 'https://example.org/',
                         'source_snapshot_path': '/results/raw/original.html',
                         'axe_wcag_violations': 14, 'lighthouse_score': 93}],
            'experiments': [{'data': {'id': 5, 'title': 'Original', 'status': 'completed'}, 'environment': [], 'tranco_sample': None}],
            'templates': [],
            'runs': [{'data': {'id': 21, 'source_result_id': 11, 'title': 'Repair', 'status': 'accepted',
                              'accepted_iteration_id': 31, 'total_cost_usd': 0.145, 'template_id': None},
                      'iterations': [{'id': 31, 'run_id': 21, 'iteration_number': 1, 'output_path': '/datasets/remediations/21/candidate.html',
                                      'output_url': 'http://dataset-server:8080/remediations/21/candidate.html',
                                      'prompt_text': 'Exact prompt with /results/raw/original.html',
                                      'axe_wcag_violations': 0, 'lighthouse_score': 96}],
                      'events': [{'id': 41, 'run_id': 21, 'message': 'Accepted', 'actor': 'Coordinator'}]}],
            'files': [], 'missing_optional_files': [],
        }
        self.content = {'artifacts/0/original.html': b'<html>Original</html>',
                        'artifacts/1/candidate.html': b'<html>Candidate</html>'}
        for index, (name, data) in enumerate(self.content.items()):
            self.payload['files'].append({'member': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'owner': 'source:11' if index == 0 else 'run:21',
                'path': '/results/raw/original.html' if index == 0 else '/datasets/remediations/21/candidate.html',
                'relative': 'evidence/0/original.html' if index == 0 else 'candidates/candidate.html'})

    def archive(self, payload=None, extras=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as package:
            package.writestr('remediation.json', json.dumps(payload or self.payload))
            for name, data in {**self.content, **(extras or {})}.items():
                package.writestr(name, data)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_binary_manifest_validated_without_execution(self):
        with self.archive() as package:
            self.assertEqual(validate_package(package), self.payload)

    def test_corruption_traversal_extra_members_and_symlinks_rejected(self):
        variants = [self.archive(extras={'artifacts/0/original.html': b'wrong'}),
                    self.archive(extras={'../escape': b'x'}), self.archive(extras={'settings.json': b'x'})]
        for archive in variants:
            with archive, self.assertRaises((ValueError, KeyError)):
                validate_package(archive)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as package:
            package.writestr('remediation.json', json.dumps(self.payload))
            member = zipfile.ZipInfo('artifacts/0/original.html'); member.external_attr = 0o120777 << 16
            package.writestr(member, self.content[member.filename])
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive, self.assertRaises(ValueError):
            validate_package(archive)

    def test_active_foreign_candidate_child_and_missing_source_rejected(self):
        changes = [('status', 'queued'), ('accepted_iteration_id', 999), ('source_result_id', 999)]
        for key, value in changes:
            payload = copy.deepcopy(self.payload); payload['runs'][0]['data'][key] = value
            with self.archive(payload) as archive, self.assertRaises(ValueError):
                validate_package(archive)
        payload = copy.deepcopy(self.payload); payload['runs'][0]['iterations'][0]['run_id'] = 999
        with self.archive(payload) as archive, self.assertRaises(ValueError):
            validate_package(archive)
        payload = copy.deepcopy(self.payload); payload['files'].pop(0)
        with self.archive(payload) as archive, self.assertRaises(ValueError):
            validate_package(archive)

    def test_import_new_ids_exact_bytes_metrics_costs_and_prompt(self):
        with tempfile.TemporaryDirectory() as temporary, self.archive() as archive:
            root = Path(temporary); raw = root / 'raw'; raw.mkdir()
            conn = MemoryConnection(self.payload)
            ids = import_package(conn, archive, validate_package(archive), '2026-10-05', raw_root=raw, dataset_root=root / 'datasets')
            self.assertTrue(conn.committed); self.assertFalse(conn.rolled_back)
            self.assertNotEqual(ids, [21])
            self.assertEqual((root / 'datasets/remediations' / str(ids[0]) / 'candidate.html').read_bytes(), b'<html>Candidate</html>')
            self.assertEqual(next(raw.rglob('original.html')).read_bytes(), b'<html>Original</html>')
            iteration = next(item for item in conn.q.writes if item[0].startswith('INSERT INTO remediation_iterations'))
            self.assertIn(self.payload['runs'][0]['iterations'][0]['prompt_text'], iteration[1])
            self.assertIn(96, iteration[1]); self.assertIn(0, iteration[1])
            run = next(item for item in conn.q.writes if item[0].startswith('INSERT INTO remediation_runs'))
            self.assertIn(0.145, run[1]); self.assertIn('manifest_sha256', str(run[1]))
            self.assertIn('accepted_iteration_id', conn.q.writes[-1][0])

    def test_failed_transaction_removes_only_new_directories(self):
        with tempfile.TemporaryDirectory() as temporary, self.archive() as archive:
            root = Path(temporary); raw = root / 'raw'; raw.mkdir()
            old = raw / 'existing.html'; old.write_text('untouched')
            conn = MemoryConnection(self.payload, fail=True)
            with self.assertRaisesRegex(RuntimeError, 'Injected'):
                import_package(conn, archive, self.payload, '2026-10-05', raw_root=raw, dataset_root=root / 'datasets')
            self.assertTrue(conn.rolled_back); self.assertFalse(conn.committed)
            self.assertEqual(list(raw.iterdir()), [old]); self.assertEqual(old.read_text(), 'untouched')
            self.assertEqual(list((root / 'datasets/remediations').iterdir()), [])

    def test_relocating_json_keeps_historical_text_and_ids(self):
        value = {'path': '/old/file', 'source_path': '/old/file', 'prompt': '/old/file', 'run_id': 21}
        restored = _relocate_json(value, {'/old/file': '/new/file'})
        self.assertEqual(restored, dict(value, path='/new/file', source_path='/new/file'))

    def test_export_rejects_running_before_reading_files(self):
        payload = copy.deepcopy(self.payload); payload['runs'][0]['data']['status'] = 'running'
        with self.assertRaisesRegex(ValueError, 'terminal'):
            export_manifest(MemoryCursor(payload), [21], '2026-10-05')

    def test_named_manifest_writer_streams_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'data'; path.write_bytes(b'x' * 200_000)
            chunks = list(file_archive_chunks('remediation.json', {'version': 1}, [(path, 'artifacts/data')]))
            with zipfile.ZipFile(io.BytesIO(b''.join(chunks))) as archive:
                self.assertEqual(archive.read('artifacts/data'), path.read_bytes())
                self.assertEqual(json.loads(archive.read('remediation.json')), {'version': 1})



    def test_shared_export_renders_both_sizes_and_translations(self):
        from jinja2 import Environment, FileSystemLoader
        root = Path(__file__).resolve().parents[1] / 'app/templates'
        env = Environment(loader=FileSystemLoader(root), autoescape=True)
        for label in ('Export data', 'Exportar datos'):
            module = env.get_template('_portable_export.html').make_module({'_': lambda value: label})
            for compact in (False, True):
                output = str(module.portable_export('/remediation/659/export', compact=compact))
                self.assertIn(label, output)
                self.assertIn('href="/remediation/659/export"', output)
                self.assertIn('download', output)
                self.assertIn('warp-export', output)
                self.assertIn('history-action' if compact else 'btn-primary', output)
                self.assertNotIn('style=', output)

    def test_inline_selection_renders_shared_icon_and_external_form_contract(self):
        from bs4 import BeautifulSoup
        from jinja2 import Environment, FileSystemLoader
        root = Path(__file__).resolve().parents[1] / 'app/templates'
        env = Environment(loader=FileSystemLoader(root), autoescape=True)
        html = env.get_template('_history_export_selection.html').render(
            _=lambda value: value, url_for=lambda endpoint: '/remediation/export')
        dom = BeautifulSoup(html, 'html.parser')
        form = dom.select_one('form[data-history-selection]')
        self.assertEqual(form['id'], 'remediationExportSelection')
        self.assertEqual(form['method'], 'post')
        self.assertEqual(form['action'], '/remediation/export')
        button = form.select_one('[data-history-export]')
        self.assertTrue(button.has_attr('disabled'))
        self.assertEqual(button.select_one('svg path')['d'], 'M12 3v12m0 0 4-4m-4 4-4-4M5 20h14')
        self.assertEqual(button.get_text(strip=True), 'Export')
        self.assertEqual(button['aria-label'], 'Export selected')
        self.assertEqual(len(form.select('button')), 1)
        self.assertEqual(form.find(recursive=False).name, 'button')
        label = form.select_one('label')
        self.assertEqual(label.get_text(strip=True), 'Select all')
        self.assertFalse(label.select('.visually-hidden'))

    def route_app(self):
        from flask import Flask
        from flask_babel import Babel
        from routes.experiments import experiments_bp
        from routes.remediation import remediation_bp
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-only'
        Babel(app)
        app.register_blueprint(experiments_bp)
        app.register_blueprint(remediation_bp)
        return app



    def test_single_and_batch_export_routes_share_streaming_download(self):
        app = self.route_app(); conn = MagicMock()
        exported_at = datetime(2026, 10, 5, 9, 7, 3)
        with patch('routes.remediation.get_connection', return_value=conn), \
             patch('routes.remediation.now_local', return_value=exported_at) as clock, \
             patch('routes.remediation.export_manifest') as export:
            for path, data, expected in (('/remediation/21/export', None, [21]),
                                         ('/remediation/export', {'run_ids': ['21', '22']}, [21, 22])):
                payload = copy.deepcopy(self.payload)
                if len(expected) > 1:
                    second_run = copy.deepcopy(payload['runs'][0])
                    second_run['data']['id'] = 22
                    payload['runs'].append(second_run)
                export.return_value = (payload, [])
                clock.reset_mock()
                response = app.test_client().post(path, data=data) if data else app.test_client().get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'application/vnd.warp+zip')
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                filename = ('remediation-21.warp' if len(expected) == 1
                            else 'remediations-20261005-090703.warp')
                self.assertEqual(response.headers['Content-Disposition'],
                                 f'attachment; filename="{filename}"')
                self.assertEqual(export.call_args.args[1], expected)
                self.assertEqual(export.call_args.args[2], exported_at.isoformat())
                clock.assert_called_once_with()
                with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(json.loads(archive.read('remediation.json')), payload)


if __name__ == '__main__':
    unittest.main()
