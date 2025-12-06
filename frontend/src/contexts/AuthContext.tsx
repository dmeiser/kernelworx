/**
 * Authentication context provider using AWS Amplify + Cognito
 * 
 * Manages user authentication state, login/logout flows, and token refresh.
 * Integrates with AppSync GraphQL API to fetch Account metadata.
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { fetchAuthSession, signInWithRedirect, signOut, getCurrentUser } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import type { Account, AuthContextValue } from '../types/auth';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
  /** Optional Apollo Client for GraphQL queries (injected to avoid circular deps) */
  apolloClient?: {
    query: (options: { query: unknown; variables?: Record<string, unknown> }) => Promise<{ data: { getMyAccount: Account } }>;
  };
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children, apolloClient }) => {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);

  /**
   * Fetch account data from GraphQL API
   */
  const fetchAccountData = useCallback(async (accountId: string): Promise<Account | null> => {
    if (!apolloClient) {
      // Apollo Client not yet initialized, use minimal account data
      return {
        accountId,
        email: '',
        displayName: 'User',
        isAdmin: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
    }

    try {
      // GraphQL query will be defined later when Apollo Client is set up
      // For now, return minimal account data
      // const GET_MY_ACCOUNT = gql`query GetMyAccount { getMyAccount { accountId email displayName isAdmin createdAt updatedAt } }`;
      // const { data } = await apolloClient.query({ query: GET_MY_ACCOUNT });
      // return data.getMyAccount;
      
      return {
        accountId,
        email: '',
        displayName: 'User',
        isAdmin: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
    } catch (error) {
      console.error('Failed to fetch account data:', error);
      return null;
    }
  }, [apolloClient]);

  /**
   * Check current auth session and load account data
   */
  const checkAuthSession = useCallback(async () => {
    try {
      const session = await fetchAuthSession();
      
      if (session.tokens?.idToken) {
        // User is authenticated, get user info
        const user = await getCurrentUser();
        const accountData = await fetchAccountData(user.userId);
        
        if (accountData) {
          setAccount(accountData);
        }
      } else {
        // No valid session
        setAccount(null);
      }
    } catch (error) {
      console.error('Auth session check failed:', error);
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

    // Listen for auth events (OAuth callback, sign out, etc.)
    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      switch (payload.event) {
        case 'signInWithRedirect':
          // User returned from Hosted UI - refresh session
          checkAuthSession();
          break;
        case 'signInWithRedirect_failure':
          console.error('Sign in failed:', payload.data);
          setLoading(false);
          break;
        case 'signedOut':
          setAccount(null);
          setLoading(false);
          break;
        case 'tokenRefresh':
          // Token was refreshed - update account data
          checkAuthSession();
          break;
        case 'tokenRefresh_failure':
          console.error('Token refresh failed:', payload.data);
          setAccount(null);
          break;
      }
    });

    return unsubscribe;
  }, [checkAuthSession]);

  /**
   * Login via Cognito Hosted UI
   * 
   * This redirects the user to the Cognito Hosted UI at:
   * https://{COGNITO_DOMAIN}/oauth2/authorize
   * 
   * The user will authenticate with their chosen social provider (Google/Facebook/Apple),
   * and Cognito will redirect back to the app with an authorization code.
   * Amplify automatically exchanges the code for JWT tokens.
   */
  const login = useCallback(async () => {
    try {
      await signInWithRedirect({ provider: 'Google' });
    } catch (error) {
      console.error('Login failed:', error);
      throw error;
    }
  }, []);

  /**
   * Logout and clear session
   * 
   * This signs the user out via Cognito and redirects to the sign-out URL.
   */
  const logout = useCallback(async () => {
    try {
      await signOut();
      setAccount(null);
    } catch (error) {
      console.error('Logout failed:', error);
      throw error;
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
    isAuthenticated: !!account,
    isAdmin: account?.isAdmin ?? false,
    login,
    logout,
    refreshSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

/**
 * Hook to access auth context
 */
export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
