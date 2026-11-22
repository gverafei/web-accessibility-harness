import unittest
from bs4 import BeautifulSoup
from born_components import render_components,data_contract,COMPONENT_CSS
from born_content import content_manifest,bind_content
from reconstruction_agents import assemble_areas


class VerifiedComponentTests(unittest.TestCase):
    def test_cards_rebuild_with_bootstrap_and_preserve_every_record(self):
        source='<div><article data-warp-source-kind="card" id="one"><h2>First</h2><a href="/first">Read</a><img src="/first.png" alt="First photo"></article><article data-warp-source-kind="card"><h2>Second</h2><a href="/second">Read second</a></article></div>'
        html,evidence=render_components(source,'main')
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(data_contract(soup),data_contract(BeautifulSoup(source,'html.parser')))
        self.assertEqual(len(soup.select('.card > .card-body')),2)
        self.assertEqual(evidence['components']['cards-grid'],1)

    def test_source_record_signals_survive_theme_retirement(self):
        source='<div><div class="views-row original-theme"><h3>A story</h3><a href="/story">Read</a><img src="/story.png" alt="Photo"></div></div>'
        component={'id':'c0','area':'main','element':'section','source':source}
        old=content_manifest([component],'https://example.org/')
        new=content_manifest([component],'https://example.org/',verified_components=True)
        self.assertNotIn('component_renderer',old[0])
        self.assertNotIn('card-body',old[0]['html'])
        self.assertIn('card-body',new[0]['html'])
        self.assertNotIn('original-theme',new[0]['html'])
        self.assertEqual(data_contract(BeautifulSoup(old[0]['html'],'html.parser')),data_contract(BeautifulSoup(new[0]['html'],'html.parser')))

    def test_form_relationships_options_and_hidden_tokens_are_immutable(self):
        source='<form action="/save" method="post"><input type="hidden" name="token" value="secret"><label for="email">Email</label><input id="email" type="email" name="email" required aria-describedby="help"><p id="help">Help</p><select name="kind"><option value="a" selected>First</option><option value="b">Second</option></select><button type="submit" name="submit" value="yes">Save</button></form>'
        html,_=render_components(source,'main')
        self.assertEqual(data_contract(BeautifulSoup(source,'html.parser')),data_contract(BeautifulSoup(html,'html.parser')))
        self.assertIsNotNone(BeautifulSoup(html,'html.parser').select_one('.btn-primary'))

    def test_nested_records_and_tabular_data_are_not_flattened(self):
        source='<article data-warp-source-kind="card"><h2>Data</h2><table><caption>Values</caption><tr><th scope="col">Name</th></tr><tr><td>A</td></tr></table></article>'
        html,evidence=render_components(source,'main')
        soup=BeautifulSoup(html,'html.parser')
        self.assertFalse(soup.select('.card-body'))
        self.assertEqual(soup.th['scope'],'col')
        self.assertEqual(evidence['components'],{'table':1})

    def test_unknown_content_is_not_summarized_or_guessed_into_a_card(self):
        source='<section><h2>Legal</h2><p>All terms and conditions.</p><a href="/legal">Terms</a></section>'
        html,evidence=render_components(source,'main')
        self.assertEqual(data_contract(BeautifulSoup(source,'html.parser')),data_contract(BeautifulSoup(html,'html.parser')))
        self.assertEqual(evidence['components'],{})

    def test_footer_icons_are_bounded_without_dropping_accessible_names(self):
        source='<nav aria-label="Social"><a href="/social" aria-label="LinkedIn"><svg viewBox="0 0 512 512"><path d="M0 0"></path></svg></a></nav>'
        html,_=render_components(source,'footer')
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(soup.a['aria-label'],'LinkedIn')
        self.assertEqual(soup.svg['viewbox'],'0 0 512 512')
        self.assertIn('[data-warp-renderer="footer"] svg',COMPONENT_CSS)
        self.assertIsNotNone(soup.select_one('[data-warp-renderer=footer]'))

    def test_full_and_fragmented_documents_receive_renderer_css(self):
        component={'id':'c0','area':'footer','element':'footer','source':'<footer><a href="/legal">Legal</a></footer>'}
        manifest=content_manifest([component],'https://example.org/',verified_components=True)
        layout='<html><head><title>Page</title></head><body><main></main><footer><div data-warp-slot="c0"></div></footer></body></html>'
        self.assertIn(COMPONENT_CSS,bind_content(layout,manifest))
        fragment=bind_content('<div data-warp-slot="c0"></div>',manifest,fragment=True)
        assembled=assemble_areas([{'area':'footer','key':'c0','html':fragment}], 'Page')
        self.assertIn(COMPONENT_CSS,assembled)

    def test_external_svg_icons_and_brand_are_sized_without_changing_data(self):
        source='<a href="/social"><img src="/ico-linkedin.svg" alt="LinkedIn"><img src="/icons8-external-link.svg" alt="External link icon"></a><img src="/brand.svg" alt="Company logo"><img src="/report.svg" alt="Report figure">'
        html,_=render_components(source,'footer')
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(len(soup.select('img[data-warp-icon]')),2)
        self.assertEqual(len(soup.select('img[data-warp-brand]')),1)
        self.assertFalse(soup.find('img',alt='Report figure').has_attr('data-warp-icon'))
        self.assertEqual(data_contract(soup),data_contract(BeautifulSoup(source,'html.parser')))

    def test_rebuilt_grid_does_not_inherit_conflicting_bootstrap_column_widths(self):
        source='<div class="row g-4"><article class="col-md-6" data-warp-source-kind="card"><h2>A</h2></article><article class="col-md-6" data-warp-source-kind="card"><h2>B</h2></article></div>'
        html,_=render_components(source,'main')
        soup=BeautifulSoup(html,'html.parser')
        self.assertNotIn('row',soup.div.get('class',[]))
        self.assertFalse(soup.select('.col-md-6'))


if __name__=='__main__': unittest.main()
