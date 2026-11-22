"""Rendered targets must not masquerade as editable static selectors."""
import copy
import json
import unittest
from hashlib import sha256
from harness.source_bound_repair import bindings, VERSION
from harness.dynamic_objectives import repair_work, work_messages
from harness.planning_evidence import expanded_feedback


class SourceBoundRepairTests(unittest.TestCase):
    def test_rendered_only_target_is_explicitly_unresolved_without_hiding_it(self):
        source = '<button id="filter">All products</button><p id="text">Read</p>'
        evidence = {'failed_opportunities': [
            {'type': 'color-contrast', 'target': ['.selected']},
            {'type': 'color-contrast', 'target': ['#text']}], 'unresolved_prior_findings': []}
        before = copy.deepcopy(evidence)
        work = repair_work(evidence, {}, version=VERSION, editable_source=source)
        messages = work_messages(work)
        payload = json.loads(messages[1]['content'].split('\n',1)[1])
        self.assertEqual(expanded_feedback(payload['evidence']), evidence)
        actual = payload['editable_source_bindings']
        self.assertEqual(actual['document_sha256'], sha256(source.encode()).hexdigest())
        self.assertEqual(actual['findings'][0]['status'], 'no_match')
        self.assertEqual(actual['findings'][0]['editable_selectors'], [])
        self.assertEqual(actual['findings'][1]['editable_selectors'], ['#text'])
        self.assertEqual(evidence, before)
        self.assertIn('Do not copy unresolved', messages[0]['content'])

    def test_exact_identity_resolves_without_using_a_stale_recorded_selector(self):
        source = '<a id="link" href="/read">Read</a>'
        finding = {'target': ['.old-selector'], 'context': {'element': {
            'tag': 'a', 'attributes': {'id': 'link', 'href': '/read'}, 'text': 'Read'}}}
        row = bindings({'failed_opportunities': [finding]}, source)['findings'][0]
        self.assertEqual(row['status'], 'verified_element')
        self.assertEqual(row['editable_selectors'], ['[id="link"]'])

    def test_ambiguous_changed_nested_invalid_and_missing_targets_stay_unresolved(self):
        source = '<a href="/read">Read</a><a href="/read">Read</a><h2 id="h">New</h2>'
        rows = [
            {'context': {'element': {'tag': 'a', 'attributes': {'href':'/read'}, 'text':'Read'}}},
            {'target': ['#h'], 'context': {'element': {'tag':'h2','attributes':{'id':'h'},'text':'Old'}}},
            {'target': [['iframe', '#a']]}, {'target':['[bad']}, {}]
        result = bindings({'failed_opportunities': rows}, source)
        self.assertTrue(all(not row['editable_selectors'] for row in result['findings']))
        self.assertEqual(bindings({}, None)['status'], 'unavailable')

    def test_different_candidate_is_rebound_and_legacy_payload_is_unchanged(self):
        from harness.adaptive_repair_context import VERSION as LEGACY
        evidence = {'failed_opportunities': [{'target':['.selected'],'type':'color-contrast'}]}
        a = bindings(evidence, '<button>All</button>')
        b = bindings(evidence, '<button class="selected">All</button>')
        self.assertNotEqual(a['document_sha256'], b['document_sha256'])
        self.assertFalse(a['findings'][0]['editable_selectors'])
        self.assertEqual(b['findings'][0]['editable_selectors'], ['.selected'])
        old = repair_work(evidence, {}, version=LEGACY, editable_source='<button>All</button>')
        self.assertNotIn('editable_source_bindings', old)
        self.assertNotIn('editable_source_bindings', work_messages(old)[1]['content'])

    def test_roles_share_findings_but_receive_distinct_output_contracts(self):
        from harness.source_bound_repair import CURRENT_VERSION
        evidence = {'failed_opportunities': [{'target':['#x'],'type':'link-name'}]}
        work = repair_work(evidence, {}, version=CURRENT_VERSION, editable_source='<a id="x">Read</a>')
        rows = {role:work_messages(work,role) for role in
                ('component-planner','repair-diagnostician','repair-generator')}
        self.assertEqual(rows['component-planner'][:2], rows['repair-generator'][:2])
        self.assertIn('COMPONENT PLANNING', rows['component-planner'][-1]['content'])
        self.assertIn('does not execute operations', rows['component-planner'][-1]['content'])
        self.assertIn('REPAIR DIAGNOSIS', rows['repair-diagnostician'][-1]['content'])
        self.assertIn('REPAIR GENERATION', rows['repair-generator'][-1]['content'])
        self.assertEqual(len(work_messages(repair_work(evidence,{},version=VERSION,editable_source='<a id="x">Read</a>'))),2)

    def test_component_output_schema_cannot_accept_saved_operation_only_response(self):
        from harness.source_bound_repair import component_output_format
        from remediation_planner import validate_component_plan
        format = component_output_format()
        self.assertEqual(format['type'], 'json_schema')
        schema = format['json_schema']['schema']
        self.assertTrue(format['json_schema']['strict'])
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('components', schema['required'])
        bad = {'operations': [], 'root_causes': [], 'rationale': 'No permission'}
        self.assertFalse(set(schema['required']) <= set(bad))
        with self.assertRaises(ValueError):
            validate_component_plan(bad, [], patch_only=True)
        good = {'components': [], 'rationale': 'No supported component work'}
        self.assertEqual(validate_component_plan(good, [], patch_only=True), [])
