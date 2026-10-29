import unittest
from bs4 import BeautifulSoup
from harness.observed_state import element_path
from harness.saved_widgets import prepare, SLICK_19, GLOBAL, NEWS_FEED, BOOTSTRAP


class SavedWidgetBindingTests(unittest.TestCase):
    def dropdown_fixture(self, markup):
        soup = BeautifulSoup('<html><head><script data-warp-frozen-acquired-boot src="/bootstrap.js"></script></head><body>'
                             +markup+'</body></html>','html.parser')
        capture = {'data':{'captured_url':'https://example.org/',
                          'assets':[{'url':'https://example.org/bootstrap.js','sha256':BOOTSTRAP}]}}
        return soup,capture

    def test_saved_bootstrap_sibling_menu_does_not_require_generated_ids(self):
        soup,capture = self.dropdown_fixture('<li class="nav-item dropdown"><a data-bs-toggle="dropdown" href="/academics">Academics</a>'
            '<ul class="dropdown-menu"><li><a href="/saved-option">Saved option</a></li></ul></li>')
        before = str(soup)
        widgets = prepare(soup,capture,element_path)
        self.assertEqual(len(widgets),1)
        self.assertEqual(widgets[0]['kind'],'dropdown')
        self.assertEqual(widgets[0]['binding_sha256'],BOOTSTRAP)
        self.assertEqual(str(soup),before)
        self.assertIsNone(soup.select_one('[data-bs-toggle]').get('id'))

    def test_ambiguous_empty_or_mismatched_saved_dropdowns_are_not_bound(self):
        cases = [
            '<div><a data-bs-toggle="dropdown">Open</a><ul class="dropdown-menu"><a href="/one">One</a></ul><ul class="dropdown-menu"><a href="/two">Two</a></ul></div>',
            '<div><a data-bs-toggle="dropdown">Open</a><a data-bs-toggle="dropdown">Other</a><ul class="dropdown-menu"><a href="/one">One</a></ul></div>',
            '<div><a data-bs-toggle="dropdown">Open</a><ul class="dropdown-menu"></ul></div>',
            '<div><a id="open" data-bs-toggle="dropdown">Open</a><ul class="dropdown-menu" aria-labelledby="other"><a href="/one">One</a></ul></div>',
            '<div><a id="open" data-bs-toggle="dropdown">Open</a><ul class="dropdown-menu"><a href="/one">One</a></ul><span id="open"></span></div>',
        ]
        for markup in cases:
            with self.subTest(markup=markup):
                soup,capture = self.dropdown_fixture(markup)
                self.assertEqual(prepare(soup,capture,element_path),[])

    def test_dropdown_binding_requires_the_exact_captured_library_and_script(self):
        soup,capture = self.dropdown_fixture('<div><a data-bs-toggle="dropdown">Open</a><ul class="dropdown-menu"><a href="/one">One</a></ul></div>')
        capture['data']['assets'][0]['sha256'] = '0'*64
        self.assertEqual(prepare(soup,capture,element_path),[])
        capture['data']['assets'][0]['sha256'] = BOOTSTRAP
        soup.script.attrs.pop('data-warp-frozen-acquired-boot')
        self.assertEqual(prepare(soup,capture,element_path),[])

    def fixture(self, library=SLICK_19, count=10):
        identities = (library, GLOBAL, NEWS_FEED)
        assets = [{'url': f'https://assets.example/{index}.js', 'sha256': value}
                  for index, value in enumerate(identities)]
        scripts = ''.join(f'<script data-warp-frozen-acquired-boot src="{asset["url"]}"></script>'
                          for asset in assets)
        slides = ''.join(f'<div class="slick-slide{" slick-current slick-active" if index == 0 else ""}" data-slick-index="{index}"><p>Saved item {index}</p></div>'
                         for index in range(count))
        soup = BeautifulSoup(f'<html><head>{scripts}</head><body><div class="noticias-slider slick-initialized"><div class="slick-list"><div class="slick-track">{slides}</div></div></div></body></html>', 'html.parser')
        capture = {'data': {'captured_url': 'https://example.org/', 'assets': assets}}
        return soup, capture

    def test_observed_library_and_feed_bind_all_ten_saved_slides_without_mutation(self):
        soup, capture = self.fixture()
        before = str(soup)
        widgets = prepare(soup, capture, element_path)
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0]['count'], 10)
        self.assertEqual(widgets[0]['active'], 0)
        self.assertEqual(widgets[0]['show'], 1)
        self.assertEqual(widgets[0]['step'], 1)
        self.assertEqual(widgets[0]['binding_sha256'], [SLICK_19, GLOBAL, NEWS_FEED])
        self.assertEqual(str(soup), before)

    def test_unknown_library_or_missing_feed_does_not_inherit_a_binding(self):
        soup, capture = self.fixture(library='0' * 64)
        self.assertEqual(prepare(soup, capture, element_path), [])
        soup, capture = self.fixture()
        capture['data']['assets'].pop()
        self.assertEqual(prepare(soup, capture, element_path), [])

    def test_duplicate_slide_indices_are_not_reinterpreted(self):
        soup, capture = self.fixture()
        soup.select('.slick-slide')[1]['data-slick-index'] = '0'
        self.assertEqual(prepare(soup, capture, element_path), [])

    def test_other_widget_types_do_not_inherit_news_configuration(self):
        soup, capture = self.fixture()
        soup.select_one('.noticias-slider')['class'] = ['agenda-deck', 'slick-initialized']
        self.assertEqual(prepare(soup, capture, element_path), [])
