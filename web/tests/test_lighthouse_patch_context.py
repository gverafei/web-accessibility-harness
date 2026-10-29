import unittest
from copy import deepcopy
from remediation_content_contract import grounded_lighthouse_context


class LighthousePatchContextTests(unittest.TestCase):
    def test_missing_nodes_are_not_patch_targets_and_raw_input_is_immutable(self):
        findings = [{'audit': 'button-name', 'items': [{'selector': '#missing'}, {'selector': '#real'}]}]
        original = deepcopy(findings)
        result, omitted = grounded_lighthouse_context(findings, '<button id="real">Go</button>')
        self.assertEqual(result[0]['items'], [{'selector': '#real'}])
        self.assertEqual(omitted[0]['selectors'], ['#missing'])
        self.assertEqual(findings, original)

    def test_fully_unmatched_audit_is_removed_only_from_prompt(self):
        result, omitted = grounded_lighthouse_context([{'audit': 'name', 'items': [{'selector': '#missing'}]}], '<p>Text</p>')
        self.assertEqual(result, [])
        self.assertEqual(len(omitted), 1)

    def test_non_node_retained_but_uninterpretable_target_explicitly_omitted(self):
        findings = [{'audit': 'language', 'items': []}, {'audit': 'frame', 'items': [{'selector': '[[invalid'}]}]
        result, omitted = grounded_lighthouse_context(findings, '<p>Text</p>')
        self.assertEqual(result, [findings[0]])
        self.assertEqual(omitted[0]['selectors'], ['[[invalid'])

    def test_unescaped_framework_id_resolves_only_when_exact_node_exists(self):
        finding = {'audit': 'heading-order', 'items': [
            {'selector': 'h3#:dynamic-id:', 'snippet': '<h3 id=":dynamic-id:">'}]}
        original = deepcopy(finding)
        result, omitted = grounded_lighthouse_context([finding], '<h3 id=":dynamic-id:">Title</h3>')
        self.assertEqual(result[0]['items'][0]['selector'], '[id=":dynamic-id:"]')
        self.assertEqual(result[0]['items'][0]['original_selector'], 'h3#:dynamic-id:')
        self.assertEqual(omitted, [])
        self.assertEqual(finding, original)

    def test_invalid_selector_with_absent_or_ambiguous_snippet_id_is_not_actionable(self):
        finding = {'audit': 'heading-order', 'items': [
            {'selector': 'h3#:dynamic-id:', 'snippet': '<h3 id=":dynamic-id:">'}]}
        for source in ('<h3>Other title</h3>',
                       '<h3 id=":dynamic-id:">One</h3><h3 id=":dynamic-id:">Two</h3>',
                       '<button id=":dynamic-id:">Wrong element</button>'):
            result, omitted = grounded_lighthouse_context([finding], source)
            self.assertEqual(result, [])
            self.assertEqual(len(omitted), 1)
