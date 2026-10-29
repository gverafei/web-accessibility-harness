import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import rag_corpus
import rag_sync_jobs as jobs
import sync_act_rag as sync
from main import app


def response(result=None, status=200):
    value = Mock(status_code=status)
    value.json.return_value = {'result': result or {}}
    return value


class RagMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root_patch = patch('rag_corpus.ROOT', self.root)
        self.root_patch.start()
        self.active = patch('rag_sync_jobs.active_runs', return_value=0)
        self.active.start()

    def tearDown(self):
        self.active.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_pointer_is_atomic_validated_and_legacy_default_preserved(self):
        self.assertEqual(rag_corpus.active_collection('legacy'), 'legacy')
        rag_corpus.write_json('corpus.json', {'collection':'snapshot-1'})
        self.assertEqual(rag_corpus.active_collection('legacy'), 'snapshot-1')
        self.assertFalse(list(self.root.glob('.pending-*')))
        rag_corpus.write_json('corpus.json', {'collection':'../unsafe'})
        with self.assertRaises(ValueError): rag_corpus.active_collection('legacy')

    @patch('rag_sync_jobs.corpus_info', return_value={'count':396})
    def test_confirmation_active_runs_and_initialize_guards(self, info):
        with self.assertRaises(jobs.SyncConflict): jobs.enqueue('update')
        with self.assertRaises(jobs.SyncConflict): jobs.enqueue('initialize')
        with patch('rag_sync_jobs.active_runs', return_value=1):
            with self.assertRaises(jobs.SyncConflict): jobs.enqueue('update', True)
        self.assertFalse((self.root/'job.json').exists())

    @patch('rag_sync_jobs.corpus_info', return_value={'count':396})
    def test_queue_is_explicit_deduplicated_and_never_runs_inline(self, info):
        with patch('sync_act_rag.main') as synchronize:
            self.assertEqual(jobs.enqueue('update', True)['status'], 'queued')
            with self.assertRaises(jobs.SyncConflict): jobs.enqueue('update', True)
            synchronize.assert_not_called()

    def test_worker_waits_for_runs_then_records_real_progress(self):
        rag_corpus.write_json('job.json', {'status':'queued','mode':'update'})
        with patch('rag_sync_jobs.active_runs', return_value=1), patch('sync_act_rag.main') as execute:
            self.assertFalse(jobs.process_pending()); execute.assert_not_called()
        def execute(**kwargs):
            kwargs['progress']('index', 60)
            self.assertEqual(rag_corpus.read_json('job.json')['percent'], 60)
            return {'synchronized_at':'2026-10-02T12:00:00+00:00'}
        with patch('sync_act_rag.main', side_effect=execute):
            self.assertTrue(jobs.process_pending())
        self.assertEqual(rag_corpus.read_json('job.json')['status'],'completed')
        self.assertEqual(rag_corpus.read_json('job.json')['percent'],100)

    def test_worker_failure_and_interruption_do_not_retry(self):
        rag_corpus.write_json('corpus.json', {'collection':'old'})
        rag_corpus.write_json('job.json', {'status':'queued','mode':'update'})
        with patch('sync_act_rag.main', side_effect=RuntimeError('offline')), patch.object(jobs.LOG,'exception'):
            jobs.process_pending()
        self.assertEqual(rag_corpus.active_collection('legacy'),'old')
        self.assertEqual(rag_corpus.read_json('job.json')['status'],'failed')
        rag_corpus.write_json('job.json', {'status':'running','mode':'update'})
        with patch('sync_act_rag.main') as execute:
            self.assertTrue(jobs.process_pending()); execute.assert_not_called()
        self.assertIn('interrupted',rag_corpus.read_json('job.json')['error'])

    def test_lock_blocks_double_requests_and_other_worker_work(self):
        with jobs.maintenance_lock():
            with self.assertRaises(jobs.SyncConflict): jobs.enqueue('update', True)
            self.assertTrue(jobs.process_pending())

    @patch('rag_sync_jobs.requests.post')
    @patch('rag_sync_jobs.requests.get')
    def test_existing_corpus_reports_separate_sources_without_invented_date(self, get, post):
        get.return_value = response({'points_count':2})
        post.return_value = response({'points':[
            {'payload':{'source':'W3C ACT Rules'}},
            {'payload':{'source_kind':'curated_guidance'}}]})
        info=jobs.corpus_info()
        self.assertEqual((info['official'],info['complementary']), (1,1))
        self.assertIsNone(info['synchronized_at'])

    @patch('routes.rag_maintenance.enqueue')
    def test_post_queues_only_json_confirmed_requests(self, enqueue):
        enqueue.return_value = {'status':'queued'}
        with app.test_client() as client:
            self.assertEqual(client.post('/rag-act/synchronize',data='bad').status_code,400)
            self.assertEqual(client.post('/rag-act/synchronize',json=['bad']).status_code,400)
            r=client.post('/rag-act/synchronize',json={'mode':'update','confirmed':True})
        self.assertEqual(r.status_code,202)
        enqueue.assert_called_once_with('update',confirmed=True)

    @patch('routes.rag_maintenance.enqueue', side_effect=jobs.SyncConflict('Synchronization is already running.'))
    def test_route_reports_conflict_not_success(self, enqueue):
        with app.test_client() as client:
            r=client.post('/rag-act/synchronize',json={'mode':'update','confirmed':True})
        self.assertEqual(r.status_code,409)

    @patch('routes.rag_maintenance.view', side_effect=ValueError('invalid JSON'))
    def test_status_reports_unreadable_state_without_starting_maintenance(self, view):
        with app.test_client() as client, patch('sync_act_rag.main') as execute:
            r=client.get('/rag-act/status')
        self.assertEqual(r.status_code,503)
        execute.assert_not_called()

    def test_invalid_state_does_not_stop_other_research_work(self):
        rag_corpus.write_json('job.json', ['invalid'])
        with patch.object(jobs.LOG,'exception'), patch('sync_act_rag.main') as execute:
            self.assertFalse(jobs.process_pending())
            execute.assert_not_called()
        self.assertEqual(json.loads((self.root/'job.json').read_text()), ['invalid'])

    def test_sync_builds_and_verifies_snapshot_before_publishing(self):
        cases=[{'approved':True,'expected':'passed','relativePath':'sample.html','url':'https://www.w3.org/example'}]
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('repo/content-assets/wcag-act-rules/testcases.json',json.dumps({'testcases':cases}))
            archive.writestr('repo/content-assets/wcag-act-rules/sample.html','<html lang="en"><title>Example</title></html>')
        downloaded=response();downloaded.content=data.getvalue()
        rag_corpus.write_json('corpus.json',{'collection':'previous'})
        with patch('sync_act_rag.requests.get',side_effect=[response({'points_count':1}),downloaded,response({'points_count':1})]), patch('sync_act_rag.requests.put') as put, patch('sync_act_rag.requests.delete') as delete, patch('remediation_rag_supplement.points',return_value=[]):
            result=sync.main()
        self.assertNotEqual(result['collection'],'previous')
        self.assertEqual(rag_corpus.active_collection('legacy'),result['collection'])
        self.assertTrue(all('/previous' not in c.args[0] for c in put.call_args_list))
        delete.assert_not_called()
        self.assertEqual(result['official'],1)
        self.assertEqual((result['index_total'],result['index_approved'],result['index_eligible']), (1,1,1))

    def test_failed_verification_preserves_existing_pointer(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('repo/content-assets/wcag-act-rules/testcases.json',json.dumps({'testcases':[{'approved':True,'expected':'failed','relativePath':'missing','url':'x'}]}))
        downloaded=response();downloaded.content=data.getvalue()
        rag_corpus.write_json('corpus.json',{'collection':'previous'})
        with patch('sync_act_rag.requests.get',side_effect=[response({'points_count':1}),downloaded]), patch('sync_act_rag.requests.put') as put:
            with self.assertRaises(ValueError):sync.main()
        put.assert_not_called()
        self.assertEqual(rag_corpus.active_collection('legacy'),'previous')

    def test_sync_eligibility_and_coverage_have_no_125_case_limit(self):
        cases=[{'approved':True,'expected':'passed','relativePath':'sample.html',
                'url':'https://www.w3.org/example/%s' % n} for n in range(129)]
        cases += [{'approved':True,'expected':'inapplicable'},
                  {'approved':False,'expected':'failed'}]
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('repo/content-assets/wcag-act-rules/testcases.json',json.dumps({'testcases':cases}))
            archive.writestr('repo/content-assets/wcag-act-rules/sample.html','<html lang="en"><title>Example</title></html>')
        downloaded=response();downloaded.content=data.getvalue()
        with patch('sync_act_rag.requests.get',side_effect=[response({'points_count':1}),downloaded,response({'points_count':129})]), patch('sync_act_rag.requests.put'), patch('remediation_rag_supplement.points',return_value=[]):
            result=sync.main()
        self.assertEqual(result['official'],129)
        self.assertEqual((result['index_total'],result['index_approved'],result['index_eligible']), (131,130,129))

    def test_indexing_failure_or_incomplete_upload_never_publishes_snapshot(self):
        import requests
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('repo/content-assets/wcag-act-rules/testcases.json',json.dumps({'testcases':[
                {'approved':True,'expected':'failed','relativePath':'sample.html','url':'https://www.w3.org/example'}]}))
            archive.writestr('repo/content-assets/wcag-act-rules/sample.html','<html><title>Example</title></html>')
        downloaded=response();downloaded.content=data.getvalue()
        for failed_upload in (False, True):
            with self.subTest(failed_upload=failed_upload):
                rag_corpus.write_json('corpus.json',{'collection':'previous'})
                put_effect = [response(), requests.HTTPError('offline')] if failed_upload else None
                with patch('sync_act_rag.requests.get', side_effect=[response({'points_count':396}),downloaded,response({'points_count':0})]), patch('sync_act_rag.requests.put',side_effect=put_effect), patch('remediation_rag_supplement.points',return_value=[]):
                    with self.assertRaises((ValueError, requests.HTTPError)):sync.main()
                self.assertEqual(rag_corpus.active_collection('legacy'),'previous')

    def test_retrieval_uses_one_frozen_collection_for_query_and_scroll(self):
        from remediation_rag import retrieve
        rag_corpus.write_json('corpus.json',{'collection':'snapshot-old'})
        def post(url, **kwargs):
            rag_corpus.write_json('corpus.json',{'collection':'snapshot-new'})
            return response({'points':[]})
        with patch('remediation_rag.requests.post',side_effect=post) as request:
            retrieve('image alternative',2)
        self.assertTrue(all('/snapshot-old/' in c.args[0] for c in request.call_args_list))


if __name__=='__main__': unittest.main()
