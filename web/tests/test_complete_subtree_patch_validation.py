import copy
import json
import unittest

from bs4 import BeautifulSoup

from coordinated_role_validation import LEGACY_VERSION, VERSION
from harness.controller import materialize
from remediation_interventions import VERSION as INTERVENTION_VERSION
from remediation_patch_context import repair_context
from remediation_patch_safety import fully_observed_nodes


class CompleteSubtreePatchTests(unittest.TestCase):
    def setUp(self):
        self.source = ('<html lang="en"><head><title>Example</title></head><body>'
                       '<p>Keep the complete original paragraph.</p></body></html>')
        self.context = repair_context(self.source, [{'nodes': [{'target': ['html']}]}], [])
        self.plan = {
            'operations': [{'action': 'replace_element', 'selector': 'body > p',
                            'html': '<main><p>Keep the complete original paragraph.</p></main>'}],
            'root_causes': [{'id': 'landmark', 'selectors': ['body > p'],
                             'depends_on': [], 'operation_indexes': [0]}],
        }

    def apply(self, version=VERSION, *, context=None, plan=None):
        return materialize(
            self.source, json.dumps(plan or self.plan), 3, 'https://example.org/',
            intervention_version=INTERVENTION_VERSION,
            patch_context=self.context if context is None else context,
            validation_version=version,
        )

    def test_complete_ancestor_proves_its_exact_descendant_without_new_permissions(self):
        page, result = self.apply()
        self.assertEqual(len(result['applied']), 1)
        self.assertEqual(BeautifulSoup(page, 'html.parser').main.p.text,
                         'Keep the complete original paragraph.')

    def test_legacy_validation_preserves_its_original_descendant_rejection(self):
        _, result = self.apply(LEGACY_VERSION)
        self.assertFalse(result['applied'])
        self.assertIn('complete supplied evidence', result['rejected'][0]['reason'])

    def test_partial_stale_and_overview_only_evidence_never_prove_descendants(self):
        context = json.loads(self.context)
        variants = [{**context, 'affected_nodes': []}]
        for change in ({'html_truncated': True}, {'attributes_abbreviated': ['lang']},
                       {'html': '<html><body>Different</body></html>'}, {'match_count': 2}):
            variants.append({**context, 'affected_nodes': [{**context['affected_nodes'][0], **change}]})
        for evidence in variants:
            with self.subTest(evidence=evidence):
                self.assertFalse(self.apply(context=json.dumps(evidence))[1]['applied'])

    def test_identical_markup_outside_an_observed_subtree_stays_unobserved(self):
        source = '<div id="a"><span>Same</span></div><div id="b"><span>Same</span></div>'
        context = json.loads(repair_context(source, [{'nodes': [{'target': ['#a']}]}], []))
        soup = BeautifulSoup(source, 'html.parser')
        observed = fully_observed_nodes(soup, context, include_descendants=True)
        self.assertIn(id(soup.select_one('#a span')), observed)
        self.assertNotIn(id(soup.select_one('#b span')), observed)

    def test_complete_evidence_does_not_allow_whole_page_replacement_or_text_loss(self):
        for selector, replacement in (('body', '<main>Keep the complete original paragraph.</main>'),
                                      ('body > p', '<main><p>Lost information</p></main>')):
            plan = copy.deepcopy(self.plan)
            plan['operations'][0].update(selector=selector, html=replacement)
            plan['root_causes'][0]['selectors'] = [selector]
            with self.subTest(selector=selector):
                self.assertFalse(self.apply(plan=plan)[1]['applied'])


if __name__ == '__main__':
    unittest.main()
