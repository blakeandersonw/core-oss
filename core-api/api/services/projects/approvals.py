"""Client-facing project issue approval workflow."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException, status

from api.services.notifications.create import NotificationType, create_notification
from api.services.notifications.helpers import get_actor_info
from api.services.notifications.subscriptions import get_subscribers
from api.services.projects.access import (
    enforce_issue_not_locked,
    get_issue_context,
    require_issue_approver,
    require_issue_capability,
)
from api.services.projects.issues import get_issue_by_id
from lib.supabase_client import get_authenticated_async_client

logger = logging.getLogger(__name__)


APPROVAL_FIELDS = [
    "approval_status",
    "approval_requested_by",
    "approval_requested_at",
    "approval_note",
    "approved_by",
    "approved_at",
    "approval_decision_note",
    "approver_id",
    "approval_locked",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approval_state(issue: Dict[str, Any]) -> Dict[str, Any]:
    return {field: issue.get(field) for field in APPROVAL_FIELDS}


async def get_issue_approval_state(user_jwt: str, issue_id: str) -> Dict[str, Any]:
    issue = await get_issue_by_id(user_jwt, issue_id)
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")
    return _approval_state(issue)


async def request_issue_approval(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    approver_id: str,
    note: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await get_issue_context(supabase, issue_id)

    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=user_id,
        board_id=issue["board_id"],
    )

    if issue.get("approval_status") == "pending" and issue.get("approver_id") == approver_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is already pending")
    if approver_id == issue.get("created_by"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Creator cannot approve their own issue")

    member = await supabase.table("workspace_members")\
        .select("user_id")\
        .eq("workspace_id", issue["workspace_id"])\
        .eq("user_id", approver_id)\
        .maybe_single()\
        .execute()
    if not member.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approver must be a workspace member")

    update_data = {
        "approval_status": "pending",
        "approver_id": approver_id,
        "approval_locked": False,
        "approval_requested_by": user_id,
        "approval_requested_at": _now_iso(),
        "approval_note": note.strip() if note else None,
        "approved_by": None,
        "approved_at": None,
        "approval_decision_note": None,
        "last_edited_by": user_id,
        "last_edited_at": _now_iso(),
    }
    result = await supabase.table("project_issues")\
        .update(update_data)\
        .eq("id", issue_id)\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")

    try:
        actor = await get_actor_info(user_id)
        await create_notification(
            recipients=[approver_id],
            type=NotificationType.APPROVAL_REQUESTED,
            title=f"{actor['actor_name']} requested approval for: {issue.get('title', 'an issue')}",
            body=note.strip() if note else None,
            resource_type="issue",
            resource_id=issue_id,
            actor_id=user_id,
            workspace_id=issue.get("workspace_id"),
            data={
                "board_id": issue.get("board_id"),
                "issue_title": issue.get("title"),
                "approval_note": note.strip() if note else None,
                **actor,
            },
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.warning("Approval request notification failed for issue %s: %s", issue_id, e)

    updated = await get_issue_by_id(user_jwt, issue_id)
    return updated or result.data[0]


async def _notify_approval_decision(
    *,
    issue: Dict[str, Any],
    actor_id: str,
    issue_id: str,
    notification_type: str,
    title: str,
    note: Optional[str],
    background_tasks: Optional[BackgroundTasks] = None,
) -> None:
    subscribers = await get_subscribers("issue", issue_id)
    recipients: List[str] = [sub["user_id"] for sub in subscribers]
    requester_id = issue.get("approval_requested_by")
    if requester_id:
        recipients.append(requester_id)
    recipients = list({uid for uid in recipients if uid})
    if not recipients:
        return

    actor = await get_actor_info(actor_id)
    await create_notification(
        recipients=recipients,
        type=notification_type,
        title=title,
        body=note,
        resource_type="issue",
        resource_id=issue_id,
        actor_id=actor_id,
        workspace_id=issue.get("workspace_id"),
        data={
            "board_id": issue.get("board_id"),
            "issue_title": issue.get("title"),
            "approval_decision_note": note,
            **actor,
        },
        background_tasks=background_tasks,
    )


async def approve_issue_approval(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    note: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await get_issue_context(supabase, issue_id)
    member = await supabase.table("workspace_members")\
        .select("user_id")\
        .eq("workspace_id", issue["workspace_id"])\
        .eq("user_id", user_id)\
        .maybe_single()\
        .execute()
    if not member.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access required")

    if issue.get("approval_status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending")
    require_issue_approver(issue, user_id)

    decision_note = note.strip() if note else None
    update_data = {
        "approval_status": "approved",
        "approved_by": user_id,
        "approved_at": _now_iso(),
        "approval_decision_note": decision_note,
        "approval_locked": True,
        "last_edited_by": user_id,
        "last_edited_at": _now_iso(),
    }
    result = await supabase.table("project_issues")\
        .update(update_data)\
        .eq("id", issue_id)\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")

    try:
        actor = await get_actor_info(user_id)
        await _notify_approval_decision(
            issue=issue,
            actor_id=user_id,
            issue_id=issue_id,
            notification_type=NotificationType.APPROVAL_GRANTED,
            title=f"{actor['actor_name']} approved: {issue.get('title', 'an issue')}",
            note=decision_note,
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.warning("Approval granted notification failed for issue %s: %s", issue_id, e)

    updated = await get_issue_by_id(user_jwt, issue_id)
    return updated or result.data[0]


async def reject_issue_approval(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    note: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, Any]:
    decision_note = note.strip()
    if not decision_note:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rejection note is required")

    supabase = await get_authenticated_async_client(user_jwt)
    issue = await require_issue_capability(
        supabase,
        user_id=user_id,
        issue_id=issue_id,
        capability="request_approval",
    )
    member = await supabase.table("workspace_members")\
        .select("user_id")\
        .eq("workspace_id", issue["workspace_id"])\
        .eq("user_id", user_id)\
        .maybe_single()\
        .execute()
    if not member.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access required")

    if issue.get("approval_status") != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending")
    require_issue_approver(issue, user_id)

    update_data = {
        "approval_status": "rejected",
        "approved_by": user_id,
        "approved_at": _now_iso(),
        "approval_decision_note": decision_note,
        "approval_locked": False,
        "last_edited_by": user_id,
        "last_edited_at": _now_iso(),
    }
    result = await supabase.table("project_issues")\
        .update(update_data)\
        .eq("id", issue_id)\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")

    try:
        actor = await get_actor_info(user_id)
        await _notify_approval_decision(
            issue=issue,
            actor_id=user_id,
            issue_id=issue_id,
            notification_type=NotificationType.APPROVAL_REJECTED,
            title=f"{actor['actor_name']} requested changes on: {issue.get('title', 'an issue')}",
            note=decision_note,
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.warning("Approval rejected notification failed for issue %s: %s", issue_id, e)

    updated = await get_issue_by_id(user_jwt, issue_id)
    return updated or result.data[0]


async def unlock_issue_approval(
    *,
    user_id: str,
    user_jwt: str,
    issue_id: str,
    background_tasks: Optional[BackgroundTasks] = None,
) -> Dict[str, Any]:
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await require_issue_capability(
        supabase,
        user_id=user_id,
        issue_id=issue_id,
        capability="manage_approval",
    )
    if not issue.get("approval_locked"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Issue is not locked")

    result = await supabase.table("project_issues")\
        .update({
            "approval_locked": False,
            "last_edited_by": user_id,
            "last_edited_at": _now_iso(),
        })\
        .eq("id", issue_id)\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")

    try:
        actor = await get_actor_info(user_id)
        await _notify_approval_decision(
            issue=issue,
            actor_id=user_id,
            issue_id=issue_id,
            notification_type=NotificationType.TASK_UPDATED,
            title=f"{actor['actor_name']} unlocked: {issue.get('title', 'an issue')}",
            note=None,
            background_tasks=background_tasks,
        )
    except Exception as e:
        logger.warning("Approval unlock notification failed for issue %s: %s", issue_id, e)

    updated = await get_issue_by_id(user_jwt, issue_id)
    return updated or result.data[0]
