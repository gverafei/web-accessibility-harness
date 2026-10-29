import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from harness.environment import Environment
from harness.store import Store
from harness.contracts import ContractError

class MseReferenceTests(unittest.TestCase):
 def test_derived_bytes_are_separate_blobs_and_rehydrated_without_inventing_legacy(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);env=Environment(Store(root/'store'),results=root)
   raw=b'observed append bytes';sha=hashlib.sha256(raw).hexdigest()
   bundle={'version':'observed-mse-buffer-bytes-v1','scope':'browser_derived_window_mse','total_bytes':len(raw),'records':[{'buffers':[{'appends':[{'body':base64.b64encode(raw).decode(),'sha256':sha,'byte_length':len(raw)}]}]}],'targets':[]}
   file=root/'capture.json';screenshot=root/'capture.jpg';screenshot.write_bytes(b'image')
   file.write_text(json.dumps({'network':'<html><body>Source</body></html>','rendered':'<html><body>Source</body></html>','captured_url':'https://example.org/','assets':[],'scope':'native test fixture','visible':{},'mse_buffer_reference':bundle}))
   stored=env.store_capture({'capture_path':str(file),'screenshot_path':str(screenshot)},'mse','native')
   append=stored['data']['mse_buffer_reference']['records'][0]['buffers'][0]['appends'][0]
   self.assertNotIn('body',append);self.assertEqual(env.store.read_blob(append['artifact_id']),raw);self.assertEqual(stored['data']['assets'],[])
   path,_=env.origin_manifest(stored,'<html><body>Source</body></html>','mse','manifest',{})
   restored=json.loads(Path(path).read_text())['mse_buffer_reference']['records'][0]['buffers'][0]['appends'][0]
   self.assertEqual(base64.b64decode(restored['body']),raw);self.assertEqual(restored['sha256'],sha)
   self.assertNotIn('body',append)
   old={'data':{'captured_url':'https://example.org/','assets':[],'scope':'legacy fixture'}}
   path,_=env.origin_manifest(old,'<html></html>','mse','legacy',{})
   self.assertNotIn('mse_buffer_reference',json.loads(Path(path).read_text()))
   append['sha256']='0'*64
   with self.assertRaises(ContractError):env.origin_manifest(stored,'<html></html>','mse','tampered',{})

 def test_oversized_derived_blob_is_rejected_before_manifest_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store=Store(root/'store');env=Environment(store,results=root/'results')
   raw=b'x'*8000001;blob=store.blob(raw,'observed_mse_append','mse','application/octet-stream')
   mse={'records':[{'buffers':[{'appends':[{'artifact_id':blob['id'],'sha256':hashlib.sha256(raw).hexdigest(),'byte_length':len(raw)}]}]}]}
   capture={'data':{'captured_url':'https://example.org/','assets':[],'scope':'native fixture','mse_buffer_reference':mse}}
   with self.assertRaisesRegex(ContractError,'byte limit'):env.origin_manifest(capture,'<html></html>','mse','oversized',{})
   self.assertFalse((root/'results'/'origin_inputs').exists())

 def test_worker_init_bytes_use_separate_verified_blobs_and_immutable_rehydration(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);env=Environment(Store(root/'store'),results=root)
   raw=b'actual observed worker init prefix';sha=hashlib.sha256(raw).hexdigest()
   worker={'records':[{'buffers':[{'body':base64.b64encode(raw).decode(),'sha256':sha,'byte_length':len(raw)}]}],'total_bytes':len(raw)}
   file=root/'capture.json';screenshot=root/'capture.jpg';screenshot.write_bytes(b'image')
   file.write_text(json.dumps({'network':'<html></html>','rendered':'<html></html>','captured_url':'https://example.org/','assets':[],'scope':'synthetic persistence test','visible':{},'worker_media_reference':worker}))
   capture=env.store_capture({'capture_path':str(file),'screenshot_path':str(screenshot)},'worker','native')
   item=capture['data']['worker_media_reference']['records'][0]['buffers'][0]
   self.assertNotIn('body',item)
   self.assertEqual(env.store.read_blob(item['artifact_id']),raw)
   path,_=env.origin_manifest(capture,'<html></html>','worker','manifest',{})
   restored=json.loads(Path(path).read_text())['worker_media_reference']['records'][0]['buffers'][0]
   self.assertEqual(base64.b64decode(restored['body']),raw)
   self.assertNotIn('body',item)
   item['sha256']='0'*64
   with self.assertRaises(ContractError):env.origin_manifest(capture,'<html></html>','worker','tampered',{})
