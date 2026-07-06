"""
Projects service - Kanban-style boards with states and issues
"""
from .boards import (
    get_boards,
    get_board_by_id,
    create_board,
    update_board,
    delete_board,
)
from .states import (
    get_states,
    create_state,
    update_state,
    delete_state,
    reorder_states,
)
from .issues import (
    get_issues,
    get_issue_by_id,
    create_issue,
    update_issue,
    delete_issue,
    move_issue,
    reorder_issues,
)
from .labels import (
    get_labels,
    create_label,
    update_label,
    delete_label,
    get_issue_labels,
    add_label_to_issue,
    remove_label_from_issue,
)
from .assignees import (
    get_issue_assignees,
    add_assignee,
    remove_assignee,
)
from .comments import (
    get_comments,
    create_comment,
    update_comment,
    delete_comment,
    add_reaction,
    remove_reaction,
)
from .approvals import (
    get_issue_approval_state,
    request_issue_approval,
    approve_issue_approval,
    reject_issue_approval,
    unlock_issue_approval,
)
from .attachments import (
    initiate_attachment_upload,
    confirm_attachment_version,
    list_issue_attachments,
    list_attachment_versions,
    get_attachment_version_url,
)

__all__ = [
    # Boards
    'get_boards',
    'get_board_by_id',
    'create_board',
    'update_board',
    'delete_board',

    # States
    'get_states',
    'create_state',
    'update_state',
    'delete_state',
    'reorder_states',

    # Issues
    'get_issues',
    'get_issue_by_id',
    'create_issue',
    'update_issue',
    'delete_issue',
    'move_issue',
    'reorder_issues',

    # Labels
    'get_labels',
    'create_label',
    'update_label',
    'delete_label',
    'get_issue_labels',
    'add_label_to_issue',
    'remove_label_from_issue',

    # Assignees
    'get_issue_assignees',
    'add_assignee',
    'remove_assignee',

    # Comments
    'get_comments',
    'create_comment',
    'update_comment',
    'delete_comment',
    'add_reaction',
    'remove_reaction',

    # Approvals
    'get_issue_approval_state',
    'request_issue_approval',
    'approve_issue_approval',
    'reject_issue_approval',
    'unlock_issue_approval',
    'initiate_attachment_upload',
    'confirm_attachment_version',
    'list_issue_attachments',
    'list_attachment_versions',
    'get_attachment_version_url',
]
