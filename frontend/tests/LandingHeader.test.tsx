import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LandingHeader } from '../src/components/LandingHeader';
import { AuthProvider } from '../src/contexts/AuthContext';
import { BrowserRouter } from 'react-router-dom';
import * as amplifyAuth from 'aws-amplify/auth';

vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  getCurrentUser: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()),
  },
}));

vi.mock('@mui/material', async () => {
  const actual = await vi.importActual('@mui/material');
  return {
    ...actual,
    useMediaQuery: vi.fn(() => true),
  };
});

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const renderWithAuth = (isAuthenticated = false) => {
  if (isAuthenticated) {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: { idToken: { toString: () => 'mock-token' } },
    } as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue({
      userId: 'user-123',
      username: 'testuser',
    } as any);
  } else {
    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: undefined,
    } as any);
  }

  return render(
    <BrowserRouter>
      <AuthProvider>
        <LandingHeader />
      </AuthProvider>
    </BrowserRouter>,
  );
};

describe('LandingHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockClear();
  });

  it('navigates to home when logo is clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    const logo = screen.getByAltText('KernelWorx mark');
    await user.click(logo);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });

  it('navigates to login when unauthenticated CTA is clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth(false);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('navigates to home when authenticated CTA is clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth(true);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /dashboard/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /dashboard/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });
  });

  it('navigates to home when logo is activated with Enter', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    const logoButton = screen.getByAltText('KernelWorx mark').closest('button');
    expect(logoButton).toBeTruthy();
    (logoButton as HTMLElement).focus();
    await user.keyboard('{Enter}');

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });

  it('navigates to home when logo is activated with Space', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    const logoButton = screen.getByAltText('KernelWorx mark').closest('button');
    expect(logoButton).toBeTruthy();
    fireEvent.keyDown(logoButton as HTMLElement, { key: ' ', code: 'Space' });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });

  it('does not navigate when a non-activation key is pressed on the logo', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    const logoButton = screen.getByAltText('KernelWorx mark').closest('button');
    expect(logoButton).toBeTruthy();
    fireEvent.keyDown(logoButton as HTMLElement, { key: 'Tab', code: 'Tab' });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('navigates to login when sign in button is clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth(false);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('calls logout when sign out button is clicked', async () => {
    vi.mocked(amplifyAuth.signOut).mockResolvedValue(undefined as any);

    vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
      tokens: { idToken: { toString: () => 'mock-token' } },
    } as any);
    vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue({
      userId: 'user-123',
      username: 'testuser',
    } as any);

    const user = userEvent.setup();
    render(
      <BrowserRouter>
        <AuthProvider>
          <LandingHeader />
        </AuthProvider>
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /sign out/i }));

    await waitFor(() => {
      expect(amplifyAuth.signOut).toHaveBeenCalled();
    });
  });

  it('renders desktop navigation with anchor links on the home page', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <LandingHeader />
        </AuthProvider>
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('How it works')).toBeInTheDocument();
    });

    expect(screen.getByText('Features')).toBeInTheDocument();
    expect(screen.getByText('Our story')).toBeInTheDocument();
    expect(screen.getByText('FAQ')).toBeInTheDocument();
  });

  it('renders desktop navigation with RouterLinks on non-home pages', async () => {
    window.history.pushState({}, '', '/story');

    render(
      <BrowserRouter>
        <AuthProvider>
          <LandingHeader />
        </AuthProvider>
      </BrowserRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('How it works')).toBeInTheDocument();
    });

    expect(screen.getByText('Features')).toBeInTheDocument();
    expect(screen.getByText('Our story')).toBeInTheDocument();
    expect(screen.getByText('FAQ')).toBeInTheDocument();

    window.history.pushState({}, '', '/');
  });
});