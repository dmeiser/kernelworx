/**
 * Tests for HomePage
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { HomePage } from '../src/pages/HomePage';
import { AuthProvider } from '../src/contexts/AuthContext';
import { BrowserRouter } from 'react-router-dom';
import * as amplifyAuth from 'aws-amplify/auth';

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

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const renderWithAuth = (account = null) => {
  vi.mocked(amplifyAuth.fetchAuthSession).mockResolvedValue({
    tokens: { idToken: { toString: () => 'mock-token' } },
  } as any);

  vi.mocked(amplifyAuth.getCurrentUser).mockResolvedValue({
    userId: 'user-123',
    username: 'testuser',
  } as any);

  return render(
    <BrowserRouter>
      <AuthProvider>
        <HomePage />
      </AuthProvider>
    </BrowserRouter>,
  );
};

describe('HomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockClear();
  });

  it('renders welcome heading', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText(/welcome back/i)).toBeInTheDocument();
    });
  });

  it('renders news and updates section', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('News & Updates')).toBeInTheDocument();
    });
  });

  it('renders quick action tiles', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('My Scouts')).toBeInTheDocument();
      expect(screen.getByText('Payment Methods')).toBeInTheDocument();
      expect(screen.getByText('Catalogs')).toBeInTheDocument();
      expect(screen.getByText('Shared Campaigns')).toBeInTheDocument();
    });
  });

  it('navigates to /scouts when My Scouts tile clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('My Scouts')).toBeInTheDocument();
    });

    await user.click(screen.getByText('My Scouts'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/scouts');
    });
  });

  it('navigates to /payment-methods when Payment Methods tile clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Payment Methods')).toBeInTheDocument();
    });

    await user.click(screen.getByText('Payment Methods'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/payment-methods');
    });
  });
});
