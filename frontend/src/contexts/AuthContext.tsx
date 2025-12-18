/**
 * Authentication context provider using AWS Amplify + Cognito
 *
 * Manages user authentication state, login/logout flows, and token refresh.
 * Integrates with AppSync GraphQL API to fetch Account metadata.
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import {
  fetchAuthSession,
  signInWithRedirect,
  signIn,
  signOut,
  getCurrentUser,
} from "aws-amplify/auth";
import { Hub } from "aws-amplify/utils";
import { apolloClient } from "../lib/apollo";
import { GET_MY_ACCOUNT } from "../lib/graphql";
import type { Account, AuthContextValue } from "../types/auth";

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasValidTokens, setHasValidTokens] = useState(false);

  /**
   * Fetch account data from GraphQL API
   */
  const fetchAccountData = useCallback(
    async (accountId: string): Promise<Account | null> => {
      try {
        const { data } = await apolloClient.query<{ getMyAccount: Account }>({
          query: GET_MY_ACCOUNT,
          fetchPolicy: "network-only", // Always fetch fresh data
        });
        return data.getMyAccount;
      } catch (error) {
        console.error("Failed to fetch account data:", error);
        return null;
      }
    },
    [],
  );

  /**
   * Check current auth session and load account data
   */
  const checkAuthSession = useCallback(async () => {
    try {
      const session = await fetchAuthSession();

      if (session.tokens?.idToken) {
        // User has valid tokens
        setHasValidTokens(true);
        
        // Get user info and account data
        const user = await getCurrentUser();
        const accountData = await fetchAccountData(user.userId);

        if (accountData) {
          // Check admin status from JWT token claims, NOT from DynamoDB
          // The cognito:groups claim is the source of truth for permissions
          const groups = (session.tokens.idToken.payload['cognito:groups'] as string[]) || [];
          const isAdminFromToken = groups.includes('ADMIN');
          
          // Set account with admin status from JWT token
          setAccount({
            ...accountData,
            isAdmin: isAdminFromToken,
          });
        } else {
          // User is authenticated but account record doesn't exist yet
          // This can happen right after signup before post-auth Lambda runs
          console.warn("User has valid tokens but no account record yet");
          setAccount(null);
        }
      } else {
        // No valid session
        setHasValidTokens(false);
        setAccount(null);
      }
    } catch (error) {
      console.error("Auth session check failed:", error);
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

    // Listen for auth events (OAuth callback, sign out, etc.)
    const unsubscribe = Hub.listen("auth", ({ payload }) => {
      switch (payload.event) {
        case "signInWithRedirect":
          // User returned from Hosted UI - refresh session
          checkAuthSession();
          break;
        case "signInWithRedirect_failure":
          console.error("Sign in failed:", payload.data);
          setLoading(false);
          break;
        case "signedOut":
          setAccount(null);
          setLoading(false);
          break;
        case "tokenRefresh":
          // Token was refreshed - update account data
          checkAuthSession();
          break;
        case "tokenRefresh_failure":
          console.error("Token refresh failed:", payload.data);
          setAccount(null);
          break;
      }
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
      console.error("Login failed:", error);
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
        console.error("Email/password login failed:", error);
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
      console.log("Starting logout...");
      setAccount(null);
      setHasValidTokens(false);
      // signOut with global:true will redirect to Cognito's /logout endpoint
      // which clears the Cognito session cookies, then redirects back to redirectSignOut
      await signOut({ global: true });
      // Note: The redirect happens automatically, we won't reach this line
    } catch (error) {
      console.error("Logout failed:", error);
      // If signOut fails, clear local state and do manual redirect
      setAccount(null);
      // Build the Cognito logout URL manually as fallback
      const domain = import.meta.env.VITE_COGNITO_DOMAIN;
      const clientId = import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID;
      const logoutUri = encodeURIComponent(
        import.meta.env.VITE_OAUTH_REDIRECT_SIGNOUT,
      );
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
 */
export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
};
