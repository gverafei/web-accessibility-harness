import json
import unittest
from unittest.mock import patch

import category_models as models


class CategoryModelTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'ollama_base_url': 'http://local:11434',
                         'ollama_model': 'gemma4:latest', 'openrouter_api_key': 'secret'}
        self.default = {'id': 'anthropic/example@high', 'model': 'anthropic/example',
                        'label': 'Example', 'enabled': True, 'is_default': True,
                        'reasoning_effort': 'high', 'supported_parameters': ['reasoning']}

    def choices(self, settings=None, error=None):
        with (patch.object(models, 'configured_catalog', return_value=[self.default]),
              patch.object(models, 'decision_catalogue', return_value=[]),
              patch.object(models, 'local_configuration', return_value={
                  'model':'gemma4:latest','base_url':'http://local:11434/v1'}, side_effect=error)):
            return models.category_model_options(settings or self.settings)

    def test_only_configured_local_model_and_catalogue_default(self):
        choices, error = self.choices()
        self.assertFalse(error)
        self.assertEqual([item['id'] for item in choices],
                         ['ollama/gemma4:latest', 'anthropic/example@high'])
        self.assertEqual(choices[0]['config']['model'], 'gemma4:latest')
        self.assertEqual(choices[1]['config']['reasoning_effort'], 'high')

    def test_local_discovery_failure_keeps_cloud_and_disables_no_fallback(self):
        choices, error = self.choices(error=ValueError())
        self.assertTrue(error)
        self.assertEqual([item['id'] for item in choices], ['anthropic/example@high'])
        choices, _ = self.choices({**self.settings, 'openrouter_api_key': ''})
        self.assertFalse(choices[-1]['enabled'])
        self.assertTrue(choices[0]['enabled'])

    def test_exact_choice_snapshot_and_rejected_legacy_cloud_substitution(self):
        choices, _ = self.choices()
        with patch.object(models, 'category_model_options', return_value=(choices, False)):
            snapshot = models.resolve_category_model('ollama/gemma4:latest', self.settings)
            for invalid in ('luna', 'ollama/not-installed', 'anthropic/other'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    models.resolve_category_model(invalid, self.settings)
        self.assertEqual(models.load_category_snapshot(json.dumps(snapshot), snapshot['model']), snapshot)
        self.assertNotIn('secret', json.dumps(snapshot))
        snapshot['config']['model'] = 'changed'
        with self.assertRaises(ValueError):
            models.load_category_snapshot(snapshot, snapshot['model'])

    def test_legacy_jobs_remain_readable(self):
        self.assertIsNone(models.load_category_snapshot(None, 'ollama/gemma4:latest'))

    def test_saved_decisions_catalogue_is_offered_without_model_dispatch(self):
        from harness.decision_models import DEFINITIONS
        with patch.object(models,'configured_catalog',return_value=[]), patch.object(models,'local_configuration',return_value=None), patch.object(models,'decision_catalogue',return_value=list(DEFINITIONS)):
            choices,_=models.category_model_options(self.settings)
        self.assertEqual(len(choices),1)
        choice=choices[0]; self.assertEqual(choice['provider'],'decisions')
        self.assertIn('Decisions API',choice['label'])
        snapshot=models.freeze_category_model(choice)
        self.assertEqual(models.load_category_snapshot(snapshot,choice['model']),snapshot)
        self.assertNotIn('secret',json.dumps(snapshot))
