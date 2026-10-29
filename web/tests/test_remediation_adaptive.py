import unittest

from remediation_adaptive import rag_activation, meaningful_improvement
from remediation_jobs import _bounded_progress


class AdaptiveRemediationTests(unittest.TestCase):
    def test_progress_messages_respect_database_contract(self):
        self.assertEqual(len(_bounded_progress('x' * 900)), 500)
        self.assertEqual(_bounded_progress(None), '')

    def test_rag_uses_measured_source_from_first_repair(self):
        self.assertEqual(rag_activation(True, 1, [{'rule': 'label'}], []),
                         (True, 'measured_failure'))
        self.assertEqual(rag_activation(True, 1, [], []),
                         (False, 'no_measured_failure'))
        self.assertEqual(rag_activation(True, 1, [], [{'id': 'contrast'}]),
                         (True, 'measured_failure'))
        self.assertEqual(rag_activation(True, 2, [], []),
                         (False, 'no_measured_failure'))
        self.assertEqual(rag_activation(True, 2, [{'rule': 'label'}], []),
                         (True, 'measured_failure'))
        self.assertEqual(rag_activation(False, 2, [{'rule': 'label'}], []),
                         (False, 'disabled'))

    def test_distance_and_material_retention_gains_continue(self):
        self.assertEqual(meaningful_improvement(5, 4, {}, {}, 90, 90, 2),
                         (True, 'automated_target_distance'))
        self.assertEqual(
            meaningful_improvement(0, 0, {'images_percent': 80},
                                   {'images_percent': 80.6}, 90, 90, 5),
            (True, 'content_retention'),
        )

    def test_tiny_changes_stop_and_visual_only_counts_for_steps_one_to_three(self):
        self.assertEqual(
            meaningful_improvement(0, 0, {'text_percent': 99.8},
                                   {'text_percent': 100}, 90, 90.5, 2),
            (False, 'marginal'),
        )
        self.assertEqual(meaningful_improvement(0, 0, {}, {}, 90, 91, 3),
                         (True, 'visual_preservation'))
        self.assertEqual(meaningful_improvement(0, 0, {}, {}, 90, 99, 5),
                         (False, 'marginal'))


if __name__ == '__main__':
    unittest.main()
