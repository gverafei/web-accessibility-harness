import tempfile
import unittest
from harness.store import Store
from harness.contracts import ContractError
from harness.evaluator_recovery import authorize, validate


class InstrumentRecoveryTests(unittest.TestCase):
    def test_changed_runtime_requires_matching_unchanged_source_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.append('campaign', {'frozen_source_binding':{'audit_id':'before'}}, ident='campaign')
            store.append('evaluator_snapshot', {'source_files': {'old': 'hash'}}, 'campaign',
                         'campaign-evaluator-runtime')
            before = {'status':'completed', 'axe':2, 'lighthouse':98,
                      'replay': {'input_document_sha256':'same-source'}}
            store.append('audit', before, 'campaign', 'before')
            store.append('audit', before, 'calibration', 'after')
            current = {'source_files': {'new':'hash'}}
            revision = authorize(store, 'campaign', current, 'before', 'after', 'Detector cycle fix')
            self.assertEqual(validate(store, 'campaign', revision['id'], current),
                             {'source_files': {'old':'hash'}})
            with self.assertRaises(ContractError):
                validate(store, 'campaign', revision['id'], {'source_files': {'third':'hash'}})
            for field, value in [('axe', 3), ('replay', {'input_document_sha256':'changed'})]:
                changed = {**before, field:value}
                bad = store.append('audit', changed, 'calibration')
                with self.assertRaises(ContractError):
                    authorize(store, 'campaign', current, 'before', bad['id'], 'Invalid calibration')
