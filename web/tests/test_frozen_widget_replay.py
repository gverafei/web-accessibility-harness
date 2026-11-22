import unittest
from bs4 import BeautifulSoup
from remediation_content_contract import prepare_frozen_widget_replay, captured_widget_replay_warnings


class FrozenWidgetReplayTests(unittest.TestCase):
    source='''<html><body><form action="/translate" method="post"><div class="bootstrap-select"><button type="button" class="dropdown-toggle">English</button><div class="dropdown-menu"><ul class="dropdown-menu"><li><a>English</a></li><li><a>Español</a></li></ul></div><select id="language" name="language" class="selectpicker" aria-label="Language" onchange="translate(this.value)" tabindex="-98"><option value="en" selected>English</option><option value="es">Español</option></select></div><input type="hidden" name="token" value="original"></form><script src="/original.js"></script></body></html>'''

    def test_dehydrates_only_generated_dom_and_retains_native_task_data(self):
        html,evidence=prepare_frozen_widget_replay(self.source)
        soup=BeautifulSoup(html,'html.parser')
        self.assertEqual(len(evidence),1)
        self.assertFalse(soup.select('.bootstrap-select'))
        self.assertEqual(soup.select_one('select')['onchange'],'translate(this.value)')
        self.assertEqual(soup.select_one('select')['name'],'language')
        self.assertEqual([(x['value'],x.get_text()) for x in soup.select('option')],[('en','English'),('es','Español')])
        self.assertTrue(soup.option.has_attr('selected'))
        self.assertEqual(soup.form['method'],'post')
        self.assertEqual(soup.input['value'],'original')
        self.assertEqual(soup.script['src'],'/original.js')
        self.assertFalse(soup.select_one('select').has_attr('tabindex'))
        self.assertEqual(prepare_frozen_widget_replay(html),(html,[]))

    def test_no_scripts_no_replay_normalization(self):
        source=self.source.replace('<script src="/original.js"></script>','')
        self.assertEqual(prepare_frozen_widget_replay(source),(source,[]))

    def test_unknown_choices_help_controls_or_structure_are_not_removed(self):
        for source in [self.source.replace('<a>Español</a>','<a>Other choice</a>'),self.source.replace('</ul>','</ul><p>Important help</p>'),self.source.replace('</select>','</select><input name="extra">'),self.source.replace('</select>','</select><p>Other content</p>'),self.source.replace('>English</button>','>Translate now</button>')]:
            with self.subTest(source=source): self.assertEqual(prepare_frozen_widget_replay(source),(source,[]))

    def test_real_author_tab_order_is_retained(self):
        html,_=prepare_frozen_widget_replay(self.source.replace('tabindex="-98"','tabindex="0"'))
        self.assertEqual(BeautifulSoup(html,'html.parser').select_one('select')['tabindex'],'0')

    def test_compound_translator_is_not_treated_as_a_plain_bootstrap_select(self):
        source=self.source.replace('class="selectpicker"','class="gt_selector notranslate"')
        self.assertEqual(prepare_frozen_widget_replay(source),(source,[]))

    def test_warning_requires_measured_duplicate_control_data(self):
        one='<div class="bootstrap-select"><select name="language"><option value="en">English</option></select></div>'
        self.assertEqual(captured_widget_replay_warnings(one,one),[])
        warnings=captured_widget_replay_warnings(one,one+one)
        self.assertEqual(warnings[0]['source_count'],1)
        self.assertEqual(warnings[0]['rendered_count'],2)
        self.assertEqual(captured_widget_replay_warnings(one,one+one.replace('English','Another option')),[])
