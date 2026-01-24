/**
 * Tests for LandingPage
 *
 * Tests rendering, login button behavior, branding compliance
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { LandingPage } from '../src/pages/LandingPage';
import { AuthProvider } from '../src/contexts/AuthContext';
import { BrowserRouter } from 'react-router-dom';
import * as amplifyAuth from 'aws-amplify/auth';

// Mock AWS Amplify
vi.mock('aws-amplify/auth', () => ({
  fetchAuthSession: vi.fn(),
  signInWithRedirect: vi.fn(),
  getCurrentUser: vi.fn(),
}));

vi.mock('aws-amplify/utils', () => ({
  Hub: {
    listen: vi.fn(() => vi.fn()),
  },
}));

// Mock useNavigate
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
        <LandingPage />
      </AuthProvider>
    </BrowserRouter>,
  );
};

describe('LandingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockClear();
  });

  it('renders the page title with correct branding', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('KernelWorx')).toBeInTheDocument();
    });

    // Check for Kaushan Script font in header
    const headerTitle = screen.getAllByText('KernelWorx')[0];
    expect(headerTitle).toHaveStyle({ fontFamily: '"Kaushan Script", cursive' });
  });

  it('renders the hero title', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Popcorn Sales Made Easy')).toBeInTheDocument();
    });
  });

  it('renders the subtitle', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(
        screen.getByText(
          'Track orders, manage sellers, and generate reports for your Scouting America popcorn fundraiser',
        ),
      ).toBeInTheDocument();
    });
  });

  it('renders all feature sections', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('🍿 Organize Your Sales')).toBeInTheDocument();
      expect(screen.getByText('🤝 Collaborate with Others')).toBeInTheDocument();
      expect(screen.getByText('📊 Generate Reports')).toBeInTheDocument();
      expect(screen.getByText('🔒 Secure & Private')).toBeInTheDocument();
    });
  });

  it('renders COPPA warning', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('⚠️ Age Requirement (COPPA Compliance)')).toBeInTheDocument();
      expect(screen.getByText(/You must be at least 13 years old to create an account/)).toBeInTheDocument();
    });
  });

  it('renders footer text', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Built with ❤️ for Scouting America volunteers')).toBeInTheDocument();
      expect(screen.getByText('Open source • MIT License • Free to use')).toBeInTheDocument();
    });
  });

  it('shows "Login" button when not authenticated', async () => {
    renderWithAuth(false);

    await waitFor(() => {
      const loginButtons = screen.getAllByRole('button', { name: /login/i });
      expect(loginButtons.length).toBeGreaterThan(0);
    });
  });

  it('shows "Go to My Scouts" button when authenticated', async () => {
    renderWithAuth(true);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /go to my scouts/i }).length).toBeGreaterThan(0);
    });
  });

  it('navigates to /login when Login button is clicked and user not authenticated', async () => {
    const user = userEvent.setup();

    renderWithAuth(false);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /login/i }).length).toBeGreaterThan(0);
    });

    const loginButton = screen.getAllByRole('button', { name: /login/i })[0];
    await user.click(loginButton);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('navigates to scouts when button clicked and user is authenticated', async () => {
    const user = userEvent.setup();

    renderWithAuth(true);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /go to my scouts/i }).length).toBeGreaterThan(0);
    });

    const buttons = screen.getAllByRole('button', { name: /go to my scouts/i });
    await user.click(buttons[0]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/scouts');
    });
  });

  it('shows "Get Started" CTA button when not authenticated', async () => {
    renderWithAuth(false);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
    });
  });

  it('shows "Go to My Scouts" CTA button when authenticated', async () => {
    renderWithAuth(true);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /go to my scouts/i }).length).toBeGreaterThan(0);
    });
  });

  it('applies correct branding to hero title', async () => {
    renderWithAuth();

    await waitFor(() => {
      const heroTitle = screen.getByText('Popcorn Sales Made Easy');
      expect(heroTitle).toHaveStyle({
        fontFamily: '"Kaushan Script", cursive',
      });
    });
  });

  it('renders logo image in header', async () => {
    renderWithAuth();

    await waitFor(() => {
      const logo = screen.getByAltText('Popcorn kernel');
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveAttribute('src', '/logo.svg');
    });
  });
});
