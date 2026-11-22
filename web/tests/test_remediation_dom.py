import unittest

from remediation_jobs import apply_deterministic_repairs, apply_repair_plan, absolutize_resources, candidate_gate_distance, compact_html, concise_english_summary, content_retention, document_base_url, dom_change_summary, dom_distance, parse_json_response, preservation_instruction, repair_context, visual_similarity


class RemediationDomDistanceTests(unittest.TestCase):
    def test_evaluator_failure_preserves_the_original_error(self):
        from remediation_jobs import validate_candidate_evaluation
        with self.assertRaisesRegex(RuntimeError, 'Lighthouse: browser disconnected'):
            validate_candidate_evaluation({'status':'failed','error':'Lighthouse: browser disconnected'})
        for incomplete in ({}, {'axe':None,'lighthouse':None}, {'axe':{'violations':0}}):
            with self.assertRaisesRegex(RuntimeError, 'results are missing'):
                validate_candidate_evaluation(incomplete)
        validate_candidate_evaluation({'axe':{'violations':0,'wcag_violations':0,'best_practice_issues':0},'lighthouse':{'accessibility_score':100}})

    def test_transient_no_fcp_is_retried_once_and_recorded(self):
        from unittest.mock import Mock,patch
        from remediation_jobs import _evaluate_candidate
        responses=[]
        for payload in ({'results':[{'status':'failed','error':'Lighthouse incomplete result (NO_FCP)'}]},
                        {'results':[{'axe':{'violations':0,'wcag_violations':0,'best_practice_issues':0},'lighthouse':{'accessibility_score':100}}]}):
            response=Mock();response.json.return_value=payload;response.raise_for_status.return_value=None
            responses.append(response)
        app=Mock();app.config={'EVALUATOR_URL':'http://evaluator'}
        with patch('remediation_jobs.requests.post',side_effect=responses) as post:
            item=_evaluate_candidate(app,{'urls':['http://candidate']})
        self.assertEqual(post.call_count,2)
        self.assertEqual(item['_evaluation_retry']['attempts'],2)
        self.assertIn('NO_FCP',item['_evaluation_retry']['first_error'])

    def test_repeated_transient_failure_keeps_original_error(self):
        from unittest.mock import Mock,patch
        from remediation_jobs import _evaluate_candidate
        responses=[]
        for message in ('original page.goto: Timeout','retry page.goto: Timeout'):
            response=Mock();response.json.return_value={'results':[{'status':'failed','error':message}]};response.raise_for_status.return_value=None
            responses.append(response)
        app=Mock();app.config={'EVALUATOR_URL':'http://evaluator'}
        with patch('remediation_jobs.requests.post',side_effect=responses):
            with self.assertRaisesRegex(RuntimeError,'original page.goto: Timeout'):
                _evaluate_candidate(app,{'urls':['http://candidate']})

    def test_unresponsive_evaluator_has_bounded_timeout(self):
        from unittest.mock import Mock,patch
        import requests
        from remediation_jobs import EVALUATOR_HTTP_TIMEOUT_SECONDS, _evaluate_candidate
        app=Mock(); app.config={'EVALUATOR_URL':'http://evaluator'}
        with patch('remediation_jobs.requests.post',side_effect=requests.Timeout('stalled')) as post:
            with self.assertRaisesRegex(RuntimeError,'evaluator response is unavailable'):
                _evaluate_candidate(app,{'urls':['http://candidate']})
        self.assertEqual(post.call_args.kwargs['timeout'],EVALUATOR_HTTP_TIMEOUT_SECONDS)

    def test_reconstruction_inventory_keeps_complete_reading_order(self):
        from remediation_jobs import reconstruction_inventory
        inventory=reconstruction_inventory('<main><p>First paragraph</p><ul><li>Last item</li></ul><table><tr><td>Final data</td></tr></table></main>')
        self.assertEqual([item['text'] for item in inventory['reading_order']],['First paragraph','Last item','Final data'])

    def test_independent_repair_context_has_page_content_without_axe(self):
        context=repair_context('<html><body><button id="go">Continue</button></body></html>',[],[])
        self.assertIn('Continue',context)
        self.assertIn('independent_page_overview',context)

    def test_visual_similarity_is_optional_when_evidence_is_missing(self):
        self.assertIsNone(visual_similarity('/missing/original.png','/missing/candidate.png'))
        self.assertIsNone(visual_similarity(None,None))
        self.assertIsNone(visual_similarity('/missing/original.png',None))
        self.assertIsNone(visual_similarity(None,'/missing/candidate.png'))

    def test_candidate_gate_distance_rejects_large_axe_regression(self):
        self.assertLess(
            candidate_gate_distance(11,91,1,98),
            candidate_gate_distance(408,96,1,98),
        )

    def test_identical_structure_has_zero_distance(self):
        distance, original_nodes, candidate_nodes = dom_distance(
            '<main><h1>Original text</h1></main>',
            '<main><h1>Different text</h1></main>',
        )
        self.assertEqual(distance, 0)
        self.assertEqual(original_nodes, candidate_nodes)

    def test_semantic_structure_changes_increase_distance(self):
        distance, _, _ = dom_distance(
            '<div><input type="text"></div>',
            '<main><form><label for="name"></label><input name="name" type="text"></form></main>',
        )
        self.assertGreater(distance, 0)

    def test_candidate_resources_are_resolved_against_acquired_page(self):
        result = absolutize_resources(
            '<link href="styles/site.css"><img src="images/hero.jpg"><a href="#main">Skip</a>',
            'https://example.org/catalog/index.html',
        )
        self.assertIn('href="https://example.org/catalog/styles/site.css"', result)
        self.assertIn('src="https://example.org/catalog/images/hero.jpg"', result)
        self.assertIn('href="#main"', result)

    def test_empty_srcset_entries_do_not_crash_resource_resolution(self):
        result = absolutize_resources(
            '<img srcset=" , images/a.jpg 1x, , images/b.jpg 2x, ">',
            'https://example.org/catalog/',
        )
        self.assertIn('srcset="https://example.org/catalog/images/a.jpg 1x, https://example.org/catalog/images/b.jpg 2x"', result)

    def test_inline_carousel_background_keeps_quoted_attribute_intact(self):
        from bs4 import BeautifulSoup
        html = '''<div class="slide-image" tipo_media="" style='background-image: url("/banner.jpg"); background-size: contain;' aria-label="Banner"></div>'''
        result = absolutize_resources(html, 'https://example.org/fei/')
        slide = BeautifulSoup(result, 'html.parser').div
        self.assertEqual(slide['style'], 'background-image: url("https://example.org/banner.jpg"); background-size: contain;')
        self.assertEqual(set(slide.attrs), {'class','tipo_media','style','aria-label'})
        self.assertEqual(absolutize_resources(result, 'https://example.org/fei/'), result)

    def test_resource_rewriting_never_edits_javascript_strings(self):
        from bs4 import BeautifulSoup
        script = '''const html = `<img src="relative.jpg">`; const css = "url('relative.png')";'''
        html = f'<script>{script}</script><style>.hero{{background:url("images/a(1).png")}}</style>'
        output = BeautifulSoup(absolutize_resources(html, 'https://example.org/'), 'html.parser')
        self.assertEqual(output.script.string, script)
        self.assertIn('https://example.org/images/a(1).png', output.style.string)

    def test_oversized_screenshot_does_not_discard_measured_candidate(self):
        from unittest.mock import patch
        from PIL import Image
        with patch('remediation_jobs.Image.open', side_effect=Image.DecompressionBombError('too large')):
            self.assertIsNone(visual_similarity('/original.jpg', '/candidate.jpg'))

    def test_relative_document_base_is_resolved_against_original_origin(self):
        original = 'https://www.example.org/catalog/index.html'
        self.assertEqual(document_base_url('<base href="/">', original), 'https://www.example.org/')
        self.assertEqual(document_base_url('<base href="assets/">', original), 'https://www.example.org/catalog/assets/')
        self.assertEqual(document_base_url('<base href="javascript:alert(1)">', original), original)

    def test_compaction_preserves_structure_and_external_resources(self):
        source = '<html><head><style>body{color:red}</style><script>hugeInline()</script><script src="app.js">fallback</script></head><body><!-- note --><main><h1>Title</h1><svg><path></path></svg></main></body></html>'
        result = compact_html(source)
        self.assertIn('<main><h1>Title</h1>', result)
        self.assertIn('<script src="app.js"></script>', result)
        self.assertIn('<svg></svg>', result)
        self.assertNotIn('hugeInline', result)
        self.assertNotIn('<style>', result)

    def test_dom_change_summary_reports_structural_accessibility_changes(self):
        changes = dom_change_summary(
            '<html><body><div><img></div></body></html>',
            '<html lang="en"><body><main><img alt="Example"><button aria-label="Open">Open</button></main></body></html>',
        )
        self.assertIn({'element': 'main', 'count': 1}, changes['elements_added'])
        self.assertIn({'element': 'div', 'count': 1}, changes['elements_removed'])
        self.assertIn({'attribute': 'alt', 'count': 1}, changes['accessibility_attributes_added'])

    def test_content_retention_detects_summarized_rows_and_missing_destinations(self):
        original='<main><p>Alpha beta gamma delta</p><a href="/a">A</a><a href="/b">B</a></main>'
        candidate='<main><p>Alpha beta</p><a href="/a">A</a></main>'
        retention=content_retention(original,candidate)
        self.assertLess(retention['text_percent'],90)
        self.assertLess(retention['links_percent'],85)
        self.assertIn('/b',retention['missing_link_examples'])

    def test_content_retention_treats_relative_and_absolute_destinations_as_equal(self):
        original='<a href="docs/guide.html">Guide</a><a href="/about">About</a>'
        candidate='<a href="https://example.org/path/docs/guide.html">Guide</a><a href="https://example.org/about">About</a>'
        retention=content_retention(original,candidate,'https://example.org/path/index.html')
        self.assertEqual(retention['links_percent'],100.0)
        self.assertEqual(retention['missing_link_examples'],[])

    def test_screen_reader_profile_allows_visual_change_but_forbids_content_loss(self):
        instruction=preservation_instruction(90)
        self.assertIn('Visual resemblance is not required',instruction)
        self.assertIn('Never omit',instruction)

    def test_constrained_patch_preserves_styles_scripts_and_content(self):
        source='<!doctype html><html><head><style>.brand{color:#135}</style><script>window.keepMe=true</script></head><body><main><img id="hero" src="hero.jpg"><p>Keep every word</p></main></body></html>'
        candidate,result=apply_repair_plan(source,{"operations":[{"action":"set_attribute","selector":"#hero","name":"alt","value":"Campus entrance"},{"action":"append_css","css":"#hero:focus{outline:3px solid #000}"}]})
        self.assertEqual(len(result["applied"]),2)
        self.assertIn('window.keepMe=true',candidate)
        self.assertIn('.brand{color:#135}',candidate)
        self.assertIn('Keep every word',candidate)
        self.assertIn('alt="Campus entrance"',candidate)

    def test_constrained_patch_rejects_root_replacement(self):
        source='<html><body><p>Original</p></body></html>'
        candidate,result=apply_repair_plan(source,{"operations":[{"action":"replace_element","selector":"body","html":"<body>Lost</body>"}]})
        self.assertIn('Original',candidate)
        self.assertEqual(len(result["applied"]),0)
        self.assertEqual(len(result["skipped"]),1)

    def test_constrained_patch_rejects_semantic_violation_hiding(self):
        source='<html><body><div id="content"></div><li id="orphan">Item</li></body></html>'
        candidate,result=apply_repair_plan(source,{"operations":[
            {"action":"set_attribute","selector":"#content","name":"role","value":"main"},
            {"action":"set_attribute","selector":"#orphan","name":"role","value":"presentation"},
        ]})
        self.assertNotIn('role="main"',candidate)
        self.assertNotIn('role="presentation"',candidate)
        self.assertEqual(len(result["skipped"]),2)

    def test_constrained_patch_rejects_executable_markup(self):
        source='<html><body><main id="main">Content</main></body></html>'
        candidate,result=apply_repair_plan(source,{"operations":[{"action":"append_body_html","html":"<script>document.body.innerHTML='changed'</script>"}]})
        self.assertNotIn("innerHTML",candidate)
        self.assertEqual(len(result["skipped"]),1)

    def test_deterministic_repairs_fix_mechanical_evidence(self):
        source='<html><body role="main"><span id="region" style="color:#999">Region</span><a class="more" aria-label="Article title">Read more</a></body></html>'
        candidate,repairs=apply_deterministic_repairs(source,[
            {"rule":"aria-allowed-role","nodes":[{"target":["body"]}]},
            {"rule":"color-contrast","nodes":[{"target":["#region"],"failure":"background color: #ffffff"}]},
        ],[{"audit":"label-content-name-mismatch","items":[{"selector":"a.more"}]}])
        self.assertNotIn('body role=',candidate)
        self.assertIn('color: #000000 !important',candidate)
        self.assertIn('aria-label="Article title"',candidate)
        self.assertEqual(len(repairs),2)

    def test_current_policies_never_apply_unrequested_mechanical_edits(self):
        from remediation_interventions import VERSION
        source='<ul role="list"><li role="tabpanel"><a aria-label="Shopping bag"><span aria-hidden="true">Icon text</span></a></li></ul>'
        candidate,repairs=apply_deterministic_repairs(source,
            [{'rule':'aria-required-children','nodes':[{'target':['ul']}]}],
            [{'audit':'label-content-name-mismatch','items':[{'selector':'a'}]}],intervention_version=VERSION)
        self.assertEqual(candidate,source)
        self.assertEqual(repairs,[])

    def test_deterministic_repairs_resolve_measured_protected_block_roles_and_names(self):
        source='''<html><body><a id="empty" href="https://example.test/help"></a>
        <span id="decorative" role="presentation" tabindex="0">Visible</span>
        <div id="progress" role="progressbar" aria-valuenow="40"></div>
        <ul id="native" role="menu"><li>Item</li></ul></body></html>'''
        evidence=[
            {'rule':'link-name','nodes':[{'target':['#empty']}]},
            {'rule':'presentation-role-conflict','nodes':[{'target':['#decorative']}]},
            {'rule':'aria-progressbar-name','nodes':[{'target':['#progress']}]},
            {'rule':'aria-required-children','nodes':[{'target':['#native']}]},
        ]
        candidate,repairs=apply_deterministic_repairs(source,evidence,[])
        self.assertIn('aria-label="Link to example.test"',candidate)
        self.assertNotIn('role="presentation"',candidate)
        self.assertIn('aria-label="Progress"',candidate)
        self.assertNotIn('role="menu"',candidate)
        self.assertEqual(len(repairs),4)

    def test_repair_context_contains_only_affected_nodes_and_head(self):
        source='<html><head><title>Example</title></head><body><button id="save"></button><p>Unrelated</p></body></html>'
        context=repair_context(source,[{"nodes":[{"target":["#save"]}]}],[])
        self.assertIn('#save',context)
        self.assertIn('<button id=\\"save\\">',context)
        self.assertIn('independent_page_overview',context)


    def test_agent_summaries_are_short_and_do_not_render_chinese(self):
        self.assertLessEqual(len(concise_english_summary("word " * 100)),261)
        self.assertIn("unsupported language",concise_english_summary("图像缺少替代文本"))
        self.assertEqual(parse_json_response('```json\n{"status":"pass"}\n```')["status"],"pass")


if __name__ == "__main__":
    unittest.main()
