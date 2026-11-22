"""A semantic finding at a perfect audit endpoint must retain bounded replacement evidence."""
import json
import unittest

from harness.controller import materialize
from remediation_interventions import VERSION
from remediation_patch_context import repair_context


class ContextualPatchTargetsTests(unittest.TestCase):
    source = '<!doctype html><html><head><title>Project</title></head><body><div id="content"><h2 aria-label="Project web server">Project</h2><p>A web server and proxy.</p></div></body></html>'

    def evidence(self):
        return {'failed_opportunities':[{'type':'heading-not-descriptive','status':'failed',
            'context':{'element':{'tag':'h2','attributes':{'aria-label':'Project web server'},'text':'Project'}}}]}

    def replace(self, context):
        operation = {'action':'replace_element', 'selector':'[id="content"] > h2:nth-of-type(1)',
                     'html':'<h2 aria-label="Project web server">Project web server</h2>'}
        plan = {'operations':[operation], 'root_causes':[{'id':'heading', 'selectors':[operation['selector']],
                 'depends_on':[], 'operation_indexes':[0]}]}
        return materialize(self.source, json.dumps(plan), 3, 'https://example.org/',
                           intervention_version=VERSION, patch_context=context)

    def test_semantic_heading_remains_repairable_at_zero_axe_and_perfect_lighthouse(self):
        legacy = repair_context(self.source, [], [])
        self.assertFalse(self.replace(legacy)[1]['applied'])
        context = repair_context(self.source, [], [], contextual_evidence=self.evidence())
        parsed = json.loads(context)
        self.assertEqual(len(parsed['affected_nodes']), 1)
        self.assertFalse(parsed['affected_nodes'][0]['html_truncated'])
        page, report = self.replace(context)
        self.assertTrue(report['applied'])
        self.assertIn('Project web server</h2>', page)

    def test_ambiguous_stale_and_unlocatable_elements_do_not_authorize_replacement(self):
        evidence = self.evidence()
        for source in (self.source.replace('</h2>', '</h2><h2 aria-label="Project web server">Project</h2>'),
                       self.source.replace('>Project</h2>', '>Changed</h2>')):
            context = json.loads(repair_context(source, [], [], contextual_evidence=evidence))
            self.assertEqual(context['affected_nodes'], [])
            self.assertTrue(context['unresolved_contextual_targets'])
        evidence['failed_opportunities'][0]['context']['element'].pop('text')
        context = json.loads(repair_context(self.source, [], [], contextual_evidence=evidence))
        self.assertEqual(context['affected_nodes'], [])

    def test_context_limits_and_source_task_guards_still_apply(self):
        source = self.source.replace('>Project</h2>', '>'+'Project '*1000+'</h2>')
        evidence = self.evidence(); evidence['failed_opportunities'][0]['context']['element']['text'] = 'Project '*1000
        context = json.loads(repair_context(source, [], [], contextual_evidence=evidence))
        self.assertTrue(context['affected_nodes'][0]['html_truncated'])
        context = repair_context(self.source, [], [], contextual_evidence=self.evidence(), limit=100)
        self.assertFalse(self.replace(context)[1]['applied'])

    def test_legacy_and_fixed_policy_contexts_keep_their_contract(self):
        self.assertEqual(repair_context(self.source, [], []),
                         repair_context(self.source, [], [], contextual_evidence=None))
        self.assertEqual(json.loads(repair_context(self.source, [], []))['version'], 'focused-patch-context-v4')

    def test_unique_alias_selects_only_the_fully_observed_instance(self):
        source = '<div id="content"><center><h4>Latest News</h4></center><center><h4>Other Projects</h4></center></div>'
        context = repair_context(source, [], [{'items':[{'selector':'#content > center > h4'}]}])
        operations = [{'action':'replace_element',
                       'selector':f'#content > center:nth-of-type({i}) > h4',
                       'html':f'<h3>{text}</h3>'}
                      for i, text in ((1, 'Latest News'), (2, 'Other Projects'))]
        plan = {'operations':operations, 'root_causes':[{'id':'heading',
                'selectors':[op['selector'] for op in operations],
                'depends_on':[], 'operation_indexes':[0,1]}]}
        page, report = materialize(source, json.dumps(plan), 3, 'https://example.org/',
                                  intervention_version=VERSION, patch_context=context)
        self.assertEqual(len(report['applied']), 2)
        self.assertIn('<h3>Other Projects</h3>', page)
        # A broad selector still cannot replace different headings with one text.
        operations[0]['selector'] = '#content > center > h4'
        plan = {'operations':[operations[0]], 'root_causes':[{'id':'heading',
                'selectors':[operations[0]['selector']], 'depends_on':[], 'operation_indexes':[0]}]}
        self.assertFalse(materialize(source, json.dumps(plan), 3, 'https://example.org/',
            intervention_version=VERSION, patch_context=context)[1]['applied'])

    def test_alias_cannot_borrow_a_different_nodes_markup_or_stale_excerpt(self):
        from bs4 import BeautifulSoup
        from remediation_patch_safety import fully_observed_nodes
        source = '<div><span>Same</span><span>Same</span></div>'
        context = json.loads(repair_context(source, [], [{'items':[{'selector':'span:first-child'}]}]))
        soup = BeautifulSoup(source, 'html.parser')
        self.assertEqual(fully_observed_nodes(soup, context), {id(soup.select_one('span:first-child'))})
        for changes in ({'html':'<span>Stale</span>'}, {'match_index':2},
                        {'match_count':2}, {'html_truncated':True},
                        {'attributes_abbreviated':['id']}):
            changed = {**context, 'affected_nodes':[{**context['affected_nodes'][0], **changes}]}
            self.assertEqual(fully_observed_nodes(soup, changed), set())


if __name__ == '__main__':
    unittest.main()
