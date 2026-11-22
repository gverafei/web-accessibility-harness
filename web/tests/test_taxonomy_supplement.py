import unittest,tempfile,copy
from harness.store import Store
from harness.contracts import ContractError
from accessibility_taxonomy.supplement import resolve
class Ledger:
 def rows(self,*args):return []
class Provider:
 campaign='test';ledger=Ledger();manifest={}
 def __init__(self):self.count=0
 def decisions(self,run,account,key,evidence,questions,**kwargs):
  self.count+=1
  return {q['name']:{'type':'choice','choice':'visible_text' if 'visible_text' in [c['value'] for c in q['choices']] else 'not_applicable'} for q in questions}
class SupplementTests(unittest.TestCase):
 def test_hash_blinding_numeric_verdict_cache_and_real_attribution(self):
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);p=Provider();base=store.append('taxonomy_assessment',{'version':'retained-taxonomy-assessment-v8','audit_id':'a','document_sha256':'doc','model':{},'opportunities':[{'opportunity_id':'c','type':'color-contrast','status':'insufficient_evidence','method':'axe','target':['#a']},{'opportunity_id':'v','type':'video-caption','status':'insufficient_evidence','method':'axe','target':['#v']}],'measurement_cost_usd':0})
   sup={'version':'rendered-taxonomy-supplement-v3','document_sha256':'doc','items':[{'type':'color-contrast','target':['#a'],'evidence':{'measurement':{'status':'passed','ratio':3.89,'threshold':4.5}}},{'type':'video-caption','target':['#v'],'evidence':{'html':'<video id="v"></video>','media':{'complete':True,'audio_tracks':0,'caption_tracks':0}}}]}
   r=resolve(store,p,'test',base,sup,{});self.assertEqual([x['status'] for x in r['data']['opportunities']],['failed','not_applicable']);self.assertEqual(r['data']['audit_id'],'a');
   from accessibility_taxonomy.presentation import details
   view=details({'original_assessment_id':r['id'],'retained_assessment_id':r['id']},store);self.assertEqual(len(view['supplements']),2);self.assertEqual(view['supplements'][0]['before']['ratio'],3.89);self.assertEqual(view['supplements'][1]['after']['audio_tracks'],0);
   self.assertEqual(p.count,1);self.assertEqual(resolve(store,p,'test',base,sup,{}),r);self.assertEqual(p.count,1)
   revised=store.append('taxonomy_assessment',base['data'],'test')
   reused=resolve(store,p,'test',revised,sup,{})
   self.assertEqual(p.count,1);self.assertEqual(reused['data']['supplement_judgment_parent_id'],r['id'])
   self.assertEqual(reused['data']['supplementary_judgments'],r['data']['supplementary_judgments'])
   wrong=copy.deepcopy(sup);wrong['document_sha256']='wrong'
   with self.assertRaises(ContractError):resolve(store,p,'test',base,wrong,{})
 def test_contrast_pixel_array_stays_complete_in_artifact_not_repeated_in_question(self):
  from harness.contracts import digest
  import json
  class Capture(Provider):
   def decisions(self,*args,**kwargs):self.question=args[4][0];return super().decisions(*args,**kwargs)
  with tempfile.TemporaryDirectory()as root:
   store=Store(root);provider=Capture()
   base=store.append('taxonomy_assessment',{'audit_id':'audit','document_sha256':'doc','measurement_cost_usd':0,
    'opportunities':[{'opportunity_id':'c','type':'color-contrast','status':'insufficient_evidence','method':'axe','target':['#a']}]})
   colors=[[255,255,255]]*50000
   supplement={'version':'rendered-taxonomy-supplement-v3','document_sha256':'doc',
    'items':[{'type':'color-contrast','target':['#a'],'evidence':{'measurement':{'status':'passed','ratio':7,'threshold':4.5,'background_colors':colors}}}]}
   before=copy.deepcopy(supplement);result=resolve(store,provider,'run',base,supplement,{})
   self.assertEqual(supplement,before)
   evidence=json.loads(provider.question['instructions'].split('Evidence: ')[1])
   self.assertNotIn('background_colors',evidence['measurement'])
   self.assertEqual(evidence['measurement']['background_color_evidence']['sha256'],digest(colors))
   self.assertEqual(evidence['measurement']['background_color_evidence']['count'],50000)
   self.assertEqual(result['data']['opportunities'][0]['status'],'passed')
   progress=store.checkpoint('run-taxonomy-progress')[0]
   self.assertEqual((progress['completed'],progress['total'],progress['status']),(1,1,'completed'))

 def test_shared_screenshot_preserves_every_judgment_and_rejects_changed_bytes(self):
  import base64,hashlib,json
  class CapturingProvider(Provider):
   def decisions(self,*args,**kwargs):
    self.images=kwargs['image_parts'];self.evidence=json.loads(args[3]);return super().decisions(*args,**kwargs)
  with tempfile.TemporaryDirectory() as root:
   store=Store(root);p=CapturingProvider();body=base64.b64encode(b'verified-image-bytes').decode();key=hashlib.sha256(b'verified-image-bytes').hexdigest()
   rows=[{'opportunity_id':n,'type':'color-contrast','status':'insufficient_evidence','method':'axe','target':['#'+n]} for n in ['a','b']]
   base=store.append('taxonomy_assessment',{'document_sha256':'doc','opportunities':rows,'measurement_cost_usd':0})
   sup={'version':'rendered-taxonomy-supplement-v4','document_sha256':'doc','screenshots':{key:{'sha256':key,'document_sha256':'doc','viewport':{'x':0,'y':0,'width':1440,'height':1000},'body':body}},'items':[{'type':'color-contrast','target':['#'+n],'evidence':{'screenshot_id':key,'measurement':{'status':'passed','ratio':7,'threshold':4.5}}}for n in ['a','b']]}
   result=resolve(store,p,'test',base,sup,{})
   self.assertEqual([x['status'] for x in result['data']['opportunities']],['passed','passed']);self.assertEqual(len(p.images),1);self.assertEqual(p.evidence['shared_image_opportunities'],{'a':['a','b']})
   wrong=copy.deepcopy(sup);wrong['screenshots'][key]['body']=base64.b64encode(b'changed').decode()
   with self.assertRaises(ContractError):resolve(store,p,'test',base,wrong,{})
   self.assertEqual(p.count,1)
