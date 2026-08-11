import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from supabase_auth.errors import AuthApiError, AuthUnknownError

from api import routes
from api.schemas import ForgotPasswordRequest, LoginRequest, ResetPasswordRequest


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


    def test_forgot_password_uses_configured_redirect_and_generic_response(self):
        auth_client = MagicMock()
        with (
            patch.object(routes, "get_supabase_auth_client", return_value=auth_client),
            patch.dict(
                "os.environ",
                {"PASSWORD_RESET_REDIRECT_URL": "http://localhost:5173/reset-password"},
            ),
        ):
            result = routes.forgot_password(
                ForgotPasswordRequest(email="USER@example.com")
            )

        auth_client.auth.reset_password_for_email.assert_called_once_with(
            "user@example.com",
            options={"redirect_to": "http://localhost:5173/reset-password"},
        )
        self.assertNotIn("user@example.com", result["message"])

    def test_forgot_password_does_not_reveal_unknown_email(self):
        auth_client = MagicMock()
        auth_client.auth.reset_password_for_email.side_effect = RuntimeError("unknown user")
        with patch.object(routes, "get_supabase_auth_client", return_value=auth_client):
            result = routes.forgot_password(
                ForgotPasswordRequest(email="missing@example.com")
            )

        self.assertIn("如果该邮箱已注册", result["message"])

    def test_reset_password_updates_only_authenticated_user(self):
        service = MagicMock()
        service.auth.admin.update_user_by_id.return_value = SimpleNamespace(
            user=SimpleNamespace(id="user-1")
        )
        with patch.object(routes, "database", return_value=service):
            result = routes.reset_password(
                ResetPasswordRequest(password="NewPassword123"),
                user=SimpleNamespace(id="user-1"),
            )

        service.auth.admin.update_user_by_id.assert_called_once_with(
            "user-1", {"password": "NewPassword123"}
        )
        self.assertIn("密码已更新", result["message"])


if __name__ == "__main__":
    unittest.main()
