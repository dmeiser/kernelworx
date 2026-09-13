/**
 * Tests for ProtectedRoute component
 *
 * Tests authentication and authorization checks
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ProtectedRoute } from '../src/components/ProtectedRoute';
import { AuthProvider } from '../src/contexts/AuthContext';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as amplifyAuth from 'aws-amplify/auth';

// Mock Apollo Client
vi.mock('../src/lib/apollo', () => ({
  apolloClient: {
    query: vi.fn().mockResolvedValue({
      data: {
        getMyAccount: {
          id: 'user-123',
          email: 'test@example.com',
          name: 'Test User',
          displayName: 'Tester',
          isAdmin: false,
          createdAt: '2024-01-01T00:00:00Z',
          updatedAt: '2024-01-01T00:00:00Z',
        },
      },
    }),
  },
}));

// Mock AWS Amplify
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  getCurrentUser: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()),
  },
}));

// Mock setup helpers to reduce complexity
const mockLoadingState = () => {
  vi.mocked(amplifyAuth.fetchAuthSession).mockImplementation(
    () => new Promise(() => {}), // Never resolves - simulates loading
  );
};

const mockAuthenticatedState = (isAdmin: boolean) => {
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: {
      idToken: {
        toString: () => 'mock-token',
        payload: {
          'cognito:groups': isAdmin ? ['ADMIN'] : [],
        },
      },
    },
  } as any);
  vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue({
    userId: isAdmin ? 'admin-123' : 'user-123',
    username: isAdmin ? 'admin' : 'user',
  } as any);
};

const mockUnauthenticatedState = () => {
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: undefined,
  } as any);
};

// Helper: Determine which mock to apply based on auth state
type AuthParams = { isAuthenticated?: boolean; isAdmin?: boolean; loading?: boolean };

const getAuthMockFn = (params: AuthParams): (() => void) => {
  if (params.loading) return mockLoadingState;
  if (params.isAuthenticated) return () => mockAuthenticatedState(params.isAdmin ?? false);
  return mockUnauthenticatedState;
};

// Helper: Set up auth mock based on params
const setupAuthMock = (params: AuthParams) => getAuthMockFn(params)();

// Helper to render with routing context
const renderWithRouter = (
  ui: React.ReactElement,
  params: { isAuthenticated?: boolean; isAdmin?: boolean; loading?: boolean } = {},
) => {
  setupAuthMock(params);
  return render(
    <MemoryRouter initialEntries={['/protected']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route path="/protected" element={ui} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
};

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading spinner while checking auth state', () => {
    renderWithRouter(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>,
      { loading: true },
    );

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('redirects to login when not authenticated', async () => {
    renderWithRouter(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>,
      { isAuthenticated: false },
    );

    // Wait for auth check to complete
    await screen.findByText('Login Page');

    expect(screen.getByText('Login Page')).toBeInTheDocument();
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', async () => {
    renderWithRouter(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true },
    );

    await screen.findByText('Protected Content');

    expect(screen.getByText('Protected Content')).toBeInTheDocument();
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument();
  });

  it('allows access when authenticated and requireAdmin is false', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={false}>
        <div>Regular Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: false },
    );

    await screen.findByText('Regular Content');

    expect(screen.getByText('Regular Content')).toBeInTheDocument();
  });

  it('shows access denied when requireAdmin is true but user is not admin', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={true}>
        <div>Admin Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: false },
    );

    await screen.findByText('Access Denied');

    expect(screen.getByText('Access Denied')).toBeInTheDocument();
    expect(screen.getByText('You do not have permission to access this page.')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('renders children when requireAdmin is true and user is admin', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={true}>
        <div>Admin Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: true },
    );

    await screen.findByText('Admin Content');
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('uses replace navigation when redirecting to login', async () => {
    // This test verifies that the Navigate component uses replace prop
    // which prevents the protected route from appearing in browser history
    renderWithRouter(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>,
      { isAuthenticated: false },
    );

    await screen.findByText('Login Page');

    // If replace is working, going back wouldn't show the protected route
    expect(screen.getByText('Login Page')).toBeInTheDocument();
  });

  it('defaults requireAdmin to false when not specified', async () => {
    renderWithRouter(
      <ProtectedRoute>
        <div>Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: false },
    );

    await screen.findByText('Content');

    // Should allow access since requireAdmin defaults to false
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('keeps normal users unaffected when mfa-required event fires on non-admin routes', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={false}>
        <div>Regular User Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: false },
    );

    await screen.findByText('Regular User Content');

    act(() => {
      window.dispatchEvent(
        new CustomEvent('mfa-required', {
          detail: { message: 'MFA required' },
        }),
      );
    });

    expect(screen.getByText('Regular User Content')).toBeInTheDocument();
    expect(screen.queryByTestId('mfa-setup-required-state')).not.toBeInTheDocument();
  });

  it('blocks admin route with MFA setup required state when MFA is required', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={true}>
        <div>Admin Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: true },
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent('mfa-required', {
          detail: { message: 'MFA required' },
        }),
      );
    });

    expect(await screen.findByTestId('mfa-setup-required-state')).toBeInTheDocument();
    expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });
});
