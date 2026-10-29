import copy,hashlib,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from harness.candidate_repair_context import messages,branch_capture,branch_document,functional_evidence
from harness.contracts import ContractError
class CorrectiveContextTests(unittest.TestCase):
 def test_full_visual_diagnosis_survives_large_score_and_fidelity_evidence(self):
  report={'candidate_audit_id':'candidate','candidate':{'axe':8,'lighthouse':95},'visual_status':'rejected','visual_reason':'Hero clipped by horizontal overflow','visual_impact':'material','visual_blocking_confidence':.99,'source_fidelity':{'raw':'x'*200000}}
  original=copy.deepcopy(report);result=messages(report)
  self.assertEqual(result[0]['role'],'system');self.assertEqual(result[1]['role'],'user')
  self.assertIn(report['visual_reason'],result[1]['content']);self.assertNotIn('source_fidelity',result[1]['content']);self.assertEqual(report,original)
 def test_no_report_does_not_add_feedback_to_initial_generation(self):
  self.assertEqual(messages(None),[])
 def test_current_rejected_branch_capture_is_used_instead_of_old_incumbent(self):
  with tempfile.TemporaryDirectory()as folder:
   picture=Path(folder)/'candidate.jpg';picture.write_bytes(b'fixture')
   document='<html>Current branch</html>';audit={'data':{'replay':{'input_document_sha256':hashlib.sha256(document.encode()).hexdigest()},'raw_result':{'screenshot_path':str(picture)}}}
   store=SimpleNamespace(get=lambda ident:audit)
   self.assertEqual(branch_capture(store,{'audit_id':'rejected-branch'},document),str(picture))
   with self.assertRaises(ContractError):branch_capture(store,{'audit_id':'rejected-branch'},'<html>Original</html>')
 def test_missing_candidate_capture_is_not_substituted_by_the_source(self):
  document='candidate';store=SimpleNamespace(get=lambda ident:{'data':{'replay':{'input_document_sha256':hashlib.sha256(document.encode()).hexdigest()},'raw_result':{}}})
  self.assertIsNone(branch_capture(store,{'audit_id':'a'},document))

 def test_refinement_advances_to_latest_rejected_branch_without_changing_incumbent(self):
  documents={'one':b'first candidate','two':b'newer rejected candidate'}
  store=SimpleNamespace(read_blob=documents.__getitem__,get=lambda ident:{'data':{'replay':{'input_document_sha256':hashlib.sha256(documents[ident]).hexdigest()},'raw_result':{}}})
  incumbent={'source_id':'original'}
  branch={'source_id':'one','audit_id':'one','level':4,'worker_id':'luna-high'}
  self.assertEqual(branch_document(store,branch,4,'luna-high'),'first candidate')
  branch.update(source_id='two',audit_id='two')
  self.assertEqual(branch_document(store,branch,4,'luna-high'),'newer rejected candidate')
  self.assertEqual(incumbent,{'source_id':'original'})
  with self.assertRaises(ContractError):branch_capture(store,branch,'first candidate')

 def test_worker_or_intervention_switch_does_not_reuse_an_unrelated_branch(self):
  store=SimpleNamespace(read_blob=lambda ident:self.fail('Unrelated branch must not be read'))
  branch={'source_id':'one','audit_id':'one','level':4,'worker_id':'luna-high'}
  self.assertIsNone(branch_document(store,branch,5,'luna-high'))
  self.assertIsNone(branch_document(store,branch,4,'luna-light'))
  self.assertIsNone(branch_document(store,None,4,'luna-high'))

 def test_bridge_dispatch_receives_complete_priority_report_after_the_main_prompt(self):
  from harness.remediation_bridge import Bridge
  from remediation_interventions import VERSION
  collected=[];store=SimpleNamespace(get=lambda ident:(_ for _ in ()).throw(KeyError(ident)))
  call={'logical_key':'r-attempt-1:call:0','input_tokens':1,'output_tokens':1,'cost':0,'elapsed':0}
  provider=SimpleNamespace(dispatch=lambda *args:collected.append(args[4])or{'model':'openai/luna','choices':[{'finish_reason':'stop','message':{'content':'candidate'}}]},ledger=SimpleNamespace(rows=lambda *args:[call]))
  bridge=Bridge.__new__(Bridge);bridge.rid='r';bridge.cid='c';bridge.attempt_id='r-attempt-1';bridge.call_index=0;bridge.store=store;bridge.providers=provider
  bridge.worker={'model':'openai/luna'};bridge.manifest={'intervention_version':VERSION,'repair_budget':{'max_output_tokens':100}};bridge.config={'single_shot':False};bridge.number=2
  bridge.condition={'level':1}
  bridge.state={'last_candidate_report':{'visual_reason':'Hero clipped by horizontal overflow','visual_status':'rejected','visual_impact':'material'}}
  bridge.settings={'openrouter_base_url':'https://example.invalid','openrouter_api_key':'test'}
  bridge.transport({'model':'openai/luna','max_tokens':20,'messages':[{'role':'user','content':'Large audit evidence '+'x'*10000}]})
  self.assertIn('Hero clipped by horizontal overflow',collected[0]['messages'][-1]['content'])
  self.assertEqual(collected[0]['messages'][-1]['role'],'user')

 def test_exact_broken_resource_and_targets_survive_large_other_evidence(self):
  audit={'id':'a-current','data':{'replay':{'input_document_sha256':'current-sha'},'raw_result':{'transport':{'visible':{'broken_image_urls':['https://assets.invalid/exact-news.jpg']}}}}}
  usability={'audit_id':'a-current','metrics':{'unresolved_local_targets':[{'element':'a','target':'#missing'}]}}
  evidence=functional_evidence(audit,usability)
  report={'candidate_audit_id':'a-current','functional_evidence':evidence,'source_fidelity':{'raw':'x'*200000}}
  content=messages(report)[1]['content']
  self.assertIn('exact-news.jpg',content);self.assertIn('#missing',content);self.assertIn('current-sha',content)
  self.assertNotIn('source_fidelity',content)
  with self.assertRaises(ContractError):functional_evidence(audit,{'audit_id':'older'})

 def test_absent_resource_urls_remain_unknown_without_source_substitution(self):
  evidence=functional_evidence({'id':'a','data':{}},{'audit_id':'a','metrics':{}})
  self.assertEqual(evidence['broken_image_urls'],[])
  self.assertIsNone(evidence['document_sha256'])
  self.assertIn('unavailable',evidence['scope'])
