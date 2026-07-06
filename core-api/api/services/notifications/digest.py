"""Notification digest email batching."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from api.config import settings
from api.services.notifications.create import REALTIME_EMAIL_TYPES, TYPE_TO_CATEGORY
from api.services.notifications.email import _frontend_url_for_notification
from api.services.notifications.preferences import should_notify
from lib.resend_client import send_digest_email
from lib.supabase_client import get_async_service_role_client

logger = logging.getLogger(__name__)


def _group_items_by_workspace(
    rows: List[Dict[str, Any]],
    workspace_names: Dict[str, str],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        workspace_id = row.get("workspace_id") or "unknown"
        grouped[workspace_id].append(
            {
                "title": row.get("title"),
                "body": row.get("body"),
                "action_url": _frontend_url_for_notification(row),
                "category": TYPE_TO_CATEGORY.get(row.get("type"), "general"),
                "created_at": row.get("created_at"),
            }
        )

    return [
        {
            "workspace_name": workspace_names.get(workspace_id, "Workspace"),
            "items": items,
        }
        for workspace_id, items in grouped.items()
    ]


async def process_notification_digest(batch_size: Optional[int] = None) -> Dict[str, Any]:
    """Send or dry-run notification digest emails and mark included rows."""
    client = await get_async_service_role_client()
    limit = batch_size or settings.digest_batch_size

    result = await client.table("notifications")\
        .select("*")\
        .eq("read", False)\
        .eq("archived", False)\
        .is_("emailed_at", "null")\
        .order("created_at")\
        .limit(limit)\
        .execute()

    candidates = [
        row for row in (result.data or [])
        if row.get("type") not in REALTIME_EMAIL_TYPES
    ]
    if not candidates:
        return {
            "processed": 0,
            "digests_sent": 0,
            "rows_marked": 0,
            "errors": 0,
        }

    user_ids = list({row["user_id"] for row in candidates if row.get("user_id")})
    workspace_ids = list({row["workspace_id"] for row in candidates if row.get("workspace_id")})

    users_result = await client.table("users")\
        .select("id, email, name")\
        .in_("id", user_ids)\
        .execute()
    users = {row["id"]: row for row in (users_result.data or [])}

    workspace_names: Dict[str, str] = {}
    if workspace_ids:
        workspaces_result = await client.table("workspaces")\
            .select("id, name")\
            .in_("id", workspace_ids)\
            .execute()
        workspace_names = {row["id"]: row.get("name") or "Workspace" for row in (workspaces_result.data or [])}

    rows_by_user: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        rows_by_user[row["user_id"]].append(row)

    digests_sent = 0
    rows_marked = 0
    errors = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for user_id, rows in rows_by_user.items():
        user = users.get(user_id)
        if not user or not user.get("email"):
            continue

        included: List[Dict[str, Any]] = []
        for row in rows:
            category = TYPE_TO_CATEGORY.get(row.get("type"), "general")
            if await should_notify(
                user_id,
                category,
                row.get("workspace_id"),
                channel="email_digest",
            ):
                included.append(row)

        if not included:
            continue

        try:
            if settings.notification_emails_enabled:
                await send_digest_email(
                    recipient_email=user["email"],
                    recipient_name=user.get("name") or user["email"],
                    grouped_items=_group_items_by_workspace(included, workspace_names),
                    manage_preferences_url=f"{settings.frontend_url.rstrip('/')}/settings/notifications",
                )
                digests_sent += 1

            included_ids = [row["id"] for row in included]
            await client.table("notifications")\
                .update({"emailed_at": now_iso})\
                .in_("id", included_ids)\
                .execute()
            rows_marked += len(included_ids)
        except Exception as e:
            errors += 1
            logger.warning("Notification digest failed for user %s: %s", user_id, e)

    return {
        "processed": len(candidates),
        "digests_sent": digests_sent,
        "rows_marked": rows_marked,
        "errors": errors,
    }
