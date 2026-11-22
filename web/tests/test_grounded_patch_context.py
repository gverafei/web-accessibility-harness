import json
import unittest
from bs4 import BeautifulSoup
from grounded_patch_context import repair_context, VERSION
from remediation_patch_safety import fully_observed_nodes, rejection_reason
from remediation_patch_context import repair_context as legacy

class GroundedTargetsTests(unittest.TestCase):
    def test_every_recorded_target_gets_source_evidence_beyond_first_24(self):
        source = '<html><head><style>' + 'x'*30000 + '</style></head><body><footer>' + ''.join(
            f'<a class="small" id="link-{i}" href="/item-{i}">Item {i}</a>' for i in range(70)) + '</footer></body></html>'
        findings = [{'type':'target-size','target':[f'#link-{i}']} for i in range(70)]
        context = repair_context(source,[],[],contextual_evidence={'failed_opportunities':findings})
        data = json.loads(context)
        self.assertLessEqual(len(context), 50000)
        self.assertEqual(len(data['selector_evidence']), 70)
        self.assertEqual(data['selectors_omitted'], 0)
        self.assertTrue(all(row['elements'][0]['attributes']['class'] == ['small'] for row in data['selector_evidence']))
        self.assertEqual(data['selector_evidence'][-1]['elements'][0]['attributes']['href'],'/item-69')
        self.assertEqual(data['version'], VERSION)
        self.assertTrue(all(row['match_count'] == 1 for row in data['selector_evidence']))

    def test_aliases_merge_only_identical_source_match_sets(self):
        source='<a id="first" class="item">A</a><a class="item">B</a>'
        targets=[{'target':['#first']},{'target':['a:first-child']},{'target':['.item']}]
        data=json.loads(repair_context(source,[{'nodes':targets}],[]))
        self.assertEqual(data['measured_selector_count'],3)
        self.assertEqual(data['equivalent_selectors_merged'],1)
        self.assertEqual([row['match_count'] for row in data['selector_evidence']],[1,2])

    def test_verified_identity_reference_reuses_full_evidence_without_fake_attributes(self):
        source='<h2 id="h">News</h2>'
        finding={'context':{'element':{'tag':'h2','attributes':{'id':'h'},'text':'News'}}}
        data=json.loads(repair_context(source,[],[],contextual_evidence={'failed_opportunities':[finding]}))
        row=data['selector_evidence'][0]['elements'][0]
        self.assertEqual(row['contextual_element_reference'],0)
        self.assertNotIn('attributes',row)
        self.assertEqual(data['selectors_omitted'],0)

    def test_identical_component_classes_do_not_claim_shared_ancestry(self):
        source='<div class="card"><a id="a">A</a></div><div class="card"><a id="b">B</a></div>'
        data=json.loads(repair_context(source,[{'nodes':[{'target':['#a']},{'target':['#b']}]}],[]))
        parents=[row['elements'][0]['ancestor_refs'][0] for row in data['selector_evidence']]
        self.assertNotEqual(parents[0],parents[1])

    def test_nested_invalid_and_absent_selectors_are_not_reinterpreted(self):
        findings=[{'target':target} for target in ([['#host','#inside']], ['iframe','#inside'], ['#missing'],['[bad'])]
        data=json.loads(repair_context('<div id="inside">Text</div>',[],[],contextual_evidence={'failed_opportunities':findings}))
        self.assertEqual(len(data['unresolved_targets']),2)
        self.assertEqual([row['status'] for row in data['selector_evidence']],['no_match','invalid_selector'])
        self.assertFalse(data['affected_nodes'])

    def test_recorded_selector_cannot_override_stale_semantic_identity(self):
        finding={'target':['#h'],'context':{'element':{'tag':'h2','attributes':{'id':'h'},'text':'Old'}}}
        data=json.loads(repair_context('<h2 id="h">New</h2>',[],[],contextual_evidence={'failed_opportunities':[finding]}))
        self.assertFalse(data['selector_evidence'])
        self.assertTrue(data['unresolved_targets'])

    def test_full_replacement_proof_is_still_exact_and_partial_index_cannot_supply_it(self):
        source='<div><h4 id="h">News</h4><p id="long">'+'a'*5000+'</p></div>'
        context=json.loads(repair_context(source,[{'nodes':[{'target':['#h']},{'target':['#long']}]}],[]))
        soup=BeautifulSoup(source,'html.parser')
        self.assertEqual(fully_observed_nodes(soup,context),{id(soup.select_one('#h'))})
        self.assertEqual(context['context_nodes_omitted'],1)
        context['affected_nodes'][0]['html']='<h4 id="h">Other</h4>'
        self.assertFalse(fully_observed_nodes(soup,context))

    def test_oversized_inventory_is_explicitly_partial_and_bounded(self):
        source=''.join(f'<a id="link-{i}" href="/x">Text</a>' for i in range(120))
        targets=[{'target':[f'#link-{i}']} for i in range(120)]
        result=repair_context(source,[{'nodes':targets}],[],limit=4000)
        data=json.loads(result)
        self.assertLessEqual(len(result),4000)
        self.assertGreater(data['selectors_omitted'],0)
        self.assertGreater(data['context_nodes_omitted'],0)
        self.assertEqual(data['selectors_omitted']+len(data['selector_evidence']),120)

    def test_multi_match_coverage_and_css_scope_are_not_silently_expanded(self):
        source='<div id="group"><a>A</a><a>B</a><a>C</a></div><a>Other</a>'
        data=json.loads(repair_context(source,[{'nodes':[{'target':['#group a']}]}],[]))
        self.assertEqual(data['selector_evidence'][0]['match_count'],3)
        self.assertEqual(data['selector_evidence'][0]['instances_omitted'],1)
        invalid={'action':'append_css','selector':'#group a:first-child','css':'a { min-height:24px; }'}
        self.assertEqual(rejection_reason(source,invalid,'coordinated','https://example.org',data),'CSS affects elements outside the declared component')

    def test_legacy_context_remains_available_and_unchanged_by_new_projection(self):
        source='<button id="b">Go</button>'
        args=(source,[{'nodes':[{'target':['#b']}]}],[])
        before=legacy(*args)
        repair_context(*args)
        self.assertEqual(legacy(*args),before)

class GroundedIntegrationTests(unittest.TestCase):
    def test_native_and_sql_workers_share_the_versioned_context(self):
        from harness.controller import worker_prompt
        from remediation_jobs import repair_context as sql_context
        from remediation_patch_context import repair_context as shared_context
        source='<div><h2 id="h">News</h2></div>'
        evidence={'failed_opportunities':[{'type':'heading-not-descriptive','target':['#h']}]}
        kwargs={'contextual_evidence':evidence,'target_coverage':VERSION}
        context=shared_context(source,[],[],**kwargs)
        self.assertEqual(sql_context(source,[],[],**kwargs),context)
        prompt=worker_prompt(source,source,{'failures':[]},3,'https://example.org/',{},'',patch_context=context)
        self.assertIn(context,prompt)
        with self.assertRaises(ValueError):
            shared_context(source,[],[],target_coverage='unknown')

    def test_manifest_requires_explicit_supported_context_version(self):
        import copy
        from harness.contracts import validate_manifest, ContractError
        from test_slider_bridge import BridgeTests
        fixture=BridgeTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        old=copy.deepcopy(fixture.manifest)
        self.assertNotIn('adaptive_patch_context_version',validate_manifest(old))
        from harness.dynamic_objectives import COORDINATED_EVIDENCE_VERSION
        old.update(adaptive_evidence_version=COORDINATED_EVIDENCE_VERSION, adaptive_patch_context_version=VERSION)
        self.assertEqual(validate_manifest(old)['adaptive_patch_context_version'],VERSION)
        supported=old['adaptive_evidence_version']
        from harness.dynamic_objectives import EVIDENCE_VERSION
        old['adaptive_evidence_version']=EVIDENCE_VERSION
        with self.assertRaises(ContractError):validate_manifest(old)
        old['adaptive_evidence_version']=supported
        from grounded_patch_context import COMPONENT_VERSION
        old['adaptive_patch_context_version']=COMPONENT_VERSION
        self.assertEqual(validate_manifest(old)['adaptive_patch_context_version'], COMPONENT_VERSION)
        old['adaptive_patch_context_version']='unknown'
        with self.assertRaises(ContractError):validate_manifest(old)

if __name__ == '__main__': unittest.main()

class ComponentCoverageTests(unittest.TestCase):
    def test_contextual_identity_retains_shared_ancestor_and_exact_selector(self):
        from grounded_patch_context import COMPONENT_VERSION
        source = '<footer class="muted"><div><div><ul><li><a id="a">A</a></li><li><a id="b">B</a></li></ul></div></div></footer>'
        findings = [{'context': {'element': {'tag': 'a', 'attributes': {'id': key}, 'text': key.upper()}}}
                    for key in ('a', 'b')]
        data = json.loads(repair_context(source, [], [], contextual_evidence={'failed_opportunities': findings}, version=COMPONENT_VERSION))
        footer = next(i for i, row in enumerate(data['ancestor_evidence']) if row['element'] == 'footer')
        soup = BeautifulSoup(source, 'html.parser')
        self.assertEqual(soup.select(data['ancestor_evidence'][footer]['selector']), [soup.footer])
        for row in data['selector_evidence']:
            self.assertIn(footer, row['elements'][0]['ancestor_refs'])
        self.assertNotIn(id(soup.footer), fully_observed_nodes(soup, data))
        old = json.loads(repair_context(source, [], [], contextual_evidence={'failed_opportunities': findings}))
        self.assertEqual(old['ancestor_evidence'], [])

    def test_shared_css_root_beyond_three_levels_survives_audit_projection(self):
        from grounded_patch_context import COMPONENT_VERSION
        source = '<section id="common"><div><div><ul><li><span id="a">A</span></li><li><span id="b">B</span></li></ul></div></div></section>'
        audit = [{'nodes': [{'target': ['#a']}, {'target': ['#b']}]}]
        old = json.loads(repair_context(source, audit, []))
        data = json.loads(repair_context(source, audit, [], version=COMPONENT_VERSION))
        self.assertFalse(any(row['id'] == 'common' for row in old['ancestor_evidence']))
        common = next(i for i, row in enumerate(data['ancestor_evidence']) if row['id'] == 'common')
        self.assertTrue(all(common in row['elements'][0]['ancestor_refs'] for row in data['selector_evidence']))
        self.assertEqual(old['measured_selector_count'], data['measured_selector_count'])
        self.assertEqual(old['affected_nodes'], data['affected_nodes'])

    def test_versioned_integration_preserves_defaults_and_css_permissions(self):
        from grounded_patch_context import COMPONENT_VERSION
        source = '<footer><a id="a">A</a></footer><a>Other</a>'
        args = (source, [{'nodes': [{'target': ['#a']}]}], [])
        previous = legacy(*args, target_coverage=VERSION)
        new = legacy(*args, target_coverage=COMPONENT_VERSION)
        self.assertEqual(legacy(*args, target_coverage=VERSION), previous)
        self.assertEqual(json.loads(new)['version'], COMPONENT_VERSION)
        invalid = {'action': 'append_css', 'selector': '#a', 'css': 'a { color: black; }'}
        self.assertEqual(rejection_reason(source, invalid, 'coordinated', 'https://example.org', json.loads(new)),
                         'CSS affects elements outside the declared component')
