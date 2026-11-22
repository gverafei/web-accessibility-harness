import tempfile
import unittest
from types import SimpleNamespace
import requests
from harness.store import Store
from harness.providers import Providers


class PartialTransportTests(unittest.TestCase):
    def test_incomplete_bytes_are_saved_without_becoming_a_model_response(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            provider = Providers(store, {}, 'campaign', {})
            def chunks(**kwargs):
                yield b'{"choices":[{"message":{"content":"partial'
                raise requests.exceptions.ChunkedEncodingError('disconnected')
            response = SimpleNamespace(iter_content=chunks, encoding='utf-8')
            with self.assertRaises(requests.exceptions.ChunkedEncodingError):
                provider.read_response(response, {'campaign':'campaign','id':'call'})
            receipt = store.list('provider_partial_response','campaign')[0]['data']
            self.assertFalse(receipt['complete'])
            self.assertFalse(receipt['response_interpreted'])
            self.assertEqual(store.read_blob(receipt['artifact_id']),
                             b'{"choices":[{"message":{"content":"partial')
            self.assertFalse(store.list('provider_response', 'campaign'))
