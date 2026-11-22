import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
from flask import render_template, session
from main import app
from navigation import breadcrumbs, NAVIGATION


class NavigationTests(unittest.TestCase):
    def test_shared_command_navigation_has_no_sidebar_or_removed_features(self):
        with app.test_request_context('/'),patch('main.get_settings',return_value={}):
            page=BeautifulSoup(render_template('base.html'),'html.parser')
        self.assertIsNone(page.select_one('.app-sidebar'))
        self.assertIsNotNone(page.select_one('#commandMenu[aria-labelledby]'))
        self.assertEqual(page.select_one('#commandMenu nav a:last-child')['href'],'/harness/configuration')
        urls={a['href'] for a in page.select('#commandMenu nav a')}
        self.assertTrue({'/','/analytics','/evaluations','/remediation/','/models','/skills','/tools','/agents','/taxonomy','/rag-act'}<=urls)
        self.assertFalse(urls & {'/comparisons','/urls/manage','/experiments/import','/interventions','/harness/reviews'})

    def test_breadcrumbs_follow_real_capture_and_execution_routes(self):
        for path,labels in {
            '/':['Start'],'/analytics':['Activity'],'/evaluations':['Captures'],
            '/remediation/':['Executions'],'/remediation/1297':['Executions','Execution #1297'],
            '/experiments/474':['Captures','Capture #474'],
            '/harness/configuration':['Configuration'],'/skills':['Skills'],
        }.items():
            with self.subTest(path=path),app.test_request_context(path),patch('database.get_connection') as db:
                self.assertEqual([item['label'] for item in breadcrumbs()],labels)
                db.assert_not_called()

    def test_spanish_navigation_and_home_target_are_shared(self):
        with app.test_request_context('/evaluations'):
            session['language']='es'
            page=BeautifulSoup(render_template('base.html'),'html.parser')
        self.assertEqual(page.select_one('.app-breadcrumbs a')['href'],'/')
        self.assertIn('Capturas',page.select_one('.app-breadcrumbs').get_text())
        self.assertIn('Configuración',page.select_one('#commandMenu nav').get_text())

    def test_command_dialog_declares_accessible_controls(self):
        with app.test_request_context('/'):
            page=BeautifulSoup(render_template('base.html'),'html.parser')
        control=page.select_one('#commandMenuButton')
        self.assertEqual(control['aria-controls'],'commandMenu')
        self.assertEqual(control['aria-haspopup'],'dialog')
        self.assertEqual(page.select_one('main')['id'],'workspaceContent')
        toggle = page.select_one('#dockToggle')
        self.assertEqual(toggle['aria-controls'], page.select_one('.command-dock')['id'])
        self.assertEqual(toggle['aria-expanded'], 'true')
        self.assertIn('Meta+Shift+M', toggle['aria-keyshortcuts'])
        self.assertIsNotNone(toggle.find_parent(class_='workspace-header'))
        self.assertIsNone(page.select_one('.command-navigation,.command-dock-toggle'))
        self.assertIsNone(toggle.find_parent(id='commandDock'))


if __name__=='__main__':unittest.main()
