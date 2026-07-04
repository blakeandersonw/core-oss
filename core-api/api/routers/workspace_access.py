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


class ClientContactResponse(BaseModel):
    id: str
    workspace_id: str
    kind: str
    value: str
    label: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class ClientContactListResponse(BaseModel):
    contacts: List[ClientContactResponse]
    count: int


class ClientContactEnvelopeResponse(BaseModel):
    contact: ClientContactResponse


class WorkspaceConnectorResponse(BaseModel):
    id: str
    workspace_id: str
    provider: str
    display_name: Optional[str] = None
    status: str
    scopes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class WorkspaceConnectorListResponse(BaseModel):
    connectors: List[WorkspaceConnectorResponse]
    count: int


class WorkspaceConnectorEnvelopeResponse(BaseModel):
    connector: WorkspaceConnectorResponse


class ApiKeyResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    key_prefix: str
    key: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        extra = "allow"


class ApiKeyListResponse(BaseModel):
    api_keys: List[ApiKeyResponse]
    count: int


class ApiKeyEnvelopeResponse(BaseModel):
    api_key: ApiKeyResponse


class WorkspaceWebhookResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    url: str
    events: List[str] = Field(default_factory=list)
    secret: Optional[str] = None
    is_active: bool = True
    last_delivery_at: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        extra = "allow"


class WorkspaceWebhookListResponse(BaseModel):
    webhooks: List[WorkspaceWebhookResponse]
    count: int


class WorkspaceWebhookEnvelopeResponse(BaseModel):
    webhook: WorkspaceWebhookResponse


class DeleteResponse(BaseModel):
    status: str
    id: Optional[str] = None

    class Config:
        extra = "allow"


class McpManifestResponse(BaseModel):
    workspace_id: str
    tools: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        extra = "allow"


class McpExecuteResponse(BaseModel):
    result: Any = None

    class Config:
        extra = "allow"


@router.get("/api/workspaces/{workspace_id}/client-contacts", response_model=ClientContactListResponse)
async def list_client_contacts_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    contacts = await list_client_contacts(user_jwt, workspace_id)
    return {"contacts": contacts, "count": len(contacts)}


@router.post("/api/workspaces/{workspace_id}/client-contacts", response_model=ClientContactEnvelopeResponse, status_code=201)
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


@router.delete("/api/workspaces/{workspace_id}/client-contacts/{contact_id}", response_model=DeleteResponse)
async def delete_client_contact_endpoint(
    workspace_id: str,
    contact_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_client_contact(user_jwt, workspace_id, contact_id)


@router.get("/api/workspaces/{workspace_id}/connectors", response_model=WorkspaceConnectorListResponse)
async def list_workspace_connectors_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    return {"connectors": connectors, "count": len(connectors)}


@router.post("/api/workspaces/{workspace_id}/connectors", response_model=WorkspaceConnectorEnvelopeResponse, status_code=201)
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


@router.delete("/api/workspaces/{workspace_id}/connectors/{connector_id}", response_model=DeleteResponse)
async def delete_workspace_connector_endpoint(
    workspace_id: str,
    connector_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_workspace_connector(user_jwt, workspace_id, connector_id)


@router.get("/api/workspaces/{workspace_id}/api-keys", response_model=ApiKeyListResponse)
async def list_api_keys_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    keys = await list_api_keys(user_jwt, workspace_id)
    return {"api_keys": keys, "count": len(keys)}


@router.post("/api/workspaces/{workspace_id}/api-keys", response_model=ApiKeyEnvelopeResponse, status_code=201)
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


@router.post("/api/workspaces/{workspace_id}/api-keys/{api_key_id}/revoke", response_model=DeleteResponse)
async def revoke_api_key_endpoint(
    workspace_id: str,
    api_key_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await revoke_api_key(user_jwt, workspace_id, api_key_id)


@router.get("/api/workspaces/{workspace_id}/webhooks", response_model=WorkspaceWebhookListResponse)
async def list_webhooks_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    webhooks = await list_webhook_subscriptions(user_jwt, workspace_id)
    return {"webhooks": webhooks, "count": len(webhooks)}


@router.post("/api/workspaces/{workspace_id}/webhooks", response_model=WorkspaceWebhookEnvelopeResponse, status_code=201)
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


@router.delete("/api/workspaces/{workspace_id}/webhooks/{webhook_id}", response_model=DeleteResponse)
async def delete_webhook_endpoint(
    workspace_id: str,
    webhook_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    return await delete_webhook_subscription(user_jwt, workspace_id, webhook_id)


@router.get("/api/workspaces/{workspace_id}/mcp/manifest", response_model=McpManifestResponse)
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


@router.get("/api/mcp/workspaces/{workspace_id}/manifest", response_model=McpManifestResponse)
async def external_mcp_manifest_endpoint(
    workspace_id: str,
    api_key_record: Dict[str, Any] = Depends(_api_key_record),
):
    return await workspace_mcp_manifest(workspace_id, api_key_record.get("scopes") or [])


@router.post("/api/mcp/workspaces/{workspace_id}/execute", response_model=McpExecuteResponse)
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
