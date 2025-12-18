/**
 * Type definitions for authentication
 */

export interface Account {
  accountId: string;
  email: string;
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitNumber?: string;
  isAdmin: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AuthContextValue {
  /** Current authenticated user account, or null if not authenticated */
  account: Account | null;

  /** Whether authentication state is currently loading */
  loading: boolean;

  /** Whether user is authenticated */
  isAuthenticated: boolean;

  /** Whether user has admin privileges */
  isAdmin: boolean;

  /** Initiate login flow via Cognito Hosted UI (for social login) */
  login: () => Promise<void>;

  /** Sign in with email and password (custom UI) */
  loginWithPassword: (
    email: string,
    password: string,
  ) => Promise<{ isSignedIn: boolean }>;

  /** Sign out current user and clear session */
  logout: () => Promise<void>;

  /** Refresh current session and account data */
  refreshSession: () => Promise<void>;
}
