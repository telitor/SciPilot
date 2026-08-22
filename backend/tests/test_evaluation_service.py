import unittest

from services.evaluation_service import attach_evaluation_trends


class EvaluationTrendTests(unittest.TestCase):
    def test_compares_newest_run_with_previous_dataset_version(self):
        rows = [
            {
                "id": "new",
                "suite_id": "suite-v2",
                "mode": "real-model",
                "status": "completed",
                "metrics": {
                    "pass_rate": 0.9,
                    "p95_latency_ms": 900,
                    "estimated_cost_cny": 0.12,
                },
            },
            {
                "id": "old",
                "suite_id": "suite-v1",
                "mode": "real-model",
                "status": "completed",
                "metrics": {
                    "pass_rate": 0.7,
                    "p95_latency_ms": 1200,
                    "estimated_cost_cny": 0.1,
                },
            },
        ]
        suites = {
            "suite-v2": {"slug": "provider-smoke", "version": 2},
            "suite-v1": {"slug": "provider-smoke", "version": 1},
        }

        enriched = attach_evaluation_trends(rows, suites)

        self.assertEqual(enriched[0]["suite_version"], 2)
        self.assertEqual(enriched[0]["comparison"]["previous_run_id"], "old")
        self.assertEqual(enriched[0]["comparison"]["previous_suite_version"], 1)
        self.assertAlmostEqual(enriched[0]["comparison"]["deltas"]["pass_rate"], 0.2)
        self.assertEqual(enriched[0]["comparison"]["deltas"]["p95_latency_ms"], -300.0)

    def test_does_not_compare_different_modes_or_suite_slugs(self):
        rows = [
            {
                "id": "new",
                "suite_id": "a",
                "mode": "offline",
                "status": "completed",
                "metrics": {"mrr": 1.0},
            },
            {
                "id": "old",
                "suite_id": "b",
                "mode": "real-model",
                "status": "completed",
                "metrics": {"mrr": 0.5},
            },
        ]

        enriched = attach_evaluation_trends(
            rows,
            {
                "a": {"slug": "retrieval", "version": 1},
                "b": {"slug": "retrieval", "version": 1},
            },
        )

        self.assertEqual(enriched[0]["comparison"], {})


if __name__ == "__main__":
    unittest.main()
