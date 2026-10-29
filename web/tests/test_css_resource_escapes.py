import unittest
from bs4 import BeautifulSoup
from harness.html_tools import absolutize_resources


class CssResourceEscapesTest(unittest.TestCase):
    def style(self,value):
        dom=BeautifulSoup('<div></div><script>const keep="url(relative.png)"</script>','html.parser')
        dom.div['style']='--bg:url('+value+')'
        result=BeautifulSoup(absolutize_resources(str(dom),'https://example.org/'),'html.parser')
        self.assertEqual(result.script.string,'const keep="url(relative.png)"')
        return result.div['style']

    def test_captured_hex_slashes_with_terminating_spaces(self):
        self.assertIn('https://example.org/adobe/hero.webp?x=1',self.style(r'\2f adobe\2f hero.webp?x=1'))

    def test_six_digit_escape_consumes_only_hex_digits(self):
        self.assertIn('https://example.org/hero.webp',self.style(r'\00002fhero.webp'))

    def test_escaped_letters_and_parentheses(self):
        self.assertIn('https://example.org/images/hero).webp',self.style(r'images/\68 ero\).webp'))

    def test_quoted_url_with_escaped_quote(self):
        self.assertIn('https://example.org/hero\\".webp',self.style(r'"hero\".webp"'))

    def test_quoted_line_continuation(self):
        self.assertIn('https://example.org/foobar.webp',self.style('"foo\\\nbar.webp"'))

    def test_null_and_invalid_scalar_escape_do_not_raise(self):
        for token in (r'\0 ',r'\d800 ',r'\ffffff '):
            with self.subTest(token=token):self.assertIn('\ufffd.webp',self.style(token+'.webp'))
