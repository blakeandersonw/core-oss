import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  getBuilderProjects,
  createBuilderProject,
  getBuilderProject,
  getBuilderVersions,
  getBuilderConversation,
  type BuilderProject,
  type BuilderVersion,
  type BuilderMessage,
} from '../api/client';

export type ViewMode = 'preview' | 'code';

interface BuilderState {
  // Project list
  projects: BuilderProject[];
  isLoadingProjects: boolean;

  // Active project
  activeProjectId: string | null;
  activeProject: BuilderProject | null;

  // Versions
  versions: BuilderVersion[];
  activeVersion: BuilderVersion | null;

  // File tree (current working state)
  fileTree: Record<string, string>;

  // Conversation
  messages: BuilderMessage[];
  isLoadingMessages: boolean;

  // Generation state
  isGenerating: boolean;
  generationStatus: string | null;

  // Pending prompt (set when creating from home page)
  pendingPrompt: string | null;

  // Build errors (from Sandpack)
  buildError: string | null;

  // UI state
  viewMode: ViewMode;

  // Actions
  fetchProjects: () => Promise<void>;
  createProject: (name: string) => Promise<BuilderProject>;
  setActiveProject: (projectId: string | null) => Promise<void>;
  fetchVersions: (projectId: string) => Promise<void>;
  setActiveVersion: (version: BuilderVersion) => void;
  updateFileTree: (path: string, content: string, action: 'create' | 'update' | 'delete') => void;
  setFileTree: (fileTree: Record<string, string>) => void;
  fetchMessages: (projectId: string) => Promise<void>;
  addMessage: (message: BuilderMessage) => void;
  setIsGenerating: (generating: boolean) => void;
  setGenerationStatus: (status: string | null) => void;
  setPendingPrompt: (prompt: string | null) => void;
  setBuildError: (error: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
  reset: () => void;
}

const initialState = {
  projects: [],
  isLoadingProjects: false,
  activeProjectId: null,
  activeProject: null,
  versions: [],
  activeVersion: null,
  fileTree: {},
  messages: [],
  isLoadingMessages: false,
  isGenerating: false,
  generationStatus: null,
  pendingPrompt: null,
  buildError: null,
  viewMode: 'preview' as ViewMode,
};

export const useBuilderStore = create<BuilderState>()(
  persist(
    (set, get) => ({
      ...initialState,

      fetchProjects: async () => {
        set({ isLoadingProjects: true });
        try {
          const projects = await getBuilderProjects();
          set({ projects, isLoadingProjects: false });
        } catch (err) {
          console.error('Failed to fetch builder projects:', err);
          set({ isLoadingProjects: false });
        }
      },

      createProject: async (name: string) => {
        const project = await createBuilderProject(name);
        set((s) => ({ projects: [project, ...s.projects] }));
        return project;
      },

      setActiveProject: async (projectId: string | null) => {
        if (!projectId) {
          set({
            activeProjectId: null,
            activeProject: null,
            versions: [],
            activeVersion: null,
            fileTree: {},
            messages: [],
          });
          return;
        }

        set({ activeProjectId: projectId });

        try {
          const [project, versions] = await Promise.all([
            getBuilderProject(projectId),
            getBuilderVersions(projectId),
          ]);

          const latestVersion = versions[0] || null;
          set({
            activeProject: project,
            versions,
            activeVersion: latestVersion,
            fileTree: latestVersion?.file_tree || {},
          });

          // Fetch messages
          await get().fetchMessages(projectId);
        } catch (err) {
          console.error('Failed to load project:', err);
        }
      },

      fetchVersions: async (projectId: string) => {
        try {
          const versions = await getBuilderVersions(projectId);
          set({ versions });
        } catch (err) {
          console.error('Failed to fetch versions:', err);
        }
      },

      setActiveVersion: (version: BuilderVersion) => {
        set({
          activeVersion: version,
          fileTree: version.file_tree || {},
        });
      },

      updateFileTree: (path: string, content: string, action: 'create' | 'update' | 'delete') => {
        set((s) => {
          const newTree = { ...s.fileTree };
          if (action === 'delete') {
            delete newTree[path];
          } else {
            newTree[path] = content;
          }
          return { fileTree: newTree };
        });
      },

      setFileTree: (fileTree: Record<string, string>) => {
        set({ fileTree });
      },

      fetchMessages: async (projectId: string) => {
        set({ isLoadingMessages: true });
        try {
          const messages = await getBuilderConversation(projectId);
          set({ messages, isLoadingMessages: false });
        } catch (err) {
          console.error('Failed to fetch messages:', err);
          set({ messages: [], isLoadingMessages: false });
        }
      },

      addMessage: (message: BuilderMessage) => {
        set((s) => ({ messages: [...s.messages, message] }));
      },

      setIsGenerating: (generating: boolean) => {
        set({ isGenerating: generating });
      },

      setGenerationStatus: (status: string | null) => {
        set({ generationStatus: status });
      },

      setPendingPrompt: (prompt: string | null) => {
        set({ pendingPrompt: prompt });
      },

      setBuildError: (error: string | null) => {
        set({ buildError: error });
      },

      setViewMode: (mode: ViewMode) => {
        set({ viewMode: mode });
      },

      reset: () => {
        set(initialState);
      },
    }),
    {
      name: 'starterstack-builder-storage-v1',
      partialize: (state) => ({
        activeProjectId: state.activeProjectId,
        viewMode: state.viewMode,
      }),
    },
  ),
);
