import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch
from flask import render_template
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

database_stub = types.ModuleType("database")
database_stub.init_db = lambda: None
database_stub.get_connection = lambda: None
sys.modules["database"] = database_stub

main = importlib.import_module("main")


class InternationalizationTestCase(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()

    def test_english_is_the_default_language(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="en" data-theme="light" data-theme-choice="light">', response.data)
        self.assertIn(b"Enter the target URLs to start remediation.", response.data)

    def test_language_can_be_changed_to_spanish(self):
        response = self.client.get("/language/es?next=/", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="es" data-theme="light" data-theme-choice="light">', response.data)
        self.assertIn("Iniciar remediación".encode(), response.data)

    def test_language_redirect_does_not_accept_external_targets(self):
        response = self.client.get(
            "/language/es?next=https://example.com",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_dashboard_is_translated_to_spanish(self):
        with main.app.test_request_context("/", headers={"Accept-Language": "es"}):
            from flask import session
            session["language"] = "es"
            html = render_template(
                "dashboard.html", evaluations={"total": 0},
                pages={"pages": 0, "lighthouse": None},
                remediations={"total": 0, "cost": 0},
                costs={"evaluation": 0, "remediation": 0, "total": 0},
                insights={"most_used_model": {}, "most_used_strategy": {},
                          "value_model": {}, "accessibility_model": {}},
            )
            self.assertIn("Web Accessibility Harness", html)
            self.assertIn("Actividad de remediación · estrategias", html)
            self.assertNotIn("activity-recent", html)
            self.assertIn("Costo de remediación", html)
            self.assertNotIn("Web accessibility research at a glance", html)

    def test_dashboard_does_not_query_removed_recent_lists(self):
        connection = Mock()
        with patch('routes.experiments.get_connection', return_value=connection), \
                patch('dashboard_activity.activity', return_value={}) as activity:
            response = self.client.get('/analytics')
        self.assertEqual(response.status_code, 200)
        activity.assert_called_once()
        connection.cursor.return_value.execute.assert_not_called()
        connection.cursor.return_value.close.assert_called_once()
        connection.close.assert_called_once()

    def test_theme_can_be_changed_for_the_browser_session(self):
        response = self.client.get("/theme/dark?next=/", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="en" data-theme="dark" data-theme-choice="dark">', response.data)
        self.assertIn(b'class="nav-utility theme-cycle"', response.data)

    def test_theme_redirect_does_not_accept_external_targets(self):
        response = self.client.get(
            "/theme/system?next=https://example.com",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_theme_can_be_saved_without_navigation(self):
        for theme in ("dark", "light", "system"):
            response = self.client.post(f"/theme/{theme}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {"theme": theme})
            with self.client.session_transaction() as session:
                self.assertEqual(session["ui_theme"], theme)

    def test_readonly_preview_allows_theme_preferences_but_rejects_task_writes(self):
        with patch.dict('os.environ', {'HARNESS_READ_ONLY': '1'}):
            app = main.create_app({'TESTING': True})
        client = app.test_client()
        self.assertEqual(client.post('/theme/dark').status_code, 200)
        self.assertEqual(client.post('/').status_code, 403)

    def test_theme_control_is_icon_only_and_not_a_dropdown(self):
        response = self.client.get("/")
        self.assertIn(b'id="themeCycle"', response.data)
        self.assertIn(b'data-theme-icon="system"', response.data)
        self.assertNotIn(b'aria-label="Color theme" data-bs-toggle', response.data)
        self.assertNotIn(b'next=/">Light</a>', response.data)

    def test_unknown_theme_still_defaults_to_light(self):
        self.assertEqual(self.client.post("/theme/invalid").json, {"theme": "light"})

    def test_language_switch_retains_the_report_and_query_filters(self):
        from bs4 import BeautifulSoup
        from urllib.parse import parse_qs, urlsplit
        for location in ('/remediation/1326', '/evaluations?q=uv.mx&size=20'):
            with main.app.test_request_context(location):
                html = render_template('base.html')
            link = BeautifulSoup(html, 'html.parser').select_one('a[aria-label="Change language"]')['href']
            self.assertEqual(parse_qs(urlsplit(link).query)['next'], [location])
            response = self.client.get(link)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['Location'], location)

    def test_readonly_mode_is_not_shown_in_the_header(self):
        with patch.dict('os.environ', {'HARNESS_READ_ONLY': '1'}):
            app = main.create_app({'TESTING': True})
        response = app.test_client().get('/')
        self.assertNotIn(b'Read-only preview', response.data)
        self.assertIn(b'Enter the target URLs to start remediation.', response.data)


if __name__ == "__main__":
    unittest.main()
