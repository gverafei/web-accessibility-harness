import json
import unittest
from unittest.mock import MagicMock, patch
from remediation_model_choices import (default_catalog, validate_catalog, model_choices,
    model_choice, frozen_model_configuration, discover_models, configured_catalog)


class DynamicCatalogueTests(unittest.TestCase):
    def settings(self, choices):
        return {'remediation_model_catalog_json': json.dumps(choices),
                'generative_model_metadata_json': json.dumps({c['model']: dict(c, model=c['model']) for c in choices})}

    def test_fresh_installation_has_current_models_and_one_green_luna_default(self):
        choices = configured_catalog({'remediation_model_catalog_json': ''})
        self.assertEqual({c['model'] for c in choices}, {
            'openai/gpt-6-luna', 'openai/gpt-6.1-sol',
        })
        defaults = [c for c in choices if c['is_default']]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0]['id'], 'openai/gpt-6-luna')
        self.assertEqual(defaults[0]['color'], '#2f9e66')
        self.assertEqual(validate_catalog(choices), configured_catalog(self.settings(choices)))

    def test_bundled_defaults_never_replace_a_saved_catalogue(self):
        saved = [dict(default_catalog()[2], id='researcher-model', model='future/research-model')]
        self.assertEqual([c['id'] for c in configured_catalog(self.settings(saved))], ['researcher-model'])

    def test_saved_older_sol_remains_selectable_without_being_bundled(self):
        saved = [dict(default_catalog()[2], id='openai/gpt-6-sol',
                      model='openai/gpt-6-sol', label='GPT-6 Sol')]
        with self.assertRaises(ValueError):
            model_choice('openai/gpt-6-sol', self.settings(saved))
        self.assertFalse(configured_catalog(self.settings(saved))[0]['enabled'])
        self.assertNotIn('openai/gpt-6-sol', {choice['model'] for choice in default_catalog()})

    def test_unknown_future_model_works_without_a_code_change(self):
        choice = dict(default_catalog()[2], id='my-lola', model='openai/gpt-lola-6.1', label='GPT Lola 6.1')
        settings = self.settings([choice])
        self.assertEqual(model_choices(settings), [])
        self.assertEqual(configured_catalog(settings)[0]['model'], 'openai/gpt-lola-6.1')

    def test_disabled_choices_do_not_appear_and_order_is_preserved(self):
        choices = default_catalog()
        choices[2]['enabled'] = choices[2]['is_default'] = False
        choices.reverse()
        self.assertEqual([c['id'] for c in model_choices(self.settings(choices))],
                         [c['id'] for c in choices if c['enabled']])

    def test_snapshot_does_not_follow_catalogue_edits(self):
        original = model_choice('openai/gpt-6-luna@high')
        snapshot = frozen_model_configuration(original)
        original.update(model='future/changed', reasoning_effort='low')
        self.assertEqual(snapshot['model'], 'openai/gpt-6-luna')
        self.assertEqual(snapshot['reasoning_effort'], 'high')
        self.assertEqual(len(snapshot['digest']), 64)

    def test_router_empty_duplicate_invalid_colors_and_efforts_are_rejected(self):
        base = default_catalog()[0]
        for choices in ([], [base, base], [dict(base, model='openrouter/auto')],
                        [dict(base, color='red')], [dict(base, enabled=False)],
                        [dict(base, reasoning_effort='unsupported')], [dict(base, id='<script>')]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                validate_catalog(choices)

    def test_discovery_reads_capabilities_and_prices_without_generation(self):
        response = MagicMock()
        response.json.return_value = {'data': [{'id': 'future/lola-6.1', 'name': 'Lola',
            'supported_parameters': ['reasoning', 'temperature', 'response_format', 'max_tokens'], 'context_length': 32000, 'pricing': {'prompt':'0.000001','completion':'0.000002'},
            'architecture': {'input_modalities': ['text','image'], 'output_modalities': ['text']}}]}
        with patch('remediation_model_choices.requests.get', return_value=response) as get:
            models = discover_models({'openrouter_base_url':'https://example.org/api', 'openrouter_api_key':'test'})
        self.assertTrue(models[0]['vision'])
        self.assertTrue(models[0]['reasoning_supported'])
        self.assertEqual(models[0]['input_usd_per_million'], 1)
        self.assertEqual(models[0]['output_usd_per_million'], 2)
        self.assertEqual(get.call_args.args[0], 'https://example.org/api/models')

    def test_catalogue_endpoint_saves_only_valid_configuration(self):
        from main import app
        client=app.test_client()
        with client.session_transaction() as session: session['csrf_token']='fixture-catalog-token'
        with patch('routes.model_catalog.save_settings') as save:
            response = client.post('/configuration/models', headers={'X-CSRF-Token':'fixture-catalog-token'}, json={'choices': default_catalog()})
            self.assertEqual(response.status_code, 200)
            save.assert_called_once()
            response = client.post('/configuration/models', headers={'X-CSRF-Token':'fixture-catalog-token'}, json={'choices': []})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(save.call_count, 1)
