"""Workspace client-portal and developer-access endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from api.dependencies import get_current_user_id, get_current_user_jwt
from api.services.composio import (
    create_connect_link,
    refresh_connected_account,
    revoke_connected_account,
    resolve_frontend_origin,
    sign_login_state,
    validate_provider,
    verify_login_state,
)
from api.services.connections.hardening import (
    health_from_failed_check,
    verify_composio_backed_connection,
    workspace_connector_update_payload,
)
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
    require_workspace_admin_access,
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
    external_account_id: Optional[str] = None


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
    external_account_id: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    last_verified_at: Optional[str] = None
    error_reason: Optional[str] = None
    last_error_at: Optional[str] = None
    failed_attempts: int = 0
    revoked_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class WorkspaceConnectorListResponse(BaseModel):
    connectors: List[WorkspaceConnectorResponse]
    count: int


class WorkspaceConnectorEnvelopeResponse(BaseModel):
    connector: WorkspaceConnectorResponse


class ConnectorReconnectResponse(BaseModel):
    redirect_url: Optional[str] = None
    status: Optional[str] = None

    class Config:
        extra = "allow"


class ConnectorCompleteReconnectRequest(BaseModel):
    provider: str
    state: str
    status: Optional[str] = None
    connected_account_id: Optional[str] = None


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


def _find_connector(connectors: List[Dict[str, Any]], connector_id: str) -> Optional[Dict[str, Any]]:
    return next((connector for connector in connectors if str(connector.get("id")) == connector_id), None)


async def _persist_workspace_connector_health(
    *,
    connector: Dict[str, Any],
    workspace_id: str,
    user_id: str,
    user_jwt: str,
) -> Dict[str, Any]:
    external_account_id = connector.get("external_account_id")
    if not external_account_id:
        return connector
    try:
        health = await verify_composio_backed_connection(str(external_account_id))
        payload = workspace_connector_update_payload(health)
    except Exception as exc:
        health = health_from_failed_check(connector, table="workspace_connectors", error=exc)
        return {
            **connector,
            "unverified": True,
            "error_reason": health.error_reason,
        }

    return await upsert_workspace_connector(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        provider=str(connector.get("provider") or ""),
        display_name=connector.get("display_name"),
        status_value=str(payload["status"]),
        scopes=list(payload.get("scopes") or connector.get("scopes") or []),
        metadata=dict(connector.get("metadata") or {}),
        external_account_id=payload.get("external_account_id") or external_account_id,
        error_reason=payload.get("error_reason"),
        last_verified_at=payload.get("last_verified_at"),
        last_error_at=payload.get("last_error_at"),
        failed_attempts=payload.get("failed_attempts"),
    )


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
        external_account_id=request.external_account_id,
    )
    return {"connector": connector}


@router.post("/api/workspaces/{workspace_id}/connectors/{connector_id}/verify", response_model=WorkspaceConnectorEnvelopeResponse)
async def verify_workspace_connector_endpoint(
    workspace_id: str,
    connector_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    await require_workspace_admin_access(user_jwt, workspace_id)
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    connector = _find_connector(connectors, connector_id)
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    verified = await _persist_workspace_connector_health(
        connector=connector,
        workspace_id=workspace_id,
        user_id=user_id,
        user_jwt=user_jwt,
    )
    return {"connector": verified}


@router.post("/api/workspaces/{workspace_id}/connectors/verify", response_model=WorkspaceConnectorListResponse)
async def verify_workspace_connectors_endpoint(
    workspace_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    await require_workspace_admin_access(user_jwt, workspace_id)
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    verified = []
    for connector in connectors:
        verified.append(await _persist_workspace_connector_health(
            connector=connector,
            workspace_id=workspace_id,
            user_id=user_id,
            user_jwt=user_jwt,
        ))
    return {"connectors": verified, "count": len(verified)}


@router.post("/api/workspaces/{workspace_id}/connectors/{connector_id}/reconnect", response_model=ConnectorReconnectResponse)
async def reconnect_workspace_connector_endpoint(
    workspace_id: str,
    connector_id: str,
    request: Request,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    await require_workspace_admin_access(user_jwt, workspace_id)
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    connector = _find_connector(connectors, connector_id)
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    provider = validate_provider(str(connector.get("provider") or ""))
    external_account_id = connector.get("external_account_id")
    if external_account_id:
        refresh = await refresh_connected_account(str(external_account_id))
        if refresh.get("redirect_url"):
            return refresh
        if refresh.get("status") == "connected":
            return {"status": "connected"}

    frontend_origin = resolve_frontend_origin(request.headers.get("origin"))
    state = sign_login_state(
        provider=provider,
        redirect_to=frontend_origin,
        composio_user_id=user_id,
        flow="workspace-connector-reconnect",
        connection_id=connector_id,
        workspace_id=workspace_id,
    )
    callback_query = urlencode({
        "flow": "workspace-connector-reconnect",
        "provider": provider,
        "state": state,
    })
    callback_url = f"{frontend_origin}/oauth/callback?{callback_query}"
    link = await create_connect_link(provider=provider, user_id=user_id, callback_url=callback_url)
    redirect_url = link.get("redirect_url")
    if not isinstance(redirect_url, str) or not redirect_url:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Composio did not return a redirect URL")
    return {"redirect_url": redirect_url, "status": "pending"}


@router.post("/api/workspaces/{workspace_id}/connectors/complete-reconnect", response_model=WorkspaceConnectorEnvelopeResponse)
async def complete_workspace_connector_reconnect_endpoint(
    workspace_id: str,
    body: ConnectorCompleteReconnectRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    await require_workspace_admin_access(user_jwt, workspace_id)
    if body.status and body.status != "success":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Composio reconnect failed")
    provider = validate_provider(body.provider)
    state_payload = verify_login_state(body.state)
    if (
        state_payload.get("flow") != "workspace-connector-reconnect"
        or state_payload.get("provider") != provider
        or state_payload.get("composio_user_id") != user_id
        or state_payload.get("workspace_id") != workspace_id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reconnect state does not match workspace")
    connector_id = str(state_payload.get("connection_id") or "")
    if not connector_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reconnect state is missing connector")
    if not body.connected_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Composio connected account ID")

    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    connector = _find_connector(connectors, connector_id)
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    updated = await upsert_workspace_connector(
        user_jwt=user_jwt,
        user_id=user_id,
        workspace_id=workspace_id,
        provider=str(connector.get("provider") or provider),
        display_name=connector.get("display_name"),
        status_value="pending",
        scopes=list(connector.get("scopes") or []),
        metadata=dict(connector.get("metadata") or {}),
        external_account_id=body.connected_account_id,
    )
    verified = await _persist_workspace_connector_health(
        connector=updated,
        workspace_id=workspace_id,
        user_id=user_id,
        user_jwt=user_jwt,
    )
    return {"connector": verified}


@router.delete("/api/workspaces/{workspace_id}/connectors/{connector_id}", response_model=DeleteResponse)
async def delete_workspace_connector_endpoint(
    workspace_id: str,
    connector_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    await require_workspace_admin_access(user_jwt, workspace_id)
    connectors = await list_workspace_connectors(user_jwt, workspace_id)
    connector = _find_connector(connectors, connector_id)
    if connector and connector.get("external_account_id"):
        try:
            await revoke_connected_account(str(connector["external_account_id"]), hard=True)
        except Exception:
            pass
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
