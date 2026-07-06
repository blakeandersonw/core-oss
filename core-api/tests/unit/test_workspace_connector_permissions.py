import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBiYXNlIiwicmVmIjoidGVzdCIsInJvbGUiOiJhbm9uIn0."
    "testsignature",
)


@pytest.mark.asyncio
async def test_workspace_connector_reconnect_requires_admin_before_composio(monkeypatch):
    from api.routers import workspace_access

    async def deny_admin(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Workspace admin access required")

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Composio side effect should not run before admin check")

    monkeypatch.setattr(workspace_access, "require_workspace_admin_access", deny_admin)
    monkeypatch.setattr(workspace_access, "refresh_connected_account", fail_if_called)
    monkeypatch.setattr(workspace_access, "create_connect_link", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        await workspace_access.reconnect_workspace_connector_endpoint(
            "workspace-1",
            "connector-1",
            type("Request", (), {"headers": {}})(),
            user_jwt="jwt",
            user_id="user-1",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_workspace_connector_delete_requires_admin_before_revoke(monkeypatch):
    from api.routers import workspace_access

    async def deny_admin(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Workspace admin access required")

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Composio revoke should not run before admin check")

    monkeypatch.setattr(workspace_access, "require_workspace_admin_access", deny_admin)
    monkeypatch.setattr(workspace_access, "revoke_connected_account", fail_if_called)

    with pytest.raises(HTTPException) as exc:
        await workspace_access.delete_workspace_connector_endpoint(
            "workspace-1",
            "connector-1",
            user_jwt="jwt",
        )

    assert exc.value.status_code == 403
