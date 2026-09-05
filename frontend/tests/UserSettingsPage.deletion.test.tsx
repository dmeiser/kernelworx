/**
 * UserSettingsPage Account Deletion Integration Tests
 *
 * Exercises the end-to-end happy path flow on UserSettingsPage:
 * - Navigates to user settings and displays account info
 * - Opens account deletion confirmation modal
 * - Previews seller profiles to be deleted
 * - Confirms deletion by typing DELETE
 * - Follows stepped deletion progress (profiles, then credentials & payment methods)
 * - Verifies user logout and redirect to home page
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { UserSettingsPage } from '../src/pages/UserSettingsPage';
import {
  GET_MY_ACCOUNT,
  LIST_MY_PROFILES,
  DELETE_SELLER_PROFILE,
  DELETE_MY_ACCOUNT,
} from '../src/lib/graphql';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockLogout = vi.fn().mockResolvedValue(undefined);
vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    logout: mockLogout,
    account: { isAdmin: false },
    isAuthenticated: true,
  }),
}));

vi.mock('aws-amplify/auth', () => ({
  fetchMFAPreference: vi.fn().mockResolvedValue({ enabled: [], preferred: undefined }),
  listWebAuthnCredentials: vi.fn().mockResolvedValue({ credentials: [] }),
  setUpTOTP: vi.fn(),
  verifyTOTPSetup: vi.fn(),
  updateMFAPreference: vi.fn(),
  deleteWebAuthnCredential: vi.fn(),
}));

describe('UserSettingsPage - Account Deletion Happy Path', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const getMyAccountMock = {
    request: {
      query: GET_MY_ACCOUNT,
    },
    result: {
      data: {
        getMyAccount: {
          __typename: 'Account',
          accountId: 'ACCOUNT#test-user-1',
          email: 'happy-path-owner@example.com',
          givenName: 'Happy',
          familyName: 'User',
          city: 'Austin',
          state: 'TX',
          unitType: 'PACK',
          unitNumber: 123,
          isAdmin: false,
          preferences: null,
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:00:00Z',
        },
      },
    },
  };

  const listProfilesMock = {
    request: {
      query: LIST_MY_PROFILES,
      variables: {},
    },
    result: {
      data: {
        listMyProfiles: {
          __typename: 'SellerProfileConnection',
          profiles: [
            {
              __typename: 'SellerProfile',
              profileId: 'PROFILE#scout-alpha',
              sellerName: 'Scout Alpha',
              ownerAccountId: 'ACCOUNT#test-user-1',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
              latestCampaign: null,
            },
            {
              __typename: 'SellerProfile',
              profileId: 'PROFILE#scout-beta',
              sellerName: 'Scout Beta',
              ownerAccountId: 'ACCOUNT#test-user-1',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
              latestCampaign: null,
            },
          ],
          nextToken: null,
        },
      },
    },
  };

  const deleteScoutAlphaMock = {
    request: {
      query: DELETE_SELLER_PROFILE,
      variables: { profileId: 'PROFILE#scout-alpha' },
    },
    result: {
      data: {
        deleteSellerProfile: true,
      },
    },
  };

  const deleteScoutBetaMock = {
    request: {
      query: DELETE_SELLER_PROFILE,
      variables: { profileId: 'PROFILE#scout-beta' },
    },
    result: {
      data: {
        deleteSellerProfile: true,
      },
    },
  };

  const deleteMyAccountMock = {
    request: {
      query: DELETE_MY_ACCOUNT,
    },
    result: {
      data: {
        deleteMyAccount: true,
      },
    },
  };

  test('completes full stepped deletion flow, logs out, and redirects to home', async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider
        mocks={[
          getMyAccountMock,
          listProfilesMock,
          deleteScoutAlphaMock,
          deleteScoutBetaMock,
          deleteMyAccountMock,
        ]}
      >
        <MemoryRouter>
          <UserSettingsPage />
        </MemoryRouter>
      </MockedProvider>
    );

    // Verify user settings page loads
    await waitFor(() => {
      expect(screen.getByText('User Settings')).toBeInTheDocument();
      expect(screen.getByText('happy-path-owner@example.com')).toBeInTheDocument();
    });

    // Delete account section is visible
    const deleteBtn = screen.getByRole('button', { name: /Delete My Account/i });
    expect(deleteBtn).toBeInTheDocument();

    // Click Delete My Account to open dialog
    await user.click(deleteBtn);

    // Confirmation dialog appears with profile preview
    expect(screen.getByText('Confirm Account Deletion')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Seller profiles to be deleted (2):')).toBeInTheDocument();
      expect(screen.getByText('Scout Alpha')).toBeInTheDocument();
      expect(screen.getByText('Scout Beta')).toBeInTheDocument();
    });

    // Verify catalog preservation copy and payment method warning
    expect(screen.getByText(/Custom catalogs you created are preserved/i)).toBeInTheDocument();

    // Confirm button is initially disabled
    const confirmBtn = screen.getByRole('button', { name: 'Delete Account' });
    expect(confirmBtn).toBeDisabled();

    // Enter confirmation code
    const confirmInput = screen.getByPlaceholderText('Type DELETE to confirm');
    await user.type(confirmInput, 'DELETE');
    expect(confirmBtn).toBeEnabled();

    // Execute deletion
    await user.click(confirmBtn);

    // Progress checklist appears
    await waitFor(() => {
      expect(screen.getByText('Discover account profiles')).toBeInTheDocument();
      expect(screen.getByText('Found 2 seller profile(s)')).toBeInTheDocument();
      expect(screen.getByText('Profile 1: Scout Alpha')).toBeInTheDocument();
      expect(screen.getByText('Profile 2: Scout Beta')).toBeInTheDocument();
      expect(screen.getByText('Account, payment methods & credentials')).toBeInTheDocument();
    });

    // Deletion completes, showing success banner, calling logout, and navigating to '/'
    await waitFor(() => {
      expect(screen.getByText('Account Deleted')).toBeInTheDocument();
      expect(mockLogout).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });
});
