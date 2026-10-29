"""Synthetic Decisions fixtures: transport, accounting and fail-closed admission."""
import base64
import json
import tempfile
import unittest
import requests
from unittest.mock import Mock
import test_harness
from harness import evidence_verifier, category_review
from harness.contracts import ContractError, validate_manifest
from harness.decision_models import DEFINITIONS, snapshot
from harness.providers import Providers, Ledger, BudgetStop, input_token_bound

class MultimodalDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.f=test_harness.HarnessTest();self.f.setUp();self.addCleanup(self.f.tmp.cleanup)
        self.store=self.f.store;self.model=snapshot(DEFINITIONS[0])
        self.c=self.f.campaign();self.c['data']['decision_model']=self.model
        self.session=Mock();self.provider=Providers(self.store,self.c['data'],self.c['id'],{'openrouter_api_key':'fixture-key','openrouter_base_url':'https://openrouter.ai/api/v1'},session=self.session)
        self.image={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(b'synthetic image').decode()}}
        self.questions=[{'type':'choice','name':'state','instructions':'Assess synthetic evidence.', 'choices':[{'value':v} for v in ('usable','blank')]}]
        self.reply({'state':{'type':'choice','choice':'usable','probabilities':{'usable':.9,'blank':.1}}})
    def reply(self,answers,model=None,cost=.00001):
        raw={'id':'fixture-response','model':model or self.model['response_model'],'answers':answers,'usage':{'input_tokens':50,'output_tokens':0,'cost':cost}}
        response=requests.Response();response.status_code=200;response.encoding="utf-8"
        response._content=json.dumps(raw).encode();response._content_consumed=True
        self.session.post.return_value=response
    def test_multimodal_request_recovery_and_receipt(self):
        for _ in range(2):
            answer=self.provider.decisions('run','review','image','Synthetic state',self.questions,image_parts=[self.image,self.image])
            self.assertEqual(answer['state']['choice'],'usable')
        self.session.post.assert_called_once();body=self.session.post.call_args.kwargs['json']
        self.assertEqual(body['state'],['Synthetic state',self.image,self.image])
        self.assertTrue(self.session.post.call_args.args[0].endswith('/api/alpha/decisions'))
        row=Ledger(self.store).rows(self.c['id'])[0]
        self.assertEqual((row['cost_status'],row['output_tokens']),('provider_reported',0));self.assertEqual(row['cost'],.00001)
        bound,images=input_token_bound(body,self.model)
        self.assertEqual((bound,images),(self.model['context_length'],2))
    def test_malformed_paid_output_keeps_receipt_no_chat_fallback(self):
        self.reply({},cost=.00002)
        with self.assertRaises(ContractError):self.provider.decisions('run','repair','bad','Evidence',self.questions,image_parts=[self.image])
        row=Ledger(self.store).rows(self.c['id'])[0]
        self.assertEqual(row['cost_status'],'provider_reported');self.assertEqual(row['cost'],.00002)
        self.assertEqual(self.session.post.call_count,1)
    def test_image_reservation_blocks_before_http_and_text_overflow_not_truncated(self):
        self.provider.manifest['review_budget']['max_call_cost_usd']=.01
        with self.assertRaises(BudgetStop):self.provider.decisions('run','review','over','Evidence',self.questions,image_parts=[self.image])
        with self.assertRaises(BudgetStop):self.provider.decisions('run','review','text-over','x'*(self.model['context_length']+1),self.questions,image_parts=[self.image])
        self.session.post.assert_not_called();self.assertEqual(Ledger(self.store).rows(self.c['id']),[])
    def test_invalid_images_or_text_only_model_never_dispatch(self):
        bad=[{'type':'image_url','image_url':{'url':'https://example.com/p.png'}}, {'type':'input_image','image_url':'data:image/png;base64,eA=='},
             {'type':'image_url','image_url':{'url':'data:image/png;base64,e'}}]
        for image in bad:
            with self.assertRaises(ContractError):self.provider.decisions('run','review','invalid','Evidence',self.questions,image_parts=[image])
        with self.assertRaises(ContractError):self.provider.decisions('run','review','text-only','Evidence',self.questions,model=snapshot(DEFINITIONS[1]),image_parts=[self.image])
        self.session.post.assert_not_called()
    def fixture(self,status='admitted'):
        image=self.store.blob(b'synthetic','capture_screenshot',media_type='image/png')
        c=self.store.append('capture',{'screenshot_id':image['id'],'visible':{'text':'Fixture'}})
        a=self.store.append('audit',{'artifacts':{'screenshot':image['id']}})
        d=self.store.append('replay_admission',{'status':status,'reasons':['fixture'] if status!='admitted' else [],'metrics':{}})
        return c,a,d
    def test_typed_capture_admission_and_recovery(self):
        c,a,d=self.fixture();p=Mock(campaign=self.c['id'])
        p.decisions.return_value={'reason':{'type':'choice','choice':'usable'}}
        for _ in range(2):row=evidence_verifier.verify(self.store,p,'run','capture-decision',c,a,d,self.model)
        self.assertEqual(row['data']['status'],'admitted');self.assertEqual(row['data']['reason_code'],'usable')
        self.assertIn(c['id'],row['data']['evidence_refs']);p.decisions.assert_called_once();p.chat.assert_not_called()
        self.assertEqual(len(p.decisions.call_args.kwargs['image_parts']),2)
        questions=p.decisions.call_args.args[4]
        self.assertEqual([q['name'] for q in questions],['reason'])
    def test_refusals_missing_invalid_and_unexpected_answers_cannot_admit(self):
        answers=[{}, {'reason':{'type':'refusal'}}, {'reason':{'type':'choice','choice':'invented'}},
            {'status':{'type':'choice','choice':'admitted'},'reason':{'type':'choice','choice':'blocked'}},
            {'status':{'type':'choice','choice':'rejected'},'reason':{'type':'choice','choice':'insufficient'}}]
        for n,answer in enumerate(answers):
            c,a,d=self.fixture();p=Mock(campaign=self.c['id']);p.decisions.return_value=answer
            row=evidence_verifier.verify(self.store,p,'run','refusal-'+str(n),c,a,d,self.model)
            self.assertEqual(row['data']['status'],'review_required');p.chat.assert_not_called()
            self.assertEqual(row['data']['answers'],answer)
    def test_single_classification_maps_failure_and_uncertainty_without_admission(self):
        for reason in ('blank','blocked','unrelated','degraded','out_of_scope','insufficient'):
            with self.subTest(reason=reason):
                c,a,d=self.fixture();p=Mock(campaign=self.c['id'])
                p.decisions.return_value={'reason':{'type':'choice','choice':reason}}
                row=evidence_verifier.verify(self.store,p,'run','reason-'+reason,c,a,d,self.model)
                self.assertEqual(row['data']['status'],'review_required' if reason=='insufficient' else 'rejected')
                self.assertEqual(row['data']['reason_code'],reason);p.chat.assert_not_called()
    def test_existing_versioned_evidence_is_not_reclassified(self):
        c,a,d=self.fixture();p=Mock(campaign=self.c['id'])
        old=self.store.append('evidence_verification',{'version':'capture-evidence-verifier-v3','status':'review_required','rationale':'Inconsistent capture decisions'},self.c['id'],'old-check')
        row=evidence_verifier.verify(self.store,p,'run','old-check',c,a,d,self.model)
        self.assertEqual(row,old);p.decisions.assert_not_called()
    def test_deterministic_failure_never_spends(self):
        c,a,d=self.fixture('rejected');p=Mock(campaign=self.c['id'])
        row=evidence_verifier.verify(self.store,p,'run','blocked-capture',c,a,d,self.model)
        self.assertEqual(row['data']['status'],'rejected');p.decisions.assert_not_called();p.chat.assert_not_called()
    def test_category_review_preserves_dataset_and_reuses_decision(self):
        p=Mock(campaign=self.c['id']);p.decisions.return_value={'category':{'type':'choice','choice':'Education'}}
        observation={'id':2,'url':'https://fixture.example/','site_category':'Technology'}
        for _ in range(2):row=category_review.review(self.store,p,'run','category-review',self.model,observation,'<main>Education</main>')
        self.assertEqual(observation['site_category'],'Technology');self.assertEqual(row['data']['category'],'Education')
        self.assertEqual(row['data']['original_category'],'Technology');self.assertEqual(row['data']['answers'],p.decisions.return_value)
        p.decisions.assert_called_once();p.chat.assert_not_called()
    def test_manifest_accepts_only_image_capable_capture_decisions(self):
        m=dict(self.f.manifest,capture_verifier=DEFINITIONS[0],category_review_model=DEFINITIONS[0])
        result=validate_manifest(m);self.assertEqual(result['capture_verifier']['model'],self.model['model'])
        with self.assertRaises(ContractError):validate_manifest(dict(m,capture_verifier=DEFINITIONS[1]))
