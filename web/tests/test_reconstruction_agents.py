import unittest
import json
import tempfile
from pathlib import Path
from reconstruction_agents import assemble_areas,namespace_fragment
from reconstruction_regression import checkpoint_areas


class ReconstructionAreaTests(unittest.TestCase):
    def test_layout_partition_does_not_drop_direct_content(self):
        from remediation_planner import component_candidates
        source='<div>Important direct content<section>'+('<p>Article</p>'*90)+'</section><footer>Contact</footer></div>'
        candidates=component_candidates(source)
        self.assertEqual(len(candidates),1)
        self.assertIn('Important direct content',candidates[0]['text'])

    def test_main_independent_regions_can_be_partitioned(self):
        from remediation_planner import component_candidates
        source='<main><!-- theme debug --><section>'+('<p>Article</p>'*90)+'</section><section>News</section></main>'
        candidates=component_candidates(source)
        self.assertEqual([item['element'] for item in candidates],['section','section'])
        self.assertEqual(candidates[1]['text'],'News')

    def test_layout_with_form_does_not_block_sibling_partitioning(self):
        from remediation_planner import component_candidates
        content='<div><!-- Drupal theme debug --><form><label>Search<input name="q"></label></form><section>'+('<p>Content</p>'*90)+'</section><footer>Contact</footer></div>'
        candidates=component_candidates(content)
        self.assertEqual([item['element'] for item in candidates],['form','section','footer'])
        self.assertIn('name="q"',candidates[0]['source'])

    def test_functional_carousel_stays_owned_as_one_component(self):
        from remediation_planner import component_candidates
        content='<div class="carousel"><div>'+('<img src="/slide.png">'*90)+'</div><button>Next</button></div>'
        candidates=component_candidates(content)
        self.assertEqual(len(candidates),1)
        self.assertIn('<button>Next</button>',candidates[0]['source'])

    def test_act_grounding_reaches_fragment_generator(self):
        from unittest.mock import Mock
        from reconstruction_agents import regenerate_areas
        call=Mock(return_value=('{"html":"<p>Complete content</p>"}',1,2,.001,.01,'openai/gpt-6-luna'))
        regenerate_areas([{'area':'main','source':'<p>Complete content</p>','prefix':'main-'}],
            {'title':'Page','base_url':'https://example.org'}, {}, 'openai/gpt-6-luna', .9,
            'low', [], call, lambda *args: {'document_text':'Complete content'},
            lambda *args: [], json.loads, None,
            {'act_grounding':'ACT passed/failed image-name pair'}, Mock())
        prompt=call.call_args.args[2]
        self.assertIn('ACT passed/failed image-name pair',prompt)
        self.assertIn('Complete content',prompt)

    def test_legacy_component_guidance_reaches_owned_fragment(self):
        from unittest.mock import Mock
        from reconstruction_agents import regenerate_areas
        from framework_knowledge import retrieve_framework_knowledge
        call=Mock(return_value=('{"html":"<p>Complete content</p>"}',1,2,.001,.01,'openai/gpt-6-luna'))
        regenerate_areas([{'area':'main','source':'<form></form>','prefix':'main-'}],
            {'title':'Page','base_url':'https://example.org'}, {}, 'openai/gpt-6-luna', .9,
            'low', [], call, lambda *args: {'signals':['form']},
            retrieve_framework_knowledge, json.loads, None, {}, Mock())
        prompt=call.call_args.args[2]
        for field in ('guidance','source','knowledge_version'):
            self.assertIn('"'+field+'"',prompt)
        self.assertIn('https://www.w3.org/WAI/tutorials/',prompt)
        self.assertNotIn('"structure"',prompt)
        self.assertNotIn('components/navbar/',prompt)

    def test_exhausted_budget_blocks_first_paid_area_call(self):
        from unittest.mock import Mock
        from reconstruction_agents import regenerate_areas, ReconstructionBudgetStop
        call=Mock()
        with self.assertRaisesRegex(ReconstructionBudgetStop,'budget'):
            regenerate_areas([{'area':'main','source':'<p>Content</p>','prefix':'main-'}],
                {'base_url':'https://example.org'}, {}, 'openai/gpt-6-luna', .9,
                'low', [], call, lambda *args: {}, Mock(), Mock(), None,
                {'remaining_budget':0}, Mock())
        call.assert_not_called()

    def test_budget_stop_keeps_paid_event_and_does_not_assemble_partial_page(self):
        from unittest.mock import Mock
        from reconstruction_agents import regenerate_areas, ReconstructionBudgetStop
        call=Mock(return_value=('{"html":"<p>Content</p>"}',1,2,.02,.01,'openai/gpt-6-luna'))
        event=Mock(); state={'remaining_budget':.01}
        tasks=[{'area':area,'source':'<p>Content</p>','prefix':area+'-'} for area in ('header','main')]
        with self.assertRaises(ReconstructionBudgetStop):
            regenerate_areas(tasks,{'title':'Page','base_url':'https://example.org'},
                {},'openai/gpt-6-luna',.9,'low',[],call,lambda *args: {},
                lambda *args: [],json.loads,None,state,event)
        self.assertEqual(call.call_count,1)
        paid=[args for args in event.call_args_list if args.args[1]=='area_generated']
        self.assertEqual(paid[0].args[3]['cost_usd'],.02)
        self.assertIn('header',state)
        self.assertFalse(any(args.args[1]=='area_assemble' for args in event.call_args_list))

    def test_namespace_preserves_labels_and_local_references(self):
        part={"html":'<label for="q">Query</label><input id="q"><a href="#q">Jump</a>',"css":"#q {color:blue}"}
        namespace_fragment(part,"warp-main-")
        self.assertIn('for="warp-main-q"',part["html"])
        self.assertIn('href="#warp-main-q"',part["html"])
        self.assertIn('#warp-main-q',part["css"])

    def test_namespace_updates_get_element_by_id_without_rewriting_text(self):
        part={'html':'<div id="panel">panel</div>','javascript':"document.getElementById('panel').hidden=true; const label='panel';"}
        namespace_fragment(part,'warp-c0-')
        self.assertIn("getElementById('warp-c0-panel')",part['javascript'])
        self.assertIn("label='panel'",part['javascript'])

    def test_assembly_resolves_cross_area_aria_and_script_references(self):
        header=namespace_fragment({'area':'header','html':'<button aria-controls="panel">Open</button>','javascript':"document.getElementById('panel').hidden=false;"},'warp-c0-')
        main=namespace_fragment({'area':'main','html':'<section id="panel">Content</section>'},'warp-c1-')
        result=assemble_areas([header,main],'Title')
        self.assertIn('aria-controls="warp-c1-panel"',result)
        self.assertIn("getElementById('warp-c1-panel')",result)

    def test_regression_restores_area_without_discarding_conversation(self):
        plan=[{"area":"main","source":"<p>Article</p>"}]
        state={"main":{"part":{"area":"main","html":"<p>Article</p>"},"messages":[{"role":"user","content":"history"}]}}
        with tempfile.TemporaryDirectory() as directory:
            audit=Path(directory)/"axe.json"
            audit.write_text(json.dumps({"violations":[]}))
            checkpoint_areas(state,'<main id="content"><p>Article</p></main>',audit,plan)
            state["main"]["part"]={"area":"main","html":"<p>Lost</p>"}
            result=checkpoint_areas(state,'<main id="content"><p>Lost</p></main>',audit,plan)
        self.assertEqual(result["restored"],["main"])
        self.assertIn("Article",state["main"]["part"]["html"])
        self.assertEqual(len(state["main"]["messages"]),1)

    def test_component_tasks_preserve_frozen_order(self):
        from remediation_planner import component_candidates,validate_component_plan,reconstruction_tasks
        candidates=component_candidates('<body><nav>Home</nav><main>Complete article</main><footer>Contact</footer></body>')
        proposal={'components':[{'id':item['id'],'area':area,'intervention':'regenerate','depends_on':[]} for item,area in zip(candidates,['header','main','footer'])]}
        proposal['components'].reverse()
        plan=reconstruction_tasks(validate_component_plan(proposal,candidates))
        self.assertEqual([item['area'] for item in plan],['header','main','footer'])
        self.assertIn('Complete article',plan[1]['source'])

    def test_missing_audit_disables_previous_reuse(self):
        state={'main':{'reuse':True,'part':{'html':'<p>Article</p>'}}}
        result=checkpoint_areas(state,'<main>Article</main>','/nonexistent-audit.json',[{'area':'main','source':'<p>Article</p>'}])
        self.assertFalse(state['main']['reuse'])
        self.assertEqual(result['reason'],'audit unavailable')

    def test_repeated_words_cannot_hide_content_loss(self):
        plan=[{'area':'main','source':'<p>News News News</p>'}]
        state={'main':{'part':{'html':'<p>News News News</p>'}}}
        with tempfile.TemporaryDirectory() as directory:
            audit=Path(directory)/'axe.json'; audit.write_text('{"violations":[]}')
            checkpoint_areas(state,'<main id="content">News News News</main>',audit,plan)
            state['main']['part']={'html':'<p>News</p>'}
            result=checkpoint_areas(state,'<main id="content">News</main>',audit,plan)
        self.assertEqual(result['restored'],['main'])

    def test_checkpoint_canonicalizes_resources_and_uses_protected_source(self):
        html='<p>News</p><a href="https://example.org/story">Read</a><img src="https://example.org/photo.png" alt="Photo">'
        plan=[{'area':'main','key':'c0','source':'<p>News News duplicate captured menu</p><a href="/story">Read</a><img src="/photo.png">'}]
        state={'c0':{'part':{'html':html}},'born_manifest':[{'id':'c0','html':'<p>News</p><a href="/story">Read</a><img src="/photo.png" alt="Photo">'}]}
        with tempfile.TemporaryDirectory() as directory:
            audit=Path(directory)/'axe.json'; audit.write_text('{"violations":[]}')
            outcome=checkpoint_areas(state,'<main id="content"><div id="warp-c0">'+html+'</div></main>',audit,plan,'https://example.org/')
        self.assertEqual(state['c0']['best_score'],(0,0))
        self.assertEqual(outcome['retained'],['c0'])

    def test_assembler_owns_one_document_and_framework(self):
        result=assemble_areas([{"area":"header","html":"<nav>Home</nav>"},{"area":"main","html":"<h1>Article</h1>"},{"area":"footer","html":"<p>Contact</p>"}],"Title","es")
        self.assertEqual(result.count('<main '),1)
        self.assertEqual(result.count('bootstrap.min.css'),0)
        self.assertIn('href="#content"',result)
        self.assertIn('lang="es"',result)

    def test_assembler_rejects_conflicting_ids_and_documents(self):
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            assemble_areas([{"area":"header","html":"<p id=x>One</p>"},{"area":"main","html":"<p id=x>Two</p>"}],"Title")
        with self.assertRaisesRegex(ValueError,"contract"):
            assemble_areas([{"area":"main","html":"<main>Nested main</main>"}],"Title")

    def test_multiple_components_share_one_main_landmark(self):
        from bs4 import BeautifulSoup
        result=assemble_areas([{'area':'main','key':'c0','html':'<h1>Article</h1>'},{'area':'main','key':'c1','html':'<p>Related</p>'}], 'Title')
        soup=BeautifulSoup(result,'html.parser')
        self.assertEqual(len(soup.find_all('main')),1)
        self.assertIsNotNone(soup.find(id='warp-c0'))
        self.assertIsNotNone(soup.find(id='warp-c1'))
