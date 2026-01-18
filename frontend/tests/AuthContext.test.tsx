/**
 * Tests for AuthContext
 *
 * Tests authentication flows, token refresh, Hub event listeners
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, renderHook } from '@testing-library/react';
import { act } from '@testing-library/react';
import { AuthProvider, useAuth } from '../src/contexts/AuthContext';
import * as amplifyAuth from 'aws-amplify/auth';
import * as amplifyUtils from 'aws-amplify/utils';

// Mock Apollo client
vi.mock('../src/lib/apollo', () => ({
  apolloClient: {
    query: vi.fn().mockResolvedValue({
      data: {
        getMyAccount: {
          accountId: 'user-123',
          email: 'test@example.com',
          givenName: 'Test',
          familyName: 'User',
          isAdmin: false,
          createdAt: '2024-01-01T00:00:00Z',
          updatedAt: '2024-01-01T00:00:00Z',
        },
      },
    }),
    clearStore: vi.fn().mockResolvedValue(undefined),
  },
}));

// Mock AWS Amplify
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  getCurrentUser: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()), // Returns unsubscribe function
  },
}));

// Helper to create mock session with proper idToken structure
const createMockSession = (hasTokens: boolean = true, groups: string[] = []) => ({
  tokens: hasTokens
    ? {
        idToken: {
          toString: () => 'mock-token',
          payload: {
            'cognito:groups': groups,
          },
        },
      }
    : undefined,
});

const mockUser = {
  userId: 'user-123',
  username: 'testuser',
};

// Test component that uses the auth context
const TestComponent = () => {
  const { account, loading, isAuthenticated, isAdmin, login, logout, refreshSession } = useAuth();

  return (
    <div>
      <div data-testid="loading">{loading.toString()}</div>
      <div data-testid="isAuthenticated">{isAuthenticated.toString()}</div>
      <div data-testid="isAdmin">{isAdmin.toString()}</div>
      {account && (
        <>
          <div data-testid="accountId">{account.accountId}</div>
          <div data-testid="email">{account.email}</div>
        </>
      )}
      <button onClick={login}>Login</button>
      <button onClick={logout}>Logout</button>
      <button onClick={refreshSession}>Refresh</button>
    </div>
  );
};

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('throws error when useAuth is used outside AuthProvider', () => {
    // Suppress console.error for this test
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<TestComponent />);
    }).toThrow('useAuth must be used within AuthProvider');

    consoleErrorSpy.mockRestore();
  });

  it('initializes with loading state', () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    expect(screen.getByTestId('loading')).toHaveTextContent('true');
  });

  it('sets account when user is authenticated', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('accountId')).toHaveTextContent('user-123');
    expect(screen.getByTestId('email')).toHaveTextContent('test@example.com');
  });

  it('sets account to null when no valid session exists', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('false');
    expect(screen.queryByTestId('accountId')).not.toBeInTheDocument();
  });

  it('handles auth session check failure', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(amplifyAuth.fetchAuthSession).mockRejectedValue(new Error('Auth error'));

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('false');
    expect(consoleErrorSpy).toHaveBeenCalledWith('Auth session check failed:', expect.any(Error));

    consoleErrorSpy.mockRestore();
  });

  it('calls signInWithRedirect on login', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
    vi.mocked(amplifyAuth.signInWithRedirect).mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    const loginButton = screen.getByText('Login');
    loginButton.click();

    await waitFor(() => {
      expect(amplifyAuth.signInWithRedirect).toHaveBeenCalled();
    });
  });

  it('catches errors during login', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
    vi.mocked(amplifyAuth.signInWithRedirect).mockRejectedValue(new Error('Login failed'));

    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    await waitFor(() => {
      expect(result.current).toBeDefined();
    });

    // Login should reject and log error
    let caughtError: Error | undefined;
    try {
      await act(async () => {
        await result.current.login();
      });
    } catch (error) {
      caughtError = error as Error;
    }

    expect(caughtError).toBeInstanceOf(Error);
    expect(consoleErrorSpy).toHaveBeenCalledWith('Login failed:', expect.any(Error));
    consoleErrorSpy.mockRestore();
  });

  it('calls signOut on logout and clears account', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    vi.mocked(amplifyAuth.signOut).mockResolvedValue(undefined);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });

    const logoutButton = screen.getByText('Logout');
    logoutButton.click();

    await waitFor(() => {
      expect(amplifyAuth.signOut).toHaveBeenCalled();
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('false');
    });
  });

  it('handles logout failure with fallback redirect', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    vi.mocked(amplifyAuth.signOut).mockRejectedValue(new Error('Logout failed'));

    // Mock window.location.href
    const originalLocation = window.location;
    const locationHrefSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { ...originalLocation, href: '' },
      writable: true,
    });
    Object.defineProperty(window.location, 'href', {
      set: locationHrefSpy,
    });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });

    const logoutButton = screen.getByText('Logout');

    // Click will trigger the promise rejection, but we catch it in the handler
    logoutButton.click();

    // Wait for error to be logged
    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith('Logout failed:', expect.any(Error));
    });

    // Verify the fallback redirect was attempted
    await waitFor(() => {
      expect(locationHrefSpy).toHaveBeenCalled();
    });
    const redirectUrl = locationHrefSpy.mock.calls[0][0];
    expect(redirectUrl).toContain('/logout?client_id=');
    expect(redirectUrl).toContain('&logout_uri=');

    // Restore window.location
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
    });
    consoleErrorSpy.mockRestore();
  });

  it('listens for Hub auth events on mount', () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    expect(amplifyUtils.Hub.listen).toHaveBeenCalledWith('auth', expect.any(Function));
  });

  it('handles signInWithRedirect Hub event', async () => {
    let hubCallback: any;
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    // Simulate signInWithRedirect event
    hubCallback({ payload: { event: 'signInWithRedirect' } });

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });
  });

  it('handles signedOut Hub event', async () => {
    let hubCallback: any;
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });

    // Simulate signedOut event
    hubCallback({ payload: { event: 'signedOut' } });

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('false');
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });
  });

  it('handles tokenRefresh Hub event', async () => {
    let hubCallback: any;
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });

    // Clear previous calls
    vi.mocked(amplifyAuth.fetchAuthSession).mockClear();

    // Simulate tokenRefresh event
    hubCallback({ payload: { event: 'tokenRefresh' } });

    await waitFor(() => {
      expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
    });
  });

  it('handles signInWithRedirect_failure Hub event', async () => {
    let hubCallback: any;
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    // Simulate signInWithRedirect_failure event
    hubCallback({ payload: { event: 'signInWithRedirect_failure', data: { error: 'Auth failed' } } });

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith('Sign in failed:', { error: 'Auth failed' });
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    consoleErrorSpy.mockRestore();
  });

  it('handles tokenRefresh_failure Hub event', async () => {
    let hubCallback: any;
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    });

    // Simulate tokenRefresh_failure event
    hubCallback({ payload: { event: 'tokenRefresh_failure', data: { error: 'Token refresh failed' } } });

    await waitFor(() => {
      expect(consoleErrorSpy).toHaveBeenCalledWith('Token refresh failed:', { error: 'Token refresh failed' });
      expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('false');
    });

    consoleErrorSpy.mockRestore();
  });

  it('unsubscribes from Hub events on unmount', () => {
    const unsubscribeMock = vi.fn();
    vi.mocked(amplifyUtils.Hub.listen).mockReturnValue(unsubscribeMock);
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);

    const { unmount } = render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    unmount();

    expect(unsubscribeMock).toHaveBeenCalled();
  });

  it('exposes isAdmin flag from account', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });

    // Default implementation returns isAdmin: false
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false');
  });

  describe('loginWithPassword', () => {
    it('successfully logs in and refreshes session when isSignedIn is true', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
      vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
      vi.mocked(amplifyAuth.signIn).mockResolvedValue({ isSignedIn: true } as any);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProvider,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult: any;
      await act(async () => {
        loginResult = await result.current.loginWithPassword('test@example.com', 'password123');
      });

      expect(amplifyAuth.signIn).toHaveBeenCalledWith({ username: 'test@example.com', password: 'password123' });
      expect(loginResult.isSignedIn).toBe(true);
    });

    it('returns result with nextStep when MFA is required', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
      vi.mocked(amplifyAuth.signIn).mockResolvedValue({
        isSignedIn: false,
        nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_TOTP_CODE' },
      } as any);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProvider,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult: any;
      await act(async () => {
        loginResult = await result.current.loginWithPassword('test@example.com', 'password123');
      });

      expect(loginResult.isSignedIn).toBe(false);
      expect(loginResult.nextStep.signInStep).toBe('CONFIRM_SIGN_IN_WITH_TOTP_CODE');
    });

    it('returns result without isSignedIn or nextStep', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
      vi.mocked(amplifyAuth.signIn).mockResolvedValue({
        isSignedIn: false,
        nextStep: undefined,
      } as any);

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProvider,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let loginResult: any;
      await act(async () => {
        loginResult = await result.current.loginWithPassword('test@example.com', 'password123');
      });

      expect(loginResult.isSignedIn).toBe(false);
    });

    it('throws error on login failure', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
      vi.mocked(amplifyAuth.signIn).mockRejectedValue(new Error('Invalid credentials'));

      const { result } = renderHook(() => useAuth(), {
        wrapper: AuthProvider,
      });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      let caughtError: Error | undefined;
      await act(async () => {
        try {
          await result.current.loginWithPassword('test@example.com', 'wrongpassword');
        } catch (error) {
          caughtError = error as Error;
        }
      });

      expect(caughtError).toBeInstanceOf(Error);
      expect(caughtError?.message).toBe('Invalid credentials');
      expect(consoleErrorSpy).toHaveBeenCalledWith('Email/password login failed:', expect.any(Error));
      consoleErrorSpy.mockRestore();
    });
  });

  describe('OAuth redirect handling', () => {
    it('redirects to saved URL on OAuth completion', async () => {
      // Save a redirect URL before auth completes
      sessionStorage.setItem('oauth_redirect', '/campaigns/123');

      // Mock window.location.href
      const originalLocation = window.location;
      const locationHrefSpy = vi.fn();
      Object.defineProperty(window, 'location', {
        value: { ...originalLocation, href: '' },
        writable: true,
      });
      Object.defineProperty(window.location, 'href', {
        set: locationHrefSpy,
      });

      // Simulate successful auth session that triggers OAuth redirect handling
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
      vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

      // Manually call the redirect function by triggering Hub signInWithRedirect event
      const hubListen = vi.mocked(amplifyUtils.Hub.listen);
      let capturedListener: any;
      hubListen.mockImplementation((_channel, listener) => {
        capturedListener = listener;
        return vi.fn();
      });

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>,
      );

      // Wait for initial load
      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('false');
      });

      // Simulate signInWithRedirect completing
      if (capturedListener) {
        await act(async () => {
          capturedListener({ payload: { event: 'signInWithRedirect' } });
        });
      }

      // The redirect should have been triggered
      await waitFor(() => {
        expect(locationHrefSpy).toHaveBeenCalledWith('/campaigns/123');
      });

      // sessionStorage should be cleared
      expect(sessionStorage.getItem('oauth_redirect')).toBeNull();

      // Restore
      Object.defineProperty(window, 'location', {
        value: originalLocation,
        writable: true,
      });
    });
  });

  describe('refreshSession', () => {
    it('calls checkAuthSession to refresh account data', async () => {
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
      vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>,
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('false');
      });

      // Clear mock calls
      vi.mocked(amplifyAuth.fetchAuthSession).mockClear();

      // Click refresh button
      const refreshButton = screen.getByText('Refresh');
      refreshButton.click();

      // fetchAuthSession should be called again
      await waitFor(() => {
        expect(amplifyAuth.fetchAuthSession).toHaveBeenCalled();
      });
    });
  });

  describe('fetchAccountData error handling', () => {
    it('logs error and returns null when account fetch fails', async () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(createMockSession(true) as any);
      vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);

      // Mock Apollo client to throw an error
      const { apolloClient } = await import('../src/lib/apollo');
      vi.mocked(apolloClient.query).mockRejectedValueOnce(new Error('Network error'));

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>,
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('false');
      });

      // Error should have been logged
      expect(consoleErrorSpy).toHaveBeenCalledWith('Failed to fetch account data:', expect.any(Error));

      // Account should be null (accountId element should not exist since account is conditionally rendered)
      expect(screen.queryByTestId('accountId')).not.toBeInTheDocument();

      consoleErrorSpy.mockRestore();
    });
  });
});
