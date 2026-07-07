"""Production signup access policy."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status

from api.config import settings
from api.services.workspaces.invitations import has_valid_pending_invitation_for_email
from api.super_admin import is_super_admin_email

SIGNUP_INVITE_ONLY_ERROR = (
    "Signup is invite-only. Use a starterstack.ai email or ask for a workspace invitation."
)


def normalize_signup_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def signup_restriction_enabled() -> bool:
    return settings.api_env.strip().lower() == "production"


def get_signup_allowed_domains() -> set[str]:
    return {
        domain.strip().lower().lstrip("@")
        for domain in settings.signup_allowed_domains.split(",")
        if domain.strip()
    }


def email_matches_allowed_signup_domain(email: Optional[str]) -> bool:
    normalized = normalize_signup_email(email)
    if "@" not in normalized:
        return False
    domain = normalized.rsplit("@", 1)[1]
    return domain in get_signup_allowed_domains()


async def get_signup_eligibility(email: str) -> dict[str, str | bool | None]:
    normalized = normalize_signup_email(email)
    if not normalized:
        return {"allowed": False, "reason": "invalid_email", "message": "Email is required"}

    if not signup_restriction_enabled():
        return {"allowed": True, "reason": "unrestricted", "message": None}

    if is_super_admin_email(normalized):
        return {"allowed": True, "reason": "super_admin", "message": None}

    if email_matches_allowed_signup_domain(normalized):
        return {"allowed": True, "reason": "allowed_domain", "message": None}

    if await has_valid_pending_invitation_for_email(normalized):
        return {"allowed": True, "reason": "pending_invitation", "message": None}

    return {"allowed": False, "reason": "invite_required", "message": SIGNUP_INVITE_ONLY_ERROR}


async def assert_signup_allowed_for_email(email: str) -> None:
    eligibility = await get_signup_eligibility(email)
    if eligibility["allowed"]:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=str(eligibility["message"] or SIGNUP_INVITE_ONLY_ERROR),
    )
