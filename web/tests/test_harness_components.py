"""Component catalogues are local; read-only instructions cannot disable tasks."""
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from main import create_app
from harness.store import Store


class ComponentCatalogueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app({'TESTING': True, 'HARNESS_ROOT': self.tmp.name,
                               'SECRET_KEY': 'fixture'})
        self.client = self.app.test_client()
        self.store = Store(self.tmp.name)


    def test_skills_are_read_only_and_show_source_location(self):
        page = BeautifulSoup(self.client.get('/skills').data, 'html.parser')
        content = page.select_one('main')
        self.assertEqual(len(content.select('tbody tr')), 7)
        self.assertFalse(content.select('textarea, input, form, button'))
        self.assertIn('web/app/agent_skills/manifest-four-fixed-v3.json', content.get_text())
        for path in ('/skills/export', '/skills/activate', '/skills/source-verifier'):
            self.assertEqual(self.client.post(path).status_code, 404)
        tools = self.client.get('/tools')
        self.assertIn(b'web/app/remediation_tools.py', tools.data)
        self.assertIn(b'web/app/remediation_jobs.py', tools.data)
