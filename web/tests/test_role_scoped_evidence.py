"""Role separation, actual stage focus and immutable full measurements."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from harness.contracts import ContractError, canonical
from harness.dynamic_objectives import (
    EVIDENCE_VERSION, CURRENT_EVIDENCE_VERSION, COORDINATED_EVIDENCE_VERSION, SHARED_EVIDENCE_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION, compact_evidence, repair_work, work_messages)
from harness.planning_evidence import expanded_feedback, planner_context, shared_feedback
from harness.remediation_bridge import Bridge
from remediation_interventions import VERSION as INTERVENTIONS


def evidence():
    semantic = {'opportunity_id':'sem', 'type':'landmark-purpose-mismatch', 'status':'failed',
        'context':{'element':{'tag':'button','text':'Latest','attributes':{'id':'latest','onclick':'old()'}},
                   'observed_purpose':{'accessible_name':'Latest','element_html':'<button>Latest</button>',
                       'references':{'aria-controls':[{'id':'panel','html':'<div>'+('content '*5000)+'</div>'}]}}}}
    syntactic = {'opportunity_id':'syn','type':'link-name','status':'failed','target':['#link']}
    return {'assessment_id':'saved','document_sha256':'source', 'failed_opportunities':[semantic,syntactic],
        'unresolved_prior_findings':[{'status':'unassessed','prior_finding':dict(syntactic,opportunity_id='prior')}],
        'unresolved_prior_finding_count':1,'taxonomy_failed':{'Semantic':1,'Syntactic':1,'Layout':0},
        'taxonomy_coverage':{'Semantic':.9,'Syntactic':1,'Layout':1}}


class RoleEvidenceTests(unittest.TestCase):
    def test_projection_keeps_all_identities_statuses_targets_and_handler_evidence(self):
        e=evidence();before=copy.deepcopy(e);r=compact_evidence(e)
        self.assertEqual(e,before)
        self.assertEqual([v['opportunity_id'] for v in r['failed_opportunities']],['sem','syn'])
        self.assertEqual(r['failed_opportunities'][0]['context']['element']['attributes']['onclick'],'old()')
        self.assertEqual(r['failed_opportunities'][1]['target'],['#link'])
        self.assertEqual(r['unresolved_prior_findings'],e['unresolved_prior_findings'])
        ref=r['failed_opportunities'][0]['context']['observed_purpose']['references']['aria-controls'][0]
        self.assertIn('html_reference',ref)
        self.assertNotIn('content content',canonical(r))
        self.assertLess(len(canonical(r)),len(canonical(e))/5)

    def test_audit_work_is_focused_without_reclassifying_deferred_findings(self):
        e=evidence();work=repair_work(e,{'patch_failures':[{'id':'link-name'}]})
        self.assertEqual(work['phase'],'audit')
        self.assertEqual(work['deferred_failed_findings'],2)
        self.assertEqual(work['deferred_unresolved_findings'],1)
        self.assertEqual(work['active_contextual_evidence']['taxonomy_failed'],e['taxonomy_failed'])
        self.assertEqual(work['active_contextual_evidence']['failed_opportunities'],[])
        self.assertEqual(len(e['failed_opportunities']),2)
        self.assertEqual(work_messages(work,'component-planner'),[])
        self.assertIn('deferred, not corrected',work_messages(work,'generator')[0]['content'])

    def test_explicit_semantic_focus_reaches_only_the_selected_current_findings(self):
        work=repair_work(evidence(),{'patch_failures':[{'id':'link-name'}]},
            {'action':'P2:worker','focus':'Semantic','target_types':['landmark-purpose-mismatch']})
        self.assertEqual(work['phase'],'contextual')
        self.assertEqual([r['opportunity_id'] for r in work['active_contextual_evidence']['failed_opportunities']],['sem'])
        self.assertEqual(work['deferred_failed_findings'],1)
        self.assertTrue(work_messages(work,'component-planner'))

    def test_perfect_audits_keep_contextual_work_and_uncertain_findings(self):
        work=repair_work(evidence(),{'axe':0,'lighthouse':100,'patch_failures':[],'lighthouse_failures':[]})
        self.assertEqual(work['phase'],'contextual')
        self.assertEqual(len(work['active_contextual_evidence']['failed_opportunities']),2)
        self.assertEqual(work['active_contextual_evidence']['unresolved_prior_findings'][0]['status'],'unassessed')
        self.assertIn('0/100',work_messages(work)[0]['content'])

    def test_lighthouse_work_is_not_lost_when_axe_is_zero(self):
        self.assertEqual(repair_work(evidence(),{'axe':0,'lighthouse_failures':[{'id':'contrast'}]})['phase'],'audit')

    def test_scoped_worker_localization_keeps_full_evidence_in_memory(self):
        bridge=Bridge.__new__(Bridge);bridge.generation_contextual_evidence=evidence()
        bridge.generation_work=repair_work(bridge.generation_contextual_evidence,{'patch_failures':[{}]})
        self.assertIsNone(bridge.worker_contextual_evidence())
        self.assertEqual(len(bridge.generation_contextual_evidence['failed_opportunities']),2)
        bridge.generation_work=repair_work(bridge.generation_contextual_evidence,{})
        self.assertEqual(len(bridge.worker_contextual_evidence()['failed_opportunities']),2)
        del bridge.generation_work
        self.assertEqual(bridge.worker_contextual_evidence(),bridge.generation_contextual_evidence)




    def test_transport_separates_component_planning_and_patch_generation(self):
        from test_slider_bridge import BridgeTests
        f=BridgeTests();f.setUp();self.addCleanup(f.doCleanups);b=f.bridge();b.begin_iteration(1)
        b.generation_contextual_evidence=evidence()
        b.generation_work=repair_work(evidence(),{'patch_failures':[{}]})
        b.task_runtime=SimpleNamespace(active_task_name='component-planner')
        body={'model':b.worker['model'],'messages':[{'role':'user','content':'Plan components'}],'max_tokens':100}
        b.transport(body)
        self.assertFalse(any('Current repair work' in str(r) for r in f.session.requests[-1]['messages']))
        b.task_runtime.active_task_name='patch-generator'
        b.transport(dict(body,messages=[{'role':'user','content':'Repair'}]))
        text=canonical(f.session.requests[-1]['messages'])
        self.assertIn('Current repair work',text)
        self.assertNotIn('content content',text)
        self.assertEqual(len(b.generation_contextual_evidence['failed_opportunities']),2)
