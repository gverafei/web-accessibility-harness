import unittest

from remediation_agent_runtime import AgentRuntime


class TaskAgentTest(unittest.TestCase):
    def test_task_closes_with_its_result_and_does_not_change_worker_or_permissions(self):
        runtime = AgentRuntime(1, 7, 5, 1800)
        before = runtime.snapshot()
        result = runtime.perform('repair-generator', lambda: ('HTML', 20, 10, .001, 1.0, 'fixture'),
                                 ('current_document', 'frozen_worker'))
        record = runtime.snapshot()['agent_tasks'][0]
        self.assertEqual(result[0], 'HTML')
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['input_keys'], ['current_document', 'frozen_worker'])
        self.assertEqual(runtime.snapshot()['budgets'], before['budgets'])
        self.assertEqual(runtime.state, 'init')

    def test_incomplete_result_or_exception_is_visible_without_fabricating_completion(self):
        runtime = AgentRuntime(3, 8, 5, 1800)
        with self.assertRaises(TypeError):
            runtime.perform('repair-generator', lambda: {'unexpected': 'object'})
        self.assertEqual(runtime.task_records[-1]['status'], 'incomplete')
        with self.assertRaises(RuntimeError):
            runtime.perform('visual-reviewer', lambda: (_ for _ in ()).throw(RuntimeError('fixture')))
        self.assertEqual(runtime.task_records[-1]['error_type'], 'RuntimeError')
        self.assertEqual(len(runtime.task_records), 2)
