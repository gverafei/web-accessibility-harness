import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness.providers import Ledger, Providers, BudgetStop, UncertainCall
from harness.store import Store, Conflict
from harness.time_policy import ITERATION_BOUNDARY, effective_limits
from harness.remediation_bridge import Bridge
from accessibility_taxonomy.assessment import measure_pair
from accessibility_taxonomy.checkpoints import assessment_checkpoint, save_assessment


class IterationTimePolicyTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=Store(directory.name)
        self.limits={'max_seconds':900,'max_calls':2,'max_cost_usd':5,'max_call_cost_usd':5}
        self.manifest={'time_policy':ITERATION_BOUNDARY,'repair_budget':self.limits,
                       'review_budget':self.limits,'campaign_cost_limit':5}
        self.model={'model':'fixture','context_length':10000,'input_usd_per_million':1,
                    'output_usd_per_million':1}

    def test_clock_exception_requires_explicit_policy_and_active_stage(self):
        self.assertIs(effective_limits(self.limits,{},'iteration'),self.limits)
        self.assertIs(effective_limits(self.limits,self.manifest,None),self.limits)
        completed=effective_limits(self.limits,self.manifest,'iteration')
        self.assertEqual({k:v for k,v in completed.items()if k!='max_seconds'},
                         {k:v for k,v in self.limits.items()if k!='max_seconds'})
        self.assertEqual(self.limits['max_seconds'],900)

    def test_expired_clock_allows_active_stage_but_call_and_money_guards_remain(self):
        ledger=Ledger(self.store);body={'messages':[{'role':'user','content':'test'}],'max_tokens':1}
        first,_=ledger.begin('campaign','run','review','first',body,self.model,self.limits,5)
        ledger.reconcile(first['id'],0,'synthetic test: no HTTP')
        with self.store.connect()as db:db.execute('UPDATE calls SET created=?',(time.time()-1000,))
        with self.assertRaises(BudgetStop):ledger.begin('campaign','run','review','hard',body,self.model,self.limits,5)
        limits=effective_limits(self.limits,self.manifest,'taxonomy')
        with self.assertRaises(BudgetStop):ledger.begin('campaign','run','review','money',body,self.model,{**limits,'max_cost_usd':0},5)
        second,_=ledger.begin('campaign','run','review','second',body,self.model,limits,5)
        ledger.reconcile(second['id'],0,'synthetic test: no HTTP')
        with self.assertRaises(BudgetStop):ledger.begin('campaign','run','review','third',body,self.model,limits,5)
        self.assertEqual(len(ledger.rows()),2)

    def test_expired_start_budget_stops_before_selector_or_worker(self):
        bridge=Bridge.__new__(Bridge)
        bridge.providers=SimpleNamespace(completion_stage='iteration')
        bridge.manifest=self.manifest;bridge.state={'started':time.time()-1000}
        self.assertEqual(bridge.begin_iteration(2),(None,None))
        self.assertIsNone(bridge.providers.completion_stage)

    def test_campaign_money_context_and_unresolved_receipts_still_block(self):
        ledger=Ledger(self.store);body={'messages':[{'role':'user','content':'test'}],'max_tokens':1}
        limits=effective_limits(self.limits,self.manifest,'iteration')
        with self.assertRaises(BudgetStop):ledger.begin('campaign','run','repair','campaign-cost',body,self.model,limits,0)
        with self.assertRaises(BudgetStop):ledger.begin('campaign','run','repair','context',body,{**self.model,'context_length':1},limits,5)
        first,_=ledger.begin('campaign','run','repair','dispatching',body,self.model,limits,5)
        with self.assertRaises(UncertainCall):ledger.begin('campaign','run','repair','another',body,self.model,limits,5)
        self.assertEqual(len(ledger.rows()),1)

    def test_active_stage_cannot_take_another_workers_lease(self):
        providers=Providers(self.store,self.manifest,'campaign',{})
        providers.lease_owner='mine';self.store.claim('campaign','other',900)
        model={**self.model,'provider':'ollama'}
        with providers.complete_stage('iteration','run'):
            with self.assertRaises(Conflict):providers.dispatch('run','repair','key',model,{},'http://unused')
        self.assertEqual(providers.ledger.rows(),[])

    def test_taxonomy_completes_as_a_stage_and_restores_scope_on_error(self):
        providers=Providers(self.store,self.manifest,'campaign',{})
        def evaluate(*args):
            self.assertEqual(providers.completion_stage,'taxonomy')
            raise RuntimeError('fixture evaluation failure')
        with patch('accessibility_taxonomy.assessment._measure_pair',side_effect=evaluate):
            with self.assertRaises(RuntimeError):measure_pair(self.store,providers,'run',{}, {},'https://example.org',{})
        self.assertIsNone(providers.completion_stage)
        self.assertEqual(self.store.list('time_stage')[0]['data']['run_id'],'run')

    def test_only_time_stopped_checkpoint_can_complete_without_larger_money_budget(self):
        self.store.append('campaign',{'campaign_cost_limit':5},ident='parent')
        original=self.store.append('taxonomy_assessment',{'errors':['Provider account time limit reached']},'parent','partial')
        providers=SimpleNamespace(manifest=self.manifest,campaign='child')
        saved,ident,parent=assessment_checkpoint(self.store,providers,'partial')
        self.assertIsNone(saved);self.assertEqual(parent,'partial')
        completed=save_assessment(self.store,providers,ident,parent,{'errors':[]})
        self.assertEqual(assessment_checkpoint(self.store,providers,'partial')[0],completed)
        self.assertEqual(self.store.get('partial'),original)
        bad=self.store.append('taxonomy_assessment',{'errors':['Provider returned HTTP 500']},'parent','bad')
        self.assertEqual(assessment_checkpoint(self.store,providers,'bad')[0],bad)


if __name__=='__main__':unittest.main()
