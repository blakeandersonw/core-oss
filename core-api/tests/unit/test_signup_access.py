import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

import pytest
from fastapi import HTTPException

from api.services import signup_access


@pytest.mark.asyncio
async def test_signup_unrestricted_outside_production(monkeypatch):
    monkeypatch.setattr(signup_access.settings, "api_env", "development")

    result = await signup_access.get_signup_eligibility("person@example.com")

    assert result["allowed"] is True
    assert result["reason"] == "unrestricted"


@pytest.mark.asyncio
async def test_signup_allows_configured_domain_in_production(monkeypatch):
    monkeypatch.setattr(signup_access.settings, "api_env", "production")
    monkeypatch.setattr(signup_access.settings, "signup_allowed_domains", "starterstack.ai")
    monkeypatch.setattr(signup_access.settings, "super_admin_emails", "")

    result = await signup_access.get_signup_eligibility("Founder@StarterStack.ai")

    assert result["allowed"] is True
    assert result["reason"] == "allowed_domain"


@pytest.mark.asyncio
async def test_signup_allows_super_admin_in_production(monkeypatch):
    monkeypatch.setattr(signup_access.settings, "api_env", "production")
    monkeypatch.setattr(signup_access.settings, "signup_allowed_domains", "starterstack.ai")
    monkeypatch.setattr(signup_access.settings, "super_admin_emails", "owner@example.com")

    result = await signup_access.get_signup_eligibility("OWNER@example.com")

    assert result["allowed"] is True
    assert result["reason"] == "super_admin"


@pytest.mark.asyncio
async def test_signup_allows_pending_invitation_in_production(monkeypatch):
    async def fake_has_invite(email: str) -> bool:
        return email == "invitee@example.com"

    monkeypatch.setattr(signup_access.settings, "api_env", "production")
    monkeypatch.setattr(signup_access.settings, "signup_allowed_domains", "starterstack.ai")
    monkeypatch.setattr(signup_access.settings, "super_admin_emails", "")
    monkeypatch.setattr(signup_access, "has_valid_pending_invitation_for_email", fake_has_invite)

    result = await signup_access.get_signup_eligibility("Invitee@example.com")

    assert result["allowed"] is True
    assert result["reason"] == "pending_invitation"


@pytest.mark.asyncio
async def test_signup_rejects_uninvited_external_email_in_production(monkeypatch):
    async def fake_has_invite(email: str) -> bool:
        return False

    monkeypatch.setattr(signup_access.settings, "api_env", "production")
    monkeypatch.setattr(signup_access.settings, "signup_allowed_domains", "starterstack.ai")
    monkeypatch.setattr(signup_access.settings, "super_admin_emails", "")
    monkeypatch.setattr(signup_access, "has_valid_pending_invitation_for_email", fake_has_invite)

    with pytest.raises(HTTPException) as exc_info:
        await signup_access.assert_signup_allowed_for_email("person@example.com")

    assert exc_info.value.status_code == 403
    assert "invite-only" in exc_info.value.detail
