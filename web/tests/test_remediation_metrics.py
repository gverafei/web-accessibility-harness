import unittest

from routes.remediation import global_lighthouse_metrics, improvement_metrics


class RemediationImprovementMetricTests(unittest.TestCase):
    def test_lighthouse_improvement_recovers_original_gap_to_perfect_score(self):
        metrics = improvement_metrics(24, 16, 87, 92)

        self.assertAlmostEqual(metrics["axe_percent"], 33.333333, places=5)
        self.assertAlmostEqual(metrics["lighthouse_headroom_percent"], 38.461538, places=5)

    def test_perfect_lighthouse_score_has_no_remaining_gap_to_recover(self):
        metrics = improvement_metrics(0, 0, 100, 100)

        self.assertEqual(metrics["axe_percent"], 0.0)
        self.assertEqual(metrics["lighthouse_headroom_percent"], 0.0)

    def test_global_lighthouse_includes_terminal_unaccepted_candidates(self):
        summary = global_lighthouse_metrics([
            {"status": "accepted", "original_lighthouse": 80, "result_lighthouse": 100},
            {"status": "metrics_not_achieved", "original_lighthouse": 80, "result_lighthouse": 90},
        ])

        self.assertEqual(summary["average_gain"], 15.0)
        self.assertEqual(summary["headroom_percent"], 75.0)


if __name__ == "__main__":
    unittest.main()
