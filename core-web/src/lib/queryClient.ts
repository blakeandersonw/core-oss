import { QueryClient } from '@tanstack/react-query';
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes - data considered fresh
      gcTime: 10 * 60 * 1000,   // 10 minutes - unused data garbage collected
      retry: 2,                  // Retry failed requests twice
      refetchOnWindowFocus: true, // Refetch when user returns to tab
      refetchOnReconnect: true,   // Refetch after network reconnect
    },
    mutations: {
      retry: 1, // Retry failed mutations once
    },
  },
});

// Persist React Query cache to localStorage for instant load on page refresh
// Created lazily to avoid issues with module initialization order
let _queryPersister: ReturnType<typeof createSyncStoragePersister> | null = null;

export function getQueryPersister() {
  if (!_queryPersister && typeof window !== 'undefined') {
    _queryPersister = createSyncStoragePersister({
      storage: window.localStorage,
      key: 'starterstack-react-query-cache',
    });
  }
  return _queryPersister;
}
