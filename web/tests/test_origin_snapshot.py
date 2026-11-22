import tempfile,unittest,hashlib
from pathlib import Path
from harness.environment import Environment,EnvironmentChanged
from harness.store import Store
class OriginSnapshotTests(unittest.TestCase):
 def test_audit_discards_transport_copy_but_keeps_source_evidence(self):
  from unittest.mock import patch
  from harness.contracts import ContractError
  for fails in (False, True):
   with self.subTest(evaluator_failure=fails), tempfile.TemporaryDirectory() as tmp:
    store = Store(Path(tmp) / 'store')
    env = Environment(store, results=Path(tmp) / 'results')
    source = '<html><body>Stored source</body></html>'
    original = store.blob(source.encode(), 'source', 'campaign', 'text/html')
    capture = {'data': {'captured_url': 'https://example.org/', 'scope': 'frozen', 'assets': []}}
    consumed = []

    def evaluate(endpoint, payload):
     if endpoint == '/harness/validate':
      return {'state': 'passed', 'errors': []}
     path = Path(payload['manifest_path'])
     self.assertIn(source, path.read_text())
     consumed.append(path)
     if fails:
      raise ContractError('Evaluator unavailable')
     return {'results': [{'status': 'completed', 'axe': {'wcag_violations': 0},
                          'lighthouse': {'accessibility_score': 100}}]}

    with patch.object(env, 'verify_runtime'), patch.object(env, 'post', side_effect=evaluate):
     if fails:
      with self.assertRaisesRegex(ContractError, 'Evaluator unavailable'):
       env.audit(capture, source, 'campaign', 'audit', {})
     else:
      audit = env.audit(capture, source, 'campaign', 'audit', {})
      self.assertEqual(audit['data']['lighthouse'], 100)
      self.assertEqual(audit['data']['replay']['input_document_sha256'], hashlib.sha256(source.encode()).hexdigest())
    self.assertEqual(len(consumed), 1)
    self.assertFalse(consumed[0].exists())
    self.assertEqual(store.read_blob(original['id']), source.encode())

 def test_media_frame_reference_is_native_and_never_invented_for_legacy(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   env=Environment(Store(Path(tmp)/'store'),results=Path(tmp)/'results')
   data={'captured_url':'https://example.org/','scope':'frozen','assets':[]}
   reference=[{'position_version':'observed-media-position-v1','current_time':1.25,'paused':True}]
   file,_=env.origin_manifest({'data':{**data,'visible':{'media_descriptors':reference}}},'<html></html>','frames','observed',{})
   self.assertEqual(json.loads(Path(file).read_text())['media_reference'],reference)
   file,_=env.origin_manifest({'data':data},'<html></html>','frames','legacy',{})
   self.assertEqual(json.loads(Path(file).read_text())['media_reference'],[])
 def test_animation_reference_uses_only_observed_native_state(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   env=Environment(Store(Path(tmp)/'store'),results=Path(tmp)/'results')
   data={'captured_url':'https://example.org/','scope':'frozen','assets':[]}
   reference=[{'version':'observed-css-animation-state-v1','path':'html > body:nth-of-type(1)','time':500}]
   file,_=env.origin_manifest({'data':{**data,'visible':{'animation_reference':reference}}},'<html></html>','animation','observed',{})
   self.assertEqual(json.loads(Path(file).read_text())['animation_reference'],reference)
   file,_=env.origin_manifest({'data':data},'<html></html>','animation','legacy',{})
   self.assertEqual(json.loads(Path(file).read_text())['animation_reference'],[])
 def test_manifest_retains_distinct_media_fragments_and_original_ranges(self):
  import json,base64
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');assets=[]
   for start,body in [(0,b'0123'),(8,b'89')]:
    blob=store.blob(body,'resource','','video/webm');assets.append({'url':'https://example.org/movie.webm','mime':'video/webm','sha256':blob['data']['sha256'],'artifact_id':blob['id'],'http_status':206,'headers':{'content-range':f'bytes {start}-{start+len(body)-1}/10'}})
   filename,metadata=Environment(store,results=Path(tmp)/'results').origin_manifest({'data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}},'<html></html>','campaign','ranges',{})
   frozen=json.loads(Path(filename).read_text())['assets']
   self.assertEqual([a['http_status']for a in frozen],[206,206]);self.assertEqual([a['headers']['content-range']for a in frozen],['bytes 0-3/10','bytes 8-9/10'])
   self.assertEqual([base64.b64decode(a['body'])for a in frozen],[b'0123',b'89'])
   self.assertIn('media-ranges-v2',metadata['resource_selection'])
 def test_manifest_preserves_recorded_read_preflights_without_inventing_legacy_permissions(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');env=Environment(store,results=Path(tmp)/'results')
   data={'captured_url':'https://example.org/','scope':'frozen','assets':[]}
   record={'version':'frozen-read-cors-v1','url':'https://api.example.org/data','status':204,
           'request_headers':{'origin':'https://example.org','access-control-request-method':'GET','access-control-request-headers':'x-client'},
           'headers':{'access-control-allow-origin':'https://example.org','access-control-allow-methods':'GET','access-control-allow-headers':'x-client'}}
   filename,_=env.origin_manifest({'data':{**data,'preflights':[record]}},'<html></html>','campaign','new',{})
   self.assertEqual(json.loads(Path(filename).read_text())['preflights'],[record])
   filename,_=env.origin_manifest({'data':data},'<html></html>','campaign','legacy',{})
   self.assertEqual(json.loads(Path(filename).read_text())['preflights'],[])
 def test_manifest_identity_is_frozen_and_resources_keep_original_urls(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'store');body=b'asset';blob=s.blob(body,'resource','','text/css');capture={'id':'capture','data':{'captured_url':'https://example.org/','scope':'frozen','assets':[{'url':'https://example.org/a,b.css','mime':'text/css','sha256':hashlib.sha256(body).hexdigest(),'artifact_id':blob['id']}]}}
   env=Environment(s,results=Path(tmp)/'results');filename,metadata=env.origin_manifest(capture,'<html></html>','campaign','audit',{})
   self.assertEqual(metadata['resource_map']['https://example.org/a,b.css'],'https://example.org/a,b.css');self.assertTrue(Path(filename).exists())
   self.assertEqual(env.origin_manifest(capture,'<html></html>','campaign','audit',{})[0],filename)
   with self.assertRaises(EnvironmentChanged):env.origin_manifest(capture,'changed','campaign','audit',{})
 def test_duplicate_capture_resources_use_explicit_recorded_precedence(self):
  with tempfile.TemporaryDirectory() as tmp:
   import json,base64
   s=Store(Path(tmp)/'store');assets=[]
   for body in (b'first',b'last'):
    blob=s.blob(body,'resource','','text/css');assets.append({'url':'https://example.org/app.css','mime':'text/css','sha256':hashlib.sha256(body).hexdigest(),'artifact_id':blob['id']})
   env=Environment(s,results=Path(tmp)/'results');filename,metadata=env.origin_manifest({'id':'capture','data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}},'html','campaign','audit',{})
   payload=json.loads(Path(filename).read_text());self.assertEqual(len(payload['assets']),1);self.assertEqual(base64.b64decode(payload['assets'][0]['body']),b'last');self.assertEqual(len(metadata['duplicate_resources']),1)

 def test_navigation_history_does_not_conflict_with_injected_document(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');assets=[]
   for url,mime,body,chain in [('https://example.org/','text/html',b'challenge',[]),('https://www.example.org/','text/html',b'page',[{'from':'https://example.org/','to':'https://www.example.org/','status':301,'headers':{}}]),('https://www.example.org/app.css','text/css',b'css',[{'from':'https://example.org/old.css','to':'https://www.example.org/app.css','status':302,'headers':{}}])]:
    blob=store.blob(body,'resource','','text/plain');assets.append({'url':url,'mime':mime,'sha256':hashlib.sha256(body).hexdigest(),'artifact_id':blob['id'],'redirect_chain':chain})
   env=Environment(store,results=Path(tmp)/'results');filename,metadata=env.origin_manifest({'data':{'captured_url':'https://www.example.org/','scope':'frozen','assets':assets}},'<html>candidate</html>','new','audit',{})
   payload=json.loads(Path(filename).read_text());self.assertEqual(payload['document'],'<html>candidate</html>');self.assertEqual(len(payload['assets']),1);self.assertEqual(payload['assets'][0]['redirect_chain'][0]['status'],302);self.assertEqual(len(metadata['excluded_navigation_responses']),2)
   self.assertEqual(store.read_blob(assets[0]['artifact_id']),b'challenge')

 def test_freeze_failure_is_recorded_without_content_rejection(self):
  from unittest.mock import patch
  from harness.contracts import ContractError
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'store');env=Environment(s)
   with patch.object(env,'post',side_effect=ContractError('instrument failure')):
    with self.assertRaises(ContractError):env.freeze_source('http://dataset-server:8080/source','https://example.org/','html',b'html','unused','campaign','capture')
   failure=s.list('acquisition_failure','campaign')[0]['data']
   self.assertEqual(failure['url'],'https://example.org/')
   self.assertIn('no automatic content rejection',failure['scope'])

 def test_design_resources_reuse_verified_blobs_without_network(self):
  import json
  from unittest.mock import Mock,patch
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'store');assets=[]
   for suffix,mime in [('css/bootstrap.min.css','text/css'),('js/bootstrap.bundle.min.js','text/javascript')]:
    raw=suffix.encode();blob=s.blob(raw,'resource','old',mime)
    assets.append({'url':'https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/'+suffix,'mime':mime,'sha256':hashlib.sha256(raw).hexdigest(),'artifact_id':blob['id']})
   s.append('capture',{'assets':assets},'old','old-capture')
   session=Mock();session.get.side_effect=AssertionError('No fresh network request allowed')
   env=Environment(s,session=session)
   html='<html lang="en"><body><p>Test</p></body></html>'
   payload={'network':html,'rendered':html,'captured_url':'https://example.org/','assets':[]}
   with patch.object(env,'file',side_effect=lambda path:json.dumps(payload).encode() if path=='capture' else b'image'):
    result=env.store_capture({'capture_path':'capture','screenshot_path':'image'},'new','new-capture')
    self.assertEqual(result['data']['assets'],[])
    result=env.with_design_resources(result,'new')
   self.assertEqual(result['data']['assets'],[])
   self.assertEqual(result['id'],'new-capture')
   session.get.assert_not_called()

 def test_legacy_resources_survive_runtime_changes_but_not_changed_acquisition(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');screenshot=Path(tmp)/'page.jpg';screenshot.write_bytes(b'original screenshot')
   env=Environment(store);calls=[]
   asset=store.blob(b'css','captured_resource','first','text/css')
   def capture(origin,campaign,ident):
    calls.append(origin)
    return store.append('capture',{'captured_url':origin,'assets':[{'artifact_id':asset['id']}],
      'network_id':asset['id'],'rendered_id':asset['id']},campaign,ident)
   with patch.object(env,'capture',side_effect=capture):
    first=env.freeze_source('internal','https://example.org/','response','rendered',str(screenshot),'first','runtime-one')
    second=env.freeze_source('internal','https://example.org/','response','rendered',str(screenshot),'second','runtime-two')
    self.assertEqual(len(calls),1)
    self.assertEqual(first['data']['recovery_capture_id'],second['data']['recovery_capture_id'])
    changed=env.freeze_source('internal','https://example.org/','changed response','rendered',str(screenshot),'third','runtime-three')
    self.assertEqual(len(calls),2)
    self.assertNotEqual(first['data']['recovery_capture_id'],changed['data']['recovery_capture_id'])
    self.assertEqual(screenshot.read_bytes(),b'original screenshot')
    from harness.contracts import ContractError
    (store.root/'blobs'/asset['data']['sha256']).unlink()
    with self.assertRaisesRegex(ContractError,'explicit recovery required'):
     env.freeze_source('internal','https://example.org/','response','rendered',str(screenshot),'fourth','runtime-four')
    self.assertEqual(len(calls),2)

 def test_opaque_browser_resources_are_preserved_as_evidence_not_network_entries(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');body=b'self.onmessage=()=>{}';blob=store.blob(body,'native_worker','','text/javascript')
   asset={'url':'blob:https://example.org/old-realm-id','mime':'text/javascript','sha256':hashlib.sha256(body).hexdigest(),'artifact_id':blob['id']}
   capture={'id':'capture','data':{'captured_url':'https://example.org/','scope':'frozen','assets':[asset]}}
   filename,metadata=Environment(store,results=Path(tmp)/'results').origin_manifest(capture,'<html><body>Content</body></html>','campaign','audit',{})
   self.assertEqual(json.loads(Path(filename).read_text())['assets'],[])
   self.assertEqual(metadata['excluded_ephemeral_resources'][0]['sha256'],asset['sha256'])
   self.assertEqual(store.read_blob(blob['id']),body)
   self.assertEqual(capture['data']['assets'],[asset])

 def test_identical_resource_keeps_all_recorded_aliases_without_extra_body_bytes(self):
  import json,base64,copy
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');raw=b'#EXTM3U\n#EXT-X-ENDLIST\n';blob=store.blob(raw,'resource','','application/vnd.apple.mpegurl')
   base={'url':'https://cdn.example.org/master','mime':'application/vnd.apple.mpegurl','sha256':blob['data']['sha256'],'artifact_id':blob['id'],'http_status':200,'headers':{'access-control-allow-origin':'*'}}
   chain=lambda name:[{'from':'https://example.org/'+name,'to':base['url'],'status':302,'headers':{'access-control-allow-origin':'https://example.org'}}]
   assets=[{**base,'redirect_chain':chain('native')},{**base,'redirect_chain':chain('alternate')},{**base,'redirect_chain':[]}];original=copy.deepcopy(assets)
   env=Environment(store,results=Path(tmp)/'results');file,meta=env.origin_manifest({'data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}},'html','aliases','same',{})
   saved=json.loads(Path(file).read_text())['assets'];self.assertEqual(len(saved),1);self.assertEqual(base64.b64decode(saved[0]['body']),raw);self.assertEqual(saved[0]['additional_redirect_chains'],[chain('native'),chain('alternate')]);self.assertEqual(assets,original)
   self.assertEqual(meta['redirect_alias_policy'],'identical-recorded-resource-chains-v1')
   # Another body's route or another original response permission must not be carried over.
   different=store.blob(b'other','resource','','application/vnd.apple.mpegurl')
   unsafe=[{**assets[0],'sha256':different['data']['sha256'],'artifact_id':different['id']},{**assets[1],'headers':{'access-control-allow-origin':'https://different.example'}},assets[2]]
   file,_=env.origin_manifest({'data':{'captured_url':'https://example.org/','scope':'frozen','assets':unsafe}},'html','aliases','different',{})
   self.assertEqual(json.loads(Path(file).read_text())['assets'][0]['additional_redirect_chains'],[])

 def test_decoded_response_preserves_native_wire_evidence_and_excludes_unmapped_partial(self):
  import json,copy
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');blob=store.blob(b'decoded entity','resource','','text/plain')
   rep={'version':'browser-response-body-v1','kind':'decoded_complete_entity','logical_bytes':14,'native_http_status':206,'native_headers':{'content-encoding':'gzip','content-range':'bytes 0-4/5'},'wire_range_bytes':5}
   full={'url':'https://example.org/full','mime':'text/plain','sha256':blob['data']['sha256'],'artifact_id':blob['id'],'http_status':200,'headers':{},'body_representation':rep}
   partial={**full,'url':'https://example.org/partial','http_status':206,'body_representation':{**rep,'kind':'unsupported_encoded_range'}};assets=[full,partial];before=copy.deepcopy(assets)
   filename,meta=Environment(store,results=Path(tmp)/'results').origin_manifest({'data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}},'html','body','wire',{})
   saved=json.loads(Path(filename).read_text())['assets'];self.assertEqual(len(saved),1);self.assertEqual(saved[0]['body_representation'],rep);self.assertEqual(assets,before);self.assertEqual(meta['excluded_unmapped_encoded_ranges'][0]['sha256'],partial['sha256']);self.assertEqual(meta['excluded_unmapped_encoded_ranges'][0]['body_representation'],partial['body_representation'])

 def test_latest_native_hls_uses_response_ordinals_and_retains_observed_routes(self):
  import json,copy,base64
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');url='https://cdn.example.org/master';src='https://example.org/player'
   def record(raw,seq,chain):
    b=store.blob(raw,'resource','','application/vnd.apple.mpegurl')
    return {'url':url,'mime':'application/vnd.apple.mpegurl','sha256':b['data']['sha256'],'artifact_id':b['id'],'http_status':200,'headers':{'access-control-allow-origin':'*'},'redirect_chain':chain,'native_response_sequence':seq,'body_representation':{'kind':'browser_response_entity'}}
   chain=[{'from':src,'to':url,'status':302,'headers':{'access-control-allow-origin':'https://example.org'}}]
   first=record(b'#EXTM3U\noriginal.ts\n',1,chain);later=record(b'#EXTM3U\nlater.ts\n',2,[]);recovery=record(b'#EXTM3U\nrecovery.ts\n',None,[]);assets=[later,first,recovery];before=copy.deepcopy(assets)
   data={'captured_url':'https://example.org/','scope':'frozen','assets':assets};env=Environment(store,results=Path(tmp)/'results')
   file,meta=env.origin_manifest({'data':data},'html','native','selected',{})
   saved=json.loads(Path(file).read_text())['assets'][0];self.assertEqual(saved['sha256'],later['sha256']);self.assertEqual(base64.b64decode(saved['body']),b'#EXTM3U\nlater.ts\n');self.assertEqual(saved['additional_redirect_chains'],[chain]);self.assertEqual(assets,before);self.assertEqual(meta['native_hls_selections'][0]['native_response_sequence'],2)
   # Legacy records retain their existing behavior without guessed chronology.
   legacy=[{k:v for k,v in r.items()if k!='native_response_sequence'}for r in [first,later]]
   file,_=env.origin_manifest({'data':{**data,'assets':legacy}},'html','legacy','unchanged',{})
   saved=json.loads(Path(file).read_text())['assets'][0];self.assertEqual(saved['sha256'],later['sha256']);self.assertEqual(saved['additional_redirect_chains'],[])
   incompatible=[later,{**first,'headers':{'access-control-allow-origin':'https://different.example'}}]
   file,_=env.origin_manifest({'data':{**data,'assets':incompatible}},'html','native','permissions',{})
   self.assertEqual(json.loads(Path(file).read_text())['assets'][0]['additional_redirect_chains'],[])

 def test_duplicate_native_hls_ordinals_are_not_resolved_by_guessing(self):
  from harness.contracts import ContractError
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');assets=[]
   for raw in [b'#EXTM3U\nfirst.ts\n',b'#EXTM3U\nsecond.ts\n']:
    b=store.blob(raw,'resource','','application/vnd.apple.mpegurl');assets.append({'url':'https://example.org/master','mime':'application/vnd.apple.mpegurl','sha256':b['data']['sha256'],'artifact_id':b['id'],'http_status':200,'headers':{},'native_response_sequence':1,'body_representation':{'kind':'browser_response_entity'}})
   with self.assertRaisesRegex(ContractError,'Ambiguous native response sequence'):
    Environment(store,results=Path(tmp)/'results').origin_manifest({'data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}},'html','ambiguous','nochoice',{})

 def test_css_transport_retains_complete_observed_header_variants_for_identical_bytes(self):
  import json,base64
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'store');assets=[]
   for mime,body,headers in [
    ('text/css',b'old',{'access-control-allow-origin':'https://other.test'}),
    ('text/css',b'current',{'access-control-allow-origin':'https://example.org'}),
    ('text/css',b'current',{}),
    ('text/css',b'current',{}),
    ('text/javascript',b'script',{'access-control-allow-origin':'https://example.org'}),
    ('text/javascript',b'script',{}),
   ]:
    blob=store.blob(body,'resource','source',mime)
    assets.append({'url':'https://cdn.example.org/'+('app.css' if mime=='text/css' else 'app.js'),
                   'mime':mime,'sha256':blob['data']['sha256'],'artifact_id':blob['id'],
                   'http_status':200,'headers':headers,'native_response_sequence':len(assets)+1})
   capture={'data':{'captured_url':'https://example.org/','scope':'frozen','assets':assets}}
   filename,metadata=Environment(store,results=Path(tmp)/'results').origin_manifest(capture,'<html></html>','variants','audit',{})
   frozen=json.loads(Path(filename).read_text())['assets']
   css=[a for a in frozen if a['mime']=='text/css']
   self.assertEqual(len(css),2)
   self.assertEqual([base64.b64decode(a['body']) for a in css],[b'current',b'current'])
   self.assertEqual([a['headers'] for a in css],[{'access-control-allow-origin':'https://example.org'},{}])
   self.assertEqual([a['native_response_sequence'] for a in css],[2,3])
   self.assertEqual([a['headers'] for a in frozen if a['mime']=='text/javascript'],[{}])
   self.assertIn('css-header-variants-v1',metadata['resource_selection'])
   self.assertEqual(store.read_blob(assets[0]['artifact_id']),b'old')
