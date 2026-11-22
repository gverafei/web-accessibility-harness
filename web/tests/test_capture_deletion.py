import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from main import app


class CaptureDeletionTests(unittest.TestCase):
    def setUp(self):
        configuration = patch.dict(app.config, SECRET_KEY='isolated-test-session')
        configuration.start()
        self.addCleanup(configuration.stop)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['csrf_token'] = 'capture-test-token'
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value

    def delete(self):
        with patch('routes.experiments.get_connection', return_value=self.connection), \
                patch('routes.experiments.os.path.isdir', return_value=False):
            return self.client.post('/experiments/475/delete',
                                    data={'csrf_token': 'capture-test-token'})

    def test_delete_requires_the_current_session_token(self):
        with patch('routes.experiments.get_connection') as connect:
            response = self.client.post('/experiments/475/delete')
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()

    def test_completed_capture_without_dependents_can_be_deleted(self):
        self.cursor.fetchone.side_effect = [
            {'id': 475, 'title': 'Capture', 'status': 'completed'}, {'total': 0},
        ]
        self.assertEqual(self.delete().status_code, 302)
        self.connection.commit.assert_called_once()
        self.assertTrue(any('DELETE FROM experiments' in call.args[0]
                            for call in self.cursor.execute.call_args_list))

    def test_missing_or_active_capture_is_never_deleted(self):
        for record in (None, {'id': 475, 'status': 'queued'},
                       {'id': 475, 'status': 'running'}):
            with self.subTest(record=record):
                self.connection.reset_mock()
                self.cursor.fetchone.return_value = record
                self.assertEqual(self.delete().status_code, 302)
                self.connection.commit.assert_not_called()
                self.assertFalse(any('DELETE FROM' in call.args[0]
                                     for call in self.cursor.execute.call_args_list))

    def test_remediation_sources_cannot_be_deleted(self):
        self.cursor.fetchone.side_effect = [
            {'id': 475, 'status': 'completed'}, {'total': 1},
        ]
        self.cursor.fetchall.return_value = [{'id': 1327}]
        self.assertEqual(self.delete().status_code, 302)
        self.connection.commit.assert_not_called()
        self.assertFalse(any('DELETE FROM' in call.args[0]
                             for call in self.cursor.execute.call_args_list))

    def test_listing_actions_have_confirmation_and_session_protection(self):
        self.cursor.fetchall.return_value = [
            dict(id=475, title='Capture', urls='https://example.org/',
                 status=status, completed_urls=1)
            for status in ('completed', 'running')
        ]
        self.cursor.fetchone.return_value = {}
        with patch('routes.experiments.get_connection', return_value=self.connection):
            response = self.client.get('/evaluations')
        self.assertEqual(response.status_code, 200)
        page = BeautifulSoup(response.data, 'html.parser')
        forms = page.select('form[data-list-delete]')
        self.assertEqual(len(forms), 2)
        for form in forms:
            self.assertEqual(form['action'], '/experiments/475/delete')
            self.assertEqual(form.select_one('[name=csrf_token]')['value'],
                             'capture-test-token')
            self.assertIn('cannot be undone', form['data-confirm'])
        self.assertFalse(forms[0].select_one('button').has_attr('disabled'))
        self.assertTrue(forms[1].select_one('button').has_attr('disabled'))
