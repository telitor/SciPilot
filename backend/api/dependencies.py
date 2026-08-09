import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, Header, HTTPException

from services.supabase_service import get_supabase_client

logger = logging.getLogger(__name__)

LOCAL_DEMO_USER_ID = "00000000-0000-4000-8000-000000000001"


def local_demo_mode_enabled() -> bool:
    """Enable demo auth only when both flags explicitly select a local runtime."""

    requested = os.getenv("LOCAL_DEMO_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    runtime = os.getenv("SCIPILOT_ENV", "production").strip().lower()
    return requested and runtime == "local"


def local_demo_user() -> SimpleNamespace:
    email = os.getenv("LOCAL_DEMO_EMAIL", "demo@scipilot.local").strip().lower()
    username = os.getenv("LOCAL_DEMO_USERNAME", "本地验收用户").strip()
    return SimpleNamespace(
        id=LOCAL_DEMO_USER_ID,
        email=email,
        user_metadata={"username": username, "role": "user"},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def local_demo_login(email: str, password: str) -> SimpleNamespace | None:
    """Authenticate the isolated demo account without weakening production auth."""

    if not local_demo_mode_enabled():
        return None
    expected_email = os.getenv(
        "LOCAL_DEMO_EMAIL", "demo@scipilot.local"
    ).strip().lower()
    expected_password = os.getenv("LOCAL_DEMO_PASSWORD", "")
    if not expected_password:
        return None
    if email.strip().lower() != expected_email or password != expected_password:
        return None
    return local_demo_user()


def local_demo_token() -> str | None:
    """Derive a bearer value from the uncommitted demo password."""

    if not local_demo_mode_enabled():
        return None
    email = os.getenv("LOCAL_DEMO_EMAIL", "demo@scipilot.local").strip().lower()
    password = os.getenv("LOCAL_DEMO_PASSWORD", "")
    if not password:
        return None
    digest = hashlib.sha256(
        f"SciPilot local demo\0{email}\0{password}".encode("utf-8")
    ).hexdigest()
    return f"local-demo-{digest}"


def database():
    return get_supabase_client()


def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="登录凭证无效")

    expected_demo_token = local_demo_token()
    if expected_demo_token and hmac.compare_digest(token, expected_demo_token):
        return local_demo_user()

    try:
        response = database().auth.get_user(token)
        user = response.user
    except Exception as exc:
        logger.info("Supabase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from None

    if not user:
        raise HTTPException(status_code=401, detail="登录凭证无效")
    return user


def get_current_admin(user=Depends(get_current_user)):
    """Authorize administrators from the server-managed profile role."""

    profile = get_or_create_profile(user)
    if profile.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def format_user(user: Any, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = getattr(user, "user_metadata", None) or {}
    profile = profile or {}
    email = getattr(user, "email", None) or profile.get("email") or ""
    username = (
        profile.get("username")
        or metadata.get("username")
        or metadata.get("name")
        or (email.split("@", 1)[0] if email else "研究者")
    )
    return {
        "id": str(getattr(user, "id", "")),
        "email": email,
        "username": username,
        "avatar_url": profile.get("avatar_url"),
        "bio": profile.get("bio"),
        "preferences": profile.get("preferences") or {},
        "role": profile.get("role") or metadata.get("role") or "user",
        "created_at": profile.get("created_at")
        or getattr(user, "created_at", None),
    }


def get_or_create_profile(user: Any) -> dict[str, Any]:
    user_id = str(user.id)
    if local_demo_mode_enabled() and user_id == LOCAL_DEMO_USER_ID:
        formatted = format_user(user)
        return {
            "id": formatted["id"],
            "email": formatted["email"],
            "username": formatted["username"],
            "avatar_url": None,
            "bio": "仅用于本机验收，不连接 Supabase。",
            "preferences": {},
            "role": "user",
            "created_at": formatted["created_at"],
        }
    try:
        result = (
            database()
            .table("profiles")
            .select(
                "id,email,username,avatar_url,bio,preferences,role,created_at,updated_at"
            )
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        # Backward compatibility while the original 001-005 schema is still
        # online and migration 006 has not been applied yet.
        result = (
            database()
            .table("profiles")
            .select("id,username,avatar_url,role,created_at")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    if result.data:
        return result.data[0]

    metadata = getattr(user, "user_metadata", None) or {}
    email = getattr(user, "email", None) or ""
    payload = {
        "id": user_id,
        "email": email,
        "username": metadata.get("username")
        or (email.split("@", 1)[0] if email else "研究者"),
        "role": "user",
    }
    try:
        created = database().table("profiles").upsert(payload).execute()
    except Exception:
        legacy_payload = {
            "id": user_id,
            "username": payload["username"],
            "role": "user",
        }
        created = database().table("profiles").upsert(legacy_payload).execute()
    return created.data[0] if created.data else payload


def require_owned_row(
    table: str,
    row_id: str,
    user_id: str,
    *,
    owner_column: str = "user_id",
    columns: str = "*",
) -> dict[str, Any]:
    result = (
        database()
        .table(table)
        .select(columns)
        .eq("id", row_id)
        .eq(owner_column, user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="记录不存在")
    return result.data[0]


def record_activity(
    user_id: str,
    module: str,
    action: str,
    target: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    project_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record activity without making the primary operation fail."""

    if local_demo_mode_enabled() and user_id == LOCAL_DEMO_USER_ID:
        return

    try:
        database().table("activities").insert(
            {
                "user_id": user_id,
                "module": module,
                "action": action,
                "target": target[:500],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "project_id": project_id,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception as exc:
        logger.warning("Unable to record activity: %s", exc)
