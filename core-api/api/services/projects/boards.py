"""
Board service - CRUD operations for project boards.

Uses async Supabase client for non-blocking I/O.
"""
from typing import Dict, Any, List, Optional
import logging
from fastapi import HTTPException, status
from lib.supabase_client import get_authenticated_async_client
from api.services.projects.access import require_board_capability

logger = logging.getLogger(__name__)


async def get_boards(
    user_jwt: str,
    workspace_app_id: str,
) -> List[Dict[str, Any]]:
    """
    Get all boards for a workspace app, ordered by position.

    Args:
        user_jwt: User's Supabase JWT
        workspace_app_id: Workspace app ID (projects app)

    Returns:
        List of board dicts
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_boards")\
        .select("*")\
        .eq("workspace_app_id", workspace_app_id)\
        .order("position")\
        .execute()

    return result.data or []


async def get_board_by_id(
    user_jwt: str,
    board_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a single board by ID.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID

    Returns:
        Board dict or None
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_boards")\
        .select("*")\
        .eq("id", board_id)\
        .maybe_single()\
        .execute()

    return result.data


async def create_board(
    user_id: str,
    user_jwt: str,
    workspace_app_id: str,
    name: str,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    color: Optional[str] = None,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new board with 3 default states (Backlog, In Progress, Done).

    Args:
        user_id: Creator's user ID
        user_jwt: User's Supabase JWT
        workspace_app_id: Workspace app ID (projects app)
        name: Board name
        description: Optional board description
        icon: Optional board icon (emoji)
        color: Optional board color (hex)
        key: Optional short code (e.g. "CORE")

    Returns:
        Dict with board and states data
    """
    supabase = await get_authenticated_async_client(user_jwt)

    # Look up workspace_id from workspace_app
    app_result = await supabase.table("workspace_apps")\
        .select("workspace_id")\
        .eq("id", workspace_app_id)\
        .single()\
        .execute()
    workspace_id = app_result.data["workspace_id"]
    is_admin = await supabase.rpc(
        "is_workspace_admin",
        {"p_workspace_id": workspace_id},
    ).execute()
    if is_admin.data is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace admin access required to create project boards",
        )

    # Get next position
    position = await _get_next_board_position(supabase, workspace_app_id)

    # Build board data
    board_data: Dict[str, Any] = {
        "workspace_app_id": workspace_app_id,
        "workspace_id": workspace_id,
        "name": name,
        "position": position,
        "created_by": user_id,
    }
    if description is not None:
        board_data["description"] = description
    if icon is not None:
        board_data["icon"] = icon
    if color is not None:
        board_data["color"] = color
    if key is not None:
        board_data["key"] = key

    # Insert board
    board_result = await supabase.table("project_boards")\
        .insert(board_data)\
        .execute()
    board = board_result.data[0]

    # Create default states
    default_states = [
        {"name": "To Do", "color": "#94A3B8", "position": 0, "is_done": False},
        {"name": "In Progress", "color": "#3B82F6", "position": 1, "is_done": False},
        {"name": "Done", "color": "#10B981", "position": 2, "is_done": True},
    ]

    states_data = [
        {
            "workspace_app_id": workspace_app_id,
            "workspace_id": workspace_id,
            "board_id": board["id"],
            "name": s["name"],
            "color": s["color"],
            "position": s["position"],
            "is_done": s["is_done"],
        }
        for s in default_states
    ]

    states_result = await supabase.table("project_states")\
        .insert(states_data)\
        .execute()

    logger.info(f"Created board '{name}' with 3 default states for workspace app {workspace_app_id}")

    return {
        "board": board,
        "states": states_result.data or [],
    }


async def update_board(
    user_jwt: str,
    user_id: str,
    board_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    color: Optional[str] = None,
    key: Optional[str] = None,
    default_role_capabilities: Optional[Dict[str, Any]] = None,
    enforce_column_limits: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Update a board's fields.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID
        name: New name (optional)
        description: New description (optional)
        icon: New icon (optional)
        color: New color (optional)
        key: New key (optional)

    Returns:
        Updated board dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=board_id,
        capability="manage_board",
    )

    updates: Dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if icon is not None:
        updates["icon"] = icon
    if color is not None:
        updates["color"] = color
    if key is not None:
        updates["key"] = key
    if default_role_capabilities is not None:
        updates["default_role_capabilities"] = default_role_capabilities
    if enforce_column_limits is not None:
        updates["enforce_column_limits"] = enforce_column_limits

    if not updates:
        # Nothing to update, just return current board
        return await get_board_by_id(user_jwt, board_id)  # type: ignore

    result = await supabase.table("project_boards")\
        .update(updates)\
        .eq("id", board_id)\
        .execute()

    if not result.data:
        raise ValueError(f"Board not found: {board_id}")

    return result.data[0]


async def delete_board(
    user_jwt: str,
    user_id: str,
    board_id: str,
) -> Dict[str, Any]:
    """
    Delete a board (cascades to states and issues).

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID

    Returns:
        Status dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=board_id,
        capability="manage_board",
    )

    await supabase.table("project_boards")\
        .delete()\
        .eq("id", board_id)\
        .execute()

    logger.info(f"Deleted board {board_id}")

    return {"status": "deleted", "board_id": board_id}


async def _get_next_board_position(
    supabase: Any,
    workspace_app_id: str,
) -> int:
    """Get the next position for a new board in the workspace app."""
    result = await supabase.table("project_boards")\
        .select("position")\
        .eq("workspace_app_id", workspace_app_id)\
        .order("position", desc=True)\
        .limit(1)\
        .execute()

    if result.data:
        return result.data[0]["position"] + 1
    return 0
