"""
State service - CRUD operations for project board states/columns.

Uses async Supabase client for non-blocking I/O.
"""
from typing import Dict, Any, List, Optional
import logging
from lib.supabase_client import get_authenticated_async_client
from api.services.projects.access import (
    get_state_context,
    require_board_capability,
)

logger = logging.getLogger(__name__)


async def get_states(
    user_jwt: str,
    board_id: str,
) -> List[Dict[str, Any]]:
    """
    Get all states for a board, ordered by position.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID

    Returns:
        List of state dicts
    """
    supabase = await get_authenticated_async_client(user_jwt)

    result = await supabase.table("project_states")\
        .select("*")\
        .eq("board_id", board_id)\
        .order("position")\
        .execute()

    return result.data or []


async def create_state(
    user_jwt: str,
    user_id: str,
    board_id: str,
    name: str,
    color: Optional[str] = None,
    is_done: bool = False,
    is_locked: bool = False,
    wip_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Create a new state in a board.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID
        name: State name
        color: Optional color (hex)
        is_done: Whether this state represents completion

    Returns:
        Created state dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=board_id,
        capability="manage_states",
    )

    # Look up board to get workspace context
    board_result = await supabase.table("project_boards")\
        .select("workspace_app_id, workspace_id")\
        .eq("id", board_id)\
        .single()\
        .execute()
    board = board_result.data

    # Get next position
    position = await _get_next_state_position(supabase, board_id)

    state_data: Dict[str, Any] = {
        "workspace_app_id": board["workspace_app_id"],
        "workspace_id": board["workspace_id"],
        "board_id": board_id,
        "name": name,
        "position": position,
        "is_done": is_done,
        "is_locked": is_locked,
    }
    if color is not None:
        state_data["color"] = color
    if wip_limit is not None:
        state_data["wip_limit"] = wip_limit

    result = await supabase.table("project_states")\
        .insert(state_data)\
        .execute()

    logger.info(f"Created state '{name}' in board {board_id}")

    return result.data[0]


async def update_state(
    user_jwt: str,
    user_id: str,
    state_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None,
    is_done: Optional[bool] = None,
    is_locked: Optional[bool] = None,
    wip_limit: Optional[int] = None,
    clear_wip_limit: bool = False,
) -> Dict[str, Any]:
    """
    Update a state's fields.

    Args:
        user_jwt: User's Supabase JWT
        state_id: State UUID
        name: New name (optional)
        color: New color (optional)
        is_done: New is_done flag (optional)

    Returns:
        Updated state dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    state = await get_state_context(supabase, state_id)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=state["board_id"],
        capability="manage_states",
    )

    updates: Dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if color is not None:
        updates["color"] = color
    if is_done is not None:
        updates["is_done"] = is_done
    if is_locked is not None:
        updates["is_locked"] = is_locked
    if wip_limit is not None:
        updates["wip_limit"] = wip_limit
    if clear_wip_limit:
        updates["wip_limit"] = None

    if not updates:
        result = await supabase.table("project_states")\
            .select("*")\
            .eq("id", state_id)\
            .single()\
            .execute()
        return result.data

    result = await supabase.table("project_states")\
        .update(updates)\
        .eq("id", state_id)\
        .execute()

    if not result.data:
        raise ValueError(f"State not found: {state_id}")

    return result.data[0]


async def delete_state(
    user_jwt: str,
    user_id: str,
    state_id: str,
) -> Dict[str, Any]:
    """
    Delete a state. Will fail if issues still reference it (RESTRICT).

    Args:
        user_jwt: User's Supabase JWT
        state_id: State UUID

    Returns:
        Status dict
    """
    supabase = await get_authenticated_async_client(user_jwt)
    state = await get_state_context(supabase, state_id)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=state["board_id"],
        capability="manage_states",
    )

    await supabase.table("project_states")\
        .delete()\
        .eq("id", state_id)\
        .execute()

    logger.info(f"Deleted state {state_id}")

    return {"status": "deleted", "state_id": state_id}


async def reorder_states(
    user_jwt: str,
    user_id: str,
    board_id: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Reorder states within a board using RPC for atomicity.

    Args:
        user_jwt: User's Supabase JWT
        board_id: Board UUID
        items: List of {"id": "uuid", "position": int}

    Returns:
        Dict with updated_count
    """
    supabase = await get_authenticated_async_client(user_jwt)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=board_id,
        capability="manage_states",
    )

    try:
        result = await supabase.rpc(
            "reorder_project_states",
            {"p_board_id": board_id, "p_items": items}
        ).execute()

        updated_count = result.data if result.data else 0

        logger.info(f"Reordered {updated_count} states in board {board_id}")

        return {
            "message": "States reordered successfully",
            "updated_count": updated_count,
        }
    except Exception as e:
        if "does not exist" in str(e).lower():
            logger.warning("RPC reorder_project_states not available, using fallback")
            return await _reorder_states_fallback(supabase, board_id, items)
        raise


async def _get_next_state_position(
    supabase: Any,
    board_id: str,
) -> int:
    """Get the next position for a new state in the board."""
    result = await supabase.table("project_states")\
        .select("position")\
        .eq("board_id", board_id)\
        .order("position", desc=True)\
        .limit(1)\
        .execute()

    if result.data:
        return result.data[0]["position"] + 1
    return 0


async def _reorder_states_fallback(
    supabase: Any,
    board_id: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fallback: update positions individually (non-atomic)."""
    import asyncio

    async def update_one(item: Dict[str, Any]) -> bool:
        result = await supabase.table("project_states")\
            .update({"position": item["position"]})\
            .eq("id", item["id"])\
            .eq("board_id", board_id)\
            .execute()
        return bool(result.data)

    results = await asyncio.gather(*[update_one(item) for item in items])
    updated_count = sum(1 for r in results if r)

    return {
        "message": "States reordered successfully",
        "updated_count": updated_count,
    }
