"""Email delivery helpers for notification rows."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks

from api.config import settings
from api.services.notifications.preferences import should_notify
from lib.resend_client import send_notification_email
from lib.supabase_client import get_async_service_role_client

logger = logging.getLogger(__name__)


def _frontend_url_for_notification(notification: Dict[str, Any]) -> str:
    frontend_base = settings.frontend_url.rstrip("/")
    workspace_id = notification.get("workspace_id")
    resource_type = notification.get("resource_type")

    if workspace_id and resource_type == "issue":
        return f"{frontend_base}/workspace/{workspace_id}/projects"
    if workspace_id:
        return f"{frontend_base}/workspace/{workspace_id}"
    return frontend_base or "http://localhost:3000"


async def _send_notification_row_email(notification: Dict[str, Any], category: str) -> None:
    if not settings.notification_emails_enabled:
        return

    user_id = notification.get("user_id")
    if not user_id:
        return

    try:
        if not await should_notify(
            user_id,
            category,
            notification.get("workspace_id"),
            channel="email_digest",
        ):
            return

        client = await get_async_service_role_client()
        user_result = await client.table("users")\
            .select("id, email, name")\
            .eq("id", user_id)\
            .maybe_single()\
            .execute()

        user = user_result.data if user_result else None
        email = user.get("email") if user else None
        if not email:
            return

        data = notification.get("data") or {}
        await send_notification_email(
            recipient_email=email,
            recipient_name=user.get("name") or email,
            title=notification.get("title") or "Core notification",
            body=notification.get("body"),
            action_url=_frontend_url_for_notification(notification),
            actor_name=data.get("actor_name"),
            category=category,
        )

        await client.table("notifications")\
            .update({"emailed_at": datetime.now(timezone.utc).isoformat()})\
            .eq("id", notification["id"])\
            .execute()
    except Exception as e:
        logger.warning("Notification email send failed for notification %s: %s", notification.get("id"), e)


async def dispatch_notification_emails(
    notifications: List[Dict[str, Any]],
    *,
    category: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    """Dispatch email delivery for already-created notification rows."""
    if not notifications:
        return

    if background_tasks is not None:
        for notification in notifications:
            background_tasks.add_task(_send_notification_row_email, notification, category)
        return

    for notification in notifications:
        await _send_notification_row_email(notification, category)
