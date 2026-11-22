import tempfile
import unittest
import requests
from harness.store import Store
from harness.providers import Ledger, BudgetStop, input_token_bound

class TierReservationTests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
  self.store=Store(self.directory.name);self.ledger=Ledger(self.store)
  self.model={'id':'fixture','model':'fixture/worker','context_length':1050000,
   'input_usd_per_million':2.,'output_usd_per_million':10.,
   'pricing_overrides':[{'min_prompt_tokens':272000,'input_usd_per_million':4.,'output_usd_per_million':15.}]}
  self.limits={'max_cost_usd':5,'max_calls':20,'max_call_cost_usd':.25}
 def test_short_request_reserves_only_reachable_tiers(self):
  request={'model':'fixture/worker','messages':[{'role':'user','content':'a'*60000}],'max_tokens':8000}
  bound,_=input_token_bound(request,self.model)
  row,new=self.ledger.begin('fixture','run','repair','short',request,self.model,self.limits,5)
  self.assertTrue(new);self.assertAlmostEqual(row['reserved'],(2*bound+10*8000)/1e6)
  self.assertLess(row['reserved'],.25)
 def test_long_bound_uses_long_tier_and_blocks_without_receipt(self):
  request={'model':'fixture/worker','messages':[{'role':'user','content':'a'*273000}],'max_tokens':8000}
  with self.assertRaises(BudgetStop):self.ledger.begin('fixture','run','repair','long',request,self.model,self.limits,5)
  self.assertEqual(self.ledger.rows(),[])
 def test_unknown_image_bound_cannot_get_short_tier(self):
  request={'model':'fixture/worker','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]}],'max_tokens':8000}
  with self.assertRaises(BudgetStop):self.ledger.begin('fixture','run','repair','image',request,self.model,self.limits,5)
  self.assertEqual(self.ledger.rows(),[])

 def test_byte_upper_bound_is_not_native_context_overflow_when_compression_disabled(self):
  model={**self.model,'provider':'openrouter','context_length':2000,'input_usd_per_million':.1,'output_usd_per_million':.5}
  request={'messages':[{'role':'user','content':'漢字'*1000}],'max_tokens':100,'plugins':[{'id':'context-compression','enabled':False}]}
  bound,_=input_token_bound(request,model);self.assertGreater(bound,model['context_length'])
  row,_=self.ledger.begin('fixture','run','repair','native',request,model,{**self.limits,'max_call_cost_usd':5},5)
  stored=self.store.get(row['request_id'])['data'];self.assertEqual(stored['request'],request)
  self.assertEqual(stored['reservation']['context_validation'],'provider-native-tokenizer-no-compression')
  self.assertAlmostEqual(row['reserved'],(bound*.1+100*.5)/1e6)
 def test_native_context_still_requires_disabled_compression_and_reserves_full_price(self):
  model={**self.model,'provider':'openrouter','context_length':2000};body={'messages':[{'role':'user','content':'漢字'*1000}],'max_tokens':100}
  with self.assertRaises(BudgetStop):self.ledger.begin('fixture','run','repair','unknown-transform',body,model,self.limits,5)
  body['plugins']=[{'id':'context-compression','enabled':False}]
  with self.assertRaises(BudgetStop):self.ledger.begin('fixture','run','repair','price',body,model,{**self.limits,'max_call_cost_usd':.001},5)
  body['max_tokens']=2001
  with self.assertRaises(BudgetStop):self.ledger.begin('fixture','run','repair','output-over',body,model,self.limits,5)
  self.assertEqual(self.ledger.rows(),[])

 def test_direct_sql_dispatch_also_disables_compression_before_context_admission(self):
  import json
  from unittest.mock import Mock
  from harness.providers import Providers
  model={**self.model,'provider':'openrouter','context_length':2000,'input_usd_per_million':.1,'output_usd_per_million':.5,'pricing_source':'fixture'}
  body={'model':model['model'],'messages':[{'role':'user','content':'漢字'*1000}],'max_tokens':100}
  session=Mock();response=requests.Response();response.status_code=200;response.encoding='utf-8'
  response._content=json.dumps({'model':model['model'],'usage':{'prompt_tokens':500,'completion_tokens':10,'cost':.0001},'choices':[]}).encode();response._content_consumed=True
  session.post.return_value=response
  limits={**self.limits,'max_call_cost_usd':5,'max_seconds':900};providers=Providers(self.store,{'repair_budget':limits,'review_budget':limits,'campaign_cost_limit':5},'fixture',{},session=session)
  providers.dispatch('run','repair','sql-direct',model,body,'https://openrouter.ai/api/v1/chat/completions','fixture-token')
  sent=session.post.call_args.kwargs['json'];self.assertEqual(sent['messages'],body['messages']);self.assertNotIn('plugins',body)
  self.assertEqual(sent['plugins'],[{'id':'context-compression','enabled':False}]);self.assertEqual(self.store.get(self.ledger.rows()[0]['request_id'])['data']['request'],sent)
