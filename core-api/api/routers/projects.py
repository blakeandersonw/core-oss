"""
Projects router - HTTP endpoints for kanban-style boards with states and issues
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from api.services.projects import (
    get_boards,
    get_board_by_id,
    create_board,
    update_board,
    delete_board,
    get_states,
    create_state,
    update_state,
    delete_state,
    reorder_states,
    get_issues,
    get_issue_by_id,
    create_issue,
    update_issue,
    delete_issue,
    move_issue,
    reorder_issues,
    get_labels,
    create_label,
    update_label,
    delete_label,
    add_label_to_issue,
    remove_label_from_issue,
    get_issue_assignees,
    add_assignee,
    remove_assignee,
    get_comments,
    create_comment,
    update_comment,
    delete_comment,
    add_reaction,
    remove_reaction,
    get_issue_approval_state,
    request_issue_approval,
    approve_issue_approval,
    reject_issue_approval,
    unlock_issue_approval,
    initiate_attachment_upload,
    confirm_attachment_version,
    list_issue_attachments,
    list_attachment_versions,
    get_attachment_version_url,
)
from api.dependencies import get_current_user_jwt, get_current_user_id
from api.exceptions import handle_api_exception
from lib.supabase_client import get_authenticated_async_client
from api.services.projects.access import (
    require_board_capability,
    require_issue_capability,
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _require_issue_route_capability(
    user_jwt: str,
    user_id: str,
    issue_id: str,
    capability: str,
) -> None:
    supabase = await get_authenticated_async_client(user_jwt)
    await require_issue_capability(
        supabase,
        user_id=user_id,
        issue_id=issue_id,
        capability=capability,
    )


# ============================================================================
# Request Models
# ============================================================================

class CreateBoardRequest(BaseModel):
    """Request model for creating a board."""
    workspace_app_id: str = Field(..., description="Workspace app ID (projects app)")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    key: Optional[str] = Field(None, max_length=10, description="Short code e.g. CORE")


class UpdateBoardRequest(BaseModel):
    """Request model for updating a board."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    key: Optional[str] = Field(None, max_length=10)
    default_role_capabilities: Optional[Dict[str, Any]] = None
    enforce_column_limits: Optional[bool] = None


class CreateStateRequest(BaseModel):
    """Request model for creating a state/column."""
    name: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = None
    is_done: bool = False
    is_locked: bool = False
    wip_limit: Optional[int] = Field(None, ge=0)


class UpdateStateRequest(BaseModel):
    """Request model for updating a state."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = None
    is_done: Optional[bool] = None
    is_locked: Optional[bool] = None
    wip_limit: Optional[int] = Field(None, ge=0)
    clear_wip_limit: bool = False


class CreateIssueRequest(BaseModel):
    """Request model for creating an issue/card."""
    board_id: str = Field(..., description="Board UUID")
    state_id: str = Field(..., description="Initial state UUID")
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    priority: int = Field(default=0, ge=0, le=4, description="0=none, 1=urgent, 2=high, 3=medium, 4=low")
    due_at: Optional[datetime] = None
    type: Optional[str] = Field(None, max_length=80)
    tags: Optional[List[str]] = None
    target_due_at: Optional[datetime] = None
    complexity: Optional[int] = Field(None, ge=0, le=5)
    image_r2_keys: Optional[List[str]] = Field(None, description="List of R2 keys for issue images")
    label_ids: Optional[List[str]] = None
    assignee_ids: Optional[List[str]] = None


class UpdateIssueRequest(BaseModel):
    """Request model for updating an issue.

    Image operations (mutually exclusive - use only ONE):
    - add_image_r2_keys: Append images to existing array (atomic)
    - remove_image_r2_keys: Remove specific images from array (atomic)
    - image_r2_keys: Replace entire image array
    - clear_images: Remove all images
    """
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=4)
    due_at: Optional[datetime] = None
    clear_due_at: bool = False
    type: Optional[str] = Field(None, max_length=80)
    clear_type: bool = False
    tags: Optional[List[str]] = None
    target_due_at: Optional[datetime] = None
    clear_target_due_at: bool = False
    complexity: Optional[int] = Field(None, ge=0, le=5)
    clear_complexity: bool = False
    # Image operations - use only one at a time
    add_image_r2_keys: Optional[List[str]] = Field(None, description="Append images to existing array")
    remove_image_r2_keys: Optional[List[str]] = Field(None, description="Remove specific images from array")
    image_r2_keys: Optional[List[str]] = Field(None, description="Replace all images with these R2 keys")
    clear_images: bool = False
    state_id: Optional[str] = None
    position: Optional[int] = Field(None, ge=0)
    label_ids: Optional[List[str]] = None
    assignee_ids: Optional[List[str]] = None

    @model_validator(mode="after")
    def check_images_not_conflicting(self) -> "UpdateIssueRequest":
        """Ensure only one image operation is used at a time."""
        ops = [
            self.add_image_r2_keys is not None,
            self.remove_image_r2_keys is not None,
            self.image_r2_keys is not None,
            self.clear_images,
        ]
        if sum(ops) > 1:
            raise ValueError(
                "Image operations are mutually exclusive. "
                "Use only one of: add_image_r2_keys, remove_image_r2_keys, image_r2_keys, clear_images"
            )
        return self


class MoveIssueRequest(BaseModel):
    """Request model for moving an issue to a new state."""
    target_state_id: str = Field(..., description="Target state UUID")
    position: int = Field(..., ge=0, description="Target position in new state")


class ItemPosition(BaseModel):
    """Single item position for reordering."""
    id: str
    position: int = Field(..., ge=0)


class ReorderRequest(BaseModel):
    """Request model for reordering items."""
    items: List[ItemPosition]


class CreateLabelRequest(BaseModel):
    """Request model for creating a label."""
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default='#6B7280', max_length=20)


class UpdateLabelRequest(BaseModel):
    """Request model for updating a label."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)


class AddAssigneeRequest(BaseModel):
    """Request model for adding an assignee."""
    user_id: str = Field(..., description="User UUID to assign")


class ContentBlock(BaseModel):
    """Content block for rich text."""
    type: str = Field(..., description="Block type: text, mention, code, quote")
    data: dict = Field(default_factory=dict, description="Block data")


class CreateCommentRequest(BaseModel):
    """Request model for creating a comment."""
    blocks: List[ContentBlock] = Field(..., description="Content blocks")


class UpdateCommentRequest(BaseModel):
    """Request model for updating a comment."""
    blocks: List[ContentBlock] = Field(..., description="Updated content blocks")


class AddCommentReactionRequest(BaseModel):
    """Request model for adding a reaction."""
    emoji: str = Field(..., min_length=1, max_length=32, description="Emoji string")


class UpsertRolePresetRequest(BaseModel):
    capabilities: Dict[str, bool] = Field(default_factory=dict)


class ApprovalNoteRequest(BaseModel):
    note: Optional[str] = None


class ApprovalRequest(BaseModel):
    approver_id: str
    note: Optional[str] = None


class IssueAttachmentUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str
    file_size: int = Field(..., gt=0)


class IssueAttachmentUploadResponse(BaseModel):
    upload_url: str
    r2_key: str
    expires_at: str
    headers: Dict[str, str] = Field(default_factory=dict)


class IssueAttachmentConfirmRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str
    file_size: int = Field(..., gt=0)
    r2_key: str
    attachment_id: Optional[str] = None


class CreateBoardViewRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    filters: Dict[str, Any] = Field(default_factory=dict)
    sort: List[Dict[str, Any]] = Field(default_factory=list)
    layout: str = Field(default="kanban", pattern="^(kanban|list)$")
    is_shared: bool = True


class UpdateBoardViewRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    filters: Optional[Dict[str, Any]] = None
    sort: Optional[List[Dict[str, Any]]] = None
    layout: Optional[str] = Field(None, pattern="^(kanban|list)$")
    is_shared: Optional[bool] = None


# ============================================================================
# Response Models
# ============================================================================

class BoardResponse(BaseModel):
    """Response model for a single board."""
    id: str
    workspace_app_id: str
    workspace_id: str
    name: str
    description: Optional[str] = None
    key: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    position: int = 0
    next_issue_number: int = 1
    default_role_capabilities: Optional[Dict[str, Any]] = None
    enforce_column_limits: bool = True
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class BoardWithStatesResponse(BaseModel):
    """Response model for board creation (includes default states)."""
    board: BoardResponse
    states: List[dict]

    class Config:
        extra = "allow"


class BoardListResponse(BaseModel):
    """Response model for board list."""
    boards: List[BoardResponse]
    count: int


class StateResponse(BaseModel):
    """Response model for a single state."""
    id: str
    board_id: str
    name: str
    color: Optional[str] = None
    position: int = 0
    is_done: bool = False
    is_locked: bool = False
    wip_limit: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class StateListResponse(BaseModel):
    """Response model for state list."""
    states: List[StateResponse]
    count: int


class LabelResponse(BaseModel):
    """Response model for a label."""
    id: str
    board_id: str
    name: str
    color: str = '#6B7280'
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class LabelListResponse(BaseModel):
    """Response model for label list."""
    labels: List[LabelResponse]
    count: int


class IssueLabelJunctionResponse(BaseModel):
    """Response model for an issue-label junction row."""
    id: str
    issue_id: str
    label_id: str
    created_at: Optional[str] = None

    class Config:
        extra = "allow"


class AssigneeResponse(BaseModel):
    """Response model for an issue assignee."""
    id: str
    issue_id: str
    user_id: str
    created_at: Optional[str] = None

    class Config:
        extra = "allow"


class AssigneeListResponse(BaseModel):
    """Response model for assignee list."""
    assignees: List[AssigneeResponse]
    count: int


class IssueResponse(BaseModel):
    """Response model for a single issue."""
    id: str
    board_id: str
    state_id: str
    number: int
    title: str
    description: Optional[str] = None
    priority: int = 0
    due_at: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    target_due_at: Optional[str] = None
    complexity: Optional[int] = None
    image_r2_keys: Optional[List[str]] = None
    image_urls: Optional[List[str]] = None
    label_objects: Optional[List[LabelResponse]] = None
    assignees: Optional[List[AssigneeResponse]] = None
    position: int = 0
    created_by: Optional[str] = None
    last_edited_by: Optional[str] = None
    last_edited_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class IssueListResponse(BaseModel):
    """Response model for issue list."""
    issues: List[IssueResponse]
    count: int


class DeleteResponse(BaseModel):
    """Response for delete operations."""
    status: str

    class Config:
        extra = "allow"


class ReorderResponse(BaseModel):
    """Response for reorder operations."""
    updated_count: int

    class Config:
        extra = "allow"


class UserInfoResponse(BaseModel):
    """Embedded user info in responses."""
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        extra = "allow"


class CommentReactionResponse(BaseModel):
    """Response model for a comment reaction."""
    id: str
    comment_id: str
    user_id: str
    emoji: str
    created_at: Optional[str] = None

    class Config:
        extra = "allow"


class CommentResponse(BaseModel):
    """Response model for a single comment."""
    id: str
    issue_id: str
    user_id: str
    content: Optional[str] = None
    blocks: List[dict] = Field(default_factory=list)
    is_edited: bool = False
    edited_at: Optional[str] = None
    created_at: Optional[str] = None
    user: Optional[UserInfoResponse] = None
    reactions: Optional[List[CommentReactionResponse]] = None

    class Config:
        extra = "allow"


class CommentListResponse(BaseModel):
    """Response model for comment list."""
    comments: List[CommentResponse]
    count: int  # Page count
    total_count: int  # Total comments for this issue


class ProjectBoardRolePresetResponse(BaseModel):
    """Response model for a board role preset."""
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    board_id: str
    role: str
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class ProjectBoardMemberPermissionResponse(BaseModel):
    """Response model for a board member permission override."""
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    board_id: str
    user_id: str
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class BoardRolePresetsResponse(BaseModel):
    """Response model for board role presets and resolved capabilities."""
    role_presets: List[ProjectBoardRolePresetResponse]
    member_permissions: List[ProjectBoardMemberPermissionResponse]
    capabilities: Dict[str, bool]


class ProjectBoardRolePresetEnvelopeResponse(BaseModel):
    role_preset: ProjectBoardRolePresetResponse


class ProjectBoardMemberPermissionEnvelopeResponse(BaseModel):
    member_permission: ProjectBoardMemberPermissionResponse


class ApprovalStateResponse(BaseModel):
    approval_status: str
    approval_requested_by: Optional[str] = None
    approval_requested_at: Optional[str] = None
    approval_note: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_decision_note: Optional[str] = None
    approver_id: Optional[str] = None
    approval_locked: bool = False


class IssueAttachmentVersionResponse(BaseModel):
    id: str
    attachment_id: str
    version_number: int
    r2_key: str
    file_size: int
    content_type: str
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[str] = None

    class Config:
        extra = "allow"


class IssueAttachmentResponse(BaseModel):
    id: str
    issue_id: str
    filename: str
    content_type: str
    current_version_id: Optional[str] = None
    next_version_number: Optional[int] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    current_version: Optional[IssueAttachmentVersionResponse] = None

    class Config:
        extra = "allow"


class IssueAttachmentListResponse(BaseModel):
    attachments: List[IssueAttachmentResponse]
    count: int


class IssueAttachmentVersionListResponse(BaseModel):
    versions: List[IssueAttachmentVersionResponse]
    count: int


class AttachmentVersionURLResponse(BaseModel):
    url: str
    expires_in: int


class ProjectBoardViewResponse(BaseModel):
    """Response model for a saved board view."""
    id: str
    workspace_id: str
    board_id: str
    name: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    sort: List[Dict[str, Any]] = Field(default_factory=list)
    layout: str
    is_shared: bool = True
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        extra = "allow"


class ProjectBoardViewListResponse(BaseModel):
    views: List[ProjectBoardViewResponse]
    count: int


class ProjectBoardViewEnvelopeResponse(BaseModel):
    view: ProjectBoardViewResponse


# ============================================================================
# Board Endpoints
# ============================================================================

@router.get("/boards", response_model=BoardListResponse)
async def get_boards_endpoint(
    workspace_app_id: str = Query(..., description="Workspace app ID (projects app)"),
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get all boards for a workspace's projects app."""
    try:
        boards = await get_boards(user_jwt, workspace_app_id)
        return {"boards": boards, "count": len(boards)}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch boards", logger)


@router.get("/boards/{board_id}", response_model=BoardResponse)
async def get_board_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get a single board by ID."""
    try:
        board = await get_board_by_id(user_jwt, board_id)
        if not board:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
        return board
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to fetch board", logger)


@router.post("/boards", response_model=BoardWithStatesResponse, status_code=status.HTTP_201_CREATED)
async def create_board_endpoint(
    request: CreateBoardRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new board with default states (To Do, In Progress, Done)."""
    try:
        result = await create_board(
            user_id=user_id,
            user_jwt=user_jwt,
            workspace_app_id=request.workspace_app_id,
            name=request.name,
            description=request.description,
            icon=request.icon,
            color=request.color,
            key=request.key,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        message = str(e).lower()
        if (
            "duplicate key value violates unique constraint" in message
            and (
                "idx_project_boards_unique_key" in message
                or ("project_boards" in message and "key" in message)
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project key already exists",
            )
        handle_api_exception(e, "Failed to create board", logger)


@router.patch("/boards/{board_id}", response_model=BoardResponse)
async def update_board_endpoint(
    board_id: str,
    request: UpdateBoardRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Update a board."""
    try:
        board = await update_board(
            user_jwt=user_jwt,
            user_id=user_id,
            board_id=board_id,
            name=request.name,
            description=request.description,
            icon=request.icon,
            color=request.color,
            key=request.key,
            default_role_capabilities=request.default_role_capabilities,
            enforce_column_limits=request.enforce_column_limits,
            background_tasks=background_tasks,
        )
        return board
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to update board", logger)


@router.delete("/boards/{board_id}", response_model=DeleteResponse)
async def delete_board_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a board and all its states/issues."""
    try:
        return await delete_board(user_jwt, user_id, board_id)
    except Exception as e:
        handle_api_exception(e, "Failed to delete board", logger)


@router.get("/boards/{board_id}/role-presets", response_model=BoardRolePresetsResponse)
async def get_board_role_presets_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Get board role presets and the current user's resolved capabilities."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        from api.services.projects.access import resolve_board_capabilities

        board = await get_board_by_id(user_jwt, board_id)
        if not board:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
        presets = await supabase.table("project_board_role_presets")\
            .select("*")\
            .eq("board_id", board_id)\
            .execute()
        member_permissions = await supabase.table("project_board_member_permissions")\
            .select("*")\
            .eq("board_id", board_id)\
            .execute()
        capabilities = await resolve_board_capabilities(
            supabase,
            user_id=user_id,
            board_id=board_id,
        )
        return {
            "role_presets": presets.data or [],
            "member_permissions": member_permissions.data or [],
            "capabilities": capabilities,
        }
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to fetch board permissions", logger)


@router.put("/boards/{board_id}/role-presets/{role}", response_model=ProjectBoardRolePresetEnvelopeResponse)
async def upsert_board_role_preset_endpoint(
    board_id: str,
    role: str,
    request: UpsertRolePresetRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create or update a board role preset."""
    try:
        if role not in {"owner", "admin", "member"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace role")
        supabase = await get_authenticated_async_client(user_jwt)
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=board_id,
            capability="manage_permissions",
        )
        board = await get_board_by_id(user_jwt, board_id)
        if not board:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
        result = await supabase.table("project_board_role_presets")\
            .upsert({
                "workspace_id": board["workspace_id"],
                "board_id": board_id,
                "role": role,
                "capabilities": request.capabilities,
            }, on_conflict="board_id,role")\
            .execute()
        return {"role_preset": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to save board role preset", logger)


@router.put("/boards/{board_id}/member-permissions/{target_user_id}", response_model=ProjectBoardMemberPermissionEnvelopeResponse)
async def upsert_board_member_permission_endpoint(
    board_id: str,
    target_user_id: str,
    request: UpsertRolePresetRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create or update per-member board permission overrides."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=board_id,
            capability="manage_permissions",
        )
        board = await get_board_by_id(user_jwt, board_id)
        if not board:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

        membership = await supabase.table("workspace_members")\
            .select("id")\
            .eq("workspace_id", board["workspace_id"])\
            .eq("user_id", target_user_id)\
            .maybe_single()\
            .execute()
        if not membership.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not a workspace member")

        result = await supabase.table("project_board_member_permissions")\
            .upsert({
                "workspace_id": board["workspace_id"],
                "board_id": board_id,
                "user_id": target_user_id,
                "capabilities": request.capabilities,
            }, on_conflict="board_id,user_id")\
            .execute()
        return {"member_permission": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to save board member permissions", logger)


@router.get("/boards/{board_id}/views", response_model=ProjectBoardViewListResponse)
async def list_board_views_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """List saved views for a board."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        result = await supabase.table("project_board_views")\
            .select("*")\
            .eq("board_id", board_id)\
            .order("created_at", desc=True)\
            .execute()
        return {"views": result.data or [], "count": len(result.data or [])}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch board views", logger)


@router.post("/boards/{board_id}/views", response_model=ProjectBoardViewEnvelopeResponse, status_code=status.HTTP_201_CREATED)
async def create_board_view_endpoint(
    board_id: str,
    request: CreateBoardViewRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a saved board view."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        board = await get_board_by_id(user_jwt, board_id)
        if not board:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
        result = await supabase.table("project_board_views")\
            .insert({
                "workspace_id": board["workspace_id"],
                "board_id": board_id,
                "name": request.name,
                "filters": request.filters,
                "sort": request.sort,
                "layout": request.layout,
                "is_shared": request.is_shared,
                "created_by": user_id,
            })\
            .execute()
        return {"view": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to create board view", logger)


@router.patch("/views/{view_id}", response_model=ProjectBoardViewEnvelopeResponse)
async def update_board_view_endpoint(
    view_id: str,
    request: UpdateBoardViewRequest,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Update a saved board view."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            current = await supabase.table("project_board_views")\
                .select("*")\
                .eq("id", view_id)\
                .single()\
                .execute()
            return {"view": current.data}
        result = await supabase.table("project_board_views")\
            .update(updates)\
            .eq("id", view_id)\
            .execute()
        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="View not found")
        return {"view": result.data[0]}
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to update board view", logger)


@router.delete("/views/{view_id}", response_model=DeleteResponse)
async def delete_board_view_endpoint(
    view_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Delete a saved board view."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        await supabase.table("project_board_views")\
            .delete()\
            .eq("id", view_id)\
            .execute()
        return {"status": "deleted", "id": view_id}
    except Exception as e:
        handle_api_exception(e, "Failed to delete board view", logger)


# ============================================================================
# State Endpoints
# ============================================================================

@router.get("/boards/{board_id}/states", response_model=StateListResponse)
async def get_states_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get all states for a board, ordered by position."""
    try:
        states = await get_states(user_jwt, board_id)
        return {"states": states, "count": len(states)}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch states", logger)


@router.post("/boards/{board_id}/states", response_model=StateResponse, status_code=status.HTTP_201_CREATED)
async def create_state_endpoint(
    board_id: str,
    request: CreateStateRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new state/column in a board."""
    try:
        state = await create_state(
            user_jwt=user_jwt,
            user_id=user_id,
            board_id=board_id,
            name=request.name,
            color=request.color,
            is_done=request.is_done,
            is_locked=request.is_locked,
            wip_limit=request.wip_limit,
        )
        return state
    except Exception as e:
        handle_api_exception(e, "Failed to create state", logger)


@router.patch("/states/{state_id}", response_model=StateResponse)
async def update_state_endpoint(
    state_id: str,
    request: UpdateStateRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Update a state/column."""
    try:
        state = await update_state(
            user_jwt=user_jwt,
            user_id=user_id,
            state_id=state_id,
            name=request.name,
            color=request.color,
            is_done=request.is_done,
            is_locked=request.is_locked,
            wip_limit=request.wip_limit,
            clear_wip_limit=request.clear_wip_limit,
            background_tasks=background_tasks,
        )
        return state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to update state", logger)


@router.post("/boards/{board_id}/states/reorder", response_model=ReorderResponse)
async def reorder_states_endpoint(
    board_id: str,
    request: ReorderRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Reorder states within a board."""
    try:
        items = [{"id": p.id, "position": p.position} for p in request.items]
        result = await reorder_states(user_jwt, user_id, board_id, items)
        return result
    except Exception as e:
        handle_api_exception(e, "Failed to reorder states", logger)


@router.delete("/states/{state_id}", response_model=DeleteResponse)
async def delete_state_endpoint(
    state_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a state/column. Fails if it still has issues."""
    try:
        return await delete_state(user_jwt, user_id, state_id)
    except Exception as e:
        handle_api_exception(e, "Failed to delete state", logger)


# ============================================================================
# Label Endpoints
# ============================================================================

@router.get("/boards/{board_id}/labels", response_model=LabelListResponse)
async def get_labels_endpoint(
    board_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get all labels for a board."""
    try:
        labels = await get_labels(user_jwt, board_id)
        return {"labels": labels, "count": len(labels)}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch labels", logger)


@router.post("/boards/{board_id}/labels", response_model=LabelResponse, status_code=status.HTTP_201_CREATED)
async def create_label_endpoint(
    board_id: str,
    request: CreateLabelRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new label on a board."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=board_id,
            capability="manage_labels",
        )
        label = await create_label(
            user_jwt=user_jwt,
            user_id=user_id,
            board_id=board_id,
            name=request.name,
            color=request.color,
        )
        return label
    except Exception as e:
        message = str(e).lower()
        if "duplicate key value violates unique constraint" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Label name already exists on this board",
            )
        handle_api_exception(e, "Failed to create label", logger)


@router.patch("/labels/{label_id}", response_model=LabelResponse)
async def update_label_endpoint(
    label_id: str,
    request: UpdateLabelRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Update a label's name or color."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        label_context = await supabase.table("project_labels")\
            .select("board_id")\
            .eq("id", label_id)\
            .maybe_single()\
            .execute()
        if not label_context.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=label_context.data["board_id"],
            capability="manage_labels",
        )
        label = await update_label(
            user_jwt=user_jwt,
            label_id=label_id,
            name=request.name,
            color=request.color,
        )
        return label
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to update label", logger)


@router.delete("/labels/{label_id}", response_model=DeleteResponse)
async def delete_label_endpoint(
    label_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a label. Removes it from all issues."""
    try:
        supabase = await get_authenticated_async_client(user_jwt)
        label_context = await supabase.table("project_labels")\
            .select("board_id")\
            .eq("id", label_id)\
            .maybe_single()\
            .execute()
        if not label_context.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
        await require_board_capability(
            supabase,
            user_id=user_id,
            board_id=label_context.data["board_id"],
            capability="manage_labels",
        )
        return await delete_label(user_jwt, label_id)
    except Exception as e:
        handle_api_exception(e, "Failed to delete label", logger)


@router.post("/issues/{issue_id}/labels/{label_id}", response_model=IssueLabelJunctionResponse, status_code=status.HTTP_201_CREATED)
async def add_label_to_issue_endpoint(
    issue_id: str,
    label_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Add a label to an issue."""
    try:
        await _require_issue_route_capability(user_jwt, user_id, issue_id, "update_issue")
        result = await add_label_to_issue(user_jwt, issue_id, label_id, current_user_id=user_id)
        return result
    except Exception as e:
        message = str(e).lower()
        if "duplicate key value violates unique constraint" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Label already added to this issue",
            )
        handle_api_exception(e, "Failed to add label to issue", logger)


@router.delete("/issues/{issue_id}/labels/{label_id}", response_model=DeleteResponse)
async def remove_label_from_issue_endpoint(
    issue_id: str,
    label_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Remove a label from an issue."""
    try:
        await _require_issue_route_capability(user_jwt, user_id, issue_id, "update_issue")
        return await remove_label_from_issue(user_jwt, issue_id, label_id, current_user_id=user_id)
    except Exception as e:
        handle_api_exception(e, "Failed to remove label from issue", logger)


# ============================================================================
# Assignee Endpoints
# ============================================================================

@router.get("/issues/{issue_id}/assignees", response_model=AssigneeListResponse)
async def get_assignees_endpoint(
    issue_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get all assignees for an issue."""
    try:
        assignees = await get_issue_assignees(user_jwt, issue_id)
        return {"assignees": assignees, "count": len(assignees)}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch assignees", logger)


@router.post("/issues/{issue_id}/assignees", response_model=AssigneeResponse, status_code=status.HTTP_201_CREATED)
async def add_assignee_endpoint(
    issue_id: str,
    request: AddAssigneeRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Add an assignee to an issue (max 10)."""
    try:
        await _require_issue_route_capability(user_jwt, user_id, issue_id, "assign_issue")
        assignee = await add_assignee(user_jwt, issue_id, request.user_id, current_user_id=user_id)
        return assignee
    except Exception as e:
        message = str(e).lower()
        if "maximum of 10 assignees" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum of 10 assignees per issue reached",
            )
        if "duplicate key value violates unique constraint" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already assigned to this issue",
            )
        handle_api_exception(e, "Failed to add assignee", logger)


@router.delete("/issues/{issue_id}/assignees/{user_id}", response_model=DeleteResponse)
async def remove_assignee_endpoint(
    issue_id: str,
    user_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    current_user_id: str = Depends(get_current_user_id),
):
    """Remove an assignee from an issue."""
    try:
        await _require_issue_route_capability(user_jwt, current_user_id, issue_id, "assign_issue")
        return await remove_assignee(user_jwt, issue_id, user_id, current_user_id=current_user_id)
    except Exception as e:
        handle_api_exception(e, "Failed to remove assignee", logger)


# ============================================================================
# Issue Endpoints
# ============================================================================

@router.get("/boards/{board_id}/issues", response_model=IssueListResponse)
async def get_issues_endpoint(
    board_id: str,
    state_id: Optional[str] = Query(None, description="Filter by state"),
    assignee_user_id: Optional[str] = Query(None, description="Filter by assignee user ID"),
    include_done: bool = Query(True, description="Include completed issues"),
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get issues for a board with optional filters."""
    try:
        issues = await get_issues(
            user_jwt, board_id,
            state_id=state_id,
            assignee_user_id=assignee_user_id,
            include_done=include_done,
        )
        return {"issues": issues, "count": len(issues)}
    except Exception as e:
        handle_api_exception(e, "Failed to fetch issues", logger)


@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue_endpoint(
    issue_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get a single issue by ID."""
    try:
        issue = await get_issue_by_id(user_jwt, issue_id)
        if not issue:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
        return issue
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to fetch issue", logger)


@router.post("/issues", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
async def create_issue_endpoint(
    request: CreateIssueRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new issue with auto-allocated number."""
    try:
        issue = await create_issue(
            user_id=user_id,
            user_jwt=user_jwt,
            board_id=request.board_id,
            state_id=request.state_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            due_at=request.due_at,
            issue_type=request.type,
            tags=request.tags,
            target_due_at=request.target_due_at,
            complexity=request.complexity,
            image_r2_keys=request.image_r2_keys,
            label_ids=request.label_ids,
            assignee_ids=request.assignee_ids,
        )
        return issue
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to create issue", logger)


@router.patch("/issues/{issue_id}", response_model=IssueResponse)
async def update_issue_endpoint(
    issue_id: str,
    request: UpdateIssueRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Update an issue. Changing state_id triggers completion logic."""
    try:
        issue = await update_issue(
            user_jwt=user_jwt,
            user_id=user_id,
            issue_id=issue_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            due_at=request.due_at,
            clear_due_at=request.clear_due_at,
            issue_type=request.type,
            clear_type=request.clear_type,
            tags=request.tags,
            target_due_at=request.target_due_at,
            clear_target_due_at=request.clear_target_due_at,
            complexity=request.complexity,
            clear_complexity=request.clear_complexity,
            add_image_r2_keys=request.add_image_r2_keys,
            remove_image_r2_keys=request.remove_image_r2_keys,
            image_r2_keys=request.image_r2_keys,
            clear_images=request.clear_images,
            state_id=request.state_id,
            position=request.position,
            label_ids=request.label_ids,
            assignee_ids=request.assignee_ids,
            background_tasks=background_tasks,
        )
        return issue
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to update issue", logger)


@router.post("/issues/{issue_id}/move", response_model=IssueResponse)
async def move_issue_endpoint(
    issue_id: str,
    request: MoveIssueRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Move an issue to a new state and position (atomic operation)."""
    try:
        issue = await move_issue(
            user_jwt=user_jwt,
            issue_id=issue_id,
            target_state_id=request.target_state_id,
            position=request.position,
            current_user_id=user_id,
            background_tasks=background_tasks,
        )
        return issue
    except Exception as e:
        handle_api_exception(e, "Failed to move issue", logger)


@router.post("/states/{state_id}/issues/reorder", response_model=ReorderResponse)
async def reorder_issues_endpoint(
    state_id: str,
    request: ReorderRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Reorder issues within a state."""
    try:
        items = [{"id": p.id, "position": p.position} for p in request.items]
        result = await reorder_issues(user_jwt, user_id, state_id, items)
        return result
    except Exception as e:
        handle_api_exception(e, "Failed to reorder issues", logger)


@router.delete("/issues/{issue_id}", response_model=DeleteResponse)
async def delete_issue_endpoint(
    issue_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Delete an issue."""
    try:
        return await delete_issue(user_jwt, user_id, issue_id)
    except Exception as e:
        handle_api_exception(e, "Failed to delete issue", logger)


# ============================================================================
# Approval Endpoints
# ============================================================================

@router.get("/issues/{issue_id}/approval", response_model=ApprovalStateResponse)
async def get_issue_approval_endpoint(
    issue_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get approval state for an issue."""
    try:
        return await get_issue_approval_state(user_jwt, issue_id)
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to fetch approval state", logger)


@router.post("/issues/{issue_id}/approval/request", response_model=IssueResponse)
async def request_issue_approval_endpoint(
    issue_id: str,
    request: ApprovalRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Request approval for an issue."""
    try:
        return await request_issue_approval(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            approver_id=request.approver_id,
            note=request.note,
            background_tasks=background_tasks,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to request approval", logger)


@router.post("/issues/{issue_id}/approval/approve", response_model=IssueResponse)
async def approve_issue_approval_endpoint(
    issue_id: str,
    request: ApprovalNoteRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Approve a pending issue approval request."""
    try:
        return await approve_issue_approval(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            note=request.note,
            background_tasks=background_tasks,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to approve issue", logger)


@router.post("/issues/{issue_id}/approval/reject", response_model=IssueResponse)
async def reject_issue_approval_endpoint(
    issue_id: str,
    request: ApprovalNoteRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Reject a pending issue approval request."""
    try:
        return await reject_issue_approval(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            note=request.note or "",
            background_tasks=background_tasks,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to reject issue", logger)


@router.post("/issues/{issue_id}/approval/unlock", response_model=IssueResponse)
async def unlock_issue_approval_endpoint(
    issue_id: str,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Unlock an approved issue for revisions."""
    try:
        return await unlock_issue_approval(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            background_tasks=background_tasks,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to unlock issue", logger)


# ============================================================================
# Attachment Endpoints
# ============================================================================

@router.post("/issues/{issue_id}/attachments/upload-url", response_model=IssueAttachmentUploadResponse)
async def initiate_issue_attachment_upload_endpoint(
    issue_id: str,
    request: IssueAttachmentUploadRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Get a presigned PUT URL for a project issue attachment."""
    try:
        return await initiate_attachment_upload(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            filename=request.filename,
            content_type=request.content_type,
            file_size=request.file_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to initiate attachment upload", logger)


@router.post("/issues/{issue_id}/attachments/confirm", response_model=IssueAttachmentResponse)
async def confirm_issue_attachment_endpoint(
    issue_id: str,
    request: IssueAttachmentConfirmRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Confirm an uploaded project issue attachment version."""
    try:
        return await confirm_attachment_version(
            user_id=user_id,
            user_jwt=user_jwt,
            issue_id=issue_id,
            filename=request.filename,
            content_type=request.content_type,
            file_size=request.file_size,
            r2_key=request.r2_key,
            attachment_id=request.attachment_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to confirm attachment upload", logger)


@router.get("/issues/{issue_id}/attachments", response_model=IssueAttachmentListResponse)
async def list_issue_attachments_endpoint(
    issue_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """List attachments for a project issue."""
    try:
        attachments = await list_issue_attachments(user_jwt, issue_id)
        return {"attachments": attachments, "count": len(attachments)}
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to list issue attachments", logger)


@router.get("/attachments/{attachment_id}/versions", response_model=IssueAttachmentVersionListResponse)
async def list_attachment_versions_endpoint(
    attachment_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """List retained versions for an issue attachment."""
    try:
        versions = await list_attachment_versions(user_jwt, attachment_id)
        return {"versions": versions, "count": len(versions)}
    except Exception as e:
        handle_api_exception(e, "Failed to list attachment versions", logger)


@router.get("/attachment-versions/{version_id}/url", response_model=AttachmentVersionURLResponse)
async def get_attachment_version_url_endpoint(
    version_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get a presigned download URL for an issue attachment version."""
    try:
        return await get_attachment_version_url(user_jwt=user_jwt, version_id=version_id)
    except HTTPException:
        raise
    except Exception as e:
        handle_api_exception(e, "Failed to get attachment version URL", logger)


# ============================================================================
# Comment Endpoints
# ============================================================================

@router.get("/issues/{issue_id}/comments", response_model=CommentListResponse)
async def get_comments_endpoint(
    issue_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max comments to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Get comments for an issue, ordered chronologically."""
    try:
        result = await get_comments(user_jwt, issue_id, limit=limit, offset=offset)
        return result
    except Exception as e:
        handle_api_exception(e, "Failed to fetch comments", logger)


@router.post("/issues/{issue_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment_endpoint(
    issue_id: str,
    request: CreateCommentRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new comment on an issue."""
    try:
        await _require_issue_route_capability(user_jwt, user_id, issue_id, "comment_issue")
        blocks = [b.model_dump() for b in request.blocks]
        comment = await create_comment(
            user_id,
            user_jwt,
            issue_id,
            blocks,
            background_tasks=background_tasks,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to create comment", logger)


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment_endpoint(
    comment_id: str,
    request: UpdateCommentRequest,
    background_tasks: BackgroundTasks,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Update a comment (author only)."""
    try:
        blocks = [b.model_dump() for b in request.blocks]
        comment = await update_comment(
            user_jwt,
            user_id,
            comment_id,
            blocks,
            background_tasks=background_tasks,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to update comment", logger)


@router.delete("/comments/{comment_id}", response_model=DeleteResponse)
async def delete_comment_endpoint(
    comment_id: str,
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Delete a comment (author or admin)."""
    try:
        return await delete_comment(user_jwt, comment_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        handle_api_exception(e, "Failed to delete comment", logger)


@router.post("/comments/{comment_id}/reactions", response_model=CommentReactionResponse, status_code=status.HTTP_201_CREATED)
async def add_comment_reaction_endpoint(
    comment_id: str,
    request: AddCommentReactionRequest,
    user_jwt: str = Depends(get_current_user_jwt),
    user_id: str = Depends(get_current_user_id),
):
    """Add a reaction to a comment."""
    try:
        reaction = await add_reaction(user_id, user_jwt, comment_id, request.emoji)
        return reaction
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        message = str(e).lower()
        if "duplicate key value violates unique constraint" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already reacted with this emoji",
            )
        handle_api_exception(e, "Failed to add reaction", logger)


@router.delete("/comments/{comment_id}/reactions/{emoji}", response_model=DeleteResponse)
async def remove_comment_reaction_endpoint(
    comment_id: str,
    emoji: str,
    user_id: str = Depends(get_current_user_id),
    user_jwt: str = Depends(get_current_user_jwt),
):
    """Remove a reaction from a comment (own reaction only)."""
    try:
        await remove_reaction(user_id, user_jwt, comment_id, emoji)
        return {"status": "deleted"}
    except Exception as e:
        handle_api_exception(e, "Failed to remove reaction", logger)
