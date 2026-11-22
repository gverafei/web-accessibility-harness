import unittest
from bs4 import BeautifulSoup
from born_composition import composition_units,bind_composition,composition_payload
from born_components import data_contract
from born_content import content_manifest, bind_content, layout_only


class CompositionTests(unittest.TestCase):
    def test_manifest_binding_and_iteration_keep_internal_layout(self):
        manifest=content_manifest([{'id':'c0','area':'main','element':'div','source':'<div id="original"><h2>Title</h2><p>Exact body</p></div>'}],'https://example.org/',True)
        manifest[0]['require_composition']=True
        refs=''.join('<div class="col-12" data-warp-unit="'+unit['id']+'"></div>' for unit in manifest[0]['composition_units'])
        layout='<!doctype html><html><head><title>Title</title></head><body><main><section class="row" data-warp-slot="c0">'+refs+'</section></main></body></html>'
        output=bind_content(layout,manifest)
        soup=BeautifulSoup(output,'html.parser')
        self.assertEqual(soup.select_one('#original').get_text(' ',strip=True),'Title Exact body')
        editable=layout_only(output)
        self.assertNotIn('Exact body',editable)
        self.assertEqual(len(BeautifulSoup(editable,'html.parser').select('[data-warp-unit]')),2)
        self.assertIn('col-12',editable)
        self.assertNotIn('id="original"',editable)
        self.assertEqual(BeautifulSoup(bind_content(editable,manifest),'html.parser').select_one('#original').get_text(' ',strip=True),'Title Exact body')
        with self.assertRaises(ValueError):
            bind_content(layout.replace(refs,''),manifest)

    def test_anchor_container_does_not_lock_its_whole_interior(self):
        source='<div id="content"><h2>Title</h2><p>Body</p><form action="/send"><input name="q"></form></div>'
        payload=composition_payload(source,'c0')
        self.assertEqual([u['kind'] for u in payload['units']],['h2','p','form'])
        soup=BeautifulSoup('<section>'+''.join('<div class="col" data-warp-unit="'+u['id']+'"></div>' for u in payload['units'])+'</section>','html.parser')
        bind_composition(soup.section,payload['units'],payload['shells'])
        self.assertEqual(data_contract(soup),data_contract(BeautifulSoup(source,'html.parser')))
    def test_internal_bootstrap_structure_preserves_exact_owned_data(self):
        source='<div><h2>Products</h2><p>Complete original description</p><a href="/product"><img src="/product.png" alt="Product"></a><form action="/search"><label for="q">Search</label><input id="q" name="q"><button>Go</button></form></div>'
        units=composition_units(source,'c0')
        self.assertEqual([u['kind'] for u in units],['h2','p','a','form'])
        soup=BeautifulSoup('<section class="row g-4">'+''.join('<div class="col-12 col-md-6" data-warp-unit="'+u['id']+'"></div>' for u in units)+'</section>','html.parser')
        bind_composition(soup.section,units)
        self.assertEqual(data_contract(soup),data_contract(BeautifulSoup(source,'html.parser')))

    def test_wrong_order_inventions_missing_units_and_hidden_content_fail(self):
        units=composition_units('<h2>Title</h2><p>Body</p>','c0')
        good='<div data-warp-unit="c0-u0"></div><div data-warp-unit="c0-u1"></div>'
        for markup in [good.replace('c0-u0','foreign'),good.replace('c0-u1','c0-u0'),good+'<a href="/invented">Go</a>','Invented'+good,good.replace('<div','<div class="d-md-none"',1),good.replace('c0-u0"></div>','c0-u0">Summary</div>')]:
            with self.subTest(markup=markup),self.assertRaises(ValueError):
                bind_composition(BeautifulSoup('<section>'+markup+'</section>','html.parser').section,units)

    def test_relationship_bearing_container_and_unknown_structure_stay_atomic(self):
        units=composition_units('<div id="group"><label for="q">Query</label><input id="q"></div><table><tr><td>Data</td></tr></table>','c0')
        self.assertEqual([u['kind'] for u in units],['div','table'])
