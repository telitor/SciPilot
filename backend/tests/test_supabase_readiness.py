import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import routes
from services import supabase_service as service


class SupabaseReadinessTests(unittest.TestCase):
    def setUp(self):
        service.reset_supabase_readiness_cache()

    def tearDown(self):
        service.reset_supabase_readiness_cache()

    def test_bounded_probe_checks_auth_and_core_table_then_caches_success(self):
        http_context = MagicMock()
        http_client = MagicMock()
        http_context.__enter__.return_value = http_client
        client = MagicMock()
        environment = {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_SECRET_KEY": "service-secret",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(service.httpx, "Client", return_value=http_context) as http,
            patch.object(service, "create_client", return_value=client) as create,
        ):
            service.check_supabase_readiness(timeout_seconds=1, cache_seconds=5)
            service.check_supabase_readiness(timeout_seconds=1, cache_seconds=5)

        http.assert_called_once()
        self.assertFalse(http.call_args.kwargs["follow_redirects"])
        self.assertIs(create.call_args.kwargs["options"].httpx_client, http_client)
        client.auth.admin.list_users.assert_called_once_with(page=1, per_page=1)
        client.table.assert_called_once_with("research_projects")

    def test_probe_rejects_plaintext_and_never_exposes_upstream_details(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "http://project.supabase.internal",
                    "SUPABASE_SECRET_KEY": "service-secret",
                },
                clear=True,
            ),
            patch.object(service, "create_client") as create,
            self.assertRaises(service.SupabaseReadinessError) as caught,
        ):
            service.check_supabase_readiness(cache_seconds=0)
        create.assert_not_called()
        self.assertEqual(str(caught.exception), "Core data service is not ready")
        self.assertNotIn("service-secret", str(caught.exception))

        service.reset_supabase_readiness_cache()
        with (
            patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://project.supabase.co",
                    "SUPABASE_SECRET_KEY": "service-secret",
                },
                clear=True,
            ),
            patch.object(service.httpx, "Client") as http,
            patch.object(
                service,
                "create_client",
                side_effect=RuntimeError("upstream echoed service-secret"),
            ),
            self.assertRaises(service.SupabaseReadinessError) as failed,
        ):
            http.return_value.__enter__.return_value = MagicMock()
            service.check_supabase_readiness(cache_seconds=0)
        self.assertEqual(str(failed.exception), "Core data service is not ready")
        self.assertNotIn("service-secret", str(failed.exception))

    def test_api_contract_returns_safe_503_or_bounded_success_payload(self):
        with (
            patch.object(
                routes,
                "check_supabase_readiness",
                side_effect=service.SupabaseReadinessError("private upstream detail"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            routes.readiness()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("private", str(caught.exception.detail))

        with patch.object(routes, "check_supabase_readiness"):
            result = routes.readiness()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["dependencies"], {"supabase": "ok"})


if __name__ == "__main__":
    unittest.main()
