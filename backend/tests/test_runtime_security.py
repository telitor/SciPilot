import os
import unittest
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import JSONResponse

from services.rate_limit_service import ApiRateLimitMiddleware, _client_key, _rule_for
from services.runtime_config_service import inspect_runtime_configuration


class RuntimeSecurityTests(unittest.TestCase):
    def test_production_rejects_placeholder_core_credentials(self):
        env = {
            "SCIPILOT_ENV": "production",
            "SUPABASE_URL": "https://your-project-ref.supabase.co",
            "SUPABASE_ANON_KEY": "anon-placeholder",
            "SUPABASE_SERVICE_ROLE_KEY": "service-placeholder",
            "CORS_ORIGINS": "http://localhost:5173",
        }
        with patch.dict(os.environ, env, clear=True):
            report = inspect_runtime_configuration()
        self.assertGreaterEqual(len(report.errors), 3)

    def test_production_rejects_wildcard_cors_and_demo_mode(self):
        env = {
            "SCIPILOT_ENV": "production",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_ANON_KEY": "ey-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "ey-service",
            "CORS_ORIGINS": "*",
            "LOCAL_DEMO_MODE": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            report = inspect_runtime_configuration()
        self.assertTrue(any("wildcard" in item for item in report.errors))
        self.assertTrue(any("LOCAL_DEMO_MODE" in item for item in report.errors))

    def test_invalid_external_reliability_value_is_reported_without_secret(self):
        env = {
            "SCIPILOT_ENV": "local",
            "LOCAL_DEMO_MODE": "true",
            "LOCAL_DEMO_PASSWORD": "local-only-password",
            "CORS_ORIGINS": "http://localhost:5173",
            "SCIPILOT_EXTERNAL_MAX_ATTEMPTS": "100",
        }
        with patch.dict(os.environ, env, clear=True):
            report = inspect_runtime_configuration()

        self.assertTrue(
            any("SCIPILOT_EXTERNAL_MAX_ATTEMPTS" in item for item in report.warnings)
        )
        self.assertNotIn("local-only-password", str(report))

    def test_production_requires_tls_even_when_deploy_cli_is_bypassed(self):
        env = {
            "SCIPILOT_ENV": "production",
            "SUPABASE_URL": "http://supabase.internal",
            "SUPABASE_ANON_KEY": "ey-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "ey-service",
            "CORS_ORIGINS": "https://app.scipilot.internal",
            "SCIPILOT_LLM_BASE_URL": "http://maas.internal/v2",
            "XFYUN_KB_BASE_URL": "http://chatdoc.internal",
            "PROBLEM_DECOMPOSITION_WS_URL": "ws://agent.internal/chat",
            "XF_AGENT_WS_PATH": "ws://paper-agent.internal/chat",
        }
        with patch.dict(os.environ, env, clear=True):
            report = inspect_runtime_configuration()

        joined = "\n".join(report.errors)
        self.assertIn("SUPABASE_URL", joined)
        self.assertIn("SCIPILOT_LLM_BASE_URL", joined)
        self.assertIn("XFYUN_KB_BASE_URL", joined)
        self.assertIn("PROBLEM_DECOMPOSITION_WS_URL", joined)
        self.assertIn("XF_AGENT_WS_PATH", joined)

    def test_local_runtime_can_use_explicit_development_http_endpoints(self):
        env = {
            "SCIPILOT_ENV": "local",
            "LOCAL_DEMO_MODE": "true",
            "LOCAL_DEMO_PASSWORD": "local-only-password",
            "CORS_ORIGINS": "http://localhost:5173",
            "SCIPILOT_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "XFYUN_KB_BASE_URL": "http://127.0.0.1:8081",
            "PROBLEM_DECOMPOSITION_WS_URL": "ws://127.0.0.1:8082/chat",
            "XF_AGENT_WS_PATH": "ws://127.0.0.1:8083/chat",
        }
        with patch.dict(os.environ, env, clear=True):
            report = inspect_runtime_configuration()

        self.assertFalse(
            any("HTTPS URL in production" in item for item in report.errors)
        )
        self.assertFalse(any("WSS URL in production" in item for item in report.errors))

    def test_high_cost_routes_have_separate_rate_limit_rules(self):
        self.assertEqual(_rule_for("/api/v1/auth/login", "POST").name, "auth")
        self.assertEqual(_rule_for("/api/v1/papers/upload-async", "POST").name, "upload")
        self.assertEqual(_rule_for("/api/v1/knowledge/answer", "POST").name, "knowledge")
        self.assertEqual(_rule_for("/api/v1/chat", "POST").name, "model")
        self.assertIsNone(_rule_for("/api/v1/health", "GET"))

    def test_rate_limit_key_hashes_bearer_token(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/chat",
                "headers": [(b"authorization", b"Bearer private-token")],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
                "query_string": b"",
            }
        )
        key = _client_key(request)
        self.assertTrue(key.startswith("token:"))
        self.assertNotIn("private-token", key)


class RateLimitMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_request_is_rejected_when_limit_is_one(self):
        middleware = ApiRateLimitMiddleware(lambda scope, receive, send: None)

        def request() -> Request:
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/v1/auth/login",
                    "headers": [],
                    "client": ("127.0.0.1", 12345),
                    "scheme": "http",
                    "server": ("testserver", 80),
                    "query_string": b"",
                }
            )

        async def call_next(_: Request):
            return JSONResponse({"ok": True})

        with patch.dict(
            os.environ,
            {"RATE_LIMIT_ENABLED": "true", "RATE_LIMIT_AUTH_REQUESTS": "1"},
        ):
            first = await middleware.dispatch(request(), call_next)
            second = await middleware.dispatch(request(), call_next)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)


if __name__ == "__main__":
    unittest.main()
