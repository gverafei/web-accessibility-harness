import tempfile
import unittest
from unittest.mock import Mock
from accessibility_taxonomy import CATALOG, RULES, summarize, compare, contextual_review
from harness.store import Store
from harness.contracts import ContractError


def opportunity(key, status, kind='image-alt-not-descriptive', **extra):
    return dict(opportunity_id=key,type=kind,status=status,context='<img alt="image">',**extra)


class OutcomesTest(unittest.TestCase):
    def test_frozen_catalog_is_not_a_claim_of_112_implemented_checks(self):
        self.assertEqual(len(RULES),99)
        self.assertEqual(RULES['frame-title']['category'],'Syntactic')
        self.assertNotIn('color-only-distinction',RULES)
        self.assertEqual(CATALOG['source']['commit'],'bf45666aa281af7cca23aaabd9bfe3bd802b9036')

    def test_unknown_is_not_zero_or_passed(self):
        row=summarize([opportunity('a','failed'),opportunity('b','insufficient_evidence')])['categories']['Semantic']
        self.assertEqual(row['failed'],1);self.assertEqual(row['observed_burden'],5)
        self.assertIsNone(row['burden']);self.assertEqual(row['coverage'],.5)
        self.assertIsNone(summarize([])['categories']['Semantic']['burden'])
        unknown=summarize([opportunity('x','failed','unknown-rule')])['categories']['Unclassified']
        self.assertEqual(unknown['unknown_impact'],1);self.assertIsNone(unknown['burden'])

    def test_deletion_not_repair_and_new_defects_not_hidden(self):
        result=compare([opportunity('gone','failed'),opportunity('fix','failed')],
                       [opportunity('fix','passed'),opportunity('new','failed')])
        self.assertEqual(result['excluded_original_ids'],['gone'])
        self.assertEqual(result['categories']['Semantic']['resolved'],1)
        self.assertEqual(result['new_opportunities']['categories']['Semantic']['failed'],1)
        self.assertEqual(result['categories']['Semantic']['burden_reduction_percent'],100)
        self.assertEqual(result['original']['categories']['Semantic']['opportunities'],2)

    def test_zero_baseline_and_regression(self):
        out=compare([opportunity('a','passed')],[opportunity('a','failed')])['categories']['Semantic']
        self.assertIsNone(out['burden_reduction_percent']);self.assertEqual(out['new_on_existing'],1)
        out=compare([opportunity('a','failed'),opportunity('b','passed')],
                    [opportunity('a','failed'),opportunity('b','failed')])['categories']['Semantic']
        self.assertEqual(out['burden_reduction_percent'],-100)

    def test_duplicates_and_invalid_verdicts_fail_closed(self):
        with self.assertRaises(ValueError):summarize([opportunity('a','passed'),opportunity('a','failed')])
        with self.assertRaises(ValueError):summarize([opportunity('a','probably')])

    def test_closed_judge_is_blinded_and_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);provider=Mock(campaign='campaign')
            provider.decisions.return_value={'a':{'type':'choice','choice':'insufficient_evidence','confidence':.6}}
            args=(store,provider,'run','assessment',{'id':'decisions'}, {'html':'<img alt="image">'},[opportunity('a','error','heading-not-descriptive')])
            first=contextual_review(*args);second=contextual_review(*args)
            self.assertEqual(first,second);provider.decisions.assert_called_once()
            self.assertEqual(first['data']['summary']['categories']['Semantic']['unassessed'],1)
            with self.assertRaises(ContractError):contextual_review(*args[:5],{'html':'changed'},args[-1])
            self.assertEqual(provider.decisions.call_count,1)

    def test_judge_unknown_references_and_invalid_probability_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            provider=Mock(campaign='campaign');args=(Store(root),provider,'run','assessment',{'id':'decisions'},{},[opportunity('a','error','heading-not-descriptive')])
            provider.decisions.return_value={'alien':{'type':'choice','choice':'passed','confidence':1}}
            with self.assertRaises(ContractError):contextual_review(*args)
            provider.decisions.return_value={'a':{'type':'choice','choice':'passed','confidence':float('nan')}}
            with self.assertRaises(ContractError):contextual_review(*args)

    def test_other_images_and_numeric_text_do_not_establish_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            provider=Mock(campaign='campaign')
            rows=[dict(opportunity('image','error'),context={'element':{'attributes':{'alt':'A red square'}}}),dict(opportunity('language','error','language-of-parts-mismatch'),context={'observed_text':'123'})]
            result=contextual_review(Store(root),provider,'run','missing',{'id':'decisions'},{},rows,image_parts=[{'image_url':{'url':'other-image'}}])
            provider.decisions.assert_not_called()
            self.assertTrue(all(r['status']=='insufficient_evidence' for r in result['data']['opportunities']))
