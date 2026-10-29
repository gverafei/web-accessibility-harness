import unittest
import tempfile
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup
from main import app
from capture_report import details, visual_verdict
from harness.store import Store


class CaptureReportTests(unittest.TestCase):
    def test_saved_findings_keep_wcag_scope_and_exclude_unrelated_lighthouse_audits(self):
        axe = {'violations':[{'id':'contrast','help':'Contrast','tags':['wcag2aa','wcag143'], 'nodes':[{},{}]},
                             {'id':'region','tags':['best-practice'],'nodes':[{}]}]}
        lighthouse = {'categories':{'accessibility':{'auditRefs':[{'id':'contrast'}]}},
                      'audits':{'contrast':{'id':'contrast','title':'Contrast','score':0},
                                'speed':{'id':'speed','title':'Performance','score':0}}}
        rows = [{'id':1,'status':'completed','axe_wcag_violations':2,'lighthouse_score':84}]
        with patch('capture_report.read_report',side_effect=[axe,lighthouse]):
            summary = details(rows)
        self.assertEqual(summary['axe_instances'],2)
        self.assertEqual(rows[0]['report']['axe_findings'][0]['criteria'],['1.4.3'])
        self.assertEqual(len(rows[0]['report']['axe_findings']),1)
        self.assertEqual([r['id'] for r in rows[0]['report']['lighthouse_findings']],['contrast'])

    def test_visual_verdict_cannot_be_replaced_by_a_remediation_judgment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            judgment = store.append('evidence_verification',{'phase':'baseline','capture_id':'capture',
                'audit_id':'audit','status':'rejected','rationale':'Recorded acquisition defect'},'acquisition')
            data = {'application':'acquisition','source_id':502,'verification_id':judgment['id'],
                    'capture_id':'capture','audit_id':'audit','bindings':[{'id':judgment['id'],'hash':judgment['hash']}]}
            store.append('verification_case',data,'acquisition')
            other = store.append('evidence_verification',dict(judgment['data'],status='admitted'),'remediation')
            store.append('verification_case',dict(data,application='remediation',verification_id=other['id']), 'remediation')
            before = [(r['id'],r['hash']) for r in store.list()]
            self.assertEqual(visual_verdict(store,502)['status'],'rejected')
            self.assertEqual(before,[(r['id'],r['hash']) for r in store.list()])

    def listing_metrics(self, rows, measurements):
        connection = MagicMock()
        connection.cursor.return_value.fetchall.return_value = rows
        connection.cursor.return_value.fetchone.return_value = measurements
        with patch('routes.experiments.get_connection',return_value=connection):
            response = app.test_client().get('/evaluations')
        self.assertEqual(response.status_code,200)
        page = BeautifulSoup(response.data,'html.parser')
        connection.commit.assert_not_called()
        return [value.get_text() for value in page.select('.summary-metrics [data-metric-value]')]

    def test_capture_strip_has_counts_and_readable_measured_means(self):
        rows = [dict(id=474,title='UV',urls='https://www.uv.mx/',status='completed',completed_urls=1),
                dict(id=475,title='Another capture',urls='https://example.org/',status='running',completed_urls=0)]
        metrics = self.listing_metrics(rows,{'average_axe':15.3913,'average_lighthouse':89.5424})
        self.assertEqual(metrics,['2','1','15.4','89.5'])

    def test_empty_and_zero_measurements_are_distinct(self):
        self.assertEqual(self.listing_metrics([],{}),['0','0','—','—'])
        rows = [dict(id=474,title='UV',urls='https://www.uv.mx/',status='completed',completed_urls=1)]
        self.assertEqual(self.listing_metrics(rows,{'average_axe':0,'average_lighthouse':0}),['1','1','0.0','0.0'])

    def test_old_loading_link_opens_current_report_without_a_transition_page(self):
        with patch('routes.experiments.get_connection') as connect:
            response = app.test_client().get('/experiments/474/loading')
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/experiments/474')
        connect.assert_not_called()

    def test_saved_capture_report_renders_without_removed_templates_or_name_editor(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = {'id':474,'title':'UV','status':'completed'}
        cursor.fetchall.return_value = [{'id':501,'url':'https://www.uv.mx/',
            'status':'completed','axe_wcag_violations':15,'lighthouse_score':90,
            'screenshot_path':'/results/raw/capture.jpg','source_snapshot_path':'/results/raw/page.html'}]
        with patch('routes.experiments.get_connection',return_value=connection):
            response = app.test_client().get('/experiments/474')
        self.assertEqual(response.status_code,200)
        page = BeautifulSoup(response.data,'html.parser')
        self.assertEqual(page.select_one('h1').get_text(),'UV')
        self.assertIn('Axe 15',page.get_text(' ',strip=True))
        self.assertTrue(page.select('a[href="/experiments/474/source/501"]'))
        self.assertFalse(page.select('input[name=title], .capture-name-editor'))
        connection.commit.assert_not_called()

    def test_missing_capture_returns_not_found(self):
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = None
        with patch('routes.experiments.get_connection',return_value=connection):
            response = app.test_client().get('/experiments/99999')
        self.assertEqual(response.status_code,404)
        connection.commit.assert_not_called()
