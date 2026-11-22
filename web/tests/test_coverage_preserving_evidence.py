"""Combined repair coverage without changing measurements or edit authority."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from harness.contracts import ContractError, canonical, validate_manifest
from harness.dynamic_objectives import (
    COMPACT_EVIDENCE_VERSION, EVIDENCE_VERSION, repair_work,
    scoped_evidence_enabled, work_messages,
)
from harness.remediation_bridge import Bridge
from test_role_scoped_evidence import evidence



class CoveragePreservingEvidenceTests(unittest.TestCase):
    def work(self, findings=None, audit=None, stage=None):
        return repair_work(
            evidence() if findings is None else findings,
            {'patch_failures': [{'id': 'link-name'}]} if audit is None else audit,
            stage, version=COMPACT_EVIDENCE_VERSION,
        )

    def test_general_focus_keeps_all_findings_despite_audit_and_stale_types(self):
        findings = evidence()
        before = copy.deepcopy(findings)
        work = self.work(findings, stage={
            'action': 'P2:high', 'focus': 'all', 'target_types': ['link-name'],
        })
        self.assertEqual(work['phase'], 'combined')
        self.assertEqual(work['active_contextual_evidence'], before)
        self.assertEqual(work['deferred_failed_findings'], 0)
        self.assertEqual(work['deferred_unresolved_findings'], 0)
        self.assertEqual(findings, before)

    def test_both_p2_roles_get_the_same_complete_compact_evidence(self):
        work = self.work()
        planner = work_messages(work, 'component-planner')
        generator = work_messages(work, 'patch-generator')
        self.assertEqual(planner, generator)
        brief = json.loads(planner[1]['content'].split('\n', 1)[1])
        projected = brief['contextual_findings']
        self.assertEqual([r['opportunity_id'] for r in projected['failed_opportunities']], ['sem', 'syn'])
        self.assertEqual(projected['unresolved_prior_findings'], evidence()['unresolved_prior_findings'])
        attributes = projected['failed_opportunities'][0]['context']['element']['attributes']
        self.assertEqual(attributes, {'id': 'latest', 'onclick': 'old()'})
        self.assertNotIn('content content', canonical(planner))
        self.assertIn('Never edit a protected handler', planner[0]['content'])
        self.assertIn('the brief does not authorize edits', planner[0]['content'])

    def test_lighthouse_failure_at_perfect_scores_does_not_hide_context(self):
        audit = {'axe': 0, 'lighthouse': 100, 'patch_failures': [],
                 'lighthouse_failures': [{'id': 'label-content-name-mismatch', 'score': 0}]}
        before = copy.deepcopy(audit)
        work = self.work(audit=audit)
        self.assertEqual(work['phase'], 'combined')
        self.assertEqual(len(work['active_contextual_evidence']['failed_opportunities']), 2)
        self.assertTrue(work_messages(work, 'component-planner'))
        self.assertEqual(audit, before)

    def test_explicit_category_focus_stays_bounded_and_counts_pending_findings(self):
        for focus, selected_type, expected in (
            ('Semantic', 'landmark-purpose-mismatch', 'sem'),
            ('Syntactic', 'link-name', 'syn'),
        ):
            with self.subTest(focus=focus):
                work = self.work(stage={'action': 'P2:high', 'focus': focus,
                                        'target_types': [selected_type]})
                active = work['active_contextual_evidence']
                self.assertEqual([r['opportunity_id'] for r in active['failed_opportunities']], [expected])
                self.assertEqual(work['deferred_failed_findings'], 1)
                self.assertEqual(work['deferred_unresolved_findings'], int(focus == 'Semantic'))
                self.assertEqual(active['taxonomy_failed'], evidence()['taxonomy_failed'])
                self.assertTrue(work_messages(work, 'component-planner'))

    def test_general_focus_at_perfect_audits_keeps_unknown_prior_findings(self):
        work = self.work(audit={'axe': 0, 'lighthouse': 100})
        self.assertEqual(work['phase'], 'contextual')
        self.assertEqual(work['active_contextual_evidence'], evidence())
        self.assertEqual(work['active_contextual_evidence']['unresolved_prior_findings'][0]['status'], 'unassessed')

    def test_localization_receives_the_full_active_scope_without_mutating_measurement(self):
        bridge = Bridge.__new__(Bridge)
        bridge.generation_contextual_evidence = evidence()
        bridge.generation_work = self.work(bridge.generation_contextual_evidence)
        self.assertEqual(bridge.worker_contextual_evidence(), evidence())
        self.assertEqual(bridge.generation_contextual_evidence, evidence())

    def test_transport_supplies_coverage_to_both_p2_roles(self):
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bridge = fixture.bridge()
        bridge.begin_iteration(1)
        bridge.generation_contextual_evidence = evidence()
        bridge.generation_work = self.work()
        bridge.task_runtime = SimpleNamespace(active_task_name='component-planner')
        body = {'model': bridge.worker['model'], 'max_tokens': 100,
                'messages': [{'role': 'user', 'content': 'Plan components'}]}
        bridge.transport(body)
        planner = fixture.session.requests[-1]['messages'][-2:]
        bridge.task_runtime.active_task_name = 'patch-generator'
        bridge.transport(dict(body, messages=[{'role': 'user', 'content': 'Repair'}]))
        generator = fixture.session.requests[-1]['messages'][-2:]
        self.assertEqual(planner, generator)
        self.assertIn(COMPACT_EVIDENCE_VERSION, canonical(planner))
        self.assertIn('landmark-purpose-mismatch', canonical(planner))
        brief = json.loads(planner[1]['content'].split('\n', 1)[1])
        self.assertEqual([r['opportunity_id'] for r in brief['contextual_findings']['failed_opportunities']], ['sem', 'syn'])
        self.assertEqual(bridge.generation_contextual_evidence, evidence())

    def test_versioned_manifests_preserve_old_scope_and_reject_unknown_versions(self):
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        manifest = dict(fixture.manifest)
        for version in (EVIDENCE_VERSION, COMPACT_EVIDENCE_VERSION):
            with self.subTest(version=version):
                manifest['adaptive_evidence_version'] = version
                self.assertEqual(validate_manifest(manifest)['adaptive_evidence_version'], version)
                self.assertTrue(scoped_evidence_enabled(manifest))
        legacy = repair_work(evidence(), {'patch_failures': [{}]}, version=EVIDENCE_VERSION)
        self.assertEqual(legacy['phase'], 'audit')
        self.assertEqual(legacy['active_contextual_evidence']['failed_opportunities'], [])
        self.assertEqual(work_messages(legacy, 'component-planner'), [])
        with self.assertRaises(ContractError):
            repair_work(evidence(), {}, version='unknown')

    def test_iteration_boundary_uses_the_frozen_new_contract(self):
        from remediation_interventions import VERSION as INTERVENTIONS
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bridge = fixture.bridge()
        bridge.manifest.update(intervention_version=INTERVENTIONS,
                               adaptive_evidence_version=COMPACT_EVIDENCE_VERSION)
        stage = {'action': 'P2:cheap', 'focus': 'all', 'target_types': ['link-name']}
        choice = {'selected': 'P2:cheap', 'available': ['P2:cheap'], 'repair_stage': stage}
        with patch.object(bridge, 'prepare_dynamic_context'), \
                patch.object(bridge, 'contextual_evidence_for', return_value=evidence()), \
                patch('harness.remediation_bridge.select', return_value=choice):
            bridge.begin_iteration(1)
        self.assertEqual(bridge.generation_work['version'], COMPACT_EVIDENCE_VERSION)
        self.assertEqual(bridge.worker_contextual_evidence(), evidence())
        self.assertEqual(bridge.decision['data']['repair_stage'], stage)
