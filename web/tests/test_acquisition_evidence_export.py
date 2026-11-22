"""Portable evidence must retain native acquisition and repeatability receipts."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from harness.contracts import digest
from harness.export import bundle
from harness.store import Store


class AcquisitionEvidenceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.corpus = self.store.append('corpus', {'items': []})

    def campaign(self):
        return self.store.append('campaign', {
            'corpus_id': self.corpus['id'], 'conditions': [], 'workers': [],
            'partition': 'development', 'source': {'count': 0}, 'capture_only': True,
            'repetitions': 1, 'analysis': {'contrasts': []}})

    def unpack(self, campaign):
        with zipfile.ZipFile(io.BytesIO(bundle(self.store, campaign['id'], True))) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        for name, expected in json.loads(files['MANIFEST.json'])['files'].items():
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), expected)
        records = {row['id']: row for row in json.loads(files['records.json'])}
        for row in records.values():
            self.assertEqual(digest(row['data']), row['hash'])
        artifacts = {row['id']: row for row in json.loads(files['artifacts.json'])}
        return records, artifacts, files

    def evidence(self, campaign, status='admitted'):
        capture = self.store.append('capture', {'requested_url': 'https://fixture.example/'}, campaign['id'])
        audits = []
        for ordinal in range(2):
            rendered = self.store.blob('<main>Same frozen fixture</main>', 'rendered_audit', campaign['id'])
            audits.append(self.store.append('audit', {'status': 'completed', 'artifacts': {'rendered': rendered['id']},
                'capture_id': capture['id'], 'independent_browser_document': ordinal}, campaign['id']))
        repeat = self.store.append('source_repeatability', {'status': status,
            'reasons': [] if status == 'admitted' else ['source_measurement_not_repeatable'],
            'audit_ids': [row['id'] for row in audits], 'capture_id': capture['id'], 'paid_calls': 0}, campaign['id'])
        return repeat, audits

    def test_repeat_receipt_and_independent_audits_survive_export_without_rehashing(self):
        campaign = self.campaign()
        repeat, audits = self.evidence(campaign, status='rejected')
        records, artifacts, files = self.unpack(campaign)
        self.assertEqual(records[repeat['id']], repeat)
        self.assertEqual(records[repeat['id']]['data']['status'], 'rejected')
        for audit in audits:
            self.assertEqual(records[audit['id']], audit)
            artifact = artifacts[audit['data']['artifacts']['rendered']]
            self.assertIn('blobs/' + artifact['data']['sha256'], files)

    def test_reused_receipt_closes_only_reachable_ancestor_evidence(self):
        old = self.campaign()
        repeat, audits = self.evidence(old)
        unrelated, _ = self.evidence(old)
        current = self.campaign()
        self.store.append('page', {'repeatability_id': repeat['id']}, current['id'])
        records, _, _ = self.unpack(current)
        self.assertEqual(records[repeat['id']], repeat)
        self.assertTrue(all(row['id'] in records for row in audits))
        self.assertNotIn(unrelated['id'], records)

    def test_recovery_selection_and_native_media_bytes_survive_private_export(self):
        old = self.campaign()
        roles = ('verified_dynamic_context_candidate', 'observed_mse_append', 'observed_worker_media_init')
        artifacts = [self.store.blob('fixture-' + role, role, old['id']) for role in roles]
        selection = self.store.append('source_selection', {'accepted': False,
            'artifact_ids': [row['id'] for row in artifacts]}, old['id'])
        current = self.campaign()
        self.store.append('capture', {'source_selection_id': selection['id']}, current['id'])
        records, exported, files = self.unpack(current)
        self.assertEqual(records[selection['id']], selection)
        for artifact in artifacts:
            self.assertEqual(exported[artifact['id']], artifact)
            self.assertEqual(files['blobs/' + artifact['data']['sha256']], self.store.read_blob(artifact['id']))
