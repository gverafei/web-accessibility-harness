"""Synthetic UI/lifecycle/capture checks, independent of the real pilot."""
import unittest
from unittest.mock import patch
import test_harness
from harness import lifecycle
from harness.capture_admission import assess
from harness.contracts import ContractError
from harness.reports import campaign_report
from harness.providers import Ledger
from main import create_app

class ReadableEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.fixture=test_harness.HarnessTest();self.fixture.setUp();self.addCleanup(self.fixture.tmp.cleanup)
        self.store=self.fixture.store




    def test_capture_admission_strong_blockers_and_ordinary_mentions(self):
        for source,meta in [('<title>Sucuri Website Firewall - Access Denied</title>',{'http_status':307}),
                            ('<title>Just a moment...</title><form id="challenge-form"></form>',{'http_status':200}),
                            ('<title>Ordinary page</title>',{'http_status':403})]:
            self.assertEqual(assess(source,meta)['status'],'failed')
        for source in ('<title>How a Sucuri firewall works</title><p>Access denied is an error.</p>',
                       '<title>Just a moment...</title><p>A poem.</p>', '<title>Ordinary page</title><img>'):
            self.assertEqual(assess(source,{'http_status':200})['status'],'passed')

    def test_blocked_capture_is_retained_as_failure_without_paid_calls(self):
        f=self.fixture
        def capture(url,campaign,ident):
            source=f.store.blob('<title>Sucuri WebSite Firewall - Access Denied</title>','rendered_html',campaign,'text/html')
            screenshot=f.store.blob('fixture','capture_screenshot',campaign,'image/jpeg')
            return f.store.append('capture',{'rendered_id':source['id'],'network_id':source['id'],'screenshot_id':screenshot['id'],
                'captured_url':url,'requested_url':url,'http_status':307,'assets':[],'errors':[]},campaign,ident)
        f.environment.capture=capture
        c=f.campaign();f.execute(c)
        self.assertEqual(len(self.store.list('capture',c['id'])),1)
        self.assertEqual(len(self.store.list('acquisition_failure',c['id'])),1)
        self.assertEqual(self.store.list('capture_admission',c['id'])[0]['data']['status'],'failed')
        self.assertEqual(self.store.list('page',c['id']),[]);self.assertEqual(f.session.requests,[])
