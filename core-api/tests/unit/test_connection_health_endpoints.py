import os

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJIUzI1NiIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiJ9."
    "testsignature",
)


class FakeQuery:
    def __init__(self, table_name, client):
        self.table_name = table_name
        self.client = client
        self._operation = None
        self._payload = None
        self._filters = []
        self._limit = None

    def select(self, *_args, **_kwargs):
        self._operation = "select"
        return self

    def update(self, payload):
        self._operation = "update"
        self._payload = payload
        return self

    def upsert(self, payload, **kwargs):
        self._operation = "upsert"
        self._payload = payload
        self.client.upserts.append({
            "table": self.table_name,
            "payload": payload,
            "kwargs": kwargs,
        })
        return self

    def insert(self, payload):
        self._operation = "insert"
        self._payload = payload
        return self

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def limit(self, value):
        self._limit = value
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._operation == "update":
            self.client.updates.append({
                "table": self.table_name,
                "payload": self._payload,
                "filters": list(self._filters),
            })
            return type("Result", (), {"data": [self._payload]})()
        if self._operation == "upsert":
            return type("Result", (), {"data": [self._payload]})()
        rows = list(self.client.rows.get(self.table_name, []))
        for key, value in self._filters:
            rows = [row for row in rows if row.get(key) == value]
        if self._limit is not None:
            rows = rows[:self._limit]
        if self._operation == "insert":
            self.client.inserts.append({
                "table": self.table_name,
                "payload": self._payload,
            })
            rows = [self._payload]
        if len(rows) <= 1:
            return type("Result", (), {"data": rows[0] if rows else None})()
        return type("Result", (), {"data": rows})()


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.updates = []
        self.upserts = []
        self.inserts = []

    def table(self, table_name):
        return FakeQuery(table_name, self)


@pytest.mark.asyncio
async def test_email_health_composio_outage_returns_unverified_last_known(monkeypatch):
    from api.routers import auth

    fake_supabase = FakeSupabase({
        "ext_connections": [{
            "id": "account-1",
            "user_id": "user-1",
            "provider": "google",
            "external_account_id": "ca-1",
            "verification_status": "connected",
            "is_active": True,
            "scopes": ["gmail.readonly"],
        }]
    })

    async def fail_verify(_connected_account_id):
        raise HTTPException(status_code=502, detail="Composio unavailable")

    monkeypatch.setattr(auth, "get_service_role_client", lambda: fake_supabase)
    monkeypatch.setattr(auth, "verify_composio_backed_connection", fail_verify)

    result = await auth.get_email_account_health("account-1", current_user_id="user-1")

    assert result["status"] == "connected"
    assert result["unverified"] is True
    assert "Unable to verify connection" in result["error_reason"]
    assert fake_supabase.updates == []


@pytest.mark.asyncio
async def test_complete_reconnect_rechecks_state_owner_before_updating(monkeypatch):
    from api.routers import auth

    monkeypatch.setattr(auth, "verify_login_state", lambda _state: {
        "flow": "composio-reconnect",
        "provider": "google",
        "composio_user_id": "other-user",
        "connection_id": "account-1",
    })

    body = auth.CompleteReconnectRequest(
        provider="google",
        state="signed-state",
        status="success",
        connected_account_id="ca-new",
    )

    with pytest.raises(HTTPException) as exc:
        await auth.complete_email_account_reconnect(body, current_user_id="user-1")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_remove_email_account_revoke_failure_still_removes_locally(monkeypatch):
    from api.routers import auth

    fake_supabase = FakeSupabase({
        "ext_connections": [{
            "id": "account-1",
            "user_id": "user-1",
            "external_account_id": "ca-1",
        }]
    })
    removed = []

    async def fail_revoke(*_args, **_kwargs):
        raise RuntimeError("Composio outage")

    monkeypatch.setattr(auth, "get_service_role_client", lambda: fake_supabase)
    monkeypatch.setattr(auth, "revoke_connected_account", fail_revoke)
    monkeypatch.setattr(
        auth.AuthService,
        "remove_email_account",
        staticmethod(lambda account_id, user_id: removed.append((account_id, user_id)) or True),
    )

    result = await auth.remove_email_account("account-1", current_user_id="user-1")

    assert result == {"message": "Email account removed successfully"}
    assert removed == [("account-1", "user-1")]


@pytest.mark.asyncio
async def test_composio_login_persists_connected_account_id_and_profile_account_key(monkeypatch):
    from api.routers import auth

    fake_supabase = FakeSupabase({"ext_connections": []})

    monkeypatch.setattr(auth, "verify_login_state", lambda _state: {
        "provider": "google",
        "composio_user_id": "login-user",
        "redirect_to": "http://localhost/settings",
    })
    monkeypatch.setattr(auth, "get_connected_account_profile", lambda **_kwargs: _await({
        "email": "person@example.com",
        "name": "Person",
        "avatar_url": "https://example.com/avatar.png",
        "provider_account_id": "provider-account-1",
    }))
    monkeypatch.setattr(auth, "get_connected_account_status", lambda _account_id: _await({
        "status": "connected",
        "scopes": ["gmail.readonly"],
        "external_account_id": "provider-account-1",
    }))
    monkeypatch.setattr(auth, "_ensure_auth_user_and_magic_token", lambda **_kwargs: {
        "token_hash": "token-hash",
        "user_id": "user-1",
    })
    monkeypatch.setattr(auth, "get_service_role_client", lambda: fake_supabase)

    body = auth.ComposioLoginCompleteRequest(
        provider="google",
        state="signed-state",
        status="success",
        connected_account_id="ca-composio-1",
    )

    result = await auth.complete_composio_login(
        request=Request({
            "type": "http",
            "method": "POST",
            "path": "/api/auth/composio/complete-login",
            "headers": [(b"origin", b"http://localhost")],
            "client": ("127.0.0.1", 12345),
        }),
        response=Response(),
        body=body,
    )

    payload = fake_supabase.upserts[0]["payload"]
    assert result.email == "person@example.com"
    assert payload["external_account_id"] == "ca-composio-1"
    assert payload["provider_user_id"] == "provider-account-1"
    assert payload["scopes"] == ["gmail.readonly"]


class _await:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        if False:
            yield None
        return self.value
