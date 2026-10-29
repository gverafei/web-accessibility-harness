import unittest
from bs4 import BeautifulSoup
from frozen_carousel_replay import replay_manifest
from remediation_content_contract import prepare_frozen_widget_replay

HTML = '''<html><head></head><body>
<main><h1>Authored content</h1></main>
<script id="oracle_chat" src="//www.oracle.com/asset/web/js/oracle-chat.js"></script>
<div class="ochat_slideout" data-trackas="ochat_slideout"><ul class="ochat_slidew2"><div class="ochat_flyout"><a id="ochat-flyoutclose" aria-label="Repaired close">Close</a></div></ul></div>
<div id="ochat_modal" class="ochat_modal" data-trackas="ochat-modal"><div class="ochat_modalw1"><div class="ochat_modalw2"><button>Chat</button></div></div></div></body></html>'''


class FrozenChatReplayTests(unittest.TestCase):
    def test_preserves_every_captured_node_and_patch_with_idempotent_guard(self):
        result, evidence = prepare_frozen_widget_replay(HTML)
        before, after = BeautifulSoup(HTML, 'html.parser'), BeautifulSoup(result, 'html.parser')
        for selector in ['main', '.ochat_slideout', '#ochat_modal']:
            self.assertEqual(str(before.select_one(selector)), str(after.select_one(selector)))
        body_order = [n.get('id') or ' '.join(n.get('class', [])) for n in after.body.find_all(recursive=False)]
        self.assertLess(body_order.index('ochat_modal'), body_order.index('oracle_chat'))
        self.assertEqual(after.select_one('#ochat-flyoutclose')['aria-label'], 'Repaired close')
        self.assertEqual(evidence[0]['component'], 'oracle-chat')
        self.assertEqual(prepare_frozen_widget_replay(result), (result, []))
        self.assertEqual(replay_manifest(result)[0]['version'], evidence[0]['version'])

    def test_unknown_incomplete_or_duplicate_sdk_roots_are_not_silently_removed(self):
        for source in [HTML.replace('www.oracle.com', 'example.com'),
                       HTML.replace('oracle-chat.js', 'another-chat.js'),
                       HTML.replace('ochat_modalw1', 'unknown-wrapper'),
                       HTML.replace('</body>', '<div class="ochat_slideout">Distinct content</div></body>')]:
            self.assertEqual(prepare_frozen_widget_replay(source), (source, []))


if __name__ == '__main__':
    unittest.main()
