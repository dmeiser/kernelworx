/**
 * Tests for LandingPage
 *
 * Tests rendering, login button behavior, and brand compliance.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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

  it('renders the brand wordmark', async () => {
    renderWithAuth();
    await waitFor(() => {
      expect(screen.getAllByText(/KernelWorx/i).length).toBeGreaterThan(0);
    });
  });

  it('renders the hero heading', async () => {
    renderWithAuth();
    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: /Use it on your own/i }),
      ).toBeInTheDocument();
    });
  });

  it('renders the hero dashboard preview', async () => {
    renderWithAuth();
    await waitFor(() => {
      const preview = screen.getByAltText('KernelWorx dashboard preview');
      expect(preview).toBeInTheDocument();
      expect(preview).toHaveAttribute('src', '/marketing/home-page.png');
    });
  });

  it('shows "Get started" CTA when not authenticated', async () => {
    renderWithAuth(false);
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /get started/i }).length).toBeGreaterThan(0);
    });
  });

  it('shows "Go to Dashboard" CTA when authenticated', async () => {
    renderWithAuth(true);
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /go to dashboard/i }).length).toBeGreaterThan(0);
    });
  });

  it('navigates to /login when Get started is clicked and user is not authenticated', async () => {
    const user = userEvent.setup();
    renderWithAuth(false);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /get started/i }).length).toBeGreaterThan(0);
    });

    await user.click(screen.getAllByRole('button', { name: /get started/i })[0]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login');
    });
  });

  it('navigates to /home when Go to Dashboard is clicked and user is authenticated', async () => {
    const user = userEvent.setup();
    renderWithAuth(true);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /go to dashboard/i }).length).toBeGreaterThan(0);
    });

    const buttons = screen.getAllByRole('button', { name: /go to dashboard/i });
    await user.click(buttons[0]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });
  });

  it('renders FAQ accordion', async () => {
    renderWithAuth();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /What is KernelWorx\?/i })).toBeInTheDocument();
    });
  });

  it('renders footer links', async () => {
    renderWithAuth();
    await waitFor(() => {
      const footer = screen.getByRole('contentinfo');
      expect(within(footer).getByRole('link', { name: /privacy/i })).toBeInTheDocument();
      expect(within(footer).getByRole('link', { name: /our story/i })).toBeInTheDocument();
      expect(within(footer).getByRole('link', { name: /sponsor/i })).toHaveAttribute(
        'href',
        'https://github.com/sponsors/dmeiser',
      );
    });
  });

  it('renders feature sections', async () => {
    renderWithAuth();
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Organize your sellers/i })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /Share with your unit/i })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /Flexible payments/i })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /Run reports/i })).toBeInTheDocument();
    });
  });
});
