import unittest
from born_framework import framework_assets,embed_framework,framework_evidence
class RetiredFrameworkTests(unittest.TestCase):
 def test_no_download_or_injection(self):
  html='<html><head><style>p{color:red}</style></head><body>Source</body></html>'
  self.assertEqual(framework_assets('/directory-that-does-not-exist'),{})
  self.assertEqual(embed_framework(html,{}),html)
  self.assertEqual(framework_evidence({})['sha256'],{})
