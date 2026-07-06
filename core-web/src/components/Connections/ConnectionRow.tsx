import { RefreshCw, RotateCw, Trash2 } from 'lucide-react';
import { ScopeList } from './ScopeList';
import { StatusBadge } from './StatusBadge';
import type { Connection } from './types';

interface ConnectionRowProps {
  connection: Connection;
  canManage?: boolean;
  isBusy?: boolean;
  onReconnect?: (id: string) => void;
  onDisconnect?: (id: string) => void;
  onVerify?: (id: string) => void;
}

const RECONNECT_STATUSES = new Set(['error', 'expired', 'disconnected']);

export function ConnectionRow({
  connection,
  canManage = true,
  isBusy = false,
  onReconnect,
  onDisconnect,
  onVerify,
}: ConnectionRowProps) {
  const canReconnect = canManage && RECONNECT_STATUSES.has(connection.status);
  const initial = connection.displayName.charAt(0).toUpperCase();

  return (
    <div className="flex items-start gap-3 border-b border-border-gray py-3 last:border-b-0">
      <div className="h-9 w-9 shrink-0 overflow-hidden rounded-full bg-bg-gray text-sm font-semibold text-text-secondary flex items-center justify-center">
        {connection.avatarUrl ? (
          <img src={connection.avatarUrl} alt="" className="h-full w-full object-cover" />
        ) : (
          initial
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate text-sm font-medium text-text-body">{connection.displayName}</p>
          <StatusBadge status={connection.unverified ? 'unknown' : connection.status} />
          {connection.isPrimary && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-border-gray text-text-secondary">Primary</span>
          )}
        </div>
        {connection.email && (
          <p className="truncate text-xs text-text-secondary">{connection.email}</p>
        )}
        {connection.errorReason && (
          <p className="mt-1 text-xs text-red-600">{connection.errorReason}</p>
        )}
        <ScopeList grantedScopes={connection.grantedScopes} requestedScopes={connection.requestedScopes} />
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {onVerify && (
          <button
            type="button"
            onClick={() => onVerify(connection.id)}
            disabled={isBusy}
            className="rounded p-1.5 text-text-secondary hover:bg-bg-gray hover:text-text-body disabled:opacity-50"
            title="Verify status"
          >
            <RefreshCw size={15} />
          </button>
        )}
        {canReconnect && onReconnect && (
          <button
            type="button"
            onClick={() => onReconnect(connection.id)}
            disabled={isBusy}
            className="rounded p-1.5 text-text-secondary hover:bg-bg-gray hover:text-text-body disabled:opacity-50"
            title="Reconnect"
          >
            <RotateCw size={15} />
          </button>
        )}
        {canManage && onDisconnect && !connection.isPrimary && (
          <button
            type="button"
            onClick={() => onDisconnect(connection.id)}
            disabled={isBusy}
            className="rounded p-1.5 text-text-secondary hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
            title="Disconnect"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>
    </div>
  );
}
