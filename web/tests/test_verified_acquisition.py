"""Acquisition-only contracts; all pages, browser results and judgments are synthetic."""
import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from harness.contracts import ContractError, digest
from harness.decision_models import DEFINITIONS
from harness.store import Store
from harness import verified_acquisition as acquisition

HTML = '<!doctype html><html lang="en"><head><title>Learning fixture</title></head><body><main><h1>Learning fixture</h1><p>' + 'Educational content for a synthetic acquisition fixture. ' * 4 + '</p><a href="/help">Help</a></main></body></html>'
RUNTIME = {'source_files': {'fixture.js': 'unchanged'}, 'browser': 'synthetic'}


class Environment:
    def __init__(self, store):
        self.store, self.captures, self.audits = store, 0, 0
        self.scores = (0, 100)
        self.drift = False
        self.reference = True
        self.replay_status = 'admitted'

    def verify_runtime(self, campaign):
        expected = self.store.get(campaign + '-evaluator-runtime')['data']
        if expected != {'schema': 'a11yharness/1', **RUNTIME}:
            raise ContractError('Evaluator changed')

    def runtime(self):
        return copy.deepcopy(RUNTIME)

    def capture(self, url, campaign, ident):
        self.captures += 1
        rendered = self.store.blob(HTML, 'rendered_html', campaign, 'text/html')
        response = self.store.blob('<html><body>Initial response</body></html>', 'network_html', campaign)
        source = self.store.blob(HTML, 'replay_source_html', campaign, 'text/html')
        data = {'rendered_id': rendered['id'], 'network_id': response['id'], 'replay_source_id': source['id'],
                'requested_url': url, 'captured_url': url, 'http_status': 200, 'assets': [], 'visible': {'title': 'Learning fixture'}}
        if self.reference:
            data['native_control_reference'] = {'version': 'observed-native-control-state-v1', 'records': []}
        return self.store.append('capture', data, campaign, ident)

    def audit(self, capture, source, campaign, ident, config):
        self.audits += 1
        return self.store.append('audit', {'status': 'completed', 'axe': self.scores[0], 'lighthouse': self.scores[1],
            'failures': [], 'artifacts': {}, 'replay': {'manifest_sha256': 'same-resources',
                'input_document_sha256': hashlib.sha256(source.encode()).hexdigest(),
                'rendered_document_sha256': 'same-rendered', 'diagnostics': {'phase_evidence': {
                    'stable': True, 'phases': [{'sha256': str(self.audits) if self.drift else 'same-paint'}]}}}}, campaign, ident)

    def capture_verified(self, url, campaign, ident, config):
        return self.capture(url, campaign, ident)

    def replay_check(self, capture, source, campaign, ident, audit):
        return self.store.append('replay_admission', {'status': self.replay_status,
            'reasons': [] if self.replay_status == 'admitted' else ['resource_loss'],
            'audit_id': audit['id'], 'capture_id': capture['id']}, campaign, ident)


class Provider:
    def __init__(self, campaign):
        self.campaign, self.calls = campaign, []

    def decisions(self, run, account, key, evidence, questions, **kwargs):
        self.calls.append(json.loads(evidence))
        return {'category': {'type': 'choice', 'choice': 'Education'}}


class VerifiedAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.environment = Environment(self.store)
        self.value = {'name': 'Synthetic pilot', 'study_id': 'synthetic-acquisition', 'seed': '1',
            'authorization_reference': 'synthetic fixture, no real authorization', 'campaign_cost_limit': 5,
            'budget_group': {'id': 'synthetic-data', 'stage': 'acquisition', 'total_usd': 5,
                             'stage_limits': {'acquisition': 5}},
            'capture_verifier': dict(DEFINITIONS[0]), 'category_review_model': dict(DEFINITIONS[0]),
            'repair_budget': {'max_cost_usd': 5, 'max_seconds': 600, 'max_calls': 4, 'max_output_tokens': 256},
            'review_budget': {'max_cost_usd': 5, 'max_seconds': 600, 'max_calls': 4, 'max_output_tokens': 256},
            'candidates': [{'candidate_id': 'candidate-1', 'url': 'https://fixture.example/', 'rank': 2, 'segment': 'S1'}]}
        self.visual_calls = []
        def visual(store, providers, run, ident, capture, audit, check, model):
            self.visual_calls.append(capture['id'])
            try:
                return store.get(ident)
            except KeyError:
                return store.append('evidence_verification', {'status': 'admitted', 'capture_id': capture['id'],
                    'audit_id': audit['id'], 'deterministic_id': check['id']}, providers.campaign, ident)
        self.visual_patch = patch('harness.evidence_verifier.verify', side_effect=visual)
        self.visual_patch.start()
        self.addCleanup(self.visual_patch.stop)

    def freeze(self):
        campaign = acquisition.freeze(self.store, self.value, RUNTIME, 'synthetic-pilot')
        self.provider = Provider(campaign['id'])
        return campaign

    def run_page(self, campaign):
        return acquisition.acquire(self.store, self.environment, self.provider, campaign, 0)

    def test_freeze_dispatches_nothing_and_idempotently_reuses_manifest(self):
        first = self.freeze()
        second = self.freeze()
        self.assertEqual(first, second)
        self.assertEqual(self.environment.captures, 0)
        self.assertEqual(self.store.list('run'), [])
        self.assertEqual(first['data']['workers'], [])
        self.assertEqual(first['data']['conditions'], [])

    def test_changed_frozen_configuration_cannot_reuse_campaign_id(self):
        self.freeze()
        self.value['campaign_cost_limit'] = 4
        with self.assertRaises(ValueError):
            self.freeze()

    def test_perfect_audit_is_eligible_and_category_uses_acquired_dom(self):
        campaign = self.freeze()
        result = self.run_page(campaign)
        self.assertEqual(result['data']['status'], 'automatically_admitted_pending_human')
        page = self.store.get(result['data']['page_id'])
        self.assertEqual(self.store.get(page['data']['repeatability_id'])['data']['status'], 'admitted')
        self.assertEqual(self.environment.audits, 2)
        self.assertIn('Educational content', self.provider.calls[0]['visible_text'])
        self.assertNotIn('Initial response', self.provider.calls[0]['visible_text'])
        self.assertEqual(self.provider.calls[0]['source_result_id'], self.store.get(page['data']['capture_id'])['data']['rendered_id'])
        self.assertFalse(page['data']['human_verified'])
        self.assertEqual(self.store.list('run'), [])
        self.assertEqual(self.store.list('retrieval'), [])

    def test_resume_preserves_success_without_new_capture_audit_or_category_call(self):
        campaign = self.freeze()
        first = self.run_page(campaign)
        counts = (self.environment.captures, self.environment.audits, len(self.provider.calls))
        self.assertEqual(self.run_page(campaign), first)
        self.assertEqual((self.environment.captures, self.environment.audits, len(self.provider.calls)), counts)

    def test_drift_blocks_paid_review_and_classification_and_preserves_failure(self):
        campaign = self.freeze()
        self.environment.drift = True
        result = self.run_page(campaign)
        self.assertEqual(result['data']['status'], 'rejected')
        self.assertEqual(self.visual_calls, [])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.store.list('source_repeatability')[0]['data']['status'], 'rejected')
        self.assertEqual(self.run_page(campaign), result)
        self.assertEqual(self.environment.captures, 1)

    def test_missing_native_reference_blocks_before_audit_and_paid_work(self):
        campaign = self.freeze()
        self.environment.reference = False
        result = self.run_page(campaign)
        self.assertEqual(result['data']['status'], 'rejected')
        self.assertEqual(self.environment.audits, 0)
        self.assertEqual(self.provider.calls, [])

    def test_rejected_replay_does_not_become_a_page(self):
        campaign = self.freeze()
        self.environment.replay_status = 'rejected'
        result = self.run_page(campaign)
        self.assertEqual(result['data']['status'], 'rejected')
        self.assertEqual(self.store.list('page'), [])
        self.assertEqual(self.visual_calls, [])

    def test_runtime_change_stops_before_capture(self):
        campaign = self.freeze()
        with patch('harness.versions.snapshot', return_value={'changed': True}):
            with self.assertRaisesRegex(ContractError, 'runtime'):
                self.run_page(campaign)
        self.assertEqual(self.environment.captures, 0)

    def test_no_unlisted_or_duplicate_candidate_can_be_dispatched(self):
        campaign = self.freeze()
        with self.assertRaises(ContractError):
            acquisition.acquire(self.store, self.environment, self.provider, campaign, 1)
        self.value['candidates'] *= 2
        with self.assertRaises(ContractError):
            acquisition.freeze(self.store, self.value, RUNTIME, 'another')

    def test_partial_or_wrong_budget_and_generator_settings_are_rejected(self):
        for change in ({'budget_group': None}, {'campaign_cost_limit': 6}, {'conditions': [{'id': 'P5'}]},
                       {'capture_verifier': None}, {'category_review_model': None}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                acquisition.freeze(self.store, dict(self.value, **change), RUNTIME, 'invalid')

    def test_native_bundle_retains_repeat_and_outcome_without_retrieval_corpus(self):
        import io, zipfile
        from harness.export import bundle
        campaign = self.freeze()
        result = self.run_page(campaign)
        with zipfile.ZipFile(io.BytesIO(bundle(self.store, campaign['id'], True))) as archive:
            rows = {row['id']: row for row in json.loads(archive.read('records.json'))}
        self.assertIn(result['id'], rows)
        page = rows[result['data']['page_id']]
        self.assertIn(page['data']['repeatability_id'], rows)

    def test_invalid_category_preserves_valid_page_without_repeating_model_work(self):
        campaign = self.freeze()
        self.provider.decisions = lambda *args, **kwargs: {'category': {'type': 'choice', 'choice': 'Invented label'}}
        result = self.run_page(campaign)
        page = self.store.get(result['data']['page_id'])
        self.assertEqual(result['data']['status'], 'automatically_admitted_pending_human')
        self.assertIsNone(page['data']['category_review_id'])
        self.assertIsNotNone(page['data']['category_error'])
        self.assertEqual(len(self.store.list('category_review_failure')), 1)
        self.assertEqual(self.run_page(campaign), result)

    def test_transport_failure_retains_attempt_without_automatic_recapture(self):
        import requests
        campaign = self.freeze()
        with patch.object(self.environment, 'capture', side_effect=requests.Timeout('Synthetic timeout')) as capture:
            result = self.run_page(campaign)
            self.assertEqual(result['data']['status'], 'unavailable')
            self.assertEqual(self.run_page(campaign), result)
            capture.assert_called_once()
        self.assertEqual(len(self.store.list('acquisition_attempt')), 1)

    def test_generic_worker_cannot_launch_acquisition_as_remediation(self):
        from harness.engine import launch
        campaign = self.freeze()
        with self.assertRaisesRegex(ContractError, 'acquisition adapter'):
            launch(self.store, campaign['id'])
        self.assertEqual(self.store.checkpoint(campaign['id'])[0]['status'], 'externally_managed')

    def test_visual_recovery_repeats_the_final_source_before_another_paid_review(self):
        campaign = self.freeze()
        visual_sources = []
        def visual(store, providers, run, ident, capture, audit, replay, model):
            visual_sources.append(capture['id'])
            return store.append('evidence_verification', {'status': 'rejected' if len(visual_sources) == 1 else 'admitted',
                'capture_id': capture['id'], 'audit_id': audit['id'], 'deterministic_id': replay['id']}, campaign['id'], ident)
        def recover(store, environment, capture, source, audit, replay, cid, identity, config, verification=None):
            if verification is None:
                return capture, source, audit, replay
            altered = source.replace('Learning fixture', 'Recovered learning fixture')
            blob = store.blob(altered, 'verified_dynamic_context_candidate', cid)
            recovered = store.append('capture', {**capture['data'], 'parent_capture_id': capture['id'],
                'replay_source_id': blob['id']}, cid, identity + '-alternative')
            next_audit = environment.audit(recovered, altered, cid, identity + '-audit', config)
            next_replay = environment.replay_check(recovered, altered, cid, identity + '-replay', next_audit)
            return recovered, altered, next_audit, next_replay
        with patch('harness.evidence_verifier.verify', side_effect=visual), patch('harness.source_recovery.recover', side_effect=recover):
            result = self.run_page(campaign)
        page = self.store.get(result['data']['page_id'])
        repeat = self.store.get(page['data']['repeatability_id'])
        self.assertEqual(self.environment.audits, 4)
        self.assertEqual(len(visual_sources), 2)
        self.assertNotEqual(*visual_sources)
        self.assertEqual(repeat['data']['capture_id'], page['data']['capture_id'])
        self.assertIn(page['data']['audit_id'], repeat['data']['audit_ids'])
        self.assertEqual(len(self.store.list('source_repeatability')), 2)

    def test_partition_conflict_is_retained_before_visiting_the_domain(self):
        campaign = self.freeze()
        self.store.assign_domain(self.value['study_id'], 'fixture.example', 'test')
        result = self.run_page(campaign)
        self.assertEqual(result['data']['status'], 'rejected')
        self.assertEqual(self.environment.captures, 0)
        self.assertEqual(self.provider.calls, [])

    def test_unknown_consumption_stops_before_another_capture(self):
        from harness.providers import Ledger, UncertainCall
        campaign = self.freeze()
        Ledger(self.store)
        with patch.object(Ledger, 'rows', return_value=[{'cost_status': 'unknown', 'status': 'transport_error'}]):
            with self.assertRaises(UncertainCall):
                self.run_page(campaign)
        self.assertEqual(self.environment.captures, 0)
