import copy
import json
import tempfile
import unittest
from harness.environment import Environment
from harness.store import Store
from harness.replay_admission import compare
from remediation_structure_contract import assess
from vera_regeneration import generation_messages, generation_text


class NativeControlPreservationTests(unittest.TestCase):
    def reference(self):
        return {'version':'observed-native-control-state-v1','document_sha256':'fixture',
                'records':[{'id':'date','path':'fixture-path','signature':{'tag':'select'},
                            'state':{'value':'','selected_indexes':[0]},'restorable':True}]}

    def test_runtime_option_change_is_rejected_even_when_visible_control_labels_match(self):
        original={'text':'A complete original source page with meaningful content and controls','controls':['SELECT||date'],'native_control_reference':self.reference()}
        candidate=copy.deepcopy(original)
        candidate['native_control_reference']['records'][0]['state']={'value':'Jan','selected_indexes':[1]}
        result=compare(original,candidate)
        self.assertEqual(result['status'],'rejected')
        self.assertIn('native_control_state_changed',result['reasons'])
        self.assertEqual(result['metrics']['native_control_state_coverage'],0)
        self.assertEqual(compare(original,copy.deepcopy(original))['status'],'admitted')

    def test_missing_legacy_native_properties_are_unknown_not_zero_or_fabricated(self):
        evidence={'text':'A complete original source page with meaningful content and controls','controls':['SELECT||date']}
        result=compare(evidence,evidence)
        self.assertIsNone(result['metrics']['native_control_state_coverage'])

    def test_anonymous_control_wrapper_change_preserves_state_and_multiplicity(self):
        reference=self.reference()
        reference['records'][0].update(id=None,signature={'tag':'button','attributes':[['type','button']], 'owner':None},state={'value':''})
        reference['records'].append(copy.deepcopy(reference['records'][0]))
        original={'text':'A complete original source page with meaningful content and controls','native_control_reference':reference}
        candidate=copy.deepcopy(original)
        for i,record in enumerate(candidate['native_control_reference']['records']):record['path']='new-wrapper-'+str(i)
        self.assertEqual(compare(original,candidate)['status'],'admitted')
        candidate['native_control_reference']['records'].pop()
        self.assertIn('native_control_state_changed',compare(original,candidate)['reasons'])

    def test_anonymous_controls_still_require_same_contract_state_and_owner(self):
        reference=self.reference();reference['records'][0]['id']=None
        original={'text':'A complete original source page with meaningful content and controls','native_control_reference':reference}
        for field,value in [('state',{'value':'Jan','selected_indexes':[1]}),('signature',{'tag':'button'}),('signature',{'tag':'select','owner':{'id':'different-form'}})]:
            candidate=copy.deepcopy(original);candidate['native_control_reference']['records'][0][field]=value
            self.assertIn('native_control_state_changed',compare(original,candidate)['reasons'])

    def test_manifest_carries_observed_state_without_modifying_source_document(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory+'/store')
            env=Environment(store,results=directory+'/results')
            source='<html><body><select id="date"><option disabled>Month</option></select></body></html>'
            capture={'id':'fixture-capture','data':{'captured_url':'https://example.org/','assets':[],'scope':'Synthetic native-state fixture',
                                                'native_control_reference':self.reference()}}
            path,_=env.origin_manifest(capture,source,'fixture-campaign','fixture-audit',{})
            with open(path) as stream:manifest=json.load(stream)
            self.assertEqual(manifest['native_control_reference'],self.reference())
            self.assertEqual(manifest['document'],source)

    def test_regeneration_receives_actual_properties_alongside_declared_html(self):
        source='<html><body><select id="date"><option disabled>Month</option><option>January</option></select></body></html>'
        messages=generation_messages('# Date','https://example.org/',reference_document=source,
                                     framework='source',observed_native_controls=self.reference())
        text=generation_text(messages)
        self.assertIn('observed_native_controls',text)
        self.assertIn('selected_indexes',text)
        with self.assertRaises(ValueError):
            generation_messages('source','https://example.org/',observed_native_controls={'records':[]})

    def test_option_selection_and_disabled_options_remain_part_of_declared_contract(self):
        source='<select><option value="" disabled selected>Choose</option><option value="one">One</option></select>'
        for candidate in (source.replace(' selected',''),source.replace(' disabled','')):
            self.assertEqual(assess(source,candidate,'https://example.org/')['status'],'violated')
        self.assertEqual(assess(source,source.replace('selected','selected="selected"'),'https://example.org/')['status'],'passed')

    def test_boolean_equivalence_and_same_endpoint_form_ownership(self):
        source='<form id="one" action="/submit"><input name="first" required></form><form id="two" action="/submit"><input name="second"></form>'
        self.assertEqual(assess(source,source.replace(' required',' required="required"'),'https://example.org/')['status'],'passed')
        candidate='<form id="one" action="/submit"><input name="second"></form><form id="two" action="/submit"><input name="first" required></form>'
        self.assertEqual(assess(source,candidate,'https://example.org/')['status'],'violated')
