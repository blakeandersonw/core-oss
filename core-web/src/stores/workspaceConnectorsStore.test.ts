import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspaceConnectorsStore } from './workspaceConnectorsStore';
import { verifyWorkspaceConnector, type WorkspaceConnector } from '../api/client';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock('../api/client', () => ({
  deleteWorkspaceConnector: vi.fn(),
  getWorkspaceConnectors: vi.fn(),
  reconnectWorkspaceConnector: vi.fn(),
  saveWorkspaceConnector: vi.fn(),
  verifyWorkspaceConnector: vi.fn(),
  verifyWorkspaceConnectors: vi.fn(),
}));

const githubConnector: WorkspaceConnector = {
  id: 'connector-1',
  workspace_id: 'workspace-1',
  provider: 'github',
  display_name: 'GitHub',
  status: 'connected',
  scopes: ['repo'],
  error_reason: null,
};

describe('workspaceConnectorsStore', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useWorkspaceConnectorsStore.setState({
      connectorsByWorkspace: {},
      isLoading: false,
      isVerifying: false,
      error: null,
      lastVerifiedAtByWorkspace: {},
    });
  });

  it('adds a verified connector when reconnect completion is consumed before the list is loaded', async () => {
    vi.mocked(verifyWorkspaceConnector).mockResolvedValue(githubConnector);

    await useWorkspaceConnectorsStore.getState().verify('workspace-1', 'connector-1');

    expect(useWorkspaceConnectorsStore.getState().connectorsByWorkspace['workspace-1']).toEqual([
      githubConnector,
    ]);
  });
});
