"""Frozen experimental endpoint routing remains explicit and reproducible."""
import copy
import unittest
from harness.contracts import ContractError, model_snapshot
from harness.providers import bind_provider_route

class FrozenProviderRouteTests(unittest.TestCase):
    def setUp(self):
        self.model = {'id':'openai/gpt-6.1-sol@high','model':'openai/gpt-6.1-sol',
                      'input_usd_per_million':1,'output_usd_per_million':5,
                      'provider_route':{'only':['openai/flex'],'allow_fallbacks':False,
                                        'require_parameters':True,
                                        'max_price':{'prompt':2,'completion':7.5}}}

    def test_snapshot_retains_route_and_separates_its_identity(self):
        frozen = model_snapshot(self.model)
        self.assertEqual(frozen['provider_route'], self.model['provider_route'])
        other = copy.deepcopy(self.model)
        other['provider_route']['only'] = ['openai']
        self.assertNotEqual(model_snapshot(other)['digest'], frozen['digest'])

    def test_route_is_bound_without_changing_messages_or_original_body(self):
        body = {'messages':[{'role':'user','content':'source'}], 'reasoning':{'effort':'high'}}
        before = copy.deepcopy(body)
        routed = bind_provider_route(body, model_snapshot(self.model))
        self.assertEqual(body, before)
        self.assertEqual(routed['reasoning'], {'effort':'high'})
        self.assertEqual(routed['provider']['only'], ['openai/flex'])
        self.assertIs(routed['provider']['allow_fallbacks'], False)

    def test_conflicting_route_and_fallback_cannot_silently_change_endpoint(self):
        with self.assertRaises(ContractError):
            bind_provider_route({'provider':{'only':['other']}}, model_snapshot(self.model))
        for change in [{'allow_fallbacks':True}, {'only':[]}, {'only':['https://bad.example']}, {'extra':1}]:
            model = copy.deepcopy(self.model)
            model['provider_route'].update(change)
            with self.assertRaises(ContractError):
                model_snapshot(model)

    def test_unconfigured_models_preserve_their_existing_request(self):
        body = {'model':'worker','messages':[]}
        self.assertIs(bind_provider_route(body, {}), body)
