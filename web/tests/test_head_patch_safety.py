import unittest,copy
from bs4 import BeautifulSoup
from harness.html_tools import insert_head_metadata
from harness.syntax_policy import localize,compare
class HeadPatchTests(unittest.TestCase):
 def test_css_precedes_custom_head_flow_without_rewriting_authored_nodes(self):
  source='<html><head><style>.old{color:red}</style><custom-style><style>.theme{color:blue}</style></custom-style><meta name="x" content="y"></head><body><button>Keep</button></body></html>'
  s=BeautifulSoup(source,'html.parser');before=str(s.find('custom-style'));style=s.new_tag('style');style.string='.button{color:black}';insert_head_metadata(s,style)
  self.assertLess(str(s).index('.button'),str(s).index('<custom-style>'));self.assertEqual(str(s.find('custom-style')),before);self.assertEqual(s.button.get_text(),'Keep');self.assertIs(style.parent,s.head)
 def test_ordinary_head_preserves_override_order(self):
  s=BeautifulSoup('<html><head><style>.a{color:red}</style></head><body>x</body></html>','html.parser');style=s.new_tag('style');style.string='.a{color:black}';insert_head_metadata(s,style);self.assertIs(s.head.contents[-1],style)
 def test_metadata_helper_rejects_page_content(self):
  s=BeautifulSoup('<html><head></head><body>Original</body></html>','html.parser')
  with self.assertRaises(ValueError):insert_head_metadata(s,s.new_tag('div'))
 def syntax(self,source):
  offset=source.index('</head>');before=source[:offset];line=before.count('\n')+1;column=len(before.rsplit('\n',1)[-1].encode('utf-16-le'))//2+1
  return {'state':'violated','validator':'html-validate','version':'fixture','errors':[{'rule':'close-order','message':"Stray end tag '</head>'",'selector':None,'line':line,'column':column}]}
 def test_exact_located_boundary_can_be_inherited_after_earlier_patch(self):
  source='<html><head>'+'a'*120+'<custom-style>x</custom-style>'+'z'*120+'</head><body>Keep</body></html>';candidate=source.replace('<head>','<head><style>.local{color:black}</style>')
  base=localize(self.syntax(source),source,'https://example.test/');new=localize(self.syntax(candidate),candidate,'https://example.test/');self.assertEqual(compare(new,base)['state'],'passed');self.assertEqual(len(compare(new,base)['inherited']),1)
 def test_same_error_count_different_boundary_is_new_regression(self):
  source='<html><head>'+'a'*120+'</head><body>Keep</body></html>';candidate=source.replace('Keep','Lost')
  base=localize(self.syntax(source),source,'https://example.test/');new=localize(self.syntax(candidate),candidate,'https://example.test/');self.assertEqual(compare(new,base)['state'],'violated')
 def test_missing_location_cannot_be_silently_inherited(self):
  source='<html><head>x</head><body>Keep</body></html>';raw=self.syntax(source);raw['errors'][0].pop('line');base=localize(raw,source,'https://example.test/');self.assertEqual(compare(base,base)['state'],'unverified')
