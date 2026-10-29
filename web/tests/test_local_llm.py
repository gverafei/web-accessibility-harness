import unittest
from unittest.mock import MagicMock, patch

import requests
import json
from local_llm import local_configuration
from remediation_model_choices import model_choices, model_choice


SETTINGS = {'ollama_base_url': 'http://host.docker.internal:11434',
            'ollama_model': 'llama3.1:8b', 'ollama_capabilities_json': '["completion"]'}


def native_response(content, incoming=0, outgoing=0):
    response = MagicMock(status_code=200)
    response.iter_lines.return_value = [
        json.dumps({'message': {'content': content}, 'done': False}).encode(),
        json.dumps({'message': {'content': ''}, 'done': True,
                    'prompt_eval_count': incoming, 'eval_count': outgoing}).encode(),
    ]
    return response


class LocalLlmTests(unittest.TestCase):
    def test_legacy_local_settings_do_not_inject_an_unselected_model_into_pool(self):
        self.assertIsNone(local_configuration({}))
        self.assertEqual(model_choices(SETTINGS), model_choices())
        self.assertTrue(all(not choice['id'].startswith('ollama/') for choice in model_choices(SETTINGS)))
        with self.assertRaises(ValueError):
            model_choice('ollama/llama3.1:8b', SETTINGS)

    def test_configuration_validation(self):
        self.assertEqual(local_configuration(SETTINGS)['base_url'], 'http://host.docker.internal:11434/v1')
        self.assertEqual(local_configuration(dict(SETTINGS, ollama_base_url='http://server:11434/v1/'))['base_url'], 'http://server:11434/v1')
        for change in ({'ollama_model': ''}, {'ollama_base_url': ''},
                       {'ollama_base_url': 'file:///tmp/test'},
                       {'ollama_base_url': 'https://user:password@server'},
                       {'ollama_base_url': 'https://ollama.com'},
                       {'ollama_model': 'model-cloud'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                local_configuration(dict(SETTINGS, **change))

    def test_local_dispatch_keeps_parameters_and_has_no_paid_auth(self):
        from remediation_jobs import call_model
        response = native_response('{"patches":[]}', 10, 20)
        messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Repair'},
                                                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]
        with patch('remediation_jobs.requests.post', return_value=response) as post:
            result = call_model(SETTINGS, 'ollama/llama3.1:8b', 'Repair',
                                json_mode=True, temperature=.5, messages=messages,
                                output_token_limit=6000, reasoning_override='low')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], 'http://host.docker.internal:11434/api/chat')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['model'], 'llama3.1:8b')
        self.assertEqual(payload['options']['temperature'], .5)
        self.assertEqual(payload['options']['num_predict'], 6000)
        self.assertEqual(payload['options']['num_ctx'], 32768)
        self.assertFalse(payload['truncate'])
        self.assertFalse(payload['shift'])
        self.assertEqual(payload['format'], 'json')
        self.assertEqual(payload['messages'][0]['content'], 'Repair')
        self.assertNotIn('reasoning', payload)
        self.assertNotIn('headers', post.call_args.kwargs)
        self.assertEqual(result[1:4], (10, 20, 0.))
        self.assertEqual(result[-1], 'ollama/llama3.1:8b')

    def test_snapshot_survives_settings_changes(self):
        from remediation_jobs import call_model
        response = native_response('HTML')
        with patch('remediation_jobs.requests.post', return_value=response) as post:
            call_model({'_local_llm_config': local_configuration(SETTINGS)},
                       'ollama/llama3.1:8b', 'Generate')
        self.assertIn('host.docker.internal', post.call_args.args[0])

    def test_network_error_does_not_fall_back(self):
        from remediation_jobs import call_model
        with patch('remediation_jobs.requests.post', side_effect=requests.ConnectionError('offline')) as post:
            with self.assertRaises(requests.ConnectionError):
                call_model(SETTINGS, 'ollama/llama3.1:8b', 'Generate')
        self.assertEqual(post.call_count, 1)

    def test_native_vision_and_frozen_context_preserve_complete_messages(self):
        from local_llm import local_chat
        config = dict(local_configuration(SETTINGS), vision=True, context_length=40960)
        response = native_response('ok', 21000, 12)
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'complete source'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]
        with patch('local_llm.requests.post', return_value=response) as post:
            self.assertEqual(local_chat(config, messages, temperature=.2), ('ok', 21000, 12))
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['messages'][0], {'role': 'user', 'content': 'complete source', 'images': ['AAAA']})
        self.assertEqual(payload['options']['num_ctx'], 40960)
        self.assertEqual(payload['options']['temperature'], .2)

    def test_native_context_overflow_is_explicit_not_silently_retried(self):
        from local_llm import local_chat
        response = MagicMock(status_code=400)
        response.json.return_value = {'error': 'input exceeds context length'}
        with patch('local_llm.requests.post', return_value=response) as post:
            with self.assertRaisesRegex(requests.RequestException, 'input exceeds context length'):
                local_chat(local_configuration(SETTINGS), [{'role': 'user', 'content': 'source'}])
        self.assertEqual(post.call_count, 1)
        from local_llm import LocalModelError
        from remediation_completion import retain_interrupted_result
        self.assertTrue(retain_interrupted_result(42, 'automated', isinstance(LocalModelError('context overflow'), requests.RequestException)))

    def test_non_thinking_mode_and_output_ceiling_are_preserved(self):
        from remediation_jobs import call_model
        settings = dict(SETTINGS, ollama_model='qwen3.5:4b', ollama_capabilities_json='["completion", "thinking"]')
        response = native_response('ok')
        with patch('local_llm.requests.post', return_value=response) as post, \
             patch.dict('os.environ', {'REMEDIATION_OUTPUT_TOKEN_LIMIT': '5000'}):
            call_model(settings, 'ollama/qwen3.5:4b', 'repair', output_token_limit=6000, temperature=.5)
        payload = post.call_args.kwargs['json']
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options']['num_predict'], 5000)
        self.assertEqual(payload['options']['temperature'], .5)

    def test_every_thinking_local_model_uses_bounded_non_thinking_mode(self):
        from local_llm import local_configuration
        settings = dict(SETTINGS, ollama_model='gemma4:latest',
                        ollama_capabilities_json='["completion", "vision", "thinking"]')
        self.assertEqual(local_configuration(settings)['reasoning_effort'], 'none')

    def test_partial_stream_is_never_used_as_a_candidate(self):
        from local_llm import local_chat
        response = native_response('partial HTML')
        response.iter_lines.return_value = [b'{"message":{"content":"partial HTML"},"done":false}']
        with patch('local_llm.requests.post', return_value=response):
            with self.assertRaisesRegex(requests.RequestException, 'partial output was not applied'):
                local_chat(local_configuration(SETTINGS), [{'role': 'user', 'content': 'source'}])
        response.close.assert_called_once()

    def test_local_snapshot_blocks_every_remote_call(self):
        from remediation_jobs import call_model
        with patch('remediation_jobs.requests.post') as post, self.assertRaises(ValueError):
            call_model({'_local_llm_config': local_configuration(SETTINGS)},
                       'openrouter/auto', 'Inspect')
        post.assert_not_called()

    def test_connection_check_only_lists_installed_models(self):
        from main import app
        response = MagicMock()
        response.json.return_value = {'models': [{'name': 'llama3.1:8b'}]}
        with patch('routes.experiments.get_settings', return_value=SETTINGS), \
             patch('routes.experiments.requests.get', return_value=response) as get, \
             patch('routes.experiments.requests.post') as post:
            result = app.test_client().post('/configuration/test-ollama')
        self.assertEqual(result.status_code, 302)
        self.assertEqual(get.call_args.args[0], 'http://host.docker.internal:11434/api/tags')
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith('/api/show'))

    def test_connection_check_handles_ollama_null_model_list(self):
        from main import app
        response = MagicMock()
        response.json.return_value = {'models': None}
        with patch('routes.experiments.get_settings', return_value=SETTINGS), \
             patch('routes.experiments.requests.get', return_value=response):
            result = app.test_client().post('/configuration/test-ollama')
        self.assertEqual(result.status_code, 302)
