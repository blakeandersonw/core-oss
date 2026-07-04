"""Project board capability checks for client-facing workspaces."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, status


DEFAULT_ROLE_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "owner": {
        "create_issue": True,
        "update_issue": True,
        "move_issue": True,
        "assign_issue": True,
        "comment_issue": True,
        "delete_issue": True,
        "manage_labels": True,
        "manage_states": True,
        "manage_board": True,
        "manage_permissions": True,
    },
    "admin": {
        "create_issue": True,
        "update_issue": True,
        "move_issue": True,
        "assign_issue": True,
        "comment_issue": True,
        "delete_issue": True,
        "manage_labels": True,
        "manage_states": True,
        "manage_board": True,
        "manage_permissions": True,
    },
    "member": {
        "create_issue": True,
        "update_issue": True,
        "move_issue": True,
        "assign_issue": True,
        "comment_issue": True,
        "delete_issue": False,
        "manage_labels": False,
        "manage_states": False,
        "manage_board": False,
        "manage_permissions": False,
    },
}


def default_capabilities_for_role(role: Optional[str]) -> Dict[str, bool]:
    return dict(DEFAULT_ROLE_CAPABILITIES.get(role or "member", DEFAULT_ROLE_CAPABILITIES["member"]))


async def get_board_context(supabase: Any, board_id: str) -> Dict[str, Any]:
    result = await supabase.table("project_boards")\
        .select("id, workspace_id, workspace_app_id, default_role_capabilities, enforce_column_limits")\
        .eq("id", board_id)\
        .maybe_single()\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project board not found")
    return result.data


async def get_issue_context(supabase: Any, issue_id: str) -> Dict[str, Any]:
    result = await supabase.table("project_issues")\
        .select("id, workspace_id, workspace_app_id, board_id, state_id, created_by")\
        .eq("id", issue_id)\
        .maybe_single()\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project issue not found")
    return result.data


async def get_state_context(supabase: Any, state_id: str) -> Dict[str, Any]:
    result = await supabase.table("project_states")\
        .select("id, workspace_id, workspace_app_id, board_id, is_locked, wip_limit")\
        .eq("id", state_id)\
        .maybe_single()\
        .execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project state not found")
    return result.data


async def _workspace_role(supabase: Any, workspace_id: str, user_id: str) -> Optional[str]:
    result = await supabase.table("workspace_members")\
        .select("role")\
        .eq("workspace_id", workspace_id)\
        .eq("user_id", user_id)\
        .maybe_single()\
        .execute()
    return result.data.get("role") if result.data else None


async def resolve_board_capabilities(
    supabase: Any,
    *,
    user_id: str,
    board_id: str,
) -> Dict[str, bool]:
    board = await get_board_context(supabase, board_id)
    role = await _workspace_role(supabase, board["workspace_id"], user_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access required")

    capabilities = default_capabilities_for_role(role)
    board_defaults = board.get("default_role_capabilities") or {}
    role_defaults = board_defaults.get(role) if isinstance(board_defaults, dict) else None
    if isinstance(role_defaults, dict):
        capabilities.update({k: bool(v) for k, v in role_defaults.items()})

    preset = await supabase.table("project_board_role_presets")\
        .select("capabilities")\
        .eq("board_id", board_id)\
        .eq("role", role)\
        .maybe_single()\
        .execute()
    if preset.data and isinstance(preset.data.get("capabilities"), dict):
        capabilities.update({k: bool(v) for k, v in preset.data["capabilities"].items()})

    override = await supabase.table("project_board_member_permissions")\
        .select("capabilities")\
        .eq("board_id", board_id)\
        .eq("user_id", user_id)\
        .maybe_single()\
        .execute()
    if override.data and isinstance(override.data.get("capabilities"), dict):
        capabilities.update({k: bool(v) for k, v in override.data["capabilities"].items()})

    return capabilities


async def require_board_capability(
    supabase: Any,
    *,
    user_id: str,
    board_id: str,
    capability: str,
) -> None:
    capabilities = await resolve_board_capabilities(supabase, user_id=user_id, board_id=board_id)
    if not capabilities.get(capability, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project board permission required: {capability}",
        )


async def require_issue_capability(
    supabase: Any,
    *,
    user_id: str,
    issue_id: str,
    capability: str,
) -> Dict[str, Any]:
    issue = await get_issue_context(supabase, issue_id)
    await require_board_capability(
        supabase,
        user_id=user_id,
        board_id=issue["board_id"],
        capability=capability,
    )
    return issue


async def enforce_state_accepts_issue(
    supabase: Any,
    *,
    user_id: str,
    target_state_id: str,
    source_issue_id: Optional[str] = None,
) -> Dict[str, Any]:
    state = await get_state_context(supabase, target_state_id)
    board = await get_board_context(supabase, state["board_id"])
    capabilities = await resolve_board_capabilities(supabase, user_id=user_id, board_id=state["board_id"])
    if state.get("is_locked") and not capabilities.get("manage_board", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This column is locked")

    if board.get("enforce_column_limits") and state.get("wip_limit") is not None:
        query = supabase.table("project_issues")\
            .select("id", count="exact")\
            .eq("state_id", target_state_id)
        if source_issue_id:
            query = query.neq("id", source_issue_id)
        result = await query.execute()
        current_count = result.count or len(result.data or [])
        if current_count >= int(state["wip_limit"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Column ticket cap reached",
            )
    return state
