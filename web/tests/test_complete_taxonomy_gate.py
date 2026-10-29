import time,unittest
from unittest.mock import Mock,patch
from harness.remediation_bridge import Bridge
from harness.contracts import MeasurementIncomplete

class CompleteTaxonomyGateTests(unittest.TestCase):
 def test_error_closure_does_not_repeat_incomplete_measurement_or_provider_calls(self):
  from remediation_jobs import close_failed_bridge
  b=Mock();b.rid='run';partial={'taxonomy_measurement':{'status':'partial'}}
  b.store.get.return_value={'data':partial};error=MeasurementIncomplete('Budget limit')
  outcome,returned=close_failed_bridge(b,error)
  self.assertEqual(outcome,partial);self.assertIs(returned,error)
  b.finish.assert_not_called();b.store.get.assert_called_once_with('run-result')
 def test_error_closure_preserves_new_measurement_failure_for_terminal_sql_state(self):
  from remediation_jobs import close_failed_bridge
  b=Mock();b.rid='run';partial={'taxonomy_measurement':{'status':'not_assessed'}}
  b.store.get.return_value={'data':partial};b.finish.side_effect=MeasurementIncomplete('Campaign reservation limit')
  outcome,error=close_failed_bridge(b,RuntimeError('Original failure'))
  self.assertEqual(outcome,partial);self.assertIsInstance(error,MeasurementIncomplete)
  b.finish.assert_called_once_with('Original failure')
 def test_candidate_measurement_failure_without_result_closes_without_more_judgments(self):
  from remediation_jobs import close_failed_bridge
  b=Mock();b.rid='run';error=MeasurementIncomplete('Context bound')
  b.store.get.side_effect=[KeyError('missing'),{'data':{'taxonomy_measurement':{'status':'not_assessed'}}}]
  b.finish.side_effect=MeasurementIncomplete('Context bound')
  outcome,returned=close_failed_bridge(b,error)
  self.assertEqual(outcome['taxonomy_measurement']['status'],'not_assessed')
  b.finish.assert_called_once_with('Context bound',measurement_failure=error)

 def test_failure_override_records_actual_error_without_calling_taxonomy(self):
  b=self.bridge()
  with patch('accessibility_taxonomy.assessment.measure_pair') as measure,patch('harness.remediation_bridge.once') as save:
   with self.assertRaises(MeasurementIncomplete):b.finish('Candidate interrupted',measurement_failure=MeasurementIncomplete('Context bound'))
  measure.assert_not_called()
  self.assertEqual(save.call_args.args[2]['taxonomy_measurement']['errors'],['Context bound'])
  self.assertEqual(b.state['status'],'failed')

 def bridge(self):
  b=Bridge.__new__(Bridge);b.store=Mock();b.store.get.return_value={'id':'audit','data':{'axe':1,'lighthouse':99}}
  b.state={'incumbent':{'audit_id':'audit','distance':0,'technical':'passed','original':True},'attempts':[],'started':time.time(),'policy_id':None}
  b.providers=Mock();b.rid='run';b.cid='campaign';b.url='https://example.test/';b.capture={};b.baseline={'id':'baseline'};b.manifest={'partition':'test','mode':'frozen'};b.page={'id':'page'};b.condition={'id':'P2'};b.costs=Mock(return_value={'known':True,'cost_usd':.01});b.persist=Mock()
  return b
 def test_missing_measurement_keeps_receipt_and_cannot_complete_even_when_targets_are_met(self):
  b=self.bridge()
  with patch('accessibility_taxonomy.assessment.measure_pair',return_value={'status':'not_assessed','errors':['Provider call limit reached']}),patch('harness.remediation_bridge.once') as save:
   with self.assertRaises(MeasurementIncomplete):b.finish('Targets met')
  self.assertEqual(b.state['status'],'failed');b.store.checkpoint.assert_not_called();self.assertEqual(save.call_args.args[2]['taxonomy_measurement']['status'],'not_assessed')
 def test_complete_measurement_with_original_retained_finishes_normally(self):
  b=self.bridge()
  with patch('accessibility_taxonomy.assessment.measure_pair',return_value={'status':'completed','errors':[]}),patch('harness.remediation_bridge.once'):
   result=b.finish('No beneficial intervention')
  self.assertEqual(b.state['status'],'completed');self.assertTrue(result['selected']['original']);self.assertTrue(result['preserved_success'])
 def test_unresolved_charge_persists_candidate_and_closes_incomplete_without_retry(self):
  from harness.providers import UncertainCall
  b=self.bridge();b.state['attempts']=['paid-attempt'];b.costs.return_value={'known':False,'cost_usd':.01}
  with patch('accessibility_taxonomy.assessment.measure_pair',side_effect=UncertainCall('Unresolved provider charge')) as measure,patch('harness.remediation_bridge.once') as save:
   with self.assertRaises(MeasurementIncomplete):b.finish('Provider interrupted')
  measure.assert_called_once();b.store.checkpoint.assert_not_called()
  outcome=save.call_args.args[2]
  self.assertEqual(outcome['attempts'],['paid-attempt']);self.assertFalse(outcome['costs']['known'])
  self.assertEqual(outcome['taxonomy_measurement']['errors'],['Unresolved provider charge'])
  self.assertEqual(b.state['status'],'failed')
