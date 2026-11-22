import unittest
from unittest.mock import Mock, patch
from remediation_jobs import _current_consumption, _write_recorded_consumption


class LiveConsumptionTests(unittest.TestCase):
    def test_replayed_generation_does_not_add_again_and_new_review_is_included(self):
        bridge = Mock()
        bridge.costs.side_effect = [
            dict(input_tokens=100, output_tokens=30, cost_usd=.23),
            dict(input_tokens=100, output_tokens=30, cost_usd=.23),
            dict(input_tokens=120, output_tokens=40, cost_usd=.29),
        ]
        cursor = Mock()
        for incoming, outgoing, generation_cost in [(70, 20, .1), (140, 40, .2), (140, 40, .2)]:
            usage = _current_consumption(bridge, incoming, outgoing, generation_cost)
            _write_recorded_consumption(cursor, 411, usage)
        self.assertEqual([call.args[1][2] for call in cursor.execute.call_args_list], [.23, .23, .29])
        self.assertEqual(cursor.execute.call_args.args[1], (120, 40, .29, 411))

    def test_local_execution_preserves_usage_and_optional_elapsed_time(self):
        cursor = Mock()
        usage = _current_consumption(None, 50, 10, 0)
        _write_recorded_consumption(cursor, 9, usage, 12.5)
        self.assertEqual(cursor.execute.call_args.args[1], (50, 10, 0, 12.5, 9))
        self.assertIn('execution_seconds=%s', cursor.execute.call_args.args[0])

    def test_run_starts_progress_before_any_paid_stage(self):
        from remediation_jobs import process_remediation
        class InitialProgressReached(BaseException):
            pass
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = {'intervention_version': 'fixture'}
        with patch('remediation_jobs.get_settings', return_value={}), \
             patch('remediation_jobs.get_connection', return_value=connection), \
             patch('remediation_jobs._snapshot', return_value='<html><body>Source</body></html>'), \
             patch('remediation_jobs.versioned_approach', return_value=Mock(step=0)), \
             patch('remediation_jobs.build_agent_runtime'), \
             patch('remediation_jobs._progress', side_effect=InitialProgressReached) as progress:
            with self.assertRaises(InitialProgressReached):
                process_remediation(Mock(), 412)
        progress.assert_called_once_with(cursor, connection, 412, 'acquire', 5,
                                         'Loading the preserved acquired snapshot')
