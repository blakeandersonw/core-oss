from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiJ9."
    "testsignature",
)


class FakeQuery:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows
        self.filters: List[tuple[str, Any]] = []
        self.in_filter: tuple[str, List[str]] | None = None

    def select(self, _fields: str) -> "FakeQuery":
        return self

    def eq(self, field: str, value: Any) -> "FakeQuery":
        self.filters.append((field, value))
        return self

    def in_(self, field: str, values: List[str]) -> "FakeQuery":
        self.in_filter = (field, values)
        return self

    async def execute(self):
        selected = self.rows
        for field, value in self.filters:
            selected = [row for row in selected if row.get(field) == value]
        if self.in_filter:
            field, values = self.in_filter
            selected = [row for row in selected if row.get(field) in values]
        return SimpleNamespace(data=selected)


class FakeSupabase:
    def __init__(self, state: Dict[str, List[Dict[str, Any]]]):
        self.state = state

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.state.get(name, []))


def test_extract_mentioned_user_ids_reads_person_mentions_once():
    from api.services.projects.comments import extract_mentioned_user_ids

    blocks = [
        {"type": "text", "data": {"content": "hello"}},
        {"type": "mention", "data": {"entityType": "person", "entityId": "user-1", "displayName": "Ada"}},
        {"type": "mention", "data": {"entity_type": "person", "entity_id": "user-1", "display_name": "Ada"}},
        {"type": "mention", "data": {"entityType": "document", "entityId": "doc-1", "displayName": "Spec"}},
    ]

    assert extract_mentioned_user_ids(blocks) == ["user-1"]


@pytest.mark.asyncio
async def test_filter_workspace_member_ids_rejects_cross_workspace_mentions():
    from api.services.projects.comments import _filter_workspace_member_ids

    supabase = FakeSupabase(
        {
            "workspace_members": [
                {"workspace_id": "ws-1", "user_id": "user-1"},
                {"workspace_id": "ws-2", "user_id": "user-2"},
            ]
        }
    )

    result = await _filter_workspace_member_ids(
        supabase,
        workspace_id="ws-1",
        user_ids=["user-1", "user-2"],
    )

    assert result == ["user-1"]
