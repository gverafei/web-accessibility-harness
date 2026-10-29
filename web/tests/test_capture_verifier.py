"""Identified synthetic fixtures for the in-loop evidence verification agent."""
import json
import unittest
from unittest.mock import Mock
import test_harness
from harness import evidence_verifier
from harness.contracts import ContractError

class CaptureVerifierTest(unittest.TestCase):
    def setUp(self):
        self.f=test_harness.HarnessTest();self.f.setUp();self.addCleanup(self.f.tmp.cleanup);self.s=self.f.store

    def fixtures(self,status='admitted'):
        image=self.s.blob(b'synthetic image','capture_screenshot',media_type='image/jpeg')
        capture=self.s.append('capture',{'screenshot_id':image['id'],'visible':{'text':'Known fixture'}})
        audit=self.s.append('audit',{'artifacts':{'screenshot':image['id']}})
        check=self.s.append('replay_admission',{'status':status,'reasons':[],'metrics':{},'replayed':{'text':'Known fixture'}})
        return capture,audit,check

    def test_closed_response_and_grounded_references(self):
        valid={'status':'admitted','rationale':'Known fixture is visible.','evidence_refs':['image']}
        self.assertEqual(evidence_verifier.parse(valid,['image']),valid)
        self.assertEqual(evidence_verifier.parse('```json\n'+json.dumps(valid)+'\n```',['image']),valid)
        for malformed in ('Explanation\n```json\n'+json.dumps(valid)+'\n```', '```json\n'+json.dumps(valid)+'\n```\nadditional text',json.dumps(valid)+' '+json.dumps(valid)):
            with self.assertRaises(ContractError):evidence_verifier.parse(malformed,['image'])
        for changed in (dict(valid,evidence_refs=['invented']),dict(valid,evidence_refs=[{}]),dict(valid,status='success'),dict(valid,budget=99)):
            with self.subTest(changed=changed),self.assertRaises(ContractError):evidence_verifier.parse(changed,['image'])

    def test_deterministic_rejection_and_missing_configuration_never_dispatch(self):
        provider=Mock(campaign='fixture')
        for status in ('rejected','review_required','admitted'):
            c,a,d=self.fixtures(status);record=evidence_verifier.verify(self.s,provider,'run',status,c,a,d)
            self.assertEqual(record['data']['status'],'rejected' if status=='rejected' else 'review_required')
        provider.chat.assert_not_called()

    def test_typed_visual_call_is_bounded_and_reused(self):
        c,a,d=self.fixtures();provider=Mock(campaign='fixture')
        provider.chat.return_value={'status':'admitted','rationale':'Known fixture content and controls remain visible.','evidence_refs':[c['id'],a['id']]}
        model={'model':'synthetic/vision','vision':True}
        first=evidence_verifier.verify(self.s,provider,'run','verification',c,a,d,model)
        second=evidence_verifier.verify(self.s,provider,'run','verification',c,a,d,model)
        self.assertEqual(first['id'],second['id']);provider.chat.assert_called_once()
        self.assertEqual(provider.chat.call_args.args[1],'review')
        self.assertEqual(len(provider.chat.call_args.kwargs['image_parts']),2)
        self.assertIn('Gambling pages are eligible.',provider.chat.call_args.args[4])
        self.assertIn('Reject a substantially unstyled',provider.chat.call_args.args[4])

        evidence_verifier.verify(self.s,provider,'run','candidate-check',c,a,d,model,candidate=True)
        self.assertIn('visual-identity changes are allowed',provider.chat.call_args.args[4])
        self.assertIn('a different or simpler design alone is not degradation',provider.chat.call_args.args[4])

    def test_matching_captures_do_not_waive_unusable_source_admission(self):
        capture, audit, check = self.scoped_baseline()
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {
            'status': 'rejected',
            'rationale': 'The acquired primary application area is visibly unusable in both views.',
            'evidence_refs': [capture['id'], audit['id']],
        }
        first = evidence_verifier.verify(self.s, provider, 'run', 'source-usability',
            capture, audit, check, {'model':'synthetic/vision','vision':True})
        second = evidence_verifier.verify(self.s, provider, 'run', 'source-usability',
            capture, audit, check, {'model':'synthetic/vision','vision':True})
        self.assertEqual(first, second)
        self.assertEqual(first['data']['status'], 'rejected')
        self.assertEqual(first['data']['admission_scope'], 'acquired-source-and-replay-usability')
        provider.chat.assert_called_once()
        prompt = provider.chat.call_args.args[4]
        self.assertIn('Reject a materially broken acquisition even when the replay is identical.', prompt)
        self.assertIn('corrupt glyphs', prompt)
        self.assertIn('Ordinary pre-existing accessibility issues', prompt)

    def scoped_baseline(self):
        capture, audit, check = self.fixtures()
        visible = {'text':'Visible hero and below-fold article inventory',
                   'title':'Known homepage', 'controls':['A||Products'],
                   'viewport':{'width':1440,'height':1000}}
        capture['data']['visible'] = dict(visible)
        check['data']['replayed'] = dict(visible)
        body = '<html><body><section id="promos"><a href="/camera-c210"><img src="/promo.jpg" alt=""></a></section><section><h2>Other products</h2></section></body></html>'
        rendered = self.s.blob(body,'rendered_html',media_type='text/html')
        capture['data']['rendered_id'] = rendered['id']
        capture['data']['captured_url'] = 'https://fixture.test/'
        audit['data']['artifacts']['rendered'] = rendered['id']
        return capture, audit, check

    def previous_baseline(self, ident, capture, audit, check, status='rejected'):
        return self.s.append('evidence_verification', {
            'version':evidence_verifier.VERSION, 'phase':'baseline',
            'capture_id':capture['id'], 'audit_id':audit['id'],
            'deterministic_id':check['id'], 'status':status,
            'rationale':'Old-scope fixture assessment.', 'evidence_refs':[capture['id']]},
            'fixture', ident)

    def test_baseline_labels_full_document_scope_without_changing_candidate_input(self):
        capture, audit, check = self.scoped_baseline()
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'admitted','rationale':'Known homepage.',
                                      'evidence_refs':[capture['id']]}
        model = {'model':'synthetic/vision','vision':True}
        result = evidence_verifier.verify(self.s,provider,'run','scope',capture,audit,check,model)
        prompt = provider.chat.call_args.args[4]
        evidence = json.loads(prompt.split('\nEVIDENCE\n')[1])
        self.assertEqual(result['data']['version'],evidence_verifier.BASELINE_VERSION)
        self.assertEqual(evidence['original']['title'],capture['data']['visible']['title'])
        self.assertNotIn('text',evidence['original'])
        self.assertIn('observation_scope',evidence)
        self.assertIn('compared independently by deterministic replay checks',prompt)
        self.assertIn('Continue to reject blank, blocked, unrelated',prompt)
        result = evidence_verifier.verify(self.s,provider,'run','candidate-scope',capture,audit,check,model,candidate=True)
        prompt = provider.chat.call_args.args[4]
        self.assertEqual(result['data']['version'],evidence_verifier.VERSION)
        self.assertNotIn('observation_scope',json.loads(prompt.split('\nEVIDENCE\n')[1]))
        self.assertNotIn('compared independently by deterministic replay checks',prompt)

    def test_admitted_legacy_source_remains_cached(self):
        capture,audit,check = self.scoped_baseline()
        prior = self.previous_baseline('old-pass',capture,audit,check,'admitted')
        provider = Mock(campaign='fixture')
        result = evidence_verifier.verify(self.s,provider,'run','old-pass',capture,audit,check,
                                         {'model':'synthetic/vision','vision':True})
        self.assertEqual(result,prior)
        provider.chat.assert_not_called()

    def test_identical_legacy_reproduction_gets_one_versioned_scope_review(self):
        capture,audit,check = self.scoped_baseline()
        prior = self.previous_baseline('old-reject',capture,audit,check)
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'admitted','rationale':'Same usable homepage.',
                                      'evidence_refs':[capture['id']]}
        model = {'model':'synthetic/vision','vision':True}
        result = evidence_verifier.verify(self.s,provider,'run','old-reject',capture,audit,check,model)
        self.assertEqual(result['data']['previous_verification_id'],prior['id'])
        self.assertEqual(self.s.get(prior['id']),prior)
        self.assertEqual(evidence_verifier.verify(self.s,provider,'run','old-reject',capture,audit,check,model),result)
        provider.chat.assert_called_once()

    def test_changed_or_unadmitted_reproduction_cannot_use_scope_recovery(self):
        for change in ('image','title','deterministic'):
            with self.subTest(change=change):
                capture,audit,check = self.scoped_baseline()
                prior = self.previous_baseline('different-'+change,capture,audit,check)
                if change == 'image':
                    image = self.s.blob(b'different image','capture_screenshot',media_type='image/jpeg')
                    audit['data']['artifacts']['screenshot'] = image['id']
                elif change == 'title':
                    check['data']['replayed']['title'] = 'Another page'
                else:
                    check['data']['status'] = 'rejected'
                provider = Mock(campaign='fixture')
                result = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,
                                                 {'model':'synthetic/vision','vision':True})
                self.assertEqual(result,prior)
                provider.chat.assert_not_called()

    def test_rejected_scope_review_is_preserved_without_retrying_until_it_passes(self):
        capture,audit,check = self.scoped_baseline()
        self.previous_baseline('still-rejected',capture,audit,check)
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'rejected','rationale':'Observed blocking fixture.',
                                      'evidence_refs':[capture['id']]}
        model = {'model':'synthetic/vision','vision':True}
        first = evidence_verifier.verify(self.s,provider,'run','still-rejected',capture,audit,check,model)
        second = evidence_verifier.verify(self.s,provider,'run','still-rejected',capture,audit,check,model)
        self.assertEqual(first,second)
        self.assertEqual(first['data']['status'],'rejected')
        provider.chat.assert_called_once()

    def test_materiality_scope_preserves_both_views_and_one_negative_reassessment(self):
        capture, audit, check = self.scoped_baseline()
        image = self.s.blob(b'changed peripheral region', 'capture_screenshot', media_type='image/jpeg')
        audit['data']['artifacts']['screenshot'] = image['id']
        old = self.previous_baseline('materiality-parent', capture, audit, check)
        prior = self.s.append('evidence_verification', dict(old['data'],
            version=evidence_verifier.LEGACY_MATERIALITY_VERSION), 'fixture', 'materiality-review')
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'rejected','rationale':'The primary content is materially absent.',
                                     'evidence_refs':[capture['id'], audit['id']]}
        model = {'model':'synthetic/vision','vision':True}
        result = evidence_verifier.verify(self.s, provider, 'run', prior['id'], capture, audit, check, model)
        self.assertEqual(result['data']['status'], 'rejected')
        self.assertEqual(result['data']['previous_verification_id'], prior['id'])
        self.assertEqual(self.s.get(prior['id']), prior)
        self.assertEqual(evidence_verifier.verify(self.s, provider, 'run', prior['id'], capture, audit, check, model), result)
        provider.chat.assert_called_once()
        prompt = provider.chat.call_args.args[4]
        self.assertIn('An isolated missing third-party advertisement', prompt)
        self.assertIn('Treat a missing region as material', prompt)
        self.assertEqual(len(provider.chat.call_args.kwargs['image_parts']), 2)

    def test_materiality_review_cannot_bypass_failed_inventory_admission(self):
        capture, audit, check = self.scoped_baseline()
        old = self.previous_baseline('inventory-parent', capture, audit, check)
        prior = self.s.append('evidence_verification', dict(old['data'],
            version=evidence_verifier.LEGACY_MATERIALITY_VERSION), 'fixture', 'inventory-review')
        check['data']['status'] = 'rejected'
        provider = Mock(campaign='fixture')
        self.assertEqual(evidence_verifier.verify(self.s, provider, 'run', prior['id'],
            capture, audit, check, {'model':'synthetic/vision','vision':True}), prior)
        provider.chat.assert_not_called()

    def test_baseline_image_identity_keeps_unnamed_image_links_and_source_bytes(self):
        capture,audit,check = self.scoped_baseline()
        ident = capture['data']['rendered_id']
        before = self.s.read_blob(ident)
        evidence = evidence_verifier.baseline_image_identity(self.s,capture,audit)
        item = evidence['original']['items'][0]
        self.assertEqual(item['alt'],'')
        self.assertIsNone(item['link_name'])
        self.assertEqual(item['link_href'],'https://fixture.test/camera-c210')
        self.assertEqual(item['absolute_src'],'https://fixture.test/promo.jpg')
        self.assertEqual(item['region_id'],'promos')
        self.assertEqual(evidence['original']['items'],evidence['replay']['items'])
        self.assertEqual(self.s.read_blob(ident),before)

    def test_missing_image_and_link_attributes_are_not_replaced_with_page_url(self):
        capture,audit,check = self.scoped_baseline()
        rendered = self.s.blob('<html><a><img></a></html>','rendered_html',media_type='text/html')
        audit['data']['artifacts']['rendered'] = rendered['id']
        item = evidence_verifier.baseline_image_identity(self.s,capture,audit)['replay']['items'][0]
        for field in ('src','absolute_src','alt','link_href','link_name'):
            self.assertIsNone(item[field])

    def test_legacy_scope_review_gets_visual_evidence_once_with_a_recorded_parent(self):
        capture,audit,check = self.scoped_baseline()
        prior = self.previous_baseline('scope-only',capture,audit,check)
        data = dict(prior['data'],version=evidence_verifier.LEGACY_SCOPE_VERSION)
        prior = self.s.append('evidence_verification',data,'fixture','legacy-scope')
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'rejected','rationale':'Keep a concrete rejection.',
                                      'evidence_refs':[capture['id']]}
        model = {'model':'synthetic/vision','vision':True}
        first = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,model)
        second = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,model)
        self.assertEqual(first,second)
        self.assertEqual(first['data']['previous_verification_id'],prior['id'])
        self.assertIn('observation_scope',json.loads(provider.chat.call_args.args[4].split('\nEVIDENCE\n')[1]))
        provider.chat.assert_called_once()

    def test_legacy_scope_recovery_requires_recorded_rendered_documents(self):
        capture,audit,check = self.scoped_baseline()
        prior = self.previous_baseline('scope-without-dom',capture,audit,check)
        data = dict(prior['data'],version=evidence_verifier.LEGACY_SCOPE_VERSION)
        prior = self.s.append('evidence_verification',data,'fixture','legacy-scope-without-dom')
        audit['data']['artifacts'].pop('rendered')
        provider = Mock(campaign='fixture')
        result = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,
                                         {'model':'synthetic/vision','vision':True})
        self.assertEqual(result,prior)
        provider.chat.assert_not_called()

    def test_source_visual_input_omits_hidden_inventory_but_keeps_views_and_guard_metrics(self):
        capture,audit,check = self.scoped_baseline()
        check['data']['metrics'] = {'text_coverage':1.0,'control_coverage':1.0,'broken_images':0}
        before = json.dumps([capture,audit,check],sort_keys=True)
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'admitted','rationale':'Same styled views.',
                                      'evidence_refs':[capture['id']]}
        evidence_verifier.verify(self.s,provider,'run','visual-source',capture,audit,check,
                                {'model':'synthetic/vision','vision':True})
        prompt = provider.chat.call_args.args[4]
        evidence = json.loads(prompt.split('\nEVIDENCE\n')[1])
        self.assertNotIn(capture['data']['visible']['text'],prompt)
        self.assertNotIn('image_identity',evidence)
        self.assertEqual(evidence['checks'],check['data']['metrics'])
        self.assertEqual(len(provider.chat.call_args.kwargs['image_parts']),2)
        self.assertIn(capture['id'],evidence['references'])
        self.assertEqual(json.dumps([capture,audit,check],sort_keys=True),before)

    def test_legacy_image_review_can_receive_one_visual_task_correction(self):
        capture,audit,check = self.scoped_baseline()
        prior = self.previous_baseline('legacy-image-parent',capture,audit,check)
        data = dict(prior['data'],version=evidence_verifier.LEGACY_IMAGE_VERSION)
        prior = self.s.append('evidence_verification',data,'fixture','legacy-image')
        provider = Mock(campaign='fixture')
        provider.chat.return_value = {'status':'rejected','rationale':'Keep current-version rejection.',
                                      'evidence_refs':[capture['id']]}
        model = {'model':'synthetic/vision','vision':True}
        first = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,model)
        second = evidence_verifier.verify(self.s,provider,'run',prior['id'],capture,audit,check,model)
        self.assertEqual(first,second)
        self.assertEqual(first['data']['version'],evidence_verifier.BASELINE_VERSION)
        self.assertEqual(first['data']['previous_verification_id'],prior['id'])
        self.assertEqual(first['data']['status'],'rejected')
        provider.chat.assert_called_once()

    def test_candidate_local_decision_judges_observable_failure_not_facts(self):
        c,a,d=self.fixtures();provider=Mock(campaign='fixture')
        provider.decisions.return_value={'reason':{'type':'choice','choice':'degraded'},'impact':{'type':'choice','choice':'material'},'blocking_defect':{'type':'predicate','probability':.97}}
        model={'model':'openai/gpt-6-luna-decisions','output_modalities':['decisions'],'vision':True}
        result=evidence_verifier.verify(self.s,provider,'run','creative-verification',c,a,d,model,candidate=True,candidate_local=True)
        self.assertEqual(result['data']['status'],'rejected')
        question=provider.decisions.call_args.args[4][0]
        self.assertIn('not reasons for rejection',question['instructions'])
        self.assertIn('Do not evaluate factual truth',question['instructions'])
        self.assertNotIn('unsupported',[v['value']for v in question['choices']])

    def test_current_visual_review_is_independent_of_destination_check(self):
        c,a,d=self.fixtures('rejected');provider=Mock(campaign='fixture')
        provider.chat.return_value={'reason_code':'usable','impact':'none','blocking_confidence':.02,'rationale':'Legible candidate; remote links are not visually verified.','evidence_refs':[c['id'],a['id']]}
        result=evidence_verifier.verify(self.s,provider,'run','independent-candidate-visual',c,a,d,{'model':'synthetic/vision','vision':True},candidate=True,candidate_local=True)
        provider.chat.assert_called_once()
        self.assertEqual(result['data']['status'],'admitted')
        self.assertEqual(result['data']['deterministic_status'],'rejected')

    def test_visual_review_does_not_receive_source_fact_judging_task(self):
        c,a,d=self.fixtures();provider=Mock(campaign='fixture')
        provider.chat.return_value={'reason_code':'usable','impact':'none','blocking_confidence':.01,'rationale':'The quantities occur in the acquired source.','evidence_refs':[c['id']]}
        source='<html><head><style>.hide{display:none}</style></head><body><h1>Courses</h1><div hidden>2,180+ courses</div><script>untrustedInstruction()</script></body></html>'
        evidence_verifier.verify(self.s,provider,'run','complete-factual-source',c,a,d,{'model':'synthetic/vision','vision':True},candidate=True,candidate_local=True,reference_source=source)
        prompt=provider.chat.call_args.args[4];evidence=json.loads(prompt.split('\nEVIDENCE\n')[1])
        self.assertNotIn('acquired_source_facts',evidence)
        self.assertNotIn('2,180+ courses',prompt)
        self.assertIn('Do not evaluate factual truth',prompt)

    def test_decisions_redesign_admission_keeps_baseline_styling_check(self):
        c,a,d=self.fixtures();provider=Mock(campaign='fixture')
        provider.decisions.return_value={'reason':{'type':'choice','choice':'usable'}}
        model={'model':'openai/gpt-6-luna-decisions','vision':True,'output_modalities':['decisions']}
        for candidate in (False,True):
            record=evidence_verifier.verify(self.s,provider,'run','design-'+str(candidate),c,a,d,model,candidate=candidate)
            self.assertEqual(record['data']['status'],'admitted')
            question=provider.decisions.call_args.args[4][0]
            degraded=next(x['description'] for x in question['choices'] if x['value']=='degraded')
            if candidate:self.assertIn('different or simpler design alone is not degradation',degraded)
            else:self.assertIn('Essential styling',degraded)

    def test_invalid_candidate_agent_blocks_retention_and_judging(self):
        self.f.manifest['capture_verifier']=dict(self.f.legacy_judges[0],vision=True)
        old_capture=self.f.environment.capture;old_audit=self.f.environment.audit
        def capture(*args):
            row=old_capture(*args);row['data']['visible']={'text':'Known synthetic fixture'}
            return row
        def audit(*args):
            row=old_audit(*args);row['data']['artifacts']['screenshot']=next(r['id'] for r in self.s.list('artifact',args[2]) if r['data']['role']=='capture_screenshot')
            return row
        self.f.environment.capture=capture;self.f.environment.audit=audit
        self.f.environment.replay_check=lambda c,s,cid,i,a:self.s.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{}},cid,i)
        old_post=self.f.session.post;agent_calls=[]
        def post(url,**kwargs):
            body=kwargs['json'];content=body['messages'][0]['content'];prompt=content[0]['text'] if isinstance(content,list) else content
            if not prompt.startswith('You are the capture evidence verification agent.'):
                return old_post(url,**kwargs)
            self.f.session.requests.append(body);agent_calls.append(body)
            refs=json.loads(prompt.split('\nEVIDENCE\n')[1])['references']
            answer={'status':'admitted' if len(agent_calls)==1 else 'rejected','rationale':'Known fixture assessment.','evidence_refs':[refs[0]]}
            payload={'model':body['model'],'usage':{'prompt_tokens':10,'completion_tokens':10,'cost':0},'choices':[{'finish_reason':'stop','message':{'content':'```json\n'+json.dumps(answer)+'\n```'}}]}
            return type('Response',(),{'status_code':200,'text':json.dumps(payload)})()
        self.f.session.post=post;c=self.f.campaign();self.f.execute(c)
        self.assertTrue(self.s.list('run_result',c['id']),self.s.checkpoint(c['id'])[0])
        result=self.s.list('run_result',c['id'])[0]['data']
        self.assertTrue(result['selected']['original'])
        self.assertEqual(len(agent_calls),1+len(self.s.list('attempt',c['id'])))
        for retained in self.s.list('retention',c['id']):
            self.assertFalse(retained['data']['candidate']['admissible']);self.assertFalse(retained['data']['changed'])
        for case in self.s.list('review_case',c['id']):
            if case['data'].get('attempt_id'):self.assertEqual(case['data']['review']['initial'],[{},{}])

    def test_provenance_flag_requires_human_confirmation_without_visual_veto(self):
        c,a,d=self.fixtures();provider=Mock(campaign='fixture')
        destinations=[{'target':'https://example.test/new'}]
        d=self.s.append('replay_admission',d['data']|{'metrics':{'unverified_destinations':destinations},
            'warnings':['destination_provenance_requires_human_confirmation']})
        provider.chat.return_value={'reason_code':'usable','impact':'none','blocking_confidence':.01,
            'rationale':'Coherent legible page.','evidence_refs':[c['id']]}
        result=evidence_verifier.verify(self.s,provider,'run','provenance-flag',c,a,d,
            {'model':'synthetic/vision','vision':True},candidate=True,candidate_local=True)
        self.assertEqual(result['data']['status'],'admitted')
        self.assertEqual(result['data']['blocking_confidence'],.01)
        self.assertEqual(result['data']['destination_provenance'],destinations)
        self.assertIn('destination_provenance_requires_human_confirmation',result['data']['warnings'])
        evidence=json.loads(provider.chat.call_args.args[4].split('\nEVIDENCE\n')[1])
        self.assertNotIn('unverified_destinations',evidence['checks'])
