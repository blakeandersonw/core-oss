import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBiYXNlIiwicmVmIjoidGVzdCIsInJvbGUiOiJhbm9uIn0."
    "testsignature",
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeAsyncClient:
    responses = []
    calls = []

    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def request(self, method, url, **kwargs):
        self.__class__.calls.append((method, url, kwargs))
        response = self.__class__.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def fake_composio_settings(monkeypatch):
    from api.services import composio

    monkeypatch.setattr(composio, "settings", SimpleNamespace(
        composio_api_key="test-key",
        composio_base_url="https://composio.test/api/v3.1",
        composio_google_auth_config_id="ac_google",
        composio_microsoft_auth_config_id="ac_ms",
        composio_github_auth_config_id="ac_gh",
        supabase_jwt_secret="secret",
        supabase_service_role_key="",
        frontend_url="http://localhost:5173",
        get_allowed_origins=["http://localhost:5173"],
    ))
    monkeypatch.setattr(composio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(composio.asyncio, "sleep", lambda *_args, **_kwargs: _NoopAwaitable())
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = []


class _NoopAwaitable:
    def __await__(self):
        if False:
            yield None
        return None


@pytest.mark.asyncio
async def test_get_connected_account_status_parses_tolerantly():
    from api.services.composio import get_connected_account_status

    FakeAsyncClient.responses = [
        FakeResponse(200, {
            "id": "ca_123",
            "status": "EXPIRED",
            "status_reason": "User revoked access",
            "requested_scopes": ["repo"],
            "state": {"val": {"account_id": "provider-123"}},
        })
    ]

    result = await get_connected_account_status("ca_123")

    assert result["status"] == "expired"
    assert result["status_reason"] == "User revoked access"
    assert result["scopes"] == ["repo"]
    assert result["external_account_id"] == "provider-123"


@pytest.mark.asyncio
async def test_revoke_connected_account_treats_404_as_success():
    from api.services.composio import revoke_connected_account

    FakeAsyncClient.responses = [FakeResponse(404, {"message": "not found"})]

    result = await revoke_connected_account("missing", hard=True)

    assert result == {}
    assert FakeAsyncClient.calls[0][0] == "DELETE"


@pytest.mark.asyncio
async def test_list_connected_accounts_for_user_reads_items_page():
    from api.services.composio import list_connected_accounts_for_user

    FakeAsyncClient.responses = [
        FakeResponse(200, {
            "items": [
                {"id": "ca_1", "status": "ACTIVE"},
                {"id": "ca_2", "status": "EXPIRED"},
            ],
            "next_cursor": "cursor-2",
        })
    ]

    result = await list_connected_accounts_for_user("user-1", limit=2)

    assert [item["id"] for item in result["items"]] == ["ca_1", "ca_2"]
    assert result["next_cursor"] == "cursor-2"
    method, url, kwargs = FakeAsyncClient.calls[0]
    assert method == "GET"
    assert url.endswith("/connected_accounts")
    assert kwargs["params"] == {"user_ids[]": "user-1", "limit": 2}


@pytest.mark.asyncio
async def test_get_connected_account_profile_allows_deprecated_provider_user_id_field():
    from api.services.composio import get_connected_account_profile

    FakeAsyncClient.responses = [
        FakeResponse(200, {
            "id": "ca_123",
            "user_id": "provider-account-123",
            "status": "ACTIVE",
            "email": "person@example.com",
        }),
        FakeResponse(200, {
            "items": [{"id": "ca_123", "status": "ACTIVE"}],
        }),
        FakeResponse(502, {"message": "profile tool unavailable"}),
    ]

    result = await get_connected_account_profile(
        provider="google",
        user_id="login-user-1",
        connected_account_id="ca_123",
    )

    assert result["email"] == "person@example.com"
    assert result["provider_account_id"] == "provider-account-123"


@pytest.mark.asyncio
async def test_get_connected_account_profile_rejects_account_outside_login_user():
    from api.services.composio import get_connected_account_profile

    FakeAsyncClient.responses = [
        FakeResponse(200, {
            "id": "ca_123",
            "email": "person@example.com",
        }),
        FakeResponse(200, {
            "items": [{"id": "ca_other", "status": "ACTIVE"}],
        }),
    ]

    with pytest.raises(HTTPException) as exc:
        await get_connected_account_profile(
            provider="google",
            user_id="login-user-1",
            connected_account_id="ca_123",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_request_with_retry_retries_429_then_succeeds():
    from api.services.composio import get_connected_account_status

    FakeAsyncClient.responses = [
        FakeResponse(429, {"message": "rate limited"}),
        FakeResponse(200, {"id": "ca_123", "status": "ACTIVE"}),
    ]

    result = await get_connected_account_status("ca_123")

    assert result["status"] == "connected"
    assert len(FakeAsyncClient.calls) == 2
