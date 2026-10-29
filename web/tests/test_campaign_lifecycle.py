import copy
import unittest
from unittest.mock import patch
import test_harness
from harness import lifecycle
from harness.contracts import ContractError
from harness.engine import create_campaign,launch
from harness.providers import Ledger,BudgetStop
from harness.store import Conflict
from main import create_app

class CampaignLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fixture=test_harness.HarnessTest();self.fixture.setUp();self.addCleanup(self.fixture.tmp.cleanup)
        self.store=self.fixture.store

    def test_removal_preserves_shared_billing_and_blocks_launch(self):
        value=copy.deepcopy(self.fixture.manifest)
        value['budget_group']={'id':'shared','stage':'matrix','total_usd':.3,'stage_limits':{'matrix':.1,'other':.2}}
        old=create_campaign(self.store,value);new=create_campaign(self.store,value)
        ledger=Ledger(self.store);model=old['data']['workers'][0]
        call,_=ledger.begin(old['id'],'run','repair','old',{},model,old['data']['repair_budget'],5,old['data']['budget_group'])
        ledger.received(call,'{"model":"family0/worker","usage":{"prompt_tokens":1,"completion_tokens":1,"cost":0.08}}',model,0,200)
        original=self.store.get(old['id'])
        lifecycle.change(self.store,old['id'])
        self.assertEqual(lifecycle.visible(self.store,'campaign'),[new])
        self.assertEqual(self.store.get(old['id']),original)
        with self.assertRaises(ContractError):launch(self.store,old['id'])
        priced=dict(model,input_usd_per_million=30)
        with self.assertRaisesRegex(BudgetStop,'Shared stage'):
            ledger.begin(new['id'],'run','repair','new',{},priced,new['data']['repair_budget'],5,new['data']['budget_group'])
        lifecycle.change(self.store,old['id'],False)
        self.assertEqual(self.store.checkpoint(old['id'])[0]['status'],'draft')
        self.assertEqual(len(lifecycle.visible(self.store,'campaign')),2)
        self.assertEqual(ledger.rows(old['id'])[0]['cost'],.08)
