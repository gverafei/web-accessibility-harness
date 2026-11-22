"""Synthetic decision boundaries, not estimates of real reviewer accuracy."""
import unittest
from unittest.mock import Mock
import test_harness
from harness import evidence_verifier
from harness.visual_review_policy import resolve, parse
from harness.contracts import ContractError
from harness.technical import assess

class VisualConfidenceTest(unittest.TestCase):
    def test_uncertain_and_minor_findings_warn_without_veto(self):
        for impact, confidence in [('minor', .99), ('material', .4), ('material', .899), ('material', .99)]:
            with self.subTest(impact=impact, confidence=confidence):
                row=resolve('unsupported',impact,confidence)
                self.assertEqual(row['status'],'admitted')
                self.assertEqual(row['warnings'],['unsupported'])
        self.assertEqual(resolve('degraded','material',.90)['status'],'rejected')
        self.assertEqual(resolve('usable','none',.01)['status'],'admitted')
        self.assertEqual(resolve('insufficient','material',.2)['status'],'review_required')
        self.assertEqual(resolve('blank','material',.3)['status'],'review_required')

    def test_missing_or_invalid_certainty_does_not_become_acceptance(self):
        for confidence in [None,True,'0.99',float('nan'),float('inf'),-.1,1.1]:
            with self.subTest(confidence=confidence),self.assertRaises((ContractError,ValueError)):
                resolve('degraded','material',confidence)
        for reason,impact in [('unknown','minor'),('usable','material'),('unsupported','none')]:
            with self.assertRaises(ContractError):resolve(reason,impact,.7)
        value={'reason_code':'unsupported','impact':'minor','blocking_confidence':.2,'rationale':'A small quantity may lack support.','evidence_refs':['source']}
        self.assertEqual(parse(value,['source'])['status'],'admitted')
        with self.assertRaises(ContractError):parse(dict(value,evidence_refs=['invented']),['source'])
        with self.assertRaises(ContractError):parse(dict(value,status='admitted'),['source'])

    def test_paid_brief_rationale_alias_is_exact_not_a_verdict_override(self):
        value={'reason_code':'usable','impact':'none','blocking_confidence':.01,
               'brief_rationale':'Observed controls are legible.','evidence_refs':['source']}
        row=parse(value,['source'])
        self.assertEqual(row['status'],'admitted')
        self.assertEqual(row['normalized_fields'],['brief_rationale -> rationale'])
        self.assertEqual(row['rationale'],value['brief_rationale'])
        with self.assertRaises(ContractError):parse(dict(value,rationale='Another answer'),['source'])
        with self.assertRaises(ContractError):parse({k:v for k,v in value.items()if k!='blocking_confidence'},['source'])

    def test_decisions_probability_changes_only_current_candidate_policy(self):
        f=test_harness.HarnessTest();f.setUp();self.addCleanup(f.tmp.cleanup);s=f.store
        image=s.blob(b'synthetic image','capture_screenshot',media_type='image/jpeg')
        c=s.append('capture',{'screenshot_id':image['id'],'visible':{'text':'Known fixture'}})
        a=s.append('audit',{'artifacts':{'screenshot':image['id']}})
        d=s.append('replay_admission',{'status':'admitted','reasons':[],'metrics':{},'replayed':{'text':'Known fixture'}})
        provider=Mock(campaign='fixture')
        provider.decisions.return_value={'reason':{'type':'choice','choice':'degraded'},'impact':{'type':'choice','choice':'minor'},'blocking_defect':{'type':'predicate','probability':.15}}
        model={'model':'openai/gpt-6-luna-decisions','output_modalities':['decisions'],'vision':True}
        row=evidence_verifier.verify(s,provider,'run','low-certainty',c,a,d,model,candidate=True,candidate_local=True)
        self.assertEqual(row['data']['status'],'admitted')
        self.assertEqual(row['data']['blocking_confidence'],.15)
        self.assertEqual(len(provider.decisions.call_args.args[4]),3)
        provider.decisions.return_value={'reason':{'type':'choice','choice':'degraded'}}
        legacy=evidence_verifier.verify(s,provider,'run','baseline',c,a,d,model)
        self.assertEqual(legacy['data']['status'],'rejected')
        incomplete=evidence_verifier.verify(s,provider,'run','incomplete-confidence',c,a,d,model,candidate=True,candidate_local=True)
        self.assertEqual(incomplete['data']['status'],'review_required')
        self.assertTrue(incomplete['data']['response_contract_error'])
        # A warning cannot erase independently observed broken-resource evidence.
        result=assess({'status':'completed'}, {'status':'violated'}, row['data'],fidelity_required=False,
                      usability={'status':'rejected','reasons':['broken_visible_resources']})
        self.assertEqual(result['status'],'violated')

    def test_usable_with_minor_detail_is_coherent_and_provisionally_admitted(self):
        value={'reason_code':'usable','impact':'minor','blocking_confidence':.12,
               'rationale':'The wordmark is clipped, but content and controls remain legible.',
               'evidence_refs':['candidate','usability']}
        result=parse(value,['candidate','usability'])
        self.assertEqual(result['status'],'admitted')
        self.assertEqual(result['impact'],'minor')
        self.assertEqual(result['blocking_confidence'],.12)
        self.assertEqual(result['warnings'],['minor_visual_finding'])
        with self.assertRaises(ContractError):parse(dict(value,impact='material'),['candidate','usability'])
