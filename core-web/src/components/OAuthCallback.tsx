import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { API_BASE } from '../lib/apiBase';

/**
 * OAuth callback page rendered at /oauth/callback.
 * Extracts the authorization code from the URL and sends it
 * back to the opener window via postMessage, then auto-closes.
 */
export default function OAuthCallback() {
  const [message, setMessage] = useState('Completing authentication...');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const flow = params.get('flow');
    const code = params.get('code');
    const error = params.get('error');
    const errorDescription = params.get('error_description');

    if (flow === 'composio-login') {
      const completeLogin = async () => {
        try {
          const provider = params.get('provider');
          const state = params.get('state');
          const status = params.get('status');
          const connectedAccountId = params.get('connected_account_id')
            || params.get('connectedAccountId')
            || params.get('connection_id')
            || params.get('connectionId');

          if (!provider || !state || !connectedAccountId) {
            throw new Error('Missing Composio callback parameters');
          }
          if (status && status !== 'success') {
            throw new Error(errorDescription || error || 'Composio authentication failed');
          }

          const response = await fetch(`${API_BASE}/auth/composio/complete-login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              provider,
              state,
              status,
              connected_account_id: connectedAccountId,
            }),
          });

          if (!response.ok) {
            let message = `Failed to complete sign-in (${response.status})`;
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
            throw new Error(message);
          }

          const data = (await response.json()) as {
            token_hash?: unknown;
            redirect_to?: unknown;
          };
          if (typeof data.token_hash !== 'string' || !data.token_hash) {
            throw new Error('Missing Supabase login token');
          }

          const { error: verifyError } = await supabase.auth.verifyOtp({
            token_hash: data.token_hash,
            type: 'email',
          });
          if (verifyError) throw verifyError;

          setMessage('Signed in. Redirecting...');
          const redirectTo = typeof data.redirect_to === 'string' && data.redirect_to
            ? data.redirect_to
            : window.location.origin;
          window.location.replace(redirectTo);
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Authentication failed');
        }
      };

      void completeLogin();
      return;
    }

    if (flow === 'composio-reconnect' || flow === 'workspace-connector-reconnect') {
      const completeReconnect = async () => {
        try {
          const provider = params.get('provider');
          const state = params.get('state');
          const status = params.get('status');
          const connectedAccountId = params.get('connected_account_id')
            || params.get('connectedAccountId')
            || params.get('connection_id')
            || params.get('connectionId');

          if (!provider || !state || !connectedAccountId) {
            throw new Error('Missing Composio reconnect parameters');
          }
          if (status && status !== 'success') {
            throw new Error(errorDescription || error || 'Composio reconnect failed');
          }

          const { data } = await supabase.auth.getSession();
          const accessToken = data.session?.access_token;
          if (!accessToken) {
            throw new Error('Sign in again to finish reconnecting');
          }

          const workspaceId = sessionStorage.getItem('reconnecting_workspace_id');
          const endpoint = flow === 'workspace-connector-reconnect'
            ? `${API_BASE}/workspaces/${workspaceId}/connectors/complete-reconnect`
            : `${API_BASE}/auth/email-accounts/complete-reconnect`;
          if (flow === 'workspace-connector-reconnect' && !workspaceId) {
            throw new Error('Missing workspace reconnect context');
          }

          const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${accessToken}`,
            },
            body: JSON.stringify({
              provider,
              state,
              status,
              connected_account_id: connectedAccountId,
            }),
          });

          if (!response.ok) {
            let message = `Failed to complete reconnect (${response.status})`;
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
            throw new Error(message);
          }

          const reconnectingConnectionId = sessionStorage.getItem('reconnecting_connection_id');
          if (flow === 'workspace-connector-reconnect') {
            if (workspaceId && reconnectingConnectionId) {
              sessionStorage.setItem('completed_workspace_connector_reconnect_id', reconnectingConnectionId);
              sessionStorage.setItem('completed_workspace_connector_reconnect_workspace_id', workspaceId);
            }
          } else if (reconnectingConnectionId) {
            sessionStorage.setItem('completed_email_account_reconnect_id', reconnectingConnectionId);
          }
          sessionStorage.removeItem('reconnecting_connection_id');
          sessionStorage.removeItem('reconnecting_workspace_id');
          setMessage('Reconnected. Redirecting...');
          window.location.replace(window.location.origin);
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Reconnect failed');
        }
      };

      void completeReconnect();
      return;
    }

    if (window.opener) {
      window.opener.postMessage(
        {
          type: 'oauth-callback',
          code: code || undefined,
          error: error ? errorDescription || error : undefined,
        },
        window.location.origin
      );
    }

    // Auto-close after a short delay
    setTimeout(() => window.close(), 1000);
  }, []);

  return (
    <div className="flex items-center justify-center h-screen bg-white">
      <p className={`text-sm ${error ? 'text-red-600' : 'text-gray-500'}`}>
        {error || message}
      </p>
    </div>
  );
}
