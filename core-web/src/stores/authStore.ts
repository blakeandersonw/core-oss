import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User, Session } from '@supabase/supabase-js';
import { supabase, isSupabaseConfigured } from '../lib/supabase';
import { API_BASE } from '../lib/apiBase';
import { trackEvent } from '../lib/posthog';

// UserProfile type (avoid circular import with client.ts)
export interface UserProfile {
  id: string;
  email: string;
  name?: string;
  avatar_url?: string;
  onboarding_completed_at?: string | null;
  is_super_admin?: boolean;
}

export type ProfileStatus = 'idle' | 'loading' | 'ready' | 'error';

interface AuthState {
  user: User | null;
  session: Session | null;
  userProfile: UserProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  profileStatus: ProfileStatus;
  profileError: string | null;
  // undefined = not yet loaded (wait), null = loaded + not completed, string = completed
  onboardingCompletedAt: string | null | undefined;

  // Actions
  initialize: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signInWithGoogle: (redirectToOrEvent?: unknown) => Promise<void>;
  signInWithMicrosoft: (redirectToOrEvent?: unknown) => Promise<void>;
  signUpWithEmail: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => string | null;
  fetchUserProfile: () => Promise<void>;
  updateAvatarUrl: (avatarUrl: string | null) => void;
  updateUserName: (name: string) => Promise<void>;
  completeOnboarding: () => Promise<void>;
}

let fetchProfilePromise: Promise<void> | null = null;
const completedOAuthPayloadKeys = new Set<string>();
const inFlightOAuthPayloadKeys = new Set<string>();

type SupabaseOAuthProvider = 'google' | 'azure';
type BackendOAuthProvider = 'google' | 'microsoft';
type ComposioLoginProvider = 'google' | 'microsoft';

const BACKEND_PROVIDER_MAP: Record<SupabaseOAuthProvider, BackendOAuthProvider> = {
  google: 'google',
  azure: 'microsoft',
};

const GOOGLE_OAUTH_SCOPES = [
  'openid',
  'email',
  'profile',
  'https://www.googleapis.com/auth/calendar',
  'https://www.googleapis.com/auth/gmail.modify',
];

const MICROSOFT_OAUTH_SCOPES = [
  'email',
  'User.Read',
  'Mail.ReadWrite',
  'Mail.Send',
  'Calendars.ReadWrite',
  'MailboxSettings.Read',
];

const COMPLETE_OAUTH_SCOPES: Record<BackendOAuthProvider, string[]> = {
  google: GOOGLE_OAUTH_SCOPES,
  microsoft: MICROSOFT_OAUTH_SCOPES,
};

class OAuthStartError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'OAuthStartError';
    this.status = status;
  }
}

function isFetchNetworkError(error: unknown): boolean {
  if (!(error instanceof TypeError)) return false;
  return /failed to fetch|networkerror|load failed/i.test(error.message);
}

function isSupabaseOAuthProvider(value: unknown): value is SupabaseOAuthProvider {
  return value === 'google' || value === 'azure';
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined;
}

function toEpochSeconds(value: unknown): number {
  if (typeof value !== 'string' || value.trim().length === 0) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : Math.floor(parsed / 1000);
}

function getSupabaseProvider(user: User): SupabaseOAuthProvider | undefined {
  const identities = (user.identities ?? [])
    .filter((identity): identity is typeof identity & { provider: SupabaseOAuthProvider } =>
      isSupabaseOAuthProvider(identity.provider))
    .sort((a, b) => toEpochSeconds(b.last_sign_in_at) - toEpochSeconds(a.last_sign_in_at));

  if (identities.length > 0) {
    return identities[0].provider;
  }

  const appProvider = asOptionalString(asRecord(user.app_metadata).provider);
  if (isSupabaseOAuthProvider(appProvider)) return appProvider;

  return undefined;
}

function getProviderUserId(user: User, provider: SupabaseOAuthProvider): string {
  const metadata = asRecord(user.user_metadata);
  const matchedIdentity = (user.identities ?? []).find((identity) => identity.provider === provider);
  const identityData = asRecord(matchedIdentity?.identity_data);

  const candidates = [
    asOptionalString(identityData.sub),
    asOptionalString(metadata.provider_id),
    asOptionalString(metadata.sub),
    asOptionalString(identityData.user_id),
    asOptionalString(identityData.id),
    asOptionalString(matchedIdentity?.id),
    user.id,
  ];

  return candidates.find((value): value is string => Boolean(value)) ?? user.id;
}

async function startComposioLogin(provider: ComposioLoginProvider, redirectTo?: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/composio/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider,
        redirect_to: redirectTo || window.location.href,
      }),
    });
  } catch (error) {
    if (!isFetchNetworkError(error)) throw error;
    throw new OAuthStartError(`Could not reach the auth API at ${API_BASE} to start ${provider} sign-in`);
  }

  if (!response.ok) {
    let message = `Failed to start ${provider} sign-in`;
    try {
      const errorData = (await response.json()) as { detail?: unknown; message?: unknown };
      if (typeof errorData.detail === 'string') {
        message = errorData.detail;
      } else if (typeof errorData.message === 'string') {
        message = errorData.message;
      }
    } catch {
      // Keep default message.
    }
    throw new OAuthStartError(message, response.status);
  }

  const data = (await response.json()) as { redirect_url?: unknown };
  if (typeof data.redirect_url !== 'string' || !data.redirect_url) {
    throw new Error('Composio did not return a sign-in URL');
  }

  window.location.assign(data.redirect_url);
}

async function completeOAuthConnection(session: Session): Promise<void> {
  const providerToken = asOptionalString(session.provider_token);
  const email = asOptionalString(session.user.email);
  if (!providerToken || !email) return;

  const supabaseProvider = getSupabaseProvider(session.user);
  if (!supabaseProvider) return;

  const backendProvider = BACKEND_PROVIDER_MAP[supabaseProvider];
  const providerUserId = getProviderUserId(session.user, supabaseProvider);
  const payloadKey = `${session.user.id}:${backendProvider}:${providerUserId}:${providerToken.slice(0, 24)}`;

  if (completedOAuthPayloadKeys.has(payloadKey) || inFlightOAuthPayloadKeys.has(payloadKey)) {
    return;
  }
  inFlightOAuthPayloadKeys.add(payloadKey);

  const metadata = asRecord(session.user.user_metadata);
  const name = asOptionalString(metadata.full_name) ?? asOptionalString(metadata.name) ?? email.split('@')[0];
  const avatarUrl = asOptionalString(metadata.avatar_url) ?? asOptionalString(metadata.picture);
  const payloadMetadata: Record<string, unknown> = {};
  if (asOptionalString(metadata.picture)) payloadMetadata.picture = metadata.picture;
  if (asOptionalString(metadata.full_name)) payloadMetadata.full_name = metadata.full_name;
  if (metadata.email_verified !== undefined) payloadMetadata.email_verified = metadata.email_verified;

  const payload = {
    user_id: session.user.id,
    email,
    name,
    avatar_url: avatarUrl,
    provider: backendProvider,
    provider_user_id: providerUserId,
    access_token: providerToken,
    refresh_token: asOptionalString(session.provider_refresh_token),
    scopes: COMPLETE_OAUTH_SCOPES[backendProvider],
    metadata: payloadMetadata,
  };

  try {
    const response = await fetch(`${API_BASE}/auth/complete-oauth`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let errorMessage = `Failed to complete OAuth flow (${response.status})`;
      try {
        const errorData = (await response.json()) as { detail?: unknown; message?: unknown };
        if (typeof errorData.detail === 'string') {
          errorMessage = errorData.detail;
        } else if (typeof errorData.message === 'string') {
          errorMessage = errorData.message;
        }
      } catch {
        // Ignore parse failures.
      }
      throw new Error(errorMessage);
    }

    completedOAuthPayloadKeys.add(payloadKey);
    if (completedOAuthPayloadKeys.size > 1000) {
      completedOAuthPayloadKeys.clear();
    }
  } catch (err) {
    console.error('Failed to complete OAuth provider setup:', err);
  } finally {
    inFlightOAuthPayloadKeys.delete(payloadKey);
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      session: null,
      userProfile: null,
      isLoading: true,
      isAuthenticated: false,
      profileStatus: 'idle',
      profileError: null,
      onboardingCompletedAt: undefined,

      initialize: async () => {
        if (!isSupabaseConfigured()) {
          set({ isLoading: false, profileStatus: 'idle', profileError: null });
          return;
        }

        try {
          // Get current session from Supabase's own storage
          const { data: { session }, error } = await supabase.auth.getSession();

          if (error) {
            console.error('Auth initialization error:', error);
            set({ isLoading: false, profileStatus: 'error', profileError: error.message });
            return;
          }

          set({
            user: session?.user ?? null,
            session: session ?? null,
            isAuthenticated: !!session,
            profileStatus: session ? 'loading' : 'idle',
            profileError: null,
          });

          // Fetch user profile if authenticated
          if (session) {
            await get().fetchUserProfile();
            void completeOAuthConnection(session);
          }

          set({ isLoading: false });

          // Listen for auth changes
          supabase.auth.onAuthStateChange((event, session) => {
            set({
              user: session?.user ?? null,
              session,
              isAuthenticated: !!session,
              profileStatus: session ? 'loading' : 'idle',
              profileError: null,
              ...(session ? {} : { userProfile: null, onboardingCompletedAt: undefined }),
            });
            // Fetch profile on auth change
            if (session) {
              get().fetchUserProfile();
              if (event === 'SIGNED_IN' || event === 'INITIAL_SESSION') {
                void completeOAuthConnection(session);
              }
            } else {
              set({ userProfile: null, profileStatus: 'idle', profileError: null });
            }
          });
        } catch (err) {
          console.error('Auth initialization error:', err);
          set({
            isLoading: false,
            profileStatus: 'error',
            profileError: err instanceof Error ? err.message : 'Failed to initialize authentication',
          });
        }
      },

      signInWithEmail: async (email, password) => {
        const { data, error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });

        if (error) throw error;

        set({
          user: data.user,
          session: data.session,
          isAuthenticated: true,
          profileStatus: 'loading',
          profileError: null,
        });
        await get().fetchUserProfile();
        trackEvent('signed_in', { method: 'email' });
      },

      signInWithGoogle: async (redirectToOrEvent?: unknown) => {
        const redirectTo = typeof redirectToOrEvent === 'string'
          ? redirectToOrEvent
          : undefined;
        trackEvent('sign_in_started', { method: 'google' });
        await startComposioLogin('google', redirectTo);
      },

      signInWithMicrosoft: async (redirectToOrEvent?: unknown) => {
        const redirectTo = typeof redirectToOrEvent === 'string'
          ? redirectToOrEvent
          : undefined;
        trackEvent('sign_in_started', { method: 'microsoft' });
        await startComposioLogin('microsoft', redirectTo);
      },

      signUpWithEmail: async (email, password) => {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
        });

        if (error) throw error;

        set({
          user: data.user,
          session: data.session,
          isAuthenticated: !!data.session,
          profileStatus: data.session ? 'loading' : 'idle',
          profileError: null,
        });
        if (data.session) {
          await get().fetchUserProfile();
        }
        trackEvent('signed_up', { method: 'email' });
      },

      signOut: async () => {
        trackEvent('signed_out');
        await supabase.auth.signOut();
        set({
          user: null,
          session: null,
          userProfile: null,
          isAuthenticated: false,
          profileStatus: 'idle',
          profileError: null,
          onboardingCompletedAt: undefined,
        });
      },

      getAccessToken: () => {
        return get().session?.access_token ?? null;
      },

      fetchUserProfile: async () => {
        if (fetchProfilePromise) return fetchProfilePromise;

        const token = get().session?.access_token;
        if (!token) {
          set({ profileStatus: 'idle', profileError: null });
          return;
        }

        set({ profileStatus: 'loading', profileError: null });

        fetchProfilePromise = (async () => {
          try {
            const response = await fetch(`${API_BASE}/users/me`, {
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
              },
            });

            if (response.ok) {
              const profile = (await response.json()) as UserProfile;
              set({
                userProfile: profile,
                onboardingCompletedAt: profile.onboarding_completed_at ?? null,
                profileStatus: 'ready',
                profileError: null,
              });
              return;
            }

            if (response.status === 404) {
              set({
                userProfile: null,
                onboardingCompletedAt: null,
                profileStatus: 'ready',
                profileError: null,
              });
              return;
            }

            if (response.status === 401) {
              await get().signOut();
              return;
            }

            let errorMessage = `Failed to load user profile (${response.status})`;
            try {
              const errorData = (await response.json()) as { detail?: unknown; message?: unknown };
              if (typeof errorData.detail === 'string') {
                errorMessage = errorData.detail;
              } else if (typeof errorData.message === 'string') {
                errorMessage = errorData.message;
              }
            } catch {
              // Keep status-based message.
            }

            set({
              profileStatus: 'error',
              profileError: errorMessage,
            });
          } catch (err) {
            console.error('Failed to fetch user profile:', err);
            set({
              profileStatus: 'error',
              profileError: err instanceof Error ? err.message : 'Failed to load user profile',
            });
          } finally {
            fetchProfilePromise = null;
          }
        })();

        return fetchProfilePromise;
      },

      updateAvatarUrl: (avatarUrl) => {
        const currentProfile = get().userProfile;
        if (currentProfile) {
          set({
            userProfile: {
              ...currentProfile,
              avatar_url: avatarUrl ?? undefined,
            },
          });
        }
      },

      updateUserName: async (name) => {
        const token = get().session?.access_token;
        if (!token) throw new Error('No auth token');

        const response = await fetch(`${API_BASE}/users/me`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ name }),
        });

        if (!response.ok) {
          throw new Error(`Failed to update user name (${response.status})`);
        }

        const currentProfile = get().userProfile;
        if (currentProfile) {
          set({ userProfile: { ...currentProfile, name } });
        }
      },

      completeOnboarding: async () => {
        const token = get().session?.access_token;
        if (!token) throw new Error('No auth token');

        const timestamp = new Date().toISOString();
        const response = await fetch(`${API_BASE}/users/me`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ onboarding_completed_at: timestamp }),
        });

        if (!response.ok) {
          throw new Error(`Failed to complete onboarding (${response.status})`);
        }

        const currentProfile = get().userProfile;
        if (currentProfile) {
          set({
            userProfile: { ...currentProfile, onboarding_completed_at: timestamp },
            onboardingCompletedAt: timestamp,
          });
        }
      },
    }),
    {
      name: 'core-auth-storage',
      partialize: (state) => ({
        // Persist isAuthenticated as a hint for instant redirect on page load
        isAuthenticated: state.isAuthenticated,
        // Persist onboarding status so new users are immediately redirected on reload
        // without waiting for profile fetch. undefined=unknown, null=not done, string=done.
        onboardingCompletedAt: state.onboardingCompletedAt,
      }),
    }
  )
);
