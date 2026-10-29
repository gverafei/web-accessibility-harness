import unittest
from unittest.mock import Mock
from harness.engine import active_method, launch
from harness.selection import select
from harness.contracts import ContractError

class DecisionsOnlyMethodTests(unittest.TestCase):
 def test_new_method_rejects_training_and_frozen_parameters(self):
  for extra in ({'mode':'development'},{'mode':'longitudinal'},{'policy_id':'old'}):
   with self.assertRaises(ContractError):active_method({'mode':'frozen','conditions':[],**extra})
  for condition in ({'selector':'linucb'},{'policy_id':'old'},{'memory_policy_id':'old'},{'guidance_policy_id':'old'}):
   with self.assertRaises(ContractError):active_method({'mode':'frozen','conditions':[condition]})
 def test_old_campaign_cannot_resume_before_ledger_or_authorization(self):
  store=Mock();store.get.return_value={'kind':'campaign','data':{'mode':'development','conditions':[]}}
  with self.assertRaises(ContractError):launch(store,'old')
  store.append.assert_not_called();store.checkpoint.assert_not_called()
 def test_selector_rejects_policy_before_provider_call(self):
  provider=Mock();manifest={'workers':[{'id':'saved'}]}
  with self.assertRaises(ContractError):select(provider,'r','k',manifest,{'level':6,'selector':'decisions'},{},{},policy={'id':'old'})
  provider.decisions.assert_not_called()
