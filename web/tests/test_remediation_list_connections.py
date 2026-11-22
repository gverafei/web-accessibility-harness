import unittest
from unittest.mock import Mock,patch
from main import app
from routes.remediation import runs

class RemediationListConnectionTests(unittest.TestCase):
    def test_failed_list_read_closes_cursor_and_transaction(self):
        connection=Mock();cursor=connection.cursor.return_value
        cursor.fetchall.side_effect=RuntimeError('Large historical record sort failure')
        with app.test_request_context('/remediation/'),patch('routes.remediation.get_connection',return_value=connection):
            with self.assertRaises(RuntimeError):runs()
        cursor.close.assert_called_once();connection.close.assert_called_once()

    def test_participation_query_projects_only_the_required_strategy_field(self):
        connection=Mock();cursor=connection.cursor.return_value;cursor.fetchall.side_effect=[[],[]]
        with app.test_request_context('/remediation/'),patch('routes.remediation.get_connection',return_value=connection),patch('routes.remediation.render_template',return_value='ok'):
            self.assertEqual(runs(),'ok')
        query=cursor.execute.call_args_list[1].args[0]
        self.assertIn("JSON_UNQUOTE(JSON_EXTRACT(strategy_json,'$.assigned_level')) assigned_level",query)
        self.assertNotIn('agent_usage_json,strategy_json FROM',query)
        self.assertNotIn('ORDER BY',query)
        cursor.close.assert_called_once();connection.close.assert_called_once()
