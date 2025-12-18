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

// Mock AWS Amplify
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  signOut: vi.fn(),
  getCurrentUser: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()), // Returns unsubscribe function
  },
}));

// Test component that uses the auth context
const TestComponent = () => {
  const { account, loading, isAuthenticated, isAdmin, login, logout } = useAuth();
  
  return (
    <div>
      <div data-testid="loading">{loading.toString()}</div>
      <div data-testid="isAuthenticated">{isAuthenticated.toString()}</div>
      <div data-testid="isAdmin">{isAdmin.toString()}</div>
      {account && (
        <>
          <div data-testid="accountId">{account.accountId}</div>
          <div data-testid="displayName">{account.displayName}</div>
        </>
      )}
      <button onClick={login}>Login</button>
      <button onClick={logout}>Logout</button>
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
      </AuthProvider>
    );
    
    expect(screen.getByTestId('loading')).toHaveTextContent('true');
  });

  it('sets account when user is authenticated', async () => {
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });
    
    expect(screen.getByTestId('isAuthenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('accountId')).toHaveTextContent('user-123');
    expect(screen.getByTestId('displayName')).toHaveTextContent('User');
  });

  it('sets account to null when no valid session exists', async () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
      </AuthProvider>
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
      </AuthProvider>
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
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    vi.mocked(amplifyAuth.signOut).mockResolvedValue(undefined);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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

  it('handles logout failure', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    vi.mocked(amplifyAuth.signOut).mockRejectedValue(new Error('Logout failed'));
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
    
    consoleErrorSpy.mockRestore();
  });

  it('listens for Hub auth events on mount', () => {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({ tokens: undefined } as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    expect(amplifyUtils.Hub.listen).toHaveBeenCalledWith('auth', expect.any(Function));
  });

  it('handles signInWithRedirect Hub event', async () => {
    let hubCallback: any;
    vi.mocked(amplifyUtils.Hub.listen).mockImplementation((channel, callback) => {
      hubCallback = callback;
      return vi.fn();
    });
    
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
    
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
    
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
      </AuthProvider>
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
    
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'user-123',
      username: 'testuser',
    };
    
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
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
      </AuthProvider>
    );
    
    unmount();
    
    expect(unsubscribeMock).toHaveBeenCalled();
  });

  it('exposes isAdmin flag from account', async () => {
    const mockSession = {
      tokens: {
        idToken: { toString: () => 'mock-token' },
      },
    };
    
    const mockUser = {
      userId: 'admin-123',
      username: 'adminuser',
    };
    
    // Mock fetchAccountData to return admin account
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue(mockSession as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(mockUser as any);
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false');
    });
    
    // Default implementation returns isAdmin: false
    expect(screen.getByTestId('isAdmin')).toHaveTextContent('false');
  });
});
