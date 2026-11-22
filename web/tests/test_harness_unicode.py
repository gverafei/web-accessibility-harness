"""Browser UTF-16 evidence must round-trip without loss or historical hash drift."""
import hashlib
import json
import tempfile
import unittest
from harness.contracts import canonical, digest
from harness.store import Store


class BrowserUnicodeEvidenceTests(unittest.TestCase):
    def test_scalar_unicode_keeps_existing_canonical_bytes_and_digest(self):
        value = {'texto': 'Español 中文 🌐', 'escaped': r'\ud83c', 'nested': [0, True, None]}
        previous = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        self.assertEqual(canonical(value), previous)
        self.assertEqual(digest(value), hashlib.sha256(previous.encode()).hexdigest())

    def test_lone_code_units_are_preserved_in_keys_and_nested_values(self):
        value = {'label': 'x' * 161 + '\ud83c', '\udc00': ['\ud800', 'tail\udfff']}
        encoded = canonical(value).encode('utf-8')
        self.assertEqual(json.loads(encoded), value)
        self.assertIn(b'\\ud83c', encoded)
        self.assertNotIn(b'\xef\xbf\xbd', encoded)

    def test_valid_utf16_pair_has_the_same_hash_as_its_scalar(self):
        pair = {'label': '\ud83c\udf10'}
        scalar = {'label': '🌐'}
        self.assertEqual(canonical(pair), canonical(scalar))
        self.assertEqual(digest(pair), digest(json.loads(canonical(pair))))

    def test_store_round_trip_preserves_lone_surrogate_and_validates_hash(self):
        value = {'label': 'control\ud83c', 'nested': ['\udc00', '🌐']}
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            record = store.append('capture', value, 'unicode-fixture', 'unicode-fixture')
            self.assertEqual(record['data']['label'], value['label'])
            self.assertEqual(store.get(record['id'])['hash'], record['hash'])
            self.assertEqual(store.list('capture')[0]['data']['nested'], value['nested'])

    def test_bundle_preserves_truncated_utf16_text_and_valid_references(self):
        import io,zipfile
        from harness.export import bundle
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            corpus=store.append('corpus',{'items':[]},ident='unicode-corpus')
            campaign=store.append('campaign',{'corpus_id':corpus['id'],'policy_id':None,'conditions':[],'workers':[],'partition':'test','source':{'count':0},'capture_only':True,'repetitions':1,'analysis':{'contrasts':[]}},ident='unicode-campaign')
            artifact=store.blob(b'Native body intact','captured_resource',campaign['id'])
            text='x'*161+'\ud83c'
            store.append('capture',{'label':text,'resource_id':artifact['id']},campaign['id'],'unicode-capture')
            payload=bundle(store,campaign['id'],True)
            with zipfile.ZipFile(io.BytesIO(payload))as archive:
                records=json.loads(archive.read('records.json'))
                capture=next(r for r in records if r['id']=='unicode-capture')
                self.assertEqual(capture['data']['label'],text)
                self.assertIn(artifact['id'],capture['data']['resource_id'])
                self.assertTrue(any(archive.read(name)==b'Native body intact'for name in archive.namelist()if name.startswith('blobs/')))

    def test_nonfinite_numbers_still_rejected(self):
        with self.assertRaises(ValueError):
            canonical({'score': float('nan')})

    def test_corrected_candidate_and_sql_history_are_available_only_in_private_bundle(self):
        import io,zipfile
        from harness.export import bundle
        with tempfile.TemporaryDirectory()as folder:
            store=Store(folder);corpus=store.append('corpus',{'items':[]})
            campaign=store.append('campaign',{'corpus_id':corpus['id'],'conditions':[],'workers':[],
                'partition':'test','source':{'count':0},'capture_only':True,'repetitions':1,'analysis':{'contrasts':[]}})
            candidate=store.blob(b'<main>Corrected paid candidate</main>','corrected_existing_paid_candidate',campaign['id'])
            journal=store.append('sql_correction_archive',{'source_id':candidate['id'],'original_prompt':'Private captured HTML'},campaign['id'])
            for private in (False,True):
                with zipfile.ZipFile(io.BytesIO(bundle(store,campaign['id'],private)))as z:
                    records=json.loads(z.read('records.json'));self.assertEqual(journal['id']in {r['id']for r in records},private)
                    self.assertEqual(any(name.startswith('blobs/')for name in z.namelist()),private)
