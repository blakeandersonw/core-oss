"""Shared connection health projection for user and workspace connectors."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.services.composio import get_connected_account_status, map_composio_status
from api.services.syncs.failure_policy import get_failed_sync_quarantine_reason


CONNECTION_STATUSES = {"connected", "disconnected", "error", "pending", "expired", "unknown"}
INACTIVE_STATUSES = {"disconnected", "error", "expired"}


@dataclass
class ConnectionHealth:
    status: str
    last_verified_at: str
    error_reason: Optional[str] = None
    scopes: Optional[List[str]] = None
    external_account_id: Optional[str] = None
    raw_status: Optional[str] = None
    unverified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_connection_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in CONNECTION_STATUSES else "unknown"


def _parse_optional_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _legacy_connection_failure_reason(row: Dict[str, Any]) -> Optional[str]:
    existing_reason = row.get("error_reason")
    if existing_reason:
        return str(existing_reason)

    provider = row.get("provider")
    failed_attempts = row.get("failed_attempts")
    token_expires_at = _parse_optional_datetime(row.get("token_expires_at"))
    if token_expires_at and token_expires_at <= datetime.now(timezone.utc) and not row.get("refresh_token"):
        return (
            "OAuth token expired and no refresh token is available; "
            "user must reconnect"
        )

    if failed_attempts:
        return get_failed_sync_quarantine_reason(
            provider=provider,
            error=row.get("last_error") or row.get("last_error_message") or "legacy connection verification failed",
            retry_count=int(failed_attempts) - 1,
        )

    return None


def health_from_composio_status(status_payload: Dict[str, Any]) -> ConnectionHealth:
    status_value = normalize_connection_status(status_payload.get("status"))
    reason = status_payload.get("status_reason")
    return ConnectionHealth(
        status=status_value,
        last_verified_at=now_iso(),
        error_reason=str(reason) if reason else None,
        scopes=list(status_payload.get("scopes") or []),
        external_account_id=status_payload.get("external_account_id"),
        raw_status=status_payload.get("raw_status"),
    )


def health_from_legacy_ext_connection(row: Dict[str, Any]) -> ConnectionHealth:
    if not row.get("is_active"):
        status_value = "disconnected"
    else:
        status_value = normalize_connection_status(row.get("verification_status"))
        if status_value == "unknown":
            status_value = "connected"

    reason = _legacy_connection_failure_reason(row)
    if reason and status_value == "connected":
        status_value = "expired" if "token expired" in reason.lower() else "error"

    return ConnectionHealth(
        status=status_value,
        last_verified_at=now_iso(),
        error_reason=str(reason) if reason else None,
        scopes=list(row.get("scopes") or []),
        external_account_id=row.get("external_account_id"),
    )


def health_from_failed_check(row: Dict[str, Any], *, table: str, error: Any) -> ConnectionHealth:
    status_field = "verification_status" if table == "ext_connections" else "status"
    status_value = normalize_connection_status(row.get(status_field))
    if status_value == "unknown" and row.get("is_active") is False:
        status_value = "disconnected"
    return ConnectionHealth(
        status=status_value or "unknown",
        last_verified_at=str(row.get("last_verified_at") or now_iso()),
        error_reason=str(row.get("error_reason") or f"Unable to verify connection: {error}"),
        scopes=list(row.get("scopes") or []),
        external_account_id=row.get("external_account_id"),
        unverified=True,
    )


def ext_connection_update_payload(health: ConnectionHealth) -> Dict[str, Any]:
    status_value = normalize_connection_status(health.status)
    payload: Dict[str, Any] = {
        "verification_status": status_value,
        "last_verified_at": health.last_verified_at,
        "error_reason": health.error_reason if status_value in {"error", "expired"} else None,
        "last_error_at": health.last_verified_at if status_value in {"error", "expired"} else None,
        "failed_attempts": 0 if status_value == "connected" else 1,
    }
    if status_value in INACTIVE_STATUSES:
        payload["is_active"] = False
    elif status_value == "connected":
        payload["is_active"] = True
    if health.scopes is not None:
        payload["scopes"] = health.scopes
    return payload


def workspace_connector_update_payload(health: ConnectionHealth) -> Dict[str, Any]:
    status_value = normalize_connection_status(health.status)
    payload: Dict[str, Any] = {
        "status": status_value,
        "last_verified_at": health.last_verified_at,
        "error_reason": health.error_reason if status_value in {"error", "expired"} else None,
        "last_error_at": health.last_verified_at if status_value in {"error", "expired"} else None,
        "failed_attempts": 0 if status_value == "connected" else 1,
    }
    if health.scopes is not None:
        payload["scopes"] = health.scopes
    return payload


async def verify_composio_backed_connection(connected_account_id: str) -> ConnectionHealth:
    return health_from_composio_status(await get_connected_account_status(connected_account_id))


__all__ = [
    "CONNECTION_STATUSES",
    "ConnectionHealth",
    "ext_connection_update_payload",
    "health_from_composio_status",
    "health_from_failed_check",
    "health_from_legacy_ext_connection",
    "map_composio_status",
    "normalize_connection_status",
    "verify_composio_backed_connection",
    "workspace_connector_update_payload",
]
