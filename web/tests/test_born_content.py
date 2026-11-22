import unittest
from bs4 import BeautifulSoup
from born_content import content_manifest, bind_content, layout_only


class BornContentTests(unittest.TestCase):
    def setUp(self):
        self.components=[{'id':'c0','area':'main','element':'section','source':'<section class="carousel" hidden><h2>News</h2><p>Every original word</p><a href="/news">Read</a><img src="/banner.png" alt="Banner"><form action="/search" method="post"><input type="hidden" name="token" value="original"><label for="q">Search</label><input id="q" name="q"><select name="category"><option value="a">Articles</option></select></form></section>'}]
        self.manifest=content_manifest(self.components,'https://example.org/')
        self.layout='<!doctype html><html><head><title>News</title></head><body><main><div data-warp-slot="c0"></div></main></body></html>'

    def test_assembler_preserves_text_media_and_submission_contract(self):
        soup=BeautifulSoup(bind_content(self.layout,self.manifest),'html.parser')
        self.assertIn('Every original word',soup.get_text())
        self.assertEqual(soup.img['src'],'https://example.org/banner.png')
        self.assertEqual(soup.form['action'],'https://example.org/search')
        self.assertEqual(soup.form['method'],'post')
        self.assertEqual(soup.select_one('input[name=token]')['value'],'original')
        self.assertEqual(soup.option['value'],'a')
        self.assertFalse(soup.select_one('section').has_attr('hidden'))
        self.assertNotIn('carousel',soup.select_one('section').get('class',[]))

    def test_missing_duplicate_reordered_and_populated_slots_are_invalid(self):
        for layout in [self.layout.replace('data-warp-slot="c0"','data-warp-slot="invented"'),self.layout.replace('</main>','<div data-warp-slot="c0"></div></main>'),self.layout.replace('data-warp-slot="c0"></div>','data-warp-slot="c0">Summary</div>')]:
            with self.subTest(layout=layout),self.assertRaises(ValueError): bind_content(layout,self.manifest)

    def test_layout_iteration_uses_empty_slots_not_a_rewritten_source(self):
        output=bind_content(self.layout,self.manifest)
        self.assertNotIn('Every original word',layout_only(output))
        self.assertIn('data-warp-slot="c0"',layout_only(output))

    def test_hidden_content_and_generated_concealment_are_invalid(self):
        for layout in [self.layout.replace('<main>','<main hidden>'),self.layout.replace('</head>','<style>main { display:none }</style></head>')]:
            with self.assertRaises(ValueError): bind_content(layout,self.manifest)

    def test_source_order_is_immutable(self):
        manifest=self.manifest+[{**self.manifest[0],'id':'c1'}]
        reversed_layout=self.layout.replace('<div data-warp-slot="c0"></div>','<div data-warp-slot="c1"></div><div data-warp-slot="c0"></div>')
        with self.assertRaisesRegex(ValueError,'exact order'): bind_content(reversed_layout,manifest)

    def test_fragment_can_bind_owned_block_without_a_document(self):
        output=bind_content('<article data-warp-slot="c0"></article>',self.manifest,fragment=True)
        self.assertIn('Every original word',output)
        self.assertNotIn('<html',output)

    def test_layout_cannot_invent_content_or_replace_page_with_embed(self):
        for extra in ['<p>Completely invented information</p>','<iframe src="https://example.org"></iframe>','<script>location.href="https://example.org"</script>']:
            with self.assertRaises(ValueError): bind_content(self.layout.replace('</body>',extra+'</body>'),self.manifest)

    def test_static_widgets_do_not_leave_dead_buttons_or_autoplay(self):
        from born_content import readable_fragment
        soup=BeautifulSoup(readable_fragment('<button onclick="next()">Next slide</button><form><button type="submit">Submit</button></form><video autoplay src="/a.mp4"></video>','https://example.org/'),'html.parser')
        self.assertIsNotNone(soup.find('span',string='Next slide'))
        self.assertEqual(soup.button['type'],'submit')
        self.assertFalse(soup.video.has_attr('autoplay'))
        self.assertTrue(soup.video.has_attr('controls'))

    def test_captured_select_popup_becomes_native_disclosure_not_expanded_menu(self):
        from born_content import readable_fragment
        source='<div class="bootstrap-select"><ul><li><a role="option" aria-selected="true">English</a></li><li><a role="option" aria-selected="false">Español</a></li></ul><select aria-label="Language"><option>English</option><option>Español</option></select></div>'
        soup=BeautifulSoup(readable_fragment(source,'https://example.org/'),'html.parser')
        self.assertIsNotNone(soup.details)
        self.assertFalse(soup.details.has_attr('open'))
        self.assertEqual(soup.summary.get_text(),'Language')
        self.assertEqual(len(soup.select('option')),2)
        self.assertFalse(soup.select('[aria-selected]'))
        self.assertTrue(soup.select_one('select').has_attr('disabled'))

    def test_rebuilt_content_keeps_supported_grid_not_theme_and_bounds_icons(self):
        from born_content import readable_fragment
        soup=BeautifulSoup(readable_fragment('<div class="row theme-hidden"><div class="col-md-6 original-theme"><svg viewBox="0 0 40 40"></svg><input autofocus name="q"></div></div>','https://example.org/'),'html.parser')
        self.assertIn('row',soup.div['class'])
        self.assertIn('col-md-6',soup.select_one('div div')['class'])
        self.assertNotIn('original-theme',soup.select_one('div div')['class'])
        self.assertIn('warp-icon',soup.svg['class'])
        self.assertFalse(soup.input.has_attr('autofocus'))

    def test_global_landmarks_cannot_shuffle_a_late_auxiliary_block_before_footer(self):
        from born_content import coherent_regions
        plan=[{'id':f'c{i}','area':area} for i,area in enumerate(['header','main','footer','main'])]
        result=coherent_regions(plan)
        self.assertEqual([item['area'] for item in result],['header','main','footer','footer'])
        self.assertEqual(result[-1]['planner_area'],'main')
        self.assertEqual([item['id'] for item in result],[item['id'] for item in plan])

    def test_layout_does_not_inject_or_rewrite_external_design_dependencies(self):
        source='<main><p>Source content</p></main>'
        from born_content import content_manifest
        manifest=self.manifest
        layout=self.layout
        output=bind_content(layout,manifest)
        self.assertNotIn('cdn.jsdelivr',output)
        with self.assertRaises(ValueError):bind_content(layout.replace('</body>','<script src="https://cdn.test/library.js"></script></body>'),manifest)

    def test_captured_duplicate_controls_get_unique_ids_and_local_labels(self):
        from born_content import readable_fragment
        source='<div><label for="q">First query</label><input id="q" name="q"></div><div><label for="q">Second query</label><input id="q" name="q"></div>'
        soup=BeautifulSoup(readable_fragment(source,'https://example.org/'),'html.parser')
        ids=[node['id'] for node in soup.select('[id]')]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual([node['for'] for node in soup.select('label')],ids)
        self.assertEqual(len(soup.select('input[name=q]')),2)

    def test_only_proven_cloned_navigation_is_consolidated(self):
        from born_content import readable_fragment
        source='<nav id="cloned-menu"><h2>Navigation</h2><a href="/news">News</a></nav><nav id="original-menu"><h2>Navigation</h2><a href="/news">News</a></nav><nav id="footer"><h2>Footer</h2><a href="/news">News</a></nav>'
        soup=BeautifulSoup(readable_fragment(source,'https://example.org/'),'html.parser')
        self.assertEqual(len(soup.select('nav')),2)
        self.assertIsNotNone(soup.find(id='original-menu'))
        self.assertIsNotNone(soup.find(id='footer'))

    def test_screenshot_samples_remain_readable_and_bounded(self):
        import tempfile,base64,io
        from pathlib import Path
        from PIL import Image
        from remediation_jobs import screenshot_references
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'long.png'
            Image.new('RGB',(1000,6000),'white').save(path)
            references=screenshot_references(path)
        images=[item for item in references if item['type']=='image_url']
        self.assertEqual(len(images),4)
        sizes=[Image.open(io.BytesIO(base64.b64decode(item['image_url']['url'].split(',')[1]))).size for item in images]
        self.assertEqual(sizes[1:],[(1000,1200)]*3)
        self.assertLess(sizes[0][0],300)

    def test_missing_primary_heading_uses_only_acquired_title(self):
        soup=BeautifulSoup(bind_content(self.layout,self.manifest,document_title='Original site title'),'html.parser')
        self.assertEqual(soup.h1.get_text(),'Original site title')
        self.assertEqual(soup.h1['data-warp-heading-origin'],'frozen-document-title')
        self.assertEqual(soup.main.find(True,recursive=False),soup.h1)
        from born_content import ensure_primary_heading
        self.assertEqual(ensure_primary_heading(str(soup),'Another title'),str(soup))

    def test_recomposition_bounds_footer_media_without_component_replacement(self):
        component={'id':'c0','area':'footer','element':'footer','source':'<footer><a href="/social"><img src="/ico-linkedin.svg" alt="LinkedIn"></a><img src="/brand.svg" alt="Site logo"></footer>'}
        manifest=content_manifest([component],'https://example.org/')
        soup=BeautifulSoup(manifest[0]['html'],'html.parser')
        self.assertFalse(soup.select('[data-warp-renderer]'))
        self.assertEqual(soup.find('img',alt='LinkedIn')['data-warp-icon'],'true')
        self.assertEqual(soup.find('img',alt='Site logo')['data-warp-brand'],'true')
