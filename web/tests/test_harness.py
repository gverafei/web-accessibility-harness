import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
os.environ['HARNESS_TESTING']='1'
from harness.store import Store,Conflict
from harness.contracts import ContractError,validate_manifest,model_snapshot,CRITERIA
from harness.sampling import sample
from harness.controller import distance,preserved,retain,materialize,profile,gate
from harness.providers import Ledger,Providers,UncertainCall,BudgetStop,parse_decision,parse_openrouter_decision
from harness.statistics import kappa,agreement_report,paired_interval
from harness.retrieval import Retriever,relevance_metrics
from harness.engine import Engine,create_campaign,launch
from harness.judges import parse_rating,consensus,annotate,adjudicate
from harness.export import bundle
from harness.reports import campaign_report
from harness import benchmark

HTML='<!doctype html><html lang="en"><head><title>Page</title></head><body><main><h1>Page</h1><img src="https://fixture.example/photo.jpg"><a href="https://fixture.example/help">Help</a></main></body></html>'

class Session:
    def __init__(self): self.requests=[];self.bad=False;self.transport=False;self.malformed=False
    def post(self,url,**kwargs):
        import requests
        self.requests.append(kwargs['json'])
        if self.transport: raise requests.Timeout('fixture timeout')
        body=kwargs['json'];prompt=body['messages'][0]['content'];prompt=prompt if isinstance(prompt,str) else prompt[0]['text']
        if 'Evaluate only the acquired' in prompt:
            evidence=json.loads(prompt.split('\nEVIDENCE\n')[1].split('\nANONYMIZED')[0])
            answer={'ratings':{c:{'status':'passed','rationale':'The acquired evidence supports this property.','evidence_refs':[next(iter(evidence))]} for c in CRITERIA}}
        else: answer={'operations':[{'action':'set_attribute','selector':'img','name':'alt','value':'Page photo'}]}
        payload={'model':'unexpected' if self.bad else body['model'],'usage':{'prompt_tokens':10,'completion_tokens':10,'cost':0},
                 'choices':[{'finish_reason':'stop','message':{'content':'invalid JSON' if self.malformed else json.dumps(answer)}}]}
        class Response:
            status_code=200
            text=json.dumps(payload)
        return Response()

class Environment:
    def __init__(self,store):self.store=store;self.captures=0;self.fail=set()
    def capture(self,url,campaign,ident):
        self.captures+=1
        if url in self.fail: raise ContractError('fixture acquisition failure')
        original=self.store.blob(HTML,'rendered_html',campaign,'text/html')
        screenshot=self.store.blob(b'fixture-image','capture_screenshot',campaign,'image/jpeg')
        return self.store.append('capture',{'rendered_id':original['id'],'network_id':original['id'],'screenshot_id':screenshot['id'],
          'captured_url':url,'requested_url':url,'assets':[],'errors':[],'scope':'synthetic offline fixture'},campaign,ident)
    def audit(self,capture,source,campaign,ident,config):
        good='alt="Page photo"' in source
        return self.store.append('audit',{'status':'completed','axe':0 if good else 5,'lighthouse':100 if good else 80,
          'syntax':{'state':'passed'},'failures':[] if good else [{'id':'image-alt','nodes':[{'target':['img']}],'tags':['wcag111']}],
          'artifacts':{},'replay':{'scope':'synthetic frozen fixture','uncaptured':[]}},campaign,ident)

class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
        self.corpus=self.store.append('corpus',{'collection':'fixture','endpoint':'http://unused','metadata':{'provenance':'synthetic fixture'},
          'examples':[{'id':'a','rule_id':'image-alt','rule_name':'Image has non-empty accessible name','expected':'passed','code':'<img alt="Photo">','title':'Photo'},
                      {'id':'b','rule_id':'image-alt','rule_name':'Image has non-empty accessible name','expected':'failed','code':'<img>','title':'Photo'}]})
        def model(key,family): return {'id':key,'model':family+'/'+key,'family':family,'context_length':262144,
                  'input_usd_per_million':0,'output_usd_per_million':0,'pricing_source':'synthetic fixture','vision':False}
        self.legacy_judges=[model_snapshot(model('judge1','family1')),model_snapshot(model('judge2','family2'))]
        self.manifest={'name':'Fixture campaign','study_id':'fixture-study','seed':'42','mode':'frozen','partition':'test',
          'source':{'kind':'urls','urls':['https://fixture.example/']},'workers':[dict(model('worker','openai'),model='openai/gpt-6-luna',reasoning_effort='low')],
          'repetitions':1,'max_iterations':2,
          'repair_budget':{'max_cost_usd':1,'max_seconds':60,'max_calls':8,'max_output_tokens':128},
          'review_budget':{'max_cost_usd':1,'max_seconds':60,'max_calls':8,'max_output_tokens':128},'campaign_cost_limit':5,
          'conditions':[{'id':'P1','level':1,'worker_id':'worker','selector':'rules'}],'corpus_id':self.corpus['id']}
        self.session=Session();self.environment=Environment(self.store)
        self.providers=lambda s,m,c,settings: Providers(s,m,c,settings,self.session)
        self.retrievers=lambda s,c: Retriever(s,c,vector_search=lambda q,k:[{'id':'a','score':1},{'id':'b','score':.8}])
    def campaign(self,mode='frozen'):
        if mode!='frozen': self.manifest.update(mode=mode,partition='development')
        return create_campaign(self.store,self.manifest)
    def execute(self,campaign):
        launch(self.store,campaign['id']); Engine(self.store,{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'},
          self.environment,self.providers,self.retrievers).execute(campaign['id'])
    def test_sampling_reproducible_unique_whole_frame(self):
        ranking=[(n,'d'+str(n)+'.example') for n in range(1,101)]
        a=sample(ranking,'ABCDE','42',12,4)
        self.assertEqual(a,sample(list(reversed(ranking)),'ABCDE','42',12,4));self.assertEqual(len({r['domain'] for r in a}),16)
        self.assertEqual([r['role'] for r in a[-4:]],['reserve']*4)
        self.assertNotEqual(a,sample(ranking,'ABCDE','43',12,4))

    def test_empty_generation_is_accounted_without_a_second_measurement(self):
        from unittest.mock import patch
        original_post = self.session.post
        requests = []
        def respond(url, **kwargs):
            response = original_post(url, **kwargs)
            requests.append(kwargs['json'])
            if len(requests) == 1:
                payload = json.loads(response.text)
                payload['choices'][0]['message']['content'] = '{"operations":[]}'
                response.text = json.dumps(payload)
            return response
        self.session.post = respond
        campaign = self.campaign()
        with patch.object(self.environment, 'audit', wraps=self.environment.audit) as auditor:
            self.execute(campaign)
        self.assertEqual(auditor.call_count, 2)  # acquired source and one changed page
        self.assertEqual(len(self.store.list('attempt', campaign=campaign['id'])), 1)
        noop = self.store.list('proposal_noop', campaign=campaign['id'])
        self.assertEqual(len(noop), 1)
        self.assertFalse(noop[0]['data']['evaluated'])
        self.assertEqual(len(requests), 2)
        self.assertIn('no new audit', requests[1]['messages'][0]['content'])
        self.assertEqual(len(Ledger(self.store).rows(campaign['id'])), 2)
    def test_partition_overlap_rejected(self):
        self.store.assign_domain('study','example.org','development')
        with self.assertRaises(Conflict): self.store.assign_domain('study','example.org','test')
    def test_immutable_record_checkpoint_cas_and_claim(self):
        r=self.store.append('fixture',{'x':1});self.assertEqual(self.store.get(r['id'])['data']['x'],1)
        self.store.checkpoint('run',{'stage':1},0)
        with self.assertRaises(Conflict):self.store.checkpoint('run',{'stage':2},0)
        self.assertTrue(self.store.claim('run','one'));self.assertFalse(self.store.claim('run','two'))
    def test_new_core_manifest_excludes_independent_review(self):
        self.manifest['judges']=self.legacy_judges
        with self.assertRaisesRegex(ContractError,'independent review is deferred'):validate_manifest(self.manifest)
        self.manifest.pop('judges')
        self.assertEqual(validate_manifest(self.manifest)['evaluation_basis'],'observable-technical-v1')
    def test_time_policy_survives_actual_campaign_registration(self):
        from harness.time_policy import ITERATION_BOUNDARY
        self.assertNotIn('time_policy',validate_manifest(self.manifest))
        self.manifest['time_policy']=ITERATION_BOUNDARY
        campaign=self.campaign()
        self.assertEqual(self.store.get(campaign['id'])['data']['time_policy'],ITERATION_BOUNDARY)
        self.assertNotIn('time_policy',campaign['data']['workers'][0])
        self.manifest['time_policy']='unbounded'
        with self.assertRaisesRegex(ContractError,'Invalid time policy'):
            self.campaign()

    def binding_fixture(self):
        from harness.source_binding import VERSION
        return {'version':VERSION,'sql_source_id':1,'capture_id':'capture','audit_id':'audit','replay_id':'replay','source_artifact_id':'source',
                **{key:'a'*64 for key in ('input_sha256','native_package_sha256','reference_document_sha256','evaluator_runtime_sha256')},
                'preflight_basis':'fixture'}

    def test_frozen_binding_survives_campaign_registration_and_scope(self):
        binding=self.binding_fixture();self.manifest.update(frozen_source_binding=binding,source_binding_scope='fixture-cut')
        campaign=self.campaign();data=self.store.get(campaign['id'])['data']
        self.assertEqual(data['frozen_source_binding'],binding)
        self.assertEqual(data['source_binding_scope'],'fixture-cut')
        binding['input_sha256']='b'*64
        self.assertEqual(self.store.get(campaign['id'])['data']['frozen_source_binding']['input_sha256'],'a'*64)

    def test_malformed_binding_rejected_before_campaign_registration(self):
        for key,value in (('version','other'),('input_sha256','bad'),('capture_id',None),('sql_source_id',True),('api_key','secret')):
            with self.subTest(key=key):
                binding=self.binding_fixture();binding[key]=value;self.manifest['frozen_source_binding']=binding
                with self.assertRaises(ContractError):self.campaign()

    def test_binding_scope_requires_binding(self):
        self.manifest['source_binding_scope']='fixture-cut'
        with self.assertRaisesRegex(ContractError,'requires its frozen binding'):self.campaign()

    def test_secrets_not_in_manifest(self):
        self.manifest['api_key']='sensitive';self.manifest['workers'][0]['api_key']='sensitive'
        self.manifest['source']['api_key']='sensitive';self.manifest['evaluator']={'api_key':'sensitive'}
        self.assertNotIn('sensitive',json.dumps(validate_manifest(self.manifest)))
        import copy
        for key,value in [('source',[]),('workers',{}),('conditions',[[]]),('targets','bad'),('analysis',[]),('oracle_benchmark_ids','bad')]:
            manifest=copy.deepcopy(self.manifest);manifest[key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):validate_manifest(manifest)
    def test_controller_original_kept_and_protected_actions(self):
        before={'distance':2,'admissible':True};after={'distance':3,'admissible':True}
        self.assertEqual(retain(before,after),(before,False))
        self.assertEqual(preserved(HTML,HTML.replace('Help','Removed'),'https://fixture.example')['status'],'violated')
        c,meta=materialize(HTML,json.dumps({'operations':[{'action':'set_attribute','selector':'a','name':'href','value':'https://evil.example'}]}),1,'https://fixture.example')
        self.assertIn('https://fixture.example/help',c)
        self.assertTrue(meta['rejected'])
    def test_initial_profile_and_normalized_distance(self):
        context=profile(HTML,{'failures':[{'id':'image-alt','nodes':[{'target':['img']}]}]},'https://fixture.example')
        self.assertEqual(context['repair_context'],'isolated');self.assertEqual(context['purpose'],'homepage')
        self.assertAlmostEqual(distance(5,80,{'max_axe':3,'min_lighthouse':94}),2/3+.14)
        self.assertFalse(gate({'status':'completed','syntax':{'state':'violated'}},{'status':'passed'}))

    def test_lighthouse_only_defect_retrieves_attributed_examples(self):
        campaign=self.campaign()
        engine=Engine(self.store,{},self.environment,self.providers,self.retrievers)
        provider=self.providers(self.store,campaign['data'],campaign['id'],{})
        audit={'failures':[], 'lighthouse_failures':[{'audit':'image-alt','title':'Image alternative'}]}
        examples,trace=engine.retrieve(provider,campaign['data'],campaign['data']['conditions'][0],
            'lighthouse-only',1,{'purpose':'homepage','repair_context':'isolated'},audit)
        self.assertEqual([item['id'] for item in examples],['a','b'])
        self.assertEqual(trace['data']['requested_rules'],['image-alt'])
        self.assertEqual(json.loads(trace['data']['query'])['failures'],[])
        self.assertEqual(self.session.requests,[])

    def test_unknown_lighthouse_audit_does_not_inject_vector_neighbors(self):
        campaign=self.campaign()
        engine=Engine(self.store,{},self.environment,self.providers,self.retrievers)
        provider=self.providers(self.store,campaign['data'],campaign['id'],{})
        examples,trace=engine.retrieve(provider,campaign['data'],campaign['data']['conditions'][0],
            'unknown-lighthouse',1,{'purpose':'homepage','repair_context':'isolated'},
            {'failures':[], 'lighthouse_failures':[{'audit':'unknown-audit','title':'Image alternative'}]})
        self.assertEqual(examples,[])
        self.assertEqual(trace['data']['injected'],[])
        self.assertEqual(self.session.requests,[])
    def test_receipt_precedes_parse_and_replay_reuses_response(self):
        c=self.campaign();p=self.providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'})
        self.session.bad=True
        with self.assertRaises(ContractError):p.chat('run','repair','key',c['data']['workers'][0],'source')
        rows=p.ledger.rows(c['id']);self.assertEqual(rows[0]['cost_status'],'provider_reported')
        self.assertEqual(len(self.store.list('call_receipt',c['id'])),1)
        with self.assertRaises(ContractError):p.chat('run','repair','key',c['data']['workers'][0],'source')
        self.assertEqual(len(self.session.requests),1)
    def test_unknown_consumption_blocks_new_calls_until_reconciliation(self):
        c=self.campaign();p=self.providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'})
        self.session.transport=True
        with self.assertRaises(UncertainCall):p.chat('run','repair','key',c['data']['workers'][0],'source')
        with self.assertRaises(UncertainCall):p.chat('run','repair','other',c['data']['workers'][0],'source')
        row=p.ledger.rows()[0];p.ledger.reconcile(row['id'],0,'fixture provider lookup')
        self.session.transport=False;p.chat('run','repair','other',c['data']['workers'][0],'source')
        self.assertEqual(len(self.session.requests),2)
    def test_budgets_before_dispatch(self):
        c=self.campaign();c['data']['repair_budget']['max_calls']=1
        p=self.providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'})
        p.chat('run','repair','key',c['data']['workers'][0],'source')
        with self.assertRaises(BudgetStop):p.chat('run','repair','another',c['data']['workers'][0],'source')
        self.assertEqual(len(self.session.requests),1)
    def test_per_call_cap_blocks_large_request_without_ledger_or_http(self):
        self.manifest['repair_budget']['max_call_cost_usd'] = .02
        self.manifest['workers'][0]['input_usd_per_million'] = 1
        c = self.campaign()
        self.assertEqual(c['data']['repair_budget']['max_call_cost_usd'], .02)
        p = self.providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'})
        with self.assertRaisesRegex(BudgetStop,'per-call'):
            p.chat('run','repair','oversized',c['data']['workers'][0],'x'*30000)
        self.assertEqual(self.session.requests,[])
        self.assertEqual(p.ledger.rows(),[])
        p.chat('run','repair','small',c['data']['workers'][0],'small request')
        self.assertEqual(len(self.session.requests),1)
        # Lowering today's cap never duplicates a paid historical response.
        c['data']['repair_budget']['max_call_cost_usd'] = 0
        p.chat('run','repair','small',c['data']['workers'][0],'small request')
        self.assertEqual(len(self.session.requests),1)
    def test_decisions_exact_closed_contract(self):
        questions=[{'type':'choice','name':'action','choices':[{'value':'stop'},{'value':'P1'}]}]
        payload={'model':'gpt-6-luna','answers':[{'type':'choice','name':'action','choice':'P1','confidence':.7,
                      'probabilities':[{'value':'stop','probability':.3},{'value':'P1','probability':.7}]}]}
        self.assertEqual(parse_decision(payload,questions)['action']['choice'],'P1')
        payload['answers'][0]['choice']='outside'
        with self.assertRaises(ContractError):parse_decision(payload,questions)
    def test_openrouter_decisions_shared_key_endpoint_named_schema_and_replay(self):
        from harness.decision_models import DEFINITIONS,snapshot
        from unittest.mock import Mock
        questions=[{'type':'predicate','name':'relevant','instructions':'Is the acquired example relevant?'},
          {'type':'choice','name':'action','instructions':'Choose an admissible action.','choices':[{'value':'stop'},{'value':'P1'}]}]
        for model in DEFINITIONS:
            with self.subTest(model=model['model']):
                c=self.campaign();c['data']['decision_model']=snapshot(model)
                payload={'model':model.get('response_model',model['model']),'answers':{'relevant':{'type':'noul','noul':.8},
                  'action':{'type':'choice','choice':'P1','probabilities':{'stop':.3,'P1':.7},'confidence':.7}},
                  'usage':{'input_tokens':42,'output_tokens':0}}
                session=Mock();session.post.return_value=type('Response',(),{'status_code':200,'text':json.dumps(payload)})()
                p=Providers(self.store,c['data'],c['id'],{'openrouter_api_key':'router-fixture-key','openrouter_base_url':'https://openrouter.ai/api/v1'},session)
                key='decision-'+model['model'];answer=p.decisions('run','repair',key,'Acquired fixture evidence',questions)
                self.assertEqual(answer['relevant']['probability'],.8);self.assertEqual(answer['action']['choice'],'P1')
                args=session.post.call_args;self.assertEqual(args.args[0],'https://openrouter.ai/api/alpha/decisions')
                self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer router-fixture-key')
                body=args.kwargs['json'];self.assertEqual(body['model'],model['model']);self.assertEqual(body['state'],'Acquired fixture evidence')
                self.assertEqual(body['questions']['relevant'],{'type':'noul','instructions':questions[0]['instructions']})
                self.assertEqual(body['questions']['action']['criteria'],{'stop':'stop','P1':'P1'})
                self.assertFalse(body['provider']['allow_fallbacks']);self.assertNotIn('messages',body)
                call=p.ledger.rows(c['id'])[0];self.assertEqual(call['cost_status'],'estimated')
                self.assertAlmostEqual(call['cost'],42*model['input_usd_per_million']/1000000)
                p.decisions('run','repair',key,'Acquired fixture evidence',questions);self.assertEqual(session.post.call_count,1)
                with self.assertRaises(ContractError):p.decisions('run','repair','bad','Source',[{'type':'predicate','name':'bad','instruction':'Wrong key'}])
                self.assertEqual(session.post.call_count,1)

    def test_openrouter_optional_confidence_and_probability_validation(self):
        model='openai/gpt-6-luna-decisions';q=[{'name':'action','type':'choice','choices':[{'value':False},{'value':True}]}]
        payload={'model':model,'answers':{'action':{'type':'choice','choice':'true'}}}
        answer=parse_openrouter_decision(payload,q,model)['action'];self.assertIs(answer['choice'],True)
        self.assertNotIn('confidence',answer);self.assertNotIn('probabilities',answer)
        for values in ({'false':.8,'true':.8},{'false':.2,'outside':.8},{'false':True,'true':.0}):
            payload['answers']['action']['probabilities']=values
            with self.subTest(values=values),self.assertRaises(ContractError):parse_openrouter_decision(payload,q,model)
        question=[{'name':'severity','type':'score','levels':[{'label':'none'},{'label':'some'},{'label':'major'}]}]
        value={'model':model,'answers':{'severity':{'type':'score','score':2.1,'probabilities':{'1':.1,'2':.7,'3':.2}}}}
        self.assertAlmostEqual(parse_openrouter_decision(value,question,model)['severity']['score'],1.1)
        value['answers']['severity']['score']=3
        with self.assertRaises(ContractError):parse_openrouter_decision(value,question,model)

    def test_decision_response_charge_retained_before_invalid_or_swapped_identity(self):
        from harness.decision_models import DEFINITIONS,snapshot
        from unittest.mock import Mock
        questions=[{'type':'predicate','name':'valid','instructions':'Is this evidence adequate?'}]
        for returned,answer in [(DEFINITIONS[1]['model'],.5),(DEFINITIONS[0]['response_model'],1.5),
                               ('openai/gpt-6-luna-decisions-20261007',.5)]:
            c=self.campaign();c['data']['decision_model']=snapshot(DEFINITIONS[0]);session=Mock()
            payload={'model':returned,'answers':{'valid':{'type':'noul','noul':answer}},'usage':{'input_tokens':7,'output_tokens':0,'cost':.01}}
            session.post.return_value=type('Response',(),{'status_code':200,'text':json.dumps(payload)})()
            p=Providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture','openrouter_base_url':'http://fixture/api/v1'},session)
            with self.assertRaises(ContractError):p.decisions('run','repair','invalid-'+c['id'],'Evidence',questions)
            self.assertEqual(p.ledger.rows(c['id'])[0]['cost'],.01);self.assertEqual(len(self.store.list('call_receipt',c['id'])),1)
            self.assertEqual(session.post.call_count,1)

    def test_decision_manifest_catalogue_separation_and_small_context_limit(self):
        import copy
        from harness.decision_models import DEFINITIONS,snapshot,validate_catalogue
        from remediation_model_choices import default_catalog,validate_catalog
        values=[dict(v) for v in DEFINITIONS];values[0].update(context_length=1234,input_usd_per_million=0,response_model='openai/other')
        catalogue=validate_catalogue(values);self.assertEqual(catalogue[0]['context_length'],1050000)
        self.assertEqual(catalogue[0]['response_model'],DEFINITIONS[0]['response_model'])
        self.assertEqual(snapshot(catalogue[0])['response_model'],DEFINITIONS[0]['response_model'])
        historical=dict(catalogue[0],context_length=32768,input_usd_per_million=.2,response_model='openai/gpt-6-luna-decisions-20261006')
        self.assertEqual(snapshot(historical)['context_length'],32768)
        self.assertEqual(snapshot(historical)['input_usd_per_million'],.2)
        values[0]['enabled']=False
        with self.assertRaises(ContractError):validate_catalogue(values)
        with self.assertRaises(ContractError):model_snapshot(DEFINITIONS[0])
        cloud=default_catalog();cloud[0]['model']=DEFINITIONS[0]['model']
        with self.assertRaises(ValueError):validate_catalog(cloud)
        manifest=copy.deepcopy(self.manifest);manifest['conditions'][0]['selector']='decisions'
        with self.assertRaises(ContractError):validate_manifest(manifest)
        manifest['decision_model']=DEFINITIONS[0];self.assertEqual(validate_manifest(manifest)['decision_model']['model'],DEFINITIONS[0]['model'])
        from unittest.mock import Mock
        c=self.campaign();c['data']['decision_model']=snapshot(DEFINITIONS[1]);session=Mock()
        p=Providers(self.store,c['data'],c['id'],{'openrouter_api_key':'fixture','openrouter_base_url':'http://fixture'},session)
        with self.assertRaises(BudgetStop):p.decisions('run','repair','oversize','x'*DEFINITIONS[1]['context_length'],[{'name':'valid','type':'predicate','instructions':'Validate evidence.'}])
        session.post.assert_not_called();self.assertEqual(p.ledger.rows(c['id']),[])

    def test_model_metadata_survives_configuration_without_price_loss(self):
        from remediation_model_choices import default_catalog,validate_catalog
        values=default_catalog();values[0].update(label='Chosen display name',tier='max',input_usd_per_million=0)
        saved=validate_catalog(values);self.assertEqual(saved[0]['context_length'],1050000)
        self.assertAlmostEqual(saved[0]['input_usd_per_million'],.1)
        self.assertEqual(saved[0]['output_usd_per_million'],.5);self.assertFalse(saved[0]['temperature_supported'])
        self.assertEqual(saved[0]['label'],'Chosen display name')
    def test_decisions_score_refusal_and_invalid_numeric_contracts(self):
        question={'type':'score','name':'severity','levels':[{'label':'none'},{'label':'some'},{'label':'major'}]}
        score={'type':'score','name':'severity','score':1.1,'confidence':.55,'probabilities':[
          {'value':0,'label':'none','probability':.1},{'value':1,'label':'some','probability':.7},{'value':2,'label':'major','probability':.2}]}
        payload={'model':'gpt-6-luna','answers':[score]};self.assertEqual(parse_decision(payload,[question])['severity']['score'],1.1)
        score['score']=1.8
        with self.assertRaises(ContractError):parse_decision(payload,[question])
        score['score']='1.1'
        with self.assertRaises(ContractError):parse_decision(payload,[question])
        self.assertEqual(parse_decision({'model':'gpt-6-luna','answers':[{'type':'refusal','name':'severity'}]},[question])['severity']['type'],'refusal')
    def test_judge_unknown_evidence_and_missing_distinct(self):
        ratings={'ratings':{c:{'status':'passed','rationale':'Fixture evidence','evidence_refs':['unknown']} for c in CRITERIA}}
        with self.assertRaises(ContractError):parse_rating(ratings,['known'])
        self.assertTrue(consensus([{},{}])['content']['missing'])
        a={c:{'status':'passed'} for c in CRITERIA};b={c:{'status':'unverified'} for c in CRITERIA}
        self.assertTrue(consensus([a,b])['content']['disagreement'])
    def test_kappa_known_degenerate_missing_and_clustered(self):
        pairs=[('passed','passed'),('passed','violated'),('violated','passed'),('violated','violated')]
        self.assertEqual(kappa(pairs)['kappa'],0)
        self.assertIsNone(kappa([('passed','passed')])['kappa'])
        self.assertEqual(kappa([('unverified','unverified'),(None,'passed')])['coverage'],.5)
        report=agreement_report([{'page_id':str(i),'left':a,'right':b} for i,(a,b) in enumerate(pairs)])
        self.assertEqual(report['pages'],4)
    def test_critical_calibration_uses_adjudicated_severity_and_explicit_coverage(self):
        from harness.statistics import calibration
        rows=[{'prediction':'passed','reference':'violated','reference_critical':True},
              {'prediction':'violated','reference':'violated','reference_critical':False},
              {'prediction':'passed','reference':'violated'}, {'prediction':None,'reference':'violated','reference_critical':True}]
        result=calibration(rows);self.assertEqual(result['n'],3);self.assertEqual(result['false_acceptances'],2)
        self.assertEqual(result['critical_false_acceptances'],1);self.assertEqual(result['critical_error_rate'],1)
        self.assertAlmostEqual(result['severity_coverage'],2/3)
        self.assertIsNone(calibration([{'prediction':'passed','reference':'violated'}])['critical_error_rate'])
    def test_relevance_known_and_partial_reference(self):
        metrics=relevance_metrics(['a','c'],['a'],{'a':True,'b':True,'c':False},['a','b','c'],2)
        self.assertEqual(metrics['retrieved']['precision'],.5);self.assertEqual(metrics['retrieved']['recall_at_k'],.5)
        partial=relevance_metrics(['a'],['a'],{'a':True},['a','b'],2)
        self.assertIsNone(partial['retrieved']['recall_at_k'])
    def test_retrieval_complete_pairs_and_no_filler(self):
        r=self.retrievers(self.store,self.corpus['id'])
        examples,trace=r.retrieve('photo image-alt',[{'id':'image-alt'}],2)
        self.assertEqual({e['expected'] for e in examples},{'passed','failed'});self.assertEqual(len(trace['injected']),2)
        self.assertEqual(r.retrieve('unknown',[{'id':'unmapped-rule'}],2)[0],[])
    def test_technical_campaign_resume_export_without_judge_or_author_calls(self):
        c=self.campaign();self.execute(c)
        state,_=self.store.checkpoint(c['id']);self.assertEqual(state['status'],'completed',state)
        result=self.store.list('run_result',c['id'])[0];self.assertTrue(result['data']['preserved_success'])
        self.assertEqual(len(self.session.requests),1)
        engine=Engine(self.store,{},self.environment,self.providers,self.retrievers)
        engine.run(c,self.store.list('page',c['id'])[0],c['data']['conditions'][0],0)
        self.assertEqual(len(self.session.requests),1);self.assertEqual(self.environment.captures,1)
        self.assertEqual(self.store.list('review_case',c['id']),[])
        self.assertEqual(self.store.list('judge_rating',c['id']),[])
        self.assertEqual(self.store.list('author_sample',c['id']),[])
        self.assertEqual(result['data']['evaluation_basis'],'observable-technical-v1')
        self.assertEqual(result['data']['semantic_preservation'],'not_assessed')
        self.assertEqual(campaign_report(self.store,c['id'])['conditions'][0]['preserved_success'],1)
        original_list=self.store.list
        def bounded_list(kind=None,campaign=None):
            if kind is None and campaign is None:raise AssertionError('Export loaded unrelated catalogue')
            return original_list(kind,campaign)
        with __import__('unittest.mock',fromlist=['patch']).patch.object(self.store,'list',side_effect=bounded_list):
            data=bundle(self.store,c['id'],True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('reanalyze.py',archive.namelist());self.assertNotIn(b'fixture-secret',b''.join(archive.read(n) for n in archive.namelist()))
    def test_taxonomy_original_is_measured_before_generation_without_feedback_leak(self):
        from harness.decision_models import DEFINITIONS
        self.manifest['decision_model']=dict(DEFINITIONS[0])
        c=self.campaign()
        phases=[]
        def measurement(store,providers,run,baseline,retained,*args):
            phases.append((len(self.session.requests),baseline['id']==retained['id']))
            return {'status':'completed','errors':[],'calibration_marker':'never_send_to_generator'}
        with patch('accessibility_taxonomy.assessment.measure_pair',side_effect=measurement):self.execute(c)
        self.assertEqual(phases,[(0,True),(1,False)])
        self.assertNotIn('never_send_to_generator',json.dumps(self.session.requests))
        self.assertEqual(len(self.store.list('taxonomy_baseline',c['id'])),1)

    def test_failed_taxonomy_baseline_prevents_generation(self):
        from harness.decision_models import DEFINITIONS
        self.manifest['decision_model']=dict(DEFINITIONS[0])
        c=self.campaign()
        with patch('accessibility_taxonomy.assessment.measure_pair',return_value={'status':'not_assessed','errors':['measurement unavailable']}):self.execute(c)
        self.assertEqual(self.session.requests,[])
        self.assertEqual(self.store.list('run_result',c['id']),[])
    def test_expired_worker_claim_resumes_without_busy_loop(self):
        c=self.campaign();launch(self.store,c['id']);self.store.claim(c['id'],'crashed-worker')
        engine=Engine(self.store,{'openrouter_api_key':'fixture-secret','openrouter_base_url':'http://fake'},self.environment,self.providers,self.retrievers)
        self.assertFalse(engine.tick());self.assertEqual(len(self.session.requests),0)
        with self.store.connect() as db:db.execute('UPDATE claims SET expires=0 WHERE id=?',(c['id'],))
        self.assertTrue(engine.tick());self.assertEqual(self.store.checkpoint(c['id'])[0]['status'],'completed')
        self.assertEqual(len(self.session.requests),1);self.assertFalse(engine.tick())
    def test_failure_and_reserve_provenance_preserved(self):
        c=self.campaign();first={'url':'https://bad.example/','domain':'bad.example','order':0,'role':'selected'}
        reserve={'url':'https://reserve.example/','domain':'reserve.example','order':1,'role':'reserve'}
        self.environment.fail.add(first['url']);engine=Engine(self.store,{},self.environment,self.providers,self.retrievers)
        self.assertIsNone(engine.acquire(c,first));page=engine.acquire(c,reserve,replaces=first['url'])
        self.assertEqual(page['data']['replaces'],first['url']);self.assertEqual(len(self.store.list('acquisition_failure',c['id'])),1)
    def test_all_worker_interventions_have_valid_source_contracts(self):
        from harness.controller import worker_prompt
        context=profile(HTML,{'failures':[]},'https://fixture.example/')
        for level in range(1,6):
            self.assertIn('Preserve acquired facts',worker_prompt(HTML,HTML,{'failures':[]},level,'https://fixture.example/',context,''))
        c,_=materialize(HTML,HTML,4,'https://fixture.example/');self.assertNotIn('bootstrap@5.3.8',c)
        with self.assertRaises(ContractError):materialize(HTML,'<html>incomplete',4,'https://fixture.example/')
    def test_initial_rag_is_recorded_when_original_already_meets_targets(self):
        self.manifest['targets']={'max_axe':10,'min_lighthouse':80}
        c=self.campaign();self.execute(c)
        result=self.store.list('run_result',c['id'])[0]['data'];self.assertTrue(result['selected']['original'])
        self.assertEqual(result['attempts'],[]);self.assertEqual(len(self.store.list('retrieval',c['id'])),1)
        self.assertEqual(len(self.session.requests),0)
        self.assertEqual(self.store.list('decision',c['id'])[0]['data']['selector'],'deterministic-target-stop')
    def test_benchmark_two_independent_annotations_and_oracle(self):
        context=profile(HTML,{'failures':[{'id':'image-alt'}]},'https://fixture.example')
        case=benchmark.create(self.store,self.corpus['id'],context,['a'],2,'42')
        ratings={key:{'relevant':key=='a','rationale':'Known synthetic context.'} for key in case['data']['universe']}
        benchmark.annotate(self.store,case['id'],'author_a',ratings)
        with self.assertRaises(ContractError):benchmark.adjudicate(self.store,case['id'],ratings)
        benchmark.annotate(self.store,case['id'],'author_b',ratings);ref=benchmark.adjudicate(self.store,case['id'],ratings)
        self.assertEqual(benchmark.oracle_ids(self.store,ref['id'],context),['a'])
    def test_frozen_rag_contrast_requires_matched_controls(self):
        self.manifest['rag_contrast']=True;self.manifest['conditions'][0]['rag']='off'
        with self.assertRaises(ContractError):create_campaign(self.store,self.manifest)
    def test_three_rag_conditions_share_one_snapshot_and_validated_oracle(self):
        context=profile(HTML,{'failures':[{'id':'image-alt'}]},'https://fixture.example/')
        case=benchmark.create(self.store,self.corpus['id'],context,['a','b'],2,'42')
        ratings={key:{'relevant':True,'rationale':'Known applicable positive/negative fixture pair.'} for key in ('a','b')}
        for author in ('author_a','author_b'):benchmark.annotate(self.store,case['id'],author,ratings)
        reference=benchmark.adjudicate(self.store,case['id'],ratings)
        self.manifest.update(rag_contrast=True,oracle_benchmark_ids=[reference['id']])
        self.manifest['conditions']=[{'id':rag,'level':1,'worker_id':'worker','rag':rag} for rag in ('off','retrieved','oracle')]
        c=self.campaign();self.execute(c)
        state=self.store.checkpoint(c['id'])[0];self.assertEqual(state['status'],'completed',state)
        self.assertEqual(self.environment.captures,1);self.assertEqual(len(self.store.list('run_result',c['id'])),3)
        traces={r['data']['condition']:r['data'] for r in self.store.list('retrieval',c['id'])}
        self.assertEqual(traces['off']['injected'],[]);self.assertEqual(set(traces['oracle']['injected']),{'a','b'})
        self.assertEqual(len({r['data']['page_id'] for r in self.store.list('run_result',c['id'])}),1)
    def test_worse_regeneration_branch_can_improve_without_displacing_original(self):
        class RegenerationSession(Session):
            def post(self,url,**kwargs):
                body=kwargs['json'];prompt=body['messages'][0]['content']
                if body['model']=='openai/gpt-6-luna' and 'complete standalone HTML' in prompt:
                    self.requests.append(body)
                    payload={'model':body['model'],'usage':{'prompt_tokens':10,'completion_tokens':10,'cost':0},
                             'choices':[{'finish_reason':'stop','message':{'content':HTML}}]}
                    class Response:
                        status_code=200;text=json.dumps(payload)
                    return Response()
                return super().post(url,**kwargs)
        original_audit=self.environment.audit
        def measured(capture,source,cid,ident,config):
            if 'bootstrap@' in source and 'alt="Page photo"' not in source:
                return self.store.append('audit',{'status':'completed','axe':10,'lighthouse':70,'syntax':{'state':'passed'},
                  'failures':[{'id':'image-alt','nodes':[{'target':['img']}]}],'artifacts':{},'replay':{'uncaptured':[]}},cid,ident)
            return original_audit(capture,source,cid,ident,config)
        self.session=RegenerationSession();self.environment.audit=measured
        self.manifest['conditions']=[{'id':'regen','level':4,'worker_id':'worker'}]
        c=self.campaign();self.execute(c)
        result=self.store.list('run_result',c['id'])[0]['data'];self.assertEqual(len(result['attempts']),2)
        first=self.store.get(result['attempts'][0]+'-retention')['data']
        self.assertTrue(first['selected']['original']);self.assertFalse(first['changed'])
        self.assertTrue(result['preserved_success']);self.assertEqual(self.store.get(result['attempts'][1])['data']['level'],4);self.assertEqual(self.store.get(result['attempts'][1])['data']['operation_level'],2)
    def test_undefined_pre_and_proven_harm(self):
        from harness.analysis import pre
        run={'axe':10,'lighthouse':85,'preservation':'passed','seconds':60};baseline={'axe':40,'lighthouse':70}
        settings={'axe_weight':.5,'cost_reference':1,'time_reference':180}
        self.assertAlmostEqual(pre(run,baseline,.2,True,settings),.45/(1+.2+60/180))
        self.assertIsNone(pre(run,baseline,.2,False,settings));run['preservation']='violated';self.assertEqual(pre(run,baseline,.2,True,settings),0)
    def test_offline_export_reanalysis_executes_and_checks_hashes(self):
        import subprocess
        c=self.campaign();self.execute(c)
        path=Path(self.tmp.name)/'export';path.mkdir()
        with zipfile.ZipFile(io.BytesIO(bundle(self.store,c['id'],True))) as archive: archive.extractall(path)
        completed=subprocess.run([sys.executable,str(path/'reanalyze.py')],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertTrue((path/'runs.csv').is_file())
        (path/'fixture.json').write_text('{}')
        failed=subprocess.run([sys.executable,str(path/'reanalyze.py')],capture_output=True,text=True)
        self.assertNotEqual(failed.returncode,0);self.assertIn('Hash mismatch',failed.stderr)
    def historical_campaign(self):
        # Identified legacy evidence fixture, never a new executable manifest.
        import copy
        current=self.campaign();self.execute(current)
        data=copy.deepcopy(current['data']);data.pop('evaluation_basis',None);data['judges']=self.legacy_judges
        historic=self.store.append('campaign',data)
        original=self.store.list('run_result',current['id'])[0]['data']
        assessment=self.store.get(original['selected']['case_id'])
        case=self.store.append('review_case',{'run_id':'legacy-'+original['run_id'],'page_id':original['page_id'],
            'attempt_id':None,'evidence':assessment['data']['evidence'],
            'review':{'status':'passed','initial':[{},{}],'revised':[{},{}],'consensus':{},'needs_human':False},'queue':None},historic['id'])
        result={k:v for k,v in original.items() if k not in ('evaluation_basis','semantic_preservation')}
        result.update(run_id='legacy-'+original['run_id'],attempts=[])
        result['selected']=result['selected'] | {'case_id':case['id'],'semantic':'passed'}
        self.store.append('run_result',result,historic['id'])
        return historic,case

    def test_capture_only_then_reused_snapshot_never_recaptures_page(self):
        self.manifest['capture_only']=True;self.manifest['author_sample_count']=0
        c=self.campaign();self.execute(c)
        self.assertEqual(self.store.checkpoint(c['id'])[0]['stage'],'diagnosis');self.assertEqual(len(self.session.requests),0)
        page=self.store.list('page',c['id'])[0];self.assertEqual(len(self.store.list('retrieval',c['id'])),1)
        self.manifest.update(capture_only=False,name='Reuse',source={'kind':'snapshots','page_ids':[page['id']]})
        second=self.campaign();self.execute(second)
        self.assertEqual(self.environment.captures,1);self.assertTrue(self.store.list('run_result',second['id'])[0]['data']['preserved_success'])
        with zipfile.ZipFile(io.BytesIO(bundle(self.store,second['id'],True))) as archive:
            records=json.loads(archive.read('records.json'));self.assertTrue(any(r['id']==page['data']['capture_id'] for r in records))
    def test_campaign_source_version_change_prevents_dispatch(self):
        c=self.campaign();launch(self.store,c['id'])
        with patch('harness.versions.snapshot',return_value={'code_digest':'changed'}):
            Engine(self.store,{},self.environment,self.providers,self.retrievers).execute(c['id'])
        state,_=self.store.checkpoint(c['id']);self.assertEqual(state['status'],'interrupted');self.assertIn('version changed',state['error'])
        self.assertEqual(self.environment.captures,0);self.assertEqual(len(self.session.requests),0)
    def test_evaluator_runtime_drift_blocks_measurement(self):
        from harness.environment import Environment as RealEnvironment,EnvironmentChanged
        environment=RealEnvironment(self.store)
        with patch.object(environment,'runtime',return_value={'source_files':{'audit':'original'}}):environment.verify_runtime('campaign')
        with patch.object(environment,'runtime',return_value={'source_files':{'audit':'original'}}):environment.verify_runtime('campaign')
        with patch.object(environment,'runtime',return_value={'source_files':{'audit':'changed'}}),self.assertRaises(EnvironmentChanged):environment.verify_runtime('campaign')
        self.assertEqual(self.store.get('campaign-evaluator-runtime')['data']['source_files']['audit'],'original')
    def test_reused_baseline_cannot_mix_evaluator_versions(self):
        from harness.engine import existing
        fingerprint={'version':'one'}
        def freeze(cid):
            if not existing(self.store,cid+'-evaluator-runtime'):self.store.append('evaluator_snapshot',dict(fingerprint),cid,cid+'-evaluator-runtime')
        self.environment.verify_runtime=freeze;self.manifest['capture_only']=True
        first=self.campaign();self.execute(first);page=self.store.list('page',first['id'])[0]
        fingerprint['version']='two';self.manifest['source']={'kind':'snapshots','page_ids':[page['id']]}
        second=self.campaign();self.execute(second)
        state=self.store.checkpoint(second['id'])[0];self.assertEqual(state['status'],'interrupted')
        self.assertIn('different or missing evaluator versions',state['error']);self.assertEqual(self.environment.captures,1)
    def test_coordinated_repair_rejects_cycles_and_orders_dependencies(self):
        operations=[{'action':'set_attribute','selector':'img','name':'alt','value':'Page photo'},
                    {'action':'set_attribute','selector':'img','name':'alt','value':'First value'}]
        groups=[{'id':'final','selectors':['img'],'depends_on':['first'],'operation_indexes':[0]},
                {'id':'first','selectors':['img'],'depends_on':[],'operation_indexes':[1]}]
        candidate,_=materialize(HTML,json.dumps({'operations':operations,'root_causes':groups}),3,'https://fixture.example/')
        self.assertIn('alt="Page photo"',candidate)
        groups[1]['depends_on']=['final']
        with self.assertRaises(ContractError):materialize(HTML,json.dumps({'operations':operations,'root_causes':groups}),3,'https://fixture.example/')
    def test_local_provider_preserves_context_and_rejects_truncation(self):
        from harness.contracts import model_snapshot
        model=model_snapshot({'id':'local','model':'fixture:1','provider':'ollama','family':'fixture','context_length':32768})
        c=self.campaign();p=Providers(self.store,c['data'],c['id'],{'ollama_base_url':'http://local/v1'})
        envelope={'model':'fixture:1','message':{'content':'{}'},'done':True,'done_reason':'stop'}
        with patch.object(p,'dispatch',return_value=envelope) as dispatch:
            self.assertEqual(p.chat('run','repair','key',model,'known acquired prompt'),'{}')
            body=dispatch.call_args.args[4];self.assertFalse(body['truncate']);self.assertEqual(body['options']['num_ctx'],32768)
            self.assertEqual(dispatch.call_args.args[5],'http://local/api/chat')
        with patch.object(p,'dispatch',return_value=envelope | {'done_reason':'length'}),self.assertRaises(ContractError):
            p.chat('run','repair','key2',model,'source')
