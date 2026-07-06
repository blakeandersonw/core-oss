"""Composio Connect Link helpers for Google/Microsoft auth."""
from __future__ import annotations

import base64
import hashlib
import hmac
import asyncio
import json
import secrets
import time
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status

from api.config import settings


ComposioProvider = Literal["google", "microsoft", "github"]

_STATE_TTL_SECONDS = 10 * 60
_PROFILE_TOOLS: Dict[ComposioProvider, str] = {
    "google": "GMAIL_GET_PROFILE",
    "microsoft": "OUTLOOK_GET_PROFILE",
}
_EMAIL_KEYS = {
    "email",
    "email_address",
    "emailaddress",
    "emailAddress",
    "mail",
    "userPrincipalName",
    "user_principal_name",
    "preferred_username",
}
_NAME_KEYS = {"name", "displayName", "display_name", "full_name"}
_AVATAR_KEYS = {"picture", "avatar_url", "avatarUrl", "photo", "image"}


def validate_provider(provider: str) -> ComposioProvider:
    if provider not in ("google", "microsoft", "github"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be google, microsoft, or github",
        )
    return provider  # type: ignore[return-value]


def _auth_config_id(provider: ComposioProvider) -> str:
    if provider == "google":
        return settings.composio_google_auth_config_id.strip()
    if provider == "microsoft":
        return settings.composio_microsoft_auth_config_id.strip()
    return settings.composio_github_auth_config_id.strip()


def ensure_composio_configured(provider: ComposioProvider) -> None:
    if not settings.composio_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Composio auth is not configured. Set COMPOSIO_API_KEY.",
        )
    if not _auth_config_id(provider):
        env_name_by_provider = {
            "google": "COMPOSIO_GOOGLE_AUTH_CONFIG_ID",
            "microsoft": "COMPOSIO_MICROSOFT_AUTH_CONFIG_ID",
            "github": "COMPOSIO_GITHUB_AUTH_CONFIG_ID",
        }
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Composio auth is not configured. Set {env_name_by_provider[provider]}.",
        )


def _state_secret() -> bytes:
    secret = (
        settings.supabase_jwt_secret
        or settings.supabase_service_role_key
        or settings.composio_api_key
    )
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No server secret configured for Composio auth state",
        )
    return secret.encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def sign_login_state(
    *,
    provider: ComposioProvider,
    redirect_to: str,
    composio_user_id: str,
    flow: str = "composio-login",
    connection_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    payload = {
        "provider": provider,
        "redirect_to": redirect_to,
        "composio_user_id": composio_user_id,
        "flow": flow,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    if connection_id:
        payload["connection_id"] = connection_id
    if workspace_id:
        payload["workspace_id"] = workspace_id
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _b64url_encode(payload_json)
    signature = hmac.new(
        _state_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_b64url_encode(signature)}"


def verify_login_state(token: str) -> Dict[str, Any]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Composio auth state",
        ) from exc

    expected_signature = hmac.new(
        _state_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Composio auth state",
        )

    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Composio auth state",
        ) from exc

    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Composio auth state expired. Please try again.",
        )
    validate_provider(str(payload.get("provider") or ""))
    if not payload.get("composio_user_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Composio auth state",
        )
    return payload


def allowed_frontend_origins() -> set[str]:
    origins = {origin.rstrip("/") for origin in settings.get_allowed_origins}
    if settings.frontend_url:
        parsed = urlparse(settings.frontend_url)
        if parsed.scheme and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return origins


def resolve_frontend_origin(origin_header: Optional[str]) -> str:
    allowed = allowed_frontend_origins()
    if origin_header:
        parsed = urlparse(origin_header)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if origin in allowed:
            return origin

    parsed = urlparse(settings.frontend_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:5173"


def normalize_redirect_to(redirect_to: Optional[str], frontend_origin: str) -> str:
    if not redirect_to:
        return frontend_origin

    parsed = urlparse(redirect_to)
    if not parsed.scheme and not parsed.netloc:
        path = redirect_to if redirect_to.startswith("/") else f"/{redirect_to}"
        return f"{frontend_origin}{path}"

    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin in allowed_frontend_origins():
        return redirect_to
    return frontend_origin


def make_login_composio_user_id() -> str:
    return f"core-login-{secrets.token_urlsafe(24)}"


def _composio_base_url() -> str:
    return settings.composio_base_url.rstrip("/")


def _composio_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": settings.composio_api_key,
    }


def _extract_error_message(data: Any) -> str:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("slug") or error.get("suggested_fix")
            if message:
                return str(message)
        if data.get("message"):
            return str(data["message"])
        if data.get("detail"):
            return str(data["detail"])
    return "Composio request failed"


async def _request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{_composio_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=_composio_headers(),
                json=json_body,
                params=params,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Composio request failed: {exc}",
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text}

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_extract_error_message(data),
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected Composio response",
        )
    return data


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


async def _request_with_retry(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 2,
    allow_404: bool = False,
) -> Dict[str, Any]:
    """Composio request wrapper for non-interactive verify/revoke paths."""
    if not settings.composio_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Composio auth is not configured. Set COMPOSIO_API_KEY.",
        )

    url = f"{_composio_base_url()}{path}"
    last_transport_error: Optional[httpx.HTTPError] = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers=_composio_headers(),
                    json=json_body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            last_transport_error = exc
            if attempt < retries:
                await asyncio.sleep(0.2 * (2 ** attempt))
                continue
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Composio request failed: {exc}",
            ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text}

        if response.status_code == 404 and allow_404:
            return {}

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < retries:
            await asyncio.sleep(0.2 * (2 ** attempt))
            continue

        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_extract_error_message(data),
            )

        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Composio response",
            )
        return data

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Composio request failed: {last_transport_error or 'retry budget exhausted'}",
    )


_COMPOSIO_STATUS_MAP = {
    "ACTIVE": "connected",
    "INITIATED": "pending",
    "INITIALIZING": "pending",
    "EXPIRED": "expired",
    "FAILED": "error",
    "INACTIVE": "disconnected",
}


def map_composio_status(raw: Any) -> str:
    """Map Composio's status enum to the app's shared connection vocabulary."""
    return _COMPOSIO_STATUS_MAP.get(str(raw or "").strip().upper(), "unknown")


def _coerce_scope_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.replace(",", " ")
        return [part.strip() for part in normalized.split() if part.strip()]
    if isinstance(value, list):
        scopes: List[str] = []
        for item in value:
            scopes.extend(_coerce_scope_values(item))
        return scopes
    if isinstance(value, dict):
        scopes: List[str] = []
        for nested in value.values():
            scopes.extend(_coerce_scope_values(nested))
        return scopes
    return []


def _nested_dict(value: Any, *keys: str) -> Dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def extract_granted_scopes(account: Dict[str, Any]) -> List[str]:
    """Extract granted/requested scopes from known Composio v3.1 locations."""
    state_val = _nested_dict(account, "state", "val")
    raw_scopes: List[Any] = [
        account.get("requested_scopes"),
        account.get("requested_user_scopes"),
        account.get("scopes"),
        state_val.get("requested_scopes"),
        state_val.get("requested_user_scopes"),
        state_val.get("scopes"),
    ]

    deduped: List[str] = []
    seen: set[str] = set()
    for raw in raw_scopes:
        for scope in _coerce_scope_values(raw):
            if scope not in seen:
                seen.add(scope)
                deduped.append(scope)
    return deduped


def extract_external_account_id(account: Dict[str, Any]) -> Optional[str]:
    """Extract the provider account ID from Composio's preferred and legacy fields."""
    state_val = _nested_dict(account, "state", "val")
    for value in (
        state_val.get("account_id"),
        account.get("account_id"),
        account.get("user_id"),
        account.get("external_account_id"),
        account.get("connected_account_id"),
        account.get("id"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_status_reason(account: Dict[str, Any]) -> Optional[str]:
    state_val = _nested_dict(account, "state", "val")
    for value in (
        account.get("status_reason"),
        account.get("reason"),
        state_val.get("status_reason"),
        state_val.get("reason"),
        _extract_error_message(account) if account.get("error") else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def create_connect_link(
    *,
    provider: ComposioProvider,
    user_id: str,
    callback_url: str,
) -> Dict[str, Any]:
    ensure_composio_configured(provider)
    return await _request(
        "POST",
        "/connected_accounts/link",
        json_body={
            "auth_config_id": _auth_config_id(provider),
            "user_id": user_id,
            "callback_url": callback_url,
        },
    )


async def get_connected_account(connected_account_id: str) -> Dict[str, Any]:
    return await _request("GET", f"/connected_accounts/{connected_account_id}")


async def get_connected_account_status(connected_account_id: str) -> Dict[str, Any]:
    account = await _request_with_retry("GET", f"/connected_accounts/{connected_account_id}")
    return {
        "status": map_composio_status(account.get("status")),
        "raw_status": account.get("status"),
        "status_reason": extract_status_reason(account),
        "scopes": extract_granted_scopes(account),
        "external_account_id": extract_external_account_id(account),
        "account": account,
    }


async def list_connected_accounts_for_user(
    user_id: str,
    *,
    limit: int = 100,
    cursor: Optional[str] = None,
    retry: bool = True,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"user_ids[]": user_id, "limit": limit}
    if cursor:
        params["cursor"] = cursor
    request = _request_with_retry if retry else _request
    return await request("GET", "/connected_accounts", params=params)


async def revoke_connected_account(connected_account_id: str, *, hard: bool = True) -> Dict[str, Any]:
    if hard:
        return await _request_with_retry(
            "DELETE",
            f"/connected_accounts/{connected_account_id}",
            allow_404=True,
        )
    return await _request_with_retry(
        "PATCH",
        f"/connected_accounts/{connected_account_id}/status",
        json_body={"status": "INACTIVE"},
        allow_404=True,
    )


async def refresh_connected_account(connected_account_id: str) -> Dict[str, Any]:
    data = await _request_with_retry("POST", f"/connected_accounts/{connected_account_id}/refresh")
    redirect_url = (
        data.get("redirect_url")
        or data.get("redirectUrl")
        or _nested_dict(data, "data").get("redirect_url")
        or _nested_dict(data, "data").get("redirectUrl")
    )
    return {
        "redirect_url": redirect_url if isinstance(redirect_url, str) else None,
        "status": map_composio_status(data.get("status") or _nested_dict(data, "data").get("status")),
        "raw": data,
    }


async def execute_profile_tool(
    *,
    provider: ComposioProvider,
    user_id: str,
    connected_account_id: str,
) -> Dict[str, Any]:
    tool_slug = _PROFILE_TOOLS[provider]
    return await _request(
        "POST",
        f"/tools/execute/{tool_slug}",
        json_body={
            "user_id": user_id,
            "connected_account_id": connected_account_id,
            "version": "latest",
            "arguments": {},
        },
    )


def _find_string(value: Any, keys: set[str]) -> Optional[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in keys and isinstance(nested, str) and nested.strip():
                return nested.strip()
        for nested in value.values():
            found = _find_string(nested, keys)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_string(nested, keys)
            if found:
                return found
    return None


async def get_connected_account_profile(
    *,
    provider: ComposioProvider,
    user_id: str,
    connected_account_id: str,
) -> Dict[str, Optional[str]]:
    account = await get_connected_account(connected_account_id)
    user_accounts = await list_connected_accounts_for_user(user_id, limit=100, retry=False)
    items = user_accounts.get("items")
    if not isinstance(items, list):
        items = []
    if not any(isinstance(item, dict) and item.get("id") == connected_account_id for item in items):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Composio connected account does not match auth state",
        )

    profile_result: Dict[str, Any] = {}
    try:
        profile_result = await execute_profile_tool(
            provider=provider,
            user_id=user_id,
            connected_account_id=connected_account_id,
        )
    except HTTPException:
        # Account details often include enough profile data. Fall back to that
        # so a profile tool schema change does not break sign-in outright.
        profile_result = {}

    email = _find_string(profile_result, _EMAIL_KEYS) or _find_string(account, _EMAIL_KEYS)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine the email address for this Composio account",
        )

    return {
        "email": email.lower(),
        "provider_account_id": extract_external_account_id(account),
        "name": _find_string(profile_result, _NAME_KEYS) or _find_string(account, _NAME_KEYS),
        "avatar_url": _find_string(profile_result, _AVATAR_KEYS) or _find_string(account, _AVATAR_KEYS),
    }
