import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  getProjectBoards,
  getProjectStates,
  getProjectIssues,
  getProjectLabels,
  getWorkspaceMembers,
  getIssueComments,
  createProjectBoard,
  updateProjectBoard,
  deleteProjectBoard,
  createProjectState,
  updateProjectState,
  deleteProjectState,
  reorderProjectStates,
  createProjectIssue,
  updateProjectIssue,
  deleteProjectIssue,
  moveProjectIssue,
  reorderProjectIssues,
  getProjectBoardRolePresets,
  requestIssueApproval,
  approveIssueApproval,
  rejectIssueApproval,
  unlockIssueApproval,
  getIssueAttachments,
  getAttachmentVersions,
  getAttachmentVersionUrl,
  initiateIssueAttachmentUpload,
  confirmIssueAttachmentVersion,
  createProjectLabel,
  addLabelToIssue,
  removeLabelFromIssue,
  addIssueAssignee,
  removeIssueAssignee,
  createIssueComment,
  updateIssueComment,
  deleteIssueComment,
  addCommentReaction,
  removeCommentReaction,
  type ProjectBoard,
  type ProjectBoardMemberPermission,
  type ProjectState,
  type ProjectIssue,
  type ProjectLabel,
  type ProjectIssueAssignee,
  type IssueAttachment,
  type IssueAttachmentVersion,
  type WorkspaceMember,
  type IssueComment,
  type ContentBlock,
  type CommentReaction,
} from '../../api/client';
import { projectKeys } from './keys';
import { useAuthStore } from '../../stores/authStore';
import { toast } from 'sonner';

// Re-export types for convenience
export type {
  ProjectBoard,
  ProjectState,
  ProjectIssue,
  ProjectLabel,
  ProjectIssueAssignee,
  IssueAttachment,
  IssueAttachmentVersion,
  WorkspaceMember,
  IssueComment,
  ContentBlock,
  CommentReaction,
  ProjectBoardMemberPermission,
};

// ============================================================================
// Constants
// ============================================================================

const STALE_TIMES = {
  boards: 5 * 60 * 1000, // 5 min - rarely changes
  boardData: 2 * 60 * 1000, // 2 min - issues change often
  comments: 30 * 1000, // 30 sec - conversations move fast
  members: 10 * 60 * 1000, // 10 min - very stable
  attachments: 30 * 1000,
};

const DEFAULT_TODO_COLOR = '#EF4444';
const DEFAULT_TODO_BLUE = '#3B82F6';
type BoardData = {
  states: ProjectState[];
  issues: ProjectIssue[];
  labels: ProjectLabel[];
};

type UpdateIssueInput = {
  title?: string;
  description?: string;
  priority?: number;
  due_at?: string;
  clear_due_at?: boolean;
  add_image_r2_keys?: string[];
  remove_image_r2_keys?: string[];
  image_r2_keys?: string[];
  clear_images?: boolean;
  state_id?: string;
  position?: number;
};

type PendingTempIssueOp =
  | { type: 'update'; updates: UpdateIssueInput }
  | { type: 'delete' }
  | { type: 'move'; targetStateId: string; position: number }
  | { type: 'toggle_label'; labelId: string; hasLabel: boolean }
  | { type: 'add_assignee'; userId: string }
  | { type: 'remove_assignee'; userId: string };

const pendingTempIssueOps = new Map<string, PendingTempIssueOp[]>();

// ============================================================================
// Helpers
// ============================================================================

const normalizeTodoStateColor = (state: ProjectState): ProjectState => {
  const name = state.name?.trim().toLowerCase();
  if (name === 'to do' || name === 'todo' || name === 'to-do') {
    if (!state.color || state.color === DEFAULT_TODO_BLUE) {
      return { ...state, color: DEFAULT_TODO_COLOR };
    }
  }
  return state;
};

const normalizeStates = (states: ProjectState[]) => states.map(normalizeTodoStateColor);
const isTempIssueId = (issueId: string) => issueId.startsWith('temp-');

const queuePendingTempIssueOp = (tempIssueId: string, op: PendingTempIssueOp) => {
  const existing = pendingTempIssueOps.get(tempIssueId) ?? [];
  existing.push(op);
  pendingTempIssueOps.set(tempIssueId, existing);
};

const getCachedIssue = (
  queryClient: QueryClient,
  boardDataKey: readonly unknown[],
  issueId: string
): ProjectIssue | null => {
  const data = queryClient.getQueryData<BoardData>(boardDataKey);
  return data?.issues.find((issue) => issue.id === issueId) ?? null;
};

const buildFallbackIssue = (issueId: string, boardId: string | null): ProjectIssue => ({
  id: issueId,
  board_id: boardId ?? '',
  state_id: '',
  number: 0,
  title: '',
  priority: 0,
  position: 0,
  label_objects: [],
  assignees: [],
});

const mergeTempIssueIntoCreatedIssue = (serverIssue: ProjectIssue, tempIssue: ProjectIssue): ProjectIssue => ({
  ...serverIssue,
  title: tempIssue.title,
  description: tempIssue.description,
  priority: tempIssue.priority,
  due_at: tempIssue.due_at,
  image_r2_keys: tempIssue.image_r2_keys,
  image_urls: tempIssue.image_urls,
  state_id: tempIssue.state_id,
  position: tempIssue.position,
  label_objects: tempIssue.label_objects,
  assignees: tempIssue.assignees,
});

async function flushPendingTempIssueOps(params: {
  tempIssueId: string;
  realIssueId: string;
  queryClient: QueryClient;
  boardDataKey: readonly unknown[];
}) {
  const { tempIssueId, realIssueId, queryClient, boardDataKey } = params;
  const ops = pendingTempIssueOps.get(tempIssueId);
  if (!ops || ops.length === 0) return;

  pendingTempIssueOps.delete(tempIssueId);

  let wasDeleted = false;
  try {
    for (const op of ops) {
      if (wasDeleted) break;

      switch (op.type) {
        case 'update':
          await updateProjectIssue(realIssueId, op.updates);
          break;
        case 'delete':
          await deleteProjectIssue(realIssueId);
          wasDeleted = true;
          break;
        case 'move':
          await moveProjectIssue(realIssueId, op.targetStateId, op.position);
          break;
        case 'toggle_label':
          if (op.hasLabel) {
            await removeLabelFromIssue(realIssueId, op.labelId);
          } else {
            await addLabelToIssue(realIssueId, op.labelId);
          }
          break;
        case 'add_assignee':
          await addIssueAssignee(realIssueId, op.userId);
          break;
        case 'remove_assignee':
          await removeIssueAssignee(realIssueId, op.userId);
          break;
      }
    }

    if (wasDeleted) {
      queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) =>
        old ? { ...old, issues: old.issues.filter((issue) => issue.id !== realIssueId) } : old
      );
    }
  } catch (error) {
    console.error('Failed to sync temp issue changes after create', error);
    toast.error('Some card changes could not be synced. Please refresh.');
  } finally {
    queryClient.invalidateQueries({ queryKey: boardDataKey });
  }
}

// ============================================================================
// Query Hooks
// ============================================================================

/**
 * Fetch all boards for a workspace
 */
export function useProjectBoards(workspaceAppId: string | null) {
  return useQuery({
    queryKey: projectKeys.boards(workspaceAppId ?? ''),
    queryFn: async () => {
      if (!workspaceAppId) throw new Error('No workspace app ID');
      const result = await getProjectBoards(workspaceAppId);
      return result.boards;
    },
    enabled: !!workspaceAppId,
    staleTime: STALE_TIMES.boards,
  });
}

/**
 * Fetch board data (states, issues, labels) combined
 */
export function useProjectBoard(boardId: string | null) {
  return useQuery({
    queryKey: projectKeys.boardData(boardId ?? ''),
    queryFn: async () => {
      if (!boardId) throw new Error('No board ID');
      const [statesResult, issuesResult, labelsResult] = await Promise.all([
        getProjectStates(boardId),
        getProjectIssues(boardId),
        getProjectLabels(boardId),
      ]);
      return {
        states: normalizeStates(statesResult.states),
        issues: issuesResult.issues,
        labels: labelsResult.labels,
      };
    },
    enabled: !!boardId,
    staleTime: STALE_TIMES.boardData,
  });
}

/**
 * Fetch states for a board
 */
export function useProjectStates(boardId: string | null) {
  return useQuery({
    queryKey: projectKeys.states(boardId ?? ''),
    queryFn: async () => {
      if (!boardId) throw new Error('No board ID');
      const result = await getProjectStates(boardId);
      return normalizeStates(result.states);
    },
    enabled: !!boardId,
    staleTime: STALE_TIMES.boardData,
  });
}

/**
 * Fetch issues for a board
 */
export function useProjectIssues(boardId: string | null) {
  return useQuery({
    queryKey: projectKeys.issues(boardId ?? ''),
    queryFn: async () => {
      if (!boardId) throw new Error('No board ID');
      const result = await getProjectIssues(boardId);
      return result.issues;
    },
    enabled: !!boardId,
    staleTime: STALE_TIMES.boardData,
  });
}

/**
 * Fetch labels for a board
 */
export function useProjectLabels(boardId: string | null) {
  return useQuery({
    queryKey: projectKeys.labels(boardId ?? ''),
    queryFn: async () => {
      if (!boardId) throw new Error('No board ID');
      const result = await getProjectLabels(boardId);
      return result.labels;
    },
    enabled: !!boardId,
    staleTime: STALE_TIMES.boardData,
  });
}

/**
 * Fetch comments for an issue
 */
export function useIssueComments(issueId: string | null) {
  return useQuery({
    queryKey: projectKeys.comments(issueId ?? ''),
    queryFn: async () => {
      if (!issueId) throw new Error('No issue ID');
      const result = await getIssueComments(issueId);
      return result.comments;
    },
    enabled: !!issueId && !issueId.startsWith('temp-'),
    staleTime: STALE_TIMES.comments,
  });
}

/**
 * Fetch workspace members
 */
export function useProjectMembers(workspaceId: string | null) {
  return useQuery({
    queryKey: projectKeys.members(workspaceId ?? ''),
    queryFn: async () => {
      if (!workspaceId) throw new Error('No workspace ID');
      return getWorkspaceMembers(workspaceId);
    },
    enabled: !!workspaceId,
    staleTime: STALE_TIMES.members,
  });
}

export function useProjectBoardPermissions(boardId: string | null) {
  return useQuery({
    queryKey: projectKeys.boardPermissions(boardId ?? ''),
    queryFn: async () => {
      if (!boardId) throw new Error('No board ID');
      return getProjectBoardRolePresets(boardId);
    },
    enabled: !!boardId,
    staleTime: STALE_TIMES.members,
  });
}

// ============================================================================
// Board Mutations
// ============================================================================

/**
 * Create a new board with optimistic update
 */
export function useCreateBoard(workspaceAppId: string | null) {
  const queryClient = useQueryClient();
  const boardsKey = projectKeys.boards(workspaceAppId ?? '');

  return useMutation({
    mutationFn: async (data: {
      name: string;
      description?: string;
      icon?: string;
      color?: string;
    }) => {
      if (!workspaceAppId) throw new Error('No workspace app ID');
      return createProjectBoard({ workspace_app_id: workspaceAppId, ...data });
    },

    onMutate: async (newBoardData) => {
      await queryClient.cancelQueries({ queryKey: boardsKey });
      const previousBoards = queryClient.getQueryData<ProjectBoard[]>(boardsKey);

      const inferredWorkspaceId = previousBoards?.[0]?.workspace_id ?? '';
      const nextPosition = previousBoards?.length
        ? Math.max(...previousBoards.map((b) => b.position)) + 1
        : 0;
      const nextIssueNumber = previousBoards?.length
        ? Math.max(...previousBoards.map((b) => b.next_issue_number)) + 1
        : 1;

      // Optimistic add with temp ID
      const tempBoard: ProjectBoard = {
        id: `temp-${Date.now()}`,
        workspace_id: inferredWorkspaceId,
        workspace_app_id: workspaceAppId!,
        name: newBoardData.name,
        description: newBoardData.description,
        icon: newBoardData.icon,
        color: newBoardData.color,
        position: nextPosition,
        next_issue_number: nextIssueNumber,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      queryClient.setQueryData<ProjectBoard[]>(boardsKey, (old) =>
        old ? [...old, tempBoard] : [tempBoard]
      );

      return { previousBoards, tempId: tempBoard.id };
    },

    onSuccess: (result, _variables, context) => {
      // Replace temp with real board
      queryClient.setQueryData<ProjectBoard[]>(boardsKey, (old) =>
        old?.map((b) => (b.id === context?.tempId ? result.board : b))
      );
      // Also cache the initial states for this board
      queryClient.setQueryData(
        projectKeys.boardData(result.board.id),
        { states: normalizeStates(result.states), issues: [], labels: [] }
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoards) {
        queryClient.setQueryData(boardsKey, context.previousBoards);
      }
    },
  });
}

/**
 * Update a board with optimistic update
 */
export function useUpdateBoard(workspaceAppId: string | null) {
  const queryClient = useQueryClient();
  const boardsKey = projectKeys.boards(workspaceAppId ?? '');

  return useMutation({
    mutationFn: async ({
      boardId,
      updates,
    }: {
      boardId: string;
      updates: Partial<Pick<ProjectBoard, 'name' | 'description' | 'icon' | 'color'>>;
    }) => updateProjectBoard(boardId, updates),

    onMutate: async ({ boardId, updates }) => {
      await queryClient.cancelQueries({ queryKey: boardsKey });
      const previousBoards = queryClient.getQueryData<ProjectBoard[]>(boardsKey);

      queryClient.setQueryData<ProjectBoard[]>(boardsKey, (old) =>
        old?.map((b) => (b.id === boardId ? { ...b, ...updates } : b))
      );

      return { previousBoards };
    },

    onSuccess: (updated) => {
      queryClient.setQueryData<ProjectBoard[]>(boardsKey, (old) =>
        old?.map((b) => (b.id === updated.id ? updated : b))
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoards) {
        queryClient.setQueryData(boardsKey, context.previousBoards);
      }
    },
  });
}

/**
 * Delete a board with optimistic update
 */
export function useDeleteBoard(workspaceAppId: string | null) {
  const queryClient = useQueryClient();
  const boardsKey = projectKeys.boards(workspaceAppId ?? '');

  return useMutation({
    mutationFn: (boardId: string) => deleteProjectBoard(boardId),

    onMutate: async (boardId) => {
      await queryClient.cancelQueries({ queryKey: boardsKey });
      const previousBoards = queryClient.getQueryData<ProjectBoard[]>(boardsKey);

      queryClient.setQueryData<ProjectBoard[]>(boardsKey, (old) =>
        old?.filter((b) => b.id !== boardId)
      );

      // Also remove cached board data
      queryClient.removeQueries({ queryKey: projectKeys.boardData(boardId) });

      return { previousBoards, boardId };
    },

    onError: (_err, _boardId, context) => {
      if (context?.previousBoards) {
        queryClient.setQueryData(boardsKey, context.previousBoards);
      }
    },
  });
}

// ============================================================================
// State/Column Mutations
// ============================================================================

/**
 * Create a new state/column with optimistic update
 */
export function useCreateState(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async (data: { name: string; color?: string; is_done?: boolean }) => {
      if (!boardId) throw new Error('No board ID');
      return createProjectState(boardId, data);
    },

    onMutate: async (newStateData) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      const tempState: ProjectState = {
        id: `temp-${Date.now()}`,
        board_id: boardId!,
        name: newStateData.name,
        color: newStateData.color,
        is_done: newStateData.is_done ?? false,
        position: (previousBoardData?.states.length ?? 0),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old ? { ...old, states: [...old.states, normalizeTodoStateColor(tempState)] } : old
      );

      return { previousBoardData, tempId: tempState.id };
    },

    onSuccess: (newState, _variables, context) => {
      queryClient.setQueryData(boardDataKey, (old: { states: ProjectState[]; issues: ProjectIssue[]; labels: ProjectLabel[] } | undefined) =>
        old ? { ...old, states: old.states.map((s) => (s.id === context?.tempId ? normalizeTodoStateColor(newState) : s)) } : old
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

/**
 * Update a state/column with optimistic update
 */
export function useUpdateState(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({
      stateId,
      updates,
    }: {
      stateId: string;
      updates: { name?: string; color?: string; is_done?: boolean };
    }) => updateProjectState(stateId, updates),

    onMutate: async ({ stateId, updates }) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              states: old.states.map((s) =>
                s.id === stateId ? normalizeTodoStateColor({ ...s, ...updates }) : s
              ),
            }
          : old
      );

      return { previousBoardData };
    },

    onSuccess: (updated) => {
      queryClient.setQueryData(boardDataKey, (old: { states: ProjectState[]; issues: ProjectIssue[]; labels: ProjectLabel[] } | undefined) =>
        old ? { ...old, states: old.states.map((s) => (s.id === updated.id ? normalizeTodoStateColor(updated) : s)) } : old
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

/**
 * Delete a state/column with optimistic update
 */
export function useDeleteState(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: (stateId: string) => deleteProjectState(stateId),

    onMutate: async (stateId) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              states: old.states.filter((s) => s.id !== stateId),
              issues: old.issues.filter((i) => i.state_id !== stateId),
            }
          : old
      );

      return { previousBoardData };
    },

    onError: (_err, _stateId, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

/**
 * Reorder states/columns with optimistic update
 */
export function useReorderStates(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async (items: { id: string; position: number }[]) => {
      if (!boardId) throw new Error('No board ID');
      return reorderProjectStates(boardId, items);
    },

    onMutate: async (items) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              states: old.states.map((s) => {
                const match = items.find((i) => i.id === s.id);
                return match ? { ...s, position: match.position } : s;
              }),
            }
          : old
      );

      return { previousBoardData };
    },

    onError: (_err, _items, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: boardDataKey });
    },
  });
}

// ============================================================================
// Issue/Card Mutations
// ============================================================================

/**
 * Create a new issue/card with optimistic update
 */
export function useCreateIssue(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async (data: {
      state_id: string;
      title: string;
      description?: string;
      priority?: number;
      due_at?: string;
      label_ids?: string[];
      assignee_ids?: string[];
    }) => {
      if (!boardId) throw new Error('No board ID');
      return createProjectIssue({ board_id: boardId, ...data });
    },

    onMutate: async (newIssueData) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      // Calculate position (max + 1 in target state)
      const columnIssues = previousBoardData?.issues.filter(
        (i) => i.state_id === newIssueData.state_id
      ) ?? [];
      const maxPosition = columnIssues.length > 0
        ? Math.max(...columnIssues.map((c) => c.position))
        : -1;

      const tempIssue: ProjectIssue = {
        id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        board_id: boardId!,
        state_id: newIssueData.state_id,
        number: Date.now(),
        title: newIssueData.title,
        description: newIssueData.description,
        priority: newIssueData.priority ?? 0,
        due_at: newIssueData.due_at,
        label_objects: [],
        assignees: [],
        position: maxPosition + 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old ? { ...old, issues: [...old.issues, tempIssue] } : old
      );

      return { previousBoardData, tempId: tempIssue.id };
    },

    onSuccess: (newIssue, _variables, context) => {
      const tempId = context?.tempId;
      queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) => {
        if (!old || !tempId) return old;
        const tempIssue = old.issues.find((issue) => issue.id === tempId);
        if (!tempIssue) return old;

        const mergedIssue = mergeTempIssueIntoCreatedIssue(newIssue, tempIssue);
        return {
          ...old,
          issues: old.issues.map((issue) => (issue.id === tempId ? mergedIssue : issue)),
        };
      });

      if (tempId) {
        void flushPendingTempIssueOps({
          tempIssueId: tempId,
          realIssueId: newIssue.id,
          queryClient,
          boardDataKey,
        });
      }
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
      if (context?.tempId) {
        pendingTempIssueOps.delete(context.tempId);
      }
    },
  });
}

/**
 * Update an issue/card with optimistic update
 */
export function useUpdateIssue(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({
      issueId,
      updates,
    }: {
      issueId: string;
      updates: UpdateIssueInput;
    }) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'update', updates });
        return getCachedIssue(queryClient, boardDataKey, issueId) ?? buildFallbackIssue(issueId, boardId);
      }
      return updateProjectIssue(issueId, updates);
    },

    onMutate: async ({ issueId, updates }) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      // Build optimistic update, handling clear flags
      const optimisticUpdates: Partial<ProjectIssue> = { ...updates };
      if (updates.clear_due_at) {
        optimisticUpdates.due_at = undefined;
      }
      if (updates.clear_images) {
        optimisticUpdates.image_r2_keys = [];
        optimisticUpdates.image_urls = [];
      }

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              issues: old.issues.map((i) =>
                i.id === issueId ? { ...i, ...optimisticUpdates } : i
              ),
            }
          : old
      );

      return { previousBoardData };
    },

    onSuccess: (updated) => {
      queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) =>
        old ? { ...old, issues: old.issues.map((i) => (i.id === updated.id ? updated : i)) } : old
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

export function useIssueApprovalActions(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  const replaceIssue = (updated: ProjectIssue) => {
    queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) =>
      old ? { ...old, issues: old.issues.map((issue) => (issue.id === updated.id ? updated : issue)) } : old
    );
  };

  const requestApproval = useMutation({
    mutationFn: ({ issueId, approverId, note }: { issueId: string; approverId: string; note?: string }) =>
      requestIssueApproval(issueId, approverId, note),
    onSuccess: replaceIssue,
  });

  const approveApproval = useMutation({
    mutationFn: ({ issueId, note }: { issueId: string; note?: string }) =>
      approveIssueApproval(issueId, note),
    onSuccess: replaceIssue,
  });

  const rejectApproval = useMutation({
    mutationFn: ({ issueId, note }: { issueId: string; note: string }) =>
      rejectIssueApproval(issueId, note),
    onSuccess: replaceIssue,
  });

  const unlockApproval = useMutation({
    mutationFn: ({ issueId }: { issueId: string }) => unlockIssueApproval(issueId),
    onSuccess: replaceIssue,
  });

  return { requestApproval, approveApproval, rejectApproval, unlockApproval };
}

export function useIssueAttachments(issueId: string | null) {
  return useQuery({
    queryKey: projectKeys.attachments(issueId ?? ''),
    queryFn: async () => {
      if (!issueId) throw new Error('No issue ID');
      const result = await getIssueAttachments(issueId);
      return result.attachments;
    },
    enabled: !!issueId && !issueId.startsWith('temp-'),
    staleTime: STALE_TIMES.attachments,
  });
}

export function useAttachmentVersions(attachmentId: string | null) {
  return useQuery({
    queryKey: projectKeys.attachmentVersions(attachmentId ?? ''),
    queryFn: async () => {
      if (!attachmentId) throw new Error('No attachment ID');
      const result = await getAttachmentVersions(attachmentId);
      return result.versions;
    },
    enabled: !!attachmentId,
    staleTime: STALE_TIMES.attachments,
  });
}

export function useUploadAttachmentVersion(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({
      issueId,
      file,
      attachmentId,
    }: {
      issueId: string;
      file: File;
      attachmentId?: string;
    }) => {
      const upload = await initiateIssueAttachmentUpload(issueId, {
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        file_size: file.size,
      });

      const put = await fetch(upload.upload_url, {
        method: 'PUT',
        body: file,
        headers: upload.headers,
      });
      if (!put.ok) {
        throw new Error('Attachment upload failed');
      }

      return confirmIssueAttachmentVersion(issueId, {
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        file_size: file.size,
        r2_key: upload.r2_key,
        attachment_id: attachmentId,
      });
    },
    onSuccess: (attachment, variables) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.attachments(variables.issueId) });
      queryClient.invalidateQueries({ queryKey: projectKeys.attachmentVersions(attachment.id) });
      queryClient.invalidateQueries({ queryKey: boardDataKey });
    },
  });
}

export function useAttachmentVersionUrl() {
  return useMutation({
    mutationFn: (versionId: string) => getAttachmentVersionUrl(versionId),
  });
}

/**
 * Delete an issue/card with optimistic update
 */
export function useDeleteIssue(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async (issueId: string) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'delete' });
        return { status: 'deleted' };
      }
      return deleteProjectIssue(issueId);
    },

    onMutate: async (issueId) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old ? { ...old, issues: old.issues.filter((i) => i.id !== issueId) } : old
      );

      // Also remove cached comments for this issue
      queryClient.removeQueries({ queryKey: projectKeys.comments(issueId) });

      return { previousBoardData };
    },

    onError: (_err, _issueId, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }

      const message = _err instanceof Error ? _err.message : 'Failed to delete card';
      const isPermissionError =
        message.includes('403') || message.toLowerCase().includes('permission');
      toast.error(
        isPermissionError
          ? 'Only the card creator or workspace admins can delete this card'
          : 'Failed to delete card'
      );
    },
  });
}

/**
 * Move an issue to a different state with optimistic update
 */
export function useMoveIssue(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({
      issueId,
      targetStateId,
      position,
    }: {
      issueId: string;
      targetStateId: string;
      position: number;
    }) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'move', targetStateId, position });
        return (
          getCachedIssue(queryClient, boardDataKey, issueId) ??
          { ...buildFallbackIssue(issueId, boardId), state_id: targetStateId, position }
        );
      }
      return moveProjectIssue(issueId, targetStateId, position);
    },

    onMutate: async ({ issueId }) => {
      // Cancel any in-flight queries and save previous state for rollback
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      // Note: Optimistic update is done synchronously in KanbanBoard before calling mutate
      // This onMutate just saves the state for potential rollback
      return { previousBoardData, issueId };
    },

    onSuccess: (updatedIssue, _variables, context) => {
      if (context?.issueId && isTempIssueId(context.issueId)) return;
      // Update cache with ONLY the fields that move affects
      // Don't spread entire response - it may have null for joined fields (assignees, labels)
      // that Pydantic sets to null when the raw DB row doesn't include them
      queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) => {
        if (!old) return old;
        return {
          ...old,
          issues: old.issues.map((issue) =>
            issue.id === context?.issueId
              ? {
                  ...issue,
                  state_id: updatedIssue.state_id,
                  position: updatedIssue.position,
                  updated_at: updatedIssue.updated_at,
                }
              : issue
          ),
        };
      });
    },

    onError: (_err, _variables, context) => {
      // Rollback to previous state on error
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },

    // Don't invalidate on success - we've already updated with server response
    // Only invalidate on error is handled by onError rollback
  });
}

/**
 * Reorder issues within a state with optimistic update
 */
export function useReorderIssues(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({
      stateId,
      items,
    }: {
      stateId: string;
      items: { id: string; position: number }[];
    }) => reorderProjectIssues(stateId, items),

    onMutate: async ({ items }) => {
      // Cancel any in-flight queries and save previous state for rollback
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      // Note: Optimistic update is done synchronously in KanbanBoard before calling mutate
      return { previousBoardData, items };
    },

    onSuccess: () => {
      // Server confirmed the reorder - optimistic update was correct
      // No need to update cache, it's already in the right state
    },

    onError: (_err, _variables, context) => {
      // Rollback to previous state on error
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },

    // Don't invalidate - optimistic update is already applied and server confirmed
  });
}

// ============================================================================
// Label Mutations
// ============================================================================

/**
 * Create a new label with optimistic update
 */
export function useCreateLabel(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async (data: { name: string; color?: string }) => {
      if (!boardId) throw new Error('No board ID');
      return createProjectLabel(boardId, data.name, data.color);
    },

    onMutate: async (newLabelData) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<{
        states: ProjectState[];
        issues: ProjectIssue[];
        labels: ProjectLabel[];
      }>(boardDataKey);

      const tempLabel: ProjectLabel = {
        id: `temp-${Date.now()}`,
        board_id: boardId!,
        name: newLabelData.name,
        color: newLabelData.color ?? '#6366F1',
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old ? { ...old, labels: [...old.labels, tempLabel] } : old
      );

      return { previousBoardData, tempId: tempLabel.id };
    },

    onSuccess: (newLabel, _variables, context) => {
      queryClient.setQueryData(boardDataKey, (old: { states: ProjectState[]; issues: ProjectIssue[]; labels: ProjectLabel[] } | undefined) =>
        old ? { ...old, labels: old.labels.map((l) => (l.id === context?.tempId ? newLabel : l)) } : old
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

/**
 * Toggle a label on an issue with optimistic update
 */
export function useToggleIssueLabel(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({ issueId, labelId, hasLabel }: { issueId: string; labelId: string; hasLabel: boolean }) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'toggle_label', labelId, hasLabel });
        if (hasLabel) {
          return { status: 'removed' };
        }
        return { id: `temp-${Date.now()}`, issue_id: issueId, label_id: labelId };
      }
      if (hasLabel) {
        return removeLabelFromIssue(issueId, labelId);
      } else {
        return addLabelToIssue(issueId, labelId);
      }
    },

    onMutate: async ({ issueId, labelId, hasLabel }) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      const label = previousBoardData?.labels.find((l) => l.id === labelId);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) => {
        if (!old) return old;
        return {
          ...old,
          issues: old.issues.map((issue) => {
            if (issue.id !== issueId) return issue;
            if (hasLabel) {
              return {
                ...issue,
                label_objects: (issue.label_objects || []).filter((l) => l.id !== labelId),
              };
            } else {
              return {
                ...issue,
                label_objects: [...(issue.label_objects || []), label!],
              };
            }
          }),
        };
      });

      return { previousBoardData };
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

// ============================================================================
// Assignee Mutations
// ============================================================================

/**
 * Add an assignee to an issue with optimistic update
 */
export function useAddAssignee(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({ issueId, userId }: { issueId: string; userId: string }) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'add_assignee', userId });
        return (
          getCachedIssue(queryClient, boardDataKey, issueId)?.assignees?.find(
            (assignee) => assignee.user_id === userId
          ) ?? {
            id: `temp-${Date.now()}`,
            issue_id: issueId,
            user_id: userId,
            created_at: new Date().toISOString(),
          }
        );
      }
      return addIssueAssignee(issueId, userId);
    },

    onMutate: async ({ issueId, userId }) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      const tempAssignee: ProjectIssueAssignee = {
        id: `temp-${Date.now()}`,
        issue_id: issueId,
        user_id: userId,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              issues: old.issues.map((issue) =>
                issue.id === issueId
                  ? { ...issue, assignees: [...(issue.assignees || []), tempAssignee] }
                  : issue
              ),
            }
          : old
      );

      return { previousBoardData, tempId: tempAssignee.id };
    },

    onSuccess: (realAssignee, { issueId }, context) => {
      if (isTempIssueId(issueId)) return;
      queryClient.setQueryData(boardDataKey, (old: BoardData | undefined) =>
        old
          ? {
              ...old,
              issues: old.issues.map((issue) =>
                issue.id === issueId
                  ? {
                      ...issue,
                      assignees: (issue.assignees || []).map((a) =>
                        a.id === context?.tempId ? realAssignee : a
                      ),
                    }
                  : issue
              ),
            }
          : old
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

/**
 * Remove an assignee from an issue with optimistic update
 */
export function useRemoveAssignee(boardId: string | null) {
  const queryClient = useQueryClient();
  const boardDataKey = projectKeys.boardData(boardId ?? '');

  return useMutation({
    mutationFn: async ({ issueId, userId }: { issueId: string; userId: string }) => {
      if (isTempIssueId(issueId)) {
        queuePendingTempIssueOp(issueId, { type: 'remove_assignee', userId });
        return { status: 'removed' };
      }
      return removeIssueAssignee(issueId, userId);
    },

    onMutate: async ({ issueId, userId }) => {
      await queryClient.cancelQueries({ queryKey: boardDataKey });
      const previousBoardData = queryClient.getQueryData<BoardData>(boardDataKey);

      queryClient.setQueryData(boardDataKey, (old: typeof previousBoardData) =>
        old
          ? {
              ...old,
              issues: old.issues.map((issue) =>
                issue.id === issueId
                  ? { ...issue, assignees: (issue.assignees || []).filter((a) => a.user_id !== userId) }
                  : issue
              ),
            }
          : old
      );

      return { previousBoardData };
    },

    onError: (_err, _variables, context) => {
      if (context?.previousBoardData) {
        queryClient.setQueryData(boardDataKey, context.previousBoardData);
      }
    },
  });
}

// ============================================================================
// Comment Mutations
// ============================================================================

/**
 * Create a new comment with optimistic update
 */
export function useCreateComment(issueId: string | null) {
  const queryClient = useQueryClient();
  const commentsKey = projectKeys.comments(issueId ?? '');

  return useMutation({
    mutationFn: async (blocks: ContentBlock[]) => {
      if (!issueId) throw new Error('No issue ID');
      return createIssueComment(issueId, blocks);
    },

    onMutate: async (blocks) => {
      await queryClient.cancelQueries({ queryKey: commentsKey });
      const previousComments = queryClient.getQueryData<IssueComment[]>(commentsKey);

      const { user: currentUser, userProfile } = useAuthStore.getState();

      const tempComment: IssueComment = {
        id: `temp-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        issue_id: issueId!,
        user_id: currentUser?.id || '',
        blocks,
        is_edited: false,
        created_at: new Date().toISOString(),
        reactions: [],
        user: currentUser
          ? {
              id: currentUser.id,
              email: currentUser.email,
              name: userProfile?.name || currentUser.user_metadata?.name,
              avatar_url: userProfile?.avatar_url || currentUser.user_metadata?.avatar_url,
            }
          : undefined,
      };

      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old ? [...old, tempComment] : [tempComment]
      );

      return { previousComments, tempId: tempComment.id };
    },

    onSuccess: (newComment, _blocks, context) => {
      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) => {
        if (!old) return old;
        // Handle race condition where realtime arrived first
        const realtimeAlreadyAdded = old.some((c) => c.id === newComment.id);
        if (realtimeAlreadyAdded) {
          return old.filter((c) => c.id !== context?.tempId);
        }
        return old.map((c) => (c.id === context?.tempId ? newComment : c));
      });
    },

    onError: (_err, _blocks, context) => {
      if (context?.previousComments) {
        queryClient.setQueryData(commentsKey, context.previousComments);
      }
    },
  });
}

/**
 * Update a comment with optimistic update
 */
export function useUpdateComment(issueId: string | null) {
  const queryClient = useQueryClient();
  const commentsKey = projectKeys.comments(issueId ?? '');

  return useMutation({
    mutationFn: async ({ commentId, blocks }: { commentId: string; blocks: ContentBlock[] }) =>
      updateIssueComment(commentId, blocks),

    onMutate: async ({ commentId, blocks }) => {
      await queryClient.cancelQueries({ queryKey: commentsKey });
      const previousComments = queryClient.getQueryData<IssueComment[]>(commentsKey);

      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.map((c) =>
          c.id === commentId
            ? { ...c, blocks, is_edited: true, edited_at: new Date().toISOString() }
            : c
        )
      );

      return { previousComments };
    },

    onSuccess: (updated) => {
      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.map((c) => (c.id === updated.id ? updated : c))
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousComments) {
        queryClient.setQueryData(commentsKey, context.previousComments);
      }
    },
  });
}

/**
 * Delete a comment with optimistic update
 */
export function useDeleteComment(issueId: string | null) {
  const queryClient = useQueryClient();
  const commentsKey = projectKeys.comments(issueId ?? '');

  return useMutation({
    mutationFn: (commentId: string) => deleteIssueComment(commentId),

    onMutate: async (commentId) => {
      await queryClient.cancelQueries({ queryKey: commentsKey });
      const previousComments = queryClient.getQueryData<IssueComment[]>(commentsKey);

      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.filter((c) => c.id !== commentId)
      );

      return { previousComments };
    },

    onError: (_err, _commentId, context) => {
      if (context?.previousComments) {
        queryClient.setQueryData(commentsKey, context.previousComments);
      }
    },
  });
}

/**
 * Add a reaction to a comment with optimistic update
 */
export function useAddCommentReaction(issueId: string | null) {
  const queryClient = useQueryClient();
  const commentsKey = projectKeys.comments(issueId ?? '');

  return useMutation({
    mutationFn: async ({ commentId, emoji }: { commentId: string; emoji: string }) =>
      addCommentReaction(commentId, emoji),

    onMutate: async ({ commentId, emoji }) => {
      await queryClient.cancelQueries({ queryKey: commentsKey });
      const previousComments = queryClient.getQueryData<IssueComment[]>(commentsKey);

      const currentUserId = useAuthStore.getState().user?.id || '';
      const tempReaction: CommentReaction = {
        id: `temp-${Date.now()}`,
        comment_id: commentId,
        user_id: currentUserId,
        emoji,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.map((c) =>
          c.id === commentId
            ? { ...c, reactions: [...(c.reactions || []), tempReaction] }
            : c
        )
      );

      return { previousComments, tempId: tempReaction.id };
    },

    onSuccess: (reaction, { commentId }, context) => {
      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.map((c) => {
          if (c.id !== commentId) return c;
          const reactions = c.reactions || [];
          // Handle race condition where realtime arrived first
          const realtimeAlreadyAdded = reactions.some((r) => r.id === reaction.id);
          return {
            ...c,
            reactions: realtimeAlreadyAdded
              ? reactions.filter((r) => r.id !== context?.tempId)
              : reactions.map((r) => (r.id === context?.tempId ? reaction : r)),
          };
        })
      );
    },

    onError: (_err, _variables, context) => {
      if (context?.previousComments) {
        queryClient.setQueryData(commentsKey, context.previousComments);
      }
    },
  });
}

/**
 * Remove a reaction from a comment with optimistic update
 */
export function useRemoveCommentReaction(issueId: string | null) {
  const queryClient = useQueryClient();
  const commentsKey = projectKeys.comments(issueId ?? '');

  return useMutation({
    mutationFn: async ({ commentId, emoji }: { commentId: string; emoji: string }) =>
      removeCommentReaction(commentId, emoji),

    onMutate: async ({ commentId, emoji }) => {
      await queryClient.cancelQueries({ queryKey: commentsKey });
      const previousComments = queryClient.getQueryData<IssueComment[]>(commentsKey);

      const currentUserId = useAuthStore.getState().user?.id;

      queryClient.setQueryData<IssueComment[]>(commentsKey, (old) =>
        old?.map((c) =>
          c.id === commentId
            ? {
                ...c,
                reactions: (c.reactions || []).filter(
                  (r) => !(r.emoji === emoji && r.user_id === currentUserId)
                ),
              }
            : c
        )
      );

      return { previousComments };
    },

    onError: (_err, _variables, context) => {
      if (context?.previousComments) {
        queryClient.setQueryData(commentsKey, context.previousComments);
      }
    },
  });
}

// ============================================================================
// Prefetch Helpers
// ============================================================================

/**
 * Prefetch a board's data for faster navigation
 */
export function usePrefetchBoard() {
  const queryClient = useQueryClient();

  return (boardId: string) => {
    queryClient.prefetchQuery({
      queryKey: projectKeys.boardData(boardId),
      queryFn: async () => {
        const [statesResult, issuesResult, labelsResult] = await Promise.all([
          getProjectStates(boardId),
          getProjectIssues(boardId),
          getProjectLabels(boardId),
        ]);
        return {
          states: normalizeStates(statesResult.states),
          issues: issuesResult.issues,
          labels: labelsResult.labels,
        };
      },
      staleTime: STALE_TIMES.boardData,
    });
  };
}

/**
 * Prefetch all boards for a workspace
 */
export function usePrefetchBoards() {
  const queryClient = useQueryClient();

  return async (workspaceAppId: string) => {
    const boards = queryClient.getQueryData<ProjectBoard[]>(
      projectKeys.boards(workspaceAppId)
    );
    if (!boards) return;

    // Prefetch all boards in parallel for instant switching
    await Promise.all(boards.map((board) => prefetchBoardData(board.id)));
  };
}

/**
 * Prefetch comments for an issue
 */
export function usePrefetchComments() {
  const queryClient = useQueryClient();

  return (issueId: string) => {
    if (issueId.startsWith('temp-')) return;
    queryClient.prefetchQuery({
      queryKey: projectKeys.comments(issueId),
      queryFn: async () => {
        const result = await getIssueComments(issueId);
        return result.comments;
      },
      staleTime: STALE_TIMES.comments,
    });
  };
}

// ============================================================================
// Utility Hooks
// ============================================================================

/**
 * Get sorted columns for a board from cached data
 */
export function useProjectColumns(boardId: string | null) {
  const { data } = useProjectBoard(boardId);
  if (!data) return [];
  return [...data.states].sort((a, b) => a.position - b.position);
}

/**
 * Get sorted issues for a column from cached data
 */
export function useColumnIssues(boardId: string | null, stateId: string | null) {
  const { data } = useProjectBoard(boardId);
  if (!data || !stateId) return [];
  return data.issues
    .filter((i) => i.state_id === stateId)
    .sort((a, b) => a.position - b.position);
}

/**
 * Get a single issue from cached data
 */
export function useIssue(boardId: string | null, issueId: string | null) {
  const { data } = useProjectBoard(boardId);
  if (!data || !issueId) return null;
  return data.issues.find((i) => i.id === issueId) ?? null;
}

// ============================================================================
// Standalone Prefetch Functions (for use outside React components)
// ============================================================================

import { queryClient } from '../../lib/queryClient';

/**
 * Prefetch all project data for a workspace.
 * Call this outside of React components (e.g., in preloader).
 */
/**
 * Helper to prefetch a single board's data
 */
async function prefetchBoardData(boardId: string): Promise<void> {
  await queryClient.prefetchQuery({
    queryKey: projectKeys.boardData(boardId),
    queryFn: async () => {
      const [statesResult, issuesResult, labelsResult] = await Promise.all([
        getProjectStates(boardId),
        getProjectIssues(boardId),
        getProjectLabels(boardId),
      ]);
      return {
        states: normalizeStates(statesResult.states),
        issues: issuesResult.issues,
        labels: labelsResult.labels,
      };
    },
    staleTime: STALE_TIMES.boardData,
  });
}

export async function prefetchProjectsData(
  workspaceAppId: string,
  workspaceId: string
): Promise<void> {
  // Prefetch boards list
  const boards = await queryClient.fetchQuery({
    queryKey: projectKeys.boards(workspaceAppId),
    queryFn: async () => {
      const result = await getProjectBoards(workspaceAppId);
      return result.boards;
    },
    staleTime: STALE_TIMES.boards,
  });

  // Prefetch members for the workspace
  queryClient.prefetchQuery({
    queryKey: projectKeys.members(workspaceId),
    queryFn: () => getWorkspaceMembers(workspaceId),
    staleTime: STALE_TIMES.members,
  });

  // Prefetch ALL boards' data in parallel for instant switching
  if (boards.length > 0) {
    await Promise.all(boards.map((board) => prefetchBoardData(board.id)));
  }
}

/**
 * Background prefetch project data (doesn't block, just warms cache).
 * Call this outside of React components.
 */
export async function prefetchProjectsDataBackground(
  workspaceAppId: string,
  workspaceId: string
): Promise<void> {
  // Fetch boards list
  const boards = await queryClient.fetchQuery({
    queryKey: projectKeys.boards(workspaceAppId),
    queryFn: async () => {
      const result = await getProjectBoards(workspaceAppId);
      return result.boards;
    },
    staleTime: STALE_TIMES.boards,
  });

  // Prefetch members
  queryClient.prefetchQuery({
    queryKey: projectKeys.members(workspaceId),
    queryFn: () => getWorkspaceMembers(workspaceId),
    staleTime: STALE_TIMES.members,
  });

  // Prefetch ALL boards' data for instant switching between boards
  if (boards.length > 0) {
    await Promise.all(boards.map((board) => prefetchBoardData(board.id)));
  }
}
