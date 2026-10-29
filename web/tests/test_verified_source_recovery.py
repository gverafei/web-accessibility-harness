import tempfile,unittest
from harness.store import Store
from harness.source_recovery import recover

class Environment:
 def __init__(self,store,admitted=True):self.store=store;self.admitted=admitted;self.calls=[]
 def audit(self,capture,source,campaign,ident,config):
  self.calls.append('audit');return self.store.append('audit',{'status':'completed'},campaign,ident)
 def replay_check(self,capture,source,campaign,ident,audit):
  self.calls.append('replay');return self.store.append('replay_admission',{'status':'admitted' if self.admitted else 'rejected'},campaign,ident)

class SourceRecoveryTests(unittest.TestCase):
 def setup_records(self,directory):
  store=Store(directory);source='<html><body><main><h1>Original</h1></main></body></html>'
  rendered='<html><body><main><h1>Original</h1>'+('<button>Dynamic control</button>'*6)+'</main></body></html>'
  blob=store.blob(rendered,'rendered','campaign','text/html')
  capture=store.append('capture',{'captured_url':'https://example.com/','rendered_id':blob['id'],'visible':{},'assets':[], 'source_preparation':{'selection':{'selected':'network_response'}}},'campaign','capture')
  baseline=store.append('audit',{'status':'completed'},'campaign','baseline')
  check=store.append('replay_admission',{'status':'rejected','reasons':['essential_control_loss']},'campaign','check')
  return store,capture,source,baseline,check
 def test_verified_alternative_is_once_and_original_evidence_is_unchanged(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store)
   result=recover(store,environment,capture,source,baseline,check,'campaign','source',{})
   self.assertNotEqual(result[0]['id'],capture['id']);self.assertIn('Dynamic control',result[1]);self.assertEqual(result[3]['data']['status'],'admitted')
   self.assertEqual(store.get('capture'),capture);self.assertEqual(store.get('baseline'),baseline);self.assertEqual(store.get('check'),check)
   second=recover(store,environment,capture,source,baseline,check,'campaign','source',{})
   self.assertEqual(second,result);self.assertEqual(environment.calls,['audit','replay']);self.assertEqual(store.get('source-rendered-context-selection')['data']['paid_calls'],0)
 def test_unverified_alternative_cannot_replace_original(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory)
   self.assertEqual(recover(store,Environment(store,False),capture,source,baseline,check,'campaign','source',{}),(capture,source,baseline,check))
   self.assertFalse(store.get('source-rendered-context-selection')['data']['accepted'])
 def test_resource_failure_never_triggers_a_content_switch(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store);check['data']['reasons']=['visible_media_loss','broken_visible_media']
   self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','source',{}),(capture,source,baseline,check));self.assertEqual(environment.calls,[])
 def test_recorded_native_control_loss_can_try_captured_state_once_under_unchanged_admission(self):
  for admitted in (True,False):
   with self.subTest(admitted=admitted),tempfile.TemporaryDirectory() as directory:
    store,capture,source,baseline,check=self.setup_records(directory)
    check['data']['reasons']=['native_control_state_changed'];environment=Environment(store,admitted)
    result=recover(store,environment,capture,source,baseline,check,'campaign','native-state',{})
    self.assertEqual(result[0]['id']!=capture['id'],admitted)
    self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','native-state',{}),result)
    self.assertEqual(environment.calls,['audit','replay']);self.assertEqual(store.get('capture'),capture)
    self.assertEqual(store.get('native-state-rendered-context-selection')['data']['paid_calls'],0)
 def test_native_state_loss_with_broken_resources_cannot_trigger_recovery(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store)
   check['data']['reasons']=['native_control_state_changed','broken_visible_resources']
   self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','native-state',{}),(capture,source,baseline,check));self.assertEqual(environment.calls,[])

 def test_newly_deferred_media_can_try_captured_dom_once_but_must_pass_admission(self):
  for admitted in (True,False):
   with self.subTest(admitted=admitted),tempfile.TemporaryDirectory() as directory:
    store,capture,source,baseline,check=self.setup_records(directory)
    check['data']['reasons']=['newly_deferred_media'];environment=Environment(store,admitted)
    result=recover(store,environment,capture,source,baseline,check,'campaign','media',{})
    self.assertEqual(result[0]['id']!=capture['id'],admitted)
    self.assertEqual(environment.calls,['audit','replay'])
    self.assertEqual(store.get('capture'),capture)
    self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','media',{}),result)
    self.assertEqual(environment.calls,['audit','replay'])

 def test_dynamic_image_presence_can_use_a_verified_alternative_but_not_broken_resources(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store)
   check['data']['reasons']=['visible_content_loss','visible_image_loss','visible_media_loss']
   result=recover(store,environment,capture,source,baseline,check,'campaign','images',{})
   self.assertNotEqual(result[0]['id'],capture['id']);self.assertEqual(result[3]['data']['status'],'admitted')

 def test_blank_response_replay_recovers_only_with_valid_acquired_content(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store)
   check['data']['reasons']=['blank_replay','visible_content_loss','essential_control_loss']
   capture['data']['visible']={'text':'A valid acquired application document with meaningful content. '*3}
   result=recover(store,environment,capture,source,baseline,check,'campaign','blank',{})
   self.assertNotEqual(result[0]['id'],capture['id']);self.assertEqual(result[3]['data']['status'],'admitted')
   capture['data']['visible']={};environment=Environment(store)
   self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','empty',{}),(capture,source,baseline,check));self.assertEqual(environment.calls,[])
 def test_blank_with_resource_failure_still_cannot_switch_source(self):
  with tempfile.TemporaryDirectory() as directory:
   store,capture,source,baseline,check=self.setup_records(directory);environment=Environment(store)
   capture['data']['visible']={'text':'Meaningful original content. '*4}
   check['data']['reasons']=['blank_replay','broken_visible_resources']
   self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','broken',{}),(capture,source,baseline,check));self.assertEqual(environment.calls,[])

 def test_visual_uncertainty_can_try_one_native_context_but_cannot_bypass_deterministic_admission(self):
  for admitted in (True,False):
   with self.subTest(admitted=admitted),tempfile.TemporaryDirectory() as directory:
    store,capture,source,baseline,check=self.setup_records(directory)
    check['data'].update(status='admitted',reasons=[])
    visual=store.append('evidence_verification',{'phase':'baseline','capture_id':capture['id'],'deterministic_id':check['id'],'status':'review_required','reason_code':'insufficient'},'campaign','visual')
    environment=Environment(store,admitted)
    result=recover(store,environment,capture,source,baseline,check,'campaign','visual-source',{},verification=visual)
    self.assertEqual(result[0]['id']!=capture['id'],admitted)
    self.assertEqual(environment.calls,['audit','replay'])
    self.assertTrue(store.get('visual-source-rendered-context-selection')['data']['visual_verification_required'])
    self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','visual-source',{},verification=visual),result)
    self.assertEqual(environment.calls,['audit','replay'])
    self.assertEqual(store.get('capture'),capture)

 def test_visual_recovery_rejects_unrelated_refused_candidate_or_mismatched_evidence(self):
  cases=[{'reason_code':'blocked'},{'reason_code':'unrelated'},{'reason_code':None},{'phase':'candidate'},{'capture_id':'other'},{'deterministic_id':'other'}]
  for changed in cases:
   with self.subTest(changed=changed),tempfile.TemporaryDirectory() as directory:
    store,capture,source,baseline,check=self.setup_records(directory);check['data'].update(status='admitted',reasons=[])
    data={'phase':'baseline','capture_id':capture['id'],'deterministic_id':check['id'],'status':'review_required','reason_code':'insufficient'}|changed
    visual=store.append('evidence_verification',data,'campaign','visual');environment=Environment(store)
    self.assertEqual(recover(store,environment,capture,source,baseline,check,'campaign','source',{},verification=visual),(capture,source,baseline,check));self.assertEqual(environment.calls,[])
