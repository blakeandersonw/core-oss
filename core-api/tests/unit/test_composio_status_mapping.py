import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBiYXNlIiwicmVmIjoidGVzdCIsInJvbGUiOiJhbm9uIn0."
    "testsignature",
)


def test_map_composio_status_uses_shared_vocabulary():
    from api.services.composio import map_composio_status

    assert map_composio_status("ACTIVE") == "connected"
    assert map_composio_status("INITIALIZING") == "pending"
    assert map_composio_status("INITIATED") == "pending"
    assert map_composio_status("EXPIRED") == "expired"
    assert map_composio_status("FAILED") == "error"
    assert map_composio_status("INACTIVE") == "disconnected"
    assert map_composio_status("unexpected") == "unknown"
    assert map_composio_status(None) == "unknown"


def test_extract_composio_account_health_fields_tolerantly():
    from api.services.composio import (
        extract_external_account_id,
        extract_granted_scopes,
        extract_status_reason,
    )

    account = {
        "id": "connected-account-id",
        "requested_scopes": ["repo", "read:user"],
        "requested_user_scopes": "user:email, workflow",
        "status_reason": "Token revoked",
        "state": {
            "val": {
                "account_id": "provider-account-id",
                "requested_scopes": ["repo", "admin:repo_hook"],
            }
        },
    }

    assert extract_external_account_id(account) == "provider-account-id"
    assert extract_status_reason(account) == "Token revoked"
    assert extract_granted_scopes(account) == [
        "repo",
        "read:user",
        "user:email",
        "workflow",
        "admin:repo_hook",
    ]


def test_connection_health_payloads_preserve_is_active_invariant():
    from api.services.connections.hardening import (
        ConnectionHealth,
        ext_connection_update_payload,
        workspace_connector_update_payload,
    )

    failed = ConnectionHealth(
        status="expired",
        last_verified_at="2026-07-05T00:00:00+00:00",
        error_reason="OAuth token expired",
        scopes=["repo"],
        external_account_id="provider-account-id",
    )

    ext_payload = ext_connection_update_payload(failed)
    assert ext_payload["verification_status"] == "expired"
    assert ext_payload["is_active"] is False
    assert ext_payload["error_reason"] == "OAuth token expired"
    assert "external_account_id" not in ext_payload

    workspace_payload = workspace_connector_update_payload(failed)
    assert workspace_payload["status"] == "expired"
    assert "is_active" not in workspace_payload
    assert "external_account_id" not in workspace_payload


def test_legacy_connection_without_refresh_token_surfaces_expiry():
    from api.services.connections.hardening import health_from_legacy_ext_connection

    health = health_from_legacy_ext_connection({
        "is_active": True,
        "provider": "google",
        "verification_status": "unknown",
        "token_expires_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "refresh_token": None,
        "scopes": ["gmail.readonly"],
    })

    assert health.status == "expired"
    assert "no refresh token" in (health.error_reason or "")


def test_legacy_connection_retryable_failure_stays_quiet_before_retry_cap(monkeypatch):
    from api.services.connections import hardening

    monkeypatch.setattr(hardening, "get_failed_sync_quarantine_reason", lambda **_kwargs: None)

    health = hardening.health_from_legacy_ext_connection({
        "is_active": True,
        "provider": "google",
        "verification_status": "unknown",
        "failed_attempts": 1,
        "refresh_token": "refresh-token",
    })

    assert health.status == "connected"
    assert health.error_reason is None
