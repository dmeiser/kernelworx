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
import { LIST_MY_SHARED_CAMPAIGNS } from '../src/lib/graphql';

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
    useQuery: (...args: unknown[]) => mockUseQuery(...args),
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

  it('navigates to home when pressing Enter or Space on logo', async () => {
    const user = userEvent.setup();
    renderAppLayout();

    await waitFor(() => {
      expect(screen.getByAltText('KernelWorx mark')).toBeInTheDocument();
    });

    const logoBtn = screen.getByAltText('KernelWorx mark').closest('button')!;
    logoBtn.focus();
    await user.keyboard('{Enter}');
    expect(mockNavigate).toHaveBeenCalledWith('/home');

    mockNavigate.mockClear();
    await user.keyboard(' ');
    expect(mockNavigate).toHaveBeenCalledWith('/home');

    mockNavigate.mockClear();
    await user.keyboard('{Escape}');
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('renders givenName only or email if familyName is missing', async () => {
    mockUseAuth.mockReturnValue({
      account: {
        accountId: 'ACCOUNT#123',
        email: 'test@example.com',
        givenName: 'Test',
        familyName: undefined,
        isAdmin: false,
      } as Account,
      logout: mockLogout,
      isAdmin: false,
    });
    mockUseQuery.mockReturnValue({ data: { listMySharedCampaigns: [] }, loading: false });

    render(
      <BrowserRouter>
        <AppLayout>
          <div>Content</div>
        </AppLayout>
      </BrowserRouter>,
    );

    expect(screen.getByText('Test')).toBeInTheDocument();
  });

  it('renders email when givenName and familyName are missing', async () => {
    mockUseAuth.mockReturnValue({
      account: {
        accountId: 'ACCOUNT#123',
        email: 'onlyemail@example.com',
        givenName: '',
        familyName: undefined,
        isAdmin: false,
      } as Account,
      logout: mockLogout,
      isAdmin: false,
    });
    mockUseQuery.mockReturnValue({ data: undefined, loading: false });

    render(
      <BrowserRouter>
        <AppLayout>
          <div>Content</div>
        </AppLayout>
      </BrowserRouter>,
    );

    expect(screen.getByText('onlyemail@example.com')).toBeInTheDocument();
  });

  it('handles null account displayName gracefully', async () => {
    mockUseAuth.mockReturnValue({
      account: null,
      logout: mockLogout,
      isAdmin: false,
    });
    mockUseQuery.mockReturnValue({ data: { listMySharedCampaigns: [] }, loading: false });

    render(
      <BrowserRouter>
        <AppLayout>
          <div data-testid="page-content">Content</div>
        </AppLayout>
      </BrowserRouter>,
    );

    expect(screen.getByTestId('page-content')).toBeInTheDocument();
  });

  it('renders and navigates other mobile drawer items including reports and admin', async () => {
    isDesktop = false;
    mockUseAuth.mockReturnValue({
      account: {
        accountId: 'ACCOUNT#123',
        email: 'test@example.com',
        givenName: 'Test',
        familyName: 'Admin',
        isAdmin: true,
      } as Account,
      logout: mockLogout,
      isAdmin: true,
    });
    mockUseQuery.mockReturnValue({
      data: { listMySharedCampaigns: [{ sharedCampaignCode: 'code-1', isActive: true }] },
      loading: false,
    });

    render(
      <BrowserRouter>
        <AppLayout>
          <div>Content</div>
        </AppLayout>
      </BrowserRouter>,
    );

    const user = userEvent.setup();
    const openBtn = screen.getByRole('button', { name: /open drawer/i });

    await user.click(openBtn);
    expect(screen.getByText('Campaign Reports')).toBeInTheDocument();
    expect(screen.getByText('Admin Console')).toBeInTheDocument();

    await user.click(screen.getByText('Campaign Reports'));
    expect(mockNavigate).toHaveBeenCalledWith('/campaign-reports');

    await user.click(openBtn);
    await user.click(screen.getByText('Admin Console'));
    expect(mockNavigate).toHaveBeenCalledWith('/admin');

    await user.click(openBtn);
    await user.click(screen.getByText('Catalogs'));
    expect(mockNavigate).toHaveBeenCalledWith('/catalogs');

    await user.click(openBtn);
    await user.click(screen.getByText('Payment Methods'));
    expect(mockNavigate).toHaveBeenCalledWith('/payment-methods');

    await user.click(openBtn);
    await user.click(screen.getByText('Shared Campaigns'));
    expect(mockNavigate).toHaveBeenCalledWith('/shared-campaigns');

    await user.click(openBtn);
    await user.click(screen.getByText('Accept Invite'));
    expect(mockNavigate).toHaveBeenCalledWith('/accept-invite');

    await user.click(openBtn);
    await user.click(screen.getByText('Settings'));
    expect(mockNavigate).toHaveBeenCalledWith('/settings');

    await user.click(openBtn);
    await user.click(screen.getByText('Home'));
    expect(mockNavigate).toHaveBeenCalledWith('/home');
  });

  it('queries shared campaigns with cache-first fetch policy', () => {
    renderAppLayout();

    expect(mockUseQuery).toHaveBeenCalledWith(
      LIST_MY_SHARED_CAMPAIGNS,
      expect.objectContaining({
        fetchPolicy: 'cache-first',
      }),
    );
  });
});
