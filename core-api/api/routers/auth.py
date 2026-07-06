"""
Authentication router - HTTP endpoints for auth operations
"""
from typing import Annotated, Optional, List, Dict, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from api.services.auth import AuthService
from api.services.composio import (
    create_connect_link,
    get_connected_account_profile,
    get_connected_account_status,
    make_login_composio_user_id,
    normalize_redirect_to,
    refresh_connected_account,
    revoke_connected_account,
    resolve_frontend_origin,
    sign_login_state,
    validate_provider,
    verify_login_state,
)
from api.services.connections.hardening import (
    ConnectionHealth,
    ext_connection_update_payload,
    health_from_failed_check,
    health_from_legacy_ext_connection,
    verify_composio_backed_connection,
)
from api.services.workspaces.invitations import resolve_post_signup_pending_invitations
from api.dependencies import get_current_user_email, get_current_user_jwt, get_current_user_id
from api.exceptions import handle_api_exception
from api.schemas import MessageResponse
from api.config import settings
from api.rate_limit import limiter, _get_client_ip
from lib.supabase_client import get_service_role_client
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ============== Turnstile Verification ==============

class TurnstileVerifyRequest(BaseModel):
    """Request to verify a Cloudflare Turnstile token"""
    token: str

class TurnstileVerifyResponse(BaseModel):
    """Response from Turnstile verification"""
    success: bool


@router.post("/verify-turnstile", response_model=TurnstileVerifyResponse)
@limiter.limit("10/minute", key_func=_get_client_ip)
async def verify_turnstile(request: Request, response: Response, body: TurnstileVerifyRequest) -> TurnstileVerifyResponse:
    """Verify a Cloudflare Turnstile token before allowing OAuth sign-in."""
    if not settings.turnstile_secret_key:
        # If not configured, allow through (dev environments without Turnstile)
        return TurnstileVerifyResponse(success=True)

    try:
        async with httpx.AsyncClient() as client:
            result = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.turnstile_secret_key,
                    "response": body.token,
                    "remoteip": _get_client_ip(request),
                },
            )
            data = result.json()
            if not data.get("success"):
                logger.warning("Turnstile verification failed: %s", data.get("error-codes"))
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bot verification failed")
            return TurnstileVerifyResponse(success=True)
    except httpx.HTTPError as e:
        logger.error("Turnstile API error: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Verification service unavailable")


# ============== OAuth Config Endpoint ==============

class OAuthConfigResponse(BaseModel):
    """Response model for OAuth configuration"""
    google_client_id: str
    microsoft_client_id: Optional[str] = None
    supported_providers: List[str] = ["google", "microsoft"]


@router.get("/oauth-config", response_model=OAuthConfigResponse)
async def get_oauth_config():
    """
    Get OAuth configuration for client-side OAuth flows.

    Returns OAuth Client IDs needed for direct OAuth flows
    (used for adding secondary email accounts without creating Supabase users).
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured"
        )

    return OAuthConfigResponse(
        google_client_id=settings.google_client_id,
        microsoft_client_id=settings.microsoft_client_id or None,
        supported_providers=["google", "microsoft"]
    )


# ============== Composio Sign-in Bridge ==============

class ComposioLoginStartRequest(BaseModel):
    provider: Literal["google", "microsoft"]
    redirect_to: Optional[str] = None


class ComposioLoginStartResponse(BaseModel):
    redirect_url: str


class ComposioLoginCompleteRequest(BaseModel):
    provider: Literal["google", "microsoft"]
    state: str
    status: Optional[str] = None
    connected_account_id: str


class ComposioLoginCompleteResponse(BaseModel):
    email: EmailStr
    token_hash: str
    redirect_to: str


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _read_nested_field(value: Any, *fields: str) -> Any:
    current = value
    for field in fields:
        current = _read_field(current, field)
        if current is None:
            return None
    return current


def _select_ext_connection(service_supabase: Any, connection_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    result = service_supabase.table("ext_connections")\
        .select("*")\
        .eq("id", connection_id)\
        .eq("user_id", user_id)\
        .maybe_single()\
        .execute()
    return result.data


async def _verify_and_persist_ext_connection(
    service_supabase: Any,
    row: Dict[str, Any],
) -> ConnectionHealth:
    connection_id = str(row["id"])
    external_account_id = row.get("external_account_id")
    try:
        if external_account_id:
            health = await verify_composio_backed_connection(str(external_account_id))
        else:
            health = health_from_legacy_ext_connection(row)
        service_supabase.table("ext_connections")\
            .update(ext_connection_update_payload(health))\
            .eq("id", connection_id)\
            .execute()
        return health
    except HTTPException as exc:
        if exc.status_code not in {
            status.HTTP_501_NOT_IMPLEMENTED,
            status.HTTP_502_BAD_GATEWAY,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        }:
            raise
        return health_from_failed_check(row, table="ext_connections", error=exc.detail)
    except Exception as exc:
        return health_from_failed_check(row, table="ext_connections", error=exc)


async def _best_effort_revoke_ext_connection_source(
    service_supabase: Any,
    connection_id: str,
    user_id: str,
) -> None:
    row = _select_ext_connection(service_supabase, connection_id, user_id)
    external_account_id = (row or {}).get("external_account_id")
    if not external_account_id:
        return
    try:
        await revoke_connected_account(str(external_account_id), hard=True)
        service_supabase.table("ext_connections")\
            .update({"revoked_at": datetime_now_iso()})\
            .eq("id", connection_id)\
            .execute()
    except Exception as exc:
        logger.warning("Composio revoke failed for connection %s: %s", connection_id, exc)


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _ensure_auth_user_and_magic_token(
    *,
    email: str,
    name: Optional[str],
    avatar_url: Optional[str],
    provider: str,
) -> Dict[str, str]:
    service_supabase = get_service_role_client()
    user_metadata = {
        "name": name,
        "full_name": name,
        "avatar_url": avatar_url,
        "picture": avatar_url,
        "composio_provider": provider,
    }
    user_metadata = {k: v for k, v in user_metadata.items() if v}
    params = {
        "type": "magiclink",
        "email": email,
        "options": {"data": user_metadata},
    }

    try:
        link = service_supabase.auth.admin.generate_link(params)
    except Exception as generate_error:
        logger.info("Creating Supabase Auth user for Composio sign-in: %s", email)
        try:
            service_supabase.auth.admin.create_user({
                "email": email,
                "email_confirm": True,
                "user_metadata": user_metadata,
            })
        except Exception as create_error:
            if "already" not in str(create_error).lower() and "registered" not in str(create_error).lower():
                raise create_error
        try:
            link = service_supabase.auth.admin.generate_link(params)
        except Exception as retry_error:
            logger.error("Failed to generate Supabase magic link after Composio auth: %s", retry_error)
            raise generate_error from retry_error

    token_hash = _read_nested_field(link, "properties", "hashed_token")
    user = _read_field(link, "user")
    user_id = _read_field(user, "id")
    if not token_hash or not user_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase did not return a login token",
        )

    existing = service_supabase.table("users")\
        .select("id, name, avatar_url")\
        .eq("id", user_id)\
        .maybe_single()\
        .execute()

    if existing.data:
        updates: Dict[str, Any] = {"email": email}
        if name and not existing.data.get("name"):
            updates["name"] = name
        if avatar_url and not existing.data.get("avatar_url"):
            updates["avatar_url"] = avatar_url
        service_supabase.table("users").update(updates).eq("id", user_id).execute()
    else:
        service_supabase.table("users").insert({
            "id": user_id,
            "email": email,
            "name": name,
            "avatar_url": avatar_url,
        }).execute()

    return {"token_hash": token_hash, "user_id": user_id}


@router.post("/composio/start", response_model=ComposioLoginStartResponse)
@limiter.limit("10/minute;100/day", key_func=_get_client_ip)
async def start_composio_login(
    request: Request,
    response: Response,
    body: ComposioLoginStartRequest,
):
    """Start a Composio Connect Link sign-in and return the hosted auth URL."""
    provider = validate_provider(body.provider)
    frontend_origin = resolve_frontend_origin(request.headers.get("origin"))
    redirect_to = normalize_redirect_to(body.redirect_to, frontend_origin)
    composio_user_id = make_login_composio_user_id()
    state = sign_login_state(
        provider=provider,
        redirect_to=redirect_to,
        composio_user_id=composio_user_id,
    )
    callback_query = urlencode({
        'flow': 'composio-login',
        'provider': provider,
        'state': state,
    })
    callback_url = f"{frontend_origin}/oauth/callback?{callback_query}"

    link = await create_connect_link(
        provider=provider,
        user_id=composio_user_id,
        callback_url=callback_url,
    )
    redirect_url = link.get("redirect_url")
    if not isinstance(redirect_url, str) or not redirect_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Composio did not return a redirect URL",
        )
    return ComposioLoginStartResponse(redirect_url=redirect_url)


@router.post("/composio/complete-login", response_model=ComposioLoginCompleteResponse)
@limiter.limit("10/minute;100/day", key_func=_get_client_ip)
async def complete_composio_login(
    request: Request,
    response: Response,
    body: ComposioLoginCompleteRequest,
):
    """
    Complete Composio sign-in by minting a Supabase email-token session.

    Composio proves the Google/Microsoft account connection; Supabase remains
    the app's session issuer so existing RLS and Supabase client flows continue
    to work.
    """
    if body.status and body.status != "success":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Composio authentication did not complete successfully",
        )

    provider = validate_provider(body.provider)
    state_payload = verify_login_state(body.state)
    if state_payload.get("provider") != provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Composio auth provider mismatch",
        )

    profile = await get_connected_account_profile(
        provider=provider,
        user_id=str(state_payload["composio_user_id"]),
        connected_account_id=body.connected_account_id,
    )
    email = str(profile["email"])
    session = _ensure_auth_user_and_magic_token(
        email=email,
        name=profile.get("name"),
        avatar_url=profile.get("avatar_url"),
        provider=provider,
    )
    health_payload: Dict[str, Any] = {}
    try:
        health_payload = await get_connected_account_status(body.connected_account_id)
    except Exception as exc:
        logger.warning("Unable to read Composio status during login completion: %s", exc)

    service_supabase = get_service_role_client()
    provider_account_id = (
        profile.get("provider_account_id")
        or health_payload.get("external_account_id")
    )
    provider_user_id = str(provider_account_id or email)
    scopes = list(health_payload.get("scopes") or [])
    existing_primary = service_supabase.table("ext_connections")\
        .select("id")\
        .eq("user_id", session["user_id"])\
        .eq("is_primary", True)\
        .eq("is_active", True)\
        .limit(1)\
        .execute()
    has_primary = bool(existing_primary.data)
    connection_payload: Dict[str, Any] = {
        "user_id": session["user_id"],
        "provider": provider,
        "provider_user_id": provider_user_id,
        "provider_email": email,
        "external_account_id": body.connected_account_id,
        "verification_status": health_payload.get("status") or "connected",
        "last_verified_at": datetime_now_iso(),
        "scopes": scopes,
        "is_active": True,
        "is_primary": not has_primary,
        "account_order": 0 if not has_primary else 1,
        "metadata": {
            "full_name": profile.get("name"),
            "picture": profile.get("avatar_url"),
            "composio_external_account_id": provider_account_id,
        },
    }
    service_supabase.table("ext_connections")\
        .upsert(connection_payload, on_conflict="user_id,provider,provider_user_id")\
        .execute()

    return ComposioLoginCompleteResponse(
        email=email,
        token_hash=session["token_hash"],
        redirect_to=str(state_payload.get("redirect_to") or resolve_frontend_origin(request.headers.get("origin"))),
    )


# ============== Microsoft Pre-Auth Code Exchange ==============

class MicrosoftCodeExchangeRequest(BaseModel):
    """Request to exchange Microsoft auth code for tokens (pre-Supabase auth)"""
    auth_code: str
    code_verifier: Optional[str] = None  # PKCE verifier
    redirect_uri: Optional[str] = None


class MicrosoftCodeExchangeResponse(BaseModel):
    """Response with tokens for Supabase auth and backend storage"""
    id_token: str  # For Supabase signInWithIdToken
    access_token: str  # For backend storage
    refresh_token: Optional[str] = None  # For backend storage
    expires_in: int


@router.post("/microsoft/exchange-code", response_model=MicrosoftCodeExchangeResponse)
@limiter.limit("5/minute;50/day", key_func=_get_client_ip)
async def exchange_microsoft_code(request: Request, response: Response, body: MicrosoftCodeExchangeRequest):
    """
    Exchange Microsoft authorization code for tokens.

    This is a PRE-AUTH endpoint - NO Supabase JWT required.

    Flow:
    1. iOS gets auth code via ASWebAuthenticationSession
    2. iOS calls this endpoint to exchange code for tokens
    3. iOS uses returned id_token to sign into Supabase
    4. iOS calls /complete-oauth with Supabase JWT to store user and tokens

    Returns:
        id_token: Use this for Supabase signInWithIdToken
        access_token, refresh_token, expires_in: Pass these to /complete-oauth
    """
    from api.services.auth import exchange_auth_code_for_tokens

    try:
        logger.info("🔑 [Microsoft] Pre-auth code exchange...")

        tokens = exchange_auth_code_for_tokens(
            body.auth_code,
            redirect_uri=body.redirect_uri,
            provider="microsoft",
            code_verifier=body.code_verifier
        )

        if not tokens.get("id_token"):
            logger.error("❌ [Microsoft] No id_token in exchange response")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token exchange did not return id_token. Ensure 'openid' scope is requested."
            )

        logger.info("✅ [Microsoft] Pre-auth exchange successful")

        return MicrosoftCodeExchangeResponse(
            id_token=tokens["id_token"],
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            expires_in=tokens.get("expires_in", 3600)
        )

    except ValueError as e:
        logger.error(f"❌ [Microsoft] Code exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        handle_api_exception(e, "Failed to exchange authorization code", logger)


# Pydantic models for request/response validation
class UserCreate(BaseModel):
    id: str
    email: EmailStr
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class OAuthConnectionCreate(BaseModel):
    user_id: str
    provider: str
    provider_user_id: str
    provider_email: Optional[str] = None
    access_token: str
    refresh_token: Optional[str] = None
    scopes: List[str] = []
    metadata: Optional[dict] = None


class OAuthConnectionResponse(BaseModel):
    id: str
    user_id: str
    provider: str
    is_active: bool
    scopes: List[str]
    created_at: str

    class Config:
        extra = "allow"


class UserCreateResponse(BaseModel):
    """Response model for user creation."""
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        extra = "allow"


class OAuthConnectionsListResponse(BaseModel):
    """Response model for listing user OAuth connections."""
    connections: Optional[List[OAuthConnectionResponse]] = None

    class Config:
        extra = "allow"


class CompleteOAuthResponse(BaseModel):
    """Response model for complete OAuth flow."""
    user: Optional[Dict[str, Any]] = None
    connection: Optional[Dict[str, Any]] = None
    watches: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class PostSignupResponse(BaseModel):
    """Response model for pending invitation resolution after auth bootstrap."""
    pending_invitations: List[Dict[str, Any]]
    count: int

    class Config:
        extra = "allow"


# ============== Multi-Account Models ==============

class EmailAccountResponse(BaseModel):
    """Response model for a connected email account"""
    id: str
    provider: str = "google"  # 'google' or 'microsoft'
    provider_email: str
    provider_name: Optional[str] = None
    provider_avatar: Optional[str] = None
    is_primary: bool
    account_order: int
    is_active: bool
    verification_status: Optional[str] = "unknown"
    last_verified_at: Optional[str] = None
    error_reason: Optional[str] = None
    scopes: List[str] = []
    external_account_id: Optional[str] = None
    unverified: bool = False

    class Config:
        extra = "allow"


class EmailAccountsListResponse(BaseModel):
    """Response model for listing all connected accounts"""
    accounts: List[EmailAccountResponse]


class AddEmailAccountRequest(BaseModel):
    """Request model for adding a secondary email account"""
    provider: str = "google"
    # These can be optional when using server_auth_code (fetched from Google)
    provider_user_id: Optional[str] = None
    provider_email: Optional[EmailStr] = None
    # Either access_token OR server_auth_code must be provided
    access_token: Optional[str] = None
    server_auth_code: Optional[str] = None  # For iOS or web direct OAuth
    code_verifier: Optional[str] = None  # PKCE verifier for Microsoft iOS flow
    redirect_uri: Optional[str] = None  # Required for web OAuth code exchange
    refresh_token: Optional[str] = None
    scopes: List[str] = []
    metadata: Optional[dict] = None


class UpdateEmailAccountRequest(BaseModel):
    """Request model for updating account order"""
    account_order: int


class ConnectionHealthResponse(BaseModel):
    status: str
    last_verified_at: Optional[str] = None
    error_reason: Optional[str] = None
    scopes: List[str] = []
    external_account_id: Optional[str] = None
    unverified: bool = False

    class Config:
        extra = "allow"


class ReconnectResponse(BaseModel):
    redirect_url: Optional[str] = None
    status: Optional[str] = None

    class Config:
        extra = "allow"


class CompleteReconnectRequest(BaseModel):
    provider: str
    state: str
    status: Optional[str] = None
    connected_account_id: Optional[str] = None


@router.post("/users", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    current_user_email: Annotated[str, Depends(get_current_user_email)],
    user_jwt: Annotated[str, Depends(get_current_user_jwt)],
):
    """
    Create a new user in the database.
    If user already exists, returns existing user.

    Requires: Authorization header with user's Supabase JWT
    User ID in request must match the authenticated user.
    """
    # Validate user_id matches JWT
    if user.id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create user for a different user ID"
        )

    # Validate email matches JWT claim to prevent spoofed profile rows
    if str(user.email).strip().lower() != current_user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create user with a different email"
        )

    try:
        return AuthService.create_user(user.model_dump(), user_jwt)
    except Exception as e:
        handle_api_exception(e, "Failed to create user", logger)


@router.post("/oauth-connections", response_model=OAuthConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_oauth_connection(
    connection: OAuthConnectionCreate,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Store OAuth connection tokens for a user.
    Creates or updates the connection if it already exists.

    Requires: Authorization header with user's Supabase JWT
    User ID in request must match the authenticated user.
    """
    # Validate user_id matches JWT
    if connection.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create OAuth connection for a different user"
        )

    try:
        return AuthService.create_oauth_connection(connection.model_dump())
    except Exception as e:
        handle_api_exception(e, "Failed to save OAuth connection", logger)


@router.get("/oauth-connections/{user_id}", response_model=List[OAuthConnectionResponse])
async def get_user_connections(
    user_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Get all OAuth connections for a user.

    Requires: Authorization header with user's Supabase JWT
    Can only fetch connections for the authenticated user.
    """
    # Validate user_id matches JWT
    if user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access OAuth connections for a different user"
        )

    try:
        return AuthService.get_user_connections(user_id)
    except Exception as e:
        handle_api_exception(e, "Failed to fetch connections", logger)


@router.delete("/oauth-connections/{connection_id}", response_model=MessageResponse)
async def revoke_oauth_connection(
    connection_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Revoke/deactivate an OAuth connection.

    Requires: Authorization header with user's Supabase JWT
    Can only revoke connections owned by the authenticated user.
    """
    try:
        revoked = AuthService.revoke_connection(connection_id, current_user_id)

        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found or not owned by you"
            )

        await _best_effort_revoke_ext_connection_source(
            get_service_role_client(),
            connection_id,
            current_user_id,
        )

        return {
            "message": "Connection revoked successfully"
        }
    except Exception as e:
        handle_api_exception(e, "Failed to revoke connection", logger)


class CompleteOAuthRequest(BaseModel):
    user_id: str
    email: EmailStr
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: str = "google"
    provider_user_id: str
    # Either access_token OR server_auth_code must be provided
    # - Web app provides access_token directly (from Supabase OAuth)
    # - iOS app provides server_auth_code (exchanged by backend)
    access_token: Optional[str] = None
    server_auth_code: Optional[str] = None  # For iOS: exchanged for tokens by backend
    code_verifier: Optional[str] = None  # PKCE verifier for Microsoft iOS flow
    refresh_token: Optional[str] = None
    token_expires_at: Optional[str] = None
    scopes: List[str] = []
    metadata: Optional[dict] = None


@router.post("/complete-oauth", response_model=CompleteOAuthResponse)
@limiter.limit("5/minute;50/day")
async def complete_oauth_flow(
    request: Request,
    response: Response,
    body: CompleteOAuthRequest,
    user_jwt: Annotated[str, Depends(get_current_user_jwt)],
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    current_user_email: Annotated[str, Depends(get_current_user_email)],
):
    """
    Complete OAuth flow - creates user and stores connection in one call.
    This is a convenience endpoint for the OAuth callback.

    Supports two modes:
    1. Web app: Provides access_token directly (from Supabase OAuth)
    2. iOS app: Provides server_auth_code (exchanged by backend for tokens)

    Requires: Authorization header with user's Supabase JWT
    User ID in request must match the authenticated user.
    """
    # Validate user_id matches JWT
    if body.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot complete OAuth flow for a different user"
        )

    # Validate email matches JWT claim to prevent spoofed profile rows
    if body.email and str(body.email).strip().lower() != current_user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot complete OAuth flow with a different email"
        )

    # Validate that at least one auth method is provided
    if not body.access_token and not body.server_auth_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either access_token or server_auth_code must be provided"
        )

    try:
        logger.info("🚀 === COMPLETE OAUTH FLOW START ===")
        logger.info(f"📧 User ID: {body.user_id}")
        logger.info(f"📧 Email: {body.email}")
        logger.info(f"👤 Name: {body.name}")
        logger.info(f"🔗 Provider: {body.provider}")
        logger.info(f"🔑 Has access token: {bool(body.access_token)}")
        logger.info(f"📱 Has server auth code: {bool(body.server_auth_code)}")
        logger.info(f"🔄 Has refresh token: {bool(body.refresh_token)}")
        logger.info(f"🎫 Has Supabase JWT: {bool(user_jwt)}")

        if body.server_auth_code:
            logger.info("📱 iOS flow detected - will exchange server_auth_code for tokens")

        result = await AuthService.complete_oauth_flow(body.model_dump(), user_jwt)

        logger.info("✅ OAuth flow completed successfully")
        logger.info("🏁 === COMPLETE OAUTH FLOW END ===")

        return result
    except ValueError as e:
        # Token exchange errors
        logger.error(f"❌ Token exchange error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        handle_api_exception(e, "Failed to complete OAuth flow", logger)


@router.post("/post-signup", response_model=PostSignupResponse)
async def post_signup_endpoint(
    current_user_id: Annotated[str, Depends(get_current_user_id)],
    current_user_email: Annotated[str, Depends(get_current_user_email)],
):
    """
    Resolve pending workspace invitations after authentication bootstrap.

    Called idempotently on client bootstrap so OAuth and non-OAuth sign-ins
    both materialize invitation notifications for existing pending invites.
    """
    try:
        return await resolve_post_signup_pending_invitations(current_user_id, current_user_email)
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to resolve post-signup invitations", logger)


# ============== Multi-Account Endpoints ==============

MAX_EMAIL_ACCOUNTS = 5


@router.get("/email-accounts", response_model=EmailAccountsListResponse)
async def list_email_accounts(
    current_user_id: str = Depends(get_current_user_id),
    user_jwt: str = Depends(get_current_user_jwt)
):
    """
    Get all connected email accounts for the current user.

    Returns list of accounts with id, email, name, avatar, is_primary, order.
    Accounts are sorted by account_order.
    """
    try:
        accounts = AuthService.get_email_accounts(current_user_id, user_jwt)
        return {"accounts": accounts}
    except Exception as e:
        handle_api_exception(e, "Failed to list email accounts", logger)


@router.post("/email-accounts/verify", response_model=EmailAccountsListResponse)
async def verify_email_accounts(
    current_user_id: str = Depends(get_current_user_id),
):
    service_supabase = get_service_role_client()
    result = service_supabase.table("ext_connections")\
        .select("*")\
        .eq("user_id", current_user_id)\
        .in_("provider", ["google", "microsoft"])\
        .execute()

    accounts = []
    for row in result.data or []:
        health = await _verify_and_persist_ext_connection(service_supabase, row)
        metadata = row.get("metadata") or {}
        accounts.append({
            "id": row["id"],
            "provider": row.get("provider", "google"),
            "provider_email": row.get("provider_email"),
            "provider_name": metadata.get("full_name") or metadata.get("name"),
            "provider_avatar": metadata.get("picture") or metadata.get("avatar_url"),
            "is_primary": row.get("is_primary", False),
            "account_order": row.get("account_order", 0),
            "is_active": row.get("is_active", True),
            "verification_status": health.status,
            "last_verified_at": health.last_verified_at,
            "error_reason": health.error_reason,
            "scopes": health.scopes or row.get("scopes") or [],
            "external_account_id": row.get("external_account_id"),
            "unverified": health.unverified,
        })
    return {"accounts": sorted(accounts, key=lambda account: account.get("account_order") or 0)}


@router.get("/email-accounts/{account_id}/health", response_model=ConnectionHealthResponse)
async def get_email_account_health(
    account_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    service_supabase = get_service_role_client()
    row = _select_ext_connection(service_supabase, account_id, current_user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return (await _verify_and_persist_ext_connection(service_supabase, row)).to_dict()


@router.post("/email-accounts/{account_id}/reconnect", response_model=ReconnectResponse)
async def reconnect_email_account(
    account_id: str,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
):
    service_supabase = get_service_role_client()
    row = _select_ext_connection(service_supabase, account_id, current_user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    provider = validate_provider(str(row.get("provider") or ""))
    if provider == "github":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email account provider is invalid")

    external_account_id = row.get("external_account_id")
    if external_account_id:
        refresh = await refresh_connected_account(str(external_account_id))
        if refresh.get("redirect_url"):
            return refresh
        if refresh.get("status") == "connected":
            health = await _verify_and_persist_ext_connection(service_supabase, row)
            return {"status": health.status}

    frontend_origin = resolve_frontend_origin(request.headers.get("origin"))
    redirect_to = normalize_redirect_to(request.headers.get("referer"), frontend_origin)
    state = sign_login_state(
        provider=provider,
        redirect_to=redirect_to,
        composio_user_id=current_user_id,
        flow="composio-reconnect",
        connection_id=account_id,
    )
    callback_query = urlencode({
        "flow": "composio-reconnect",
        "provider": provider,
        "state": state,
    })
    callback_url = f"{frontend_origin}/oauth/callback?{callback_query}"
    link = await create_connect_link(provider=provider, user_id=current_user_id, callback_url=callback_url)
    redirect_url = link.get("redirect_url")
    if not isinstance(redirect_url, str) or not redirect_url:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Composio did not return a redirect URL")
    return {"redirect_url": redirect_url, "status": "pending"}


@router.post("/email-accounts/complete-reconnect", response_model=ConnectionHealthResponse)
async def complete_email_account_reconnect(
    body: CompleteReconnectRequest,
    current_user_id: str = Depends(get_current_user_id),
):
    if body.status and body.status != "success":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Composio reconnect failed")
    provider = validate_provider(body.provider)
    if provider == "github":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email account provider is invalid")

    state_payload = verify_login_state(body.state)
    if state_payload.get("flow") != "composio-reconnect":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reconnect state")
    if state_payload.get("provider") != provider or state_payload.get("composio_user_id") != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reconnect state does not match user")
    account_id = str(state_payload.get("connection_id") or "")
    if not account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reconnect state is missing account")
    if not body.connected_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Composio connected account ID")

    service_supabase = get_service_role_client()
    row = _select_ext_connection(service_supabase, account_id, current_user_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    service_supabase.table("ext_connections")\
        .update({
            "external_account_id": body.connected_account_id,
            "is_active": True,
            "verification_status": "pending",
            "revoked_at": None,
        })\
        .eq("id", account_id)\
        .execute()
    row["external_account_id"] = body.connected_account_id
    row["is_active"] = True
    return (await _verify_and_persist_ext_connection(service_supabase, row)).to_dict()


@router.post("/email-accounts", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
async def add_email_account(
    request: AddEmailAccountRequest,
    current_user_id: str = Depends(get_current_user_id),
    user_jwt: str = Depends(get_current_user_jwt)
):
    """
    Add a secondary email account via OAuth.

    - Validates max 5 accounts limit
    - Prevents duplicate accounts
    - Sets up Gmail watch for new account
    - Does NOT create new user (just adds ext_connection)
    """
    # Validate that at least one auth method is provided
    if not request.access_token and not request.server_auth_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either access_token or server_auth_code must be provided"
        )

    try:
        # Check account limit
        existing_accounts = AuthService.get_email_accounts(current_user_id, user_jwt)
        if len(existing_accounts) >= MAX_EMAIL_ACCOUNTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum of {MAX_EMAIL_ACCOUNTS} email accounts allowed"
            )

        # Check for duplicate (only if email is provided - auth code flow checks later)
        if request.provider_email:
            for account in existing_accounts:
                if account['provider_email'].lower() == request.provider_email.lower():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This email account is already connected"
                    )

        # Add the account
        result = await AuthService.add_email_account(
            user_id=current_user_id,
            user_jwt=user_jwt,
            account_data=request.model_dump(),
            account_order=len(existing_accounts)  # Add at end
        )

        return result["account"]

    except ValueError as e:
        # Token exchange or validation errors
        logger.error(f"❌ Validation error adding email account: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        handle_api_exception(e, "Failed to add email account", logger)


@router.delete("/email-accounts/{account_id}", response_model=MessageResponse)
async def remove_email_account(
    account_id: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Remove a secondary email account.

    - Validates account belongs to user
    - Prevents removal of primary account (400 error)
    - Hard deletes all emails for the account
    - Stops Gmail watch
    """
    try:
        await _best_effort_revoke_ext_connection_source(
            get_service_role_client(),
            account_id,
            current_user_id,
        )
        success = AuthService.remove_email_account(
            account_id=account_id,
            user_id=current_user_id
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found or not owned by you"
            )

        return {"message": "Email account removed successfully"}

    except ValueError as e:
        # Primary account removal attempt
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        handle_api_exception(e, "Failed to remove email account", logger)


@router.patch("/email-accounts/{account_id}", response_model=MessageResponse)
async def update_email_account(
    account_id: str,
    request: UpdateEmailAccountRequest,
    current_user_id: str = Depends(get_current_user_id),
    user_jwt: str = Depends(get_current_user_jwt)
):
    """
    Update account display order.
    """
    try:
        result = AuthService.update_email_account(
            account_id=account_id,
            user_id=current_user_id,
            user_jwt=user_jwt,
            update_data={'account_order': request.account_order}
        )

        if not result.get('success'):
            error = result.get('error', 'Failed to update account')
            if 'not found' in error.lower():
                status_code = status.HTTP_404_NOT_FOUND
            elif 'no valid fields' in error.lower():
                status_code = status.HTTP_400_BAD_REQUEST
            else:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            raise HTTPException(status_code=status_code, detail=error)

        return {"message": "Email account updated successfully"}

    except Exception as e:
        handle_api_exception(e, "Failed to update email account", logger)
