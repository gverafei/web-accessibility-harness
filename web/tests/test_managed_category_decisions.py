import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from harness.store import Store
from managed_category_decisions import classify_batch
from classify_site_categories import CategoryResponseError


class ManagedDecisionsTests(unittest.TestCase):
    def test_closed_choices_pin_model_and_save_totals_even_after_refusal(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root); connection=MagicMock()
            config={'job_id':'fixture','max_call_cost_usd':.25,'max_job_cost_usd':.5,
                    'base_url':'https://saved.invalid/api/v1','definition':{'model':'fixture'}}
            rows=[{'id':7,'url':'https://example.org/','title':'University'}]
            with patch('managed_category_decisions.Store',return_value=store), patch('managed_category_decisions.Providers') as factory, patch('managed_category_decisions.get_connection',return_value=connection):
                provider=factory.return_value
                provider.ledger.rows.return_value=[{'input_tokens':30,'output_tokens':2,'cost':.001}]
                provider.decisions.return_value={'7':{'type':'choice','choice':'Education'}}
                self.assertEqual(json.loads(classify_batch({},config,rows)),{'7':'Education'})
                self.assertEqual(provider.decisions.call_args.kwargs['model'],config['definition'])
                questions=provider.decisions.call_args.args[4]
                self.assertEqual(questions[0]['name'],'7')
                self.assertIn('unknown',[c['value'] for c in questions[0]['choices']])
                provider.decisions.return_value={'7':{'type':'refusal'}}
                with self.assertRaises(CategoryResponseError):classify_batch({},config,rows)
                self.assertEqual(connection.commit.call_count,2)
                self.assertIn('SET input_tokens=%s',connection.cursor.return_value.execute.call_args.args[0])
