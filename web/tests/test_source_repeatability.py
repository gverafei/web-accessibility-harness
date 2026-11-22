import copy
import unittest
from harness.source_repeatability import compare


class SourceRepeatabilityTests(unittest.TestCase):
    def audit(self, ident='original'):
        return {'id':ident,'data':{'status':'completed','axe':11,'lighthouse':92,
            'replay':{'manifest_sha256':'assets-and-document','input_document_sha256':'input',
                      'rendered_document_sha256':'prepared-input','diagnostics':{
                          'phase_evidence':{'stable':True,'phases':[{'sha256':'measured-state'}]}}}}}

    def test_identical_complete_independent_audits_are_repeatable(self):
        result=compare(self.audit(),self.audit('repeat'))
        self.assertEqual(result['status'],'admitted')
        self.assertEqual(result['audit_ids'],['original','repeat'])

    def test_same_html_and_assets_with_different_render_or_scores_are_rejected(self):
        for field in ('state','axe','lighthouse','manifest','input'):
            repeated=self.audit('repeat')
            if field=='state':repeated['data']['replay']['diagnostics']['phase_evidence']['phases'][0]['sha256']='different'
            elif field in ('axe','lighthouse'):repeated['data'][field]+=25
            else:repeated['data']['replay'][field+'_document_sha256'if field=='input'else'manifest_sha256']='different'
            with self.subTest(field=field):
                result=compare(self.audit(),repeated)
                self.assertEqual(result['reasons'],['source_measurement_not_repeatable'])

    def test_missing_or_unstable_measurements_never_establish_repeatability(self):
        repeated=copy.deepcopy(self.audit())
        repeated['data']['replay']['diagnostics']['phase_evidence']['stable']=False
        self.assertIn('incomplete_repeat_measurement',compare(self.audit(),repeated)['reasons'])
        repeated['data']['replay']['diagnostics']['phase_evidence']['phases']=[]
        self.assertIn('missing_repeat_measurement_evidence',compare(self.audit(),repeated)['reasons'])

    def media_audit(self, current):
        value=self.audit(current);diag=value['data']['replay']['diagnostics']
        diag['phase_evidence']['phases'][0].update(sha256=current,layout_sha256='same-paint',origin='https://fixture.test',url='https://fixture.test/',viewport=[1440,1000],scroll=[0,0])
        path='html > body:nth-of-type(1) > video:nth-of-type(1)'
        diag['mse_restoration']={'restoration_version':'frozen-observed-mse-restoration-v2','live_resources':False,
            'results':[{'status':'restored','path':path,'original_src':'blob:https://fixture.test/original','current_src':current}]}
        diag['visible']={'media_descriptors':[{'position_path':path,'state':'loaded','paused':True,'src_attribute':current,'current_src':current,'current_time':.1,'video_width':1280,'video_height':720}]}
        html='<html><body><video src="'+current+'"></video><p>Keep this content</p></body></html>'
        return value,html

    def test_verified_decoder_url_nonce_is_not_a_change_but_content_paint_and_frame_are(self):
        first,a=self.media_audit('blob:https://fixture.test/one')
        second,b=self.media_audit('blob:https://fixture.test/two')
        self.assertEqual(compare(first,second,[a,b])['status'],'admitted')
        self.assertEqual(compare(first,second,[a,b.replace('Keep','Changed')])['status'],'rejected')
        changed=copy.deepcopy(second)
        changed['data']['replay']['diagnostics']['phase_evidence']['phases'][0]['layout_sha256']='different-paint'
        self.assertEqual(compare(first,changed,[a,b])['status'],'rejected')
        changed=copy.deepcopy(second)
        changed['data']['replay']['diagnostics']['visible']['media_descriptors'][0]['current_time']=.8
        self.assertEqual(compare(first,changed,[a,b])['status'],'rejected')
        changed['data']['replay']['diagnostics']['mse_restoration']['results'][0]['status']='unmatched_reference'
        self.assertEqual(compare(first,changed,[a,b])['status'],'rejected')

    def test_concurrent_campaigns_share_one_independent_source_measurement(self):
        import tempfile
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from harness.source_repeatability import verify
        from harness.store import Store
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'store';barrier=threading.Barrier(5);calls=[]
            # Campaigns share an already initialized private catalogue in production.
            # Keep cold SQLite creation outside this measurement-sharing barrier.
            Store(root)
            baseline=self.audit();capture={'id':'same-capture','data':{'replay_source_id':'same-html'}}
            class Evaluator:
                def __init__(self,store,campaign):self.store,self.campaign=store,campaign
                def runtime(self):return {'source_files':{'instrument':'frozen'}}
                def audit(self,capture,source,campaign,ident,config):
                    calls.append(campaign);time.sleep(.04)
                    data=copy.deepcopy(baseline['data']);data['independent_evidence_owner']=campaign
                    return self.store.append('audit',data,campaign,ident)
            def worker(index):
                store=Store(root);campaign='campaign-'+str(index);barrier.wait(timeout=5)
                return verify(store,Evaluator(store,campaign),capture,'same-html',baseline,campaign,{})
            with ThreadPoolExecutor(max_workers=5) as executor:results=list(executor.map(worker,range(5)))
            self.assertEqual(len(calls),1)
            self.assertEqual(len({row['id'] for row in results}),1)
            self.assertTrue(all(row['data']['status']=='admitted' for row in results))
            self.assertEqual(len(Store(root).list('source_repeatability')),1)

    def test_failed_source_measurement_releases_lock_without_publishing_a_proof(self):
        import tempfile
        from pathlib import Path
        from harness.source_repeatability import verify
        from harness.store import Store
        with tempfile.TemporaryDirectory() as temporary:
            store=Store(Path(temporary)/'store');baseline=self.audit();calls=[]
            class Evaluator:
                def runtime(self):return {'source_files':{'instrument':'frozen'}}
                def audit(self,capture,source,campaign,ident,config):
                    calls.append(ident)
                    if len(calls)==1:raise RuntimeError('Instrument unavailable')
                    return store.append('audit',copy.deepcopy(baseline['data']),campaign,ident)
            capture={'id':'capture','data':{'replay_source_id':'html'}}
            with self.assertRaisesRegex(RuntimeError,'Instrument unavailable'):
                verify(store,Evaluator(),capture,'html',baseline,'first',{})
            self.assertEqual(store.list('source_repeatability'),[])
            result=verify(store,Evaluator(),capture,'html',baseline,'retry',{})
            self.assertEqual(result['data']['status'],'admitted')
            self.assertEqual(len(calls),2)
