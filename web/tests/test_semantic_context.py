import hashlib,unittest
from accessibility_taxonomy.inventory import inventory
from accessibility_taxonomy.semantic_context import selector
from harness.contracts import ContractError

class SemanticContextTests(unittest.TestCase):
 def test_all_six_contexts_are_observed_without_navigation(self):
  html='''<html><body><p><a href="/apps" aria-label="Apps">Open</a></p><form><label for="email">Email</label><input id="email" type="email" aria-errormessage="error"><p id="error">Enter an email</p><button type="submit">Send email</button></form><div role="tab" aria-controls="panel" aria-label="Account">Account</div><div id="panel">Account settings</div><input type="checkbox" aria-checked="false"><table><tr><th id="cost" scope="col">Cost</th></tr><tr><td headers="cost">10 USD</td></tr></table></body></html>'''
  record=inventory(html,{},'https://example.org/')
  rows={x['type']:x for x in record['opportunities']}
  for typ in ('link-text-mismatch','button-label-mismatch','widget-label-purpose-mismatch','aria-state-mismatch','table-header-association-mismatch','error-message-mismatch'):
   self.assertEqual(rows[typ]['method'],'decisions');self.assertIn('observed_purpose',rows[typ]['context'])
  link=rows['link-text-mismatch']['context']['observed_purpose'];self.assertFalse(link['destination_visited']);self.assertEqual(link['configured_destination'],'https://example.org/apps');self.assertEqual(link['accessible_name'],'Apps')
  self.assertIn('Cost',rows['table-header-association-mismatch']['context']['observed_purpose']['table_html'])
 def test_exact_document_state_identity_and_no_inferred_native_state(self):
  html='<html><body><input type="checkbox" aria-checked="true"></body></html>'
  observation={'document_sha256':hashlib.sha256(html.encode()).hexdigest(),'elements':[{'selector':'html:nth-of-type(1) > body:nth-of-type(1) > input:nth-of-type(1)','checked':False}]}
  r=next(x for x in inventory(html,{},'https://example.org/',observation)['opportunities'] if x['type']=='aria-state-mismatch')
  self.assertIs(r['context']['observed_purpose']['rendered_observation']['checked'],False)
  r=next(x for x in inventory(html,{},'https://example.org/')['opportunities'] if x['type']=='aria-state-mismatch')
  self.assertNotIn('rendered_observation',r['context']['observed_purpose'])
  with self.assertRaises(ValueError):inventory(html+' ',{},'https://example.org/',observation)
 def test_names_include_alt_and_do_not_use_hidden_script_text(self):
  r=next(x for x in inventory('<a href="/apps"><img alt="Download app"><span aria-hidden="true">Wrong</span><script>bad()</script></a>',{},'https://example.org/')['opportunities'] if x['type']=='link-text-mismatch')
  self.assertEqual(r['context']['observed_purpose']['accessible_name'],'Download app')
 def test_linked_heading_receives_group_and_standalone_link_has_no_paragraph_parent(self):
  html='<div><h5><a href="/faq">About</a></h5><ul><li><a href="/faq">FAQ</a></li><li><a href="/privacy">Privacy</a></li></ul></div>'
  r=next(r for r in inventory(html,{},'https://example.org/')['opportunities'] if r['context']['element']['text']=='About')
  self.assertIn('<ul>',r['context']['observed_purpose']['programmatic_context_html'])
  html='<p>Example domains</p><a href="/examples">Learn more</a>'
  r=next(r for r in inventory(html,{},'https://example.org/')['opportunities'] if r['type']=='link-text-mismatch')
  from bs4 import BeautifulSoup
  context=BeautifulSoup(r['context']['observed_purpose']['programmatic_context_html'],'html.parser')
  self.assertNotEqual(context.find('a').parent.name,'p')
