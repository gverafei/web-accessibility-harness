"""Shared evidence calls wait for their owner without duplicating HTTP or billing."""
import concurrent.futures
import json
import threading
from types import SimpleNamespace
import unittest

import test_harness
from harness.engine import create_campaign
from harness.providers import Providers, UncertainCall
from harness.store import Conflict
from harness.category_review import review
from classify_site_categories import CATEGORIES


class ConcurrentProviderReuseTests(unittest.TestCase):
    def setUp(self):
        fixture = test_harness.HarnessTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.store = fixture.store
        self.first = create_campaign(self.store, fixture.manifest)
        self.second = create_campaign(self.store, fixture.manifest)
        self.model = self.first['data']['workers'][0]
        self.body = {'model': self.model['model'], 'max_tokens': 128,
                     'messages': [{'role': 'user', 'content': 'Shared source verification'}]}
        self.session = test_harness.Session()

    def provider(self, campaign):
        return Providers(self.store, campaign['data'], campaign['id'], {}, self.session)

    def call(self, provider):
        return provider.dispatch('source', 'review', 'shared-source', self.model,
                                 self.body, 'https://fixture.invalid', 'fixture-secret')

    def test_concurrent_campaigns_reuse_one_finished_response(self):
        entered, release = threading.Event(), threading.Event()
        original = self.session.post

        def post(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Fixture owner was not released')
            return original(*args, **kwargs)

        self.session.post = post
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call, self.provider(self.first))
            self.assertTrue(entered.wait(2))
            second = pool.submit(self.call, self.provider(self.second))
            try:
                with self.assertRaises(concurrent.futures.TimeoutError):
                    second.result(timeout=.1)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(len(self.session.requests), 1)
        calls = self.provider(self.first).ledger.rows()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['status'], 'received')
        self.assertIsNotNone(calls[0]['response_id'])

    def test_unknown_transport_charge_still_forbids_another_dispatch(self):
        self.session.transport = True
        for campaign in (self.first, self.second):
            with self.assertRaises(UncertainCall):
                self.call(self.provider(campaign))
        self.assertEqual(len(self.session.requests), 1)
        self.assertEqual(len(self.provider(self.first).ledger.rows()), 1)

    def test_concurrent_identical_evidence_retains_one_immutable_owner(self):
        barrier = threading.Barrier(2)

        def append(campaign):
            barrier.wait(timeout=2)
            return self.store.append('evidence_verification', {'status': 'admitted'},
                                     campaign['id'], 'shared-verification')

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(append, (self.first, self.second)))
        self.assertEqual(records[0], records[1])
        self.assertIn(records[0]['campaign'], (self.first['id'], self.second['id']))
        self.assertEqual(len(self.store.list('evidence_verification')), 1)

    def test_reused_identifier_cannot_replace_kind_or_content(self):
        original = self.store.append('evidence_verification', {'status': 'admitted'},
                                     self.first['id'], 'shared-verification')
        for kind, payload in (('audit', {'status': 'admitted'}),
                              ('evidence_verification', {'status': 'rejected'})):
            with self.assertRaises(Conflict):
                self.store.append(kind, payload, self.second['id'], original['id'])
            self.assertEqual(self.store.get(original['id']), original)

    def test_shared_category_owns_one_content_artifact_and_decision(self):
        entered, release = threading.Event(), threading.Event()
        requests = []

        def chat(*args, **kwargs):
            requests.append(args)
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Category fixture owner was not released')
            return json.dumps({'category': CATEGORIES[0]})

        def classify(campaign):
            provider = SimpleNamespace(campaign=campaign['id'], chat=chat)
            return review(self.store, provider, 'run', 'shared-category', self.model,
                          {'id': 1, 'url': 'https://fixture.invalid/'}, '<main>Education</main>')

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(classify, self.first)
            self.assertTrue(entered.wait(2))
            second = pool.submit(classify, self.second)
            try:
                with self.assertRaises(concurrent.futures.TimeoutError):
                    second.result(timeout=.1)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(self.store.list('category_review')), 1)
        self.assertEqual(len([r for r in self.store.list('artifact')
                              if r['data']['role'] == 'category_content']), 1)

    def test_concurrent_supplement_shares_its_judgment_and_artifact(self):
        from accessibility_taxonomy.supplement import resolve

        entered, release = threading.Event(), threading.Event()
        requests = []
        base = self.store.append('taxonomy_assessment', {
            'audit_id': 'audit', 'document_sha256': 'document', 'measurement_cost_usd': 0,
            'opportunities': [{'opportunity_id': 'contrast', 'type': 'color-contrast',
                'status': 'insufficient_evidence', 'method': 'axe', 'target': ['#text']}],
        })
        supplement = {'version': 'rendered-taxonomy-supplement-v3',
            'document_sha256': 'document', 'items': [{'type': 'color-contrast',
                'target': ['#text'], 'evidence': {'measurement': {
                    'status': 'passed', 'ratio': 7, 'threshold': 4.5}}}]}

        def decisions(*args, **kwargs):
            requests.append(args)
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Supplement fixture owner was not released')
            return {'contrast': {'type': 'choice', 'choice': 'visible_text'}}

        def assess(campaign):
            provider = SimpleNamespace(campaign=campaign['id'], manifest={},
                ledger=SimpleNamespace(rows=lambda *args: []), decisions=decisions)
            return resolve(self.store, provider, campaign['id'], base, supplement, {})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(assess, self.first)
            self.assertTrue(entered.wait(2))
            second = pool.submit(assess, self.second)
            try:
                with self.assertRaises(concurrent.futures.TimeoutError):
                    second.result(timeout=.1)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(len(requests), 1)
        self.assertEqual(len([r for r in self.store.list('artifact')
                              if r['data']['role'] == 'taxonomy_supplement_audit']), 1)
