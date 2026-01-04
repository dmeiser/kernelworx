/**
 * Authentication context provider using AWS Amplify + Cognito
 *
 * Manages user authentication state, login/logout flows, and token refresh.
 * Integrates with AppSync GraphQL API to fetch Account metadata.
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { fetchAuthSession, signInWithRedirect, signIn, signOut, getCurrentUser } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { apolloClient } from '../lib/apollo';
import { GET_MY_ACCOUNT } from '../lib/graphql';
import type { Account, AuthContextValue } from '../types/auth';
import type { AuthSession } from 'aws-amplify/auth';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
}

// Check if session has valid tokens
const hasValidSession = (session: AuthSession): boolean => {
  return session.tokens?.idToken !== undefined;
};

// Extract admin status from JWT token claims
const getAdminStatusFromSession = (session: AuthSession): boolean => {
  const groups = (session.tokens?.idToken?.payload['cognito:groups'] as string[]) || [];
  return groups.includes('ADMIN');
};

// Merge account data with admin status from token
const mergeAccountWithAdminStatus = (accountData: Account, isAdmin: boolean): Account => ({
  ...accountData,
  isAdmin,
});

// Handle redirect after OAuth login
const handleOAuthRedirect = () => {
  const savedRedirect = sessionStorage.getItem('oauth_redirect');
  if (savedRedirect) {
    sessionStorage.removeItem('oauth_redirect');
    window.location.href = savedRedirect;
  }
};

// Auth event handler types
interface AuthEventHandlers {
  onSignedOut: () => void;
  onTokenRefreshFailure: () => void;
}

// Individual event handlers
const handleSignInWithRedirect = (checkAuthSession: () => Promise<void>) => {
  checkAuthSession().then(handleOAuthRedirect);
};

const handleSignInFailure = (eventData: unknown, setLoading: (loading: boolean) => void) => {
  console.error('Sign in failed:', eventData);
  setLoading(false);
};

const handleTokenRefresh = (checkAuthSession: () => Promise<void>) => {
  checkAuthSession();
};

const handleTokenRefreshFailure = (eventData: unknown, handlers: AuthEventHandlers) => {
  console.error('Token refresh failed:', eventData);
  handlers.onTokenRefreshFailure();
};

// Create auth event handler function
const createAuthEventHandler = (
  checkAuthSession: () => Promise<void>,
  setLoading: (loading: boolean) => void,
  handlers: AuthEventHandlers,
) => {
  const eventHandlers: Record<string, (data: unknown) => void> = {
    signInWithRedirect: () => handleSignInWithRedirect(checkAuthSession),
    signInWithRedirect_failure: (data) => handleSignInFailure(data, setLoading),
    signedOut: () => handlers.onSignedOut(),
    tokenRefresh: () => handleTokenRefresh(checkAuthSession),
    tokenRefresh_failure: (data) => handleTokenRefreshFailure(data, handlers),
  };

  return (eventName: string, eventData: unknown) => {
    const handler = eventHandlers[eventName];
    if (handler) handler(eventData);
  };
};

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasValidTokens, setHasValidTokens] = useState(false);

  /**
   * Fetch account data from GraphQL API
   */
  const fetchAccountData = useCallback(async (): Promise<Account | null> => {
    try {
      const { data } = await apolloClient.query<{ getMyAccount: Account }>({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only', // Always fetch fresh data
      });
      return data?.getMyAccount ?? null;
    } catch (error) {
      console.error('Failed to fetch account data:', error);
      return null;
    }
  }, []);

  /**
   * Check current auth session and load account data
   */
  const checkAuthSession = useCallback(async () => {
    try {
      const session = await fetchAuthSession();

      if (!hasValidSession(session)) {
        setHasValidTokens(false);
        setAccount(null);
        return;
      }

      // User has valid tokens
      setHasValidTokens(true);
      await getCurrentUser();
      const accountData = await fetchAccountData();

      if (accountData) {
        const isAdminFromToken = getAdminStatusFromSession(session);
        setAccount(mergeAccountWithAdminStatus(accountData, isAdminFromToken));
      } else {
        // User is authenticated but account record doesn't exist yet
        console.warn('User has valid tokens but no account record yet');
        setAccount(null);
      }
    } catch (error) {
      console.error('Auth session check failed:', error);
      setHasValidTokens(false);
      setAccount(null);
    } finally {
      setLoading(false);
    }
  }, [fetchAccountData]);

  /**
   * Initialize auth state on mount and listen for auth events
   */
  useEffect(() => {
    checkAuthSession();

    const handleEvent = createAuthEventHandler(checkAuthSession, setLoading, {
      onSignedOut: () => {
        setAccount(null);
        setHasValidTokens(false);
        setLoading(false);
      },
      onTokenRefreshFailure: () => {
        setAccount(null);
        setHasValidTokens(false);
      },
    });

    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      handleEvent(payload.event, (payload as any).data);
    });

    return unsubscribe;
  }, [checkAuthSession]);

  /**
   * Login via Cognito Hosted UI (for social providers)
   *
   * This redirects the user to the Cognito Hosted UI at:
   * https://{COGNITO_DOMAIN}/oauth2/authorize
   *
   * The Hosted UI displays all configured authentication options:
   * - Social providers (Google, Facebook, Apple)
   * - Email/password signup and login
   * - Password reset flows
   *
   * After authentication, Cognito redirects back to the app with an authorization code.
   * Amplify automatically exchanges the code for JWT tokens.
   */
  const login = useCallback(async () => {
    try {
      // Redirect to Cognito Hosted UI (shows all login options)
      await signInWithRedirect();
    } catch (error) {
      console.error('Login failed:', error);
      throw error;
    }
  }, []);

  /**
   * Login with email and password (custom UI)
   *
   * This uses Amplify's direct sign-in without redirecting to Hosted UI.
   * After successful sign-in, the auth state will be updated automatically.
   */
  const loginWithPassword = useCallback(
    async (email: string, password: string) => {
      try {
        const result = await signIn({ username: email, password });

        // Check if sign-in is complete or if there's a next step (MFA, etc.)
        if (result.isSignedIn) {
          // Sign-in complete - refresh the auth session
          await checkAuthSession();
          return result;
        } else if (result.nextStep) {
          // There's a next step (MFA challenge, new password required, etc.)
          // Return the result so the UI can handle it
          return result;
        }

        return result;
      } catch (error) {
        console.error('Email/password login failed:', error);
        throw error;
      }
    },
    [checkAuthSession],
  );

  /**
   * Logout and clear session
   *
   * This signs the user out via Cognito and redirects to the sign-out URL.
   * With OAuth/Hosted UI, signOut will redirect to Cognito logout endpoint.
   */
  const logout = useCallback(async () => {
    try {
      console.log('Starting logout...');
      setAccount(null);
      setHasValidTokens(false);
      // signOut with global:true will redirect to Cognito's /logout endpoint
      // which clears the Cognito session cookies, then redirects back to redirectSignOut
      await signOut({ global: true });
      // Note: The redirect happens automatically, we won't reach this line
    } catch (error) {
      console.error('Logout failed:', error);
      // If signOut fails, clear local state and do manual redirect
      setAccount(null);
      // Build the Cognito logout URL manually as fallback
      const domain = import.meta.env.VITE_COGNITO_DOMAIN;
      const clientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID;
      const logoutUri = encodeURIComponent(import.meta.env.VITE_OAUTH_REDIRECT_SIGNOUT);
      window.location.href = `https://${domain}/logout?client_id=${clientId}&logout_uri=${logoutUri}`;
    }
  }, []);

  /**
   * Refresh session and account data
   */
  const refreshSession = useCallback(async () => {
    await checkAuthSession();
  }, [checkAuthSession]);

  const value: AuthContextValue = {
    account,
    loading,
    isAuthenticated: hasValidTokens, // Check tokens, not account record
    isAdmin: account?.isAdmin ?? false,
    login,
    loginWithPassword,
    logout,
    refreshSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

/**
 * Hook to access auth context
 * Note: This hook is intentionally exported alongside the provider component.
 * This is a common React pattern for context providers.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
