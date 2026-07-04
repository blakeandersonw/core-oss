"""Helpers for global super-admin checks."""

from __future__ import annotations

from typing import Optional

from api.config import settings
from lib.supabase_client import get_async_service_role_client


def _normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def get_super_admin_emails() -> set[str]:
    return {
        _normalize_email(email)
        for email in settings.super_admin_emails.split(",")
        if _normalize_email(email)
    }


def is_super_admin_email(email: Optional[str]) -> bool:
    normalized = _normalize_email(email)
    return bool(normalized and normalized in get_super_admin_emails())


async def is_super_admin_user_id(user_id: str) -> bool:
    supabase = await get_async_service_role_client()
    result = await supabase.table("users")\
        .select("email")\
        .eq("id", user_id)\
        .maybe_single()\
        .execute()

    return is_super_admin_email((result.data or {}).get("email"))
