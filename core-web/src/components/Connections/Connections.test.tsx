import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConnectionRow } from './ConnectionRow';
import { ConnectionsList } from './ConnectionsList';
import { ScopeList } from './ScopeList';
import { StatusBadge } from './StatusBadge';
import {
  emailAccountToConnection,
  workspaceConnectorToConnection,
  type Connection,
} from './types';

const baseConnection: Connection = {
  id: 'conn-1',
  kind: 'user_account',
  provider: 'google',
  displayName: 'Ada Lovelace',
  email: 'ada@example.com',
  status: 'connected',
  grantedScopes: ['gmail.readonly'],
};

afterEach(() => {
  cleanup();
});

describe('Connections shared UI', () => {
  it('maps status badges to user-facing labels', () => {
    render(
      <div>
        <StatusBadge status="connected" />
        <StatusBadge status="pending" />
        <StatusBadge status="error" />
        <StatusBadge status="expired" />
        <StatusBadge status="unknown" />
      </div>
    );

    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Needs attention')).toBeInTheDocument();
    expect(screen.getByText('Expired')).toBeInTheDocument();
    expect(screen.getByText('Unverified')).toBeInTheDocument();
  });

  it('shows reconnect only for fixable statuses and manageable rows', () => {
    const onReconnect = vi.fn();
    const { rerender } = render(
      <ConnectionRow
        connection={{ ...baseConnection, status: 'expired' }}
        onReconnect={onReconnect}
      />
    );

    fireEvent.click(screen.getByTitle('Reconnect'));
    expect(onReconnect).toHaveBeenCalledWith('conn-1');

    rerender(
      <ConnectionRow
        connection={{ ...baseConnection, status: 'connected' }}
        onReconnect={onReconnect}
      />
    );
    expect(screen.queryByTitle('Reconnect')).not.toBeInTheDocument();

    rerender(
      <ConnectionRow
        connection={{ ...baseConnection, status: 'error' }}
        canManage={false}
        onReconnect={onReconnect}
      />
    );
    expect(screen.queryByTitle('Reconnect')).not.toBeInTheDocument();
  });

  it('shows an unverified badge without changing the last-known status', () => {
    render(
      <ConnectionRow
        connection={{ ...baseConnection, status: 'connected', unverified: true }}
      />
    );

    expect(screen.getByText('Unverified')).toBeInTheDocument();
  });

  it('summarizes scopes and flags missing requested scopes', () => {
    render(
      <ScopeList
        grantedScopes={['repo']}
        requestedScopes={['repo', 'workflow']}
      />
    );

    expect(screen.getByText('1 scopes granted')).toBeInTheDocument();
    expect(screen.getByText('Missing 1 requested scopes')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /1 scopes granted/i }));
    expect(screen.getByText('repo')).toBeInTheDocument();
  });

  it('renders loading, empty, and error shells', () => {
    const { rerender } = render(<ConnectionsList connections={[]} isLoading />);
    expect(screen.getByText('Loading connections...')).toBeInTheDocument();

    rerender(<ConnectionsList connections={[]} emptyMessage="Nothing connected" />);
    expect(screen.getByText('Nothing connected')).toBeInTheDocument();

    rerender(<ConnectionsList connections={[]} error="Could not verify" />);
    expect(screen.getByText('Could not verify')).toBeInTheDocument();
  });

  it('adapts backend account and connector rows to a shared connection shape', () => {
    expect(emailAccountToConnection({
      id: 'email-1',
      provider: 'google',
      provider_email: 'ada@example.com',
      provider_name: 'Ada',
      provider_avatar: 'https://example.com/avatar.png',
      is_primary: true,
      account_order: 0,
      is_active: false,
      verification_status: 'expired',
      error_reason: 'Token expired',
      scopes: ['gmail.readonly'],
    })).toMatchObject({
      id: 'email-1',
      kind: 'user_account',
      displayName: 'Ada',
      status: 'expired',
      isPrimary: true,
    });

    expect(workspaceConnectorToConnection({
      id: 'workspace-1',
      workspace_id: 'workspace',
      provider: 'github',
      display_name: 'GitHub',
      status: 'pending',
      scopes: ['repo'],
      error_reason: null,
      metadata: { requested_scopes: ['repo', 'workflow'] },
      requested_scopes: ['repo', 'workflow'],
    })).toMatchObject({
      id: 'workspace-1',
      kind: 'workspace_connector',
      displayName: 'GitHub',
      status: 'pending',
      requestedScopes: ['repo', 'workflow'],
    });
  });
});
