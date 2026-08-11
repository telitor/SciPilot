"""Promote the first SciPilot administrator by exact email match."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from services.supabase_service import get_supabase_client


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote the first SciPilot admin without storing an email in code."
    )
    parser.add_argument("--email", required=True, help="Exact registered email")
    parser.add_argument(
        "--confirm-promote",
        action="store_true",
        help="Required explicit confirmation for the role change",
    )
    return parser.parse_args()


def bootstrap_admin(email: str, *, confirmed: bool) -> str:
    if not confirmed:
        raise RuntimeError("Refusing role change without --confirm-promote")
    normalized_email = email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid registered email is required")

    client = get_supabase_client()
    existing_admins = (
        client.table("profiles").select("id").eq("role", "admin").limit(2).execute().data
        or []
    )
    if existing_admins:
        raise RuntimeError("An administrator already exists; use the admin UI instead")

    users = client.auth.admin.list_users(page=1, per_page=1000)
    matches = [
        user
        for user in users
        if str(getattr(user, "email", "") or "").strip().lower() == normalized_email
    ]
    if len(matches) != 1:
        raise RuntimeError("Registered account not found or email is not unique")
    target = matches[0]
    user_id = str(target.id)
    profile_result = (
        client.table("profiles")
        .select("id,role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    profile = profile_result.data[0] if profile_result.data else None
    if not profile:
        raise RuntimeError("The account exists in Auth but has no profile row")
    previous_role = str(profile.get("role") or "user")
    if previous_role == "admin":
        return user_id

    updated = (
        client.table("profiles")
        .update({"role": "admin"})
        .eq("id", user_id)
        .execute()
    )
    if not updated.data:
        raise RuntimeError("Administrator role update failed")
    try:
        client.table("admin_role_audits").insert(
            {
                "target_user_id": user_id,
                "actor_user_id": None,
                "previous_role": previous_role,
                "new_role": "admin",
                "source": "bootstrap-script",
                "reason": "Initial administrator bootstrap",
            }
        ).execute()
    except Exception:
        client.table("profiles").update({"role": previous_role}).eq(
            "id", user_id
        ).execute()
        raise RuntimeError("Audit write failed; role change was rolled back") from None
    return user_id


def main() -> int:
    args = _parse_args()
    try:
        user_id = bootstrap_admin(args.email, confirmed=args.confirm_promote)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    print(f"[OK] Initial administrator configured for user id {user_id}")
    print("[OK] The email was used for lookup only and was not stored in the audit table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
