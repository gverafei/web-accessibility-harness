import json
import unittest
from unittest.mock import Mock
from bs4 import BeautifulSoup
from harness.controller import materialize, preserved
from harness.selection import select
from remediation_interventions import VERSION, approach, presentation
from remediation_approaches import constrain_plan
from remediation_jobs import repair_context
from remediation_structure_contract import assess
from vera_regeneration import generation_messages, generation_evidence, generation_text

SOURCE='<!doctype html><html><head><style>.panel{color:#123}</style></head><body><main><h1>Title</h1><div class="panel"><span id="label">Email</span><input id="field" name="email"></div><p id="next">Next</p></main></body></html>'


class PreservationFirstGuardsTests(unittest.TestCase):
    def context(self,selector):
        return repair_context(SOURCE,[{'id':'fixture','nodes':[{'target':[selector]}]}],[])

    def execute(self,op,wire=3,context=None):
        plan={'operations':[op],'root_causes':[{'id':'cause','selectors':[op['selector']],'depends_on':[],'operation_indexes':[0]}]}
        return materialize(SOURCE,json.dumps(plan),wire,'https://example.org/',intervention_version=VERSION,patch_context=context)

    def test_minimal_scope_cannot_replace_or_rewrite_behavior(self):
        ops=[{'action':'replace_element','selector':'#label','html':'<label id="label">Email</label>'},
             {'action':'append_javascript','selector':'#field','javascript':'document.querySelector("#field").focus();'}]
        candidate,details=materialize(SOURCE,json.dumps({'operations':ops}),1,'https://example.org/',intervention_version=VERSION)
        self.assertFalse(details['applied'])
        self.assertEqual(BeautifulSoup(candidate,'html.parser').find(id='label').name,'span')

    def test_structural_policy_permits_equivalent_semantic_replacement_with_complete_evidence(self):
        op={'action':'replace_element','selector':'#label','html':'<label id="label" for="field">Email</label>'}
        candidate,details=self.execute(op,context=self.context('#label'))
        self.assertEqual(len(details['applied']),1)
        self.assertEqual(BeautifulSoup(candidate,'html.parser').find(id='label').name,'label')
        self.assertEqual(preserved(SOURCE,candidate,'https://example.org/',structure_first=True)['status'],'passed')

    def test_truncated_or_missing_replacement_evidence_never_executes(self):
        op={'action':'replace_element','selector':'#label','html':'<label id="label">Email</label>'}
        context=json.loads(self.context('#label'));context['affected_nodes'][0]['html_truncated']=True
        for evidence in (None,context):
            with self.subTest(evidence=evidence):
                _,details=self.execute(op,context=evidence)
                self.assertFalse(details['applied'])

    def test_native_task_mutation_is_rejected_before_execution(self):
        for name in ('name','type','formaction','onchange'):
            with self.subTest(name=name):
                _,details=self.execute({'action':'set_attribute','selector':'#field','name':name,'value':'changed'})
                self.assertFalse(details['applied'])

    def test_scoped_focus_css_is_permitted_but_global_layout_override_is_not(self):
        allowed={'action':'append_css','selector':'#field','css':'#field:focus-visible {outline:2px solid #123;outline-offset:2px}'}
        candidate,details=self.execute(allowed)
        self.assertTrue(details['applied'])
        self.assertEqual(BeautifulSoup(candidate,'html.parser').find('style',attrs={'data-warp-repair':'true'}).parent.name,'head')
        for css in ('body {display:none}', '#next {color:#123}', '#field {position:absolute}'):
            with self.subTest(css=css):
                _,details=self.execute(dict(allowed,css=css));self.assertFalse(details['applied'])

    def test_local_opacity_can_restore_visibility_but_never_hide_content(self):
        operation = {'action': 'append_css', 'selector': '.panel',
                     'css': '.panel {opacity: 1 !important}'}
        for wire in (1, 3):
            _, details = self.execute(operation, wire=wire)
            self.assertTrue(details['applied'])
            for value in ('0', '.36', 'inherit', 'calc(1)', '1; visibility:hidden'):
                _, details = self.execute(dict(operation, css='.panel {opacity: ' + value + '}'), wire=wire)
                self.assertFalse(details['applied'])

    def test_failed_dependency_scope_prevents_partial_coordinated_execution(self):
        ops=[{'action':'set_attribute','selector':'#field','name':'aria-labelledby','value':'label'},
             {'action':'set_attribute','selector':'#label','name':'onclick','value':'changed'}]
        plan={'operations':ops}
        bounded,rejected=constrain_plan(SOURCE,plan,approach(3,VERSION))
        self.assertEqual(bounded['operations'],[]);self.assertEqual(len(rejected),2)

    def test_reordered_source_text_is_rejected_even_when_vocabulary_is_identical(self):
        candidate=SOURCE.replace('<span id="label">Email</span>','<span id="label">Next</span>').replace('<p id="next">Next</p>','<p id="next">Email</p>')
        self.assertEqual(assess(SOURCE,candidate,'https://example.org/')['status'],'violated')

    def test_moving_a_field_between_forms_changes_its_native_task_contract(self):
        source='<form id="a" action="/subscribe"><input id="email" name="email"></form><form id="b" action="/search"></form>'
        candidate='<form id="a" action="/subscribe"></form><form id="b" action="/search"><input id="email" name="email"></form>'
        self.assertEqual(assess(source,candidate,'https://example.org/')['status'],'violated')
        self.assertEqual(assess(source,source.replace('action="/subscribe"','action="https://example.org/subscribe"'),'https://example.org/')['status'],'passed')

    def test_declared_submit_behavior_and_state_are_protected(self):
        source='<form><button type="submit" formaction="/save" name="submit" value="save">Save</button><input type="checkbox" name="agree" checked></form>'
        for candidate in (source.replace('formaction="/save"','formaction="/delete"'),source.replace(' checked','')):
            self.assertEqual(assess(source,candidate,'https://example.org/')['status'],'violated')

    def test_invalid_model_action_is_rejected_without_remapping_to_another_policy(self):
        providers=Mock();providers.decisions.return_value={'action':{'type':'choice','choice':'P5:m'}}
        manifest={'intervention_version':VERSION,'workers':[{'id':'m','model':'fixture'}]}
        with self.assertRaisesRegex(ValueError,'inadmissible'):
            select(providers,'run','key',manifest,{'level':6,'worker_id':'m','selector':'decisions'},{},{'iteration':0})

    def test_current_and_historical_labels_remain_distinct(self):
        legacy=presentation({'accessibility_priority':55})
        current=presentation({'accessibility_priority':55,'intervention_version':VERSION})
        self.assertEqual(legacy['presentation_level'],3);self.assertEqual(current['presentation_level'],2)
        self.assertNotEqual(legacy['preservation_filter'],current['preservation_filter'])

    def test_markdown_first_request_keeps_original_styles_structure_tasks_and_capture(self):
        source=SOURCE.replace('<div class="panel">','<div class="panel"><form action="/save">').replace('</div>','</form></div>')
        capture={'type':'image_url','image_url':{'url':'data:image/png;base64,fixture'}}
        messages=generation_messages('# Title\nEmail\nNext','https://example.org/',reference_document=source,framework='source',visual_references=[capture])
        text=generation_text(messages);evidence=generation_evidence(messages,'markdown','local',.05)
        self.assertEqual(evidence['visual_reference_count'],1)
        self.assertIn('.panel{color:#123}',text);self.assertIn('/save',text);self.assertIn('panel',text)
        self.assertNotIn('Mandatory design base',text)
        self.assertNotIn('greater design freedom',text)
        self.assertNotIn('bootstrap@',text)
