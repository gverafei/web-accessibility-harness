import unittest
from bs4 import BeautifulSoup
from accessibility_taxonomy.selector_index import SelectorIndex

class SelectorIndexTests(unittest.TestCase):
    def test_exact_css_semantics_and_ambiguity(self):
        soup=BeautifulSoup('<main id="a" class="one"><svg><g clip-path="url(#mask)"><g opacity="1"></g><g opacity="1"></g></g></svg><a href="/one">One</a><a href="/one">Duplicate</a></main><aside class="one"><p>Text</p></aside>', 'html.parser')
        index=SelectorIndex(soup)
        for selector in ['main','main[class="one"]','#a','.one','g[clip-path="url(#mask)"] > g[opacity="1"]:nth-child(2)','a[href="/one"]','main + aside','main,aside','.one:has(p)','svg g:nth-child(1)','[id="a"]','a[href$="one"]','main > svg']:
            with self.subTest(selector=selector):
                self.assertEqual([id(n) for n in index.select(selector)],[id(n) for n in soup.select(selector)])
        self.assertEqual(len(index.select('a[href="/one"]')),2)
    def test_indexed_svg_target_does_not_scan_unrelated_tree(self):
        soup=BeautifulSoup('<svg>'+''.join('<g clip-path="url(#m%s)"><g opacity="1"></g></g>'%i for i in range(500))+'</svg>','html.parser')
        index=SelectorIndex(soup)
        soup.select=lambda *a,**k: self.fail('Indexed target unexpectedly scanned the full tree')
        self.assertEqual(len(index.select('g[clip-path="url(#m499)"] > g[opacity="1"]')),1)
