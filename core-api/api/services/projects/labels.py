"""
Label service - CRUD operations for project board labels and issue-label assignments.

Uses async Supabase client for non-blocking I/O.
"""
from typing import Dict, Any, List, Optional
import logging
from lib.supabase_client import get_authenticated_async_client
from api.services.projects.access import enforce_issue_not_locked, get_issue_context

logger = logging.getLogger(__name__)


async def get_labels(
    user_jwt: str,
    board_id: str,
) -> List[Dict[str, Any]]:
    """
    Get all labels for a board, ordered by name.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID

    Returns:
        List of label dicts
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_labels")\
        .select("*")\
        .eq("board_id", board_id)\
        .order("name")\
        .execute()

    return result.data or []


async def create_label(
    user_jwt: str,
    user_id: str,
    board_id: str,
    name: str,
    color: str = '#6B7280',
) -> Dict[str, Any]:
    """
    Create a label definition on a board.

    Args:
        user_jwt: User's Supabase JWT
        user_id: Creator's user ID
        board_id: Board UUID
        name: Label name
        color: Label color hex string

    Returns:
        Created label dict
    """
    supabase = await get_authenticated_async_client(user_jwt)

    # Look up board context
    board_result = await supabase.table("project_boards")\
        .select("workspace_app_id, workspace_id")\
        .eq("id", board_id)\
        .maybe_single()\
        .execute()
    board = board_result.data
    if not board:
        raise ValueError(f"Board not found: {board_id}")

    label_data: Dict[str, Any] = {
        "workspace_app_id": board["workspace_app_id"],
        "workspace_id": board["workspace_id"],
        "board_id": board_id,
        "name": name,
        "color": color,
        "created_by": user_id,
    }

    result = await supabase.table("project_labels")\
        .insert(label_data)\
        .execute()

    logger.info(f"Created label '{name}' on board {board_id}")
    return result.data[0]


async def update_label(
    user_jwt: str,
    label_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update a label's name and/or color.

    Args:
        user_jwt: User's Supabase JWT
        label_id: Label UUID
        name: New name (optional)
        color: New color (optional)

    Returns:
        Updated label dict
    """
    supabase = await get_authenticated_async_client(user_jwt)

    updates: Dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if color is not None:
        updates["color"] = color

    if not updates:
        result = await supabase.table("project_labels")\
            .select("*")\
            .eq("id", label_id)\
            .single()\
            .execute()
        return result.data

    result = await supabase.table("project_labels")\
        .update(updates)\
        .eq("id", label_id)\
        .execute()

    if not result.data:
        raise ValueError(f"Label not found: {label_id}")

    return result.data[0]


async def delete_label(
    user_jwt: str,
    label_id: str,
) -> Dict[str, Any]:
    """
    Delete a label. Cascades to remove from all issues.

    Args:
        user_jwt: User's Supabase JWT
        label_id: Label UUID

    Returns:
        Status dict
    """
    supabase = await get_authenticated_async_client(user_jwt)

    await supabase.table("project_labels")\
        .delete()\
        .eq("id", label_id)\
        .execute()

    logger.info(f"Deleted label {label_id}")
    return {"status": "deleted", "label_id": label_id}


async def get_issue_labels(
    user_jwt: str,
    issue_id: str,
) -> List[Dict[str, Any]]:
    """
    Get all labels attached to an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID

    Returns:
        List of label dicts (from project_labels via junction)
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_issue_labels")\
        .select("label_id, project_labels(*)")\
        .eq("issue_id", issue_id)\
        .execute()

    # Extract the nested label objects
    labels = []
    for row in (result.data or []):
        label = row.get("project_labels")
        if label:
            labels.append(label)

    return labels


async def add_label_to_issue(
    user_jwt: str,
    issue_id: str,
    label_id: str,
    current_user_id: str,
) -> Dict[str, Any]:
    """
    Add a label to an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        label_id: Label UUID

    Returns:
        Created junction row
    """
    supabase = await get_authenticated_async_client(user_jwt)

    issue = await get_issue_context(supabase, issue_id)
    await enforce_issue_not_locked(
        supabase,
        issue=issue,
        user_id=current_user_id,
        board_id=issue["board_id"],
    )

    junction_data: Dict[str, Any] = {
        "workspace_app_id": issue["workspace_app_id"],
        "workspace_id": issue["workspace_id"],
        "issue_id": issue_id,
        "label_id": label_id,
    }

    result = await supabase.table("project_issue_labels")\
        .insert(junction_data)\
        .execute()

    logger.info(f"Added label {label_id} to issue {issue_id}")
    return result.data[0]


async def remove_label_from_issue(
    user_jwt: str,
    issue_id: str,
    label_id: str,
    current_user_id: str,
) -> Dict[str, Any]:
    """
    Remove a label from an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        label_id: Label UUID

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

    await supabase.table("project_issue_labels")\
        .delete()\
        .eq("issue_id", issue_id)\
        .eq("label_id", label_id)\
        .execute()

    logger.info(f"Removed label {label_id} from issue {issue_id}")
    return {"status": "removed", "issue_id": issue_id, "label_id": label_id}
