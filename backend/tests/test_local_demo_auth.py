import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import routes
from api.dependencies import get_current_user, local_demo_token
from api.schemas import LoginRequest


class LocalDemoAuthTests(unittest.TestCase):
    ENV = {
        "SCIPILOT_ENV": "local",
        "LOCAL_DEMO_MODE": "true",
        "LOCAL_DEMO_EMAIL": "demo@scipilot.local",
        "LOCAL_DEMO_PASSWORD": "local-only-password",
        "LOCAL_DEMO_USERNAME": "验收用户",
    }

    def test_demo_login_and_bearer_round_trip_without_supabase(self):
        with patch.dict(os.environ, self.ENV, clear=False):
            response = routes.login(
                LoginRequest(
                    email="DEMO@SCIPILOT.LOCAL",
                    password="local-only-password",
                )
            )
            user = get_current_user(f"Bearer {response['token']}")

        self.assertTrue(response["token"].startswith("local-demo-"))
        self.assertEqual(user.email, "demo@scipilot.local")
        self.assertEqual(response["user"]["username"], "验收用户")

    def test_demo_login_rejects_wrong_password(self):
        with (
            patch.dict(os.environ, self.ENV, clear=False),
            self.assertRaises(HTTPException) as error,
        ):
            routes.login(
                LoginRequest(
                    email="demo@scipilot.local",
                    password="wrong",
                )
            )

        self.assertEqual(error.exception.status_code, 401)

    def test_demo_token_is_disabled_by_default(self):
        env = dict(self.ENV)
        env["LOCAL_DEMO_MODE"] = "false"
        with patch.dict(os.environ, self.ENV, clear=False):
            demo_token = local_demo_token()
        self.assertIsNotNone(demo_token)
        with (
            patch.dict(os.environ, env, clear=False),
            patch("api.dependencies.database", side_effect=RuntimeError("no db")),
            self.assertRaises(HTTPException) as error,
        ):
            get_current_user(f"Bearer {demo_token}")

        self.assertEqual(error.exception.status_code, 401)

    def test_demo_mode_is_hard_disabled_outside_local_runtime(self):
        env = dict(self.ENV)
        env["SCIPILOT_ENV"] = "production"
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(routes, "get_supabase_auth_client") as supabase_auth,
        ):
            supabase_auth.return_value.auth.sign_in_with_password.side_effect = (
                RuntimeError("not configured")
            )
            with self.assertRaises(HTTPException) as error:
                routes.login(
                    LoginRequest(
                        email="demo@scipilot.local",
                        password="local-only-password",
                    )
                )

        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
