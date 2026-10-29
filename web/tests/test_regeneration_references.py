"""Removed templates cannot influence a new prompt or mutate candidate bytes."""
import unittest
from regeneration_references import select_reference,ensure_design_base,selected_framework
from vera_regeneration import generation_messages,generation_evidence
class SourceReferenceTests(unittest.TestCase):
 def test_no_external_template_can_be_selected_or_injected(self):
  html='<html><head><style>p{color:#111}</style></head><body>Source</body></html>'
  for retired in ('bootstrap','pico','bulma','tailwind'):
   with self.assertRaises(ValueError):select_reference(html,retired)
   with self.assertRaises(ValueError):ensure_design_base(html,retired)
   with self.assertRaises(ValueError):generation_messages(html,'https://example.org/',framework=retired)
  self.assertEqual(ensure_design_base(html,'source')[0],html)
  self.assertEqual(selected_framework('old-record-value'),'source')
 def test_reference_contains_no_page_skeleton(self):
  row=select_reference('<h1>Source</h1>')
  self.assertEqual(row['html'],'');self.assertIsNone(row['stylesheet'])
  messages=generation_messages('<h1>Source</h1>','https://example.org/',creative=True)
  self.assertIsNone(generation_evidence(messages,'html','local')['structural_reference_metadata'])
  self.assertFalse(any('PAGE_REFERENCE_METADATA' in m['content']for m in messages if isinstance(m['content'],str)))
