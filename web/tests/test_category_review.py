import tempfile
import unittest
import io
import json
import zipfile
from unittest.mock import Mock
from harness.store import Store
from harness.category_review import review
from harness.contracts import ContractError


class CategoryReviewTests(unittest.TestCase):
    def test_review_preserves_original_label_and_reuses_known_result(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root); provider = Mock(campaign='fixture')
            provider.chat.return_value = {'category': 'Education'}
            row = {'id': 1, 'url': 'https://fixture.example/', 'site_category': 'Technology',
                   'site_category_source': 'Original dataset', 'source_result_id': 55}
            result = review(store, provider, 'run', 'category', {'id': 'luna'}, row, '<main>Learning</main>')
            second = review(store, provider, 'run', 'category', {'id': 'luna'}, row, '<main>Learning</main>')
            self.assertEqual(result['id'], second['id']);provider.chat.assert_called_once()
            self.assertEqual(result['data']['original_category'], 'Technology')
            self.assertEqual(result['data']['category'], 'Education')
            self.assertEqual(store.read_blob(result['data']['content_id']), b'Learning')
            self.assertEqual(row['site_category'], 'Technology')

    def test_invalid_or_extra_answers_are_not_incorporated(self):
        for response in ({'category': 'Spam'}, {'category': 'Technology', 'execute': 'script'}, []):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as root:
                store = Store(root);provider = Mock(campaign='fixture');provider.chat.return_value=response
                with self.assertRaises(ContractError):
                    review(store, provider, 'run', 'category', {}, {'id': 1, 'url': 'https://fixture.example/'}, '<p>Test</p>')
                self.assertEqual(store.list('category_review'), [])

    def test_private_export_contains_reviewed_content_but_public_export_omits_it(self):
        from harness.engine import create_campaign
        from harness.export import bundle
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            corpus = store.append('corpus', {'examples': [], 'metadata': {'provenance': 'fixture'}})
            limits = {'max_cost_usd': .02, 'max_seconds': 60, 'max_calls': 1, 'max_output_tokens': 256}
            model = {'id': 'luna', 'model': 'openai/gpt-6-luna', 'reasoning_effort':'low', 'context_length': 32768,
                     'input_usd_per_million': 0, 'output_usd_per_million': 0, 'pricing_source': 'fixture'}
            campaign = create_campaign(store, {'name': 'Fixture category review', 'study_id': 'fixture',
                'seed': '1', 'mode': 'frozen', 'partition': 'development',
                'source': {'kind': 'urls', 'urls': ['https://fixture.example/']}, 'workers': [model],
                'conditions': [{'id': 'category', 'level': 1, 'worker_id': 'luna'}],
                'corpus_id': corpus['id'], 'repair_budget': limits, 'review_budget': limits,
                'campaign_cost_limit': .04})
            provider = Mock(campaign=campaign['id']); provider.chat.return_value = {'category': 'Technology'}
            result = review(store, provider, 'run', 'category', model,
                            {'id': 1, 'url': 'https://fixture.example/'}, '<main>Verified page text</main>')
            artifact = store.get(result['data']['content_id'])
            for private in (False, True):
                with zipfile.ZipFile(io.BytesIO(bundle(store, campaign['id'], private))) as archive:
                    records = json.loads(archive.read('records.json'))
                    self.assertIn('category', [row['id'] for row in records])
                    path = 'blobs/' + artifact['data']['sha256']
                    self.assertEqual(path in archive.namelist(), private)
                    if private:
                        self.assertEqual(archive.read(path), b'Verified page text')
