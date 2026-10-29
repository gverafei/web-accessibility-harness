"""Concurrent known reservations stay bounded; missing receipts forbid replay."""
import copy
import json
import unittest
import budget_fixture as preparation
from harness.providers import BudgetStop, Ledger, UncertainCall

class SharedReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=preparation.PreparationTest();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store=self.fixture.store
        self.first=self.fixture.group_campaign()
        self.second=self.fixture.group_campaign('other')
        self.ledger=Ledger(self.store)
        self.model={**self.first['data']['workers'][0], 'input_usd_per_million': .1, 'output_usd_per_million': .5}
        self.request={'model':self.model['model'],'messages':[{'role':'user','content':'Synthetic'}],'max_tokens':1}

    def begin(self,campaign,key,model=None):
        return self.ledger.begin(campaign['id'],'run','repair',key,self.request,model or self.model,
            campaign['data']['repair_budget'],5,campaign['data']['budget_group'])

    def test_distinct_known_inflight_requests_reserve_before_overlapping(self):
        first,_=self.begin(self.first,'first');second,fresh=self.begin(self.second,'second')
        self.assertTrue(fresh)
        self.assertNotEqual(first['id'],second['id'])
        self.assertTrue(all(c['status']=='dispatching' and c['reserved']>0 for c in self.ledger.rows()))
        with self.assertRaises(UncertainCall):self.begin(self.first,'first')
        with self.assertRaises(UncertainCall):self.begin(self.first,'different-key')
        self.assertEqual(len(self.ledger.rows()),2)

    def test_outstanding_reservations_count_toward_shared_total_and_stage(self):
        expensive=copy.deepcopy(self.model);expensive['input_usd_per_million']=120
        call,_=self.begin(self.second,'first',expensive)
        self.assertGreater(call['reserved'],.1)
        with self.assertRaises(BudgetStop):self.begin(self.first,'stage',expensive)
        third=self.fixture.group_campaign('other')
        with self.assertRaises(BudgetStop):self.begin(third,'total',expensive)
        self.assertEqual(len(self.ledger.rows()),1)

    def test_unknown_charge_keeps_its_reservation_and_blocks_only_its_own_work(self):
        expensive=copy.deepcopy(self.model);expensive['input_usd_per_million']=120
        call,_=self.begin(self.second,'first',expensive)
        self.ledger.failed(call,RuntimeError('lost response'),1)
        with self.assertRaises(UncertainCall):self.begin(self.second,'first',expensive)
        with self.assertRaises(UncertainCall):self.begin(self.second,'different-key')
        with self.assertRaises(BudgetStop):self.begin(self.first,'too-large',expensive)
        second,fresh=self.begin(self.first,'bounded-independent')
        self.assertTrue(fresh)
        self.assertNotEqual(second['id'],call['id'])
        unresolved=self.ledger.rows()[0]
        self.assertIsNone(unresolved['cost'])
        self.assertEqual(unresolved['cost_status'],'unknown')
        self.assertEqual(unresolved['reserved'],call['reserved'])
