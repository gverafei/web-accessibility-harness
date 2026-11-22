import unittest
from unittest.mock import patch,Mock
from vera_regeneration import generation_messages,generation_evidence,complete_candidate,omission_context,resource_omissions,task_omissions,preservation_refinement_needed,native_control_evidence
from vera_prompt import SYSTEM_PROMPT


class WholeRegenerationTests(unittest.TestCase):

    def test_markdown_regeneration_keeps_unnamed_login_controls_as_source_metadata(self):
        source='<a href="/login"><input type="image" src="/login.png" title="Login"></a>'
        messages=generation_messages('Sign in','https://example.org/',reference_document=source)
        import json
        control_message=next(m['content'] for m in messages if m['content'].startswith('ACQUIRED_NATIVE_CONTROL_EVIDENCE'))
        controls=json.loads(control_message.split(': ',1)[1])
        self.assertEqual(messages[2]['content'],'Sign in')
        self.assertEqual(controls[0]['attributes']['type'],'image')
        self.assertEqual(controls[0]['attributes']['src'],'https://example.org/login.png')
        self.assertEqual(controls[0]['destination'],'https://example.org/login')
        self.assertIsNone(controls[0]['form'])

    def test_omission_feedback_detects_partial_loss_of_repeated_unnamed_controls(self):
        source='<input type="image" src="/a.png"><input type="image" src="/b.png">'
        missing=native_control_evidence(source,'https://example.org/','<input type="image" src="/a.png">')
        self.assertEqual(len(missing),1)
        self.assertEqual(missing[0]['attributes']['src'],'https://example.org/b.png')
        self.assertEqual(native_control_evidence(source,'https://example.org/',source),[])
        self.assertEqual(len(native_control_evidence(source,'https://example.org/','<button>Login</button>')),2)

    def test_native_evidence_keeps_form_submissions_hidden_values_and_options(self):
        source='<form action="/send" method="post"><input type="hidden" name="token" value="source-token"><select name="q"><option value="x">Original</option></select><input type="image" src="/submit.png"></form>'
        controls=native_control_evidence(source,'https://example.org/')
        self.assertEqual(len(controls),3)
        self.assertEqual(controls[0]['attributes']['value'],'source-token')
        self.assertEqual(controls[2]['form'],{'action':'https://example.org/send','method':'post'})
        self.assertIn('value="x"',controls[1]['content'])

    def test_metrics_success_does_not_skip_content_or_task_refinement(self):
        self.assertTrue(preservation_refinement_needed('regenerate_refine',False,[]))
        self.assertTrue(preservation_refinement_needed('regenerate_refine',True,[{'action':'/search'}]))
        self.assertFalse(preservation_refinement_needed('regenerate_refine',True,[]))
        self.assertFalse(preservation_refinement_needed('regenerate_only',False,[{}]))

    def test_native_form_omissions_are_detected_without_restoring_layout(self):
        source='<form action="/search.php"><input name="q"><input type="submit" name="go" value="GO"></form>'
        candidate='<form action="https://example.org/search.php"><input name="q"><button>Search</button></form>'
        missing=task_omissions(source,candidate,'https://example.org/')
        self.assertEqual(missing[0]['fields'][1]['name'],'go')
        self.assertEqual(missing[0]['action'],'https://example.org/search.php')
        self.assertEqual(task_omissions(source,source,'https://example.org/'),[])

    def test_refiner_receives_exact_omitted_content_without_source_layout(self):
        text='These twelve original words are useful information for readers visiting our support page today.'
        source='<style>old theme</style><p>'+text+'<a href="/support">Help</a></p>'
        evidence=omission_context(source,'<p>Visit support</p>','https://example.org/')
        self.assertEqual(evidence[0]['text'],text+' Help')
        self.assertEqual(evidence[0]['destinations'],['https://example.org/support'])
        self.assertNotIn('old theme',str(evidence))
        self.assertEqual(omission_context(source,source,'https://example.org/'),[])
    def test_original_message_roles_and_separate_complete_input(self):
        messages=generation_messages('<html>Exact source</html>','https://example.org/',framework='source')
        self.assertEqual([m['role'] for m in messages],['system','user','user','user'])
        self.assertTrue(messages[0]['content'].startswith(SYSTEM_PROMPT))
        self.assertEqual(messages[1]['content'],"Use the following content to create a new accessible web page version. The root URL is 'https://example.org/'.")
        self.assertEqual(messages[2]['content'],'<html>Exact source</html>')
        self.assertNotIn('data-warp-slot',SYSTEM_PROMPT)
        self.assertNotIn('Axe',SYSTEM_PROMPT)

    def test_missing_resources_keep_short_labels_and_image_relationships(self):
        source='<style>old theme</style><a href="/help">Help</a><a href="/help">Help</a><a href="/photo"><img src="/picture.jpg" alt="Office" title="Original title"></a>'
        missing=resource_omissions(source,'<main>New page</main>','https://example.org/')
        self.assertEqual(missing['links'][0],{'url':'https://example.org/help','text':'Help','title':''})
        self.assertEqual(len(missing['links']),2)
        self.assertEqual(missing['links'][1]['image_src'],'https://example.org/picture.jpg')
        self.assertEqual(missing['images'][0],{'url':'https://example.org/picture.jpg','alt':'Office','title':'Original title','link_destination':'https://example.org/photo'})
        self.assertNotIn('old theme',str(missing))
        self.assertEqual(resource_omissions(source,source,'https://example.org/'),{'links':[],'images':[]})


    def test_placeholder_links_do_not_falsely_count_as_the_source_home_url(self):
        source='<a href="/">Home</a><a href=" /help ">Help</a><a href="#section">Section</a><a href="javascript:void(0)">Toggle</a>'
        candidate='<a href="#">Home</a><a href="">Empty</a><a href="javascript:void(0)">Toggle</a><img src=""><img src="data:image/png;base64,AAAA">'
        missing=resource_omissions(source,candidate,'https://example.org/')
        self.assertEqual({item['url'] for item in missing['links']},{'https://example.org/','https://example.org/help'})
        self.assertEqual(missing['images'],[])

    def test_structural_reference_is_selected_for_the_current_design_base(self):
        messages=generation_messages('# Source','https://example.org/',framework='source')
        self.assertEqual(len(messages),4)
        self.assertIn('ACQUIRED_PAGE_CONTEXT',messages[3]['content'])
        evidence=generation_evidence(messages,'markdown','jina')
        self.assertFalse(evidence['structural_reference'])
        self.assertEqual(evidence['temperature'],.5)
        self.assertNotIn('reproduction',evidence)
        self.assertNotIn('differences',evidence)

    def test_initial_regeneration_keeps_grounding_and_structural_provenance(self):
        grounding='Applicable ACT evidence: rule image-alt, source https://act-rules.github.io/'
        messages=generation_messages('<img src="photo.jpg">','https://example.org/',framework='source',grounding=grounding)
        evidence=generation_evidence(messages,'html','frozen browser DOM')
        self.assertEqual(messages[-1]['content'],grounding)
        self.assertEqual(messages[2]['content'],'<img src="photo.jpg">')
        self.assertFalse(evidence['structural_reference'])
        self.assertIsNone(evidence['structural_reference_metadata'])
        self.assertEqual(evidence['messages'][-1]['content'],grounding)
        empty=generation_messages('<p>Source</p>','https://example.org/',framework='source',grounding='')
        self.assertEqual(len(empty),4)

    def test_experimental_temperature_is_recorded_not_silently_reset(self):
        messages=generation_messages('# Exact source','https://example.org/')
        evidence=generation_evidence(messages,'markdown','local',.7)
        self.assertEqual(evidence['temperature'],.7)
        self.assertEqual(evidence['messages'],messages)
        self.assertEqual(generation_evidence(messages,'markdown','local')['temperature'],.5)

    def test_complete_output_can_rebuild_original_structures_and_fix_labels(self):
        source='<html><body><div><input name="q"></div></body></html>'
        generated='<!doctype html><html><head><title>Source</title></head><body><main><label for="q">Search</label><input id="q" name="q"></main></body></html>'
        self.assertEqual(complete_candidate(generated,source,'https://example.org/'),generated)
        self.assertEqual(complete_candidate('```html\n'+generated+'\n```',source,'https://example.org/'),generated)

    def test_empty_truncated_and_original_embedding_are_not_substituted(self):
        for content in ('',):
            with self.assertRaises(ValueError): generation_messages(content,'https://example.org/')
        for response in ('<p>Snippet</p>','<!doctype html><html><body>Incomplete','<!doctype html><html><body><iframe src="https://example.org/"></iframe></body></html>'):
            with self.assertRaises(ValueError): complete_candidate(response,'<html><body>Original</body></html>','https://example.org/')

    def test_complete_document_with_explanatory_prose_is_extracted_not_rejected(self):
        generated='<!doctype html><html><head><title>Source</title></head><body><main>Source</main></body></html>'
        for response in ('Here is the page:\n'+generated+'\nNote: test keyboard behavior.',
                         '```html\n'+generated+'\n```\nNote: test keyboard behavior.'):
            self.assertEqual(complete_candidate(response,'<p>Original</p>','https://example.org/'),generated)
        for response in (generated+generated, generated+'<!doctype html><html><body>Incomplete'):
            with self.assertRaises(ValueError):
                complete_candidate(response,'<p>Original</p>','https://example.org/')

    def test_script_literals_do_not_end_the_extracted_document_early(self):
        generated='<!doctype html><html><head><script>const example="</html>";</script></head><body><main>Source</main></body></html>'
        self.assertEqual(complete_candidate(generated+'\nNote: complete page.','<p>Source</p>','https://example.org/'),generated)

    def test_large_regeneration_source_is_preserved_for_common_provider_guard(self):
        content='<html><body><p>'+('source '*30000)+'</p></body></html>'
        messages=generation_messages(content,'https://example.org/')
        self.assertEqual(messages[2]['content'],content)
        self.assertGreater(len(messages[2]['content']),180000)
