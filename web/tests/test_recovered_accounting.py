import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class RecoveredAccountingTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader(
            Path(__file__).resolve().parents[1] / 'app/templates'), autoescape=True)
        self.env.globals['_'] = lambda text: text

    def test_missing_run_tokens_are_not_displayed_as_zero(self):
        rendered = self.env.get_template('_remediation_run_accounting.html').render(
            best={'strategy': {'recovery': {'source': 'paper-recovery'}}},
            run={'total_input_tokens': 0, 'total_output_tokens': 0, 'execution_seconds': 65})
        self.assertIn('Token count unavailable', rendered)
        self.assertNotIn('0 tokens', rendered)
        self.assertIn('65.0 s', rendered)

    def test_missing_iteration_accounting_is_not_displayed_as_free(self):
        rendered = self.env.get_template('_remediation_iteration_accounting.html').render(
            item={'strategy': {'recovery': {'source': 'paper-recovery'}},
                  'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'execution_seconds': 0})
        self.assertIn('unavailable', rendered)
        self.assertNotIn('$0.000000', rendered)
        self.assertNotIn('0 tokens', rendered)

    def test_regular_iteration_accounting_is_preserved(self):
        rendered = self.env.get_template('_remediation_iteration_accounting.html').render(
            item={'strategy': {}, 'input_tokens': 2, 'output_tokens': 3,
                  'cost_usd': 0.0123, 'execution_seconds': 4, 'wave_credits_used': 0})
        self.assertIn('5 tokens', rendered)
        self.assertIn('$0.012300', rendered)
        self.assertIn('4.0 s', rendered)
