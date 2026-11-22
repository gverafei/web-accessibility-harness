import tempfile,unittest,json
from unittest.mock import Mock
from harness.store import Store
from harness.contracts import ContractError
from accessibility_taxonomy.image_review import review
from accessibility_taxonomy.image_evidence import vision_worker
class ImageReviewTests(unittest.TestCase):
 def test_visual_reviewer_is_independent_of_the_repair_worker_pool(self):
  verifier={'id':'openai/gpt-6-luna','model':'openai/gpt-6-luna','reasoning_effort':'low','vision':True}
  manifest={'workers':[{'model':'anthropic/claude-haiku-5.5','reasoning_effort':'low','vision':True}],'capture_verifier':verifier}
  self.assertIs(vision_worker(manifest),verifier)
  for key,value in [('model','anthropic/claude-haiku-5.5'),('reasoning_effort','high'),('vision',False)]:
   with self.assertRaises(ContractError):vision_worker(dict(manifest,capture_verifier=dict(verifier,**{key:value})))

 def test_typed_exact_identity_cache_and_explicit_vision_worker(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);p=Mock(campaign='fixture');p.manifest={'workers':[{'model':'openai/gpt-6-luna','reasoning_effort':'low','vision':True}]};p.ledger.rows.return_value=[]
   rows=[{'opportunity_id':'a','type':'image-alt-not-descriptive','context':{'supplementary_image':{'sha256':'hash'}}}];images=[{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]
   for invalid in ({'judgments':[]},{'judgments':[{'opportunity_id':'other','status':'passed'}]},{'judgments':[{'opportunity_id':'image_1','status':'passed'},{'opportunity_id':'image_1','status':'failed'}]}):
    p.chat.return_value=json.dumps(invalid)
    with self.assertRaises(ContractError):review(store,p,'run','a',rows,images)
   p.chat.return_value=json.dumps({'judgments':[{'opportunity_id':'image_1','status':'passed'}]})
   result=review(store,p,'run','a',rows,images);calls=p.chat.call_count;self.assertEqual(result['data']['opportunities'][0]['method'],'luna_vision');self.assertEqual(p.chat.call_args.args[3]['reasoning_effort'],'low')
   self.assertEqual(review(store,p,'run','a',rows,images)['id'],result['id']);self.assertEqual(p.chat.call_count,calls)
   with self.assertRaises(ContractError):review(store,p,'run','a',[dict(rows[0],context={'changed':True})],images)

 def test_short_wire_ids_restore_exact_long_ids_and_partial_cache(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);p=Mock(campaign='fixture');p.manifest={'workers':[{'model':'openai/gpt-6-luna','reasoning_effort':'low','vision':True}]};p.ledger.rows.return_value=[]
   rows=[{'opportunity_id':char*64,'type':'image-alt-not-descriptive','context':{'label':char,'supplementary_image':{'sha256':char}}} for char in 'ab']
   images=[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+char}} for char in 'ab']
   p.chat.return_value=json.dumps({'judgments':[{'opportunity_id':'image_1','status':'failed'},{'opportunity_id':'image_2','status':'passed'}]})
   result=review(store,p,'run','batch',rows,images)
   self.assertEqual([(x['opportunity_id'],x['status']) for x in result['data']['opportunities']],[(rows[0]['opportunity_id'],'failed'),(rows[1]['opportunity_id'],'passed')])
   prompt=p.chat.call_args.args[4];self.assertNotIn(rows[0]['opportunity_id'],prompt);self.assertIn('image_2',prompt)
   changed=dict(rows[1],context=dict(rows[1]['context'],label='changed'))
   p.chat.return_value=json.dumps({'judgments':[{'opportunity_id':'image_1','status':'not_applicable'}]})
   result=review(store,p,'run','next',[rows[0],changed],images)
   self.assertEqual([x['status'] for x in result['data']['opportunities']],['failed','not_applicable'])
   self.assertEqual(rows[1]['opportunity_id'],'b'*64)
