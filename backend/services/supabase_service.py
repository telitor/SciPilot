"""Supabase client factories used by the FastAPI backend."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class SupabaseConfigurationError(RuntimeError):
    """Raised when required Supabase environment variables are missing."""


def _required_env(name: str, *aliases: str) -> str:
    for candidate in (name, *aliases):
        value = os.getenv(candidate, "").strip()
        if value:
            return value
    if not value:
        raise SupabaseConfigurationError(
            f"Missing {name}. Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the trusted service-role client.

    This client may bypass RLS and must only be used by the backend after it has
    authenticated the caller and checked row ownership.
    """

    return create_client(
        _required_env("SUPABASE_URL"),
        _required_env("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )


def get_supabase_auth_client() -> Client:
    """Return an isolated anon-key client for one sign-up/sign-in request."""

    return create_client(
        _required_env("SUPABASE_URL"),
        _required_env("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY"),
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
