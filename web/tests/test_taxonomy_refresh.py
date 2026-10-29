import unittest
from unittest.mock import Mock
from accessibility_taxonomy.refresh import refreshed_outcome
from accessibility_taxonomy.assessment import VERSION,coverage
from harness.contracts import ContractError

class TaxonomyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.store=Mock(); self.store.get.side_effect=lambda ident:{'data':{'audit_id':ident.split('-')[0],'document_sha256':ident.split('-')[0]}}
        self.old={'selected':{'candidate':'valid'},'axe':10,'taxonomy_measurement':{'original_assessment_id':'a-old','retained_assessment_id':'b-old'}}
        self.new={'version':VERSION,'status':'completed','errors':[],'original_assessment_id':'a-new','retained_assessment_id':'b-new'}
    def test_replace_measurement_keeps_actual_retention_and_does_not_append_obsolete_counts(self):
        result=refreshed_outcome(self.old,self.new,self.store)
        self.assertEqual(result['selected'],self.old['selected']);self.assertEqual(result['axe'],10)
        self.assertEqual(result['taxonomy_measurement'],self.new)
        self.assertEqual(self.old['taxonomy_measurement']['original_assessment_id'],'a-old')
    def test_changed_document_or_failed_assessment_cannot_replace_active_measurement(self):
        for new in (dict(self.new,retained_assessment_id='c-new'),dict(self.new,status='partial'),dict(self.new,version='old')):
            with self.assertRaises(ContractError):refreshed_outcome(self.old,new,self.store)
    def test_outside_scope_and_detector_abstention_have_different_denominators(self):
        result=coverage([{'status':'insufficient_evidence','method':'unobserved_supplement','type':'link-text-mismatch'}, {'status':'insufficient_evidence','method':'axe','type':'color-contrast'}, {'status':'passed','method':'decisions','type':'heading-not-descriptive'}])
        self.assertEqual(result['outside_scope'],1);self.assertEqual(result['inconclusive'],1)
        self.assertEqual(result['inconclusive_types'],{'color-contrast':1})
