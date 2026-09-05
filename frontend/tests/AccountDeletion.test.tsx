/**
 * Account Deletion Component and Hook Tests
 *
 * Verifies:
 * - Stepped deletion of profiles followed by account
 * - Preservation of catalogs (never deleted)
 * - Error reporting and resumption support
 * - Idempotent handling of already-deleted profiles
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { DeleteAccountSection } from '../src/components/settings/DeleteAccountSection';
import { LIST_MY_PROFILES, DELETE_SELLER_PROFILE, DELETE_MY_ACCOUNT } from '../src/lib/graphql';

describe('DeleteAccountSection & AccountDeletionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const createListProfilesMock = () => ({
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
              profileId: 'PROFILE#scout-1',
              sellerName: 'Scout Alex',
              ownerAccountId: 'ACCOUNT#user-1',
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
              isOwner: true,
              permissions: [],
              latestCampaign: null,
            },
            {
              __typename: 'SellerProfile',
              profileId: 'PROFILE#scout-2',
              sellerName: 'Scout Ben',
              ownerAccountId: 'ACCOUNT#user-1',
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
  });

  const createDeleteProfileMock = (profileId: string, error?: string) => {
    if (error) {
      return {
        request: {
          query: DELETE_SELLER_PROFILE,
          variables: { profileId },
        },
        result: {
          errors: [new GraphQLError(error)],
        },
      };
    }
    return {
      request: {
        query: DELETE_SELLER_PROFILE,
        variables: { profileId },
      },
      result: {
        data: {
          deleteSellerProfile: true,
        },
      },
    };
  };

  const createDeleteAccountMock = () => ({
    request: {
      query: DELETE_MY_ACCOUNT,
    },
    result: {
      data: {
        deleteMyAccount: true,
      },
    },
  });

  test('renders warning and notes that catalogs are preserved', () => {
    render(
      <MockedProvider>
        <DeleteAccountSection userEmail="scoutparent@example.com" />
      </MockedProvider>
    );

    expect(screen.getByText('Delete Account')).toBeInTheDocument();
    expect(screen.getByText(/Custom catalogs/i)).toBeInTheDocument();
    expect(screen.getByText(/Catalogs you created will be preserved and never deleted/i)).toBeInTheDocument();
  });

  test('opens dialog and completes stepped deletion successfully', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          createDeleteProfileMock('PROFILE#scout-1'),
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    // Open dialog
    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));

    expect(screen.getByText('Confirm Account Deletion')).toBeInTheDocument();
    expect(screen.getByText(/Custom catalogs you created are preserved/i)).toBeInTheDocument();

    const deleteButton = screen.getByRole('button', { name: 'Delete Account' });
    expect(deleteButton).toBeDisabled();

    // Type confirmation
    const confirmInput = screen.getByPlaceholderText('Type DELETE to confirm');
    await user.type(confirmInput, 'DELETE');
    expect(deleteButton).toBeEnabled();

    // Start deletion
    await user.click(deleteButton);

    // Should transition to progress view and show profile statuses
    await waitFor(() => {
      expect(screen.getByText('Discover account profiles')).toBeInTheDocument();
    });

    // Both profiles and account deletion complete
    await waitFor(() => {
      expect(onAccountDeleted).toHaveBeenCalledTimes(1);
    });
  });

  test('notifies user on error and allows resuming deletion', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const failingMock = createDeleteProfileMock('PROFILE#scout-1', 'Temporary DynamoDB error');
    const retryMock = createDeleteProfileMock('PROFILE#scout-1');

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          failingMock,
          retryMock,
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    // Open and confirm
    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    // Wait for failure
    await waitFor(() => {
      expect(screen.getByText('Deletion Interrupted')).toBeInTheDocument();
      expect(screen.getAllByText(/Temporary DynamoDB error/i).length).toBeGreaterThan(0);
    });

    // Verify Resume Deletion button is visible
    const resumeButton = screen.getByRole('button', { name: /Resume Deletion/i });
    expect(resumeButton).toBeInTheDocument();

    // Click resume
    await user.click(resumeButton);

    // Deletion should resume and succeed
    await waitFor(() => {
      expect(onAccountDeleted).toHaveBeenCalledTimes(1);
    });
  });

  test('treats already-deleted profile (not found) as completed', async () => {
    const user = userEvent.setup();
    const onAccountDeleted = vi.fn().mockResolvedValue(undefined);

    const notFoundMock = createDeleteProfileMock('PROFILE#scout-1', 'Profile PROFILE#scout-1 not found');

    render(
      <MockedProvider
        mocks={[
          createListProfilesMock(),
          notFoundMock,
          createDeleteProfileMock('PROFILE#scout-2'),
          createDeleteAccountMock(),
        ]}
      >
        <DeleteAccountSection userEmail="scoutparent@example.com" onAccountDeleted={onAccountDeleted} />
      </MockedProvider>
    );

    await user.click(screen.getByRole('button', { name: /Delete My Account/i }));
    await user.type(screen.getByPlaceholderText('Type DELETE to confirm'), 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete Account' }));

    // Should not stop on "not found" error, instead proceeding through scout 2 and account delete
    await waitFor(() => {
      expect(onAccountDeleted).toHaveBeenCalledTimes(1);
    });
  });
});
