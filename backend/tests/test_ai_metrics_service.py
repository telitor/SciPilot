import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_metrics_service import (
    build_usage_metadata,
    estimate_tokens,
    normalize_provider_usage,
)


class AiMetricsServiceTests(unittest.TestCase):
    def test_provider_usage_is_preferred(self):
        result = build_usage_metadata(
            input_text="ignored",
            output_text="ignored",
            provider_usage={"prompt_tokens": 120, "completion_tokens": 30},
            price_prefix="TEST_MODEL",
        )
        self.assertEqual(result["input_tokens"], 120)
        self.assertEqual(result["output_tokens"], 30)
        self.assertEqual(result["usage_source"], "provider")
        self.assertIsNone(result["estimated_cost_cny"])

    def test_missing_provider_usage_is_clearly_estimated(self):
        result = build_usage_metadata(
            input_text="输入文本",
            output_text="输出文本",
            provider_usage=None,
            price_prefix="TEST_MODEL",
        )
        self.assertGreater(result["input_tokens"], 0)
        self.assertGreater(result["output_tokens"], 0)
        self.assertEqual(result["usage_source"], "estimated")

    def test_cost_requires_both_prices(self):
        with patch.dict(
            os.environ,
            {
                "TEST_MODEL_INPUT_COST_CNY_PER_1M_TOKENS": "10",
                "TEST_MODEL_OUTPUT_COST_CNY_PER_1M_TOKENS": "20",
            },
            clear=False,
        ):
            result = build_usage_metadata(
                input_text="",
                output_text="",
                provider_usage={"input_tokens": 1000, "output_tokens": 500},
                price_prefix="TEST_MODEL",
            )
        self.assertEqual(result["estimated_cost_cny"], 0.02)

    def test_spark_question_token_shape_is_normalized(self):
        self.assertEqual(
            normalize_provider_usage(
                {"question_tokens": 9, "completion_tokens": 4, "total_tokens": 13}
            ),
            {"input_tokens": 9, "output_tokens": 4},
        )

    def test_estimator_never_returns_negative_values(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreater(estimate_tokens("科研助手"), 0)


if __name__ == "__main__":
    unittest.main()
