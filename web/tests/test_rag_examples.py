import unittest
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
if 'database' not in sys.modules:
    database_stub = types.ModuleType('database')
    database_stub.init_db = lambda: None
    database_stub.get_connection = lambda: None
    sys.modules['database'] = database_stub

import rag_examples as explorer
from main import app

IDS = ['00000000-0000-4000-8000-%012d' % n for n in range(1, 13)]


def response(result=None, status=200):
    value = Mock(status_code=status)
    value.json.return_value = {'result':result}
    return value


def points():
    return [{'id':identity, 'payload':{
        'rule_name':'Image accessible name', 'rule_id':'image-alt',
        'testcase_id':'test-%s' % n, 'title':'Sample %02d' % n,
        'expected':'passed' if n % 2 else 'failed', 'requirements':['wcag20:1.1.1'],
        'source':'W3C ACT Rules' if n < 10 else 'Supplement',
        'source_kind':'official' if n < 10 else 'curated_guidance',
    }} for n, identity in enumerate(IDS)]


class RagExampleTests(unittest.TestCase):
    @patch('rag_examples.requests.post')
    def test_scroll_is_exhaustive_metadata_only_and_sorted(self, post):
        post.side_effect = [response({'points':points()[:5],'next_page_offset':IDS[4]}),
                            response({'points':points()[5:],'next_page_offset':None})]
        rows = explorer.metadata_rows('frozen')
        self.assertEqual(len(rows),12)
        self.assertEqual([row['title'] for row in rows],sorted(row['title'] for row in rows))
        for call in post.call_args_list:
            self.assertIn('/frozen/',call.args[0])
            self.assertFalse(call.kwargs['json']['with_vector'])
            self.assertNotIn('code',call.kwargs['json']['with_payload'])
        self.assertEqual(post.call_args_list[1].kwargs['json']['offset'],IDS[4])

    @patch('rag_examples.requests.post')
    def test_empty_corpus_and_repeated_cursor(self, post):
        post.return_value = response(status=404)
        self.assertEqual(explorer.metadata_rows('empty'),[])
        post.return_value = response({'points':[],'next_page_offset':IDS[0]})
        with self.assertRaises(ValueError): explorer.metadata_rows('bad')
        self.assertEqual(post.call_count,3)

    def test_search_filters_and_page_bounds_preserve_full_corpus_counts(self):
        rows = [{**p['payload'],'id':p['id'],'official':n<10,'complementary':n>=10}
                for n,p in enumerate(points())]
        first = explorer.page_view(rows,{})
        self.assertEqual((first['size'],len(first['rows']),first['pages']), (5,5,3))
        filtered = explorer.page_view(rows,{'q':'WCAG20:1.1.1','source':'official',
                                          'outcome':'failed','page':'999','size':'5'})
        self.assertEqual((filtered['matched'],filtered['official'],filtered['complementary']), (5,10,2))
        self.assertEqual(filtered['official_rules'],1)
        self.assertTrue(all(row['official'] and row['expected']=='failed' for row in filtered['rows']))
        for query in ('IMAGE-ALT','IMAGE ACCESSIBLE NAME','test-1',IDS[1]):
            self.assertGreater(explorer.page_view(rows,{'q':query})['matched'],0)
        self.assertEqual(explorer.page_view(rows,{'q':'not found'})['matched'],0)
        self.assertEqual(explorer.page_view(rows,{'size':'9000','page':'-1'})['size'],5)
        self.assertEqual(explorer.page_view(rows,{'size':'NaN'})['page'],1)

    @patch('rag_examples.active_collection',return_value='current')
    def test_pin_rejects_stale_and_arbitrary_collections(self, collection):
        self.assertEqual(explorer.collection_for_read('current'),'current')
        for requested in ('old','../unsafe','other_private_collection'):
            with self.assertRaises(explorer.CorpusChanged):explorer.collection_for_read(requested)

    def test_links_reject_executable_credentials_and_malformed_urls(self):
        self.assertEqual(explorer.safe_url('https://www.w3.org/test'),'https://www.w3.org/test')
        for url in ('javascript:alert(1)','data:text/html,hello','//example.org/x',
                    'https://user:secret@example.org','https://[bad',None):
            self.assertIsNone(explorer.safe_url(url))


    @patch('routes.rag_maintenance.read_json',return_value={})
    @patch('rag_examples.active_collection',return_value='current')
    @patch('rag_examples.requests.get')
    def test_detail_escapes_full_html_and_preserves_back_filters(self, get, collection, manifest):
        code='<script>alert("x")</script><img src="https://bad.example/track" onerror="alert(1)">'
        get.return_value=response({'payload':{**points()[0]['payload'],'code':code,
            'example_url':'javascript:alert(1)','rule_page':'https://www.w3.org/example'}})
        with app.test_client() as client, patch('routes.rag_maintenance.enqueue') as enqueue:
            result=client.get('/rag-act/examples/'+IDS[0]+'?collection=current&q=image&size=10&page=2')
        self.assertEqual(result.status_code,200)
        page=BeautifulSoup(result.data,'html.parser')
        self.assertEqual(page.select_one('pre code').get_text(),code)
        self.assertIsNone(page.select_one('#ragKnowledge'))
        self.assertIsNone(page.select_one('img[src="https://bad.example/track"]'))
        self.assertFalse(any(n.get('href','').startswith('javascript:') for n in page.select('a')))
        self.assertTrue(any('q=image' in n.get('href','') and 'page=2' in n.get('href','') for n in page.select('a')))
        self.assertFalse(get.call_args.kwargs['params']['with_vector']=='true')
        enqueue.assert_not_called()

    @patch('rag_examples.active_collection',return_value='current')
    @patch('rag_examples.requests.get')
    @patch('rag_examples.requests.post')
    def test_not_found_errors_and_changed_corpus_are_not_empty_success(self, post, get, collection):
        get.return_value=response(status=404)
        post.side_effect=requests.Timeout('offline')
        with app.test_client() as client:
            self.assertEqual(client.get('/rag-act/examples/not-uuid').status_code,404)
            get.assert_not_called()
            self.assertEqual(client.get('/rag-act/examples/'+IDS[0]).status_code,404)
            self.assertEqual(client.get('/rag-act').status_code,503)
            result=client.get('/rag-act?collection=old')
            self.assertEqual(result.status_code,409)
            self.assertIn(b'Reload the example browser',result.data)


if __name__ == '__main__': unittest.main()
