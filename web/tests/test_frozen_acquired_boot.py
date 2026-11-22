import unittest
from bs4 import BeautifulSoup
from remediation_content_contract import prepare_frozen_widget_replay
from frozen_acquired_boot import INERT, MARKER


class FrozenAcquiredBootTests(unittest.TestCase):
    def test_frozen_snapshot_keeps_markup_data_and_nonce_without_reboot_or_dehydration(self):
        raw = '<html><head><script src="/app.js" nonce="native">boot()</script><script type="module">import "/app.js"</script><script type="application/ld+json">{"name":"Page"}</script></head><body><div class="bootstrap-select"><select name="choice"><option>One</option></select><button>One</button><div class="dropdown-menu"><ul class="dropdown-menu"><li>One</li></ul></div></div><script data-warp-runtime="observed">helper()</script></body></html>'
        prepared, evidence = prepare_frozen_widget_replay(raw, captured_dom=True)
        soup = BeautifulSoup(prepared, 'html.parser')
        old = soup.select('script[' + MARKER + ']')
        self.assertEqual(len(old), 2)
        self.assertEqual(old[0]['src'], '/app.js')
        self.assertEqual(old[0]['nonce'], 'native')
        self.assertEqual(old[0].string, 'boot()')
        self.assertTrue(all(node['type'] == INERT for node in old))
        self.assertEqual(soup.select_one('script[type="application/ld+json"]').string, '{"name":"Page"}')
        self.assertNotIn('type', soup.select_one('script[data-warp-runtime]').attrs)
        self.assertEqual(len(soup.select('.bootstrap-select button')), 1)
        self.assertEqual(evidence[0]['component'], 'acquired-document-boot')
        again, changes = prepare_frozen_widget_replay(prepared, captured_dom=True)
        self.assertEqual(again, prepared)
        self.assertEqual(changes, [])
        candidate = prepared.replace('</body>', '<script>repair()</script></body>')
        replayed, changes = prepare_frozen_widget_replay(candidate)
        self.assertEqual(replayed, candidate)
        self.assertEqual(changes, [])

    def test_response_scripts_keep_original_execution_policy(self):
        raw = '<html><head><script nonce="native">boot()</script></head><body>Content</body></html>'
        prepared, evidence = prepare_frozen_widget_replay(raw)
        self.assertEqual(prepared, raw)
        self.assertEqual(evidence, [])

    def test_selected_application_snapshot_keeps_observed_background_without_boot(self):
        from remediation_content_contract import select_captured_patch_source
        network='<html><head><script>document.getElementById("hero").className="default"</script></head><body><div id="app"></div></body></html>'
        rendered='<html><head><script>document.getElementById("hero").className="default"</script></head><body><section id="hero" class="marketing"><h1>Welcome to the application with accessible navigation, information about our services and registration for new visitors.</h1><form><label>Name<input name="name"></label><button>Register</button></form></section></body></html>'
        selected,selection=select_captured_patch_source(network,rendered,base_url='https://example.org/')
        self.assertEqual(selection['selected'],'rendered_snapshot')
        prepared,_=prepare_frozen_widget_replay(selected,captured_dom=selection['selected']=='rendered_snapshot')
        soup=BeautifulSoup(prepared,'html.parser')
        self.assertEqual(soup.select_one('#hero')['class'],['marketing'])
        self.assertEqual(len(soup.select('script')),1)
        self.assertTrue(all(n.get('type')==INERT for n in soup.select('script')))
        self.assertEqual(len(soup.select('input,button')),2)
