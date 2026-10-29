import unittest

from bs4 import BeautifulSoup
from generation_input_projection import compact_asset_catalog, compact_repeated_styles
from vera_regeneration import generation_messages


class GenerationInputProjectionTest(unittest.TestCase):
    def test_asset_catalog_round_trips_exact_variants_and_order(self):
        urls = ['https://assets.example.test/images/long-shared-name-' + str(image)
                + '.png?width=' + str(width) + '&amp;crop=1%3A1'
                for image in range(10) for width in (100, 200, 400)]
        urls += [urls[0], 'https://assets.example.test/no-query.svg']
        catalog = compact_asset_catalog(urls)
        self.assertIsNotNone(catalog)
        self.assertEqual([catalog['bases'][i] + catalog['suffixes'][j]
                          for i, j in catalog['references']], urls)
        self.assertIsNone(compact_asset_catalog(['https://example.test/x']))

    def test_last_cascade_and_content_controls_assets_are_retained(self):
        source = ('<!doctype html><html><head><style>a{color:red}</style>'
                  '<style>a{color:blue}</style></head><body>'
                  '<a href="/task">Read more</a><img src="/image.png" alt="Plot">'
                  '<input name="search"><style>a{color:red}</style></body></html>')
        projected, receipt = compact_repeated_styles(source)
        before, after = (BeautifulSoup(text, 'html.parser') for text in (source, projected))
        self.assertEqual([n.get_text() for n in after.find_all('style')],
                         ['', 'a{color:blue}', 'a{color:red}'])
        self.assertEqual([str(n) for n in before.select('a,img,input')],
                         [str(n) for n in after.select('a,img,input')])
        self.assertEqual(receipt['duplicate_style_bodies'], 1)

    def test_scopes_attributes_and_unique_documents_remain_unchanged(self):
        source = ('<style media="print">a{color:red}</style>'
                  '<style media="screen">a{color:red}</style>'
                  '<template shadowrootmode="open"><style>a{color:red}</style></template>'
                  '<style id="dynamic">a{color:red}</style><style scoped>a{color:red}</style>')
        projected, receipt = compact_repeated_styles(source)
        self.assertEqual(projected, source)
        self.assertEqual(receipt['duplicate_style_bodies'], 0)

    def test_generation_uses_projection_only_when_context_is_large(self):
        source = '<style>a{color:red}</style><a href="/x">Task</a><style>a{color:red}</style>'
        regular = generation_messages(source, 'https://example.test', creative=True,
                                      source_context_limit=10000)
        compact = generation_messages(source, 'https://example.test', creative=True,
                                      source_context_limit=20)
        self.assertEqual(regular[2]['content'], source)
        self.assertEqual(compact[2]['content'].count('a{color:red}'), 1)
        self.assertTrue(any('repeated-style-input-projection-v1' in str(message['content'])
                            for message in compact))
