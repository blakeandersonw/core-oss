import type { ConnectionStatus } from './types';

const STATUS_STYLES: Record<ConnectionStatus, { label: string; classes: string }> = {
  connected: {
    label: 'Connected',
    classes: 'bg-green-50 text-green-700 border-green-200',
  },
  pending: {
    label: 'Pending',
    classes: 'bg-amber-50 text-amber-700 border-amber-200',
  },
  error: {
    label: 'Needs attention',
    classes: 'bg-red-50 text-red-700 border-red-200',
  },
  expired: {
    label: 'Expired',
    classes: 'bg-red-50 text-red-700 border-red-200',
  },
  disconnected: {
    label: 'Disconnected',
    classes: 'bg-gray-50 text-gray-600 border-gray-200',
  },
  unknown: {
    label: 'Unverified',
    classes: 'bg-gray-50 text-gray-600 border-gray-200',
  },
};

export function StatusBadge({ status }: { status: ConnectionStatus }) {
  const config = STATUS_STYLES[status] || STATUS_STYLES.unknown;
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${config.classes}`}>
      {config.label}
    </span>
  );
}
