/**
 * Tests for AppLayout component
 *
 * Covers rendering, responsive navigation, and mobile drawer behavior.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppLayout } from '../src/components/AppLayout';
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

const mockUseQuery = vi.fn();
vi.mock('@apollo/client/react', async () => {
  const actual = await vi.importActual('@apollo/client/react');
  return {
    ...actual,
    useQuery: () => mockUseQuery(),
  };
});

let isDesktop = true;
const mockUseMediaQuery = vi.fn((_query: unknown) => isDesktop);
vi.mock('@mui/material', async () => {
  const actual = await vi.importActual('@mui/material');
  return {
    ...actual,
    useMediaQuery: (query: unknown) => mockUseMediaQuery(query),
  };
});

const mockLogout = vi.fn();

const renderAppLayout = (desktop = true, admin = false) => {
  isDesktop = desktop;
  mockUseAuth.mockReturnValue({
    account: {
      accountId: 'ACCOUNT#123',
      email: 'test@example.com',
      givenName: 'Test',
      familyName: 'User',
      isAdmin: admin,
    } as Account,
    logout: mockLogout,
    isAdmin: admin,
  });
  mockUseQuery.mockReturnValue({ data: { listMySharedCampaigns: [] }, loading: false });

  return render(
    <BrowserRouter>
      <AppLayout>
        <div data-testid="page-content">Page content</div>
      </AppLayout>
    </BrowserRouter>,
  );
};

describe('AppLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogout.mockClear();
    mockNavigate.mockClear();
  });

  it('renders the app bar with logo and page content', async () => {
    renderAppLayout();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });
    expect(screen.getByText('Kernel')).toBeInTheDocument();
    expect(screen.getByText('Worx')).toBeInTheDocument();
    expect(screen.getByTestId('page-content')).toBeInTheDocument();
  });

  it('renders desktop navigation items when on desktop', async () => {
    renderAppLayout(true);

    await waitFor(() => {
      expect(screen.getByText('Home')).toBeInTheDocument();
    });
    expect(screen.getByText('My Scouts')).toBeInTheDocument();
    expect(screen.getByText('Catalogs')).toBeInTheDocument();
    expect(screen.getByText('Payment Methods')).toBeInTheDocument();
    expect(screen.getByText('Shared Campaigns')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('renders admin navigation item for admin users', async () => {
    renderAppLayout(true, true);

    await waitFor(() => {
      expect(screen.getByText('Admin Console')).toBeInTheDocument();
    });
  });

  it('does not render admin navigation item for non-admin users', async () => {
    renderAppLayout(true, false);

    await waitFor(() => {
      expect(screen.getByText('Home')).toBeInTheDocument();
    });
    expect(screen.queryByText('Admin Console')).not.toBeInTheDocument();
  });

  it('navigates to home when logo is clicked', async () => {
    const user = userEvent.setup();
    renderAppLayout();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    await user.click(screen.getByAltText('KernelWorx mark'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/home');
    });
  });

  it('navigates when a desktop nav item is clicked', async () => {
    const user = userEvent.setup();
    renderAppLayout();

    await waitFor(() => {
      expect(screen.getByText('My Scouts')).toBeInTheDocument();
    });

    await user.click(screen.getByText('My Scouts'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/scouts');
    });
  });

  it('calls logout when app bar sign out button is clicked', async () => {
    const user = userEvent.setup();
    renderAppLayout();

    await waitFor(() => {
      expect(screen.queryAllByRole('button', { name: /sign out/i }).length).toBeGreaterThan(0);
    });

    const signOutButtons = screen.getAllByRole('button', { name: /sign out/i });
    await user.click(signOutButtons[0]);

    await waitFor(() => {
      expect(mockLogout).toHaveBeenCalled();
    });
  });

  it('renders mobile menu button and opens drawer on mobile', async () => {
    const user = userEvent.setup();
    renderAppLayout(false);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /open drawer/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /open drawer/i }));

    await waitFor(() => {
      expect(screen.getByText('Home')).toBeInTheDocument();
      expect(screen.getByText('My Scouts')).toBeInTheDocument();
    });
  });

  it('closes mobile drawer after navigation', async () => {
    const user = userEvent.setup();
    renderAppLayout(false);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /open drawer/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /open drawer/i }));

    await waitFor(() => {
      expect(screen.getByText('My Scouts')).toBeInTheDocument();
    });

    await user.click(screen.getByText('My Scouts'));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/scouts');
      expect(screen.queryByRole('presentation')).not.toBeInTheDocument();
    });
  });
});
