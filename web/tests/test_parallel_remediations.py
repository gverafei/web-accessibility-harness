import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock

from remediation_concurrency import concurrency_limit, remediation_slot, validate_concurrency
from remediation_queue import RemediationQueue


class ParallelRemediationTests(unittest.TestCase):
    def test_limit_is_bounded_and_invalid_storage_uses_default(self):
        for value in (1, 2, 3, 4, 5):
            self.assertEqual(concurrency_limit({'parallel_remediations': str(value)}), value)
            self.assertEqual(validate_concurrency(value), str(value))
        for value in (0, 6, 'many', None, '2.5'):
            self.assertEqual(concurrency_limit({'parallel_remediations': value}), 2)
            with self.assertRaises(ValueError):
                validate_concurrency(value)

    def test_shared_slots_bound_runs_and_exclude_duplicate_run(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            self.assertTrue(stack.enter_context(remediation_slot(1, 2, root)))
            self.assertTrue(stack.enter_context(remediation_slot(2, 2, root)))
            self.assertFalse(stack.enter_context(remediation_slot(3, 2, root)))
            self.assertFalse(stack.enter_context(remediation_slot(1, 5, root)))

    def test_lower_limit_waits_for_existing_runs_without_cancelling(self):
        with tempfile.TemporaryDirectory() as root:
            contexts = [remediation_slot(index, 5, root) for index in range(5)]
            for context in contexts:
                self.assertTrue(context.__enter__())
            try:
                with remediation_slot(10, 5, root) as admitted:
                    self.assertFalse(admitted)
                contexts.pop(0).__exit__(None, None, None)
                with remediation_slot(11, 1, root) as admitted:
                    self.assertFalse(admitted)
            finally:
                for context in contexts:
                    context.__exit__(None, None, None)
            with remediation_slot(12, 1, root) as admitted:
                self.assertTrue(admitted)

    def test_exception_releases_slot_and_other_process_cannot_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            code = ('import json,sys; from remediation_concurrency import remediation_slot; '
                    'c=remediation_slot(2,1,sys.argv[1]); print(json.dumps(c.__enter__())); '
                    'c.__exit__(None,None,None)')
            with self.assertRaises(RuntimeError):
                with remediation_slot(1, 1, root):
                    result = subprocess.run([sys.executable, '-c', code, root],
                                            capture_output=True, text=True, check=True)
                    self.assertFalse(json.loads(result.stdout))
                    raise RuntimeError('Fixture exception')
            with remediation_slot(2, 1, root) as admitted:
                self.assertTrue(admitted)

    def test_queue_starts_five_distinct_runs_and_applies_decrease_to_new_starts(self):
        queue = RemediationQueue(Mock())
        release = threading.Event()
        started = [threading.Event() for _ in range(6)]
        def execute(run_id):
            started[run_id].set()
            release.wait(3)
        queue._execute = execute
        try:
            self.assertTrue(queue.dispatch(range(6), 5))
            self.assertTrue(all(event.wait(1) for event in started[:5]))
            self.assertFalse(started[5].is_set())
            queue.dispatch(range(6), 1)
            self.assertEqual(set(queue.active), set(range(5)))
            self.assertFalse(started[5].is_set())
        finally:
            release.set()
            queue.close()

class ParallelConfigurationTests(unittest.TestCase):


    def test_terminal_run_is_not_processed_again_after_slot_release(self):
        from remediation_jobs import process_remediation
        from unittest.mock import patch
        connection = Mock()
        connection.cursor.return_value.fetchone.return_value = {'status': 'accepted'}
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, HARNESS_ROOT=root), \
             patch('remediation_jobs.get_settings', return_value={}), \
             patch('remediation_jobs.get_connection', return_value=connection), \
             patch('remediation_jobs._snapshot') as snapshot:
            process_remediation(Mock(), 1)
        snapshot.assert_not_called()
        connection.close.assert_called_once()
