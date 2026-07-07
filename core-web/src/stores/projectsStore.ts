import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Re-export types from the API client for backward compatibility
export type {
  ProjectBoard,
  ProjectState,
  ProjectIssue,
  ProjectLabel,
  ProjectIssueAssignee,
  WorkspaceMember,
  IssueComment,
  ContentBlock,
  CommentReaction,
} from '../api/client';

// ============================================================================
// TypeScript Interfaces
// ============================================================================

interface ProjectFilters {
  search: string;
  statusIds: string[];
  assigneeIds: string[];
  labelIds: string[];
  dueFrom: string;
  dueTo: string;
  targetDueFrom: string;
  targetDueTo: string;
  types: string[];
  tags: string[];
  createdByIds: string[];
  lastEditedByIds: string[];
  complexities: number[];
  priorities: number[];
  showActiveOnly: boolean;
}

const DEFAULT_PROJECT_FILTERS: ProjectFilters = {
  search: '',
  statusIds: [],
  assigneeIds: [],
  labelIds: [],
  dueFrom: '',
  dueTo: '',
  targetDueFrom: '',
  targetDueTo: '',
  types: [],
  tags: [],
  createdByIds: [],
  lastEditedByIds: [],
  complexities: [],
  priorities: [],
  showActiveOnly: false,
};

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function numberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === 'number')
    : [];
}

function normalizeProjectFilters(filters: unknown): ProjectFilters {
  const value = filters && typeof filters === 'object'
    ? filters as Partial<ProjectFilters>
    : {};

  return {
    search: stringValue(value.search),
    statusIds: stringArray(value.statusIds),
    assigneeIds: stringArray(value.assigneeIds),
    labelIds: stringArray(value.labelIds),
    dueFrom: stringValue(value.dueFrom),
    dueTo: stringValue(value.dueTo),
    targetDueFrom: stringValue(value.targetDueFrom),
    targetDueTo: stringValue(value.targetDueTo),
    types: stringArray(value.types),
    tags: stringArray(value.tags),
    createdByIds: stringArray(value.createdByIds),
    lastEditedByIds: stringArray(value.lastEditedByIds),
    complexities: numberArray(value.complexities),
    priorities: numberArray(value.priorities),
    showActiveOnly: typeof value.showActiveOnly === 'boolean' ? value.showActiveOnly : false,
  };
}

function normalizePersistedProjectsState(
  persistedState: unknown,
  currentState: ProjectsState,
): ProjectsState {
  const persisted = persistedState && typeof persistedState === 'object'
    ? persistedState as Partial<ProjectsState>
    : {};

  return {
    ...currentState,
    ...persisted,
    filters: normalizeProjectFilters(persisted.filters ?? currentState.filters),
  };
}

// ============================================================================
// Store State Interface (UI-only state)
// ============================================================================

interface ProjectsState {
  // UI State
  activeProjectId: string | null;
  selectedCardId: string | null;
  showArchived: boolean;
  filters: ProjectFilters;

  // Context (needed for React Query hooks)
  workspaceAppId: string | null;
  workspaceId: string | null;

  // Actions
  setWorkspaceAppId: (id: string | null) => void;
  setWorkspaceId: (id: string | null) => void;
  setActiveProject: (projectId: string | null) => void;
  setSelectedCard: (cardId: string | null) => void;
  setFilters: (updates: Partial<ProjectFilters>) => void;
  clearFilters: () => void;
}

// ============================================================================
// Zustand Store (UI-only state)
// ============================================================================

export const useProjectsStore = create<ProjectsState>()(
  persist(
    (set) => ({
      // Initial state
      activeProjectId: null,
      selectedCardId: null,
      showArchived: false,
      filters: DEFAULT_PROJECT_FILTERS,
      workspaceAppId: null,
      workspaceId: null,

      // ========================================================================
      // Context Actions
      // ========================================================================

      setWorkspaceAppId: (id) => {
        set((state) => {
          if (id === state.workspaceAppId) return state;
          return {
            workspaceAppId: id,
            // Reset UI state when switching workspaces
            activeProjectId: null,
            selectedCardId: null,
          };
        });
      },

      setWorkspaceId: (id) => {
        set({ workspaceId: id });
      },

      setActiveProject: (projectId) => {
        set({ activeProjectId: projectId, selectedCardId: null });
      },

      setSelectedCard: (cardId) => {
        set({ selectedCardId: cardId });
      },

      setFilters: (updates) => {
        set((state) => ({
          filters: normalizeProjectFilters({
            ...state.filters,
            ...updates,
          }),
        }));
      },

      clearFilters: () => {
        set({
          filters: DEFAULT_PROJECT_FILTERS,
        });
      },
    }),
    {
      name: 'starterstack-projects-storage-v3', // Increment version to avoid conflicts
      partialize: (state) => ({
        showArchived: state.showArchived,
        filters: normalizeProjectFilters(state.filters),
        // Persist activeProjectId per workspace to restore on reload
        activeProjectId: state.activeProjectId,
        workspaceAppId: state.workspaceAppId,
      }),
      merge: normalizePersistedProjectsState,
    }
  )
);
