import json
import unittest

from remediation_approaches import APPROACHES, constrain_plan
from remediation_jobs import repair_context, apply_repair_plan
from remediation_patch_prompt import operation_examples, patch_prompt
from remediation_planner import planning_prompt, validate_component_plan, component_candidates
from harness.controller import worker_prompt


class PatchPromptContextTests(unittest.TestCase):
    def test_level_one_does_not_offer_replacement_or_behavior(self):
        actions={op['action']for op in operation_examples(APPROACHES[0])}
        self.assertNotIn('replace_element',actions)
        self.assertNotIn('wrap_element',actions)
        self.assertNotIn('append_javascript',actions)
        prompt=patch_prompt(repair_context('<button id="go">Save</button>',[],[]),[],[],'',
                            APPROACHES[0],'Preserve source',1,5)
        self.assertNotIn('"action": "replace_element"',prompt)
        self.assertIn('No replacement',prompt)

    def test_allowed_local_and_coordinated_operations_remain_distinct(self):
        local={op['action']for op in operation_examples(APPROACHES[1])}
        coordinated={op['action']for op in operation_examples(APPROACHES[2])}
        self.assertIn('replace_element',local)
        self.assertIn('wrap_element',local)
        self.assertNotIn('append_javascript',local)
        self.assertIn('append_javascript',coordinated)
        # Real scope guard prevents the advertised local replacement from
        # becoming region replacement; legitimate element repair remains.
        source='<nav id="menu">Links</nav><p id="help">Help</p>'
        plan={'operations':[{'action':'replace_element','selector':'#menu','html':'<nav>Links</nav>'},
                            {'action':'replace_element','selector':'#help','html':'<p id="help" lang="en">Help</p>'}]}
        allowed,rejected=constrain_plan(source,plan,APPROACHES[1])
        self.assertEqual(len(allowed['operations']),1)
        self.assertEqual(len(rejected),1)
        candidate,receipt=apply_repair_plan(source,allowed)
        self.assertIn('lang="en"',candidate)
        self.assertEqual(len(receipt['applied']),1)

    def test_context_marks_all_partial_views_and_duplicate_selector_matches(self):
        source='<html><head><style>'+('p{}'*7000)+'</style></head><body>'
        source+=''.join('<button class="task">'+('word '*600)+'</button>'for _ in range(3))+'</body></html>'
        context=json.loads(repair_context(source,[{'nodes':[{'target':['.task']}]}],[]))
        self.assertTrue(context['document_head_truncated'])
        self.assertEqual(context['selector_evidence'][0]['match_count'],3)
        self.assertEqual(context['selector_evidence'][0]['instances_omitted'],1)
        self.assertEqual([n['match_index']for n in context['affected_nodes']],[1,2])
        self.assertTrue(all(n['html_truncated']for n in context['affected_nodes']))

    def test_context_preserves_names_relationships_and_form_contract(self):
        source='''<html lang="es"><body><form action="/save" method="post"><fieldset>
        <legend>Datos personales</legend><label for="email">Correo</label><p id="help">Para recibir el aviso</p>
        <input id="email" name="email" type="email" aria-describedby="help" required>
        </fieldset></form></body></html>'''
        node=json.loads(repair_context(source,[{'nodes':[{'target':['#email']}]}],[]))['affected_nodes'][0]
        self.assertEqual(node['attributes']['name'],'email')
        self.assertEqual(node['enclosing_form']['attributes'],{'action':'/save','method':'post'})
        self.assertEqual({r['relation']for r in node['related_elements']},
                         {'aria-describedby','label-for','fieldset-legend'})
        self.assertIn('Correo',json.dumps(node,ensure_ascii=False))
        self.assertIn('Para recibir el aviso',json.dumps(node,ensure_ascii=False))

    def test_missing_and_ambiguous_reference_is_not_assumed_valid(self):
        source='<button id="go" aria-labelledby="name missing">Go</button><p id="name">One</p><p id="name">Two</p>'
        context=json.loads(repair_context(source,[{'nodes':[{'target':['#go']},{'target':['#absent']}]}],[]))
        related=context['affected_nodes'][0]['related_elements']
        self.assertEqual([r['match_count']for r in related],[2,0])
        self.assertEqual(context['selector_evidence'][1]['status'],'no_match')

    def test_context_budget_omits_whole_objects_and_reports_omission(self):
        source='<main>'+''.join('<button id="b'+str(i)+'">'+('word '*600)+'</button>'for i in range(30))+'</main>'
        findings=[{'nodes':[{'target':['#b'+str(i)]}for i in range(30)]}]
        text=repair_context(source,findings,[],limit=10000)
        context=json.loads(text)
        self.assertLessEqual(len(text),10000)
        self.assertEqual(context['selectors_omitted'],6)
        self.assertGreater(context['context_nodes_omitted'],0)

    def test_core_route_exposes_the_same_level_permissions(self):
        source='<html><head><title>Test</title></head><body><button id="go">Go</button></body></html>'
        for level in (1,2,3):
            prompt=worker_prompt(source,source,{'failures':[]},level,'https://example.org/',{},'')
            self.assertEqual('"action": "replace_element"'in prompt,level>=2)
            self.assertEqual('"action": "append_javascript"'in prompt,level==3)

    def test_patch_planner_cannot_request_component_regeneration(self):
        source='<body><nav id="nav">Links</nav><main>Article</main></body>'
        candidates=component_candidates(source)
        prompt=planning_prompt(candidates,[],'Preserve',patch_only=True)
        self.assertIn('intervention:preserve|repair,',prompt)
        self.assertNotIn('intervention:preserve|repair|regenerate',prompt)
        proposal={'components':[{'id':c['id'],'area':'main','intervention':'regenerate','depends_on':[]}for c in candidates]}
        with self.assertRaisesRegex(ValueError,'cannot regenerate'):
            validate_component_plan(proposal,candidates,patch_only=True)
        # Retain the separate reconstruction contract for historical use.
        self.assertEqual(len(validate_component_plan(proposal,candidates)),len(candidates))

    def test_sparse_patch_plan_preserves_full_inventory_and_dependencies(self):
        source='<body><nav id="nav">Links</nav><main><button id="go">Go</button></main><footer>Contact</footer></body>'
        candidates=component_candidates(source)
        prompt=planning_prompt(candidates,[], 'Preserve',patch_only=True)
        inventory=json.loads(prompt.split('\nComponents: ',1)[1].split('\nFailures: ',1)[0])
        self.assertEqual([c['id'] for c in inventory],[c['id'] for c in candidates])
        self.assertEqual([c['text'] for c in inventory],[c['text'] for c in candidates])
        proposal={'components':[{'id':'c1','area':'main','intervention':'repair',
                                'depends_on':['c0'],'reason':'Repair the control.'}]}
        plan=validate_component_plan(proposal,candidates,patch_only=True)
        self.assertEqual([c['source'] for c in plan],[c['source'] for c in candidates])
        self.assertEqual([c['intervention'] for c in plan],['preserve','repair','preserve'])
        self.assertEqual(plan[1]['depends_on'],['c0'])
        untouched=validate_component_plan({'components':[]},candidates,patch_only=True)
        self.assertTrue(all(c['intervention']=='preserve' for c in untouched))
        self.assertIn('return assignments only',prompt)
        self.assertIn('Assign EVERY component exactly once',planning_prompt(candidates,[],'Reconstruct'))


if __name__=='__main__':unittest.main()
