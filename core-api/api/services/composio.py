"""Composio Connect Link helpers for Google/Microsoft auth."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status

from api.config import settings


ComposioProvider = Literal["google", "microsoft"]

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
    if provider not in ("google", "microsoft"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be google or microsoft",
        )
    return provider  # type: ignore[return-value]


def _auth_config_id(provider: ComposioProvider) -> str:
    if provider == "google":
        return settings.composio_google_auth_config_id.strip()
    return settings.composio_microsoft_auth_config_id.strip()


def ensure_composio_configured(provider: ComposioProvider) -> None:
    if not settings.composio_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Composio auth is not configured. Set COMPOSIO_API_KEY.",
        )
    if not _auth_config_id(provider):
        env_name = (
            "COMPOSIO_GOOGLE_AUTH_CONFIG_ID"
            if provider == "google"
            else "COMPOSIO_MICROSOFT_AUTH_CONFIG_ID"
        )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Composio auth is not configured. Set {env_name}.",
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
) -> str:
    payload = {
        "provider": provider,
        "redirect_to": redirect_to,
        "composio_user_id": composio_user_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
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
    account_user_id = account.get("user_id")
    if account_user_id and account_user_id != user_id:
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
        "name": _find_string(profile_result, _NAME_KEYS) or _find_string(account, _NAME_KEYS),
        "avatar_url": _find_string(profile_result, _AVATAR_KEYS) or _find_string(account, _AVATAR_KEYS),
    }
