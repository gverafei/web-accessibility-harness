import accessibility_taxonomy.assessment
"""Fixed/adaptive SQL-loop adapters using durable receipts and labeled fixtures."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harness.store import Store
from harness.engine import create_campaign
from harness.remediation_bridge import Bridge, configure
from harness.providers import Providers, UncertainCall, Ledger
from harness.selection import actions, select
from harness.controller import profile
from harness.decision_models import DEFINITIONS

HTML='<!doctype html><html lang="en"><head><title>Fixture</title></head><body><main><h1>Fixture</h1><button id="save"></button></main></body></html>'

class Session:
    def __init__(self):self.requests=[]
    def post(self,url,**kw):
        self.requests.append(kw['json'])
        body=kw['json'];text=body['messages'][0]['content']
        if isinstance(text,list):
            evidence=json.loads(text[0]['text'].split('\nEVIDENCE\n')[1])
            answer={'status':'admitted','rationale':'Labeled fixture screenshot and content match.','evidence_refs':[evidence['references'][0]]}
            if 'Return exactly these five JSON keys' in text[0]['text']:
                answer={'reason_code':'usable','impact':'none','blocking_confidence':.01,'rationale':'Labeled fixture screenshot and content match.','evidence_refs':[evidence['references'][0]]}
        else:answer={'operations':[{'action':'set_attribute','selector':'#save','name':'aria-label','value':'Save'}]}
        class Response:
            status_code=200
        response=Response();response.text=json.dumps({'model':body['model'],'usage':{'prompt_tokens':5,'completion_tokens':5,'cost':.001},'choices':[{'message':{'content':json.dumps(answer)}}]})
        return response

class Environment:
    def __init__(self,store):self.store=store;self.captures=0
    def runtime(self):return {'version':'explicit-fixture-runtime'}
    def freeze_source(self,url,origin,source,rendered,screenshot,campaign,ident):
        self.captures+=1;blob=self.store.blob(source,'fixture source',campaign,'text/html');image=self.store.blob(b'fixture','fixture image',campaign,'image/jpeg')
        return self.store.append('capture',{'replay_source_id':blob['id'],'network_id':blob['id'],'rendered_id':blob['id'],'screenshot_id':image['id'],'captured_url':origin,'visible':{'fixture':True}},campaign,ident)
    def audit(self,capture,source,campaign,ident,config):
        fixed='aria-label="Save"' in source
        score=96 if fixed and 'data-partial-fixture' in source else 100 if fixed else 80
        raw={'status':'completed','axe':{'wcag_violations':0 if fixed else 5},'lighthouse':{'accessibility_score':score}}
        return self.store.append('audit',{'status':'completed','axe':raw['axe']['wcag_violations'],'lighthouse':raw['lighthouse']['accessibility_score'],
            'syntax':{'state':'passed'},'failures':[] if fixed else [{'id':'button-name','nodes':[{'target':['#save']}]}],'patch_failures':[],
            'lighthouse_failures':[],'artifacts':{'screenshot':capture['data']['screenshot_id']},'replay':{},'raw_result':raw},campaign,ident)
    def replay_check(self,capture,source,campaign,ident,audit):
        return self.store.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{},'replayed':{'fixture':True}},campaign,ident)

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(self.tmp.name)
        self.corpus=self.store.append('corpus',{'examples':[],'metadata':{}})
        self.workers=[{'id':name,'model':'openai/gpt-6-luna','family':'openai','reasoning_effort':'low','vision':True,'context_length':65536,
            'input_usd_per_million':.1,'output_usd_per_million':.1} for name in ('cheap','next')]
        self.manifest={'name':'Fixture','study_id':'fixture','seed':'1','mode':'frozen','partition':'development',
            'source':{'kind':'urls','urls':['https://fixture.example/']},'workers':self.workers,'capture_verifier':self.workers[0],
            'conditions':[{'id':'P6','level':6,'worker_id':'cheap','selector':'rules'}],'corpus_id':self.corpus['id'],
            'max_iterations':2,'repair_budget':{'max_cost_usd':1,'max_seconds':300,'max_calls':20,'max_output_tokens':1000},
            'review_budget':{'max_cost_usd':1,'max_seconds':300,'max_calls':20,'max_output_tokens':1000},'campaign_cost_limit':2}
        self.session=Session();self.env=Environment(self.store)
        self.screenshot=Path(self.tmp.name)/'original.jpg';self.screenshot.write_bytes(b'fixture')
    def bridge(self):
        campaign=create_campaign(self.store,self.manifest)
        self.store.checkpoint(campaign['id'],{'status':'externally_managed'})
        settings={'openrouter_base_url':'http://fixture','openrouter_api_key':'fixture-secret'}
        providers=Providers(self.store,campaign['data'],campaign['id'],settings,self.session)
        bridge=Bridge({'campaign_id':campaign['id'],'single_shot':False,'rag_enabled':False,'category':'news','category_source':'fixture','sql_source_id':7},
            {'id':9,'source_url':'https://fixture.example/'},settings,self.store,self.env,providers)
        bridge.prepare(HTML,HTML,str(self.screenshot),'unused')
        return bridge
    def test_fixed_assigned_level_survives_local_regeneration_refinement(self):
        for level in range(1,6):
            condition={'level':level,'worker_id':'cheap'}
            self.assertEqual(actions(self.manifest,condition,True),['P'+str(level)+':cheap'])

    def test_empty_proposal_retains_evidence_and_feedback_without_candidate(self):
        from harness.loop_checkpoint import validate_iteration_boundary
        from remediation_completion import NOOP_FEEDBACK
        bridge = self.bridge()
        bridge.begin_iteration(1)
        before = dict(bridge.state['incumbent'])
        parent = bridge.store.read_blob(before['source_id']).decode()
        calls = bridge.costs()
        with patch.object(bridge.environment, 'audit', side_effect=AssertionError('no new audit')):
            record = bridge.record_unchanged_proposal(parent, NOOP_FEEDBACK, {'applied': [], 'skipped': []})
            bridge.record_unchanged_proposal(parent, NOOP_FEEDBACK, {'applied': [], 'skipped': []})
        self.assertEqual(bridge.state['incumbent'], before)
        self.assertEqual(bridge.state['attempts'], [])
        self.assertEqual(bridge.state['iteration'], 1)
        self.assertEqual(bridge.state['empty_patch_count'], 1)
        self.assertEqual(record['data']['consumption'], calls)
        self.assertTrue(validate_iteration_boundary([], bridge.state, bridge.store))
        self.assertFalse(validate_iteration_boundary([{'iteration_number': 1}], bridge.state, bridge.store))
        self.assertEqual(bridge.dynamic_selection_feedback()['unmeasured_proposal']['feedback'], NOOP_FEEDBACK)
        bridge.state['iteration'] = 2
        self.assertTrue(validate_iteration_boundary([{'iteration_number': 2}], bridge.state, bridge.store))
    def candidate_limited_bridge(self, limit=5):
        from harness.iteration_policy import VERSION
        from harness.time_policy import CANDIDATE_BOUNDARY
        self.manifest.update(iteration_policy=VERSION, time_policy=CANDIDATE_BOUNDARY,
                             refinement_policy='budget-only-progress', max_iterations=limit)
        return self.bridge()

    def test_invalid_and_empty_proposals_do_not_use_candidate_slots_or_stop_after_ten_attempts(self):
        bridge = self.candidate_limited_bridge(limit=1)
        for number in range(1, 14):
            level, worker = bridge.begin_iteration(number)
            self.assertIsNotNone(level)
            if number % 2:
                bridge.record_invalid_proposal('Correct the supplied operation.', '/fixture/response.json')
            else:
                parent = bridge.store.read_blob(bridge.state['incumbent']['source_id']).decode()
                bridge.record_unchanged_proposal(parent, 'No effective change.', {'applied': [], 'skipped': []})
        self.assertEqual(bridge.state['attempts'], [])
        self.assertEqual(len(bridge.state['unmeasured_proposals']), 13)
        self.assertEqual(bridge.state['iteration'], 13)

    def test_evaluated_candidate_limit_stops_before_selection_or_another_model_call(self):
        bridge = self.candidate_limited_bridge(limit=2)
        bridge.state['attempts'] = ['measured-first', 'measured-second']
        requests = list(self.session.requests)
        self.assertEqual(bridge.begin_iteration(9), (None, None))
        self.assertEqual(bridge.state['stop_reason_override'], 'Evaluated candidate limit reached')
        self.assertEqual(self.session.requests, requests)

    def test_fixed_candidate_retry_records_invalid_feedback_and_keeps_the_measured_parent(self):
        self.manifest['conditions'] = [{'id': 'P2', 'level': 3, 'worker_id': 'cheap'}]
        bridge = self.candidate_limited_bridge()
        parent = dict(bridge.state['incumbent'])
        bridge.begin_iteration(1)
        record = bridge.record_invalid_proposal('Complete evidence is required.', '/fixture/response.json')
        self.assertEqual(record['kind'], 'proposal_invalid')
        self.assertEqual(bridge.state['incumbent'], parent)
        self.assertEqual(bridge.state['attempts'], [])
        self.assertEqual(bridge.state['feedback'], 'Complete evidence is required.')
        self.assertEqual(bridge.state['last_noop']['iteration'], 1)
        self.assertEqual(bridge.state['iteration'], 1)

    def test_attempt_cap_resets_only_after_an_evaluated_candidate(self):
        self.manifest['conditions'] = [{'id': 'P2', 'level': 3, 'worker_id': 'cheap'}]
        self.manifest['max_generation_attempts_per_candidate'] = 3
        bridge = self.candidate_limited_bridge()
        for number in (1, 2):
            self.assertIsNotNone(bridge.begin_iteration(number)[0])
            bridge.record_invalid_proposal('Correct the operation.', '/fixture/response.json')
        bridge.begin_iteration(3)
        improved = HTML.replace('<button id="save">', '<button id="save" aria-label="Save">')
        bridge.audit_record = self.env.audit(bridge.capture, improved, bridge.cid, bridge.attempt_id+'-audit', {})
        bridge.verification = {'id': 'fixture-verification', 'data': {'status': 'admitted'}}
        bridge.preservation = {'status': 'passed'}
        bridge.assessment = {'status': 'passed', 'basis': 'observable-technical-v1'}
        bridge.outcome(improved, True)
        self.assertEqual(bridge.state['last_evaluated_generation_attempt'], 3)
        for number in (4, 5, 6):
            self.assertIsNotNone(bridge.begin_iteration(number)[0])
            bridge.record_invalid_proposal('Correct the operation.', '/fixture/response.json')
        requests = list(self.session.requests)
        self.assertEqual(bridge.begin_iteration(7), (None, None))
        self.assertIn('3 attempts', bridge.state['stop_reason_override'])
        self.assertEqual(self.session.requests, requests)
        self.assertEqual(len(bridge.state['attempts']), 1)

    def test_attempt_cap_is_frozen_and_typed_without_changing_old_manifests(self):
        from harness.contracts import ContractError
        from harness.iteration_policy import VERSION
        self.assertNotIn('max_generation_attempts_per_candidate', create_campaign(self.store, self.manifest)['data'])
        self.manifest.update(iteration_policy=VERSION, max_generation_attempts_per_candidate=20)
        self.assertEqual(create_campaign(self.store, self.manifest)['data']['max_generation_attempts_per_candidate'], 20)
        for value in (0, 1001, 1.5, True):
            self.manifest['max_generation_attempts_per_candidate'] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                create_campaign(self.store, self.manifest)

    def test_perfect_fixed_candidate_stops_generation_but_completes_final_taxonomy(self):
        self.manifest['conditions'] = [{'id': 'P2', 'level': 3, 'worker_id': 'cheap'}]
        self.manifest['stop_at_perfect_audit'] = True
        bridge = self.candidate_limited_bridge()
        bridge.begin_iteration(1)
        improved = HTML.replace('<button id="save">', '<button id="save" aria-label="Save">')
        bridge.audit_record = self.env.audit(bridge.capture, improved, bridge.cid, bridge.attempt_id+'-audit', {})
        bridge.verification = {'id': 'fixture-verification', 'data': {'status': 'admitted'}}
        bridge.preservation = {'status': 'passed'}
        bridge.assessment = {'status': 'passed', 'basis': 'observable-technical-v1'}
        bridge.outcome(improved, True)
        requests = list(self.session.requests)
        self.assertEqual(bridge.begin_iteration(2), (None, None))
        self.assertEqual(self.session.requests, requests)
        self.assertIn('Perfect audit', bridge.state['stop_reason_override'])
        with patch('accessibility_taxonomy.assessment.measure_pair', return_value={'status': 'completed', 'errors': []}) as taxonomy:
            result = bridge.finish(bridge.state['stop_reason_override'])
        taxonomy.assert_called_once()
        self.assertEqual(result['taxonomy_measurement']['status'], 'completed')
        self.assertEqual((result['axe'], result['lighthouse']), (0, 100))

    def test_generation_retry_stops_at_time_boundary_without_another_request(self):
        import time
        bridge = self.candidate_limited_bridge(limit=5)
        bridge.state['started'] = time.time() - bridge.manifest['repair_budget']['max_seconds'] - 1
        requests = list(self.session.requests)
        self.assertEqual(bridge.begin_iteration(12), (None, None))
        self.assertEqual(bridge.state['stop_reason_override'], 'Execution time limit reached')
        self.assertEqual(self.session.requests, requests)

    def test_candidate_iteration_policy_is_frozen_and_rejects_unknown_units(self):
        from harness.iteration_policy import VERSION
        self.manifest['iteration_policy'] = VERSION
        self.assertEqual(create_campaign(self.store, self.manifest)['data']['iteration_policy'], VERSION)
        self.manifest['iteration_policy'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'iteration policy'):
            create_campaign(self.store, self.manifest)

    def test_user_stop_prevents_another_generation_and_closes_without_extra_assessment_calls(self):
        from harness.run_stop import request_stop, REASON
        bridge = self.candidate_limited_bridge()
        request_stop(bridge.store, 9)
        requests = list(self.session.requests)
        self.assertEqual(bridge.begin_iteration(1), (None, None))
        with patch('accessibility_taxonomy.assessment.measure_pair', side_effect=AssertionError('No new paid assessment')):
            result = bridge.finish(REASON)
        self.assertEqual(result['stop_reason'], REASON)
        self.assertTrue(result['selected']['original'])
        self.assertEqual(self.session.requests, requests)

    def test_missing_observed_native_state_blocks_before_visual_or_generator_calls(self):
        from harness.contracts import ContractError
        self.manifest['native_control_state_required']=True
        with self.assertRaisesRegex(ContractError,'Observed native control state is unavailable'):
            self.bridge()
        self.assertEqual(self.session.requests,[])
    def test_native_state_requirement_is_typed_and_preserved_in_manifest(self):
        self.manifest['native_control_state_required']=True
        campaign=create_campaign(self.store,self.manifest)
        self.assertIs(campaign['data']['native_control_state_required'],True)
        self.manifest['native_control_state_required']='false'
        with self.assertRaisesRegex(ValueError,'must be a boolean'):
            create_campaign(self.store,self.manifest)

    def test_repeatability_requirement_is_typed_and_blocks_missing_measurement_before_review(self):
        self.manifest['source_repeatability_required']=True
        campaign=create_campaign(self.store,self.manifest)
        self.assertIs(campaign['data']['source_repeatability_required'],True)
        with self.assertRaisesRegex(ValueError,'not repeatable'):
            self.bridge()
        self.assertEqual(self.session.requests,[])
        self.manifest['source_repeatability_required']='false'
        with self.assertRaisesRegex(ValueError,'must be boolean'):
            create_campaign(self.store,self.manifest)
    def test_rules_change_both_dimensions_after_stagnation(self):
        context=profile(HTML,{'status':'completed','failures':[{'id':'button-name','nodes':[{'target':['#save']}]}]},'https://fixture.example/')
        state={'iteration':0,'max_iterations':3,'stagnant':0,'axe':5,'distance':1,'cost_remaining':1,'time_remaining':1}
        first=select(None,'run','key',self.manifest,self.manifest['conditions'][0],context,state)
        second=select(None,'run','key',self.manifest,self.manifest['conditions'][0],context,state|{'stagnant':1})
        self.assertEqual(first['selected'],'P1:cheap');self.assertEqual(second['selected'],'P2:next')

    def test_dynamic_bridge_selects_again_without_fixed_continuation_adviser(self):
        bridge=self.bridge()
        bridge.manifest['refinement_policy']='budget-only-progress'
        bridge.state['last_candidate_report']={'candidate':{'axe':5,'lighthouse':80},
            'content_retention':{'text_percent':90},'visual_warnings':['missing content']}
        chosen={'selected':'P1:next','available':['stop','P1:next']}
        with patch('harness.progress_continuation.choose',side_effect=AssertionError('Fixed continuation must not route P5')), \
             patch('harness.remediation_bridge.select',return_value=chosen) as selector:
            level,worker=bridge.begin_iteration(2)
        self.assertEqual((level,worker['id']),(1,'next'))
        state=selector.call_args.args[6]
        self.assertEqual(state['measured_feedback']['content_retention']['text_percent'],90)
        self.assertEqual(state['measured_feedback']['candidate']['axe'],5)

    def test_dynamic_empty_patches_block_only_the_stalled_action(self):
        bridge=self.bridge()
        bridge.manifest['refinement_policy']='budget-only-progress'
        attempt=bridge.store.append('attempt',{'level':1,'worker_id':'cheap','source_id':bridge.state['incumbent']['source_id']},
                                    bridge.cid,bridge.rid+'-fixture-attempt')
        bridge.state['attempts']=[attempt['id']]
        bridge.state['empty_patch_count']=2
        chosen={'selected':'P1:next','available':['stop','P1:next']}
        with patch('harness.remediation_bridge.select',return_value=chosen) as selector:
            level,worker=bridge.begin_iteration(2)
        self.assertEqual((level,worker['id']),(1,'next'))
        self.assertEqual(selector.call_args.args[6]['blocked_actions'],['P1:cheap'])
        self.assertEqual(bridge.state['empty_patch_count'],0)

    def test_bounded_fixed_refinement_cannot_be_vetoed_by_an_advisory_stop(self):
        from remediation_interventions import VERSION
        self.manifest.update(intervention_version=VERSION,candidate_review_mode='diagnostic-only',refinement_policy='bounded-feedback')
        self.manifest['conditions']=[{'id':'P1','level':1,'worker_id':'cheap','selector':'fixed','public_level':1}]
        bridge=self.bridge()
        bridge.state['incumbent'].update(distance=0,technical='passed')
        bridge.state['last_candidate_report']={'functional_reasons':['broken_visible_resources'],'visual_impact':'minor'}
        with patch('harness.refinement_decisions.choose',side_effect=AssertionError('Fixed diagnostic loop must continue without a stop veto')):
            level,worker=bridge.begin_iteration(2)
        self.assertEqual(level,1)
        self.assertEqual(worker['id'],'cheap')
        self.assertEqual(bridge.manifest['candidate_review_mode'],'diagnostic-only')
        self.manifest['candidate_review_mode']='invented'
        with self.assertRaisesRegex(ValueError,'Invalid candidate_review_mode'):
            create_campaign(self.store,self.manifest)
    def test_ledger_before_parse_reuses_known_response_without_second_dispatch(self):
        bridge=self.bridge();bridge.begin_iteration(1)
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture repair'}],'max_tokens':64}
        first=bridge.transport(body);bridge.call_index=0;second=bridge.transport(body)
        self.assertEqual(first,second);self.assertEqual(len(self.session.requests),2) # baseline verifier + one worker
        self.assertEqual(len(bridge.providers.ledger.rows(bridge.cid,bridge.rid)),2)
    def test_truncated_diagnostic_replays_paid_response_then_allows_generator(self):
        from types import SimpleNamespace
        from harness.contracts import ModelOutputIncomplete
        bridge = self.bridge()
        bridge.begin_iteration(1)
        bridge.task_runtime = SimpleNamespace(active_task_name='repair-diagnostician')
        body = {'model':bridge.worker['model'], 'messages':[{'role':'user','content':'diagnose fixture'}], 'max_tokens':64}
        def response(finish, content):
            return type('Response',(),{'status_code':200,'text':json.dumps({
                'model':bridge.worker['model'],'usage':{'prompt_tokens':5,'completion_tokens':64,'cost':.001},
                'choices':[{'finish_reason':finish,'message':{'content':content}}]})})()
        with patch.object(self.session,'post',side_effect=[response('length',None),response('stop','{"operations":[]}')]) as post:
            with self.assertRaises(ModelOutputIncomplete):
                bridge.transport(body)
            receipt = bridge.store.get(bridge.rid + '-worker-output-failure')
            bridge.call_index = 0
            self.assertEqual(bridge.replay_output_limit(8192), 64)
            with self.assertRaises(ModelOutputIncomplete):
                bridge.transport(body)
            self.assertEqual(post.call_count,1)
            bridge.task_runtime.active_task_name = 'repair-generator'
            result = bridge.transport(dict(body, messages=[{'role':'user','content':'repair fixture'}]))
            self.assertEqual(result[0], '{"operations":[]}')
            self.assertEqual(post.call_count,2)
            self.assertEqual(bridge.store.get(receipt['id']),receipt)
            rows = bridge.providers.ledger.rows(bridge.cid,bridge.rid)
            self.assertEqual(len(rows),3)  # verifier, paid diagnosis, new generation

    def test_later_diagnostic_failure_does_not_block_earlier_successful_paid_replay(self):
        from types import SimpleNamespace
        from harness.contracts import ModelOutputIncomplete
        bridge=self.bridge();bridge.begin_iteration(1)
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture generation'}],'max_tokens':64}
        def response(finish,content):
            return type('Response',(),{'status_code':200,'text':json.dumps({'model':bridge.worker['model'],
                'usage':{'prompt_tokens':5,'completion_tokens':64,'cost':.001},
                'choices':[{'finish_reason':finish,'message':{'content':content}}]})})()
        with patch.object(self.session,'post',side_effect=[response('stop','{"operations":[]}'),response('length',None)]) as post:
            saved=bridge.transport(body)
            bridge.task_runtime=SimpleNamespace(active_task_name='repair-diagnostician')
            diagnosis=dict(body,messages=[{'role':'user','content':'fixture diagnosis'}])
            with self.assertRaises(ModelOutputIncomplete):bridge.transport(diagnosis)
            bridge._advisory_completion_exhausted=False
            bridge.task_runtime.active_task_name=None
            bridge.call_index=0
            self.assertEqual(bridge.transport(body),saved)
            self.assertEqual(post.call_count,2)

    def test_empty_paid_advice_is_read_without_reusing_findings_or_new_request(self):
        from types import SimpleNamespace
        from harness.contracts import ModelOutputIncomplete
        bridge=self.bridge();bridge.begin_iteration(1)
        bridge.task_runtime=SimpleNamespace(active_task_name='repair-diagnostician')
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':
            'You are the accessibility diagnosis agent BEFORE localized patch generation. Fixture evidence.'}],'max_tokens':64}
        response=type('Response',(),{'status_code':200,'text':json.dumps({'model':bridge.worker['model'],
            'usage':{'prompt_tokens':5,'completion_tokens':64,'cost':.001},
            'choices':[{'finish_reason':'length','message':{'content':None}}]})})()
        with patch.object(self.session,'post',return_value=response) as post:
            with self.assertRaises(ModelOutputIncomplete):bridge.transport(body)
            bridge.call_index=0
            self.assertIsNone(bridge.resume_saved_diagnosis())
            bridge.execution_revision={'id':'fixture-recovery'}
            reused=bridge.resume_saved_diagnosis()
            self.assertEqual(reused[0],None)
            self.assertEqual(reused[3],.001)
            self.assertEqual(bridge.call_index,1)
            self.assertEqual(post.call_count,1)
            receipt=bridge.store.list('advisory_output_unavailable',bridge.cid)[0]
            self.assertEqual(receipt['data']['findings'],[])

    def test_received_advice_is_grounded_again_without_model_inference(self):
        bridge=self.bridge();bridge.begin_iteration(1)
        raw=json.dumps({'summary':'name','findings':[{'specialty':'semantics','selector':'#go',
            'rule':'','evidence':'Original','recommendation':'Use the observed button name'}]})
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':
            'You are the accessibility diagnosis agent BEFORE localized patch generation. Fixture.'}],'max_tokens':128}
        response=type('Response',(),{'status_code':200,'text':json.dumps({'model':bridge.worker['model'],
            'usage':{'prompt_tokens':5,'completion_tokens':64,'cost':.001},
            'choices':[{'finish_reason':'stop','message':{'content':raw}}]})})()
        with patch.object(self.session,'post',return_value=response) as post:
            bridge.transport(body)
            bridge.call_index=0;bridge.execution_revision={'id':'fixture-recovery'}
            reused=bridge.resume_saved_diagnosis('<button id="go">Original</button>',[])
            self.assertEqual(reused[0],raw)
            receipt=bridge.store.list('advisory_receipt_reused',bridge.cid)[0]
            self.assertEqual(len(receipt['data']['findings']),1)
            self.assertEqual(post.call_count,1)

    def test_paid_diagnosis_and_patch_replay_after_stagnation_reset(self):
        from remediation_diagnosis import diagnosis_needed
        bridge = self.bridge(); bridge.begin_iteration(1)
        diagnosis = json.dumps({'summary': 'No added findings', 'findings': []})
        bodies = [
            {'model': bridge.worker['model'], 'max_tokens': 128,
             'messages': [{'role': 'user', 'content': text}]}
            for text in (
                'You are the accessibility diagnosis agent BEFORE localized patch generation. Fixture.',
                'Apply the measured contextual correction. Grounded diagnosis: ' + diagnosis)]
        response = type('Response', (), {'status_code': 200, 'text': json.dumps({
            'model': bridge.worker['model'], 'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'cost': .001},
            'choices': [{'finish_reason': 'stop', 'message': {'content': diagnosis}}]})})()
        with patch.object(self.session, 'post', return_value=response) as post:
            advice = bridge.transport(bodies[0]); saved_patch = bridge.transport(bodies[1])
            bridge.call_index = 0; bridge.state['empty_patch_count'] = 0
            bridge.execution_revision = {'id': 'fixture-recovery'}
            self.assertFalse(diagnosis_needed(False, False, stagnant=False))
            self.assertEqual(bridge.resume_saved_diagnosis(HTML, []), advice)
            self.assertEqual(bridge.transport(bodies[1]), saved_patch)
            self.assertEqual(post.call_count, 2)

    def test_incomplete_worker_output_keeps_receipt_and_blocks_recovery(self):
        from harness.contracts import ContractError
        for finish, content, refusal in [('length', '{"operations":[]}', None),
                                         ('stop', '', None), ('content_filter', None, None),
                                         ('stop', 'ignored', 'refused')]:
            with self.subTest(finish=finish, content=content, refusal=refusal):
                self.setUp()
                bridge=self.bridge();bridge.begin_iteration(1)
                body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture repair'}],'max_tokens':64}
                response=type('Response',(),{'status_code':200,'text':json.dumps({'model':bridge.worker['model'],
                    'usage':{'prompt_tokens':5,'completion_tokens':64,'cost':.001},
                    'choices':[{'finish_reason':finish,'message':{'content':content,'refusal':refusal}}]})})()
                before=len(self.session.requests)
                with patch.object(self.session,'post',return_value=response) as post:
                    with self.assertRaises(ContractError):bridge.transport(body)
                    self.assertEqual(post.call_count,1)
                    bridge.call_index=0
                    with self.assertRaises(ContractError):bridge.transport(body)
                    bridge.call_index=1
                    with self.assertRaises(ContractError):bridge.transport(body)
                    self.assertEqual(post.call_count,1)
                rows=bridge.providers.ledger.rows(bridge.cid,bridge.rid)
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[-1]['cost'],.001)
                self.assertTrue(rows[-1]['response_id'])
                self.assertEqual(len(self.session.requests),before)
                failure=self.store.get(bridge.rid+'-worker-output-failure')
                self.assertEqual(failure['data']['call_id'],rows[-1]['id'])

    def test_recovery_finishes_only_the_candidate_started_before_deadline(self):
        from harness.iteration_policy import VERSION as CANDIDATE_POLICY
        from harness.time_policy import CANDIDATE_BOUNDARY
        self.manifest.update(iteration_policy=CANDIDATE_POLICY, time_policy=CANDIDATE_BOUNDARY,
                             max_generation_attempts_per_candidate=20)
        bridge=self.bridge();bridge.begin_iteration(1)
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture repair'}],'max_tokens':64}
        bridge.transport(body)
        call=bridge.providers.ledger.rows(bridge.cid,bridge.rid)[-1]
        bridge.execution_revision={'data':{'completed_iteration':0,'prior_call_ids':[call['id']]}}
        with patch('harness.remediation_bridge.time.time',return_value=bridge.state['started']+1000):
            self.assertIsNotNone(bridge.begin_iteration(1)[0])
            self.assertEqual(bridge.begin_iteration(2),(None,None))

    def test_empty_provider_retry_requires_authorization_and_allows_later_calls(self):
        from harness.contracts import ContractError, ModelOutputIncomplete
        bridge=self.bridge();bridge.begin_iteration(1)
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture repair'}],'max_tokens':64}
        def response(error=False):
            choice=({'finish_reason':'error','error':{'code':502},'message':{'content':None}}
                    if error else {'finish_reason':'stop','message':{'content':'{"operations":[]}'}})
            return type('Response',(),{'status_code':200,'text':json.dumps({
                'model':bridge.worker['model'],'usage':{'prompt_tokens':5,'completion_tokens':0 if error else 5,'cost':.001},
                'choices':[choice]})})()
        with patch.object(self.session,'post',side_effect=[response(True),response(),response()]) as post:
            with self.assertRaises(ModelOutputIncomplete):bridge.transport(body)
            failure=self.store.get(bridge.rid+'-worker-output-failure')
            call=next(row for row in bridge.providers.ledger.rows(bridge.cid,bridge.rid)
                      if row['id']==failure['data']['call_id'])
            bridge.call_index=0
            with self.assertRaises(ContractError):bridge.transport(body)
            receipt=bridge.providers.ledger.reconcile(call['id'],.001,'Offline provider billing fixture')
            bridge.providers.ledger.authorize_transport_retry(call['id'],receipt['id'],'Explicit identical retry fixture')
            bridge.execution_revision={'id':'recorded-boundary'}
            result=bridge.transport(body)
            bridge.call_index=0
            self.assertEqual(bridge.transport(body),result)
            self.assertEqual(post.call_count,2)
            bridge.transport(dict(body,messages=[{'role':'user','content':'next fixture task'}]))
            self.assertEqual(post.call_count,3)
            self.assertEqual(self.store.get(failure['id']),failure)
            self.assertAlmostEqual(sum(row['cost'] for row in bridge.providers.ledger.rows(bridge.cid,bridge.rid)),.004)

    def test_unknown_response_never_dispatches_again(self):
        bridge=self.bridge();bridge.begin_iteration(1)
        body={'model':bridge.worker['model'],'messages':[{'role':'user','content':'fixture repair'}],'max_tokens':64,
              'provider':{'allow_fallbacks':False,'require_parameters':True},'stream':False}
        bridge.providers.ledger.begin(bridge.cid,bridge.rid,'repair',bridge.attempt_id+':call:0',body,bridge.worker,
                                      bridge.manifest['repair_budget'],bridge.manifest['campaign_cost_limit'])
        with self.assertRaises(UncertainCall):bridge.transport(body)
        self.assertEqual(len(self.session.requests),1)
    def test_invalid_capture_blocks_generation(self):
        with patch.object(Environment,'replay_check',side_effect=lambda *a,**k:self.store.append('replay_admission',{'status':'rejected','reasons':['blank']},a[2],a[3])):
            with self.assertRaisesRegex(ValueError,'blocked repair'):self.bridge()
        self.assertEqual(self.session.requests,[])


    def test_regression_keeps_first_candidate_in_checkpoint_outcome_and_recovery(self):
        self.manifest['targets']={'max_axe':0,'min_lighthouse':100}
        bridge=self.bridge();bridge.begin_iteration(1)
        improved=HTML.replace('<button id="save">','<button id="save" aria-label="Save" data-partial-fixture="true">')
        bridge.audit_record=self.env.audit(bridge.capture,improved,bridge.cid,bridge.attempt_id+'-audit',{})
        bridge.verification={'id':'fixture-verification','data':{'status':'admitted'}}
        bridge.preservation={'status':'passed'};bridge.assessment={'status':'passed','basis':'observable-technical-v1'}
        bridge.outcome(improved,True);incumbent=dict(bridge.state['incumbent'])
        bridge.begin_iteration(2)
        bridge.audit_record=self.env.audit(bridge.capture,HTML,bridge.cid,bridge.attempt_id+'-audit',{})
        bridge.verification={'id':'fixture-second-verification','data':{'status':'admitted'}}
        bridge.outcome(HTML,False)
        self.assertEqual(bridge.state['incumbent'],incumbent)
        self.assertEqual(self.store.checkpoint(bridge.rid)[0]['incumbent'],incumbent)
        with patch('accessibility_taxonomy.assessment.measure_pair',return_value={'status':'completed','errors':[]}):
            outcome=bridge.finish('synthetic regression')
        self.assertEqual((outcome['axe'],outcome['lighthouse']),(0,96))
        self.assertEqual(outcome['selected'],incumbent)
        self.assertEqual(len(outcome['attempts']),2)
        self.assertEqual(self.store.read_blob(incumbent['source_id']).decode(),improved)

    def test_rejected_regeneration_keeps_refinement_branch_without_promotion(self):
        bridge=self.bridge();bridge.begin_iteration(1);bridge.level=4
        original=dict(bridge.state['incumbent'])
        proposal=HTML.replace('Fixture</h1>','Regenerated fixture</h1>')
        bridge.audit_record=self.env.audit(bridge.capture,proposal,bridge.cid,bridge.attempt_id+'-audit',{})
        bridge.verification={'id':'fixture-rejected-verification','data':{'status':'rejected'}}
        bridge.assessment={'status':'violated','checks':{'syntax_nonregression':{'state':'passed'}}}
        bridge.outcome(proposal,False)
        branch=bridge.state['branch']
        self.assertEqual(self.store.read_blob(branch['source_id']).decode(),proposal)
        self.assertEqual(bridge.state['incumbent'],original)
        self.assertEqual(self.store.checkpoint(bridge.rid)[0]['branch'],branch)
        with patch('accessibility_taxonomy.assessment.measure_pair',return_value={'status':'completed','errors':[]}):
            self.assertTrue(bridge.finish('fixture omitted content')['selected']['original'])


    def test_validation_domain_conflict_precedes_capture_and_provider_calls(self):
        self.store.assign_domain('fixture','fixture.example','development')
        self.manifest.update(mode='frozen',partition='validation')
        with self.assertRaisesRegex(ValueError,'partition'):self.bridge()
        self.assertEqual(self.env.captures,0)
        self.assertEqual(self.session.requests,[])



    def test_registration_rejects_learning_on_validation(self):
        controls={'corpora':[{'id':self.corpus['id']}], 'groups':[{'id':'fixture'}]}
        values={'harness_corpus':self.corpus['id'],'preservation_level':'4',
                'harness_learning':'development','harness_partition':'validation'}
        with patch('remediation_model_choices.model_choices',return_value=self.workers),patch('harness.remediation_bridge.options',return_value=controls):
            with self.assertRaisesRegex(ValueError,'retired'):
                configure(self.store,{}, {'id':7},self.workers[0],values)
        self.assertEqual(self.store.list('campaign'),[])

    def test_main_study_registration_uses_separate_test_and_budget_identity(self):
        group={'id':'main-study-fixture','stage':'remediation','total_usd':30,
               'stage_limits':{'remediation':30}}
        controls={'corpora':[{'id':self.corpus['id']}], 'groups':[group]}
        values={'harness_corpus':self.corpus['id'],'preservation_level':'1',
                'harness_partition':'test','harness_study_id':'main-study-fixture',
                'harness_budget_group':group['id'],'harness_verifier':'cheap',
                'max_cost_usd':'5','max_execution_seconds':'900','max_iterations':'5',
                'max_axe':'5','min_lighthouse':'90'}
        with patch('remediation_model_choices.model_choices',return_value=self.workers), \
             patch('harness.remediation_bridge.options',return_value=controls), \
             patch('harness.decision_models.capture_choices',return_value=[self.workers[0]]), \
             patch('harness.decision_models.catalogue',return_value=DEFINITIONS):
            cfg=configure(self.store,{}, {'id':7,'url':'https://heldout.example/'},self.workers[0],values)
        manifest=self.store.get(cfg['campaign_id'])['data']
        self.assertEqual(manifest['partition'],'test')
        self.assertEqual(manifest['study_id'],'main-study-fixture')
        self.assertEqual(manifest['budget_group'],group)
        self.assertEqual(manifest['campaign_cost_limit'],5)
        self.assertEqual(manifest['contextual_judge_model']['model'],'openai/gpt-6-luna-decisions')
        self.assertEqual(manifest['image_judge_model']['reasoning_effort'],'low')
        # Both roles share the campaign ceiling; a hidden .5 review account
        # must not prevent complete taxonomy within the authorized run cap.
        self.assertEqual(manifest['repair_budget']['max_cost_usd'],5)
        self.assertEqual(manifest['review_budget']['max_cost_usd'],5)
        self.assertEqual(manifest['review_budget']['max_call_cost_usd'],5)
        self.assertEqual(manifest['workers'][0]['id'],'cheap')
        self.assertTrue(manifest['stop_at_perfect_audit'])
        self.assertEqual(manifest['max_generation_attempts_per_candidate'], 20)
        from coordinated_role_validation import VERSION as PATCH_VERSION
        self.assertEqual(manifest['patch_validation_version'], PATCH_VERSION)
        self.assertFalse(Ledger(self.store).rows())

    def test_dynamic_minor_only_endpoint_stops_before_another_paid_selector(self):
        from remediation_interventions import VERSION
        self.manifest['intervention_version'] = VERSION
        bridge = self.bridge()
        bridge.state['last_candidate_report'] = {
            'retained':True, 'candidate':{'axe':0,'lighthouse':100},
            'functional_status':'admitted', 'visual_status':'admitted',
            'visual_impact':'minor', 'visual_warnings':['minor_visual_finding'],
            'remaining_taxonomy_failures':{'Syntactic':0,'Semantic':0,'Layout':0},
        }
        before = len(self.session.requests)
        with patch.object(bridge, 'prepare_dynamic_context'), patch(
                'harness.remediation_bridge.select', side_effect=AssertionError('No new paid selector')):
            self.assertEqual(bridge.begin_iteration(2), (None, None))
        self.assertEqual(len(self.session.requests), before)
        self.assertIn('without remaining actionable findings', bridge.state['stop_reason_override'])

    def test_admitted_ceiling_stops_after_the_initial_improvement_review(self):
        bridge=self.bridge();bridge.state['incumbent']['distance']=0
        before=len(self.session.requests)
        with patch('harness.remediation_bridge.select',side_effect=AssertionError('Ceiling should stop before selector')):
            self.assertEqual(bridge.begin_iteration(2),(None,None))
        self.assertEqual(len(self.session.requests),before)
        self.assertEqual(bridge.decision['data']['selector'],'deterministic-target-stop')
        self.assertTrue(bridge.state['incumbent']['original'])
        self.assertEqual(bridge.state['attempts'],[])

    def test_zero_shot_keeps_requested_generation_on_ceiling(self):
        bridge=self.bridge();bridge.config['single_shot']=True;bridge.condition.update(level=1,worker_id='cheap',selector='fixed')
        bridge.state['incumbent']['distance']=0
        self.assertEqual(bridge.begin_iteration(1)[0],1)

    def test_current_rejected_redesign_can_refine_even_when_original_meets_targets(self):
        from remediation_interventions import VERSION
        bridge=self.bridge();bridge.manifest['intervention_version']=VERSION
        bridge.state['incumbent']['distance']=0
        bridge.condition.update(level=4,worker_id='cheap',selector='fixed')
        bridge.state['branch']={'level':4,'worker_id':'cheap','source_id':bridge.state['incumbent']['source_id'],'audit_id':bridge.state['incumbent']['audit_id']}
        bridge.state['stagnant']=1
        with patch.object(bridge.environment,'with_design_resources',return_value=bridge.capture,create=True):
            self.assertEqual(bridge.begin_iteration(2)[0],4)
        self.assertNotEqual(bridge.decision['data']['selector'],'deterministic-target-stop')

    def test_preaccepted_in_target_candidate_can_receive_known_destination_repair(self):
        from remediation_interventions import VERSION
        bridge=self.bridge();bridge.manifest['intervention_version']=VERSION
        bridge.manifest['decision_model']={'model':'synthetic/decisions'}
        bridge.state['incumbent'].update(distance=0,technical='passed',original=False)
        bridge.state['last_candidate_report']={'destination_repairs':[{'selector':'a','after':'/known'}]}
        bridge.condition.update(level=4,worker_id='cheap',selector='fixed')
        choice=self.store.append('local_refinement_decision',{'action':'repair_known_destinations'},bridge.cid)
        with patch('harness.refinement_decisions.choose',return_value=choice),patch.object(bridge.environment,'with_design_resources',return_value=bridge.capture,create=True):
            self.assertEqual(bridge.begin_iteration(2)[0],4)
        self.assertNotEqual(bridge.decision['data']['selector'],'deterministic-target-stop')

    def test_failed_assessment_cannot_be_promoted_by_any_caller(self):
        bridge=self.bridge();bridge.assessment={'status':'violated'}
        with self.assertRaisesRegex(ValueError,'cannot become the retained'):
            bridge.outcome(HTML,True)

    def test_current_candidate_taxonomy_is_measured_before_selection_and_stored(self):
        from remediation_interventions import VERSION
        b=self.bridge();b.manifest['intervention_version']=VERSION;b.attempt_id=b.rid+'-attempt-0';b.level=4;b.worker=self.workers[0]
        pair={'status':'completed','original':{'categories':{'Semantic':{'judged':5,'failed':2}}},'retained':{'categories':{'Semantic':{'judged':5,'failed':1}}}}
        assessment=self.store.append('taxonomy_assessment', {'opportunities': []}, b.cid)
        pair['retained_assessment_id']=assessment['id']
        replay=self.store.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{},'replayed':{'fixture':True}},b.cid)
        def bound_replay(store,capture,audit,*args,**kwargs):
            replay['data']['audit_id']=audit['id'];return replay
        with patch('pathlib.Path.read_text',return_value=HTML),patch('harness.candidate_admission.evaluate',side_effect=bound_replay),patch('accessibility_taxonomy.assessment.measure_pair',return_value=pair)as measure:
            b.evaluate({'urls':['https://fixture.example/candidate.html']})
        measure.assert_called_once()
        self.assertTrue(b.improvement['improved']);self.assertEqual(b.improvement['gains'][0]['metric'],'Semantic')
        self.assertEqual(b.candidate_taxonomy,pair)

    def test_invalid_visual_contract_is_an_instrument_stop_after_taxonomy(self):
        from remediation_interventions import VERSION
        from harness.contracts import MeasurementIncomplete
        b=self.bridge();b.manifest['intervention_version']=VERSION;b.attempt_id=b.rid+'-attempt-0';b.level=4;b.worker=self.workers[0]
        pair={'status':'completed'}
        replay=self.store.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{}},b.cid)
        invalid=self.store.append('evidence_verification',{'status':'review_required','response_contract_error':True},b.cid)
        with patch('pathlib.Path.read_text',return_value=HTML),patch('harness.candidate_admission.evaluate',return_value=replay),patch('accessibility_taxonomy.assessment.measure_pair',return_value=pair)as measure,patch('harness.remediation_bridge.verify',return_value=invalid):
            with self.assertRaisesRegex(MeasurementIncomplete,'repair generation must not repeat'):
                b.evaluate({'urls':['https://fixture.example/candidate.html']})
        measure.assert_called_once()
        self.assertFalse(self.store.list('technical_assessment',b.cid))

    def test_fixed_first_review_is_not_blocked_by_already_met_thresholds(self):
        bridge=self.bridge();bridge.state['incumbent']['distance']=0
        bridge.condition.update(level=1,worker_id='cheap',selector='fixed')
        level,worker=bridge.begin_iteration(1)
        self.assertEqual(level,1);self.assertEqual(worker['id'],'cheap')
        self.assertNotEqual(bridge.decision['data']['selector'],'deterministic-target-stop')

    def test_zero_shot_visual_contract_error_keeps_observed_audit_available(self):
        from remediation_interventions import VERSION
        b=self.bridge();b.manifest['intervention_version']=VERSION;b.config['single_shot']=True
        b.attempt_id=b.rid+'-attempt-0';b.level=4;b.worker=self.workers[0]
        replay=self.store.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{}},b.cid)
        invalid=self.store.append('evidence_verification',{'status':'review_required','response_contract_error':True},b.cid)
        with patch('pathlib.Path.read_text',return_value=HTML),patch('harness.candidate_admission.evaluate',return_value=replay),patch('accessibility_taxonomy.assessment.measure_pair')as measure,patch('harness.remediation_bridge.verify',return_value=invalid):
            result=b.evaluate({'urls':['https://fixture.example/candidate.html']})
        measure.assert_not_called()
        self.assertEqual(result,b.audit_record['data']['raw_result'])
        self.assertEqual(b.assessment['status'],'unverified')
        self.assertTrue(b.verification['data']['response_contract_error'])


    def test_zero_shot_truncated_response_is_retained_and_recovery_reuses_call(self):
        from remediation_baseline import baseline_messages
        b = self.bridge()
        b.config['single_shot'] = True
        b.condition.update(level=1, worker_id='cheap', selector='fixed')
        b.begin_iteration(1)
        sent_before = len(self.session.requests)
        original_post = self.session.post
        def truncated(url, **kwargs):
            response = original_post(url, **kwargs)
            payload = json.loads(response.text)
            payload['choices'] = [{'finish_reason': 'length', 'message': {'content': '<html><p>Partial'}}]
            response.text = json.dumps(payload)
            return response
        self.session.post = truncated
        messages = baseline_messages(HTML)
        request = {'model': b.worker['model'], 'messages': messages, 'max_tokens': 100}
        first = b.transport(request)
        b.begin_iteration(1)
        second = b.transport(request)
        self.assertEqual(first, second)
        self.assertEqual(first[0], '<html><p>Partial')
        self.assertEqual(len(self.session.requests), sent_before + 1)
        self.assertEqual(self.session.requests[-1]['messages'], messages)
        self.assertEqual(len([c for c in b.providers.ledger.rows(b.cid, b.rid) if ':call:' in c['logical_key']]), 1)

    def test_single_pass_worker_keeps_partial_markup_and_one_cached_generation(self):
        from remediation_jobs import call_model
        from remediation_zero_shot import generate
        b = self.bridge()
        b.config['single_shot'] = True
        b.condition.update(level=1, worker_id='cheap', selector='fixed')
        original_post = self.session.post
        def partial(url, **kwargs):
            response = original_post(url, **kwargs)
            payload = json.loads(response.text)
            payload['choices'] = [{'finish_reason': 'length', 'message': {'content': '<main>partial'}}]
            response.text = json.dumps(payload)
            return response
        self.session.post = partial
        settings = dict(b.settings, _harness_transport=b.transport,
                        _model_configuration=self.workers[0])
        with tempfile.TemporaryDirectory() as directory:
            first = generate(b, settings, HTML, Path(directory), call_model)
            count = len(self.session.requests)
            second = generate(b, settings, HTML, Path(directory), call_model)
            self.assertEqual(first, second)
            self.assertEqual(first[0], '<main>partial')
            self.assertTrue(first[1]['evaluable'])
            self.assertEqual(Path(directory, 'one-shot-original-response.txt').read_text(), '<main>partial')
            self.assertEqual(len(self.session.requests), count)
