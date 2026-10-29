import unittest
import json
from unittest.mock import MagicMock, patch
from remediation_model_choices import model_choices,model_choice


class UserModelChoiceTests(unittest.TestCase):
    def test_models_expose_current_gpt6_recipes(self):
        choices=model_choices()
        self.assertEqual(len(choices),3)
        self.assertEqual([(c['model'],c['reasoning_effort']) for c in choices], [
            ('openai/gpt-6-luna','low'),('openai/gpt-6-luna','high'),('openai/gpt-6.1-sol','low')])
        self.assertEqual(len({c['color'] for c in choices}),3)

    def test_choices_do_not_enable_expensive_reasoning_or_auto_routing(self):
        for choice in model_choices():
            self.assertIn(choice['reasoning_effort'],(None,'low','medium','high'))
            self.assertNotIn('openrouter/auto',choice['id'])
            self.assertNotIn('preview',choice['id'])
        with self.assertRaises(ValueError): model_choice('anthropic/claude-haiku-5.5')
        self.assertFalse(model_choice('openai/gpt-6.1-sol')['temperature_supported'])
        with self.assertRaises(ValueError): model_choice('openrouter/auto')
