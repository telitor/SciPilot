import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import routes
from api.schemas import RegisterRequest


def _user():
    return SimpleNamespace(
        id="17052979-bb53-4a63-915f-82f6b7b54e1c",
        email="new.user@example.net",
        user_metadata={"username": "New User", "role": "user"},
        created_at="2026-07-29T00:00:00Z",
    )


def _service_client():
    service = MagicMock()
    service.table.return_value.upsert.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": str(_user().id)}])
    )
    return service


class AutoConfirmRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.payload = RegisterRequest(
            email="New.User@example.net",
            password="StrongPassword2026!",
            username="New User",
        )

    def test_enabled_mode_admin_creates_confirmed_user_and_signs_in(self):
        user = _user()
        service = _service_client()
        service.auth.admin.create_user.return_value = SimpleNamespace(user=user)
        auth_client = MagicMock()
        auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(
            user=user,
            session=SimpleNamespace(access_token="user-access-token"),
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "true"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=auth_client,
            ),
        ):
            result = routes.register(self.payload)

        create_payload = service.auth.admin.create_user.call_args.args[0]
        self.assertEqual(create_payload["email"], "new.user@example.net")
        self.assertTrue(create_payload["email_confirm"])
        self.assertEqual(
            create_payload["user_metadata"],
            {"username": "New User", "role": "user"},
        )
        auth_client.auth.sign_in_with_password.assert_called_once_with(
            {
                "email": "new.user@example.net",
                "password": "StrongPassword2026!",
            }
        )
        self.assertEqual(result["token"], "user-access-token")
        self.assertFalse(result["requires_email_confirmation"])

    def test_disabled_mode_keeps_email_confirmation_signup(self):
        user = _user()
        service = _service_client()
        auth_client = MagicMock()
        auth_client.auth.sign_up.return_value = SimpleNamespace(
            user=user,
            session=None,
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "false"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=auth_client,
            ),
        ):
            result = routes.register(self.payload)

        service.auth.admin.create_user.assert_not_called()
        auth_client.auth.sign_up.assert_called_once()
        self.assertIsNone(result["token"])
        self.assertTrue(result["requires_email_confirmation"])

    def test_duplicate_email_returns_conflict_without_exposing_service_error(self):
        service = _service_client()
        service.auth.admin.create_user.side_effect = RuntimeError(
            "A user with this email address has already been registered"
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "true"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=MagicMock(),
            ),
            self.assertRaises(HTTPException) as error,
        ):
            routes.register(self.payload)

        self.assertEqual(error.exception.status_code, 409)
        self.assertNotIn("service", str(error.exception.detail).lower())

    def test_provider_password_rejection_returns_safe_bad_request(self):
        service = _service_client()
        service.auth.admin.create_user.side_effect = RuntimeError(
            "Password does not meet requirements"
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "true"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=MagicMock(),
            ),
            self.assertRaises(HTTPException) as error,
        ):
            routes.register(self.payload)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(
            error.exception.detail,
            "密码不符合 Supabase 的安全要求",
        )

    def test_failed_automatic_sign_in_removes_new_account(self):
        user = _user()
        service = _service_client()
        service.auth.admin.create_user.return_value = SimpleNamespace(user=user)
        auth_client = MagicMock()
        auth_client.auth.sign_in_with_password.side_effect = RuntimeError(
            "temporary auth failure"
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "true"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=auth_client,
            ),
            self.assertRaises(HTTPException) as error,
        ):
            routes.register(self.payload)

        self.assertEqual(error.exception.status_code, 502)
        service.auth.admin.delete_user.assert_called_once_with(str(user.id))

    def test_missing_automatic_session_removes_new_account(self):
        user = _user()
        service = _service_client()
        service.auth.admin.create_user.return_value = SimpleNamespace(user=user)
        auth_client = MagicMock()
        auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(
            user=user,
            session=None,
        )

        with (
            patch.dict(os.environ, {"AUTH_AUTO_CONFIRM_EMAIL": "true"}),
            patch.object(routes, "database", return_value=service),
            patch.object(
                routes,
                "get_supabase_auth_client",
                return_value=auth_client,
            ),
            self.assertRaises(HTTPException) as error,
        ):
            routes.register(self.payload)

        self.assertEqual(error.exception.status_code, 502)
        service.auth.admin.delete_user.assert_called_once_with(str(user.id))


if __name__ == "__main__":
    unittest.main()
