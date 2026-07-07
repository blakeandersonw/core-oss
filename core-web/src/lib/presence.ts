export interface PresenceTrackPayload {
  user_id?: string;
  session_id?: string;
  online_at?: string;
  presence_ref?: string;
}

export type WorkspacePresenceSnapshot = Record<string, string>; // sessionId -> userId
export type WorkspacePresenceState = Record<string, WorkspacePresenceSnapshot>; // workspaceId -> snapshot
type RealtimePresenceSnapshot<T extends object> = Record<
  string,
  Array<{ presence_ref?: string } & T>
>;

const PRESENCE_SESSION_STORAGE_KEY = "starterstack.presence_session_id";

let memoryPresenceSessionId: string | null = null;

function createPresenceSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `presence-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function getPresenceSessionId() {
  if (memoryPresenceSessionId) return memoryPresenceSessionId;

  const fallback = createPresenceSessionId();

  if (typeof window === "undefined") {
    memoryPresenceSessionId = fallback;
    return memoryPresenceSessionId;
  }

  try {
    const existing = window.sessionStorage.getItem(PRESENCE_SESSION_STORAGE_KEY)?.trim();
    if (existing) {
      memoryPresenceSessionId = existing;
      return memoryPresenceSessionId;
    }
    window.sessionStorage.setItem(PRESENCE_SESSION_STORAGE_KEY, fallback);
  } catch {
    // Restrictive browser contexts can disable sessionStorage.
  }

  memoryPresenceSessionId = fallback;
  return memoryPresenceSessionId;
}

export function toWorkspacePresenceSnapshot(
  presenceState: RealtimePresenceSnapshot<PresenceTrackPayload>,
): WorkspacePresenceSnapshot {
  const snapshot: WorkspacePresenceSnapshot = {};

  for (const [presenceKey, presences] of Object.entries(presenceState)) {
    if (!Array.isArray(presences) || presences.length === 0) continue;
    const userId = presences[0].user_id;
    if (!userId) continue;
    const sessionId = presences[0].session_id || presenceKey;
    snapshot[sessionId] = userId;
  }

  return snapshot;
}

/** Collect all online user IDs across all workspace snapshots, deduped. */
export function getOnlineUserIds(workspacePresence: WorkspacePresenceState): Set<string> {
  const userIds = new Set<string>();
  for (const snapshot of Object.values(workspacePresence)) {
    for (const userId of Object.values(snapshot)) {
      userIds.add(userId);
    }
  }
  return userIds;
}

export function isUserOnline(
  workspacePresence: WorkspacePresenceState,
  userId: string,
): boolean {
  for (const snapshot of Object.values(workspacePresence)) {
    for (const uid of Object.values(snapshot)) {
      if (uid === userId) return true;
    }
  }
  return false;
}
