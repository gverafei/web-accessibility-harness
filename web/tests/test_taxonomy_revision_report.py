import tempfile
import unittest
from unittest.mock import patch
from harness.store import Store
from harness.reports import current_measurements
from harness.contracts import ContractError

class RevisionReportTests(unittest.TestCase):
    def correction(self,store):
        audit=store.append('audit',{'status':'completed'},'campaign')
        verification=store.append('evidence_verification',{'status':'admitted','audit_id':audit['id']},'campaign')
        case=store.append('technical_assessment',{'audit_id':audit['id'],'verification_id':verification['id'],
            'assessment':{'status':'passed','checks':{'syntax_nonregression':{'state':'passed'},'observable_preservation':{'status':'passed'}}}},'campaign')
        old=store.append('run_result',{'run_id':'r','selected':{'original':True,'audit_id':'original'}},'campaign')
        outcome=old['data']|{'selected':{'original':False,'admissible':True,'technical':'passed','audit_id':audit['id'],'case_id':case['id']},
            'retention_revision':{'no_generation':True,'original_execution_reusable_as_corrected_policy':False}}
        revision=store.append('retention_revision',{'parent_outcome_id':old['id'],'outcome':outcome,
            'measurement_campaign_id':'review','measurement_run_id':'child','raw_receipts_modified':False},'campaign')
        return old,outcome,revision

    def test_retention_revision_is_bound_and_charges_are_included_once(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);old,outcome,revision=self.correction(store)
            call={'id':'paid-review','run':'child','cost':.01}
            with patch('harness.reports.Ledger.rows',return_value=[call,call]):
                runs,calls,ids=current_measurements(store,'campaign',[old],[])
            self.assertEqual(runs[0]['data']['selected'],outcome['selected'])
            self.assertEqual(store.get(old['id']),old)
            self.assertEqual(calls,[call|{'run':'r','revision_run_id':'child'}])
            self.assertEqual(call['run'],'child')
            self.assertEqual(ids,[revision['id']])

    def test_revision_can_extend_a_recorded_chain_without_duplicating_run_or_charge(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);old,outcome,first=self.correction(store)
            second=store.append('source_fidelity_revision',{'parent_outcome_id':first['id'],'outcome':outcome|{'source_fidelity':{'text_percent':90}},'measurement_campaign_id':'review','measurement_run_id':'child'},'campaign')
            call={'id':'same-call','run':'child','cost':.01}
            with patch('harness.reports.Ledger.rows',return_value=[call]):
                runs,calls,ids=current_measurements(store,'campaign',[old],[])
            self.assertEqual(len(runs),1);self.assertEqual(len(calls),1)
            self.assertEqual(runs[0]['data']['source_fidelity']['text_percent'],90)
            self.assertEqual(ids,[first['id'],second['id']])

    def test_superseded_invalid_envelope_stays_historical_and_keeps_cost(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);old,outcome,first=self.correction(store)
            invalid=store.append('retention_revision',{'parent_outcome_id':first['id'],'outcome':outcome|{'selected':{'original':False,'admissible':False}},'measurement_campaign_id':'old-review'},'campaign')
            final=store.append('retention_revision',first['data']|{'supersedes_revision_ids':[invalid['id']]},'campaign')
            def paid(campaign,*args):return [{'id':campaign,'run':'child','cost':.01}]
            with patch('harness.reports.Ledger.rows',side_effect=paid):
                runs,calls,ids=current_measurements(store,'campaign',[old],[])
            self.assertEqual(runs[0]['data']['selected'],outcome['selected'])
            self.assertEqual(len(calls),2);self.assertIn(invalid['id'],ids)
            self.assertEqual(store.get(invalid['id']),invalid)
            alien=store.append('run_result',{'run_id':'another'},'campaign')
            other=store.append('taxonomy_measurement_revision',{'parent_outcome_id':alien['id'],'outcome':alien['data'],'measurement_campaign_id':'review'},'campaign')
            store.append('retention_revision',first['data']|{'supersedes_revision_ids':[other['id']]},'campaign')
            with self.assertRaisesRegex(ContractError,'same run'):current_measurements(store,'campaign',[old,alien],[])

    def test_retention_revision_cannot_claim_an_unbound_or_nonadmissible_candidate(self):
        for change in ({'admissible':False},{'audit_id':'wrong'},{'technical':'violated'},{'original':True}):
            with self.subTest(change=change),tempfile.TemporaryDirectory()as root:
                store=Store(root);old,outcome,revision=self.correction(store)
                invalid=outcome|{'selected':outcome['selected']|change}
                store.append('retention_revision',revision['data']|{'outcome':invalid},'campaign')
                with self.assertRaises(ContractError):current_measurements(store,'campaign',[old],[])

    def test_revision_cannot_relax_a_historical_contract_by_changing_its_version(self):
        from remediation_interventions import VERSION
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);old,outcome,revision=self.correction(store)
            store.append('retention_revision',revision['data']|{'outcome':outcome|{'intervention_version':VERSION}},'campaign')
            with self.assertRaises(ContractError):current_measurements(store,'campaign',[old],[])

    def test_current_candidate_admission_does_not_require_perfect_fidelity(self):
        from remediation_interventions import VERSION
        with tempfile.TemporaryDirectory()as root:
            store=Store(root)
            audit=store.append('audit',{'status':'completed'},'campaign')
            verification=store.append('evidence_verification',{'status':'admitted','audit_id':audit['id']},'campaign')
            assessment={'status':'passed','fidelity_required':False,'checks':{'syntax_nonregression':{'state':'violated'},'observable_preservation':{'status':'violated'},'candidate_usability':{'status':'admitted'},'capture_verification':verification['data']}}
            case=store.append('technical_assessment',{'audit_id':audit['id'],'verification_id':verification['id'],'assessment':assessment},'campaign')
            old=store.append('run_result',{'run_id':'r','intervention_version':VERSION,'selected':{'original':True,'audit_id':'original'}},'campaign')
            outcome=old['data']|{'selected':{'original':False,'admissible':True,'technical':'passed','audit_id':audit['id'],'case_id':case['id']},'retention_revision':{'no_generation':True,'original_execution_reusable_as_corrected_policy':False}}
            store.append('retention_revision',{'parent_outcome_id':old['id'],'outcome':outcome,'measurement_campaign_id':'review','raw_receipts_modified':False},'campaign')
            with patch('harness.reports.Ledger.rows',return_value=[]):runs,_,_=current_measurements(store,'campaign',[old],[])
            self.assertEqual(runs[0]['data']['selected']['audit_id'],audit['id'])
            self.assertEqual(store.get(old['id']),old)

    def test_fidelity_only_revision_cannot_change_accessibility_or_the_selected_document(self):
        for changed in ({'axe':0},{'selected':{'audit_id':'other'}}):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory()as root:
                store=Store(root)
                old=store.append('run_result',{'run_id':'r','selected':{'audit_id':'a'},'axe':5},'campaign')
                store.append('source_fidelity_revision',{'parent_outcome_id':old['id'],'outcome':old['data']|changed,'measurement_campaign_id':'campaign'},'campaign')
                with self.assertRaises(ContractError):current_measurements(store,'campaign',[old],[])

    def test_fidelity_revision_preserves_accessibility_and_does_not_double_charge_parent_calls(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root)
            original={'run_id':'r','selected':{'source_id':'html','audit_id':'a'},'axe':2,'lighthouse':95,
                'taxonomy_measurement':{'status':'completed'},'candidate_usability':'passed',
                'admissible_success':True,'attempts':['first'],'source_fidelity':{'images_percent':0}}
            old=store.append('run_result',original,'campaign')
            outcome=old['data']|{'source_fidelity':{'images_percent':100,'image_element_percent':0}}
            revision=store.append('source_fidelity_revision',{'parent_outcome_id':old['id'],'outcome':outcome,
                'measurement_campaign_id':'campaign'},'campaign')
            call={'id':'already-paid','run':'r','cost':.01}
            with patch('harness.reports.Ledger.rows',return_value=[call]):
                runs,calls,ids=current_measurements(store,'campaign',[old],[call])
            self.assertEqual(runs[0]['data'],outcome)
            self.assertEqual(calls,[call]);self.assertEqual(ids,[revision['id']])
            self.assertEqual(store.get(old['id']),old)

    def test_current_report_uses_revision_once_without_replacing_parent_evidence(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root)
            old=store.append('run_result',{'run_id':'r','selected':{'audit_id':'a'},'taxonomy_measurement':{'version':'old'}},'campaign')
            updated=dict(old['data'],taxonomy_measurement={'version':'current'})
            revision=store.append('taxonomy_measurement_revision',{'parent_outcome_id':old['id'],'outcome':updated,'measurement_campaign_id':'review'},'campaign')
            runs,calls,ids=current_measurements(store,'campaign',[old],[])
            self.assertEqual(len(runs),1);self.assertEqual(runs[0]['data']['taxonomy_measurement']['version'],'current')
            self.assertEqual(store.get(old['id']),old);self.assertEqual(ids,[revision['id']])
            store.append('taxonomy_measurement_revision',{'parent_outcome_id':old['id'],'outcome':dict(updated,selected={'audit_id':'different'}),'measurement_campaign_id':'review'},'campaign')
            with self.assertRaises(ContractError):current_measurements(store,'campaign',[old],[])
