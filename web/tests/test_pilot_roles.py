"""Synthetic role/routing/reservation checks; no provider calls."""
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock

from model_catalog_metadata import reviewed_metadata, pricing_rates
from harness.contracts import ContractError, model_snapshot
from harness.pilot import build, resolve
from harness.providers import input_token_bound, Ledger
from harness.selection import actions, select
from harness.store import Store


class PilotRolesTest(unittest.TestCase):
    def recipe(self):
        catalogue=reviewed_metadata()
        pairs=[('luna-low','openai/gpt-6-luna','low'),
               ('opaque-haiku','anthropic/claude-haiku-5.5','low'),
               ('luna-high','openai/gpt-6-luna','high'),
               ('haiku-high','anthropic/claude-haiku-5.5','high'),
               ('gemini','google/gemini-3.8-flash','medium'),
               ('sol','openai/gpt-6.1-sol','high'),
               ('opus','anthropic/claude-opus-5.5','high'),
               ('astra','openai/gpt-6-astra','low')]
        metadata={key:dict(catalogue[actual],reasoning_effort=effort) for key,actual,effort in pairs}
        return build(metadata,worker_ids=[key for key,_,_ in pairs[:6]],
                     fixed_worker_ids=['luna-low','opaque-haiku'],capture_verifier_id='opus')

    def test_explicit_pool_fixed_subset_and_probe_coverage(self):
        recipe=self.recipe();manifest=resolve(recipe,'matrix',corpus_id='fixture',page_ids=list('abcdefghij'))
        fixed=[c for c in manifest['conditions'] if c['level']!=6]
        self.assertEqual(len(fixed),10)
        self.assertEqual({c['worker_id'] for c in fixed},{'luna-low','opaque-haiku'})
        self.assertEqual([m['id'] for m in manifest['workers']],recipe['roles']['dynamic_worker_ids'])
        self.assertNotIn('judges',manifest)
        self.assertEqual(manifest['capture_verifier']['model'],'anthropic/claude-opus-5.5')
        self.assertEqual(len(recipe['stages']['connection']['requests']),7)
        self.assertEqual(recipe['expected_core_runs'],130)
        for c in fixed:
            self.assertEqual(actions(manifest,c),[f'P{c["level"]}:{c["worker_id"]}'])
            self.assertEqual(actions(manifest,c,True),[f'P{c["level"]}:{c["worker_id"]}'])
        dynamic=manifest['conditions'][-1]
        self.assertEqual(len(actions(manifest,dynamic)),30)
        self.assertEqual(len(actions(manifest,dynamic,True)),30)
        with self.assertRaises(ContractError):
            build({m['id']:m for m in manifest['workers']+[manifest['capture_verifier']]},
                  worker_ids=recipe['roles']['dynamic_worker_ids'],fixed_worker_ids=['luna-low','missing'],
                  capture_verifier_id='opus')

    def test_opaque_choices_are_grounded_in_both_selectors(self):
        manifest=self.recipe()['stages']['matrix']['manifest']
        state={'iteration':0,'stagnant':0,'initial_level':1,'axe':5,'distance':.5,
               'max_iterations':2,'cost_remaining':1,'time_remaining':1}
        profile={'node_count':10,'control_count':1,'affected_regions':['main'],
                 'repair_context':'isolated','purpose':'product'}
        providers=Mock()
        action='P2:opaque-haiku'
        providers.decisions.return_value={'action':{'choice':action}}
        result=select(providers,'fixture','key',manifest,manifest['conditions'][-2],profile,state)
        descriptor=next(d for d in result['action_descriptors'] if d['id']==action)
        self.assertEqual(descriptor['model'],'anthropic/claude-haiku-5.5')
        self.assertEqual(descriptor['reasoning_effort'],'low')
        self.assertEqual(descriptor['level'],2)
        self.assertEqual(json.loads(providers.decisions.call_args.args[3])['actions'],result['action_descriptors'])
        question=next(q for q in providers.decisions.call_args.args[4] if q['name']=='action')
        self.assertEqual(json.loads(next(c['description'] for c in question['choices'] if c['value']==action)),descriptor)
        providers.chat.return_value=json.dumps({'action':action,'topic':'commerce','purpose':'product','repair_context':'isolated'})
        structured=select(providers,'fixture','key2',manifest,manifest['conditions'][-1],profile,state)
        self.assertEqual(structured['action_descriptors'],result['action_descriptors'])
        self.assertIn('anthropic/claude-haiku-5.5',providers.chat.call_args.args[4])
        providers.decisions.return_value={'action':{'choice':'P1:unapproved'}}
        with self.assertRaises(ContractError):
            select(providers,'fixture','key3',manifest,manifest['conditions'][-2],profile,state)

    def test_image_bound_excludes_transport_without_altering_request(self):
        model=model_snapshot(dict(reviewed_metadata()['openai/gpt-6-astra'],id='astra'))
        request={'messages':[{'role':'user','content':[
            {'type':'text','text':'Judge this evidence'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'x'*200000}},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'y'*200000}}]}],'max_tokens':4096}
        original=copy.deepcopy(request)
        bound,images=input_token_bound(request,model)
        text_only=copy.deepcopy(request)
        for part in text_only['messages'][0]['content'][1:]:part['image_url']['url']='[image input]'
        text_bound=len(json.dumps(text_only,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())+1024
        self.assertEqual(bound,text_bound+2*36001);self.assertEqual(images,2)
        self.assertEqual(request,original)
        self.assertEqual(input_token_bound(request,dict(model,vision_token_bounds={}))[0],model['context_length'])
        request['messages'][0]['content'][1]['image_url']['detail']='high'
        high=input_token_bound(request,model)[0]
        request['messages'][0]['content'][1]['image_url']['detail']='auto'
        self.assertEqual(input_token_bound(request,model)[0]-high,36001-3001)
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);ledger=Ledger(store)
            call,dispatch=ledger.begin('fixture','run','review','key',original,model,
                {'max_calls':2,'max_seconds':60,'max_cost_usd':5},5)
            rates=pricing_rates(model,bound)
            self.assertAlmostEqual(call['reserved'],(bound*rates[0]+4096*rates[1])/1000000)
            self.assertEqual(store.get(call['request_id'])['data']['request'],original)
            self.assertEqual(store.get(call['request_id'])['data']['reservation']['input_token_bound'],bound)

    def test_reviewed_vision_bounds_are_frozen_and_invalid_bounds_rejected(self):
        value=dict(reviewed_metadata()['openai/gpt-6-astra'],id='astra')
        frozen=model_snapshot(value);value['vision_token_bounds']={'auto':1}
        self.assertEqual(frozen['vision_token_bounds']['auto'],36001)
        for bounds in ({'auto':0},{'other':30},{'auto':True}):
            with self.assertRaises(ContractError):model_snapshot(dict(value,vision_token_bounds=bounds))

    def test_unknown_vision_uses_one_shared_context_and_preserves_call_cap(self):
        from harness.providers import BudgetStop
        model=model_snapshot(dict(reviewed_metadata()['openai/gpt-6-luna'],id='luna'))
        request={'messages':[{'role':'user','content':[
            {'type':'text','text':'Full original and replay'},
            {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+'x'*100000}},
            {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+'y'*100000}}]}],'max_tokens':1500}
        with tempfile.TemporaryDirectory() as root:
            ledger=Ledger(Store(root))
            call,sent=ledger.begin('fixture','run','review','one-window',request,model,
                {'max_calls':2,'max_seconds':60,'max_cost_usd':.25,'max_call_cost_usd':.25},.25)
            self.assertTrue(sent);self.assertLess(call['reserved'],.25)
            self.assertEqual(ledger.store.get(call['request_id'])['data']['reservation']['input_token_bound'],model['context_length'])
            with self.assertRaises(BudgetStop):
                ledger.begin('other','run','review','too-small',request,model,
                    {'max_calls':2,'max_seconds':60,'max_cost_usd':.1,'max_call_cost_usd':.1},.1)
