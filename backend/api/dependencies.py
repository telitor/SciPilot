import logging
from typing import Any

from fastapi import Header, HTTPException

from services.supabase_service import get_supabase_client

logger = logging.getLogger(__name__)


def database():
    return get_supabase_client()


def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="登录凭证无效")

    try:
        response = database().auth.get_user(token)
        user = response.user
    except Exception as exc:
        logger.info("Supabase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from None

    if not user:
        raise HTTPException(status_code=401, detail="登录凭证无效")
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
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record activity without making the primary operation fail."""

    try:
        database().table("activities").insert(
            {
                "user_id": user_id,
                "module": module,
                "action": action,
                "target": target[:500],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception as exc:
        logger.warning("Unable to record activity: %s", exc)
