import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LoginPage } from '../src/pages/LoginPage';
import { useAuth } from '../src/contexts/AuthContext';
import { signInWithRedirect } from 'aws-amplify/auth';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}));

vi.mock('aws-amplify/auth', () => ({
  signIn: vi.fn(),
  confirmSignIn: vi.fn(),
  signInWithRedirect: vi.fn(),
}));

describe('LoginPage redirect preservation', () => {
  const mockLoginWithPassword = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: false,
      isAdmin: false,
      loading: false,
      loginWithPassword: mockLoginWithPassword,
      logout: vi.fn(),
      refreshSession: vi.fn(),
      account: null,
    } as any);
  });

  it('redirects to preserved target including query string if already authenticated', async () => {
    vi.mocked(useAuth).mockReturnValue({
      isAuthenticated: true,
      isAdmin: false,
      loading: false,
      loginWithPassword: mockLoginWithPassword,
      logout: vi.fn(),
      refreshSession: vi.fn(),
      account: null,
    } as any);

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: { pathname: '/campaigns', search: '?tab=active&sort=desc' } },
          },
        ]}
      >
        <LoginPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/campaigns?tab=active&sort=desc', { replace: true });
    });
  });

  it('navigates to preserved target including query string on successful password login', async () => {
    mockLoginWithPassword.mockResolvedValue({ isSignedIn: true });

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: { pathname: '/orders', search: '?page=2&status=pending' } },
          },
        ]}
      >
        <LoginPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'Secret123!' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign In$/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/orders?page=2&status=pending', { replace: true });
    });
  });

  it('saves preserved target including query string to sessionStorage when initiating social login', async () => {
    vi.mocked(signInWithRedirect).mockResolvedValue();

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: { pathname: '/scouts', search: '?view=detail&id=42' } },
          },
        ]}
      >
        <LoginPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /Continue with Google/i }));

    await waitFor(() => {
      expect(sessionStorage.getItem('oauth_redirect')).toBe('/scouts?view=detail&id=42');
      expect(signInWithRedirect).toHaveBeenCalledWith({ provider: 'Google' });
    });
  });

  it('handles string from in location state and preserves query string', async () => {
    vi.mocked(signInWithRedirect).mockResolvedValue();

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: '/campaigns/create?type=shared' },
          },
        ]}
      >
        <LoginPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /Continue with Google/i }));

    await waitFor(() => {
      expect(sessionStorage.getItem('oauth_redirect')).toBe('/campaigns/create?type=shared');
    });
  });

  it('falls back to /home when no location state is provided', async () => {
    mockLoginWithPassword.mockResolvedValue({ isSignedIn: true });

    render(
      <MemoryRouter initialEntries={['/login']}>
        <LoginPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: 'Secret123!' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign In$/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/home', { replace: true });
    });
  });
});
