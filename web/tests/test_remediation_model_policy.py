import unittest
from unittest.mock import patch
from remediation_jobs import call_model


class ExplicitModelPolicyTests(unittest.TestCase):
    def test_reasoning_and_visible_patch_share_allowance_across_three_tiers(self):
        # The observed high-effort call spent all 4000 completion tokens on
        # reasoning. JSON refinements must have the same room as initial HTML.
        for model, effort in [('openai/gpt-6-astra','high'),('openai/gpt-6-luna','low'),('openai/gpt-6-luna','high'),('openai/gpt-6-sol','low'),('anthropic/claude-haiku-5.5','high'),('anthropic/claude-opus-5.5','high'),('anthropic/claude-sonnet-5.5','low'),('anthropic/claude-sonnet-5.5','high'),('openai/gpt-6.1-sol','high'),('openai/gpt-6-luna','medium'),('openai/gpt-6-luna','xhigh')]:
            for json_mode in (False, True):
                sent=[]
                settings={'_model_configuration':{'model':model,'reasoning_effort':effort},
                          '_harness_transport':lambda body:(sent.append(body) or ('patch',1,1,.001,1,model))}
                with patch.dict('os.environ',{},clear=True):
                    call_model(settings,model,'Task',json_mode=json_mode)
                self.assertEqual(sent[0]['max_tokens'],32000)
                self.assertEqual(sent[0]['reasoning']['effort'],effort)

    def test_high_effort_uses_published_capacity_without_operator_token_caps(self):
        from remediation_output_budget import output_token_ceiling
        for effort in ('high', 'xhigh', 'max'):
            settings = {'_model_configuration': {'model':'worker',
                        'reasoning_effort':effort, 'max_completion_tokens':128000}}
            with patch.dict('os.environ', {'REMEDIATION_OUTPUT_TOKEN_LIMIT':'8192'}):
                for explicit in (None, 1200, 32000, 128000):
                    self.assertEqual(output_token_ceiling(settings, 'worker', explicit), 128000)

    def test_lower_effort_retains_its_existing_output_policy(self):
        from remediation_output_budget import output_token_ceiling
        for effort in ('low', 'medium'):
            settings = {'_model_configuration': {'model':'worker',
                        'reasoning_effort':effort, 'max_completion_tokens':128000}}
            with patch.dict('os.environ', {}, clear=True):
                self.assertEqual(output_token_ceiling(settings, 'worker'), 32000)
                self.assertEqual(output_token_ceiling(settings, 'worker', 128000), 128000)

    def test_completion_allowance_respects_all_explicit_lower_limits(self):
        from remediation_output_budget import output_token_ceiling
        settings={'_model_configuration':{'model':'worker','max_completion_tokens':9000}}
        with patch.dict('os.environ',{'REMEDIATION_OUTPUT_TOKEN_LIMIT':'16000'}):
            self.assertEqual(output_token_ceiling(settings,'worker'),9000)
            self.assertEqual(output_token_ceiling(settings,'worker',1200),1200)
            self.assertEqual(output_token_ceiling(settings,'other',20000),16000)

    def test_complete_document_allowance_respects_published_maximum_and_operator_limit(self):
        from remediation_output_budget import output_token_ceiling, FULL_DOCUMENT_OUTPUT_TOKENS
        settings={'_model_configuration':{'model':'worker','max_completion_tokens':64000}}
        with patch.dict('os.environ',{},clear=True):
            self.assertEqual(output_token_ceiling(settings,'worker',FULL_DOCUMENT_OUTPUT_TOKENS),64000)
            self.assertEqual(output_token_ceiling(settings,'other'),32000)
        with patch.dict('os.environ',{'REMEDIATION_OUTPUT_TOKEN_LIMIT':'16000'}):
            self.assertEqual(output_token_ceiling(settings,'worker',FULL_DOCUMENT_OUTPUT_TOKENS),16000)

    def test_empty_paid_response_retains_usage_before_output_validation(self):
        settings = {'openrouter_base_url':'https://example.org','openrouter_api_key':'test'}
        with patch('remediation_jobs.requests.post') as post:
            post.return_value.json.return_value = {
                'model':'future/coder', 'choices':[{'message':{'content':None}}],
                'usage':{'prompt_tokens':80,'completion_tokens':12,'cost':.003}}
            result = call_model(settings, 'future/coder', 'Task')
        self.assertEqual(result[0], '')
        self.assertEqual(result[1:3], (80, 12))
        self.assertAlmostEqual(result[3], .003)

    def test_automatic_routing_is_rejected_without_a_paid_call(self):
        with patch('remediation_jobs.requests.post') as post:
            with self.assertRaisesRegex(ValueError, 'removed'):
                call_model({'openrouter_base_url':'https://example.org','openrouter_api_key':'test'},
                           'openrouter/auto', 'Task')
        post.assert_not_called()

    def test_frozen_unknown_future_model_and_reasoning_are_sent_unchanged(self):
        settings = {'openrouter_base_url':'https://example.org','openrouter_api_key':'test',
                    '_model_configuration':{'model':'future/gpt-lola-6.1','reasoning_effort':'high','temperature_supported':False}}
        with patch('remediation_jobs.requests.post') as post:
            post.return_value.json.return_value={'model':'future/gpt-lola-6.1',
                'choices':[{'message':{'content':'HTML'}}], 'usage':{'cost':.02}}
            result=call_model(settings, 'future/gpt-lola-6.1', 'Task', temperature=.5)
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['model'],'future/gpt-lola-6.1')
        self.assertEqual(payload['reasoning']['effort'],'high')
        self.assertNotIn('temperature',payload)
        self.assertNotIn('plugins',payload)
        self.assertAlmostEqual(result[3],.02)

    def test_fixed_reasoning_model_does_not_get_an_invented_effort(self):
        settings = {'openrouter_base_url':'https://example.org','openrouter_api_key':'test',
                    '_model_configuration':{'model':'future/coder','reasoning_effort':None}}
        with patch('remediation_jobs.requests.post') as post:
            post.return_value.json.return_value={'choices':[{'message':{'content':'HTML'}}]}
            call_model(settings, 'future/coder', 'Task', reasoning_override='high')
        self.assertNotIn('reasoning',post.call_args.kwargs['json'])

    def test_openai_reasoning_omits_sampling_even_when_catalogue_advertises_temperature(self):
        for effort in ('low', 'high', None):
            sent = []
            settings = {
                '_model_configuration': {'model': 'openai/gpt-6-luna',
                                         'reasoning_effort': effort, 'temperature_supported': True},
                '_harness_transport': lambda body: (sent.append(body) or ('html', 1, 1, 0, 1, body['model'])),
            }
            call_model(settings, 'openai/gpt-6-luna', 'Task', temperature=.5)
            self.assertNotIn('temperature', sent[0])
            self.assertNotIn('top_p', sent[0])
            self.assertNotIn('logprobs', sent[0])

    def test_explicit_none_reasoning_can_keep_supported_temperature(self):
        sent = []
        settings = {
            '_model_configuration': {'model': 'openai/gpt-6-luna',
                                     'reasoning_effort': 'none', 'temperature_supported': True},
            '_harness_transport': lambda body: (sent.append(body) or ('html', 1, 1, 0, 1, body['model'])),
        }
        call_model(settings, 'openai/gpt-6-luna', 'Task', temperature=.5)
        self.assertEqual(sent[0]['temperature'], .5)
