import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from accessibility_taxonomy import contextual_review
from accessibility_taxonomy.image_review import review
from harness.store import Store


class ExactEvidenceTests(unittest.TestCase):
    def test_unchanged_context_reuses_blind_judgment_but_changed_context_and_model_are_rejudged(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);calls=[]
            def decisions(run,account,key,evidence,questions,**kwargs):
                calls.append(questions)
                return {q['name']:{'type':'choice','choice':'passed' if len(calls)==1 else 'failed'}for q in questions}
            p=SimpleNamespace(campaign='test',decisions=decisions)
            row={'opportunity_id':'a','type':'heading-not-descriptive','status':'insufficient_evidence','context':{'observed_text':'Useful content'}}
            a=contextual_review(store,p,'r','before',{}, {'origin':'https://example.com','document_sha256':'original'},[row])
            changed=dict(row,opportunity_id='b',context={'observed_text':'Different content'})
            b=contextual_review(store,p,'r','after',{}, {'origin':'https://example.com','document_sha256':'candidate'},[row,changed])
            self.assertEqual(len(calls),2)
            self.assertEqual([q['name']for q in calls[1]],['b'])
            self.assertEqual([r['status']for r in b['data']['opportunities']],['passed','failed'])
            self.assertEqual(a['data']['judgment_cache_ids']['a'],b['data']['judgment_cache_ids']['a'])
            contextual_review(store,p,'r','different-model',{'id':'other'}, {'origin':'https://example.com'},[row])
            self.assertEqual(len(calls),3)
            self.assertNotIn('previous_verdict',json.dumps(calls))
            self.assertNotIn('worker_identity',json.dumps(calls))

    def test_identical_images_reuse_only_when_image_bytes_and_full_usage_match(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);calls=[]
            model={'model':'openai/gpt-6-luna','reasoning_effort':'low','vision':True}
            def chat(run,account,key,model,prompt,image_parts):
                calls.append((prompt,image_parts))
                return json.dumps({'judgments':[{'opportunity_id':'image_1','status':'passed'}]})
            p=SimpleNamespace(campaign='test',manifest={'workers':[model]},chat=chat,ledger=SimpleNamespace(rows=lambda *args:[]))
            row={'opportunity_id':'a','type':'image-alt-not-descriptive','status':'insufficient_evidence','context':{'supplementary_image':{'sha256':'verified'},'image_usage':{'purpose':'Download'}}}
            image={'type':'image_url','image_url':{'url':'data:image/png;base64,Ynl0ZXM='}}
            first=review(store,p,'r','first',[row],[image]);second=review(store,p,'r','second',[row],[image])
            self.assertEqual(len(calls),1)
            self.assertEqual(first['data']['judgment_cache_ids'],second['data']['judgment_cache_ids'])
            different=copy.deepcopy(row);different['context']['image_usage']['purpose']='Different'
            review(store,p,'r','third',[different],[image]);self.assertEqual(len(calls),2)
            changed=copy.deepcopy(image);changed['image_url']['url']='data:image/png;base64,Y2hhbmdlZA=='
            review(store,p,'r','fourth',[different],[changed]);self.assertEqual(len(calls),3)

    def test_paid_invalid_answer_never_seeds_reusable_cache(self):
        from harness.contracts import ContractError
        with tempfile.TemporaryDirectory() as root:
            store=Store(root)
            p=SimpleNamespace(campaign='test',decisions=lambda *args,**kwargs:{'a':{'type':'choice','choice':'passed','confidence':2}})
            row={'opportunity_id':'a','type':'heading-not-descriptive','status':'error','context':{'observed_text':'Content'}}
            with self.assertRaises(ContractError):contextual_review(store,p,'r','invalid',{}, {},[row])
            self.assertEqual(store.list('taxonomy_judgment_cache'),[])
