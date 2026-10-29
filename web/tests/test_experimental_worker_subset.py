import json
import unittest
from harness.contracts import ContractError
from harness.remediation_bridge import scoped_workers


class WorkerSubsetTests(unittest.TestCase):
    def setUp(self):
        self.choices = [{'id': i, 'model': 'fixture/'+i, 'family': 'fixture',
                         'input_usd_per_million': .1, 'output_usd_per_million': .1}
                        for i in ('light', 'high', 'sol', 'other')]

    def test_subset_freezes_explicit_order_without_changing_saved_catalogue(self):
        before = json.dumps(self.choices, sort_keys=True)
        workers = scoped_workers(self.choices, 'light', json.dumps(['sol', 'high', 'light']))
        self.assertEqual([w['id'] for w in workers], ['sol', 'high', 'light'])
        self.assertEqual(json.dumps(self.choices, sort_keys=True), before)
        self.assertEqual(len(scoped_workers(self.choices, 'light')), 4)

    def test_bad_or_disabled_identity_and_outside_selected_worker_are_rejected(self):
        for ids in ([], ['light', 'light'], ['disabled'], [{}], 'light', None):
            with self.subTest(ids=ids), self.assertRaises(ContractError):
                scoped_workers(self.choices, 'light', json.dumps(ids))
        with self.assertRaises(ContractError):
            scoped_workers(self.choices, 'other', '["light"]')
