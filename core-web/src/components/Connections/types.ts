import type { EmailAccount, WorkspaceConnector } from '../../api/client';

export type ConnectionStatus = 'connected' | 'disconnected' | 'error' | 'pending' | 'expired' | 'unknown';

export interface Connection {
  id: string;
  kind: 'user_account' | 'workspace_connector';
  provider: string;
  displayName: string;
  email?: string;
  status: ConnectionStatus;
  grantedScopes: string[];
  requestedScopes?: string[];
  errorReason?: string | null;
  unverified?: boolean;
  lastVerifiedAt?: string | null;
  isPrimary?: boolean;
  avatarUrl?: string | null;
}

export function emailAccountToConnection(account: EmailAccount): Connection {
  return {
    id: account.id,
    kind: 'user_account',
    provider: account.provider,
    displayName: account.provider_name || account.provider_email,
    email: account.provider_email,
    status: account.verification_status || (account.is_active ? 'connected' : 'disconnected'),
    grantedScopes: account.scopes || [],
    requestedScopes: account.requested_scopes,
    errorReason: account.error_reason,
    unverified: account.unverified,
    lastVerifiedAt: account.last_verified_at,
    isPrimary: account.is_primary,
    avatarUrl: account.provider_avatar,
  };
}

export function workspaceConnectorToConnection(connector: WorkspaceConnector): Connection {
  return {
    id: connector.id,
    kind: 'workspace_connector',
    provider: connector.provider,
    displayName: connector.display_name || connector.provider,
    status: connector.status || 'unknown',
    grantedScopes: connector.scopes || [],
    requestedScopes: connector.requested_scopes,
    errorReason: connector.error_reason,
    unverified: connector.unverified,
    lastVerifiedAt: connector.last_verified_at,
  };
}
