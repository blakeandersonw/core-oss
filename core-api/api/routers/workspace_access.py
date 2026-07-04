"""Workspace client-portal and developer-access endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from api.dependencies import get_current_user_id, get_current_user_jwt
from api.services.workspaces.client_workspace import (
    DEFAULT_API_KEY_SCOPES,
    create_api_key,
    create_client_contact,
    create_webhook_subscription,
    delete_client_contact,
    delete_webhook_subscription,
    delete_workspace_connector,
    execute_mcp_tool,
    list_api_keys,
    list_client_contacts,
    list_webhook_subscriptions,
    list_workspace_connectors,
    revoke_api_key,
    upsert_workspace_connector,
    verify_workspace_api_key,
    workspace_mcp_manifest,
)

router = APIRouter(tags=["workspace-access"])


class ClientContactRequest(BaseModel):
    kind: str = Field(..., description="email or domain")
    value: str = Field(..., min_length=1)
    label: Optional[str] = None


class WorkspaceConnectorRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    display_name: Optional[str] = None
    status: str = "pending"
    scopes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: List[str] = Field(default_factory=lambda: DEFAULT_API_KEY_SCOPES.copy())
    expires_at: Optional[datetime] = None


class WebhookCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    url: HttpUrl
    events: List[str] = Field(default_factory=list)


class McpExecuteRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


@router.get("/api/workspaces/{workspace_id}/client-contacts")
async def list_client_contacts_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    contacts = await list_client_contacts(user_jwt, workspace_id)
    return {"contacts": contacts, "count": len(contacts)}


@router.post("/api/workspaces/{workspace_id}/client-contacts", status_code=201)
async def create_client_contact_endpoint(
    workspace_id: str,
    request: ClientContactRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    contact = await create_client_contact(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        kind=request.kind,
        value=request.value,
        label=request.label,
    )
    return {"contact": contact}


@router.delete("/api/workspaces/{workspace_id}/client-contacts/{contact_id}")
async def delete_client_contact_endpoint(
    workspace_id: str,
    contact_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_client_contact(user_jwt, workspace_id, contact_id)


@router.get("/api/workspaces/{workspace_id}/connectors")
async def list_workspace_connectors_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    return {"connectors": connectors, "count": len(connectors)}


@router.post("/api/workspaces/{workspace_id}/connectors", status_code=201)
async def upsert_workspace_connector_endpoint(
    workspace_id: str,
    request: WorkspaceConnectorRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    connector = await upsert_workspace_connector(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        provider=request.provider,
        display_name=request.display_name,
        status_value=request.status,
        scopes=request.scopes,
        metadata=request.metadata,
    )
    return {"connector": connector}


@router.delete("/api/workspaces/{workspace_id}/connectors/{connector_id}")
async def delete_workspace_connector_endpoint(
    workspace_id: str,
    connector_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_workspace_connector(user_jwt, workspace_id, connector_id)


@router.get("/api/workspaces/{workspace_id}/api-keys")
async def list_api_keys_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    keys = await list_api_keys(user_jwt, workspace_id)
    return {"api_keys": keys, "count": len(keys)}


@router.post("/api/workspaces/{workspace_id}/api-keys", status_code=201)
async def create_api_key_endpoint(
    workspace_id: str,
    request: ApiKeyCreateRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    api_key = await create_api_key(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        name=request.name,
        scopes=request.scopes,
        expires_at=request.expires_at,
    )
    return {"api_key": api_key}


@router.post("/api/workspaces/{workspace_id}/api-keys/{api_key_id}/revoke")
async def revoke_api_key_endpoint(
    workspace_id: str,
    api_key_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await revoke_api_key(user_jwt, workspace_id, api_key_id)


@router.get("/api/workspaces/{workspace_id}/webhooks")
async def list_webhooks_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    webhooks = await list_webhook_subscriptions(user_jwt, workspace_id)
    return {"webhooks": webhooks, "count": len(webhooks)}


@router.post("/api/workspaces/{workspace_id}/webhooks", status_code=201)
async def create_webhook_endpoint(
    workspace_id: str,
    request: WebhookCreateRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    webhook = await create_webhook_subscription(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        name=request.name,
        url=str(request.url),
        events=request.events,
    )
    return {"webhook": webhook}


@router.delete("/api/workspaces/{workspace_id}/webhooks/{webhook_id}")
async def delete_webhook_endpoint(
    workspace_id: str,
    webhook_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_webhook_subscription(user_jwt, workspace_id, webhook_id)


@router.get("/api/workspaces/{workspace_id}/mcp/manifest")
async def user_mcp_manifest_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    keys = await list_api_keys(user_jwt, workspace_id)
    active_scopes = sorted({
        scope
        for key in keys
        if not key.get("revoked_at")
        for scope in (key.get("scopes") or [])
    })
    return await workspace_mcp_manifest(workspace_id, active_scopes or DEFAULT_API_KEY_SCOPES)


async def _api_key_record(
    workspace_id: str,
    x_workspace_api_key: Optional[str] = Header(None, alias="X-Workspace-API-Key"),
):
    if not x_workspace_api_key:
        raise HTTPException(status_code=401, detail="Missing X-Workspace-API-Key header")
    return await verify_workspace_api_key(x_workspace_api_key, workspace_id)


@router.get("/api/mcp/workspaces/{workspace_id}/manifest")
async def external_mcp_manifest_endpoint(
    workspace_id: str,
    api_key_record: Dict[str, Any] = Depends(_api_key_record),
):
    return await workspace_mcp_manifest(workspace_id, api_key_record.get("scopes") or [])


@router.post("/api/mcp/workspaces/{workspace_id}/execute")
async def external_mcp_execute_endpoint(
    workspace_id: str,
    request: McpExecuteRequest,
    api_key_record: Dict[str, Any] = Depends(_api_key_record),
):
    return await execute_mcp_tool(
        workspace_id=workspace_id,
        api_key_record=api_key_record,
        tool_name=request.tool_name,
        arguments=request.arguments,
    )
