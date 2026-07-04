"""
Issue service - CRUD operations for project issues/cards.

Uses async Supabase client for non-blocking I/O.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from lib.supabase_client import get_authenticated_async_client
from lib.image_proxy import generate_image_url
from api.services.projects.access import (
    enforce_state_accepts_issue,
    get_state_context,
    require_board_capability,
    require_issue_capability,
    resolve_board_capabilities,
)
from api.services.notifications.subscriptions import subscribe
from api.services.notifications.create import notify_subscribers, NotificationType
from api.services.notifications.helpers import get_actor_info

logger = logging.getLogger(__name__)


async def _enrich_issues_with_labels_and_assignees(
    supabase: Any,
    issues: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Enrich a list of issues with label_objects and assignees from junction tables."""
    if not issues:
        return issues

    issue_ids = [i["id"] for i in issues]

    # Fetch labels for all issues in one query
    labels_result = await supabase.table("project_issue_labels")\
        .select("issue_id, label_id, project_labels(*)")\
        .in_("issue_id", issue_ids)\
        .execute()

    # Fetch assignees for all issues in one query
    assignees_result = await supabase.table("project_issue_assignees")\
        .select("*")\
        .in_("issue_id", issue_ids)\
        .order("created_at")\
        .execute()

    # Build lookup maps
    labels_by_issue: Dict[str, List[Dict[str, Any]]] = {}
    for row in (labels_result.data or []):
        issue_id = row["issue_id"]
        label = row.get("project_labels")
        if label:
            labels_by_issue.setdefault(issue_id, []).append(label)

    assignees_by_issue: Dict[str, List[Dict[str, Any]]] = {}
    for row in (assignees_result.data or []):
        issue_id = row["issue_id"]
        assignees_by_issue.setdefault(issue_id, []).append(row)

    # Attach to issues
    for issue in issues:
        issue["label_objects"] = labels_by_issue.get(issue["id"], [])
        issue["assignees"] = assignees_by_issue.get(issue["id"], [])

    return issues


def _enrich_issues_with_image_urls(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate image_urls from image_r2_keys for each issue.

    The image_r2_keys array is stored in the database, and we generate fresh
    signed proxy URLs on each fetch to avoid expiration issues.
    """
    for issue in issues:
        r2_keys = issue.get("image_r2_keys") or []
        issue["image_urls"] = [
            generate_image_url(key, variant="preview")
            for key in r2_keys
            if key
        ]
    return issues


async def get_issues(
    user_jwt: str,
    board_id: str,
    state_id: Optional[str] = None,
    assignee_user_id: Optional[str] = None,
    include_done: bool = True,
) -> List[Dict[str, Any]]:
    """
    Get issues for a board with optional filters.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID
        state_id: Optional filter by state
        assignee_user_id: Optional filter by assignee (queries junction table)
        include_done: Whether to include completed issues (default True)

    Returns:
        List of issue dicts
    """
    supabase = await get_authenticated_async_client(user_jwt)

    # If filtering by assignee, first get matching issue IDs from junction table
    assignee_issue_ids: Optional[List[str]] = None
    if assignee_user_id:
        assignee_result = await supabase.table("project_issue_assignees")\
            .select("issue_id")\
            .eq("user_id", assignee_user_id)\
            .execute()
        assignee_issue_ids = [row["issue_id"] for row in (assignee_result.data or [])]
        if not assignee_issue_ids:
            return []

    query = supabase.table("project_issues")\
        .select("*")\
        .eq("board_id", board_id)

    if state_id:
        query = query.eq("state_id", state_id)

    if assignee_issue_ids is not None:
        query = query.in_("id", assignee_issue_ids)

    if not include_done:
        query = query.is_("completed_at", "null")

    result = await query.order("position").execute()

    issues = result.data or []
    issues = await _enrich_issues_with_labels_and_assignees(supabase, issues)
    return _enrich_issues_with_image_urls(issues)


async def get_issue_by_id(
    user_jwt: str,
    issue_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a single issue by ID.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID

    Returns:
        Issue dict or None
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_issues")\
        .select("*")\
        .eq("id", issue_id)\
        .maybe_single()\
        .execute()

    if not result.data:
        return None

    enriched = await _enrich_issues_with_labels_and_assignees(supabase, [result.data])
    enriched = _enrich_issues_with_image_urls(enriched)
    return enriched[0]


async def create_issue(
    user_id: str,
    user_jwt: str,
    board_id: str,
    state_id: str,
    title: str,
    description: Optional[str] = None,
    priority: int = 0,
    due_at: Optional[datetime] = None,
    issue_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    target_due_at: Optional[datetime] = None,
    complexity: Optional[int] = None,
    image_r2_keys: Optional[List[str]] = None,
    label_ids: Optional[List[str]] = None,
    assignee_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a new issue with auto-allocated number.

    Args:
        user_id: Creator's user ID
        user_jwt: User's Supabase JWT
        board_id: Board UUID
        state_id: Initial state UUID
        title: Issue title
        description: Optional description
        priority: Priority level 0-4 (0=none, 1=urgent, 4=low)
        due_at: Optional due date
        image_r2_keys: Optional list of R2 keys for issue images
        label_ids: Optional list of label UUIDs
        assignee_ids: Optional list of assignee user UUIDs

    Returns:
        Created issue dict with label_objects, assignees, and image_urls
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=board_id,
        capability="create_issue",
    )
    target_state = await enforce_state_accepts_issue(
        supabase,
        user_id=user_id,
        target_state_id=state_id,
    )
    if target_state["board_id"] != board_id:
        raise ValueError("Target state does not belong to the board")

    # Allocate issue number atomically
    number_result = await supabase.rpc(
        "allocate_project_issue_number",
        {"p_board_id": board_id}
    ).execute()
    issue_number = number_result.data

    # Look up board context
    board_result = await supabase.table("project_boards")\
        .select("workspace_app_id, workspace_id")\
        .eq("id", board_id)\
        .single()\
        .execute()
    board = board_result.data

    # Get next position in the target state
    position = await _get_next_issue_position(supabase, state_id)

    issue_data: Dict[str, Any] = {
        "workspace_app_id": board["workspace_app_id"],
        "workspace_id": board["workspace_id"],
        "board_id": board_id,
        "state_id": state_id,
        "number": issue_number,
        "title": title,
        "priority": priority,
        "position": position,
        "created_by": user_id,
    }
    if description is not None:
        issue_data["description"] = description
    if due_at is not None:
        issue_data["due_at"] = due_at.isoformat()
    if issue_type is not None:
        issue_data["type"] = issue_type
    if tags is not None:
        issue_data["tags"] = [tag.strip() for tag in tags if tag and tag.strip()]
    if target_due_at is not None:
        issue_data["target_due_at"] = target_due_at.isoformat()
    if complexity is not None:
        issue_data["complexity"] = complexity
    if image_r2_keys:
        # Filter out empty/None values
        valid_keys = [key for key in image_r2_keys if key]
        if valid_keys:
            issue_data["image_r2_keys"] = valid_keys

    result = await supabase.table("project_issues")\
        .insert(issue_data)\
        .execute()

    created_issue = result.data[0]
    issue_id = created_issue["id"]
    workspace_app_id = board["workspace_app_id"]
    workspace_id = board["workspace_id"]

    # Insert label junction rows
    if label_ids:
        label_rows = [
            {
                "workspace_app_id": workspace_app_id,
                "workspace_id": workspace_id,
                "issue_id": issue_id,
                "label_id": lid,
            }
            for lid in label_ids
        ]
        await supabase.table("project_issue_labels")\
            .insert(label_rows)\
            .execute()

    # Insert assignee junction rows
    if assignee_ids:
        assignee_rows = [
            {
                "workspace_app_id": workspace_app_id,
                "workspace_id": workspace_id,
                "issue_id": issue_id,
                "user_id": uid,
            }
            for uid in assignee_ids
        ]
        await supabase.table("project_issue_assignees")\
            .insert(assignee_rows)\
            .execute()

    logger.info(f"Created issue #{issue_number} '{title}' in board {board_id}")

    # Auto-subscribe creator to the issue
    try:
        await subscribe(user_id=user_id, resource_type="issue", resource_id=issue_id, reason="creator")
        # Also auto-subscribe any assignees and notify them
        if assignee_ids:
            actor = await get_actor_info(user_id)
            for aid in assignee_ids:
                await subscribe(user_id=aid, resource_type="issue", resource_id=issue_id, reason="assignee")
            from api.services.notifications.create import create_notification
            await create_notification(
                recipients=assignee_ids,
                type=NotificationType.TASK_ASSIGNED,
                title=f"{actor['actor_name']} assigned you to: {title}",
                resource_type="issue",
                resource_id=issue_id,
                actor_id=user_id,
                workspace_id=workspace_id,
                data={
                    "board_id": board_id,
                    "issue_title": title,
                    **actor,
                },
            )
    except Exception as e:
        logger.warning(f"Notification failed for issue create: {e}")

    # Return enriched issue
    enriched = await _enrich_issues_with_labels_and_assignees(supabase, [created_issue])
    enriched = _enrich_issues_with_image_urls(enriched)
    return enriched[0]


async def update_issue(
    user_jwt: str,
    user_id: str,
    issue_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    due_at: Optional[datetime] = None,
    clear_due_at: bool = False,
    issue_type: Optional[str] = None,
    clear_type: bool = False,
    tags: Optional[List[str]] = None,
    target_due_at: Optional[datetime] = None,
    clear_target_due_at: bool = False,
    complexity: Optional[int] = None,
    clear_complexity: bool = False,
    add_image_r2_keys: Optional[List[str]] = None,
    remove_image_r2_keys: Optional[List[str]] = None,
    image_r2_keys: Optional[List[str]] = None,
    clear_images: bool = False,
    state_id: Optional[str] = None,
    position: Optional[int] = None,
    label_ids: Optional[List[str]] = None,
    assignee_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Update an issue's fields. Supports changing state (triggers completion logic).

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        title: New title (optional)
        description: New description (optional)
        priority: New priority (optional)
        due_at: New due date (optional)
        clear_due_at: Clear the due date

        Image operations (mutually exclusive - validated in router):
        - add_image_r2_keys: Append to existing images (atomic-ish, does read-modify-write)
        - remove_image_r2_keys: Remove specific images (atomic-ish, does read-modify-write)
        - image_r2_keys: Replace entire image array
        - clear_images: Remove all images

        state_id: Move to new state (optional)
        position: New position (optional)
        label_ids: Replace all labels with these IDs (optional)
        assignee_ids: Replace all assignees with these IDs (optional)

    Returns:
        Updated issue dict with label_objects, assignees, and image_urls
    """
    supabase = await get_authenticated_async_client(user_jwt)
    issue = await require_issue_capability(
        supabase,
        user_id=user_id,
        issue_id=issue_id,
        capability="update_issue",
    )

    updates: Dict[str, Any] = {}
    if title is not None:
        updates["title"] = title
    if description is not None:
        updates["description"] = description
    if priority is not None:
        updates["priority"] = priority
    if due_at is not None:
        updates["due_at"] = due_at.isoformat()
    if clear_due_at:
        updates["due_at"] = None
    if issue_type is not None:
        updates["type"] = issue_type
    if clear_type:
        updates["type"] = None
    if tags is not None:
        updates["tags"] = [tag.strip() for tag in tags if tag and tag.strip()]
    if target_due_at is not None:
        updates["target_due_at"] = target_due_at.isoformat()
    if clear_target_due_at:
        updates["target_due_at"] = None
    if complexity is not None:
        updates["complexity"] = complexity
    if clear_complexity:
        updates["complexity"] = None

    # Handle image operations (mutually exclusive, validated in router)
    if clear_images:
        updates["image_r2_keys"] = []
    elif image_r2_keys is not None:
        # Replace all: filter out empty/None values
        updates["image_r2_keys"] = [key for key in image_r2_keys if key]
    elif add_image_r2_keys or remove_image_r2_keys:
        # Add/remove: need to fetch current images first (read-modify-write)
        # Note: Not perfectly atomic, but good enough for typical usage
        current = await supabase.table("project_issues")\
            .select("image_r2_keys")\
            .eq("id", issue_id)\
            .single()\
            .execute()
        current_keys = current.data.get("image_r2_keys") or []

        if add_image_r2_keys:
            # Append new keys, filter empty values
            new_keys = [key for key in add_image_r2_keys if key]
            current_keys = current_keys + new_keys

        if remove_image_r2_keys:
            # Remove specified keys
            keys_to_remove = set(remove_image_r2_keys)
            current_keys = [key for key in current_keys if key not in keys_to_remove]

        updates["image_r2_keys"] = current_keys

    if state_id is not None:
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=issue["board_id"],
            capability="move_issue",
        )
        await enforce_state_accepts_issue(
            supabase,
            user_id=user_id,
            target_state_id=state_id,
            source_issue_id=issue_id,
        )
        updates["state_id"] = state_id
    if position is not None:
        updates["position"] = position
    if updates:
        updates["last_edited_by"] = user_id
        updates["last_edited_at"] = datetime.utcnow().isoformat()

    has_junction_updates = label_ids is not None or assignee_ids is not None

    if not updates and not has_junction_updates:
        return await get_issue_by_id(user_jwt, issue_id)  # type: ignore

    if updates:
        result = await supabase.table("project_issues")\
            .update(updates)\
            .eq("id", issue_id)\
            .execute()

        if not result.data:
            raise ValueError(f"Issue not found: {issue_id}")

    # Sync label junction table (replace all)
    if label_ids is not None:
        # Get issue context for workspace fields
        issue_result = await supabase.table("project_issues")\
            .select("workspace_app_id, workspace_id")\
            .eq("id", issue_id)\
            .single()\
            .execute()
        issue_ctx = issue_result.data

        # Delete existing labels
        await supabase.table("project_issue_labels")\
            .delete()\
            .eq("issue_id", issue_id)\
            .execute()

        # Insert new labels
        if label_ids:
            label_rows = [
                {
                    "workspace_app_id": issue_ctx["workspace_app_id"],
                    "workspace_id": issue_ctx["workspace_id"],
                    "issue_id": issue_id,
                    "label_id": lid,
                }
                for lid in label_ids
            ]
            await supabase.table("project_issue_labels")\
                .insert(label_rows)\
                .execute()

    # Sync assignee junction table (replace all)
    if assignee_ids is not None:
        if label_ids is None:
            issue_result = await supabase.table("project_issues")\
                .select("workspace_app_id, workspace_id")\
                .eq("id", issue_id)\
                .single()\
                .execute()
            issue_ctx = issue_result.data

        # Delete existing assignees
        await supabase.table("project_issue_assignees")\
            .delete()\
            .eq("issue_id", issue_id)\
            .execute()

        # Insert new assignees
        if assignee_ids:
            assignee_rows = [
                {
                    "workspace_app_id": issue_ctx["workspace_app_id"],  # type: ignore
                    "workspace_id": issue_ctx["workspace_id"],  # type: ignore
                    "issue_id": issue_id,
                    "user_id": uid,
                }
                for uid in assignee_ids
            ]
            await supabase.table("project_issue_assignees")\
                .insert(assignee_rows)\
                .execute()

    # Return enriched issue
    return await get_issue_by_id(user_jwt, issue_id)  # type: ignore


async def delete_issue(
    user_jwt: str,
    user_id: str,
    issue_id: str,
) -> Dict[str, Any]:
    """
    Delete an issue.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID

    Returns:
        Status dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_issue_capability(
        supabase,
        user_id=user_id,
        issue_id=issue_id,
        capability="delete_issue",
    )

    await supabase.table("project_issues")\
        .delete()\
        .eq("id", issue_id)\
        .execute()

    logger.info(f"Deleted issue {issue_id}")

    return {"status": "deleted", "issue_id": issue_id}


async def move_issue(
    user_jwt: str,
    issue_id: str,
    target_state_id: str,
    position: int,
    current_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Move an issue to a new state and position using RPC for atomicity.

    Args:
        user_jwt: User's Supabase JWT
        issue_id: Issue UUID
        target_state_id: Target state UUID
        position: Target position in new state
        current_user_id: Who is performing the move (for notifications)

    Returns:
        Updated issue dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    if not current_user_id:
        raise ValueError("current_user_id is required to move issues")
    issue = await require_issue_capability(
        supabase,
        user_id=current_user_id,
        issue_id=issue_id,
        capability="move_issue",
    )
    target_state = await enforce_state_accepts_issue(
        supabase,
        user_id=current_user_id,
        target_state_id=target_state_id,
        source_issue_id=issue_id,
    )
    if target_state["board_id"] != issue["board_id"]:
        raise ValueError("Target state does not belong to the same board")

    # The move_project_issue RPC is required to keep ordering consistent.
    # A fallback update is not equivalent and can corrupt ordering under concurrency.
    await supabase.rpc(
        "move_project_issue",
        {
            "p_issue_id": issue_id,
            "p_target_state_id": target_state_id,
            "p_position": position,
        }
    ).execute()

    # Fetch and return the updated issue
    result = await supabase.table("project_issues")\
        .update({
            "last_edited_by": current_user_id,
            "last_edited_at": datetime.utcnow().isoformat(),
        })\
        .eq("id", issue_id)\
        .single()\
        .execute()

    logger.info(f"Moved issue {issue_id} to state {target_state_id} at position {position}")

    # Check if target state is a "done" state and notify subscribers
    if current_user_id:
        try:
            state_result = await supabase.table("project_states")\
                .select("is_done, name")\
                .eq("id", target_state_id)\
                .maybe_single()\
                .execute()
            if state_result.data and state_result.data.get("is_done"):
                issue_data = result.data
                actor = await get_actor_info(current_user_id)
                await notify_subscribers(
                    resource_type="issue",
                    resource_id=issue_id,
                    type=NotificationType.TASK_COMPLETED,
                    title=f"{actor['actor_name']} completed: {issue_data.get('title', 'an issue')}",
                    actor_id=current_user_id,
                    workspace_id=issue_data.get("workspace_id"),
                    data={
                        "board_id": issue_data.get("board_id"),
                        "issue_title": issue_data.get("title"),
                        "state_name": state_result.data.get("name"),
                        **actor,
                    },
                )
        except Exception as e:
            logger.warning(f"Notification failed for issue move: {e}")

    return result.data


async def reorder_issues(
    user_jwt: str,
    user_id: str,
    state_id: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Reorder issues within a state using RPC for atomicity.

    Args:
        user_jwt: User's Supabase JWT
        state_id: State UUID
        items: List of {"id": "uuid", "position": int}

    Returns:
        Dict with updated_count
    """
    supabase = await get_authenticated_async_client(user_jwt)
    state_context = await get_state_context(supabase, state_id)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=state_context["board_id"],
        capability="move_issue",
    )
    capabilities = await resolve_board_capabilities(
        supabase,
        user_id=user_id,
        board_id=state_context["board_id"],
    )
    if state_context.get("is_locked") and not capabilities.get("manage_board", False):
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This column is locked")

    try:
        result = await supabase.rpc(
            "reorder_project_issues",
            {"p_state_id": state_id, "p_items": items}
        ).execute()

        updated_count = result.data if result.data else 0

        logger.info(f"Reordered {updated_count} issues in state {state_id}")

        return {
            "message": "Issues reordered successfully",
            "updated_count": updated_count,
        }
    except Exception as e:
        if "does not exist" in str(e).lower():
            logger.warning("RPC reorder_project_issues not available, using fallback")
            return await _reorder_issues_fallback(supabase, state_id, items)
        raise


async def _get_next_issue_position(
    supabase: Any,
    state_id: str,
) -> int:
    """Get the next position for a new issue in the state."""
    result = await supabase.table("project_issues")\
        .select("position")\
        .eq("state_id", state_id)\
        .order("position", desc=True)\
        .limit(1)\
        .execute()

    if result.data:
        return result.data[0]["position"] + 1
    return 0


async def _reorder_issues_fallback(
    supabase: Any,
    state_id: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fallback: update positions individually (non-atomic)."""
    import asyncio

    async def update_one(item: Dict[str, Any]) -> bool:
        result = await supabase.table("project_issues")\
            .update({"position": item["position"]})\
            .eq("id", item["id"])\
            .eq("state_id", state_id)\
            .execute()
        return bool(result.data)

    results = await asyncio.gather(*[update_one(item) for item in items])
    updated_count = sum(1 for r in results if r)

    return {
        "message": "Issues reordered successfully",
        "updated_count": updated_count,
    }
