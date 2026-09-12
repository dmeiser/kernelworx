import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { UserDataPage } from '../src/pages/UserDataPage';
import {
  ADMIN_GET_USER_PROFILES,
  ADMIN_GET_USER_CATALOGS,
  ADMIN_GET_USER_CAMPAIGNS,
  ADMIN_GET_USER_SHARED_CAMPAIGNS,
} from '../src/lib/graphql';

describe('UserDataPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const accountId = 'user-123';

  const defaultMocks = [
    {
      request: {
        query: ADMIN_GET_USER_PROFILES,
        variables: { accountId },
      },
      result: {
        data: { adminGetUserProfiles: [] },
      },
    },
    {
      request: {
        query: ADMIN_GET_USER_CATALOGS,
        variables: { accountId },
      },
      result: {
        data: { adminGetUserCatalogs: [] },
      },
    },
    {
      request: {
        query: ADMIN_GET_USER_CAMPAIGNS,
        variables: { accountId },
      },
      result: {
        data: { adminGetUserCampaigns: [] },
      },
    },
    {
      request: {
        query: ADMIN_GET_USER_SHARED_CAMPAIGNS,
        variables: { accountId },
      },
      result: {
        data: { adminGetUserSharedCampaigns: [] },
      },
    },
  ];

  test('renders user data page initially', async () => {
    render(
      <MockedProvider mocks={defaultMocks}>
        <MemoryRouter initialEntries={[`/admin/user-data/${accountId}`]}>
          <Routes>
            <Route path="/admin/user-data/:accountId" element={<UserDataPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/User Data:/i)).toBeInTheDocument();
    });
  });

  test('shows MFA setup required state when profiles query returns MFA required error', async () => {
    const errorMocks = [
      {
        request: {
          query: ADMIN_GET_USER_PROFILES,
          variables: { accountId },
        },
        error: new Error('MFA required'),
      },
      ...defaultMocks.slice(1),
    ];

    render(
      <MockedProvider mocks={errorMocks}>
        <MemoryRouter initialEntries={[`/admin/user-data/${accountId}`]}>
          <Routes>
            <Route path="/admin/user-data/:accountId" element={<UserDataPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
      expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    });
  });

  test('gracefully degrades to MFA setup required state when mfa-required event fires', async () => {
    render(
      <MockedProvider mocks={defaultMocks}>
        <MemoryRouter initialEntries={[`/admin/user-data/${accountId}`]}>
          <Routes>
            <Route path="/admin/user-data/:accountId" element={<UserDataPage />} />
          </Routes>
        </MemoryRouter>
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/User Data:/i)).toBeInTheDocument();
    });

    window.dispatchEvent(
      new CustomEvent('mfa-required', {
        detail: { message: 'MFA required' },
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('mfa-setup-required-state')).toBeInTheDocument();
      expect(screen.getByText('MFA Setup Required')).toBeInTheDocument();
    });
  });
});
