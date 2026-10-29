import unittest
from unittest.mock import Mock, MagicMock
from harness.contracts import ContractError
from harness.environment import Environment


class SnapshotRecoveryTests(unittest.TestCase):
    def test_identical_snapshot_retries_once_only_for_browser_crashes(self):
        environment = Environment(MagicMock())
        body = {'manifest_path': '/results/frozen.json'}
        environment.post = Mock(side_effect=[ContractError('page.evaluate: Target crashed'), {'results': ['saved']}])
        self.assertEqual(environment.post_snapshot(body, 'campaign', 'audit', '<p>same</p>'), {'results': ['saved']})
        self.assertEqual(environment.post.call_count, 2)
        self.assertEqual(environment.post.call_args_list[0], environment.post.call_args_list[1])
        self.assertFalse(environment.store.append.call_args.args[1]['generation_repeated'])
        for failures, expected in (([ContractError('Invalid resource checksum')], 1),
                                   ([ContractError('Target crashed'), ContractError('Target crashed')], 2)):
            environment.post = Mock(side_effect=failures)
            with self.assertRaises(ContractError):
                environment.post_snapshot(body, 'campaign', 'audit', '<p>same</p>')
            self.assertEqual(environment.post.call_count, expected)


    def test_concurrent_conditions_share_browser_capacity_across_store_instances(self):
        import tempfile
        import threading
        import time
        from contextlib import contextmanager
        from concurrent.futures import ThreadPoolExecutor
        from harness.store import Store
        arrivals = 0
        active = 0
        peak = 0
        guard = threading.Lock()
        all_arrived = threading.Event()

        class ObservedStore(Store):
            @contextmanager
            def named_lock(self, key):
                nonlocal arrivals
                with guard:
                    arrivals += 1
                    if arrivals == 5:
                        all_arrived.set()
                with super().named_lock(key):
                    yield

        def post(endpoint, body):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                self.assertTrue(all_arrived.wait(2))
                time.sleep(.01)
                return {'results': [body['manifest_path']]}
            finally:
                with guard:
                    active -= 1

        with tempfile.TemporaryDirectory() as directory:
            environments = [Environment(ObservedStore(directory)) for _ in range(5)]
            for environment in environments:
                environment.post = post
            with ThreadPoolExecutor(max_workers=5) as executor:
                jobs = [executor.submit(environment.post_snapshot,
                    {'manifest_path': str(index)}, 'campaign'+str(index),
                    'audit'+str(index), '<main>same</main>')
                    for index, environment in enumerate(environments)]
                self.assertEqual([job.result()['results'][0] for job in jobs],
                                 [str(index) for index in range(5)])
        self.assertEqual(peak, 1)
        self.assertEqual(arrivals, 5)

    def test_browser_capacity_is_released_after_a_nonretryable_failure(self):
        import tempfile
        from harness.store import Store
        with tempfile.TemporaryDirectory() as directory:
            first = Environment(Store(directory))
            first.post = Mock(side_effect=ContractError('Invalid resource checksum'))
            with self.assertRaises(ContractError):
                first.post_snapshot({'manifest_path': 'first'}, 'campaign', 'audit1', 'source')
            second = Environment(Store(directory))
            second.post = Mock(return_value={'results': ['second']})
            self.assertEqual(second.post_snapshot({'manifest_path': 'second'},
                             'campaign', 'audit2', 'source'), {'results': ['second']})
            first.post.assert_called_once()
            second.post.assert_called_once()
