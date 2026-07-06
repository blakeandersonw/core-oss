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
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IkpXVCJ9."
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
        self._single = False

    def select(self, _fields: str = "*", **_kwargs: Any) -> "FakeQuery":
        self.op = "select"
        return self

    def update(self, payload: Dict[str, Any]) -> "FakeQuery":
        self.op = "update"
        self.payload = payload
        return self

    def insert(self, payload: Any) -> "FakeQuery":
        self.op = "insert"
        self.payload = payload
        return self

    def delete(self) -> "FakeQuery":
        self.op = "delete"
        return self

    def eq(self, field: str, value: Any) -> "FakeQuery":
        self.filters.append((field, value))
        return self

    def maybe_single(self) -> "FakeQuery":
        self._maybe_single = True
        return self

    def single(self) -> "FakeQuery":
        self._single = True
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
            inserted = [dict(payload, id=payload.get("id", f"{self.table_name}-{len(rows) + i + 1}")) for i, payload in enumerate(payloads)]
            rows.extend(inserted)
            return SimpleNamespace(data=inserted)

        if self.op == "update":
            updated = []
            for row in matched:
                row.update(self.payload or {})
                updated.append(dict(row))
            return SimpleNamespace(data=updated)

        if self.op == "delete":
            self.state[self.table_name] = [row for row in rows if not self._matches(row)]
            return SimpleNamespace(data=matched)

        selected = [dict(row) for row in matched]
        if self._maybe_single or self._single:
            return SimpleNamespace(data=selected[0] if selected else None)
        return SimpleNamespace(data=selected)


class FakeSupabase:
    def __init__(self, state: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.state = state or {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.state, name)


def _state(issue: Optional[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    base_issue = {
        "id": "issue-1",
        "board_id": "board-1",
        "workspace_id": "ws-1",
        "workspace_app_id": "app-1",
        "title": "Launch page",
        "created_by": "creator-1",
        "approval_status": "none",
        "approval_locked": False,
    }
    if issue:
        base_issue.update(issue)
    return {
        "project_issues": [base_issue],
        "workspace_members": [
            {"workspace_id": "ws-1", "user_id": "creator-1", "role": "member"},
            {"workspace_id": "ws-1", "user_id": "approver-1", "role": "member"},
            {"workspace_id": "ws-1", "user_id": "admin-1", "role": "admin"},
        ],
        "project_boards": [{"id": "board-1", "workspace_id": "ws-1", "default_role_capabilities": {}}],
        "project_board_role_presets": [],
        "project_board_member_permissions": [],
    }


@pytest.fixture
def approval_module(monkeypatch):
    from api.services.projects import approvals

    monkeypatch.setattr(approvals, "get_actor_info", AsyncMock(return_value={"actor_name": "Ada", "actor_avatar": None}))
    monkeypatch.setattr(approvals, "create_notification", AsyncMock())
    monkeypatch.setattr(approvals, "get_subscribers", AsyncMock(return_value=[]))
    return approvals


@pytest.mark.asyncio
async def test_request_issue_approval_assigns_approver(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "rejected"}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(
        approval_module,
        "get_issue_by_id",
        AsyncMock(return_value={"id": "issue-1", "approval_status": "pending", "approver_id": "approver-1"}),
    )

    result = await approval_module.request_issue_approval(
        user_id="creator-1",
        user_jwt="jwt",
        issue_id="issue-1",
        approver_id="approver-1",
        note="Ready",
    )

    issue = fake.state["project_issues"][0]
    assert result["approval_status"] == "pending"
    assert issue["approver_id"] == "approver-1"
    assert issue["approval_locked"] is False
    approval_module.create_notification.assert_awaited_once()
    assert approval_module.create_notification.await_args.kwargs["recipients"] == ["approver-1"]


@pytest.mark.asyncio
async def test_request_issue_approval_forbids_creator_as_approver(monkeypatch, approval_module):
    fake = FakeSupabase(_state())
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.request_issue_approval(
            user_id="creator-1",
            user_jwt="jwt",
            issue_id="issue-1",
            approver_id="creator-1",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_issue_approval_requires_assigned_approver(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "pending", "approver_id": "approver-1"}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.approve_issue_approval(
            user_id="admin-1",
            user_jwt="jwt",
            issue_id="issue-1",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_issue_approval_sets_locked(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "pending", "approver_id": "approver-1"}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(approval_module, "get_issue_by_id", AsyncMock(return_value=None))

    result = await approval_module.approve_issue_approval(
        user_id="approver-1",
        user_jwt="jwt",
        issue_id="issue-1",
        note="Ship it",
    )

    assert result["approval_status"] == "approved"
    assert result["approved_by"] == "approver-1"
    assert result["approval_locked"] is True


@pytest.mark.asyncio
async def test_reject_issue_approval_requires_note(approval_module):
    with pytest.raises(HTTPException) as exc_info:
        await approval_module.reject_issue_approval(
            user_id="approver-1",
            user_jwt="jwt",
            issue_id="issue-1",
            note=" ",
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_reject_issue_approval_unlocks(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "pending", "approver_id": "approver-1", "approval_locked": True}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(approval_module, "get_issue_by_id", AsyncMock(return_value=None))

    result = await approval_module.reject_issue_approval(
        user_id="approver-1",
        user_jwt="jwt",
        issue_id="issue-1",
        note="Needs another pass",
    )

    assert result["approval_status"] == "rejected"
    assert result["approval_locked"] is False


@pytest.mark.asyncio
async def test_unlock_issue_approval_requires_manage_approval(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "approved", "approval_locked": True}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))

    with pytest.raises(HTTPException) as exc_info:
        await approval_module.unlock_issue_approval(
            user_id="creator-1",
            user_jwt="jwt",
            issue_id="issue-1",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_unlock_issue_approval_sets_unlocked_for_admin(monkeypatch, approval_module):
    fake = FakeSupabase(_state({"approval_status": "approved", "approval_locked": True}))
    monkeypatch.setattr(approval_module, "get_authenticated_async_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(approval_module, "get_issue_by_id", AsyncMock(return_value=None))

    result = await approval_module.unlock_issue_approval(
        user_id="admin-1",
        user_jwt="jwt",
        issue_id="issue-1",
    )

    assert result["approval_locked"] is False


@pytest.mark.asyncio
async def test_update_issue_lock_guard_blocks_content_but_allows_position(monkeypatch):
    from api.services.projects import issues

    guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="locked"))
    monkeypatch.setattr(issues, "get_authenticated_async_client", AsyncMock(return_value=FakeSupabase(_state())))
    monkeypatch.setattr(
        issues,
        "require_issue_capability",
        AsyncMock(return_value={"id": "issue-1", "board_id": "board-1", "approval_locked": True, "title": "Old"}),
    )
    monkeypatch.setattr(issues, "enforce_issue_not_locked", guard)

    with pytest.raises(HTTPException):
        await issues.update_issue("jwt", "creator-1", "issue-1", title="New")
    guard.assert_awaited_once()

    guard.reset_mock(side_effect=True)
    monkeypatch.setattr(issues, "get_issue_by_id", AsyncMock(return_value={"id": "issue-1", "position": 2}))
    result = await issues.update_issue("jwt", "creator-1", "issue-1", position=2)
    assert result["position"] == 2
    guard.assert_not_awaited()
