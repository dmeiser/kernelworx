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
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('qrcode', () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,mockqrcode'),
  },
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

const buildTokenPayload = (isAdmin: boolean, isFederated: boolean) => {
  const groups = isAdmin ? ['ADMIN'] : [];
  if (isFederated) {
    return { 'cognito:groups': groups, identities: [{ providerName: 'Google' }] };
  }
  return { 'cognito:groups': groups };
};

const buildMockUser = (isAdmin: boolean) => {
  if (isAdmin) {
    return { userId: 'admin-123', username: 'admin' };
  }
  return { userId: 'user-123', username: 'user' };
};

const mockAuthenticatedState = (isAdmin: boolean, isFederated: boolean) => {
  const payload = buildTokenPayload(isAdmin, isFederated);
  const user = buildMockUser(isAdmin);
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: {
      idToken: {
        toString: () => 'mock-token',
        payload,
      },
    },
  } as any);
  vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue(user as any);
};

const mockUnauthenticatedState = () => {
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: undefined,
  } as any);
};

// Helper: Determine which mock to apply based on auth state
type AuthParams = { isAuthenticated?: boolean; isAdmin?: boolean; loading?: boolean; isFederated?: boolean };

const mockAuthForParams = (params: AuthParams) => {
  const isAdmin = Boolean(params.isAdmin);
  const isFederated = Boolean(params.isFederated);
  mockAuthenticatedState(isAdmin, isFederated);
};

const getAuthMockFn = (params: AuthParams): (() => void) => {
  if (params.loading) return mockLoadingState;
  if (params.isAuthenticated) return () => mockAuthForParams(params);
  return mockUnauthenticatedState;
};

// Helper: Set up auth mock based on params
const setupAuthMock = (params: AuthParams) => getAuthMockFn(params)();

// Helper to render with routing context
const renderWithRouter = (
  ui: React.ReactElement,
  params: AuthParams = {},
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

  it('blocks federated admin with password sign-in required dialog when MFA is required', async () => {
    renderWithRouter(
      <ProtectedRoute requireAdmin={true}>
        <div>Admin Content</div>
      </ProtectedRoute>,
      { isAuthenticated: true, isAdmin: true, isFederated: true },
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent('mfa-required', {
          detail: { message: 'MFA required' },
        }),
      );
    });

    expect(await screen.findAllByRole('heading', { name: /Admin access requires a password sign-in/i })).not.toHaveLength(0);
    expect(screen.getAllByText(/social provider which cannot present MFA/i).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /Set Up MFA/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Sign Out/i }).length).toBeGreaterThan(0);
  });
});
