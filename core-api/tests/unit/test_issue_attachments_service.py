from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiJ9."
    "testsignature",
)


class FakeQuery:
    def __init__(self, state: Dict[str, List[Dict[str, Any]]], table_name: str):
        self.state = state
        self.table_name = table_name
        self.op = "select"
        self.payload: Any = None
        self.filters: List[tuple[str, Any]] = []
        self._maybe_single = False

    def select(self, _fields: str = "*", **_kwargs: Any) -> "FakeQuery":
        self.op = "select"
        return self

    def insert(self, payload: Any) -> "FakeQuery":
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload: Dict[str, Any]) -> "FakeQuery":
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, field: str, value: Any) -> "FakeQuery":
        self.filters.append((field, value))
        return self

    def maybe_single(self) -> "FakeQuery":
        self._maybe_single = True
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def _rows(self) -> List[Dict[str, Any]]:
        return self.state.setdefault(self.table_name, [])

    def _matches(self, row: Dict[str, Any]) -> bool:
        return all(row.get(field) == value for field, value in self.filters)

    async def execute(self):
        rows = self._rows()
        matched = [row for row in rows if self._matches(row)]

        if self.op == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for payload in payloads:
                row = dict(payload)
                row.setdefault("id", f"{self.table_name}-{len(rows) + 1}")
                rows.append(row)
                inserted.append(dict(row))
            return SimpleNamespace(data=inserted)

        if self.op == "update":
            updated = []
            for row in matched:
                row.update(self.payload or {})
                updated.append(dict(row))
            return SimpleNamespace(data=updated)

        selected = [dict(row) for row in matched]
        if self._maybe_single:
            return SimpleNamespace(data=selected[0] if selected else None)
        return SimpleNamespace(data=selected)


class FakeRpc:
    def __init__(self, data: Any):
        self.data = data

    async def execute(self):
        return SimpleNamespace(data=self.data)


class FakeSupabase:
    def __init__(self, state: Dict[str, List[Dict[str, Any]]]):
        self.state = state

    def table(self, table_name: str) -> FakeQuery:
        return FakeQuery(self.state, table_name)

    def rpc(self, name: str, params: Dict[str, Any]) -> FakeRpc:
        assert name == "allocate_issue_attachment_version"
        attachment_id = params["p_attachment_id"]
        attachment = next(row for row in self.state["issue_attachments"] if row["id"] == attachment_id)
        version_number = attachment["next_version_number"]
        attachment["next_version_number"] += 1
        return FakeRpc(version_number)


class FakeR2:
    presigned_url_expiry = 3600

    def generate_key_for_context(self, user_id: str, filename: str, context: str = "files") -> str:
        return f"{context}/{user_id}/20260705/generated-{filename}"

    def generate_presigned_put_url(self, r2_key: str, content_type: str, expiration: Optional[int] = None):
        return {"url": f"https://upload.test/{r2_key}", "expires_at": "2026-07-05T00:05:00Z"}

    def get_presigned_url(self, r2_key: str, expiration: Optional[int] = None):
        return f"https://download.test/{r2_key}?expires={expiration}"


def _state(locked: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "project_issues": [
            {
                "id": "issue-1",
                "board_id": "board-1",
                "workspace_id": "ws-1",
                "workspace_app_id": "app-1",
                "created_by": "creator-1",
                "approval_locked": locked,
            }
        ],
        "workspace_members": [{"workspace_id": "ws-1", "user_id": "creator-1", "role": "member"}],
        "project_boards": [{"id": "board-1", "workspace_id": "ws-1", "default_role_capabilities": {}}],
        "project_board_role_presets": [],
        "project_board_member_permissions": [],
        "issue_attachments": [],
        "issue_attachment_versions": [],
    }


@pytest.fixture
def attachments_module(monkeypatch):
    from api.services.projects import attachments

    monkeypatch.setattr(attachments, "get_r2_client", lambda: FakeR2())
    return attachments


@pytest.mark.asyncio
async def test_initiate_attachment_upload_returns_presigned_url(monkeypatch, attachments_module):
    fake = FakeSupabase(_state())
    monkeypatch.setattr(attachments_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    result = await attachments_module.initiate_attachment_upload(
        user_id="creator-1",
        user_jwt="jwt",
        issue_id="issue-1",
        filename="brief.pdf",
        content_type="application/pdf",
        file_size=1024,
    )

    assert result["r2_key"].startswith("projects/creator-1/")
    assert result["upload_url"].startswith("https://upload.test/")
    assert result["headers"] == {"Content-Type": "application/pdf"}


@pytest.mark.asyncio
async def test_confirm_attachment_version_creates_v1_and_updates_current(monkeypatch, attachments_module):
    fake = FakeSupabase(_state())
    monkeypatch.setattr(attachments_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    attachment = await attachments_module.confirm_attachment_version(
        user_id="creator-1",
        user_jwt="jwt",
        issue_id="issue-1",
        filename="brief.pdf",
        content_type="application/pdf",
        file_size=1024,
        r2_key="projects/creator-1/20260705/brief.pdf",
    )

    assert attachment["current_version"]["version_number"] == 1
    assert attachment["current_version_id"] == attachment["current_version"]["id"]
    assert attachment["next_version_number"] == 2


@pytest.mark.asyncio
async def test_confirm_attachment_version_allocates_monotonic_versions(monkeypatch, attachments_module):
    state = _state()
    state["issue_attachments"].append({
        "id": "att-1",
        "workspace_app_id": "app-1",
        "workspace_id": "ws-1",
        "issue_id": "issue-1",
        "filename": "brief.pdf",
        "content_type": "application/pdf",
        "next_version_number": 2,
        "current_version_id": "ver-1",
    })
    fake = FakeSupabase(state)
    monkeypatch.setattr(attachments_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    attachment = await attachments_module.confirm_attachment_version(
        user_id="creator-1",
        user_jwt="jwt",
        issue_id="issue-1",
        filename="brief.pdf",
        content_type="application/pdf",
        file_size=2048,
        r2_key="projects/creator-1/20260705/brief-v2.pdf",
        attachment_id="att-1",
    )

    assert attachment["current_version"]["version_number"] == 2
    assert state["issue_attachments"][0]["next_version_number"] == 3


@pytest.mark.asyncio
async def test_attachment_upload_and_confirm_block_when_issue_locked(monkeypatch, attachments_module):
    fake = FakeSupabase(_state(locked=True))
    monkeypatch.setattr(attachments_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    with pytest.raises(HTTPException) as exc_info:
        await attachments_module.initiate_attachment_upload(
            user_id="creator-1",
            user_jwt="jwt",
            issue_id="issue-1",
            filename="brief.pdf",
            content_type="application/pdf",
            file_size=1024,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_versions_and_get_url(monkeypatch, attachments_module):
    state = _state()
    state["issue_attachment_versions"].append({
        "id": "ver-1",
        "workspace_app_id": "app-1",
        "workspace_id": "ws-1",
        "attachment_id": "att-1",
        "version_number": 1,
        "r2_key": "projects/creator-1/20260705/brief.pdf",
        "file_size": 1024,
        "content_type": "application/pdf",
    })
    fake = FakeSupabase(state)
    monkeypatch.setattr(attachments_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    versions = await attachments_module.list_attachment_versions("jwt", "att-1")
    url = await attachments_module.get_attachment_version_url(user_jwt="jwt", version_id="ver-1")

    assert len(versions) == 1
    assert url["url"].startswith("https://download.test/projects/creator-1/")
