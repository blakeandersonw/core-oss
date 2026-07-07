import os

import pytest
from fastapi import HTTPException

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
        self._operation = "select"
        self._payload = None
        self._filters = []
        self._in_filters = []
        self._order_key = None

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

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def in_(self, key, values):
        self._in_filters.append((key, set(values)))
        return self

    def order(self, key, *_args, **_kwargs):
        self._order_key = key
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
        for key, values in self._in_filters:
            rows = [row for row in rows if row.get(key) in values]
        if self._order_key:
            rows.sort(key=lambda row: row.get(self._order_key) or 0)
        return type("Result", (), {"data": rows})()


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.updates = []
        self.upserts = []

    def table(self, table_name):
        return FakeQuery(table_name, self)


@pytest.mark.asyncio
async def test_avatar_initiate_reports_storage_configuration_error(monkeypatch):
    from api.config import settings
    from api.routers import users
    from lib import r2_client

    monkeypatch.setattr(settings, "r2_s3_api", "")
    monkeypatch.setattr(settings, "r2_access_key_id", "")
    monkeypatch.setattr(settings, "r2_secret_access_key", "")
    monkeypatch.setattr(settings, "r2_bucket_name", "")
    r2_client._r2_client = None

    request = users.AvatarUploadInitiateRequest(
        filename="avatar.png",
        content_type="image/png",
        file_size=1024,
    )

    with pytest.raises(HTTPException) as exc:
        await users.initiate_avatar_upload(request, current_user_id="user-1")

    assert exc.value.status_code == 500
    assert exc.value.detail == "Storage upload is not configured"


@pytest.mark.asyncio
async def test_workspace_icon_initiate_reports_storage_configuration_error(monkeypatch):
    from api.config import settings
    from api.routers import workspaces
    from lib import r2_client

    async def owner_role(*_args, **_kwargs):
        return "owner"

    monkeypatch.setattr(workspaces, "get_user_workspace_role", owner_role)
    monkeypatch.setattr(settings, "r2_s3_api", "")
    monkeypatch.setattr(settings, "r2_access_key_id", "")
    monkeypatch.setattr(settings, "r2_secret_access_key", "")
    monkeypatch.setattr(settings, "r2_bucket_name", "")
    r2_client._r2_client = None

    request = workspaces.WorkspaceIconUploadInitiateRequest(
        filename="logo.png",
        content_type="image/png",
        file_size=1024,
    )

    with pytest.raises(HTTPException) as exc:
        await workspaces.initiate_workspace_icon_upload(
            "workspace-1",
            request,
            user_jwt="jwt",
            user_id="user-1",
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Storage upload is not configured"


def test_get_email_accounts_filters_inactive_and_dedupes_by_email(monkeypatch):
    from api.services import auth

    fake_supabase = FakeSupabase({
        "ext_connections": [
            {
                "id": "secondary-later",
                "user_id": "user-1",
                "provider": "google",
                "provider_email": "Mark@StarterStack.ai",
                "is_primary": False,
                "account_order": 2,
                "is_active": True,
                "created_at": "2026-07-05T00:00:00Z",
                "metadata": {},
            },
            {
                "id": "primary-earlier",
                "user_id": "user-1",
                "provider": "google",
                "provider_email": "mark@starterstack.ai",
                "is_primary": True,
                "account_order": 0,
                "is_active": True,
                "created_at": "2026-07-04T00:00:00Z",
                "metadata": {},
            },
            {
                "id": "inactive",
                "user_id": "user-1",
                "provider": "google",
                "provider_email": "other@starterstack.ai",
                "is_primary": False,
                "account_order": 1,
                "is_active": False,
                "created_at": "2026-07-03T00:00:00Z",
                "metadata": {},
            },
        ]
    })
    monkeypatch.setattr(auth, "get_authenticated_supabase_client", lambda _jwt: fake_supabase)

    accounts = auth.AuthService.get_email_accounts("user-1", "jwt")

    assert [account["id"] for account in accounts] == ["primary-earlier"]


@pytest.mark.asyncio
async def test_verify_email_accounts_dedupes_response(monkeypatch):
    from api.routers import auth
    from api.services.connections.hardening import ConnectionHealth

    fake_supabase = FakeSupabase({
        "ext_connections": [
            {
                "id": "duplicate",
                "user_id": "user-1",
                "provider": "google",
                "provider_email": "MARK@starterstack.ai",
                "is_primary": False,
                "account_order": 1,
                "is_active": True,
                "created_at": "2026-07-05T00:00:00Z",
                "metadata": {},
                "scopes": ["gmail.readonly"],
            },
            {
                "id": "primary",
                "user_id": "user-1",
                "provider": "google",
                "provider_email": "mark@starterstack.ai",
                "is_primary": True,
                "account_order": 0,
                "is_active": True,
                "created_at": "2026-07-04T00:00:00Z",
                "metadata": {},
                "scopes": ["gmail.readonly"],
            },
        ]
    })

    async def healthy(_client, row):
        return ConnectionHealth(
            status="connected",
            last_verified_at="2026-07-07T00:00:00Z",
            scopes=row.get("scopes"),
        )

    monkeypatch.setattr(auth, "get_service_role_client", lambda: fake_supabase)
    monkeypatch.setattr(auth, "_verify_and_persist_ext_connection", healthy)

    result = await auth.verify_email_accounts(current_user_id="user-1")

    assert [account["id"] for account in result["accounts"]] == ["primary"]


@pytest.mark.asyncio
async def test_add_email_account_rejects_case_insensitive_duplicate(monkeypatch):
    from api.services import auth

    fake_supabase = FakeSupabase({
        "ext_connections": [{
            "id": "existing",
            "user_id": "user-1",
            "provider": "google",
            "provider_email": "mark@starterstack.ai",
            "is_primary": True,
            "account_order": 0,
            "is_active": True,
            "created_at": "2026-07-04T00:00:00Z",
            "metadata": {},
        }]
    })
    monkeypatch.setattr(auth, "get_authenticated_supabase_client", lambda _jwt: fake_supabase)

    with pytest.raises(ValueError, match="already connected"):
        await auth.AuthService.add_email_account(
            user_id="user-1",
            user_jwt="jwt",
            account_data={
                "provider": "google",
                "provider_email": "MARK@StarterStack.ai",
                "provider_user_id": "provider-user-2",
                "access_token": "token",
                "scopes": [],
            },
            account_order=1,
        )
