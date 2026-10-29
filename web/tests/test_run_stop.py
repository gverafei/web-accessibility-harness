import tempfile
import unittest
from unittest.mock import MagicMock, patch

from harness.run_stop import requested
from harness.store import Store
from main import create_app


class RunStopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Store(temporary.name)
        self.app = create_app({'TESTING': True, 'HARNESS_ROOT': temporary.name,
                               'SECRET_KEY': 'isolated-session'})
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['csrf_token'] = 'stop-test-token'
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value

    def stop(self, status='running'):
        self.cursor.fetchone.return_value = {'id': 9, 'status': status}
        with patch('routes.remediation.get_connection', return_value=self.connection), \
                patch('routes.remediation.now_local', return_value='2026-10-28 12:00:00'):
            return self.client.post('/remediation/9/stop',
                                    data={'csrf_token': 'stop-test-token'},
                                    headers={'Accept': 'application/json'})

    def test_stop_requires_the_current_session_token(self):
        with patch('routes.remediation.get_connection') as connect:
            self.assertEqual(self.client.post('/remediation/9/stop').status_code, 400)
        connect.assert_not_called()

    def test_running_stop_is_durable_idempotent_and_preserves_results(self):
        self.assertEqual(self.stop().status_code, 202)
        self.assertEqual(self.stop().status_code, 202)
        self.assertTrue(requested(self.store, 9))
        self.assertFalse(requested(self.store, 10))
        self.assertEqual(len(self.store.list('run_stop_request')), 1)
        writes = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertEqual(sum(sql.startswith('INSERT INTO remediation_events') for sql in writes), 1)
        self.assertFalse(any(sql.startswith(('DELETE', 'UPDATE')) for sql in writes))

    def test_queued_stop_removes_the_run_from_the_worker_queue(self):
        self.assertEqual(self.stop('queued').status_code, 202)
        updates = [call.args[0] for call in self.cursor.execute.call_args_list if call.args[0].startswith('UPDATE')]
        self.assertEqual(len(updates), 1)
        self.assertIn("status='stopped'", updates[0])
        self.assertIn("AND status='queued'", updates[0])

    def test_finished_run_cannot_receive_a_new_stop_request(self):
        self.assertEqual(self.stop('accepted').status_code, 409)
        self.assertFalse(requested(self.store, 9))
