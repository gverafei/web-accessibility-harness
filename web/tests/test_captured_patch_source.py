import unittest
from remediation_content_contract import select_captured_patch_source


class CapturedPatchSourceTests(unittest.TestCase):
    def test_rendered_scripts_replay_authored_roster_once_with_original_urls(self):
        network = '<html><body><script src="/loader.js"></script><script src="//cdn.example/a.js"></script><script>start()</script></body></html>'
        rendered = '<html><body><p>' + 'Captured content ' * 10 + '</p><script src="https://example.test/loader.js"></script><script src="https://example.test/loader.js"></script><script src="https://cdn.example/a.js"></script><script>start()</script><script>generatedWrite()</script><script type="application/ld+json">{"name":"Page"}</script></body></html>'
        selected, evidence = select_captured_patch_source(network, rendered, base_url='https://example.test/')
        self.assertEqual(selected.count('loader.js'), 1)
        self.assertIn('https://cdn.example/a.js', selected)
        self.assertIn('start()', selected)
        self.assertNotIn('generatedWrite()', selected)
        self.assertIn('application/ld+json', selected)
        self.assertEqual(len(evidence['generated_scripts_removed']), 2)

    def test_dynamic_empty_shell_uses_exact_captured_document(self):
        network = '<html><body><noscript>Enable JavaScript</noscript><div id="root"></div></body></html>'
        rendered = '<html><body><div id="root"><p>' + 'Recorded page content ' * 10 + '</p></div></body></html>'
        selected, evidence = select_captured_patch_source(network, rendered)
        self.assertEqual(selected, rendered)
        self.assertEqual(evidence['selected'], 'rendered_snapshot')
        self.assertEqual(evidence['network_text_length'], 0)

    def test_existing_response_content_and_widgets_are_preserved(self):
        network = '<html><body><div id="root">Loading</div></body></html>'
        rendered = '<html><body>' + 'Captured content ' * 10 + '</body></html>'
        self.assertEqual(select_captured_patch_source(network, rendered), (network, None))

    def test_form_only_network_is_not_treated_as_empty(self):
        network = '<html><body><input name="query"></body></html>'
        rendered = '<html><body>' + 'Captured content ' * 10 + '</body></html>'
        self.assertEqual(select_captured_patch_source(network, rendered), (network, None))

    def test_missing_or_empty_rendered_body_never_substitutes(self):
        network = '<html><body><div id="root"></div></body></html>'
        for rendered in ('<html><head></head></html>', network):
            self.assertEqual(select_captured_patch_source(network, rendered), (network, None))

    def test_measured_dynamic_control_uses_captured_dom(self):
        network = '<html><body><p>Server content</p></body></html>'
        rendered = '<html><body><p>' + 'Captured content ' * 10 + '</p><select name="country"><option>Mexico</option></select></body></html>'
        selected, evidence = select_captured_patch_source(network, rendered, ['select[name="country"]'])
        self.assertEqual(selected, rendered)
        self.assertEqual(evidence['captured_only_selectors'], ['select[name="country"]'])

    def test_unmatched_or_invalid_selector_never_causes_substitution(self):
        network = '<html><body><p>Server content</p></body></html>'
        rendered = '<html><body><p>' + 'Captured content ' * 10 + '</p></body></html>'
        self.assertEqual(select_captured_patch_source(network, rendered, ['#missing', '[[bad']), (network, None))
