"""Offline citation recovery preserves verdicts, documents and paid receipts."""
import json
import unittest
from unittest.mock import Mock, patch

import test_harness
from harness.contracts import ContractError, digest
from harness.evidence_verifier import corrected_saved_visual, verify
from harness.providers import Providers
from harness.visual_review_policy import parse, response_schema


class VisualEvidenceRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_harness.HarnessTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.store = self.fixture.store
        self.reference = '6e7ae9c6fc2e428184e0bb727f2dc48d'
        self.typo = self.reference[:-1] + 'e'
        self.answer = dict(reason_code='usable', impact='none', blocking_confidence=0.0,
                           rationale='The observed page is legible.', evidence_refs=[self.typo])

    def test_only_unique_one_character_uuid_substitution_is_resolved(self):
        result = parse(self.answer, [self.reference])
        self.assertEqual(result['evidence_refs'], [self.reference])
        self.assertEqual(result['blocking_confidence'], 0)
        self.assertEqual(result['rationale'], self.answer['rationale'])
        self.assertEqual(self.answer['evidence_refs'], [self.typo])
        for refs, citation in [([self.reference, self.reference[:-1] + 'f'], self.typo),
                               ([self.reference], self.reference[:-2] + 'ee'),
                               (['source-record'], 'source-recorx')]:
            with self.subTest(refs=refs), self.assertRaises(ContractError):
                parse(dict(self.answer, evidence_refs=[citation]), refs)

    def test_saved_review_is_versioned_without_network_or_raw_mutation(self):
        store = self.store
        capture = store.append('capture', {}, ident='source')
        audit = store.append('audit', {}, ident='audit')
        check = store.append('candidate_usability', {}, ident='checks')
        references = ['source', 'audit', 'checks', self.reference]
        prompt = 'Review\nEVIDENCE\n' + json.dumps({'references': references})
        request = {'messages': [{'content': prompt}]}
        request_record = store.append('provider_request', {'request': request})
        raw = json.dumps({'choices': [{'message': {'content': json.dumps(self.answer)}}]})
        response = store.blob(raw, 'provider_response')
        previous = store.append('evidence_verification', {
            'response_contract_error': True, 'status': 'review_required',
            'capture_id': 'source', 'audit_id': 'audit', 'deterministic_id': 'checks',
        }, 'fixture', 'verification')
        provider = Mock(campaign='fixture')
        provider.ledger.rows.return_value = [dict(logical_key='verification:agent',
            status='received', response_id=response['id'], request_id=request_record['id'],
            request_hash=digest(request), id='paid-call')]
        corrected = verify(store, provider, 'run', previous['id'], capture, audit, check,
                           candidate=True, candidate_local=True)
        self.assertEqual(corrected['data']['status'], 'admitted')
        self.assertEqual(corrected['data']['previous_verification_id'], previous['id'])
        self.assertFalse(corrected['data']['raw_response_modified'])
        self.assertEqual(store.get(previous['id']), previous)
        self.assertEqual(store.read_blob(response['id']), raw.encode())
        provider.chat.assert_not_called()
        self.assertEqual(verify(store, provider, 'run', previous['id'], capture, audit, check,
                               candidate=True, candidate_local=True), corrected)
        other = store.append('audit', {}, ident='other-document')
        # A cached correction must still belong to the current document.
        with self.assertRaises(ContractError):
            corrected_saved_visual(store, provider, 'run', previous, capture, other, check)

    def test_saved_baseline_single_insert_is_recovered_without_another_call(self):
        store = self.store
        capture = store.append('capture', {}, ident='source')
        audit = store.append('audit', {}, ident='audit')
        check = store.append('replay_admission', {}, ident='checks')
        typo = self.reference + '2'
        answer = {'status': 'admitted', 'rationale': 'Both captures show the same usable page.',
                  'evidence_refs': ['source', typo, 'audit']}
        refs = ['source', 'audit', 'checks', self.reference]
        request = {'messages': [{'content': 'Review\nEVIDENCE\n' +
                     json.dumps({'references': refs})}]}
        request_record = store.append('provider_request', {'request': request})
        raw = json.dumps({'choices': [{'message': {'content': json.dumps(answer)}}]})
        response = store.blob(raw, 'provider_response')
        previous = store.append('evidence_verification', {
            'phase': 'baseline', 'status': 'review_required',
            'rationale': 'Invalid verifier response: Capture verifier cited unknown evidence',
            'capture_id': 'source', 'audit_id': 'audit', 'deterministic_id': 'checks',
        }, 'fixture', 'verification')
        provider = Mock(campaign='new-campaign')
        provider.ledger.rows.return_value = [dict(logical_key='verification:agent',
            status='received', response_id=response['id'], request_id=request_record['id'],
            request_hash=digest(request), id='paid-call')]
        corrected = verify(store, provider, 'new-run', previous['id'], capture, audit, check)
        self.assertEqual(corrected['data']['status'], 'admitted')
        self.assertEqual(corrected['data']['evidence_refs'], ['source', self.reference, 'audit'])
        self.assertEqual(corrected['data']['normalized_references'][0]['provided'], typo)
        self.assertEqual(corrected['campaign'], previous['campaign'])
        self.assertFalse(corrected['data']['raw_response_modified'])
        self.assertEqual(store.read_blob(response['id']), raw.encode())
        provider.chat.assert_not_called()
        self.assertEqual(verify(store, provider, 'new-run', previous['id'], capture, audit, check), corrected)
        other = store.append('audit', {}, ident='other-document')
        with self.assertRaises(ContractError):
            verify(store, provider, 'new-run', previous['id'], capture, other, check)

    def test_schema_constrains_all_five_fields_and_supplied_handles(self):
        schema = response_schema(['source', self.reference, 'source'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']), set(self.answer))
        self.assertEqual(schema['properties']['evidence_refs']['items']['enum'],
                         ['source', self.reference])
        provider = Providers(self.store, self.fixture.manifest, 'fixture', {'openrouter_base_url':'https://fixture'})
        model = dict(self.fixture.manifest['workers'][0], model='openai/gpt-6-luna',
                     supported_parameters=['structured_outputs'], reasoning_effort='low', provider='openrouter')
        envelope = {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
        with patch.object(provider, 'dispatch', return_value=envelope) as dispatch:
            provider.chat('run', 'review', 'key', model, 'Review', response_schema=schema)
        body = dispatch.call_args.args[4]
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertTrue(body['response_format']['json_schema']['strict'])
        self.assertTrue(body['provider']['require_parameters'])
        self.assertNotIn('temperature', body)
        with self.assertRaises(ContractError):
            provider.chat('run', 'review', 'key', dict(model, supported_parameters=[]),
                          'Review', response_schema=schema)
