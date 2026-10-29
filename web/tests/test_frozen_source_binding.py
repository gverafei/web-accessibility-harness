import hashlib
import tempfile
import unittest

from harness.contracts import ContractError, digest
from harness.source_binding import resolve, VERSION
from harness.store import Store


class FrozenSourceBindingTests(unittest.TestCase):
    def records(self, directory):
        store = Store(directory)
        source = store.blob('<main>Frozen content</main>', 'source')
        rendered = store.blob('<html><body>Frozen content</body></html>', 'rendered')
        capture = store.append('capture', {'replay_source_id': source['id'], 'package_sha256': 'package'})
        audit = store.append('audit', {'status': 'completed', 'artifacts': {'rendered': rendered['id']}})
        replay = store.append('replay_admission', {'status': 'admitted', 'capture_id': capture['id'], 'audit_id': audit['id']})
        binding = {'version': VERSION, 'sql_source_id': 7, 'evaluator_runtime_sha256': digest({'version': 1}),
                   'capture_id': capture['id'], 'audit_id': audit['id'], 'replay_id': replay['id'],
                   'source_artifact_id': source['id'], 'native_package_sha256': 'package',
                   'input_sha256': hashlib.sha256(store.read_blob(source['id'])).hexdigest(),
                   'reference_document_sha256': hashlib.sha256(store.read_blob(rendered['id'])).hexdigest()}
        return store, binding

    def test_valid_binding_returns_fixed_input_and_same_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            store, binding = self.records(directory)
            before = store.get(binding['capture_id'])
            result = resolve(store, binding, 7, {'version': 1})
            self.assertEqual(result['source'], '<main>Frozen content</main>')
            self.assertEqual(result['baseline']['id'], binding['audit_id'])
            self.assertEqual(store.get(binding['capture_id']), before)

    def test_other_acquisition_and_changed_evaluator_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            store, binding = self.records(directory)
            for source_id, runtime in ((8, {'version': 1}), (7, {'version': 2})):
                with self.assertRaises(ContractError):
                    resolve(store, binding, source_id, runtime)

    def test_source_and_reference_hash_mismatches_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            store, binding = self.records(directory)
            for key in ('input_sha256', 'reference_document_sha256', 'native_package_sha256'):
                invalid = dict(binding, **{key: 'changed'})
                with self.assertRaises(ContractError):
                    resolve(store, invalid, 7, {'version': 1})

    def test_admission_for_another_audit_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            store, binding = self.records(directory)
            unrelated = store.append('replay_admission', {'status': 'admitted', 'capture_id': binding['capture_id'], 'audit_id': 'different'})
            with self.assertRaises(ContractError):
                resolve(store, dict(binding, replay_id=unrelated['id']), 7, {'version': 1})
