import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from supabase_auth.errors import AuthApiError, AuthUnknownError

from api import routes
from api.schemas import LoginRequest


class AuthLoginTests(unittest.TestCase):
    def _login_with_error(self, error: Exception) -> HTTPException:
        auth_client = MagicMock()
        auth_client.auth.sign_in_with_password.side_effect = error
        with (
            patch.object(routes, "local_demo_mode_enabled", return_value=False),
            patch.object(routes, "get_supabase_auth_client", return_value=auth_client),
            self.assertRaises(HTTPException) as raised,
        ):
            routes.login(LoginRequest(email="user@example.com", password="Password123"))
        return raised.exception

    def test_invalid_credentials_remain_unauthorized(self):
        error = self._login_with_error(
            AuthApiError("Invalid login credentials", 400, "invalid_credentials")
        )
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.detail, "邮箱或密码不正确")

    def test_email_not_confirmed_has_specific_message(self):
        error = self._login_with_error(
            AuthApiError("Email not confirmed", 400, "email_not_confirmed")
        )
        self.assertEqual(error.status_code, 403)
        self.assertEqual(error.detail, "请先完成邮箱验证后再登录")

    def test_connection_failure_is_not_reported_as_bad_password(self):
        error = self._login_with_error(
            AuthUnknownError("network error", OSError("DNS lookup failed"))
        )
        self.assertEqual(error.status_code, 503)
        self.assertIn("Supabase 登录服务暂不可用", error.detail)


if __name__ == "__main__":
    unittest.main()
