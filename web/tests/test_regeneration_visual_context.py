import unittest,json
from vera_regeneration import generation_messages,generation_evidence,generation_text,source_design_context
class RegenerationVisualTests(unittest.TestCase):
 def test_single_call_control_request_is_exactly_its_baseline_instruction_and_source(self):
  from remediation_jobs import creative_refinement_prompt
  from remediation_baseline import baseline_prompt
  source='<html><body><main>Exact source</main></body></html>';control=baseline_prompt(source)
  for creative in (True,False):
   for initial in (True,False):
    actual=creative_refinement_prompt(control,creative=creative,initial_regeneration=initial,single_shot=True)
    self.assertEqual(actual,control)
  ordinary=creative_refinement_prompt(control,creative=True,initial_regeneration=False,single_shot=False)
  self.assertTrue(ordinary.startswith(control));self.assertIn('Refine the current redesigned page',ordinary)

 def test_dynamic_transition_to_creative_actions_cannot_inherit_a_design_template(self):
  from remediation_interventions import VERSION
  from regeneration_references import intervention_framework,ensure_design_base
  for level in (4,5):
   framework=intervention_framework('component_knowledge',VERSION,level)
   self.assertEqual(framework,'source')
   messages=generation_messages('<main>Original</main>','https://example.test/',framework=framework,creative=True)
   self.assertIn('new, polished',messages[0]['content'])
   html='<html><head><style>.own {color:navy}</style></head><body><main class="own">New page</main></body></html>'
   final,_=ensure_design_base(html,framework);self.assertEqual(final,html)
   self.assertNotIn('bootstrap',final)

 def test_fixed_current_and_historical_framework_requests_keep_their_previous_meaning(self):
  from remediation_interventions import VERSION,PRESERVATION_VERSION
  from regeneration_references import intervention_framework,selected_framework
  for level in (1,3):
   self.assertEqual(intervention_framework('component_knowledge',VERSION,level),selected_framework('component_knowledge'))
  for level in (4,5):
   self.assertEqual(intervention_framework('source_reference',VERSION,level),selected_framework('source_reference'))
   self.assertEqual(intervention_framework('vera_reference',PRESERVATION_VERSION,level),selected_framework('vera_reference'))

 def test_first_request_includes_capture_and_preserves_source_and_act(self):
  source='<html lang="es"><title>Marca</title><main><h1>Texto original</h1><img src="/a.png"></main></html>'
  image={'type':'image_url','image_url':{'url':'data:image/jpeg;base64,fixture'}}
  msgs=generation_messages('# Texto original','https://example.test/',reference_document=source,visual_references=[image],grounding='ACT fixture')
  self.assertEqual(msgs[2]['content'],'# Texto original');self.assertEqual(msgs[-1]['content'],'ACT fixture');self.assertIn(image,next(m['content']for m in msgs if isinstance(m['content'],list)))
  evidence=generation_evidence(msgs,'markdown','local',.05);self.assertEqual(evidence['visual_reference_count'],1);self.assertEqual(evidence['version'],'original-structure-first-regeneration-v9');self.assertEqual(evidence['temperature'],.05)
  self.assertNotIn('base64,fixture',generation_text(msgs));self.assertIn('Immutable original capture',generation_text(msgs))
 def test_outline_keeps_full_order_regions_image_caption_and_native_form(self):
  source='<main><section id="s"><h1>Original</h1><figure><img src="photo.png" alt="Exact alt"><figcaption>Exact caption</figcaption></figure><a href="/go">Exact link</a><form action="/send" method="post"><input name="q"></form></section></main>'
  d=source_design_context(source,'https://example.test/page/');self.assertEqual(d['regions'][1]['parent'],'region-1');self.assertEqual(d['images'][0]['caption'],'Exact caption');self.assertEqual(d['images'][0]['url'],'https://example.test/page/photo.png');self.assertEqual(d['links'][0]['url'],'https://example.test/go');self.assertEqual(d['forms'][0]['method'],'post')
 def test_large_outline_not_silently_truncated(self):
  d=source_design_context('<main>'+''.join('<section><h2>Item '+str(i)+'</h2><a href="/'+str(i)+'">Go</a></section>'for i in range(150))+'</main>','https://example.test/')
  self.assertEqual(len(d['regions']),151);self.assertEqual(len(d['heading_order']),150);self.assertEqual(d['heading_order'][-1]['text'],'Item 149');self.assertEqual(len(d['links']),150)
 def test_no_capture_never_claims_visual_observation(self):
  msgs=generation_messages('<p>Original</p>','https://example.test/');self.assertEqual(generation_evidence(msgs,'html','frozen')['visual_reference_count'],0);self.assertNotIn('Immutable original capture',generation_text(msgs));self.assertIn('no computed geometry',generation_text(msgs))
 def test_invalid_visual_content_fails_explicitly(self):
  for bad in [[{'type':'audio'}],['bad'],'bad']:
   with self.assertRaises(ValueError):generation_messages('Original','https://example.test/',visual_references=bad)

 def test_compact_context_preserves_every_parsed_value_and_full_source(self):
  source='<html><head><style>p { color: blue; }</style></head><body><main><p title="Exact spaces: a  b">Original</p><select id="choice"><option value="á">A  B</option></select></main></body></html>'
  msgs=generation_messages(source,'https://example.test/',framework='source')
  self.assertEqual(msgs[2]['content'],source)
  raw=next(m['content'].split(': ',1)[1]for m in msgs if isinstance(m['content'],str)and m['content'].startswith('ACQUIRED_PAGE_CONTEXT'))
  parsed=json.loads(raw)
  expected=source_design_context(source,'https://example.test/')
  self.assertEqual({k:parsed[k]for k in expected},expected)
  self.assertEqual(parsed['source_styles']['inline'],['<style>p { color: blue; }</style>'])
  self.assertEqual(raw,json.dumps(parsed,ensure_ascii=False,separators=(',',':')))
  self.assertLess(len(raw),len(json.dumps(parsed,ensure_ascii=False)))

 def test_recorded_background_and_rendered_media_are_supplied_without_new_fetches(self):
  msgs=generation_messages('# Original','https://example.test/',reference_document='<main>Original</main>',source_inventory={'media_assets':['https://example.test/hero.webp'],'dynamic_images':[{'url':'https://example.test/banner.webp','source':'rendered DOM'}]})
  outline=json.loads(next(m['content'].split(': ',1)[1]for m in msgs if isinstance(m['content'],str)and m['content'].startswith('ACQUIRED_PAGE_CONTEXT')))
  self.assertEqual(outline['media_evidence']['media_assets'],['https://example.test/hero.webp']);self.assertEqual(outline['media_evidence']['dynamic_images'][0]['source'],'rendered DOM');self.assertIn('not permission to fetch',outline['media_evidence_scope'])
