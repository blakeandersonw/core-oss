import { create } from 'zustand';
import { toast } from 'sonner';
import {
  deleteWorkspaceConnector,
  getWorkspaceConnectors,
  reconnectWorkspaceConnector,
  saveWorkspaceConnector,
  verifyWorkspaceConnector,
  verifyWorkspaceConnectors,
  type WorkspaceConnector,
} from '../api/client';

const DEFAULT_REQUESTED_SCOPES: Record<string, string[]> = {
  github: ['repo', 'issues', 'pull_requests'],
};

interface WorkspaceConnectorsState {
  connectorsByWorkspace: Record<string, WorkspaceConnector[]>;
  isLoading: boolean;
  isVerifying: boolean;
  error: string | null;
  lastVerifiedAtByWorkspace: Record<string, number>;

  connectorsForWorkspace: (workspaceId?: string | null) => WorkspaceConnector[];
  fetch: (workspaceId: string) => Promise<void>;
  addStub: (workspaceId: string, provider: string) => Promise<void>;
  verifyAll: (workspaceId: string, force?: boolean) => Promise<void>;
  verify: (workspaceId: string, connectorId: string) => Promise<void>;
  reconnect: (workspaceId: string, connectorId: string) => Promise<void>;
  disconnect: (workspaceId: string, connectorId: string) => Promise<void>;
}

export const useWorkspaceConnectorsStore = create<WorkspaceConnectorsState>()((set, get) => ({
  connectorsByWorkspace: {},
  isLoading: false,
  isVerifying: false,
  error: null,
  lastVerifiedAtByWorkspace: {},

  connectorsForWorkspace: (workspaceId) => {
    if (!workspaceId) return [];
    return get().connectorsByWorkspace[workspaceId] || [];
  },

  fetch: async (workspaceId) => {
    set({ isLoading: true, error: null });
    try {
      const connectors = await getWorkspaceConnectors(workspaceId);
      set((state) => ({
        connectorsByWorkspace: { ...state.connectorsByWorkspace, [workspaceId]: connectors },
        isLoading: false,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load connectors';
      set({ error: message, isLoading: false });
    }
  },

  addStub: async (workspaceId, provider) => {
    try {
      const connector = await saveWorkspaceConnector(workspaceId, {
        provider,
        display_name: provider.charAt(0).toUpperCase() + provider.slice(1),
        status: 'pending',
        scopes: [],
        metadata: { requested_scopes: DEFAULT_REQUESTED_SCOPES[provider] || [] },
      });
      set((state) => ({
        connectorsByWorkspace: {
          ...state.connectorsByWorkspace,
          [workspaceId]: [
            ...((state.connectorsByWorkspace[workspaceId] || []).filter((item) => item.id !== connector.id)),
            connector,
          ],
        },
      }));
      const result = await reconnectWorkspaceConnector(workspaceId, connector.id);
      if (result.redirect_url) {
        sessionStorage.setItem('reconnecting_workspace_id', workspaceId);
        sessionStorage.setItem('reconnecting_connection_id', connector.id);
        window.location.assign(result.redirect_url);
        return;
      }
      await get().verify(workspaceId, connector.id);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add connector';
      toast.error(message);
      set({ error: message });
    }
  },

  verifyAll: async (workspaceId, force = false) => {
    const lastVerifiedAt = get().lastVerifiedAtByWorkspace[workspaceId];
    if (!force && lastVerifiedAt && Date.now() - lastVerifiedAt < 30_000) return;
    set({ isVerifying: true, error: null });
    try {
      const connectors = await verifyWorkspaceConnectors(workspaceId);
      set((state) => ({
        connectorsByWorkspace: { ...state.connectorsByWorkspace, [workspaceId]: connectors },
        lastVerifiedAtByWorkspace: { ...state.lastVerifiedAtByWorkspace, [workspaceId]: Date.now() },
        isVerifying: false,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify connectors';
      toast.error(message);
      set({ error: message, isVerifying: false });
    }
  },

  verify: async (workspaceId, connectorId) => {
    set({ isVerifying: true, error: null });
    try {
      const connector = await verifyWorkspaceConnector(workspaceId, connectorId);
      set((state) => ({
        connectorsByWorkspace: {
          ...state.connectorsByWorkspace,
          [workspaceId]: (state.connectorsByWorkspace[workspaceId] || []).some((item) => item.id === connectorId)
            ? (state.connectorsByWorkspace[workspaceId] || []).map((item) =>
                item.id === connectorId ? connector : item
              )
            : [...(state.connectorsByWorkspace[workspaceId] || []), connector],
        },
        isVerifying: false,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify connector';
      toast.error(message);
      set({ error: message, isVerifying: false });
    }
  },

  reconnect: async (workspaceId, connectorId) => {
    try {
      const result = await reconnectWorkspaceConnector(workspaceId, connectorId);
      if (result.redirect_url) {
        sessionStorage.setItem('reconnecting_workspace_id', workspaceId);
        sessionStorage.setItem('reconnecting_connection_id', connectorId);
        window.location.assign(result.redirect_url);
        return;
      }
      await get().verify(workspaceId, connectorId);
      toast.success('Connector status updated');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to reconnect connector';
      toast.error(message);
      set({ error: message });
    }
  },

  disconnect: async (workspaceId, connectorId) => {
    const previous = get().connectorsByWorkspace[workspaceId] || [];
    set((state) => ({
      connectorsByWorkspace: {
        ...state.connectorsByWorkspace,
        [workspaceId]: previous.filter((item) => item.id !== connectorId),
      },
      error: null,
    }));
    try {
      await deleteWorkspaceConnector(workspaceId, connectorId);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to disconnect connector';
      toast.error(message);
      set((state) => ({
        connectorsByWorkspace: { ...state.connectorsByWorkspace, [workspaceId]: previous },
        error: message,
      }));
    }
  },
}));
