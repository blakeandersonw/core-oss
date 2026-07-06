"""Project issue due-date reminder processing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional

from api.config import settings
from api.services.notifications.create import NotificationType, create_notification
from lib.supabase_client import get_async_service_role_client

logger = logging.getLogger(__name__)


async def process_due_date_reminders(
    *,
    batch_size: Optional[int] = None,
    window_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Create one reminder notification per due issue and mark it processed."""
    client = await get_async_service_role_client()
    limit = batch_size or settings.due_reminder_batch_size
    hours = window_hours or settings.due_reminder_window_hours
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=hours)

    result = await client.table("project_issues")\
        .select("id, workspace_id, board_id, title, due_at")\
        .is_("due_reminder_sent_at", "null")\
        .is_("completed_at", "null")\
        .gte("due_at", now.isoformat())\
        .lte("due_at", window_end.isoformat())\
        .order("due_at")\
        .limit(limit)\
        .execute()

    issues = result.data or []
    processed = 0
    notifications_created = 0
    errors = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for issue in issues:
        try:
            assignees_result = await client.table("project_issue_assignees")\
                .select("user_id")\
                .eq("issue_id", issue["id"])\
                .execute()
            assignee_ids = [row["user_id"] for row in (assignees_result.data or []) if row.get("user_id")]

            if assignee_ids:
                created = await create_notification(
                    recipients=assignee_ids,
                    type=NotificationType.DUE_DATE_REMINDER,
                    title=f"Due soon: {issue.get('title', 'Project task')}",
                    body=issue.get("due_at"),
                    resource_type="issue",
                    resource_id=issue["id"],
                    workspace_id=issue.get("workspace_id"),
                    data={
                        "board_id": issue.get("board_id"),
                        "issue_title": issue.get("title"),
                        "due_at": issue.get("due_at"),
                    },
                )
                notifications_created += len(created)

            await client.table("project_issues")\
                .update({"due_reminder_sent_at": now_iso})\
                .eq("id", issue["id"])\
                .execute()
            processed += 1
        except Exception as e:
            errors += 1
            logger.warning("Due-date reminder failed for issue %s: %s", issue.get("id"), e)

    return {
        "processed": processed,
        "notifications_created": notifications_created,
        "errors": errors,
    }
