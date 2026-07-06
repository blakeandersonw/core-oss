import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBiYXNlIiwicmVmIjoidGVzdCIsInJvbGUiOiJhbm9uIn0."
    "testsignature",
)


class FakeQuery:
    def __init__(self, table_name, rows, updates):
        self.table_name = table_name
        self.rows = rows
        self.updates = updates
        self.not_ = self
        self.calls = []
        self._update_payload = None
        self._eq_filters = []

    def select(self, *args, **kwargs):
        self.calls.append(("select", args, kwargs))
        return self

    def is_(self, *args, **kwargs):
        self.calls.append(("is_", args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self.calls.append(("order", args, kwargs))
        return self

    def limit(self, *args, **kwargs):
        self.calls.append(("limit", args, kwargs))
        return self

    def eq(self, *args, **kwargs):
        self._eq_filters.append(args)
        self.calls.append(("eq", args, kwargs))
        return self

    def update(self, payload):
        self._update_payload = payload
        self.calls.append(("update", (payload,), {}))
        return self

    def execute(self):
        if self._update_payload is not None:
            self.updates.append({
                "table": self.table_name,
                "payload": self._update_payload,
                "filters": self._eq_filters,
            })
            return type("Result", (), {"data": []})()
        return type("Result", (), {"data": self.rows})()


class FakeSupabase:
    def __init__(self):
        self.updates = []
        self.queries = []
        self.rows = {
            "ext_connections": [
                {
                    "id": "ext-connected",
                    "external_account_id": "ca-connected",
                    "provider": "google",
                    "failed_attempts": 0,
                    "scopes": [],
                    "is_active": True,
                },
                {
                    "id": "ext-expired",
                    "external_account_id": "ca-expired",
                    "provider": "google",
                    "failed_attempts": 4,
                    "scopes": [],
                    "is_active": True,
                },
                {
                    "id": "ext-error",
                    "external_account_id": "ca-error",
                    "provider": "microsoft",
                    "failed_attempts": 1,
                    "scopes": [],
                    "is_active": True,
                },
            ],
            "workspace_connectors": [
                {
                    "id": "workspace-connected",
                    "workspace_id": "workspace-1",
                    "external_account_id": "ca-workspace",
                    "provider": "github",
                    "failed_attempts": 0,
                    "scopes": [],
                    "status": "unknown",
                }
            ],
        }

    def table(self, table_name):
        query = FakeQuery(table_name, self.rows.get(table_name, []), self.updates)
        self.queries.append(query)
        return query


@pytest.mark.asyncio
async def test_verify_connectors_disabled_returns_stub(monkeypatch):
    from api.routers import cron

    monkeypatch.setattr(cron, "verify_cron_auth", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cron, "is_connector_verify_enabled", lambda: False)

    result = await cron.cron_verify_connectors("Bearer test")

    assert result["status"] == "disabled"
    assert result["checked"] == 0


@pytest.mark.asyncio
async def test_verify_connectors_batches_deactivates_and_isolates_errors(monkeypatch):
    from api.routers import cron

    fake_supabase = FakeSupabase()
    deactivated = []

    async def fake_status(account_id):
        if account_id == "ca-connected":
            return {"status": "connected", "raw_status": "ACTIVE", "scopes": ["repo"]}
        if account_id == "ca-expired":
            return {"status": "expired", "raw_status": "EXPIRED", "status_reason": "Token revoked", "scopes": []}
        raise RuntimeError("Composio timeout")

    monkeypatch.setattr(cron, "verify_cron_auth", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cron, "is_connector_verify_enabled", lambda: True)
    monkeypatch.setattr(cron, "get_connector_verify_batch_size", lambda: 3)
    monkeypatch.setattr(cron, "get_service_role_client", lambda: fake_supabase)
    monkeypatch.setattr(cron, "capture_checkin", lambda **_kwargs: "check-in")
    monkeypatch.setattr(cron, "get_connected_account_status", fake_status)
    monkeypatch.setattr(
        cron,
        "deactivate_connection_with_subscriptions",
        lambda _client, connection_id, reason=None: deactivated.append((connection_id, reason)),
    )

    result = await cron.cron_verify_connectors("Bearer test")

    assert result["status"] == "completed"
    assert result["checked"] == 3
    assert result["updated"] == 2
    assert result["deactivated"] == 1
    assert result["errors"] == 1
    assert deactivated == [(
        "ext-expired",
        "Sync failed 5 times and hit the retry cap (5); user must reconnect",
    )]
    assert any(
        query.table_name == "ext_connections"
        and ("is_", ("external_account_id", "null"), {}) in query.calls
        and ("order", ("last_verified_at",), {"desc": False, "nullsfirst": True}) in query.calls
        and ("limit", (3,), {}) in query.calls
        for query in fake_supabase.queries
    )
    assert any(
        update["table"] == "ext_connections"
        and update["payload"].get("verification_status") == "connected"
        and update["payload"].get("scopes") == ["repo"]
        for update in fake_supabase.updates
    )
    assert any(
        update["table"] == "ext_connections"
        and update["payload"].get("error_reason") == "Composio timeout"
        for update in fake_supabase.updates
    )
