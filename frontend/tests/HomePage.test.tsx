/**
 * Tests for HomePage
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HomePage } from '../src/pages/HomePage';
import { BrowserRouter } from 'react-router-dom';
import type { Account } from '../src/types/auth';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockUseAuth = vi.fn();
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}));

const renderWithAuth = (account: Account | null = null) => {
  mockUseAuth.mockReturnValue({ account });

  return render(
    <BrowserRouter>
      <HomePage />
    </BrowserRouter>,
  );
};

describe('HomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockClear();
    mockUseAuth.mockReturnValue({ account: null });
  });

  it('renders welcome heading without a name when account is missing', async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Welcome back')).toBeInTheDocument();
    });
  });

  it('renders welcome heading with first name when givenName is available', async () => {
    renderWithAuth({
      accountId: 'account-123',
      email: 'alex@example.com',
      givenName: 'Alex',
      familyName: 'Kernel',
      isAdmin: false,
    } as Account);

    await waitFor(() => {
      expect(screen.getByText('Welcome back, Alex')).toBeInTheDocument();
    });
  });

  it('renders welcome heading with givenName when familyName is missing', async () => {
    renderWithAuth({
      accountId: 'account-123',
      email: 'alex@example.com',
      givenName: 'Alex',
      isAdmin: false,
    } as Account);

    await waitFor(() => {
      expect(screen.getByText('Welcome back, Alex')).toBeInTheDocument();
    });
  });

  it('falls back to email when name fields are missing', async () => {
    renderWithAuth({
      accountId: 'account-123',
      email: 'alex@example.com',
      isAdmin: false,
    } as Account);

    await waitFor(() => {
      expect(screen.getByText('Welcome back, alex@example.com')).toBeInTheDocument();
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

  it('navigates to /catalogs when Catalogs tile clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Catalogs')).toBeInTheDocument();
    });

    await user.click(screen.getByText('Catalogs'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/catalogs');
    });
  });

  it('navigates to /shared-campaigns when Shared Campaigns tile clicked', async () => {
    const user = userEvent.setup();
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByText('Shared Campaigns')).toBeInTheDocument();
    });

    await user.click(screen.getByText('Shared Campaigns'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/shared-campaigns');
    });
  });
});
