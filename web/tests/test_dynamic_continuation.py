import unittest
from remediation_completion import refinement_potential, localized_syntax_recovery, initial_progress
from harness.selection import select
from remediation_interventions import VERSION

class DynamicContinuationTests(unittest.TestCase):
 def test_measured_preservation_progress_can_continue_without_promotion(self):
  previous={'quality':0,'retention':{'links_percent':80,'text_percent':90}}
  self.assertEqual(refinement_potential(previous,0,{'links_percent':95,'text_percent':90}),['links_percent_progress'])
  self.assertEqual(refinement_potential(previous,0,{'links_percent':95},False),[])
  self.assertEqual(refinement_potential(previous,0,previous['retention']),[])
 def test_accessibility_progress_and_first_observation(self):
  self.assertEqual(refinement_potential({'quality':2,'retention':{}},1,{}),['accessibility_progress'])
  self.assertEqual(refinement_potential(None,1,{}),[])
 def test_fourth_iteration_decisions_uses_feedback_without_parameters(self):
  import json
  class Provider:
   def decisions(self, run, account, key, evidence, questions):
    self.evidence=json.loads(evidence);self.questions=questions
    values={'topic':'technology','purpose':'homepage','repair_context':'isolated','action':'P2:saved','repair_focus':'labels'}
    return {k:{'choice':v} for k,v in values.items()}
  provider=Provider();manifest={'mode':'frozen','workers':[{'id':'saved'}]}
  condition={'level':6,'selector':'decisions'}
  state={'axe':10,'distance':1,'iteration':3,'max_iterations':5,'cost_remaining':1,'time_remaining':1,'continuation_potential':True,'continuation_reasons':['links_percent_progress']}
  result=select(provider,'run','decision',manifest,condition,{},state)
  self.assertEqual(result['selected'],'P2:saved');self.assertIn('stop',result['available'])
  self.assertEqual(provider.evidence['state'],state);self.assertNotIn('learning_evidence',provider.evidence)
  self.assertIsNone(result['policy_version'])

 def test_dynamic_selector_may_stop_or_switch_after_measured_progress(self):
  import json
  class Provider:
   def decisions(self, run, account, key, evidence, questions):
    self.evidence=json.loads(evidence)
    self.choices=[choice['value'] for choice in next(q for q in questions if q['name']=='action')['choices']]
    return {'action':{'choice':'stop'}}
  provider=Provider()
  manifest={'mode':'frozen','workers':[{'id':'luna'},{'id':'haiku'}]}
  condition={'level':6,'selector':'decisions'}
  state={'iteration':1,'continuation_potential':True,
         'blocked_actions':['P1:luna'],'measured_feedback':{'candidate':{'axe':3},'content_retention':{'text_percent':80}}}
  result=select(provider,'run','decision',manifest,condition,{},state)
  self.assertEqual(result['selected'],'stop')
  self.assertNotIn('P1:luna',provider.choices)
  self.assertIn('P1:haiku',provider.choices)
  self.assertEqual(provider.evidence['state']['measured_feedback']['content_retention']['text_percent'],80)

 def test_first_dynamic_iteration_requires_a_measured_proposal(self):
  import json
  class Provider:
   def decisions(self, run, account, key, evidence, questions):
    choices=[item['value'] for item in next(q for q in questions if q['name']=='action')['choices']]
    self.asserted=('stop' not in choices)
    return {'action':{'choice':'P1:luna'}}
  provider=Provider()
  result=select(provider,'run','decision',{'mode':'frozen','workers':[{'id':'luna'}]},
                {'level':6,'selector':'decisions'}, {}, {'iteration':0,'axe':1,'lighthouse':90})
  self.assertTrue(provider.asserted)
  self.assertEqual(result['selected'],'P1:luna')

 def test_localized_syntax_recovery_is_bounded_and_preservation_gated(self):
  assessment={'checks':{'audit':'completed','observable_preservation':{'status':'passed'},'capture_verification':{'status':'admitted'},'syntax_nonregression':{'introduced':[{'selector':'main > div > li','rule':'element-permitted-parent'}]}}}
  self.assertTrue(localized_syntax_recovery({'quality':5},4,assessment))
  self.assertFalse(localized_syntax_recovery({'quality':5},4,assessment,True))
  self.assertFalse(localized_syntax_recovery({'quality':5},5,assessment))
  assessment['checks']['observable_preservation']['status']='violated'
  self.assertFalse(localized_syntax_recovery({'quality':5},4,assessment))

 def test_first_proposal_compares_with_audited_source(self):
  source=initial_progress(3)
  self.assertEqual(refinement_potential(source,1,{}),['accessibility_progress'])
  self.assertEqual(refinement_potential(source,3,{}),[])
  self.assertEqual(refinement_potential(source,4,{}),[])

 def test_public_policy_labels_map_to_distinct_internal_interventions(self):
  class Provider:
   def decisions(self, run, account, key, evidence, questions):
    return {'action':{'choice':'P2:luna-high'}}
  manifest={'intervention_version':VERSION,'workers':[{'id':'luna-high','model':'openai/gpt-6-luna','reasoning_effort':'high'}]}
  result=select(Provider(),'run','decision',manifest,{'level':6,'selector':'decisions'},
                {},{'iteration':0,'axe':1,'lighthouse':90})
  descriptor=next(item for item in result['action_descriptors'] if item['id']=='P2:luna-high')
  self.assertEqual((descriptor['level'],descriptor['wire_level']), (2,3))
  self.assertEqual(result['selected'],'P2:luna-high')

 def test_used_luna_high_never_downgrades_same_policy_to_light(self):
  class Provider:
   def decisions(self, run, account, key, evidence, questions):
    self.choices=[item['value'] for item in next(q for q in questions if q['name']=='action')['choices']]
    return {'action':{'choice':'stop'}}
  provider=Provider()
  manifest={'intervention_version':VERSION,'workers':[
   {'id':'luna-low','model':'openai/gpt-6-luna','reasoning_effort':'low'},
   {'id':'luna-high','model':'openai/gpt-6-luna','reasoning_effort':'high'},
   {'id':'haiku-low','model':'anthropic/claude-haiku-5.5','reasoning_effort':'low'}]}
  state={'iteration':1,'used_high_routes':[{'policy':'P1','model':'openai/gpt-6-luna'}]}
  select(provider,'run','decision',manifest,{'level':6,'selector':'decisions'}, {},state)
  self.assertNotIn('P1:luna-low',provider.choices)
  self.assertIn('P1:luna-high',provider.choices)
  self.assertIn('P2:luna-low',provider.choices)


class RetiredHistoryTests(unittest.TestCase):
 def test_history_configuration_is_rejected_before_any_lookup(self):
  from harness.engine import active_method
  from harness.contracts import ContractError
  for extra in ({'record_experience':True},{'experience_library_id':'retired'}):
   with self.assertRaises(ContractError):
    active_method({'mode':'frozen','conditions':[], **extra})
  with self.assertRaises(ContractError):
   active_method({'mode':'frozen','conditions':[{'controls':{'memory':True}}]})
