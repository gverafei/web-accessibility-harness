import unittest
from unittest.mock import patch, Mock
from remediation_approaches import APPROACHES, approach_for, constrain_plan
from remediation_planner import component_candidates, validate_component_plan, reconstruction_tasks
from remediation_extraction import extraction_quality, markdown_representation, markdown_quality


class ApproachTests(unittest.TestCase):
    def test_markdown_preserves_words_at_adjacent_inline_element_boundaries(self):
        source='<p>First<span>second</span>third</p><div><span>10</span><span>minutes</span></div>'
        view=markdown_representation(source,'https://example.org/','local')
        self.assertEqual(markdown_quality(source,view['markdown'],'https://example.org/')['text_vocabulary_retained_percent'],100)
        self.assertIn('First second third',view['markdown'])
        self.assertIn('10 minutes',view['markdown'])

    def test_five_distinct_engines(self):
        self.assertEqual([approach_for(p).step for p in (15,35,55,75,90)],[1,2,3,4,5])
        self.assertEqual(len({item.engine for item in APPROACHES}),5)

    def test_minimal_scope_is_enforced(self):
        plan={"operations":[{"action":"replace_element","selector":"p","html":"<p>Hello</p>"},{"action":"append_css","css":"body {font-size:40px}"},{"action":"set_attribute","selector":"a","name":"href","value":"/new"}]}
        accepted,rejected=constrain_plan('<p>Hello</p><a href="/old">Link</a>',plan,APPROACHES[0])
        self.assertFalse(accepted['operations']); self.assertEqual(len(rejected),3)

    def test_local_repair_cannot_replace_navigation(self):
        plan={'operations':[{'action':'replace_element','selector':'nav','html':'<nav>New</nav>'}]}
        self.assertFalse(constrain_plan('<nav>Old</nav>',plan,APPROACHES[1])[0]['operations'])

    def test_malformed_css_or_markup_is_rejected_without_type_errors(self):
        for approach in APPROACHES:
            with self.subTest(step=approach.step):
                plan={'operations':[
                    {'action':'append_css','css':{'p':'color: red'}},
                    {'action':'replace_element','selector':'p','html':['<p>bad</p>']},
                    {'action':'wrap_element','selector':'li','tag':['ul']},
                    {'action':'set_attribute','selector':'p','name':'lang','value':'en'}]}
                accepted,rejected=constrain_plan('<p>Hello</p>',plan,approach)
                self.assertEqual(len(rejected),3)
                self.assertEqual(accepted['operations'],[plan['operations'][-1]])

    def test_last_two_steps_distinguish_blocks_from_components(self):
        self.assertEqual(APPROACHES[3].engine,'regenerate_html')
        self.assertEqual(APPROACHES[4].engine,'regenerate_markdown')
        self.assertIn('full acquired HTML',APPROACHES[3].instruction)
        self.assertIn('quality-checked Markdown',APPROACHES[4].instruction)

    def test_replacement_cannot_silently_drop_text(self):
        plan={'operations':[{'action':'replace_element','selector':'section','html':'<section>One</section>'}]}
        self.assertFalse(constrain_plan('<section>One two three four five six</section>',plan,APPROACHES[2])[0]['operations'])

    def test_planner_omissions_preserve_source_without_granting_edits(self):
        candidates=component_candidates('<body><nav id=n>Home</nav><section>Article</section><footer>Contact</footer></body>')
        proposal={'components':[{'id':item['id'],'area':'main','intervention':'preserve','depends_on':[]} for item in candidates]}
        self.assertEqual(len(validate_component_plan(proposal,candidates)),3)
        self.assertEqual(candidates[0]['selector'],'[id="n"]')
        proposal['components'].pop()
        recovered=validate_component_plan(proposal,candidates)
        self.assertEqual(recovered[-1]['source'],candidates[-1]['source'])
        self.assertEqual(recovered[-1]['intervention'],'preserve')
        self.assertEqual(recovered[-1]['depends_on'],[])
        self.assertEqual(recovered[-1]['area'],'footer')
        with self.assertRaisesRegex(ValueError,'exactly once'):
            validate_component_plan({'components':[proposal['components'][0]]*2},candidates)

    def test_malformed_planner_fields_raise_domain_errors_not_type_errors(self):
        candidates=component_candidates('<body><p>Hello</p></body>')
        valid={'id':candidates[0]['id'],'area':'main','intervention':'repair','depends_on':[]}
        proposals=[[], {'components':{}}, {'components':['bad']},
                   {'components':[dict(valid,id=[])]},
                   {'components':[dict(valid,area=[])]},
                   {'components':[dict(valid,intervention={})]},
                   {'components':[dict(valid,depends_on=[{}])]},
                   {'components':[dict(valid,depends_on='c0')]}]
        for proposal in proposals:
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                validate_component_plan(proposal,candidates)

    def test_planner_prompt_does_not_claim_an_unattached_capture(self):
        from remediation_planner import planning_prompt
        self.assertIn('No screenshot is attached',planning_prompt([],[],'Repair'))
        self.assertIn('Original screenshot references are attached',planning_prompt([],[],'Repair',True))

    def test_repair_loop_does_not_replay_old_full_document_prompts(self):
        from pathlib import Path
        source=(Path(__file__).parents[1]/'app/remediation_jobs.py').read_text()
        self.assertNotIn('generator_messages',source)
        self.assertIn('request_messages=[{"role":"user","content":message_content if visual_reference else prompt}]',source)
        self.assertIn('base_document=previous_candidate or source',source)
        self.assertIn('previous_candidate=best_candidate',source)

    def test_markdown_preserves_images_and_links(self):
        view=markdown_representation('<h1>Title</h1><a href="/task">Task</a><img src="/banner.png" alt="Banner">','https://example.org/')
        self.assertIn('# Title',view['markdown']); self.assertIn('https://example.org/banner.png',view['markdown']); self.assertIn('https://example.org/task',view['markdown'])

    def test_markdown_preserves_form_contract_without_layout(self):
        from remediation_extraction import markdown_quality
        source='<form method="get" action="/search.php"><input name="q"><input type="submit" name="go" value="GO"></form><p>Search catalog</p>'
        view=markdown_representation(source,'https://example.org/')
        self.assertIn('https://example.org/search.php',view['markdown'])
        self.assertIn('Field `go`',view['markdown'])
        self.assertIn('value `GO`',view['markdown'])
        self.assertEqual(markdown_quality(source,view['markdown'],'https://example.org/')['text_vocabulary_retained_percent'],100)
        self.assertLess(markdown_quality(source,'unrelated','https://example.org/')['text_vocabulary_retained_percent'],95)

    def test_markdown_quality_ignores_noscript_tracking_pixel(self):
        from remediation_extraction import markdown_quality
        source='<main><p>Research content</p><img src="/chart.png" alt="Chart"></main><noscript><img src="/track.gif"></noscript>'
        view=markdown_representation(source,'https://example.org/')
        self.assertEqual(markdown_quality(source,view['markdown'],'https://example.org/')['missing_images'],[])

    @patch('remediation_extraction.requests.post')
    def test_jina_uses_frozen_html(self,post):
        post.return_value=Mock(text='# Frozen title')
        view=markdown_representation('<h1>Frozen title</h1>','https://example.org/','jina')
        self.assertEqual(post.call_args.kwargs['json']['html'],'<h1>Frozen title</h1>'); self.assertEqual(view['provider'],'jina')

    def test_acquisition_quality_flags_truncation(self):
        self.assertTrue(extraction_quality('<p>'+('text '*20)+'</p>','<p>Only two</p>')['warnings'])

    def test_fragment_tasks_keep_distinct_component_ownership(self):
        candidates=component_candidates('<body><section id=a>Article</section><section id=b>Other article</section></body>')
        plan=validate_component_plan({'components':[{'id':c['id'],'area':'main','intervention':'regenerate','depends_on':[]} for c in candidates]},candidates)
        tasks=reconstruction_tasks(plan)
        self.assertEqual([t['key'] for t in tasks],['c0','c1'])
        self.assertEqual(len({t['prefix'] for t in tasks}),2)

    def test_absolute_resources_are_equivalent_to_original_relative_urls(self):
        source='<p id=x><a href="/task">Task</a><img src="/banner.png"></p>'
        plan={'operations':[{'action':'replace_element','selector':'#x','html':'<p id=x><a href="https://example.org/task">Task</a><img src="https://example.org/banner.png" alt="Banner"></p>'}]}
        accepted,rejected=constrain_plan(source,plan,APPROACHES[2],base_url='https://example.org/')
        self.assertEqual(len(accepted['operations']),1); self.assertFalse(rejected)

    def test_retrieval_coverage_normalizes_act_title_case(self):
        from remediation_rag import retrieval_evidence
        examples=[{'rule_id':'contrast','rule_name':'Text has minimum contrast','expected':outcome} for outcome in ('passed','failed')]
        quality=retrieval_evidence(examples,[{'rule':'color-contrast'},{'rule':'region'}])
        self.assertEqual(quality['matched_pairs'],1)
        self.assertEqual(quality['missing_concepts'],['page content is contained by landmarks'])
