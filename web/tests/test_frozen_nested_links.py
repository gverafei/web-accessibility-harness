import unittest
from bs4 import BeautifulSoup
from remediation_content_contract import prepare_frozen_widget_replay
from frozen_nested_links import MARKER


class FrozenNestedLinksTests(unittest.TestCase):
    def test_captured_dom_preserves_targets_attributes_and_restores_once(self):
        raw = '<html><head><script nonce="observed">void 0</script></head><body><a href="/outer"><a href="/inner" target="_blank" rel="nofollow noopener" class="brand" aria-label="Brand">Brand</a><span>Headline</span></a></body></html>'
        prepared, evidence = prepare_frozen_widget_replay(raw, captured_dom=True)
        soup = BeautifulSoup(prepared, 'html.parser')
        node = soup.select_one('a > span[' + MARKER + ']')
        self.assertEqual(node['class'], ['brand'])
        self.assertEqual(node['aria-label'], 'Brand')
        self.assertNotIn('href', node.attrs)
        self.assertIn('"href":"/inner"', node[MARKER])
        helper = soup.select_one('script[data-warp-frozen-nested-links-runtime]')
        self.assertEqual(helper['nonce'], 'observed')
        self.assertEqual(evidence[0]['component'], 'captured-nested-links')
        again, second = prepare_frozen_widget_replay(prepared, captured_dom=True)
        self.assertEqual(again, prepared)
        self.assertEqual(second, [])

    def test_response_markup_is_never_reinterpreted_as_acquired_topology(self):
        raw = '<html><body><a href="/outer"><a href="/inner">Brand</a>Headline</a></body></html>'
        prepared, evidence = prepare_frozen_widget_replay(raw)
        self.assertEqual(prepared, raw)
        self.assertEqual(evidence, [])
        captured, evidence = prepare_frozen_widget_replay(raw, captured_dom=True)
        self.assertIn(MARKER, captured)
        self.assertEqual(len(evidence), 1)
