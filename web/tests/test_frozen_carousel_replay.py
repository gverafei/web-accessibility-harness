import hashlib
import unittest
from bs4 import BeautifulSoup
from remediation_content_contract import prepare_frozen_widget_replay, captured_widget_replay_warnings
from frozen_carousel_replay import RUNTIME, replay_manifest


def captured_widget(count=3, domain='https://assets.example.org', owner='gallery', clones=False):
    slides = ''.join(f'<div class="slick-slide slick-active{" slick-current" if i == 0 else ""}" data-slick-index="{i}" role="tabpanel"><div><article><a href="{domain}/{i}"><img src="{domain}/{i}.jpg" alt="Photo {i}"></a><button aria-label="Candidate label {i}">Action {i}</button></article></div></div>' for i in range(count))
    if clones:
        slides += slides.split('</article>')[0].replace('slick-slide slick-active slick-current', 'slick-slide slick-cloned').replace('data-slick-index="0"', 'data-slick-index="-1"') + '</article></div></div>'
    return f'<html><head><script src="{domain}/jquery.js"></script><script src="{domain}/slick.min.js"></script></head><body><div class="{owner} slick-initialized slick-slider"><button class="slick-prev" aria-label="Previous captured image">Back</button><div class="slick-list"><div class="slick-track">{slides}</div></div><button class="slick-next" aria-label="Next captured image">Forward</button><ul class="slick-dots"><li><button>1</button></li></ul></div><p id="outside">Unrelated content</p><script>window.keepOutside = true;</script></body></html>'


class FrozenCarouselReplayTests(unittest.TestCase):
    def test_adapter_uses_structure_not_domain_class_or_item_count(self):
        for count, domain, owner in [(1, 'https://one.example', 'product'), (3, 'https://two.example', 'news'), (7, 'https://three.example', 'photos')]:
            with self.subTest(count=count):
                source = captured_widget(count, domain, owner)
                html, evidence = prepare_frozen_widget_replay(source)
                before, after = BeautifulSoup(source, 'html.parser'), BeautifulSoup(html, 'html.parser')
                root = after.select_one('[data-warp-frozen-slick]')
                self.assertEqual(len(root.find_all('article', recursive=False)), count)
                self.assertEqual([str(n) for n in before.select('article')], [str(n) for n in after.select('article')])
                self.assertEqual(str(before.select_one('#outside')), str(after.select_one('#outside')))
                self.assertIn('window.keepOutside = true;', html)
                self.assertEqual(evidence[0]['slides'], count)
                self.assertEqual(evidence[0]['runtime_sha256'], hashlib.sha256(RUNTIME.read_bytes()).hexdigest())
                self.assertIn('Previous captured image', root['data-warp-slick-options'])
                self.assertEqual(len(after.select('script[src]')), 2)
                self.assertEqual(prepare_frozen_widget_replay(html), (html, []))
                self.assertEqual(replay_manifest(html)[0]['runtime_sha256'], evidence[0]['runtime_sha256'])

    def test_only_exact_generated_clones_are_consolidated(self):
        html, evidence = prepare_frozen_widget_replay(captured_widget(clones=True))
        self.assertEqual(evidence[0]['duplicate_presentations_removed'], 1)
        self.assertEqual(len(BeautifulSoup(html, 'html.parser').select('article')), 3)
        unique = captured_widget(clones=True).replace('data-slick-index="-1" role="tabpanel"><div><article>', 'data-slick-index="-1" role="tabpanel"><div><article><p>Unique information</p>')
        self.assertEqual(prepare_frozen_widget_replay(unique), (unique, []))

    def test_ambiguous_or_unknown_widgets_remain_unchanged(self):
        source = captured_widget()
        for value in [source.replace('slick.min.js', 'unknown.js'),
                      source.replace('<div class="slick-list">', '<p>Help</p><div class="slick-list">'),
                      source.replace('data-slick-index="1"', 'data-slick-index="0"'),
                      source.replace('<div class="slick-track">', '<div class="slick-track"><span>Help</span>'),
                      source.replace('class="gallery slick-initialized slick-slider"', 'class="gallery slick-initialized slick-slider" data-slick="invalid"')]:
            self.assertEqual(prepare_frozen_widget_replay(value), (value, []))

    def test_authored_wrapper_semantics_are_not_discarded(self):
        source = captured_widget()
        for value in [source.replace('role="tabpanel"', 'role="region"'),
                      source.replace('role="tabpanel"', 'role="tabpanel" aria-label="Gallery section"'),
                      source.replace('<div><article>', '<div data-author-content="true"><article>')]:
            self.assertEqual(prepare_frozen_widget_replay(value), (value, []))

    def test_observed_broken_track_and_duplicated_slides_are_reported(self):
        source = captured_widget()
        self.assertEqual(captured_widget_replay_warnings(source, source), [])
        warnings = captured_widget_replay_warnings(source, captured_widget(6))
        self.assertEqual(warnings[0]['rendered_count'], 6)
        warnings = captured_widget_replay_warnings(source, source.replace('slick-track', 'broken-track'))
        self.assertEqual(warnings[0]['component'], 'slick')

    def test_no_site_specific_tokens_in_runtime(self):
        runtime = RUNTIME.read_text()
        for text in ('uv.mx', 'noticias-slider', 'FeedNoticias', 'Universidad Veracruzana'):
            self.assertNotIn(text, runtime)
