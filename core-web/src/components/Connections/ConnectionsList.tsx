import { RefreshCw } from 'lucide-react';
import { ConnectionRow } from './ConnectionRow';
import type { Connection } from './types';

interface ConnectionsListProps {
  title?: string;
  connections: Connection[];
  isLoading?: boolean;
  isVerifying?: boolean;
  error?: string | null;
  emptyMessage?: string;
  canManage?: boolean;
  onVerifyAll?: () => void;
  onVerify?: (id: string) => void;
  onReconnect?: (id: string) => void;
  onDisconnect?: (id: string) => void;
}

export function ConnectionsList({
  title = 'Connections',
  connections,
  isLoading = false,
  isVerifying = false,
  error,
  emptyMessage = 'No connections yet',
  canManage = true,
  onVerifyAll,
  onVerify,
  onReconnect,
  onDisconnect,
}: ConnectionsListProps) {
  return (
    <div className="w-full">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-text-body">{title}</h3>
        {onVerifyAll && (
          <button
            type="button"
            onClick={onVerifyAll}
            disabled={isLoading || isVerifying}
            className="inline-flex items-center gap-1 rounded border border-border-gray px-2 py-1 text-xs text-text-secondary hover:bg-bg-gray hover:text-text-body disabled:opacity-50"
          >
            <RefreshCw size={13} className={isVerifying ? 'animate-spin' : ''} />
            Verify status
          </button>
        )}
      </div>
      {error && (
        <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      {isLoading ? (
        <div className="py-4 text-sm text-text-secondary">Loading connections...</div>
      ) : connections.length === 0 ? (
        <div className="py-4 text-sm text-text-secondary">{emptyMessage}</div>
      ) : (
        <div className="divide-y-0">
          {connections.map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              canManage={canManage}
              isBusy={isVerifying}
              onVerify={onVerify}
              onReconnect={onReconnect}
              onDisconnect={onDisconnect}
            />
          ))}
        </div>
      )}
    </div>
  );
}
