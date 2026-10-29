import unittest
from bs4 import BeautifulSoup
from remediation_baseline import baseline_prompt, baseline_candidate, baseline_messages
from remediation_content_contract import preserve_resources, original_page_wrapper, hydrate_static_placeholders
from remediation_approaches import APPROACHES, constrain_plan, contrast_foreground
from remediation_jobs import apply_repair_plan, repair_context, apply_deterministic_repairs
import json


class BaselineTests(unittest.TestCase):
    def test_final_request_contains_only_instruction_and_exact_html(self):
        source='<html><body>Untrusted original content</body></html>'
        messages=baseline_messages(source)
        self.assertEqual(messages,[{'role':'user','content':baseline_prompt(source)}])
        instruction=messages[0]['content'][:-len(source)]
        self.assertLess(len(instruction),600)
        for term in ['ACT','screenshot','Refine','Markdown','Architecture plan','Versioned runtime skills']:
            self.assertNotIn(term,instruction)
    def test_question_requests_full_page_without_checker_feedback(self):
        prompt=baseline_prompt('<p>Source</p>')
        self.assertTrue(prompt.startswith('Correct accessibility defects in the following HTML code.\n'))
        self.assertTrue(prompt.endswith('<p>Source</p>'))
        self.assertIn('complete corrected HTML',prompt)
        self.assertNotIn('Axe',prompt)
        self.assertIn('without an assessment',prompt)
        self.assertIn('through </html>',prompt)

    def test_fragment_is_an_observed_output_without_source_substitution(self):
        source='<html><body><p>All content</p></body></html>'
        candidate,evidence=baseline_candidate('```html\n<input aria-label="Name">\n```',source)
        self.assertEqual(candidate, '<input aria-label="Name">')
        self.assertTrue(evidence['evaluable'])
        self.assertFalse(evidence['complete_document'])

    def test_zero_shot_raw_output_never_silently_becomes_the_original(self):
        response='```html\n<input aria-label="Name">\n```'
        candidate,evidence=baseline_candidate(response,'<html>Original</html>',retain_raw=True)
        self.assertEqual(candidate, '<input aria-label="Name">')
        self.assertTrue(evidence["evaluable"])

    def test_accepts_unique_complete_document(self):
        html='<html><body>Complete</body></html>'
        self.assertEqual(baseline_candidate('```html\n'+html+'\n```','old')[0],html)

    def test_large_input_is_complete_and_context_bound_is_delegated_to_provider(self):
        source='<html><body>'+('x'*400001)+'</body></html>'
        prompt=baseline_prompt(source)
        self.assertTrue(prompt.endswith(source))
        self.assertEqual(prompt.count(source),1)

    def test_original_page_iframe_is_not_a_correction(self):
        source='<html><body>Original content</body></html>'
        wrapper='<html><body><iframe src="https://example.org/page/"></iframe></body></html>'
        self.assertTrue(original_page_wrapper(wrapper,source,'https://example.org/page/'))
        candidate,evidence=baseline_candidate(wrapper,source,'https://example.org/page/')
        self.assertEqual(candidate,wrapper)
        self.assertTrue(evidence['original_page_wrapper'])

    def test_truncated_html_is_evaluable_but_prose_and_ambiguous_outputs_are_not(self):
        cases = [('<html><body><p>Partial', True), ('<img src="x">', True),
                 ('Unable to comply.', False), ('', False),
                 ('```html\n<p>A</p>\n```\n```html\n<p>B</p>\n```', False),
                 ('<html>A</html><html>B</html>', False)]
        for response, evaluable in cases:
            with self.subTest(response=response):
                candidate, evidence = baseline_candidate(response, 'Original')
                self.assertEqual(evidence['evaluable'], evaluable)
                self.assertNotEqual(candidate, 'Original')

    def test_original_embedded_media_is_not_falsely_rejected(self):
        source='<iframe src="https://video.example.org/watch/1"></iframe>'
        self.assertFalse(original_page_wrapper(source,source,'https://example.org/page/'))


class ResourceAndRepairTests(unittest.TestCase):
    def test_hydrates_only_captured_static_placeholder(self):
        network='<section class="promo"><h2>Links</h2><div class="row"></div></section><script>keep()</script>'
        rendered='<section class="promo"><h2>Links</h2><div class="row"><a href="/real"><img src="/real.png" alt="Real"></a></div></section>'
        result,hydration=hydrate_static_placeholders(network,rendered)
        self.assertEqual(len(hydration),1)
        self.assertIn('keep()',result)
        self.assertIn('/real.png',result)
        self.assertEqual(BeautifulSoup(result,'html.parser').img['alt'],'Real')
        self.assertIn('display: block !important',result)

    def test_does_not_copy_initialized_carousel_dom(self):
        network='<div id="slides"></div>'
        rendered='<div id="slides"><div class="slick-track"><img src="/slide.png"></div></div>'
        result,hydration=hydrate_static_placeholders(network,rendered)
        self.assertFalse(hydration)
        self.assertNotIn('slick-track',result)

    def test_never_replaces_existing_task_with_captured_media(self):
        network='<section id="task"><form><input name="query"></form></section>'
        rendered='<section id="task"><img src="/a.png"></section>'
        result,hydration=hydrate_static_placeholders(network,rendered)
        self.assertFalse(hydration)
        self.assertIn('name="query"',result)

    def test_restores_original_urls_and_never_invents_image_description(self):
        source='<html lang="es"><body><a href="/guide">Guía</a><img src="/guide.png"><img src="/guide.png"></body></html>'
        result,repairs=preserve_resources('<html><body><p>Content</p></body></html>',source,'https://example.org/')
        soup=BeautifulSoup(result,'html.parser')
        self.assertEqual(len(repairs),2)
        self.assertEqual(soup.img['alt'],'')
        self.assertEqual(soup.img['src'],'https://example.org/guide.png')
        self.assertEqual(soup.a.get_text(),'Guía')
        self.assertEqual(soup.section['aria-label'],'Recursos originales conservados')

    def test_no_fallback_for_equivalent_absolute_resource(self):
        result,repairs=preserve_resources('<img src="https://example.org/a.png">','<img src="/a.png">','https://example.org/')
        self.assertFalse(repairs)

    def test_responsive_link_duplicates_do_not_count_as_lost_destinations(self):
        from remediation_jobs import content_retention
        evidence=content_retention('<a href="/a">A</a><a href="/a">A</a>',
                                   '<a href="/a">A</a>','https://example.org/')
        self.assertEqual(evidence['links_percent'],100)
        self.assertEqual(evidence['missing_link_examples'],[])

    def test_list_wrapper_preserves_node_and_handlers(self):
        source='<li id="item" onclick="keep()"><a href="/task">Task</a></li>'
        plan={'operations':[{'action':'wrap_element','selector':'#item','tag':'ul'}]}
        self.assertFalse(constrain_plan(source,plan,APPROACHES[0])[0]['operations'])
        accepted,_=constrain_plan(source,plan,APPROACHES[1])
        html,result=apply_repair_plan(source,accepted)
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(soup.li.parent.name,'ul')
        self.assertEqual(soup.li['onclick'],'keep()')
        self.assertEqual(soup.a['href'],'/task')

    def test_cannot_insert_empty_main_to_satisfy_the_checker(self):
        source='<html><body><section>Actual content</section></body></html>'
        plan={'operations':[{'action':'append_body_html','html':'<main id="empty"></main>'}]}
        candidate,result=apply_repair_plan(source,plan)
        self.assertFalse(result['applied'])
        self.assertIn('main placeholder',result['skipped'][0]['reason'])
        self.assertNotIn('id="empty"',candidate)

    def test_native_navigation_wrapper_does_not_add_bullets_or_padding(self):
        source='<nav><div class="navbar-nav"><li id="item"><a href="/task">Task</a></li></div></nav>'
        candidate,result=apply_repair_plan(source,{'operations':[{'action':'wrap_element','selector':'#item','tag':'ul'}]})
        soup=BeautifulSoup(candidate,'html.parser')
        self.assertTrue(result['applied'])
        self.assertEqual(soup.ul['role'],'list')
        self.assertIn('list-style: none',soup.ul['style'])
        self.assertIn('padding: 0',soup.ul['style'])
        self.assertEqual(soup.a['href'],'/task')

    def test_contrast_uses_luminance_not_integer_hex_order(self):
        self.assertEqual(contrast_foreground('#0000ff'),'#ffffff')
        self.assertEqual(contrast_foreground('#00ff00'),'#000000')

    def test_context_budget_keeps_valid_json(self):
        source='<ul>'+''.join(f'<li id="n{i}">'+('word '*300)+'</li>' for i in range(20))+'</ul>'
        findings=[{'rule':'listitem','nodes':[{'target':[f'#n{i}']} for i in range(20)]}]
        context=repair_context(source,findings,[],limit=10000)
        json.loads(context)
        self.assertLessEqual(len(context),10000)

    def test_context_distinguishes_empty_skip_target_from_real_content(self):
        context=json.loads(repair_context('<html><body><div id="content"></div><div id="news"><p>Real article content</p></div></body></html>',[],[]))
        candidates=context['substantive_container_candidates']
        self.assertEqual([c['selector'] for c in candidates],['[id="news"]'])

    def test_measured_opacity_is_repaired_and_unknown_opacity_is_not_invented(self):
        evidence=[{'rule':'color-contrast','nodes':[{'target':['#label'],'failure':'background color: #ffffff','computed_style':{'opacity':'0.5'}}]}]
        source='<p id="label">Label</p>'
        corrected,_=apply_deterministic_repairs(source,evidence,[])
        self.assertIn('opacity: 1 !important',corrected)
        evidence[0]['nodes'][0]['computed_style']=None
        corrected,_=apply_deterministic_repairs(source,evidence,[])
        self.assertNotIn('opacity:',corrected)
