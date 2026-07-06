import { create } from 'zustand';
import {
  getOAuthConfig,
  getEmailAccounts,
  verifyEmailAccounts,
  verifyEmailAccount,
  reconnectEmailAccount,
  addEmailAccount,
  removeEmailAccount,
  type EmailAccount,
} from '../api/client';
import { toast } from 'sonner';
import {
  openGoogleOAuth,
  openMicrosoftOAuth,
  GOOGLE_SCOPES,
  MICROSOFT_SCOPES,
} from '../utils/oauthPopup';

const MAX_ACCOUNTS = 5;

interface EmailAccountsState {
  accounts: EmailAccount[];
  isLoading: boolean;
  isAdding: boolean;
  isVerifying: boolean;
  error: string | null;
  lastVerifiedAt: number | null;

  fetchAccounts: () => Promise<void>;
  verifyAccounts: (force?: boolean) => Promise<void>;
  verifyAccount: (id: string) => Promise<void>;
  reconnectAccount: (id: string) => Promise<void>;
  addGoogleAccount: () => Promise<void>;
  addMicrosoftAccount: () => Promise<void>;
  removeAccount: (id: string) => Promise<void>;
}

export const useEmailAccountsStore = create<EmailAccountsState>()((set, get) => ({
  accounts: [],
  isLoading: false,
  isAdding: false,
  isVerifying: false,
  error: null,
  lastVerifiedAt: null,

  fetchAccounts: async () => {
    set({ isLoading: true, error: null });
    try {
      const { accounts } = await getEmailAccounts();
      // Sort by account_order
      accounts.sort((a, b) => a.account_order - b.account_order);
      set({ accounts, isLoading: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to fetch accounts',
        isLoading: false,
      });
    }
  },

  verifyAccounts: async (force = false) => {
    const lastVerifiedAt = get().lastVerifiedAt;
    if (!force && lastVerifiedAt && Date.now() - lastVerifiedAt < 30_000) return;
    set({ isVerifying: true, error: null });
    try {
      const { accounts } = await verifyEmailAccounts();
      accounts.sort((a, b) => a.account_order - b.account_order);
      set({ accounts, isVerifying: false, lastVerifiedAt: Date.now() });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify accounts';
      toast.error(message);
      set({ error: message, isVerifying: false });
    }
  },

  verifyAccount: async (id: string) => {
    set({ isVerifying: true, error: null });
    try {
      const health = await verifyEmailAccount(id);
      set((state) => ({
        accounts: state.accounts.map((account) => account.id === id
          ? {
              ...account,
              verification_status: health.status,
              last_verified_at: health.last_verified_at,
              error_reason: health.error_reason,
              unverified: health.unverified,
              scopes: health.scopes ?? account.scopes,
              external_account_id: health.external_account_id ?? account.external_account_id,
            }
          : account),
        isVerifying: false,
        lastVerifiedAt: Date.now(),
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to verify account';
      toast.error(message);
      set({ error: message, isVerifying: false });
    }
  },

  reconnectAccount: async (id: string) => {
    set({ error: null });
    try {
      const result = await reconnectEmailAccount(id);
      if (result.redirect_url) {
        sessionStorage.setItem('reconnecting_connection_id', id);
        window.location.assign(result.redirect_url);
        return;
      }
      await get().verifyAccount(id);
      toast.success('Connection status updated');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to reconnect account';
      toast.error(message);
      set({ error: message });
    }
  },

  addGoogleAccount: async () => {
    if (get().accounts.length >= MAX_ACCOUNTS) {
      set({ error: `Maximum of ${MAX_ACCOUNTS} email accounts allowed` });
      return;
    }

    set({ isAdding: true, error: null });
    try {
      const config = await getOAuthConfig();
      const { code } = await openGoogleOAuth(config.google_client_id);

      const redirectUri = `${window.location.origin}/oauth/callback`;
      const account = await addEmailAccount({
        provider: 'google',
        server_auth_code: code,
        redirect_uri: redirectUri,
        scopes: GOOGLE_SCOPES,
      });

      set((state) => ({
        accounts: [...state.accounts, account].sort((a, b) => a.account_order - b.account_order),
        isAdding: false,
      }));
    } catch (err) {
      // Don't show error for user cancellation
      const message = err instanceof Error ? err.message : 'Failed to add Google account';
      if (message === 'Authentication cancelled') {
        set({ isAdding: false });
      } else {
        set({ error: message, isAdding: false });
      }
    }
  },

  addMicrosoftAccount: async () => {
    if (get().accounts.length >= MAX_ACCOUNTS) {
      set({ error: `Maximum of ${MAX_ACCOUNTS} email accounts allowed` });
      return;
    }

    set({ isAdding: true, error: null });
    try {
      const config = await getOAuthConfig();
      if (!config.microsoft_client_id) {
        throw new Error('Microsoft OAuth is not configured');
      }

      const { code, codeVerifier } = await openMicrosoftOAuth(config.microsoft_client_id);

      const redirectUri = `${window.location.origin}/oauth/callback`;
      const account = await addEmailAccount({
        provider: 'microsoft',
        server_auth_code: code,
        code_verifier: codeVerifier,
        redirect_uri: redirectUri,
        scopes: MICROSOFT_SCOPES,
      });

      set((state) => ({
        accounts: [...state.accounts, account].sort((a, b) => a.account_order - b.account_order),
        isAdding: false,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add Microsoft account';
      if (message === 'Authentication cancelled') {
        set({ isAdding: false });
      } else {
        set({ error: message, isAdding: false });
      }
    }
  },

  removeAccount: async (id: string) => {
    const account = get().accounts.find((a) => a.id === id);
    if (!account) return;

    if (account.is_primary) {
      set({ error: 'Cannot remove primary account' });
      return;
    }

    // Optimistic removal
    const previousAccounts = get().accounts;
    set((state) => ({
      accounts: state.accounts.filter((a) => a.id !== id),
      error: null,
    }));

    try {
      await removeEmailAccount(id);
    } catch (err) {
      // Revert on failure
      set({
        accounts: previousAccounts,
        error: err instanceof Error ? err.message : 'Failed to remove account',
      });
    }
  },
}));
