import copy
import unittest

import test_harness
from harness.contracts import ContractError
from harness.engine import create_campaign
from harness.providers import BudgetStop, Ledger
from harness.shared_budget import effective_group, record_increase


class SharedBudgetIncreaseTest(unittest.TestCase):
    def setUp(self):
        fixture = test_harness.HarnessTest()
        fixture.setUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.store = fixture.store
        value = copy.deepcopy(fixture.manifest)
        value['budget_group'] = {'id': 'shared', 'stage': 'matrix', 'total_usd': .3,
                                 'stage_limits': {'matrix': .1, 'other': .2}}
        self.first = create_campaign(self.store, value)
        self.second = create_campaign(self.store, value)
        self.group = self.first['data']['budget_group']
        self.ledger = Ledger(self.store)
        self.model = self.first['data']['workers'][0]
        call, _ = self.ledger.begin(self.first['id'], 'run', 'repair', 'old', {},
            self.model, self.first['data']['repair_budget'], 5, self.group)
        self.ledger.received(call, '{"model":"family0/worker","usage":'
            '{"prompt_tokens":1,"completion_tokens":1,"cost":0.08}}', self.model, 0, 200)

    def reserve(self, key):
        return self.ledger.begin(self.second['id'], 'run', 'repair', key, {},
            dict(self.model, input_usd_per_million=30),
            self.second['data']['repair_budget'], 5, self.group)

    def test_authorized_increase_preserves_prior_charge_and_new_ceiling(self):
        with self.assertRaisesRegex(BudgetStop, 'Shared stage'):
            self.reserve('before')
        record_increase(self.store, 'shared', .4, {'matrix': .2, 'other': .2},
                        'Human requested an additional 0.1 USD')
        call, fresh = self.reserve('after')
        self.assertTrue(fresh)
        self.ledger.received(call, '{"model":"family0/worker","usage":'
            '{"prompt_tokens":1,"completion_tokens":1,"cost":0.10}}', self.model, 0, 200)
        with self.assertRaisesRegex(BudgetStop, 'Shared stage'):
            self.reserve('over')
        self.assertEqual(self.ledger.rows(self.first['id'])[0]['cost'], .08)
        self.assertEqual(self.store.get(self.first['id']), self.first)

    def test_increase_requires_reference_and_monotonic_limits(self):
        for total, stages, reference in ((.4, {'matrix': .2, 'other': .2}, ''),
                (.2, {'matrix': .1, 'other': .1}, 'human'),
                (.4, {'matrix': .35, 'other': .05}, 'human')):
            with self.assertRaises(ContractError):
                record_increase(self.store, 'shared', total, stages, reference)
        self.assertFalse(self.store.list('shared_budget_amendment'))

    def test_unrelated_group_and_broken_chain_cannot_extend_budget(self):
        record = record_increase(self.store, 'shared', .4, {'matrix': .2, 'other': .2}, 'human')
        unrelated = dict(self.group, id='other')
        self.assertEqual(effective_group(unrelated, [record]), unrelated)
        with self.assertRaises(ContractError):
            effective_group(self.group, [record, record])
