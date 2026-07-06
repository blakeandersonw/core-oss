"""Workspace client-portal administration helpers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from lib.supabase_client import get_authenticated_async_client, get_async_service_role_client


DEFAULT_API_KEY_SCOPES = [
    "projects:read",
    "contacts:read",
    "connectors:read",
]

SUPPORTED_MCP_TOOLS = [
    {
        "name": "list_project_boards",
        "description": "List project boards in this workspace.",
        "required_scope": "projects:read",
    },
    {
        "name": "list_project_issues",
        "description": "List issues for a board in this workspace.",
        "required_scope": "projects:read",
    },
    {
        "name": "list_client_contacts",
        "description": "List client contacts and domains configured for this workspace.",
        "required_scope": "contacts:read",
    },
]


def _normalize_contact_value(kind: str, value: str) -> str:
    normalized = value.strip().lower()
    if kind == "domain":
        normalized = normalized.lstrip("@")
    return normalized


async def _require_workspace_admin(supabase: Any, workspace_id: str) -> None:
    result = await supabase.rpc(
        "is_workspace_admin",
        {"p_workspace_id": workspace_id},
    ).execute()
    if result.data is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace admin access required",
        )


async def _require_workspace_member(supabase: Any, workspace_id: str) -> None:
    result = await supabase.rpc(
        "is_workspace_member",
        {"p_workspace_id": workspace_id},
    ).execute()
    if result.data is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access required",
        )


async def require_workspace_admin_access(user_jwt: str, workspace_id: str) -> None:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)


async def list_client_contacts(user_jwt: str, workspace_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_member(supabase, workspace_id)
    result = await supabase.table("workspace_client_contacts")\
        .select("*")\
        .eq("workspace_id", workspace_id)\
        .order("kind")\
        .order("value")\
        .execute()
    return result.data or []


async def create_client_contact(
    *,
    user_jwt: str,
    user_id: str,
    workspace_id: str,
    kind: str,
    value: str,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"email", "domain"}:
        raise HTTPException(status_code=400, detail="Contact kind must be email or domain")

    result = await supabase.table("workspace_client_contacts")\
        .insert({
            "workspace_id": workspace_id,
            "kind": normalized_kind,
            "value": _normalize_contact_value(normalized_kind, value),
            "label": label,
            "created_by": user_id,
        })\
        .execute()
    return result.data[0]


async def delete_client_contact(user_jwt: str, workspace_id: str, contact_id: str) -> Dict[str, str]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    await supabase.table("workspace_client_contacts")\
        .delete()\
        .eq("workspace_id", workspace_id)\
        .eq("id", contact_id)\
        .execute()
    return {"status": "deleted", "id": contact_id}


async def get_workspace_contact_filters(user_jwt: str, workspace_id: str) -> Dict[str, List[str]]:
    contacts = await list_client_contacts(user_jwt, workspace_id)
    return {
        "emails": [c["value"] for c in contacts if c.get("kind") == "email"],
        "domains": [c["value"] for c in contacts if c.get("kind") == "domain"],
    }


def contact_matches(filters: Dict[str, List[str]], values: List[Optional[str]]) -> bool:
    emails = set(filters.get("emails") or [])
    domains = set(filters.get("domains") or [])
    if not emails and not domains:
        return False

    for raw_value in values:
        if not raw_value:
            continue
        for token in str(raw_value).replace(";", ",").split(","):
            value = token.strip().lower()
            if not value:
                continue
            if "<" in value and ">" in value:
                value = value.split("<", 1)[1].split(">", 1)[0].strip()
            domain = value.split("@", 1)[1] if "@" in value else value.lstrip("@")
            if value in emails or domain in domains:
                return True
    return False


def filter_email_rows(rows: List[Dict[str, Any]], filters: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    return [
        row for row in rows
        if contact_matches(filters, [
            row.get("from"),
            row.get("sender"),
            row.get("to"),
            row.get("cc"),
            row.get("to_recipients"),
            row.get("cc_recipients"),
        ])
    ]


def filter_calendar_rows(rows: List[Dict[str, Any]], filters: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for row in rows:
        values: List[Optional[str]] = [row.get("organizer_email"), row.get("account_email")]
        for attendee in row.get("attendees") or []:
            if isinstance(attendee, dict):
                values.append(attendee.get("email"))
            else:
                values.append(str(attendee))
        if contact_matches(filters, values):
            matched.append(row)
    return matched


async def list_workspace_connectors(user_jwt: str, workspace_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_member(supabase, workspace_id)
    result = await supabase.table("workspace_connectors")\
        .select("*")\
        .eq("workspace_id", workspace_id)\
        .order("provider")\
        .execute()
    return result.data or []


async def upsert_workspace_connector(
    *,
    user_jwt: str,
    user_id: str,
    workspace_id: str,
    provider: str,
    display_name: Optional[str],
    status_value: str,
    scopes: List[str],
    metadata: Dict[str, Any],
    external_account_id: Optional[str] = None,
    error_reason: Optional[str] = None,
    last_verified_at: Optional[str] = None,
    last_error_at: Optional[str] = None,
    failed_attempts: Optional[int] = None,
    revoked_at: Optional[str] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    payload = {
        "workspace_id": workspace_id,
        "provider": provider.strip().lower(),
        "display_name": display_name,
        "status": status_value,
        "scopes": scopes,
        "metadata": metadata,
        "created_by": user_id,
    }
    if external_account_id is not None:
        payload["external_account_id"] = external_account_id
    if error_reason is not None or status_value in {"connected", "disconnected", "pending", "unknown"}:
        payload["error_reason"] = error_reason
    if last_verified_at is not None:
        payload["last_verified_at"] = last_verified_at
    if last_error_at is not None:
        payload["last_error_at"] = last_error_at
    if failed_attempts is not None:
        payload["failed_attempts"] = failed_attempts
    if revoked_at is not None:
        payload["revoked_at"] = revoked_at
    result = await supabase.table("workspace_connectors")\
        .upsert(payload, on_conflict="workspace_id,provider")\
        .execute()
    return result.data[0]


async def delete_workspace_connector(user_jwt: str, workspace_id: str, connector_id: str) -> Dict[str, str]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    await supabase.table("workspace_connectors")\
        .delete()\
        .eq("workspace_id", workspace_id)\
        .eq("id", connector_id)\
        .execute()
    return {"status": "deleted", "id": connector_id}


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_api_key() -> str:
    return f"core_ws_{secrets.token_urlsafe(32)}"


async def list_api_keys(user_jwt: str, workspace_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    result = await supabase.table("workspace_api_keys")\
        .select("id, workspace_id, name, key_prefix, scopes, created_by, last_used_at, revoked_at, expires_at, created_at")\
        .eq("workspace_id", workspace_id)\
        .order("created_at", desc=True)\
        .execute()
    return result.data or []


async def create_api_key(
    *,
    user_jwt: str,
    user_id: str,
    workspace_id: str,
    name: str,
    scopes: Optional[List[str]] = None,
    expires_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    key = _new_api_key()
    key_prefix = key[:18]
    result = await supabase.table("workspace_api_keys")\
        .insert({
            "workspace_id": workspace_id,
            "name": name,
            "key_prefix": key_prefix,
            "key_hash": _hash_secret(key),
            "scopes": scopes or DEFAULT_API_KEY_SCOPES,
            "created_by": user_id,
            "expires_at": expires_at.isoformat() if expires_at else None,
        })\
        .execute()
    record = result.data[0]
    record["key"] = key
    return record


async def revoke_api_key(user_jwt: str, workspace_id: str, api_key_id: str) -> Dict[str, str]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    await supabase.table("workspace_api_keys")\
        .update({"revoked_at": datetime.now(timezone.utc).isoformat()})\
        .eq("workspace_id", workspace_id)\
        .eq("id", api_key_id)\
        .execute()
    return {"status": "revoked", "id": api_key_id}


async def verify_workspace_api_key(raw_key: str, workspace_id: str) -> Dict[str, Any]:
    svc = await get_async_service_role_client()
    result = await svc.table("workspace_api_keys")\
        .select("*")\
        .eq("workspace_id", workspace_id)\
        .eq("key_hash", _hash_secret(raw_key))\
        .is_("revoked_at", "null")\
        .maybe_single()\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid workspace API key")
    record = result.data
    expires_at = record.get("expires_at")
    if expires_at:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workspace API key expired")
    await svc.table("workspace_api_keys")\
        .update({"last_used_at": datetime.now(timezone.utc).isoformat()})\
        .eq("id", record["id"])\
        .execute()
    return record


def require_api_key_scope(api_key_record: Dict[str, Any], scope: str) -> None:
    scopes = set(api_key_record.get("scopes") or [])
    if scope not in scopes and "*" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing API key scope: {scope}")


async def list_webhook_subscriptions(user_jwt: str, workspace_id: str) -> List[Dict[str, Any]]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    result = await supabase.table("workspace_webhook_subscriptions")\
        .select("*")\
        .eq("workspace_id", workspace_id)\
        .order("created_at", desc=True)\
        .execute()
    return result.data or []


async def create_webhook_subscription(
    *,
    user_jwt: str,
    user_id: str,
    workspace_id: str,
    name: str,
    url: str,
    events: List[str],
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    secret = f"whsec_{secrets.token_urlsafe(24)}"
    result = await supabase.table("workspace_webhook_subscriptions")\
        .insert({
            "workspace_id": workspace_id,
            "name": name,
            "url": url,
            "events": events,
            "secret_prefix": secret[:14],
            "secret_hash": _hash_secret(secret),
            "created_by": user_id,
        })\
        .execute()
    record = result.data[0]
    record["secret"] = secret
    return record


async def delete_webhook_subscription(user_jwt: str, workspace_id: str, webhook_id: str) -> Dict[str, str]:
    supabase = await get_authenticated_async_client(user_jwt)
    await _require_workspace_admin(supabase, workspace_id)
    await supabase.table("workspace_webhook_subscriptions")\
        .delete()\
        .eq("workspace_id", workspace_id)\
        .eq("id", webhook_id)\
        .execute()
    return {"status": "deleted", "id": webhook_id}


async def workspace_mcp_manifest(workspace_id: str, scopes: List[str]) -> Dict[str, Any]:
    allowed = set(scopes)
    tools = [
        tool for tool in SUPPORTED_MCP_TOOLS
        if tool["required_scope"] in allowed or "*" in allowed
    ]
    return {
        "workspace_id": workspace_id,
        "name": "Core Workspace MCP",
        "version": "2026-07-04",
        "tools": tools,
        "resources": [
            "workspace",
            "project_boards",
            "project_issues",
            "client_contacts",
        ],
    }


async def execute_mcp_tool(
    *,
    workspace_id: str,
    api_key_record: Dict[str, Any],
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    svc = await get_async_service_role_client()
    if tool_name == "list_project_boards":
        require_api_key_scope(api_key_record, "projects:read")
        result = await svc.table("project_boards")\
            .select("id, name, description, key, created_at, updated_at")\
            .eq("workspace_id", workspace_id)\
            .order("position")\
            .execute()
        return {"result": result.data or []}

    if tool_name == "list_project_issues":
        require_api_key_scope(api_key_record, "projects:read")
        board_id = arguments.get("board_id")
        if not board_id:
            raise HTTPException(status_code=400, detail="board_id is required")
        board = await svc.table("project_boards")\
            .select("id")\
            .eq("id", board_id)\
            .eq("workspace_id", workspace_id)\
            .maybe_single()\
            .execute()
        if not board.data:
            raise HTTPException(status_code=404, detail="Board not found in workspace")
        result = await svc.table("project_issues")\
            .select("id, board_id, state_id, number, title, priority, type, tags, target_due_at, due_at, created_at, updated_at")\
            .eq("board_id", board_id)\
            .eq("workspace_id", workspace_id)\
            .order("position")\
            .execute()
        return {"result": result.data or []}

    if tool_name == "list_client_contacts":
        require_api_key_scope(api_key_record, "contacts:read")
        result = await svc.table("workspace_client_contacts")\
            .select("kind, value, label")\
            .eq("workspace_id", workspace_id)\
            .order("kind")\
            .order("value")\
            .execute()
        return {"result": result.data or []}

    raise HTTPException(status_code=404, detail="Unknown MCP tool")
