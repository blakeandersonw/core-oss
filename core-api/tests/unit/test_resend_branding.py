"""Branding tests for backend transactional emails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.config import Settings
from lib import resend_client


def test_resend_from_domain_uses_starterstack_sender_name():
    settings = Settings(resend_from_domain="example.com", _env_file=None)

    assert settings.resend_from_address == "StarterStack <invites@example.com>"


def test_explicit_resend_from_email_still_overrides_sender_name():
    settings = Settings(
        resend_from_domain="example.com",
        resend_from_email="Custom <mail@example.com>",
        _env_file=None,
    )

    assert settings.resend_from_address == "Custom <mail@example.com>"


def test_notification_email_templates_use_starterstack_brand(monkeypatch):
    monkeypatch.setattr(resend_client.settings, "frontend_url", "https://app.example.com")

    html = resend_client._build_notification_html(
        recipient_name="Pat",
        title="Task updated",
        body="A task changed.",
        action_url="https://app.example.com/workspace/ws-1",
        actor_name=None,
        category=None,
    )
    text = resend_client._build_notification_text(
        title="Task updated",
        body="A task changed.",
        action_url="https://app.example.com/workspace/ws-1",
        actor_name=None,
        category=None,
    )

    combined = f"{html}\n{text}"
    assert "Open in StarterStack" in combined
    assert "Sent because StarterStack triggered a notification notification." in combined
    assert "Open in Core" not in combined
    assert "Core" not in combined


def test_digest_email_templates_use_starterstack_brand():
    grouped_items = [
        {
            "workspace_name": "Example Team",
            "items": [
                {
                    "title": "Task updated",
                    "body": "A task changed.",
                    "action_url": "https://app.example.com/workspace/ws-1",
                }
            ],
        }
    ]

    html = resend_client._build_digest_html(
        recipient_name="Pat",
        grouped_items=grouped_items,
        manage_preferences_url="https://app.example.com/settings/notifications",
    )
    text = resend_client._build_digest_text(
        grouped_items=grouped_items,
        manage_preferences_url="https://app.example.com/settings/notifications",
    )

    combined = f"{html}\n{text}"
    assert "StarterStack notification digest" in combined
    assert "Core notification digest" not in combined
    assert "Core" not in combined


@pytest.mark.asyncio
async def test_digest_email_subject_uses_starterstack_brand(monkeypatch):
    sent_payload = {}

    async def fake_send_email(**kwargs):
        sent_payload.update(kwargs)
        return "resend-id"

    monkeypatch.setattr(resend_client, "_send_email", fake_send_email)

    result = await resend_client.send_digest_email(
        recipient_email="pat@example.com",
        recipient_name="Pat",
        grouped_items=[
            {
                "workspace_name": "Example Team",
                "items": [
                    {
                        "title": "Task updated",
                        "body": "A task changed.",
                        "action_url": "https://app.example.com/workspace/ws-1",
                    }
                ],
            }
        ],
        manage_preferences_url="https://app.example.com/settings/notifications",
    )

    assert result == "resend-id"
    assert sent_payload["subject"] == "StarterStack notification digest"


@pytest.mark.asyncio
async def test_notification_row_email_uses_starterstack_fallback_title(monkeypatch):
    from api.services.notifications import email as notification_email_service

    monkeypatch.setattr(notification_email_service.settings, "notification_emails_enabled", True)
    monkeypatch.setattr(notification_email_service.settings, "frontend_url", "https://app.example.com")
    monkeypatch.setattr(
        notification_email_service,
        "should_notify",
        AsyncMock(return_value=True),
    )

    send_notification_email = AsyncMock(return_value="resend-id")
    monkeypatch.setattr(
        notification_email_service,
        "send_notification_email",
        send_notification_email,
    )

    query = MagicMock()
    for method_name in ("select", "eq", "maybe_single", "update"):
        getattr(query, method_name).return_value = query
    query.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(data={"id": "user-1", "email": "pat@example.com", "name": "Pat"}),
            SimpleNamespace(data=[{"id": "notif-1"}]),
        ]
    )

    client = MagicMock()
    client.table.return_value = query
    monkeypatch.setattr(
        notification_email_service,
        "get_async_service_role_client",
        AsyncMock(return_value=client),
    )

    await notification_email_service._send_notification_row_email(
        {
            "id": "notif-1",
            "user_id": "user-1",
            "workspace_id": "ws-1",
            "resource_type": "workspace_invitation",
            "data": {},
        },
        "workspace_invite",
    )

    send_notification_email.assert_awaited_once()
    assert send_notification_email.await_args.kwargs["title"] == "StarterStack notification"
