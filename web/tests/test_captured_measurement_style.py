"""A capture-only pause rule must not hide a finished entrance effect on replay."""
import unittest
from bs4 import BeautifulSoup
from harness.source_preparation import MEASUREMENT_STYLE, prepare, remove_measurement_style


class CapturedMeasurementStyleTests(unittest.TestCase):
    def setUp(self):
        self.rule = '<style data-harness-measurement-freeze="v3">'+MEASUREMENT_STYLE+'</style>'
        self.body = '<html><head><style>.hero{color:navy}</style>'+self.rule+'</head><body><main class="hero"><h1>Qualification</h1><p>Public description</p><a href="/exam">Exam content</a><button>Get your badge</button><img alt="Illustration" src="/hero.svg"></main></body></html>'

    def test_capture_only_rule_is_removed_with_a_receipt_and_no_other_dom_edits(self):
        cleaned, receipts = remove_measurement_style(self.body, '<html><body>Response</body></html>')
        expected = BeautifulSoup(self.body, 'html.parser')
        expected.select_one('style[data-harness-measurement-freeze]').decompose()
        self.assertEqual(cleaned, str(expected))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['marker'], 'v3')
        self.assertEqual(len(receipts[0]['sha256']), 64)
        self.assertEqual(remove_measurement_style(cleaned, ''), (cleaned, []))

    def test_authored_identical_rules_are_preserved_even_in_a_rendered_source(self):
        cleaned, receipts = remove_measurement_style(self.body, self.body)
        self.assertEqual(cleaned, self.body)
        self.assertEqual(receipts, [])

    def test_unknown_versions_altered_rules_and_ordinary_author_styles_are_preserved(self):
        for rendered in (self.body.replace('freeze="v3"','freeze="v99"'),
                         self.body.replace(MEASUREMENT_STYLE, '.hero{opacity:0}'),
                         self.body.replace(' data-harness-measurement-freeze="v3"','')):
            with self.subTest(rendered=rendered[:120]):
                self.assertEqual(remove_measurement_style(rendered, ''), (rendered, []))

    def test_source_preparation_keeps_meaningful_content_controls_and_resources(self):
        prepared, receipt = prepare('', self.body, 'https://example.com/', animation_reference=[], measurement_state={'version':'frozen-measurement-state-v11','animations':0})
        soup = BeautifulSoup(prepared, 'html.parser')
        self.assertIsNone(soup.select_one('style[data-harness-measurement-freeze]'))
        self.assertEqual(soup.h1.get_text(), 'Qualification')
        self.assertEqual(soup.button.get_text(), 'Get your badge')
        self.assertEqual(soup.img['src'], 'https://example.com/hero.svg')
        self.assertEqual(soup.a['href'], 'https://example.com/exam')
        self.assertIn('.hero{color:navy}', prepared)
        self.assertEqual(len(receipt['measurement_styles_omitted']), 1)
        self.assertFalse(receipt['stored_artifacts_modified'])

    def test_complete_paused_reference_allows_finished_effects_to_settle(self):
        reference=[{'version':'observed-css-animation-state-v1','name':'background-zoom','time':2500,'paused':True}]
        prepared, receipt=prepare('',self.body,'https://example.com/',animation_reference=reference,
            measurement_state={'version':'frozen-measurement-state-v11','animations':1})
        self.assertIsNone(BeautifulSoup(prepared,'html.parser').select_one('style[data-harness-measurement-freeze]'))
        self.assertEqual(len(receipt['measurement_styles_omitted']),1)
        self.assertEqual(reference[0]['time'],2500)
        self.assertEqual(receipt['observed_animation_count'],1)

    def test_incomplete_or_unknown_animation_state_keeps_the_pause(self):
        empty_state={'version':'frozen-measurement-state-v11','animations':0}
        active_state={'version':'frozen-measurement-state-v11','animations':1}
        cases=[(None,empty_state),([{'name':'finite-reveal','time':25,'paused':True}],active_state),([],active_state),([],None),
               ([{'version':'observed-css-animation-state-v1','paused':False}],active_state)]
        for reference,measurement in cases:
            with self.subTest(reference=reference,measurement=measurement):
                prepared, receipt = prepare('', self.body, 'https://example.com/', animation_reference=reference,measurement_state=measurement)
                self.assertIsNotNone(BeautifulSoup(prepared, 'html.parser').select_one('style[data-harness-measurement-freeze]'))
                self.assertEqual(receipt['measurement_styles_omitted'], [])
