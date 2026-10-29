"""Nested controls remain addressable when presentation markup exhausts excerpts."""
import json
import unittest
from bs4 import BeautifulSoup
from remediation_jobs import repair_context
from harness.html_tools import repair_context as native_context
from remediation_interventions import approach, VERSION
from remediation_patch_prompt import patch_prompt

class ControlContextTests(unittest.TestCase):
    def test_truncated_markup_retains_verified_controls_with_duplicate_ids(self):
        source='<html><body><button id="same">Other</button><x-group id="expand" role="button">'
        source+='<!--decoration-->'*200
        source+='<a id="same" tabindex="-1"><x-item role="link" tabindex="0">Show more</x-item></a></x-group></body></html>'
        findings=[{'id':'nested-interactive','nodes':[{'target':['#expand']}]}]
        data=json.loads(repair_context(source,findings,[]));node=data['affected_nodes'][0]
        self.assertTrue(node['html_truncated']);self.assertEqual(len(node['interactive_descendants']),2)
        soup=BeautifulSoup(source,'html.parser')
        for child in node['interactive_descendants']:
            matched=soup.select(child['selector']);self.assertEqual(len(matched),1)
            self.assertEqual(matched[0].name,child['element'])
        self.assertEqual(data,json.loads(native_context(source,findings,[])))
        prompt=patch_prompt(json.dumps(data),findings,[],'',approach(1,VERSION),'Preserve',1,10)
        self.assertIn('redundant interactive role',prompt)
        self.assertIn('negative tabindex alone does not repair',prompt)

    def test_measured_control_context_precedes_unrelated_overview_under_budget(self):
        source='<html><body><main>'+('unrelated '*2000)+'</main><div id="target" role="button">'
        source+='<span tabindex="0" role="button">Open</span></div></body></html>'
        text=repair_context(source,[{'nodes':[{'target':['#target']}]}],[],limit=3500)
        data=json.loads(text);self.assertLessEqual(len(text),3500)
        self.assertEqual(len(data['affected_nodes']),1)
        self.assertEqual(data['affected_nodes'][0]['interactive_descendants'][0]['text'],'Open')

    def test_repeated_attribute_and_css_repairs_are_reported_unchanged(self):
        from remediation_jobs import apply_repair_plan
        from harness.html_tools import apply_repair_plan as native_apply
        from remediation_completion import measurable_noop
        source='<html><head></head><body><button id="go" aria-labelledby="missing">Open</button></body></html>'
        plan={'operations':[
            {'action':'set_attribute','selector':'#go','name':'lang','value':'en'},
            {'action':'remove_attribute','selector':'#go','name':'aria-labelledby'},
            {'action':'append_css','selector':'#go','css':'#go { color: #112233; }'}]}
        first,receipt=apply_repair_plan(source,plan)
        self.assertEqual(len(receipt['applied']),3)
        second,receipt=native_apply(first,plan)
        self.assertEqual(first,second)
        self.assertTrue(measurable_noop(receipt))
        self.assertEqual(len(receipt['unchanged']),3)

    def test_two_empty_patches_stop_before_another_paid_decision_or_generation(self):
        from harness.remediation_bridge import Bridge
        from unittest.mock import Mock
        bridge=Bridge.__new__(Bridge)
        bridge.state={'empty_patch_count':2}
        bridge.manifest={'attempt_limit':10}
        bridge.persist=Mock()
        bridge.perform=Mock(side_effect=AssertionError('No paid task after empty plateau'))
        self.assertEqual(bridge.begin_iteration(3),(None,None))
        bridge.persist.assert_called_once()
        bridge.perform.assert_not_called()
