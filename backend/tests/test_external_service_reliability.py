import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.external_service_reliability import (
    ExternalServiceError,
    ExternalServicePolicy,
    external_reliability_configuration_warnings,
    external_service_runtime_snapshot,
    load_external_service_policy,
    reset_external_service_runtime_state,
    run_external_call,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class ExternalServiceReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_external_service_runtime_state()
        self.policy = ExternalServicePolicy(
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            max_attempts=3,
            backoff_initial_seconds=0.1,
            backoff_max_seconds=0.2,
            circuit_failure_threshold=2,
            circuit_cooldown_seconds=5,
        )

    def test_transient_failure_retries_with_bounded_exponential_backoff(self):
        clock = _FakeClock()
        outcomes = [TimeoutError("secret-one"), OSError("secret-two"), "ok"]

        def operation():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        result = run_external_call(
            provider="test-retry",
            operation="read",
            display_name="测试服务",
            policy=self.policy,
            call=operation,
            sleep_fn=clock.sleep,
            clock=clock.monotonic,
        )

        self.assertEqual(result.value, "ok")
        self.assertEqual(clock.sleeps, [0.1, 0.2])
        self.assertEqual(result.summary["attempts"], 3)
        self.assertEqual(result.summary["retries"], 2)
        self.assertTrue(result.summary["degraded"])
        self.assertEqual(result.summary["degradation_hint"], "recovered-after-retry")
        self.assertNotIn("secret", str(result.summary))

    def test_permanent_failure_is_normalized_without_retry_or_secret(self):
        calls = 0

        def operation():
            nonlocal calls
            calls += 1
            raise ValueError("credential=top-secret")

        with self.assertRaises(ExternalServiceError) as caught:
            run_external_call(
                provider="test-permanent",
                operation="write",
                display_name="测试服务",
                policy=self.policy,
                call=operation,
                sleep_fn=lambda _: None,
            )

        self.assertEqual(calls, 1)
        self.assertEqual(caught.exception.kind, "invalid_response")
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("top-secret", str(caught.exception))
        self.assertNotIn("top-secret", str(caught.exception.run_summary))

    def test_circuit_rejects_during_cooldown_then_allows_probe(self):
        clock = _FakeClock()
        policy = ExternalServicePolicy(
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            max_attempts=1,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=5,
        )

        with self.assertRaises(ExternalServiceError):
            run_external_call(
                provider="test-circuit",
                operation="read",
                display_name="测试服务",
                policy=policy,
                call=lambda: (_ for _ in ()).throw(TimeoutError()),
                clock=clock.monotonic,
            )

        with self.assertRaises(ExternalServiceError) as rejected:
            run_external_call(
                provider="test-circuit",
                operation="read",
                display_name="测试服务",
                policy=policy,
                call=lambda: "must-not-run",
                clock=clock.monotonic,
            )
        self.assertEqual(rejected.exception.kind, "circuit_open")
        self.assertEqual(rejected.exception.attempts, 0)
        self.assertEqual(rejected.exception.retry_after_seconds, 5)

        clock.now = 5.1
        recovered = run_external_call(
            provider="test-circuit",
            operation="read",
            display_name="测试服务",
            policy=policy,
            call=lambda: "recovered",
            clock=clock.monotonic,
        )
        self.assertEqual(recovered.value, "recovered")
        snapshot = external_service_runtime_snapshot("test-circuit")
        self.assertEqual(snapshot["successes"], 1)
        self.assertEqual(snapshot["failures"], 1)
        self.assertEqual(snapshot["circuit_rejections"], 1)
        self.assertEqual(snapshot["circuit"]["state"], "closed")

    def test_invalid_environment_uses_safe_defaults_and_reports_variable(self):
        with patch.dict(
            os.environ,
            {
                "TEST_PROVIDER_MAX_ATTEMPTS": "99",
                "SCIPILOT_EXTERNAL_BACKOFF_INITIAL_SECONDS": "not-a-number",
            },
            clear=False,
        ):
            policy = load_external_service_policy("TEST_PROVIDER")
            warnings = external_reliability_configuration_warnings()

        self.assertEqual(policy.max_attempts, 2)
        self.assertEqual(policy.backoff_initial_seconds, 0.25)
        self.assertTrue(
            any("SCIPILOT_EXTERNAL_BACKOFF_INITIAL_SECONDS" in item for item in warnings)
        )

    def test_provider_timeout_override_is_included_in_startup_warnings(self):
        with patch.dict(
            os.environ,
            {"SCIPILOT_LLM_READ_TIMEOUT_SECONDS": "9999"},
            clear=True,
        ):
            policy = load_external_service_policy("SCIPILOT_LLM")
            warnings = external_reliability_configuration_warnings()

        self.assertEqual(policy.read_timeout_seconds, 120.0)
        self.assertTrue(
            any("SCIPILOT_LLM_READ_TIMEOUT_SECONDS" in item for item in warnings)
        )


if __name__ == "__main__":
    unittest.main()
