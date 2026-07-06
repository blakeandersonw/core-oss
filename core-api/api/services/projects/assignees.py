"""
Assignee service - operations for project issue multi-assignee management.

Uses async Supabase client for non-blocking I/O.
"""
from typing import Dict, Any, List, Optional
import logging
from lib.supabase_client import get_authenticated_async_client
from api.services.notifications.subscriptions import subscribe
from api.services.notifications.create import create_notification, NotificationType
from api.services.notifications.helpers import get_actor_info
from api.services.projects.access import enforce_issue_not_locked, get_issue_context

logger = logging.getLogger(__name__)


async def get_issue_assignees(
    user_jwt: str,
    issue_id: str,
) -> List[Dict[str, Any]]:
    """
    Get all assignees for an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID

    Returns:
        List of assignee dicts with user_id and created_at
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_issue_assignees")\
        .select("*")\
        .eq("issue_id", issue_id)\
        .order("created_at")\
        .execute()

    return result.data or []


async def add_assignee(
    user_jwt: str,
    issue_id: str,
    user_id: str,
    current_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add an assignee to an issue. DB trigger enforces max 10.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        user_id: User UUID to assign
        current_user_id: Who is performing the action (for notifications)

    Returns:
        Created assignee row
    """
    supabase = await get_authenticated_async_client(user_jwt)

    issue = await get_issue_context(supabase, issue_id)
    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=current_user_id or "",
        board_id=issue["board_id"],
    )

    assignee_data: Dict[str, Any] = {
        "workspace_app_id": issue["workspace_app_id"],
        "workspace_id": issue["workspace_id"],
        "issue_id": issue_id,
        "user_id": user_id,
    }

    result = await supabase.table("project_issue_assignees")\
        .insert(assignee_data)\
        .execute()

    logger.info(f"Added assignee {user_id} to issue {issue_id}")

    # Auto-subscribe assignee and notify
    try:
        await subscribe(user_id=user_id, resource_type="issue", resource_id=issue_id, reason="assignee")

        if current_user_id and current_user_id != user_id:
            actor = await get_actor_info(current_user_id)
            await create_notification(
                recipients=[user_id],
                type=NotificationType.TASK_ASSIGNED,
                title=f"{actor['actor_name']} assigned you to: {issue['title']}",
                resource_type="issue",
                resource_id=issue_id,
                actor_id=current_user_id,
                workspace_id=issue["workspace_id"],
                data={
                    "board_id": issue["board_id"],
                    "issue_title": issue["title"],
                    **actor,
                },
            )
    except Exception as e:
        logger.warning(f"Notification failed for assignee add: {e}")

    return result.data[0]


async def remove_assignee(
    user_jwt: str,
    issue_id: str,
    user_id: str,
    current_user_id: str,
) -> Dict[str, Any]:
    """
    Remove an assignee from an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        user_id: User UUID to remove

    Returns:
        Status dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await get_issue_context(supabase, issue_id)
    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=current_user_id,
        board_id=issue["board_id"],
    )

    await supabase.table("project_issue_assignees")\
        .delete()\
        .eq("issue_id", issue_id)\
        .eq("user_id", user_id)\
        .execute()

    logger.info(f"Removed assignee {user_id} from issue {issue_id}")
    return {"status": "removed", "issue_id": issue_id, "user_id": user_id}
