import unittest
from pathlib import Path
from jinja2 import Environment,FileSystemLoader,select_autoescape
ROOT=Path(__file__).resolve().parents[1]
class LiveLoopTests(unittest.TestCase):
 def render(self,**changes):
  env=Environment(loader=FileSystemLoader(ROOT/'app/templates'),autoescape=select_autoescape(['html']))
  env.globals.update(_=lambda s:s,csrf_token=lambda:'isolated-test-token',url_for=lambda endpoint,**kw:'/captured/'+str(kw.get('iteration_id','original')))
  run={'id':1,'status':'running','current_phase':'evaluate','current_iteration':2,'max_iterations':5,'progress_message':'Evaluating candidate','total_cost_usd':.012,'progress_percent':50,'dynamic_level':True,'execution_mode':'iterative'}
  run.update(changes.pop('run',{}))
  from remediation_report_presentation import execution_counts
  run.setdefault('execution_counts', execution_counts(run, changes.get('iterations', [])) if not run.get('live_demo') else {'evaluated':0,'attempts':run['current_iteration'],'limit':'∞'})
  return env.get_template('_remediation_live_loop.html').render(run=run,events=changes.get('events',[]),iterations=changes.get('iterations',[]))
 def test_empty_evidence_does_not_invent_calls_or_capture(self):
  html=self.render();self.assertIn('data-active-node="audit"',html);self.assertIn('Decisions responses</dt><dd>0',html);self.assertNotIn('<img',html)
 def test_fixed_and_zero_shot_do_not_imply_dynamic_agent_or_rag(self):
  html=self.render(run={'dynamic_level':False,'execution_mode':'single_shot','current_phase':'prompt'})
  self.assertIn('data-active-node="context"',html);self.assertIn('Fixed policy',html);self.assertGreaterEqual(html.count('Not used'),2)
 def test_taxonomy_cases_and_answers_are_escaped_and_counted(self):
  event={'event_type':'decisions_call','decision_role':'Semantic evaluation','decision_cases':[{'criterion':'Link purpose <script>','result':'Violation detected'}],'actor':'Decisions agent','activity_category':'llm','activity_label':'LLM','activity_description':'Judge meaning','activity_model':'luna'}
  html=self.render(run={'progress_message':'Semantic taxonomy assessment'},events=[event]);self.assertIn('data-active-node="taxonomy"',html);self.assertIn('Recorded decision cases</dt><dd>1',html);self.assertNotIn('Link purpose <script>',html);self.assertNotIn('Violation detected',html)
 def test_revisited_generation_is_active_without_marking_all_steps_complete(self):
  html=self.render(run={'current_phase':'generate'},events=[{'event_type':'evaluate','actor':'Evaluator','activity_category':'tool','activity_label':'Tool','activity_description':'Audit'}])
  self.assertIn('data-active-node="repair"',html);self.assertIn('live-loop-audit has-evidence',html);self.assertIn('live-loop-preserve ',html)

 def test_actual_taxonomy_activity_drives_actor_nodes_and_fixed_roster(self):
  from remediation_report_presentation import live_loop_participants
  events=[{'id':1,'event_type':'evaluate','actor':'Evaluator','activity_category':'tool','activity_label':'Tool'},
          {'id':2,'event_type':'decisions_call','decision_role':'Semantic evaluation','actor':'Decisions agent','activity_category':'llm','activity_label':'LLM','activity_model':'luna','decision_cases':[{'result':'passed'}]},
          {'id':3,'event_type':'decisions_call','decision_role':'Semantic evaluation','actor':'Decisions agent','activity_category':'llm','activity_label':'LLM','activity_model':'luna','decision_cases':[{'result':'passed'}]}]
  participants=live_loop_participants(events)
  html=self.render(run={'live_participants':participants,'live_taxonomy_progress':{'status':'running','stage':'contextual','completed':2,'total':6}},events=events)
  self.assertIn('data-active-node="taxonomy"',html)
  self.assertIn('data-live-actor="3"',html)
  self.assertIn('×2',html)
  self.assertIn('2/6',html)
  self.assertIn('Live participants',html)
  self.assertNotIn('Latest evidence',html)
  self.assertLess(html.index('Current activity'),html.index('live-loop-diagram'))
  self.assertNotIn('M166 165V130L440 110',html)
  self.assertNotIn('four seconds',html)

 def test_inactive_satellites_disappear_and_real_progress_is_not_indeterminate(self):
  from remediation_report_presentation import live_loop_participants
  events=[{'id':1,'event_type':'generate','actor':'Generator'}, {'id':2,'event_type':'decisions_call','decision_role':'Semantic evaluation','actor':'Decisions agent'}]
  html=self.render(run={'live_participants':live_loop_participants(events),'live_taxonomy_progress':{'status':'running','stage':'contextual','completed':2,'total':6}},events=events)
  self.assertNotIn('data-live-actor="1"',html)
  self.assertIn('data-live-actor="2"',html)
  self.assertNotIn('is-indeterminate',html)
  self.assertIn('aria-valuemax="6"',html)
  self.assertNotIn('live-loop-govern',html)

 def test_provider_chip_requires_actual_receipt_and_shows_request_or_return(self):
  self.assertNotIn('live-model-chip',self.render())
  call={'id':'actual-call','vendor':'OpenAI','provider':'OpenRouter','stage':'repair','pending':True,'returned':False,'model':'openai/gpt-6-luna'}
  html=self.render(run={'live_provider_activity':{'active':[call],'latest':call}})
  self.assertIn('data-active-node="repair"',html)
  self.assertIn('LLM request',html)
  self.assertIn('GPT-6 Luna',html)
  call.update(pending=False,returned=True)
  html=self.render(run={'current_phase':'generate','live_provider_activity':{'active':[],'latest':call}})
  self.assertIn('LLM response',html)
  self.assertNotIn('is-consulting',html)

 def test_provider_projection_is_scoped_and_uses_recorded_provider(self):
  import tempfile
  from harness.store import Store
  from harness.providers import Ledger
  from remediation_report_presentation import live_provider_activity
  with tempfile.TemporaryDirectory() as path:
   store=Store(path);Ledger(store)
   receipt=store.append('call_request',{'model':{'provider':'openrouter'}})
   with store.connect() as db:
    for rid,ident,key in [('sql-run-1','one','taxonomy-test'),('sql-run-2','two','other')]:
     db.execute('INSERT INTO calls(id,logical_key,campaign,run,account,created,reserved,cost_status,status,request_hash,request_id,model) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident,key,'c',rid,'review',1,0,'reserved','dispatching','h',receipt['id'],'openai/luna'))
   actual=live_provider_activity(store,1)
   self.assertEqual(actual['count'],1)
   self.assertEqual(actual['active'][0]['provider'],'OpenRouter')
   self.assertEqual(actual['active'][0]['stage'],'taxonomy')

 def test_demo_is_bounded_presentation_and_wraps_without_provider_or_persistence(self):
  from remediation_live_demo import frame,STEPS,scenario
  first,_,_=frame(0);repeat,_,_=frame(len(scenario(0,0)))
  self.assertTrue(first['live_demo']);self.assertEqual(repeat['current_iteration'],2)
  self.assertEqual(first['progress_message'],repeat['progress_message'])
  for index in range(len(scenario(0,0))):
   run,events,iterations=frame(index)
   html=self.render(run=run,events=events,iterations=iterations)
   self.assertIn('Simulated activity',html)
   self.assertNotIn('live-provider-cloud',html)

 def test_recovered_public_level_and_retention_are_read_only_projections(self):
  from remediation_report_presentation import iteration_presentation
  from unittest.mock import patch
  import tempfile,copy
  strategy={'assigned_level':5,'public_level':4,'source_fidelity':{'retention':{'text_percent':80,'original_words':10,'candidate_words':8}},'harness':{'retained':True}}
  saved=copy.deepcopy(strategy);item={'id':1,'strategy':strategy,'generator_model':'openai/luna'}
  with tempfile.TemporaryDirectory() as folder,patch('harness.store.Store') as store:
   store.return_value.get.side_effect=KeyError('no historical revision')
   iteration_presentation(item,1,Path(folder))
  self.assertEqual(item['selection_summary']['level'],4)
  self.assertEqual(item['retention_summary']['percent'],80)
  self.assertEqual(strategy,saved)

 def test_return_arrow_waits_for_actual_refinement_and_acceptance_has_own_exit(self):
  self.assertNotIn('class="live-loop-return"',self.render())
  self.assertNotIn('class="live-loop-return"',self.render(events=[{'id':1,'event_type':'refine'}]))
  self.assertIn('data-event-kind="feedback"',self.render(events=[{'id':1,'event_type':'refine'}]))
  html=self.render(events=[{'id':2,'event_type':'accepted'}]);self.assertIn('live-loop-accepted',html);self.assertIn('Chosen result',html);self.assertNotIn('class="live-loop-return"',html)

 def test_demo_has_varied_bounded_routes_and_actual_stage_api_badges(self):
  from remediation_live_demo import scenario,frame
  self.assertNotEqual(scenario(1,0),scenario(2,0))
  run,events,it=frame(12,1);html=self.render(run=run,events=events,iterations=it)
  self.assertIn('data-live-call=',html);self.assertIn('LLM request',html)

 def test_two_stages_activate_only_with_two_recorded_pending_calls(self):
  calls=[{'id':'one','stage':'repair','model':'openai/gpt-6-luna','pending':True,'vendor':'OpenAI'}, {'id':'two','stage':'taxonomy','model':'openai/gpt-6-luna-decisions','pending':True,'vendor':'OpenAI'}]
  html=self.render(run={'live_provider_activity':{'active':calls,'latest':calls[-1]}})
  self.assertIn('live-loop-repair is-active',html)
  self.assertIn('live-loop-taxonomy is-active',html)
  self.assertIn('data-live-call="one"',html);self.assertIn('data-live-call="two"',html)
  calls[0]['pending']=False
  html=self.render(run={'live_provider_activity':{'active':calls[1:],'latest':calls[-1]}})
  self.assertNotIn('live-loop-repair is-active',html)

 def test_live_header_names_the_actual_active_strategy(self):
  html=self.render(run={'execution_route':{'active':'P2'},'current_iteration':2})
  self.assertIn('data-active-policy>P2</strong>',html)
  self.assertIn('Current strategy',html)

 def test_attempts_are_not_presented_as_evaluated_candidates(self):
  from bs4 import BeautifulSoup
  rows=[{'id':1,'iteration_number':6,'generator_provider':'openai','axe_violations':0,'lighthouse_score':100}]
  page=BeautifulSoup(self.render(run={'current_iteration':8,'max_iterations':5},iterations=rows),'html.parser')
  self.assertEqual(page.select_one('[data-live-candidate-count]').get_text(' ',strip=True),'Evaluated candidates: 1 / 5')
  self.assertEqual(page.select_one('[data-live-attempt-count]').get_text(' ',strip=True),'Generation attempts: 8')

 def test_evaluator_phase_overrides_an_earlier_generation_event(self):
  from remediation_report_presentation import live_loop_participants
  events=[{'id':1,'event_type':'generate','actor':'Generator'}]
  html=self.render(run={'current_phase':'evaluate','live_participants':live_loop_participants(events)},events=events)
  self.assertIn('data-active-node="audit"',html)

 def test_invalid_and_unchanged_proposals_do_not_invent_evaluator_activity(self):
  from remediation_report_presentation import live_loop_participants
  for kind in ('invalid_output','no_op'):
   events=[{'id':1,'event_type':kind,'actor':'Output contract guard'}]
   participants=live_loop_participants(events)
   html=self.render(run={'current_phase':'generate','live_participants':participants},events=events)
   self.assertIn('data-active-node="repair"',html)
   self.assertEqual(participants['stages']['audit']['calls'],0)
   self.assertTrue('before evaluation' in html or 'No new candidate was evaluated' in html)

 def test_completed_taxonomy_progress_disappears_when_generation_resumes(self):
  from bs4 import BeautifulSoup
  call={'id':'repair-call','stage':'repair','model':'openai/gpt-6-luna','pending':True,'returned':False,'provider':'OpenRouter'}
  html=self.render(run={'current_phase':'generate','progress_message':'Generating candidate',
      'live_taxonomy_progress':{'status':'running','completed':250,'total':250},
      'live_provider_activity':{'active':[call],'latest':call}})
  page=BeautifulSoup(html,'html.parser')
  taxonomy=page.select_one('[data-live-stage="taxonomy"]')
  self.assertIsNone(taxonomy.select_one('.live-stage-count'))
  self.assertIsNone(taxonomy.select_one('.live-stage-details'))
  self.assertIn('data-active-node="repair"',html)

 def test_generator_actors_and_model_share_one_annotation_stack(self):
  from bs4 import BeautifulSoup
  from remediation_report_presentation import live_loop_participants
  events=[{'id':1,'event_type':'planning','actor':'Planner'},
          {'id':2,'event_type':'generate','actor':'Generator'}]
  call={'id':'repair-call','stage':'repair','model':'openai/gpt-6-luna','pending':True,'returned':False,'provider':'OpenRouter'}
  html=self.render(events=events,run={'current_phase':'generate',
      'live_participants':live_loop_participants(events),
      'live_provider_activity':{'active':[call],'latest':call}})
  page=BeautifulSoup(html,'html.parser')
  annotations=page.select_one('[data-live-stage="repair"] .live-stage-details')
  self.assertIsNotNone(annotations.select_one('.live-stage-satellites'))
  self.assertIsNotNone(annotations.select_one('.live-model-chip'))
