import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from api import routes
from api.schemas import AdminRoleChangeRequest
from scripts import bootstrap_admin


class AdminRoleGovernanceTests(unittest.TestCase):
    def test_admin_user_directory_combines_auth_and_profile_data(self):
        auth_user = SimpleNamespace(
            id="f82d77ee-4b97-4311-96bc-973eb6dc7d60",
            email="admin@example.com",
            user_metadata={"username": "metadata-name"},
            email_confirmed_at="2026-08-01T00:00:00Z",
            confirmed_at=None,
            last_sign_in_at=None,
            created_at="2026-07-01T00:00:00Z",
        )
        query = MagicMock()
        query.select.return_value = query
        query.in_.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[
                {
                    "id": str(auth_user.id),
                    "username": "profile-name",
                    "role": "admin",
                }
            ]
        )
        service = MagicMock()
        service.auth.admin.list_users.return_value = [auth_user]
        service.table.return_value = query

        with patch.object(routes, "database", return_value=service):
            result = routes.list_admin_users(user=SimpleNamespace(id="admin-id"))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["username"], "profile-name")
        self.assertEqual(result["items"][0]["role"], "admin")

    def test_last_administrator_cannot_be_demoted(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.side_effect = [
            SimpleNamespace(
                data=[
                    {
                        "id": "f82d77ee-4b97-4311-96bc-973eb6dc7d60",
                        "username": "admin",
                        "role": "admin",
                    }
                ]
            ),
            SimpleNamespace(
                data=[{"id": "f82d77ee-4b97-4311-96bc-973eb6dc7d60"}]
            ),
        ]
        service = MagicMock()
        service.table.return_value = query

        with (
            patch.object(routes, "database", return_value=service),
            self.assertRaises(HTTPException) as raised,
        ):
            routes.update_admin_user_role(
                "f82d77ee-4b97-4311-96bc-973eb6dc7d60",
                AdminRoleChangeRequest(role="user", reason="职责调整"),
                user=SimpleNamespace(id="f82d77ee-4b97-4311-96bc-973eb6dc7d60"),
            )

        self.assertEqual(raised.exception.status_code, 409)
        query.update.assert_not_called()

    def test_role_change_writes_audit_record(self):
        profile_query = MagicMock()
        profile_query.select.return_value = profile_query
        profile_query.eq.return_value = profile_query
        profile_query.limit.return_value = profile_query
        profile_query.update.return_value = profile_query
        profile_query.execute.side_effect = [
            SimpleNamespace(
                data=[
                    {
                        "id": "10a343d9-4861-4e3d-9d34-faacf22b6fd4",
                        "username": "researcher",
                        "role": "user",
                    }
                ]
            ),
            SimpleNamespace(
                data=[
                    {
                        "id": "10a343d9-4861-4e3d-9d34-faacf22b6fd4",
                        "username": "researcher",
                        "role": "admin",
                    }
                ]
            ),
        ]
        audit_query = MagicMock()
        audit_query.insert.return_value = audit_query
        audit_query.execute.return_value = SimpleNamespace(data=[{"id": "audit-1"}])
        service = MagicMock()
        service.table.side_effect = lambda name: (
            audit_query if name == "admin_role_audits" else profile_query
        )
        service.auth.admin.get_user_by_id.return_value = SimpleNamespace(
            user=SimpleNamespace(
                id="10a343d9-4861-4e3d-9d34-faacf22b6fd4",
                email="researcher@example.com",
                user_metadata={},
                email_confirmed_at=None,
                confirmed_at=None,
                last_sign_in_at=None,
                created_at=None,
            )
        )

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "record_activity"),
        ):
            result = routes.update_admin_user_role(
                "10a343d9-4861-4e3d-9d34-faacf22b6fd4",
                AdminRoleChangeRequest(role="admin", reason="负责质量评测"),
                user=SimpleNamespace(id="f82d77ee-4b97-4311-96bc-973eb6dc7d60"),
            )

        audit_payload = audit_query.insert.call_args.args[0]
        self.assertEqual(result["role"], "admin")
        self.assertEqual(audit_payload["previous_role"], "user")
        self.assertEqual(audit_payload["new_role"], "admin")
        self.assertEqual(audit_payload["reason"], "负责质量评测")
        self.assertNotIn("email", audit_payload)

    def test_bootstrap_requires_explicit_confirmation(self):
        with self.assertRaises(RuntimeError):
            bootstrap_admin.bootstrap_admin("admin@example.com", confirmed=False)

    def test_bootstrap_refuses_when_an_admin_already_exists(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{"id": "admin-id"}])
        service = MagicMock()
        service.table.return_value = query
        with (
            patch.object(bootstrap_admin, "get_supabase_client", return_value=service),
            self.assertRaises(RuntimeError) as raised,
        ):
            bootstrap_admin.bootstrap_admin("admin@example.com", confirmed=True)
        self.assertIn("already exists", str(raised.exception))
        service.auth.admin.list_users.assert_not_called()


if __name__ == "__main__":
    unittest.main()
