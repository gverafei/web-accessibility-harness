import unittest,json
from unittest.mock import Mock
from remediation_approaches import dynamic_presentation
from remediation_interventions import presentation, policy_identifier
class DynamicPresentationTests(unittest.TestCase):
 def test_dynamic_filter_and_identifier_do_not_inherit_the_selected_action(self):
  for priority in (15,55,75,90):
   run={'dynamic_level':True,'accessibility_priority':priority,
        'intervention_version':'two-patch-creative-regeneration-v2'}
   self.assertEqual(presentation(run)['preservation_filter'],'current-105')
   self.assertEqual(presentation(run)['presentation_level'],5)
   self.assertEqual(policy_identifier(run),'P5')
   self.assertEqual(run['accessibility_priority'],priority)
 def test_frozen_condition_overrides_worker_count_and_current_priority(self):
  store=Mock();store.get.return_value={'data':{'conditions':[{'level':6}]}}
  run={'accessibility_priority':15,'harness_config_json':json.dumps({'campaign_id':'historical'})}
  self.assertTrue(dynamic_presentation(run,store))
  store.get.return_value={'data':{'conditions':[{'level':1}]}}
  self.assertFalse(dynamic_presentation(run,store))
 def test_missing_history_does_not_invent_dynamic_mode(self):
  self.assertFalse(dynamic_presentation({},Mock()))
