import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
from flask import render_template
from main import app


class HistoryViewTests(unittest.TestCase):


    def test_remediation_status_filter_reuses_history_control(self):
        with app.test_request_context('/remediation/'), patch('main.get_settings', return_value={}):
            dom = BeautifulSoup(render_template('_history_filters.html', history_input='runs'), 'html.parser')
        select = dom.select_one('[data-history-status]')
        self.assertEqual(select['aria-label'], 'Status')
        self.assertEqual([o['value'] for o in select.select('option')],
                         ['', 'queued', 'running', 'stopped', 'accepted', 'completed',
                          'completed_with_warnings', 'metrics_not_achieved', 'review_not_achieved', 'failed'])
        self.assertIsNotNone(dom.select_one('[data-history-rag]'))
        self.assertIsNotNone(dom.select_one('[data-history-preservation]'))

    def test_controls_are_shared_and_localized_without_different_datasets(self):
        with app.test_request_context('/evaluations'), patch('main.get_settings', return_value={}):
            from flask import session
            session['language'] = 'es'
            dom = BeautifulSoup(render_template('_history_view_toggle.html', history_target='test'), 'html.parser')
        self.assertEqual([b.get_text(strip=True) for b in dom.select('button')], ['Tabla', 'Tarjetas'])
        root = Path(__file__).resolve().parents[1] / 'app'
        for template in ('experiments.html', 'remediation_history.html'):
            source = (root/'templates'/template).read_text()
            self.assertIn('_history_view_toggle.html', source)
            self.assertIn('_history_view_head.html', source)
            self.assertNotIn('data-row-open', source)
