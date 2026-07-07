# Data Caching & Preloading Strategy

**Rollback commit:** `c024976` (pre-implementation baseline)

## Overview

All mini apps use a unified preloading/caching architecture:

1. **Persist middleware** on every Zustand store — data survives page reloads
2. **Stale-While-Revalidate (SWR)** — cached data shown instantly, revalidated in background
3. **Central preloader** (`useAppPreloader`) — triggers all stores after workspaces load
4. **Workspace-scoped caching** — workspace apps cache data per workspace for instant switching

## Boot Sequence

```
Auth → Workspaces Load → useAppPreloader fires
                          ├── emailStore.preload()        (global)
                          ├── calendarStore.preload()     (global)
                          └── 500ms delay, then per workspace app:
                              ├── messagesStore.preload(appId)
                              ├── projectsStore.preload(appId, wsId)
                              └── filesStore.preload(appId)
```

## Store Pattern

Every store follows the same pattern:

```ts
preload(appId?) {
  // 1. Check staleness (5-min threshold)
  if (cache exists && fresh) return;

  // 2. Restore from persist cache (instant)
  // 3. Revalidate in background (silent, no loading spinners)
}
```

## Per-Store Details

| Store | Persist Key | Scope | Preload Strategy |
|-------|-------------|-------|-----------------|
| emailStore | `starterstack-email-storage-v5` | Global | INBOX + all folders + all accounts |
| calendarStore | `starterstack-calendar-storage-v2` | Global | All events (single fetch) |
| messagesStore | `messages-workspace-cache-v2` | Per-workspace | Channels + all channel messages |
| filesStore | `starterstack-files-storage-v2` | Per-workspace | Root folder documents |
| projectsStore | `starterstack-projects-storage-v3` | Per-workspace | All boards + all board data |

## Staleness Threshold

5 minutes (`5 * 60 * 1000 ms`). Data older than this gets silently revalidated.
