import unittest

from bs4 import BeautifulSoup
from harness.html_tools import apply_repair_plan


class RepairStyleNonceTests(unittest.TestCase):
    def repair(self, head):
        source = '<html><head>' + head + '</head><body><button id="go">Go</button></body></html>'
        candidate, result = apply_repair_plan(source, {'operations': [
            {'action': 'append_css', 'selector': '#go', 'css': '#go { min-height:24px; }'}]})
        return BeautifulSoup(candidate, 'html.parser'), result

    def test_observed_style_authorization_is_reused_without_relaxing_policy(self):
        head = '<meta http-equiv="Content-Security-Policy" content="style-src \'nonce-known\'"><style nonce="known">button {height:23px}</style>'
        soup, _ = self.repair(head)
        self.assertEqual(soup.select_one('style[data-warp-repair]')['nonce'], 'known')
        self.assertEqual(soup.select_one('meta')['content'], "style-src 'nonce-known'")
        self.assertEqual(soup.select_one('button').get_text(), 'Go')

    def test_captured_rails_nonce_survives_hidden_attributes(self):
        soup, _ = self.repair('<meta name="csp-nonce" content="captured"><style nonce="">button {height:23px}</style>')
        self.assertEqual(soup.select_one('style[data-warp-repair]')['nonce'], 'captured')

    def test_conflicting_or_script_only_nonces_do_not_invent_style_authority(self):
        for head in ('<script nonce="script-only"></script>',
                     '<style nonce="one"></style><style nonce="two"></style>',
                     '<style nonce="one"></style><meta name="csp-nonce" content="two">', ''):
            with self.subTest(head=head):
                soup, _ = self.repair(head)
                self.assertNotIn('nonce', soup.select_one('style[data-warp-repair]').attrs)


if __name__ == '__main__':
    unittest.main()
