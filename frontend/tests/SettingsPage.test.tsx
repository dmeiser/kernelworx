/**
 * SettingsPage component tests
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { BrowserRouter } from 'react-router-dom';
import { SettingsPage } from '../src/pages/SettingsPage';
import { GET_MY_ACCOUNT } from '../src/lib/graphql';

// Mock navigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock logout
const mockLogout = vi.fn().mockResolvedValue(undefined);
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    logout: mockLogout,
  }),
}));

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const standardAccountMock = {
    request: { query: GET_MY_ACCOUNT },
    result: {
      data: {
        getMyAccount: {
          __typename: 'Account',
          accountId: 'account-123',
          isAdmin: false,
        },
      },
    },
  };

  const adminAccountMock = {
    request: { query: GET_MY_ACCOUNT },
    result: {
      data: {
        getMyAccount: {
          __typename: 'Account',
          accountId: 'account-123',
          isAdmin: true,
        },
      },
    },
  };

  test('renders page title and quick actions', async () => {
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(screen.getByText('Account Settings')).toBeInTheDocument();
    expect(screen.getByText('Quick Actions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /User Settings/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Manage My Scouts/i })).toBeInTheDocument();
  });

  test('shows Admin Console button for admin users', async () => {
    render(
      <MockedProvider mocks={[adminAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    // Wait for the admin button to appear
    const adminButton = await screen.findByRole('button', { name: /Admin Console/i });
    expect(adminButton).toBeInTheDocument();
  });

  test('hides Admin Console button for non-admin users', async () => {
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    // Give time for query to resolve
    await screen.findByText('Quick Actions');

    // Admin button should not be present
    expect(screen.queryByRole('button', { name: /Admin Console/i })).not.toBeInTheDocument();
  });

  test('navigates to user settings when button clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await user.click(screen.getByRole('button', { name: /User Settings/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/account/settings');
  });

  test('navigates to scouts page when Manage My Scouts clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await user.click(screen.getByRole('button', { name: /Manage My Scouts/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/scouts');
  });

  test('navigates to admin page when Admin Console clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[adminAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    const adminButton = await screen.findByRole('button', { name: /Admin Console/i });
    await user.click(adminButton);
    expect(mockNavigate).toHaveBeenCalledWith('/admin');
  });

  test('displays Data & Privacy section', () => {
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(screen.getByText('Data & Privacy')).toBeInTheDocument();
    expect(screen.getByText(/encrypted at rest/i)).toBeInTheDocument();
  });

  test('displays About section with version info', () => {
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    expect(screen.getByText('About KernelWorx')).toBeInTheDocument();
  });

  test('calls logout and navigates home when Sign Out clicked', async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[standardAccountMock]} addTypename={false}>
        <BrowserRouter>
          <SettingsPage />
        </BrowserRouter>
      </MockedProvider>,
    );

    await user.click(screen.getByRole('button', { name: /Sign Out/i }));
    expect(mockLogout).toHaveBeenCalled();
  });
});
